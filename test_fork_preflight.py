#!/usr/bin/env python3
"""Tests fork_preflight.py (audit #6) — simulation de la transaction
COMPLÈTE sur fork Anvil : déploiement Morpho, eth_call + estimate_gas +
envoi simulé d'executeArbitrage, depuis le bon appelant, à bloc fixé.

TOUT est SYNTHÉTIQUE (fork local, aucun broadcast mainnet, aucun fond
réel). Les tests sont SKIPPÉS (pas en échec) si anvil ou le RPC Base est
indisponible.
Lancer : python3 test_fork_preflight.py (stdlib + web3 via .venv).
"""
import os
import sys
import time

sys.path.insert(0, ".")

from fork_preflight import (ANVIL_TEST_ADDR_0, BASESWAP_V2_ROUTER_BASE,
                            MORPHO_BASE, UNI_V2_ROUTER_BASE, USDC_BASE,
                            WETH_BASE, deploy_morpho, find_anvil,
                            fork_preflight, impersonate, start_anvil_fork,
                            stop_anvil, stop_impersonate)

USDC = USDC_BASE
WETH = WETH_BASE
MORPHO = MORPHO_BASE


def _rpc_url():
    """RPC Base depuis config.yaml (clé jamais affichée) ou env."""
    import re
    for path in ("config.yaml", "config.yaml.example"):
        try:
            text = open(path).read()
        except OSError:
            continue
        m = re.search(r"rpc_url:\s*\"?([^\"\n]+)\"?", text)
        if m:
            return m.group(1).strip()
    return os.environ.get("BASE_RPC_URL")


def _skip_reason():
    if not find_anvil():
        return "anvil introuvable"
    if not _rpc_url():
        return "pas de RPC Base (config.yaml / BASE_RPC_URL)"
    return None


def _usdc_contract(w3):
    abi = [{"constant": False, "inputs": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}],
        "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
        "type": "function"},
        {"constant": False, "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"}],
        "name": "approve", "outputs": [{"name": "", "type": "bool"}],
        "type": "function"},
        {"constant": True, "inputs": [{"name": "who", "type": "address"}],
         "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
         "type": "function"}]
    return w3.eth.contract(address=USDC, abi=abi)


def _v2_router(w3, addr):
    abi = [{"inputs": [
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMin", "type": "uint256"},
        {"name": "path", "type": "address[]"},
        {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"}],
        "name": "swapExactTokensForTokens",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "type": "function"}]
    return w3.eth.contract(address=addr, abi=abi)


def _send(w3, fn, from_addr, key):
    tx = fn.build_transaction({
        "from": from_addr, "nonce": w3.eth.get_transaction_count(from_addr),
        "gas": 2_000_000, "gasPrice": w3.eth.gas_price})
    signed = w3.eth.account.sign_transaction(tx, key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


def test_fork_deploys_and_revert_measures_gas():
    """Cas REVERT (marché réel, sans spread) : la transaction complète
    est simulée sur le fork — eth_call, estimate_gas, envoi simulé —
    avec le gas mesuré et la raison de revert capturée."""
    reason = _skip_reason()
    if reason:
        print(f"SKIP test_fork_deploys_and_revert_measures_gas ({reason})")
        return
    from web3 import Web3
    from fork_preflight import ANVIL_TEST_KEY_0
    fork_url = _rpc_url()
    proc = start_anvil_fork(fork_url, port=8546)
    try:
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8546"))
        assert w3.is_connected()
        contract = deploy_morpho(w3, ANVIL_TEST_ADDR_0, USDC, WETH,
                                 UNI_V2_ROUTER_BASE, BASESWAP_V2_ROUTER_BASE, 0)
        assert w3.eth.get_code(contract.address) != b""
        res = fork_preflight(w3, contract, 100_000_000, ANVIL_TEST_ADDR_0)
        assert res["synthetic"] is True
        # Sans spread réel, le round-trip perd les frais (0,6 %) :
        # le contrat revert — c'est le comportement ATTENDU. Le gas du
        # revert est mesuré sur l'envoi simulé (327 643 unités) ; à noter
        # eth_estimateGas ÉCHOUE sur une tx qui revert (normal : il n'y
        # a pas de gas à estimer pour un revert) — gas_estimate est None
        # et la raison est dans gas_estimate_error.
        assert res["status"] == "REVERT", res
        assert res["revert_reason"] == "pas de quoi rembourser le loan", res
        assert res["gas_estimate"] is None, res
        assert res["gas_estimate_error"], res
        assert res["gas_used"] and res["gas_used"] > 0, res
        print(f"OK test_fork_deploys_and_revert_measures_gas — "
              f"REVERT '{res['revert_reason']}', gas consommé "
              f"{res['gas_used']} (estimate_gas : échec attendu sur revert) "
              f"(synthétique, fork bloc {res['block']})")
    finally:
        stop_anvil(proc)


def test_fork_win_with_whale_moved_price():
    """Cas WIN (SYNTHÉTIQUE) : on déplace le prix du pool Uni V2 avec
    un gros swap de baleine (USDC de Morpho, impersonnée sur le fork),
    puis executeArbitrage gagne réellement sur le fork. Prouve que le
    mécanisme complet (flash + 2 swaps + remboursement) s'exécute."""
    reason = _skip_reason()
    if reason:
        print(f"SKIP test_fork_win_with_whale_moved_price ({reason})")
        return
    from web3 import Web3
    from fork_preflight import ANVIL_TEST_KEY_0
    fork_url = _rpc_url()
    proc = start_anvil_fork(fork_url, port=8547)
    try:
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8547"))
        assert w3.is_connected()
        # Contrat : achat BaseSwap (pas cher) -> vente Uni V2 (cher).
        contract = deploy_morpho(w3, ANVIL_TEST_ADDR_0, USDC, WETH,
                                 BASESWAP_V2_ROUTER_BASE, UNI_V2_ROUTER_BASE, 0)
        # 1) Baleine : 1 000 000 USDC de Morpho (impersonnée, fork
        # seulement) vers le compte de test. Morpho détient des USDC
        # mais 0 ETH : on lui donne de l'ETH sur le fork pour le gas.
        from fork_preflight import set_balance
        set_balance(w3, MORPHO, 10.0)
        impersonate(w3, MORPHO)
        try:
            usdc = _usdc_contract(w3)
            bal = usdc.functions.balanceOf(MORPHO).call()
            assert bal >= 1_000_000_000_000, f"solde Morpho USDC : {bal}"
            tx = usdc.functions.transfer(
                ANVIL_TEST_ADDR_0, 1_000_000_000_000).build_transaction({
                    "from": MORPHO,
                    "nonce": w3.eth.get_transaction_count(MORPHO),
                    "gas": 200_000, "gasPrice": w3.eth.gas_price})
            tx_hash = w3.eth.send_transaction(tx)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        finally:
            stop_impersonate(w3, MORPHO)
        # 2) Le compte de test vend 1 000 000 USDC contre WETH sur Uni V2
        # -> le prix WETH monte sur Uni, BaseSwap reste au prix d'avant.
        usdc = _usdc_contract(w3)
        _send(w3, usdc.functions.approve(UNI_V2_ROUTER_BASE, 1_000_000_000_000),
              ANVIL_TEST_ADDR_0, ANVIL_TEST_KEY_0)
        uni = _v2_router(w3, UNI_V2_ROUTER_BASE)
        deadline = w3.eth.get_block("latest")["timestamp"] + 600
        receipt = _send(w3, uni.functions.swapExactTokensForTokens(
            1_000_000_000_000, 0, [USDC, WETH], ANVIL_TEST_ADDR_0, deadline),
            ANVIL_TEST_ADDR_0, ANVIL_TEST_KEY_0)
        assert receipt["status"] == 1
        # 3) L'arbitrage doit maintenant gagner sur le fork.
        res = fork_preflight(w3, contract, 100_000_000, ANVIL_TEST_ADDR_0)
        assert res["synthetic"] is True
        assert res["status"] == "WIN", res
        assert res["gas_used"] and res["gas_used"] > 0, res
        assert res["gas_estimate"] and res["gas_estimate"] > 0, res
        print(f"OK test_fork_win_with_whale_moved_price — WIN sur fork, "
              f"gas estimé {res['gas_estimate']}, gas consommé "
              f"{res['gas_used']} (synthétique, fork bloc {res['block']})")
    finally:
        stop_anvil(proc)


def test_preflight_roundtrip_block_pinned():
    """preflight_roundtrip épingle ses deux quotes sur UN seul bloc
    (audit #6) : block_number passé = block_number du résultat."""
    reason = _skip_reason()
    if reason:
        print(f"SKIP test_preflight_roundtrip_block_pinned ({reason})")
        return
    from preflight import get_block_number, preflight_roundtrip
    fork_url = _rpc_url()
    block = get_block_number(fork_url)
    assert block, "bloc courant illisible"
    r = preflight_roundtrip(fork_url, 100_000_000, USDC, WETH, USDC,
                            UNI_V2_ROUTER_BASE, UNI_V2_ROUTER_BASE,
                            loan_usd=100.0, block_number=block,
                            min_profit_usd=0.0, gas_multiple=0.0)
    assert r.block_number == block, (r.block_number, block)
    assert r.status in ("WIN", "LOSE", "UNAVAILABLE"), r.status
    print(f"OK test_preflight_roundtrip_block_pinned — bloc {block}, "
          f"statut {r.status}, net {r.net_usd:.4f} $ (lecture seule)")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ÉCHEC {name} : {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{failed} ÉCHEC(S) sur {len(tests)} tests.")
        sys.exit(1)
    print(f"TOUS LES TESTS FORK PREFLIGHT PASSENT ({len(tests)} tests).")
