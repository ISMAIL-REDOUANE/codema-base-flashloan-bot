"""
fork_preflight.py — Simulation de la transaction COMPLÈTE sur fork Anvil
(audit #6, correction du « preflight EVM »).

CE QUE L'ANCIEN PREFLIGHT NE FAISAIT PAS (audit confirmé) : deux
getAmountsOut sur « latest », jamais executeArbitrage, aucune vérification
des transferts / callbacks / remboursement, pas d'estimate_gas_swap, coût
gas fixe. La correction : garder les quotes comme présélection
(preflight.py, bloc fixé), puis simuler LA transaction exacte ici :

  1. fork Anvil de Base mainnet à un bloc fixé (aucun broadcast mainnet) ;
  2. déploiement du contrat MorphoFlashLoanArbitrage sur le fork ;
  3. eth_call executeArbitrage(amount) depuis le propriétaire ;
  4. eth_estimateGas de CETTE transaction exacte ;
  5. envoi simulé sur le fork (compte de test Anvil) : receipt + gas
     réellement consommé + raison de revert éventuelle.

TOUT résultat de ce module est SYNTHÉTIQUE : état forké, pas mainnet.
Un WIN ici prouve que le mécanisme s'exécute, pas qu'un profit existe
sur le marché. Aucune clé privée réelle : Anvil fournit des comptes de
test dont la clé est publique et documentée par Foundry (compte n° 0).
Aucun fond réel engagé.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

# Compte de test n° 0 d'Anvil — clé PUBLIQUE documentée par Foundry,
# utilisable uniquement sur un fork local (aucun fond réel).
ANVIL_TEST_KEY_0 = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
ANVIL_TEST_ADDR_0 = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

MORPHO_BASE = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH_BASE = "0x4200000000000000000000000000000000000006"
UNI_V2_ROUTER_BASE = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
BASESWAP_V2_ROUTER_BASE = "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86"

ARTIFACT = (Path(__file__).parent / "out" / "FlashLoanArbitrage.sol"
            / "MorphoFlashLoanArbitrage.json")


def find_anvil() -> Optional[str]:
    """Chemin d'anvil (PATH ou ~/.foundry/bin/anvil)."""
    path = shutil.which("anvil")
    if path:
        return path
    cand = Path.home() / ".foundry" / "bin" / "anvil"
    return str(cand) if cand.exists() else None


def _port_free(port: int) -> bool:
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_anvil_fork(fork_url: str, fork_block: Optional[int] = None,
                     port: int = 8545, timeout: int = 90):
    """Démarre `anvil --fork-url ... --fork-block-number ...` en arrière-plan
    et attend que le RPC réponde. Retourne le Popen (à arrêter avec
    stop_anvil). Lève RuntimeError si anvil est absent ou ne démarre pas."""
    anvil = find_anvil()
    if not anvil:
        raise RuntimeError("anvil introuvable (ni PATH ni ~/.foundry/bin)")
    if not _port_free(port):
        raise RuntimeError(f"port {port} déjà occupé — un autre anvil tourne ?")
    cmd = [anvil, "--fork-url", fork_url, "--port", str(port),
           "--silent"]
    if fork_block is not None:
        cmd += ["--fork-block-number", str(fork_block)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    import urllib.request
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("anvil s'est arrêté pendant le démarrage")
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                                  "method": "eth_blockNumber",
                                  "params": []}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if json.loads(resp.read().decode()).get("result"):
                    return proc
        except Exception:
            time.sleep(0.5)
    stop_anvil(proc)
    raise RuntimeError("anvil n'a pas démarré dans le délai imparti")


def stop_anvil(proc) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def load_morpho_artifact() -> dict:
    if not ARTIFACT.exists():
        raise FileNotFoundError(
            f"artefact absent : {ARTIFACT} — lancer `forge build` d'abord")
    return json.loads(ARTIFACT.read_text())


def deploy_morpho(w3, deployer: str, usdc: str, meme: str,
                  router_buy: str, router_sell: str,
                  min_profit_raw: int):
    """Déploie MorphoFlashLoanArbitrage sur le fork (le déployeur devient
    owner, donc l'appelant autorisé d'executeArbitrage)."""
    art = load_morpho_artifact()
    contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
    tx = contract.constructor(usdc, meme, router_buy, router_sell,
                              min_profit_raw).build_transaction({
        "from": deployer, "nonce": w3.eth.get_transaction_count(deployer),
        "gas": 3_000_000,
        "gasPrice": w3.eth.gas_price})
    signed = w3.eth.account.sign_transaction(tx, ANVIL_TEST_KEY_0)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt["status"] != 1 or not receipt["contractAddress"]:
        raise RuntimeError("déploiement Morpho sur fork échoué")
    return w3.eth.contract(address=receipt["contractAddress"], abi=art["abi"])


def _revert_reason(exc: Exception) -> str:
    msg = str(exc)
    # web3 renvoie « execution reverted: <raison> » ; parfois la raison
    # est l'ABI Error(string) (0x08c379a0 + offset + longueur + utf8).
    if "0x08c379a0" in msg:
        try:
            hexdata = msg.split("0x08c379a0", 1)[1]
            hexdata = "".join(c for c in hexdata if c in "0123456789abcdefABCDEF")
            raw = bytes.fromhex(hexdata)
            # Après le sélecteur : offset (32 o) + longueur (32 o) + texte.
            length = int.from_bytes(raw[32:64], "big")
            return raw[64:64 + length].decode("utf-8", "replace")
        except Exception:
            pass
    if "execution reverted" in msg:
        return msg.split("execution reverted", 1)[1].strip(" :")[:200]
    return msg[:200]


def set_balance(w3, address: str, eth: float = 10.0) -> None:
    """Donne de l'ETH à une adresse sur le fork (anvil_setBalance).
    Nécessaire pour envoyer une tx depuis un compte impersonné (ex.
    Morpho, qui détient des USDC mais 0 ETH)."""
    wei_hex = hex(int(eth * 10**18))
    w3.provider.make_request("anvil_setBalance", [address, wei_hex])


def fork_preflight(w3, contract, amount_raw: int, caller: str,
                   send_on_fork: bool = True) -> dict:
    """Simule executeArbitrage(amount) sur le fork, depuis le bon appelant
    (le propriétaire du contrat) : eth_call + estimate_gas + envoi simulé.
    Retourne un dict étiqueté synthétique — jamais un verdict mainnet."""
    fn = contract.functions.executeArbitrage(amount_raw)
    out = {"synthetic": True, "amount_raw": amount_raw,
           "contract": contract.address, "caller": caller,
           "status": None, "revert_reason": None,
           "gas_estimate": None, "gas_used": None,
           "tx_hash": None, "block": w3.eth.block_number}
    try:
        fn.call({"from": caller})
        out["call_ok"] = True
    except Exception as e:  # noqa: BLE001
        out["call_ok"] = False
        out["revert_reason"] = _revert_reason(e)
    try:
        out["gas_estimate"] = fn.estimate_gas({"from": caller})
    except Exception as e:  # noqa: BLE001
        out["gas_estimate_error"] = _revert_reason(e)
    if send_on_fork:
        try:
            tx = fn.build_transaction({
                "from": caller,
                "nonce": w3.eth.get_transaction_count(caller),
                "gas": out["gas_estimate"] or 2_000_000,
                "gasPrice": w3.eth.gas_price})
            signed = w3.eth.account.sign_transaction(tx, ANVIL_TEST_KEY_0)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            out["tx_hash"] = tx_hash.hex()
            out["gas_used"] = receipt["gasUsed"]
            out["status"] = "WIN" if receipt["status"] == 1 else "REVERT"
        except Exception as e:  # noqa: BLE001
            out["status"] = "SEND_FAILED"
            out["send_error"] = str(e)[:200]
    else:
        out["status"] = "WIN" if out.get("call_ok") else "REVERT"
    return out


def impersonate(w3, address: str) -> None:
    w3.provider.make_request("anvil_impersonateAccount", [address])


def stop_impersonate(w3, address: str) -> None:
    w3.provider.make_request("anvil_stopImpersonatingAccount", [address])


def run_fork_preflight(fork_url: str, fork_block: Optional[int] = None,
                       usdc: str = USDC_BASE, meme: str = WETH_BASE,
                       router_buy: str = UNI_V2_ROUTER_BASE,
                       router_sell: str = BASESWAP_V2_ROUTER_BASE,
                       min_profit_raw: int = 0, amount_raw: int = 100_000_000,
                       port: int = 8545) -> dict:
    """Orchestration complète (audit #6) : fork -> déploiement -> simulation
    de la transaction exacte. Ne touche jamais au mainnet. Résultat
    SYNTHÉTIQUE (état forké)."""
    from web3 import Web3
    proc = start_anvil_fork(fork_url, fork_block, port)
    try:
        w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
        contract = deploy_morpho(w3, ANVIL_TEST_ADDR_0, usdc, meme,
                                 router_buy, router_sell, min_profit_raw)
        result = fork_preflight(w3, contract, amount_raw, ANVIL_TEST_ADDR_0)
        result["fork_block"] = w3.eth.block_number
        return result
    finally:
        stop_anvil(proc)


if __name__ == "__main__":
    # Démo lecture seule sur fork (nécessite un RPC Base + anvil) :
    # python3 fork_preflight.py --fork-url <RPC> [--fork-block N]
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fork-url", required=True)
    ap.add_argument("--fork-block", type=int, default=None)
    ap.add_argument("--amount-usd", type=float, default=100.0)
    args = ap.parse_args()
    res = run_fork_preflight(args.fork_url, args.fork_block,
                             amount_raw=int(args.amount_usd * 1e6))
    print("FORK PREFLIGHT (SYNTHÉTIQUE — état forké, pas mainnet) :")
    print(json.dumps(res, indent=2, default=str))
