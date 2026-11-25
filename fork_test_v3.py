#!/usr/bin/env python3
"""Test fork du contrat MorphoFlashLoanArbitrageV3 (audit #7) — jambes
Uniswap V3 (exactInputSingle) sur fork Anvil de Base mainnet.

TOUT est SYNTHÉTIQUE (fork local, aucun broadcast mainnet, aucun fond
réel). Deux pools V3 synthétiques (token MEME frais, deux tiers) à des
prix différents : pool A (fee 3000) 1 MEME = 0,01 USDC, pool B
(fee 10000) 1 MEME = 0,011 USDC (spread 10 %). Cas WIN puis cas REVERT
après fermeture du spread (gros swap sur le pool B).
Tests SKIPPÉS si anvil ou RPC Base indisponible.
Lancer : python3 fork_test_v3.py (web3 via .venv).
"""
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

from fork_preflight import (ANVIL_TEST_ADDR_0, ANVIL_TEST_KEY_0,
                            MORPHO_BASE, USDC_BASE, find_anvil,
                            impersonate, set_balance, start_anvil_fork,
                            stop_anvil, stop_impersonate)

USDC = USDC_BASE
MORPHO = MORPHO_BASE
V3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
SWAP_ROUTER_02 = "0x2626664c2603336E57B271c5C0b26F421741e481"
FEE_BUY = 3000
FEE_SELL = 10000

FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"},
                {"name": "tokenB", "type": "address"},
                {"name": "fee", "type": "uint24"}],
     "name": "createPool", "outputs": [{"name": "pool", "type": "address"}],
     "type": "function"},
    {"inputs": [{"name": "tokenA", "type": "address"},
                {"name": "tokenB", "type": "address"},
                {"name": "fee", "type": "uint24"}],
     "name": "getPool", "outputs": [{"name": "pool", "type": "address"}],
     "type": "function"}]

POOL_ABI = [
    {"inputs": [{"name": "sqrtPriceX96", "type": "uint160"}],
     "name": "initialize", "outputs": [], "type": "function"},
    {"inputs": [], "name": "slot0", "outputs": [
        {"name": "sqrtPriceX96", "type": "uint160"},
        {"name": "tick", "type": "int24"},
        {"name": "observationIndex", "type": "uint16"},
        {"name": "observationCardinality", "type": "uint16"},
        {"name": "observationCardinalityNext", "type": "uint16"},
        {"name": "feeProtocol", "type": "uint8"},
        {"name": "unlocked", "type": "bool"}], "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}],
     "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}],
     "type": "function"}]

ERC20_ABI = [
    {"inputs": [{"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"}],
     "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
     "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}],
     "type": "function"},
    {"inputs": [{"name": "who", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
     "type": "function"}]


def _rpc_url():
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


def _artifact(name, sub):
    path = Path(__file__).parent / "out" / sub / f"{name}.json"
    return json.loads(path.read_text())


def _deploy(w3, artifact, deployer, *args):
    c = w3.eth.contract(abi=artifact["abi"],
                        bytecode=artifact["bytecode"]["object"])
    tx = c.constructor(*args).build_transaction({
        "from": deployer, "nonce": w3.eth.get_transaction_count(deployer),
        "gas": 5_000_000, "gasPrice": w3.eth.gas_price})
    signed = w3.eth.account.sign_transaction(tx, ANVIL_TEST_KEY_0)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    assert receipt["status"] == 1, "déploiement échoué"
    return w3.eth.contract(address=receipt["contractAddress"],
                           abi=artifact["abi"])


def _send(w3, fn, from_addr, gas=2_000_000):
    tx = fn.build_transaction({
        "from": from_addr, "nonce": w3.eth.get_transaction_count(from_addr),
        "gas": gas, "gasPrice": w3.eth.gas_price})
    signed = w3.eth.account.sign_transaction(tx, ANVIL_TEST_KEY_0)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    assert receipt["status"] == 1, f"tx échouée : {tx_hash.hex()}"
    return receipt


def _setup_pools(w3):
    """Déploie MEME + minter, finance, crée les 2 pools V3 synthétiques.
    Retourne (meme, pool_a, pool_b)."""
    deployer = ANVIL_TEST_ADDR_0
    meme = _deploy(w3, _artifact("TestToken", "TestToken.sol"),
                   deployer, "TestMEME", "MEME")
    minter = _deploy(w3, _artifact("TestV3Minter", "TestV3Minter.sol"),
                     deployer)
    # 5 000 000 MEME au déployeur.
    _send(w3, meme.functions.mint(deployer, 5_000_000 * 10**18), deployer)
    # 100 000 USDC de Morpho (impersonnée, fork seulement).
    set_balance(w3, MORPHO, 10.0)
    impersonate(w3, MORPHO)
    try:
        usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
        tx = usdc.functions.transfer(deployer, 100_000 * 10**6).build_transaction({
            "from": MORPHO, "nonce": w3.eth.get_transaction_count(MORPHO),
            "gas": 200_000, "gasPrice": w3.eth.gas_price})
        tx_hash = w3.eth.send_transaction(tx)
        w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    finally:
        stop_impersonate(w3, MORPHO)
    # Le minter reçoit 2 000 000 MEME + 25 000 USDC.
    _send(w3, meme.functions.transfer(minter.address, 2_000_000 * 10**18),
          deployer)
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    _send(w3, usdc.functions.transfer(minter.address, 25_000 * 10**6),
          deployer)
    factory = w3.eth.contract(address=V3_FACTORY, abi=FACTORY_ABI)
    pools = {}
    # Pool A (fee 3000) : 1 MEME = 0,01 USDC ; pool B (fee 10000) :
    # 1 MEME = 0,011 USDC. Deux tiers = deux pools distinctes.
    # ATTENTION : le prix V3 est en unités BRUTES (raw token1 / raw
    # token0) — MEME a 18 décimales, USDC 6 : 1 MEME = 0,01 USDC vaut
    # 10^-14 USDC-raw par MEME-raw (pas 0,01). Une erreur ici initialise
    # le pool à un prix absurde avec une liquidité poussière (bug trouvé
    # en debug : swap revert sans raison).
    for label, fee, meme_price_usdc in (("A", FEE_BUY, 0.01),
                                        ("B", FEE_SELL, 0.011)):
        pool_addr = factory.functions.getPool(USDC, meme.address, fee).call()
        if pool_addr == "0x0000000000000000000000000000000000000000":
            receipt = _send(w3, factory.functions.createPool(
                USDC, meme.address, fee), deployer, gas=5_000_000)
            pool_addr = factory.functions.getPool(USDC, meme.address, fee).call()
        pool = w3.eth.contract(address=pool_addr, abi=POOL_ABI)
        token0 = pool.functions.token0().call()
        # Prix brut token1/token0 (décimales prises en compte).
        if token0.lower() == USDC.lower():
            price_raw = (1.0 / meme_price_usdc) * 10**12  # MEME-raw / USDC-raw
            target0_raw, target1_raw = 10_000 * 10**6, 1_000_000 * 10**18
        else:
            price_raw = meme_price_usdc * 10**-12  # USDC-raw / MEME-raw
            target0_raw, target1_raw = 1_000_000 * 10**18, 10_000 * 10**6
        sqrt_price_x96 = int(math.sqrt(price_raw) * 2**96)
        _send(w3, pool.functions.initialize(sqrt_price_x96), deployer)
        tick = int(math.log(price_raw) / math.log(1.0001))
        spacing = 60 if fee == 3000 else 200
        tick_lo = (tick - 6000) // spacing * spacing
        tick_hi = (tick + 6000 + spacing - 1) // spacing * spacing
        # Liquidité : vise ~1 000 000 MEME + ~10 000 USDC par pool.
        # amount0 = L*(1/sqrtP - 1/sqrtB) ; amount1 = L*(sqrtP - sqrtA).
        sqrt_p = math.sqrt(price_raw)
        sqrt_a = math.sqrt(1.0001 ** tick_lo)
        sqrt_b = math.sqrt(1.0001 ** tick_hi)
        liq = int(min(target0_raw / (1 / sqrt_p - 1 / sqrt_b),
                      target1_raw / (sqrt_p - sqrt_a)))
        receipt = _send(w3, minter.functions.mint(
            pool_addr, tick_lo, tick_hi, liq), deployer, gas=5_000_000)
        pools[label] = pool_addr
        print(f"  pool {label} {pool_addr[:10]}... fee {fee} "
              f"prix 1 MEME = {meme_price_usdc} USDC, ticks "
              f"[{tick_lo}, {tick_hi}], L={liq}")
    return meme, pools["A"], pools["B"]


def test_v3_fork_win_and_revert():
    reason = _skip_reason()
    if reason:
        print(f"SKIP test_v3_fork_win_and_revert ({reason})")
        return
    from web3 import Web3
    proc = start_anvil_fork(_rpc_url(), port=8548)
    try:
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8548"))
        assert w3.is_connected()
        meme, pool_a, pool_b = _setup_pools(w3)
        # Contrat V3 : loan USDC, autre token MEME, tiers 3000 / 10000.
        arb = _deploy(w3, _artifact("MorphoFlashLoanArbitrageV3",
                                    "FlashLoanArbitrage.sol"),
                      ANVIL_TEST_ADDR_0, USDC, meme.address, SWAP_ROUTER_02,
                      FEE_BUY, FEE_SELL, 0)
        # --- Cas WIN : spread 10 % - frais (0,3 % + 1 %) - impact.
        fn = arb.functions.executeArbitrage(100_000_000)  # 100 USDC
        try:
            fn.call({"from": ANVIL_TEST_ADDR_0})
            call_ok = True
        except Exception as e:  # noqa: BLE001
            call_ok = False
            print(f"  eth_call WIN a revert : {e}")
        assert call_ok, "le cas WIN ne devrait pas revert"
        gas_est = fn.estimate_gas({"from": ANVIL_TEST_ADDR_0})
        receipt = _send(w3, fn, ANVIL_TEST_ADDR_0, gas=2_000_000)
        assert receipt["status"] == 1
        usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
        profit = usdc.functions.balanceOf(arb.address).call()
        assert profit > 0, "profit nul sur le cas WIN"
        print(f"OK cas WIN V3 — profit {profit / 1e6:.2f} USDC sur 100 USDC, "
              f"gas estimé {gas_est}, gas consommé {receipt['gasUsed']} "
              f"(synthétique, fork bloc {w3.eth.block_number})")
        # --- Cas REVERT : on ferme le spread en vendant 200 000 MEME
        # sur le pool B (son prix tombe sous celui du pool A).
        router_abi = [{"inputs": [{
            "components": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "recipient", "type": "address"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMinimum", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"}],
            "name": "params", "type": "tuple"}],
            "name": "exactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "type": "function"}]
        router = w3.eth.contract(address=SWAP_ROUTER_02, abi=router_abi)
        _send(w3, meme.functions.approve(SWAP_ROUTER_02, 200_000 * 10**18),
              ANVIL_TEST_ADDR_0)
        # Struct Base à 7 champs (SANS deadline — vérifié sur Basescan,
        # sélecteur 0x04e45aaf ; le struct 8 champs revert sur Base).
        _send(w3, router.functions.exactInputSingle(
            (meme.address, USDC, FEE_SELL, ANVIL_TEST_ADDR_0,
             200_000 * 10**18, 0, 0)), ANVIL_TEST_ADDR_0, gas=2_000_000)
        # Le spread est fermé/inversé : l'arbitrage doit revert.
        try:
            fn.call({"from": ANVIL_TEST_ADDR_0})
            reverted = False
        except Exception:  # noqa: BLE001
            reverted = True
        assert reverted, "le cas REVERT aurait dû revert après fermeture du spread"
        print("OK cas REVERT V3 — executeArbitrage revert après fermeture "
              f"du spread (synthétique, fork bloc {w3.eth.block_number})")
    finally:
        stop_anvil(proc)


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
    print(f"TOUS LES TESTS FORK V3 PASSENT ({len(tests)} tests).")
