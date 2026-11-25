"""
preflight.py — Simulation EVM RÉELLE avant broadcast (v2, amélioration n°3).

POURQUOI : la simulation mathématique (math_engine) ne voit pas les taxes
de token, les hooks V4, les frais dynamiques Slipstream, ni un pool qui a
changé entre deux blocs. La parade, comme dans base-flash-arb-lab :
  scan -> fork replay -> PREFLIGHT eth_call -> 1 seul live send.
Le preflight, c'est un eth_call (lecture seule, 0 gas) qui demande aux
vrais routers on-chain ce que le round-trip rapporterait VRAIMENT :
  - getAmountsOut sur le router A (achat) puis sur le router B (vente),
  - eth_estimateGas pour le gas réel des 2 swaps,
  - numéro de bloc au moment de la quote (plafond de fraîcheur : > 2 blocs
    = candidat rejeté, le prix a pu bouger depuis Denim 200 ms/bloc).

RÈGLE : si le preflight dit perte OU s'il est indisponible (RPC down,
Anvil down), on NE BROADCASTE PAS. Un preflight indisponible n'est jamais
une excuse pour envoyer quand même — c'est un SKIP.

Implémentation : urllib stdlib only (eth_call / eth_estimateGas /
eth_blockNumber). Aucune clé privée, aucune transaction signée ici :
ce module ne fait QUE des lectures. Le broadcast live n'existe pas en v2.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Sélecteurs vérifiés par keccak (web3) le 2026-11-24 :
SELECTOR_GET_AMOUNTS_OUT = bytes.fromhex("d06ca61f")  # getAmountsOut(uint256,address[])
SELECTOR_GET_RESERVES = bytes.fromhex("0902f1ac")      # getReserves()
# Aerodrome : PAS d'interface V2 (vérifié sur le bytecode par l'agent fork-test,
# FORK_TEST_RESULTS.md §7.1) — getAmountsOut(address[]) et swapExactTokensForTokens
# V2 sont ABSENTS. Seul existe le Route-based :
# getAmountsOut(uint256,(address,address,bool,address)[]) = 0x5509a1ac,
# vérifié live : 1 WETH -> 1 668,17 USDC via ce sélecteur.
SELECTOR_AERO_GET_AMOUNTS_OUT = bytes.fromhex("5509a1ac")
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

MAX_BLOCK_AGE = 2          # fraîcheur : quote de plus de 2 blocs = rejetée
PUBLIC_BASE_RPC = "https://mainnet.base.org"
# Surcoût gas forfaitaire au-delà des 2 swaps (audit #6) : flash Morpho +
# callback onMorphoFlashLoan + 2 approve + remboursement. Valeur
# documentée comme ESTIMATION (pas une mesure) ; la mesure réelle vient
# du fork (fork_preflight.py) — à mettre à jour si elle diverge.
FORK_TX_OVERHEAD_GAS = 150_000


@dataclass
class PreflightResult:
    status: str            # "WIN" | "LOSE" | "STALE" | "UNAVAILABLE"
    amount_in_raw: int = 0
    amount_out_raw: int = 0
    gross_usd: float = 0.0
    net_usd: float = 0.0
    gas_units_est: int = 0
    gas_cost_usd: float = 0.0
    l1_fee_usd: float = 0.0        # audit #12 : frais L1 mesuré (0 si non mesuré)
    block_number: Optional[int] = None
    quote_source: str = ""       # ex. "getAmountsOut UniV2 + Aerodrome (on-chain)"
    reasons: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ------------------------------------------------------------------ RPC helpers
def _rpc(rpc_url: str, method: str, params, timeout: int = 15):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "codema-flashloan-bot-v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"RPC {method} error: {out['error']}")
    return out["result"]


def _addr_b32(address: str) -> bytes:
    return bytes.fromhex(address[2:].lower().rjust(64, "0"))


def _uint_b32(value: int) -> bytes:
    return int(value).to_bytes(32, "big")


def encode_get_amounts_out(amount_in: int, path: List[str]) -> bytes:
    """Calldata getAmountsOut(uint256 amountIn, address[] path)."""
    data = SELECTOR_GET_AMOUNTS_OUT + _uint_b32(amount_in) + _uint_b32(0x40)
    data += _uint_b32(len(path))
    for a in path:
        data += _addr_b32(a)
    return data


def decode_amounts_out(raw: bytes) -> List[int]:
    """Retour : (offset, length, amounts...)."""
    if len(raw) < 96:
        raise ValueError("retour getAmountsOut trop court")
    n = int.from_bytes(raw[32:64], "big")
    return [int.from_bytes(raw[64 + 32 * i:96 + 32 * i], "big") for i in range(n)]


def eth_call(rpc_url: str, to: str, data: bytes, block="latest",
             timeout: int = 15) -> bytes:
    """eth_call à un bloc FIXÉ (audit #6) : block = numéro de bloc (int)
    ou "latest". Deux quotes à deux blocs différents ne décrivent pas
    le même état — on épingle tout le preflight sur un seul bloc."""
    block_param = hex(block) if isinstance(block, int) else block
    raw_hex = _rpc(rpc_url, "eth_call",
                   [{"to": to, "data": "0x" + data.hex()}, block_param],
                   timeout)
    return bytes.fromhex(raw_hex[2:])


def get_amounts_out(rpc_url: str, router: str, amount_in: int,
                    path: List[str], timeout: int = 15,
                    block="latest") -> List[int]:
    """Quote on-chain d'un swap via le router (lecture seule, 0 gas)."""
    return decode_amounts_out(eth_call(rpc_url, router,
                                       encode_get_amounts_out(amount_in, path),
                                       block, timeout))


def encode_get_amounts_out_route(amount_in: int,
                                 routes: List[tuple]) -> bytes:
    """Calldata Aerodrome getAmountsOut(uint256, Route[]) avec
    Route = (from, to, stable, factory). Une route = 4 mots de 32 octets."""
    data = SELECTOR_AERO_GET_AMOUNTS_OUT + _uint_b32(amount_in) + _uint_b32(0x40)
    data += _uint_b32(len(routes))
    for (frm, to, stable, factory) in routes:
        data += _addr_b32(frm) + _addr_b32(to)
        data += _uint_b32(1 if stable else 0) + _addr_b32(factory)
    return data


def get_amounts_out_route(rpc_url: str, router: str, amount_in: int,
                          routes: List[tuple], timeout: int = 15,
                          block="latest") -> List[int]:
    """Quote on-chain Aerodrome (Route-based, lecture seule, 0 gas)."""
    return decode_amounts_out(eth_call(
        rpc_url, router, encode_get_amounts_out_route(amount_in, routes),
        block, timeout))


def aero_route(token_in: str, token_out: str, stable: bool = False) -> List[tuple]:
    """Une route Aerodrome volatile (stable=False) via la factory Classic."""
    return [(token_in, token_out, stable, AERODROME_FACTORY)]


def get_reserves(rpc_url: str, pair: str, timeout: int = 15,
                 block="latest") -> tuple[int, int, int]:
    """getReserves() d'une paire V2 : (reserve0, reserve1, timestamp)."""
    raw = eth_call(rpc_url, pair, SELECTOR_GET_RESERVES, block, timeout)
    return (int.from_bytes(raw[0:32], "big"),
            int.from_bytes(raw[32:64], "big"),
            int.from_bytes(raw[64:96], "big"))


def estimate_gas_swap(rpc_url: str, router: str, from_addr: str,
                      amount_in: int, path: List[str], timeout: int = 15,
                      block="latest") -> Optional[int]:
    """eth_estimateGas d'un swapExactTokensForTokens (sélecteur 0x38ed1739).
    Retourne None si l'estimation échoue (= le swap reverterait)."""
    # swapExactTokensForTokens(uint256,uint256,address[],address,uint256)
    selector = bytes.fromhex("38ed1739")
    deadline = 0xFFFFFFFF
    data = (selector + _uint_b32(amount_in) + _uint_b32(0)
            + _uint_b32(0xA0) + _addr_b32(from_addr) + _uint_b32(deadline)
            + _uint_b32(len(path)))
    for a in path:
        data += _addr_b32(a)
    try:
        params = [{"from": from_addr, "to": router,
                   "data": "0x" + data.hex()}]
        if isinstance(block, int):
            params.append(hex(block))
        res = _rpc(rpc_url, "eth_estimateGas", params, timeout)
        return int(res, 16)
    except Exception:
        return None


def get_block_number(rpc_url: str, timeout: int = 10) -> Optional[int]:
    try:
        return int(_rpc(rpc_url, "eth_blockNumber", [], timeout), 16)
    except Exception:
        return None


# ------------------------------------------------------------------ preflight
def preflight_roundtrip(rpc_url: str, loan_raw: int, token_in: str, token_mid: str,
                        token_out: str, router_buy: str, router_sell: str,
                        flash_fee_rate: float = 0.0005,
                        gas_units: int = 450_000, gas_price_gwei: float = 0.05,
                        eth_price_usd: float = 3000.0,
                        min_profit_usd: float = 3.0, gas_multiple: float = 3.0,
                        loan_usd: float = 0.0, token_out_decimals: int = 6,
                        router_buy_is_aero: bool = False,
                        router_sell_is_aero: bool = False,
                        timeout: int = 15,
                        block_number: Optional[int] = None,
                        tx_data: Optional[bytes] = None,
                        eth_price_source: str = "config") -> PreflightResult:
    """Simule le round-trip complet avec les VRAIS routers on-chain :
    token_in --router_buy--> token_mid --router_sell--> token_out.
    Les jambes Aerodrome utilisent la cotation Route-based (le router
    Aerodrome n'a PAS getAmountsOut V2 — FORK_TEST_RESULTS.md §7.1).
    loan_usd : valeur en $ du loan (pour exprimer le net en $).
    Si token_out est l'USDC (6 décimales), amount_out_raw / 1e6 = USDC récupérés.
    Ne broadcast RIEN : que des eth_call / eth_estimateGas.

    Audit #6 — CORRIGÉ :
    * les deux quotes sont épinglées sur UN SEUL bloc (block_number, ou
      le bloc courant lu une fois) — plus de « latest » qui peut changer
      entre les deux jambes ;
    * le gas reste forfaitaire ICI, avec la raison écrite : estimer un
      swap par jambe avec eth_estimateGas depuis un EOA est impossible
      pour ce flux (les jetons n'existent qu'au milieu de la transaction,
      après le flash loan — l'estimation reverterait sur solde nul). Le
      gas de CETTE transaction exacte est mesuré sur fork par
      fork_preflight.py (contrat déployé sur fork, appelant = le contrat,
      bloc fixé, eth_estimateGas + envoi simulé). Voir ce module.
    * le net est rendu en pleine précision (audit #9 : pas d'arrondi
      au centime dans une décision).
    """
    block = block_number if block_number is not None \
        else get_block_number(rpc_url, timeout)
    try:
        if router_buy_is_aero:
            amounts_buy = get_amounts_out_route(
                rpc_url, router_buy, loan_raw, aero_route(token_in, token_mid),
                timeout, block if block is not None else "latest")
        else:
            amounts_buy = get_amounts_out(rpc_url, router_buy, loan_raw,
                                          [token_in, token_mid], timeout,
                                          block if block is not None else "latest")
        mid_bought = amounts_buy[-1]
        if router_sell_is_aero:
            amounts_sell = get_amounts_out_route(
                rpc_url, router_sell, mid_bought, aero_route(token_mid, token_out),
                timeout, block if block is not None else "latest")
        else:
            amounts_sell = get_amounts_out(rpc_url, router_sell, mid_bought,
                                           [token_mid, token_out], timeout,
                                           block if block is not None else "latest")
        out_raw = amounts_sell[-1]
    except Exception as e:
        return PreflightResult(status="UNAVAILABLE", amount_in_raw=loan_raw,
                               block_number=block,
                               quote_source="getAmountsOut on-chain",
                               error=f"preflight indisponible : {type(e).__name__}: {e}",
                               reasons=["preflight indisponible -> SKIP (on n'envoie rien "
                                        "sans simulation EVM)"])
    # Gas : forfaitaire ici (voir docstring — l'estimation de la
    # transaction exacte se fait sur fork, fork_preflight.py).
    gas_note = (f"gas forfaitaire {gas_units} unités (estimation par jambe "
                "impossible hors fork : les jetons n'existent qu'après le "
                "flash loan — voir fork_preflight.py pour le gas exact)")
    out_usd = out_raw / (10 ** token_out_decimals)
    gross = out_usd - loan_usd
    flash_fee = loan_usd * flash_fee_rate
    gas_cost = gas_units * gas_price_gwei * 1e-9 * eth_price_usd
    # Frais L1 (audit #12) : si les données de la transaction exacte sont
    # fournies, on ajoute le data fee mesuré sur l'oracle. Sans tx_data,
    # le L1 n'est pas compté — la raison le dit (pas de chiffre inventé).
    l1_fee_usd = 0.0
    l1_note = "frais L1 non mesuré (tx_data non fourni)"
    if tx_data is not None:
        try:
            from gas import estimate_full_tx_cost_usd, EthPrice
            full = estimate_full_tx_cost_usd(
                rpc_url, tx_data, gas_units, gas_price_gwei,
                EthPrice(usd=eth_price_usd, source=eth_price_source),
                block if block is not None else "latest", timeout)
            l1_fee_usd = full["l1_fee_usd"]
            l1_note = (f"frais L1 mesuré (oracle) : {l1_fee_usd:.6f} $ "
                       f"(prix ETH : {eth_price_source})")
        except Exception as e:
            return PreflightResult(status="UNAVAILABLE", amount_in_raw=loan_raw,
                                   block_number=block, error="L1 fee unavailable",
                                   reasons=[f"L1 fee unavailable: {type(e).__name__}"])

    gas_cost += l1_fee_usd
    net = gross - flash_fee - gas_cost
    reasons: List[str] = [gas_note, l1_note]
    negative: List[str] = []
    if net <= 0:
        negative.append(f"net on-chain négatif ({net:.2f} $)")
    if net <= min_profit_usd:
        negative.append(f"net on-chain {net:.2f} $ <= min {min_profit_usd:.2f} $")
    if net <= gas_cost * gas_multiple:
        negative.append(f"net {net:.2f} $ <= gas x {gas_multiple} ({gas_cost * gas_multiple:.2f} $)")
    reasons += negative
    status = "WIN" if not negative else "LOSE"
    return PreflightResult(status=status, amount_in_raw=loan_raw,
                           amount_out_raw=out_raw, gross_usd=gross,
                           net_usd=net, gas_units_est=gas_units,
                           gas_cost_usd=gas_cost, l1_fee_usd=l1_fee_usd,
                           block_number=block,
                           quote_source="getAmountsOut UniV2/Aerodrome (on-chain)",
                           reasons=reasons)


def is_fresh(quoted_block: Optional[int], current_block: Optional[int],
             max_age: int = MAX_BLOCK_AGE) -> bool:
    """Plafond de fraîcheur (recherche §3.3, règle base-flash-arb-lab) :
    un candidat vieux de plus de 2 blocs est rejeté — sur Base post-Denim
    (bloc 200 ms), 2 blocs = 400 ms, le prix a déjà pu bouger."""
    if quoted_block is None or current_block is None:
        return False
    return 0 <= (current_block - quoted_block) <= max_age


if __name__ == "__main__":
    # Démo lecture seule sur Base mainnet (0 gas) : 100 USDC -> WETH -> USDC
    # via Uniswap V2, avec les adresses vérifiées de RESEARCH.md.
    USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    WETH = "0x4200000000000000000000000000000000000006"
    UNI_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
    r = preflight_roundtrip("https://mainnet.base.org", 100_000_000, USDC, WETH, USDC,
                            UNI_ROUTER, UNI_ROUTER, loan_usd=100.0)
    print("Preflight USDC->WETH->USDC (100 $) :", r.status,
          "| net on-chain:", r.net_usd, "$ | bloc:", r.block_number,
          "| raisons:", r.reasons, "| erreur:", r.error)
    print("Fraîcheur (même bloc) :", is_fresh(r.block_number, r.block_number))
