#!/usr/bin/env python3
"""
fork_simulation.py — Simulation V2 sur fork Anvil de Base mainnet, SANS compiler
le contrat.

Pourquoi ce script existe : la compilation du contrat (forge build) est
BLOQUÉE — le contenu des dépendances clonées (lib/) a échoué un contrôle
de risque d'exécution, en attente de confirmation d'Ismail (voir
FORK_TEST_RESULTS.md). Ce script prouve quand même, sur l'état RÉEL du
fork, tout ce qui ne dépend pas du bytecode compilé :

  1. État du fork réel : Aave Pool, prime flash, liquidité USDC (via aToken).
  2. Réserves réelles Uni V2 / Sushi V2 / Aerodrome (WETH/USDC) + spread naturel.
  3. Spread synthétique créé avec des fonds fictifs du fork.
  4. Sizing mathématique (seuil 3 $) sur les réserves réelles.
  5. Cotation ON-CHAIN du round-trip via router.getAmountsOut (view) :
     c'est exactement le prix que le contrat obtiendrait — preuve
     économique de l'arbitrage, sans déployer le contrat.
  6. Estimation gas des 2 swaps on-chain (eth_estimateGas).
  7. Cas perdant : decide() = SKIP (0 gas) + mesure du coût d'un revert
     (swap avec amountOutMin impossible, broadcast sur le fork, ETH fictif).

Leçons techniques notées dans FORK_TEST_RESULTS.md :
  - Anvil 1.10 + fork : les tx LEGACY (gasPrice) échouent avec
    "Insufficient funds" — il faut des tx EIP-1559 (maxFeePerGas).
  - Aave V3 : la liquidité USDC n'est PAS dans le Pool (123 $) mais dans
    le aToken aBasUSDC (~13,66 M $) — c'est lui qu'il faut lire.

AUCUN fond réel, AUCUNE clé privée d'utilisateur, AUCUN broadcast mainnet.
Seule clé utilisée : clé de TEST publique d'Anvil (compte 0).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests
from web3 import Web3

from math_engine import Costs, Pool, amm_out, decide, gas_cost_usd

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
AAVE_POOL = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
UNI_V2_FACTORY = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"
UNI_V2_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
SUSHI_V2_FACTORY = "0x71524B4f93c58fcbF659783284E38825f0622859"
SUSHI_V2_ROUTER = "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

MIN_PROFIT_USD = 3.0
ETH_PRICE_USD = 3000.0
ANVIL_URL = "http://127.0.0.1:8545"
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ZERO = "0x0000000000000000000000000000000000000000"

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view"},
    {"name": "approve", "type": "function", "inputs": [{"name": "s", "type": "address"}, {"name": "v", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable"},
    {"name": "transfer", "type": "function", "inputs": [{"name": "t", "type": "address"}, {"name": "v", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable"},
    {"name": "decimals", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view"},
]
WETH_ABI = ERC20_ABI + [
    {"name": "deposit", "type": "function", "inputs": [], "outputs": [], "stateMutability": "payable"},
]
FACTORY_ABI = [
    {"name": "getPair", "type": "function", "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
AERO_FACTORY_ABI = [
    {"name": "getPool", "type": "function", "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}, {"name": "stable", "type": "bool"}], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
PAIR_ABI = [
    {"name": "getReserves", "type": "function", "inputs": [], "outputs": [{"name": "_r0", "type": "uint112"}, {"name": "_r1", "type": "uint112"}, {"name": "_t", "type": "uint32"}], "stateMutability": "view"},
    {"name": "token0", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
ROUTER_ABI = [
    {"name": "getAmountsOut", "type": "function", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}], "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "view"},
    {"name": "swapExactTokensForTokens", "type": "function", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "nonpayable"},
]
# Aerodrome Router : PAS d'interface V2 (vérifié on-chain par sélecteurs) —
# il faut les routes (from, to, stable, factory). Voir FORK_TEST_RESULTS.md.
AERO_ROUTER_ABI = [
    {"name": "getAmountsOut", "type": "function",
     "inputs": [{"name": "amountIn", "type": "uint256"},
                {"name": "routes", "type": "tuple[]",
                 "components": [{"name": "from", "type": "address"},
                                {"name": "to", "type": "address"},
                                {"name": "stable", "type": "bool"},
                                {"name": "factory", "type": "address"}]}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "view"},
    {"name": "swapExactTokensForTokens", "type": "function",
     "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"},
                {"name": "routes", "type": "tuple[]",
                 "components": [{"name": "from", "type": "address"},
                                {"name": "to", "type": "address"},
                                {"name": "stable", "type": "bool"},
                                {"name": "factory", "type": "address"}]},
                {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "nonpayable"},
]
POOL_ABI = [
    {"name": "FLASHLOAN_PREMIUM_TOTAL", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "uint128"}], "stateMutability": "view"},
    {"name": "getReserveData", "type": "function", "inputs": [{"name": "asset", "type": "address"}], "outputs": [
        {"name": "configuration", "type": "uint256"}, {"name": "liquidityIndex", "type": "uint128"},
        {"name": "currentLiquidityRate", "type": "uint128"}, {"name": "variableBorrowIndex", "type": "uint128"},
        {"name": "currentVariableBorrowRate", "type": "uint128"}, {"name": "currentStableBorrowRate", "type": "uint128"},
        {"name": "lastUpdateTimestamp", "type": "uint40"}, {"name": "id", "type": "uint16"},
        {"name": "aTokenAddress", "type": "address"}, {"name": "stableDebtTokenAddress", "type": "address"},
        {"name": "variableDebtTokenAddress", "type": "address"}, {"name": "interestRateStrategyAddress", "type": "address"},
        {"name": "accruedToTreasury", "type": "uint128"}, {"name": "unbacked", "type": "uint128"},
        {"name": "isolationModeTotalDebt", "type": "uint128"}], "stateMutability": "view"},
]

results = {"min_profit_usd": MIN_PROFIT_USD, "steps": {}}


def log(step, **kw):
    results["steps"][step] = kw
    print(f"[{step}] " + " | ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def main():
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    assert w3.is_connected(), "Anvil injoignable sur 127.0.0.1:8545"
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)
    me = deployer.address
    block = w3.eth.block_number
    chain_id = w3.eth.chain_id
    log("fork", chain_id=chain_id, block_number=block,
        note="fork Base mainnet, RPC public https://mainnet.base.org")
    assert chain_id == 8453

    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    weth = w3.eth.contract(address=WETH, abi=WETH_ABI)
    uni_factory = w3.eth.contract(address=UNI_V2_FACTORY, abi=FACTORY_ABI)
    sushi_factory = w3.eth.contract(address=SUSHI_V2_FACTORY, abi=FACTORY_ABI)
    aero_factory = w3.eth.contract(address=AERODROME_FACTORY, abi=AERO_FACTORY_ABI)
    pool = w3.eth.contract(address=AAVE_POOL, abi=POOL_ABI)

    # --- 1) Aave : prime flash + liquidité (via aToken, pas le Pool) ---
    pool_code = w3.eth.get_code(AAVE_POOL)
    premium_bps = pool.functions.FLASHLOAN_PREMIUM_TOTAL().call()
    reserve_data = pool.functions.getReserveData(USDC).call()
    atoken = reserve_data[8]
    atoken_usdc = usdc.functions.balanceOf(atoken).call() / 1e6
    pool_usdc = usdc.functions.balanceOf(AAVE_POOL).call() / 1e6
    log("aave", pool_has_code=len(pool_code) > 0, flash_premium_bps=premium_bps,
        flash_fee_pct=premium_bps / 100, atoken=atoken,
        atoken_usdc_balance_usd=round(atoken_usdc, 2),
        pool_usdc_balance_usd=round(pool_usdc, 2),
        note="prime 5 bps = 0,05 % confirmée on-chain ; la liquidité est dans "
             "le aToken aBasUSDC, pas dans le Pool (123 $)")
    assert premium_bps == 5
    assert atoken_usdc > 1_000_000, "liquidité Aave USDC trop faible pour un flash loan"

    # --- 2) Découverte meme coin réel (GeckoTerminal new pools + getPair on-chain) ---
    meme_candidate = None
    try:
        r = requests.get("https://api.geckoterminal.com/api/v2/networks/base/new_pools",
                         params={"page": 1}, timeout=20)
        r.raise_for_status()
        checked = 0
        for p in r.json().get("data", [])[:15]:
            a = p["attributes"]
            liq = float(a.get("reserve_in_usd") or 0)
            if not (5_000 <= liq <= 100_000):
                continue
            rel = p["relationships"]
            base_id = Web3.to_checksum_address(rel["base_token"]["data"]["id"].split("_", 1)[1])
            quote_id = Web3.to_checksum_address(rel["quote_token"]["data"]["id"].split("_", 1)[1])
            meme = base_id if quote_id in (WETH, USDC) else None
            if not meme:
                continue
            checked += 1
            pair_uni = uni_factory.functions.getPair(meme, WETH).call()
            pair_sushi = sushi_factory.functions.getPair(meme, WETH).call()
            if pair_uni != ZERO and pair_sushi != ZERO:
                meme_candidate = {"token": meme, "name": a.get("name"),
                                  "dex": a.get("dex_id"), "reserve_in_usd": liq,
                                  "pair_uni": pair_uni, "pair_sushi": pair_sushi}
                break
        log("meme_discovery", found=meme_candidate is not None, pools_verifies=checked,
            candidate=(meme_candidate or "aucun pool meme 5k-100k $ avec paires V2 sur 2 DEXs"))
    except Exception as e:
        log("meme_discovery", found=False,
            error=f"GeckoTerminal injoignable : {type(e).__name__}: {e}")

    # --- 3) Réserves réelles WETH/USDC sur 3 DEXs ---
    def read_pair(factory, t0, t1):
        addr = factory.functions.getPair(t0, t1).call()
        assert addr != ZERO, "pair introuvable"
        c = w3.eth.contract(address=addr, abi=PAIR_ABI)
        r0, r1, _ = c.functions.getReserves().call()
        tok0 = c.functions.token0().call()
        return (addr, r0, r1) if tok0.lower() == t0.lower() else (addr, r1, r0)

    uni_addr, uni_weth, uni_usdc = read_pair(uni_factory, WETH, USDC)
    sushi_addr, sushi_weth, sushi_usdc = read_pair(sushi_factory, WETH, USDC)
    aero_addr = aero_factory.functions.getPool(WETH, USDC, False).call()
    aero_c = w3.eth.contract(address=aero_addr, abi=PAIR_ABI)
    ar0, ar1, _ = aero_c.functions.getReserves().call()
    atok0 = aero_c.functions.token0().call()
    aero_weth, aero_usdc = (ar0, ar1) if atok0.lower() == WETH.lower() else (ar1, ar0)
    price_uni = (uni_usdc / 1e6) / (uni_weth / 1e18)
    price_sushi = (sushi_usdc / 1e6) / (sushi_weth / 1e18)
    price_aero = (aero_usdc / 1e6) / (aero_weth / 1e18)
    log("reserves_avant",
        uni_pair=uni_addr, uni_weth=round(uni_weth / 1e18, 2), uni_usdc=round(uni_usdc / 1e6, 2),
        sushi_pair=sushi_addr, sushi_weth=round(sushi_weth / 1e18, 2), sushi_usdc=round(sushi_usdc / 1e6, 2),
        aero_pool=aero_addr, aero_weth=round(aero_weth / 1e18, 2), aero_usdc=round(aero_usdc / 1e6, 2),
        prix_weth_uni_usd=round(price_uni, 2), prix_weth_sushi_usd=round(price_sushi, 2),
        prix_weth_aero_usd=round(price_aero, 2),
        spread_uni_sushi_pct=round(100 * (price_sushi / price_uni - 1), 4),
        spread_uni_aero_pct=round(100 * (price_aero / price_uni - 1), 4),
        note="Sushi V2 WETH/USDC quasi vide (~2,8k $) : inutilisable comme jambe "
             "de vente ; Aerodrome (~694k $) est la vraie 2e jambe")

    # --- 4) Spread synthétique : vente de WETH sur Uni V2 (fonds fictifs du fork) ---
    # Tx EIP-1559 (les tx legacy échouent sur ce fork Anvil 1.10 — voir doc).
    def send_signed(fn, value=0):
        fee = w3.eth.gas_price
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me),
                                   "gas": 500_000,
                                   "maxFeePerGas": fee, "maxPriorityFeePerGas": 0,
                                   "chainId": 8453, "value": value})
        signed = deployer.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction)

    deadline = w3.eth.get_block("latest")["timestamp"] + 600
    weth_amount = int(uni_weth * 0.05)  # 5 % de la réserve WETH Uni V2
    w3.eth.wait_for_transaction_receipt(send_signed(weth.functions.deposit(), value=weth_amount))
    w3.eth.wait_for_transaction_receipt(
        send_signed(weth.functions.approve(UNI_V2_ROUTER, weth_amount)))
    uni_router = w3.eth.contract(address=UNI_V2_ROUTER, abi=ROUTER_ABI)
    txh = send_signed(uni_router.functions.swapExactTokensForTokens(
        weth_amount, 0, [WETH, USDC], me, deadline))
    w3.eth.wait_for_transaction_receipt(txh)
    _, uni_weth2, uni_usdc2 = read_pair(uni_factory, WETH, USDC)
    ar0b, ar1b, _ = aero_c.functions.getReserves().call()
    aero_weth2, aero_usdc2 = (ar0b, ar1b) if atok0.lower() == WETH.lower() else (ar1b, ar0b)
    price_uni2 = (uni_usdc2 / 1e6) / (uni_weth2 / 1e18)
    price_aero2 = (aero_usdc2 / 1e6) / (aero_weth2 / 1e18)
    spread = 100 * (price_aero2 / price_uni2 - 1)
    log("spread_synthetique", weth_vendu=round(weth_amount / 1e18, 2),
        prix_weth_uni_usd=round(price_uni2, 2), prix_weth_aero_usd=round(price_aero2, 2),
        spread_pct=round(spread, 3),
        note="spread créé artificiellement avec des fonds fictifs du fork, "
             "pour simuler une opportunité réelle de meme coin")
    assert spread > 1.0, f"spread synthétique trop faible : {spread:.2f} %"

    # --- 5) Sizing mathématique (seuil 3 $) sur les réserves RÉELLES du fork ---
    pool_buy = Pool("UniV2 WETH/USDC (pas cher)", uni_usdc2 / 1e6, uni_weth2 / 1e18)
    pool_sell = Pool("Aerodrome WETH/USDC (cher)", aero_usdc2 / 1e6, aero_weth2 / 1e18)
    gas_price_gwei = w3.eth.gas_price / 1e9
    costs = Costs(gas_usd=gas_cost_usd(450_000, gas_price_gwei, ETH_PRICE_USD),
                  min_profit_usd=MIN_PROFIT_USD, gas_multiple=3.0)
    decision = decide(pool_buy, pool_sell, costs)
    log("decision_offchain", action=decision["action"], spread_pct=decision["spread_pct"],
        optimal_loan_usd=decision["optimal_loan_usd"],
        expected_net_usd=decision["expected_net_usd"],
        gas_usd_est=round(decision["gas_usd"], 4),
        min_profit_usd=MIN_PROFIT_USD, reasons=decision["reasons"])
    assert decision["action"] == "EXECUTE", f"decide() dit {decision['action']}"
    loan_usd = decision["optimal_loan_usd"]
    loan_usdc_wei = int(loan_usd * 1e6)

    # --- 6) Round-trip RÉEL sur le fork (sans flash loan, mais avec les vrais
    # routers) : on finance le deployer en USDC via impersonation du aToken
    # (fonds fictifs du fork), puis on exécute achat Uni V2 + vente Aerodrome.
    # C'est la preuve d'exécution la plus proche possible sans le contrat
    # compilé : il ne manque que le borrow/repay flash (+~150k gas de marge).
    # Le aToken détient les USDC mais pas d'ETH pour le gas : on lui donne
    # 1 ETH fictif (anvil_setBalance) avant l'impersonation.
    w3.provider.make_request("anvil_setBalance", [atoken, hex(10**18)])
    w3.provider.make_request("anvil_impersonateAccount", [atoken])
    fund_tx = usdc.functions.transfer(me, loan_usdc_wei).build_transaction(
        {"from": atoken, "gas": 100_000,
         "maxFeePerGas": w3.eth.gas_price, "maxPriorityFeePerGas": 0,
         "chainId": 8453, "nonce": w3.eth.get_transaction_count(atoken)})
    w3.eth.send_transaction(fund_tx)
    w3.provider.make_request("anvil_stopImpersonatingAccount", [atoken])
    log("financement_fork", usdc_recus=loan_usd,
        source=f"aToken {atoken} (impersonation Anvil, fonds fictifs du fork)",
        note="remplace le flash loan pour l'exécution des 2 swaps")
    aero_router = w3.eth.contract(address=AERODROME_ROUTER, abi=AERO_ROUTER_ABI)
    aero_route = [(WETH, USDC, False, AERODROME_FACTORY)]
    # Cotation on-chain AVANT exécution (comparaison avec le réel)
    amounts_buy = uni_router.functions.getAmountsOut(loan_usdc_wei, [USDC, WETH]).call()
    weth_quote = amounts_buy[1]
    amounts_sell = aero_router.functions.getAmountsOut(weth_quote, aero_route).call()
    usdc_quote = amounts_sell[1] / 1e6
    w3.eth.wait_for_transaction_receipt(
        send_signed(usdc.functions.approve(UNI_V2_ROUTER, loan_usdc_wei)))
    usdc_before = usdc.functions.balanceOf(me).call()
    weth_before = weth.functions.balanceOf(me).call()
    txh = send_signed(uni_router.functions.swapExactTokensForTokens(
        loan_usdc_wei, 0, [USDC, WETH], me, deadline))
    rc_buy = w3.eth.wait_for_transaction_receipt(txh)
    weth_bought = weth.functions.balanceOf(me).call() - weth_before
    w3.eth.wait_for_transaction_receipt(
        send_signed(weth.functions.approve(AERODROME_ROUTER, weth_bought)))
    txh = send_signed(aero_router.functions.swapExactTokensForTokens(
        weth_bought, 0, aero_route, me, deadline))
    rc_sell = w3.eth.wait_for_transaction_receipt(txh)
    usdc_after = usdc.functions.balanceOf(me).call()
    usdc_back = (usdc_after - (usdc_before - loan_usdc_wei)) / 1e6
    gross = usdc_back - loan_usd
    flash_fee = loan_usd * 0.0005
    gas_total_units = rc_buy["gasUsed"] + rc_sell["gasUsed"] + 150_000  # marge flash loan
    gas_cost = gas_total_units * rc_sell["effectiveGasPrice"] / 1e18 * ETH_PRICE_USD
    net_onchain = gross - flash_fee - gas_cost
    log("roundtrip_reel_fork", loan_usd=loan_usd,
        weth_achete=round(weth_bought / 1e18, 6),
        weth_achete_cotation=round(weth_quote / 1e18, 6),
        usdc_recupere=round(usdc_back, 2), usdc_recupere_cotation=round(usdc_quote, 2),
        brut_usd=round(gross, 2), flash_fee_usd=round(flash_fee, 2),
        gas_swap_achat_units=rc_buy["gasUsed"], gas_swap_vente_units=rc_sell["gasUsed"],
        gas_total_avec_marge_flash_units=gas_total_units,
        gas_price_gwei=round(rc_sell["effectiveGasPrice"] / 1e9, 4),
        gas_cost_usd=round(gas_cost, 4),
        net_onchain_usd=round(net_onchain, 2), min_profit_usd=MIN_PROFIT_USD,
        verdict="WIN" if net_onchain >= MIN_PROFIT_USD else "FAIL",
        note="swaps RÉELS sur le fork (tx minées) ; le net déduit la prime "
             "flash 0,05 % et 150k gas de marge pour le borrow/repay")
    assert net_onchain >= MIN_PROFIT_USD, "le round-trip réel ne passe pas le seuil 3 $"

    # --- 7) Cas perdant : spread naturel (~0 %) -> decide() = SKIP, 0 gas ---
    pool_buy0 = Pool("UniV2 naturel", uni_usdc / 1e6, uni_weth / 1e18)
    pool_sell0 = Pool("Aerodrome naturel", aero_usdc / 1e6, aero_weth / 1e18)
    decision0 = decide(pool_buy0, pool_sell0, costs)
    log("cas_perdant_decision_offchain", action=decision0["action"],
        spread_pct=decision0["spread_pct"], optimal_loan_usd=decision0["optimal_loan_usd"],
        expected_net_usd=decision0["expected_net_usd"], gas_paye_usd=0.0,
        reasons=decision0["reasons"],
        note="SKIP = rien broadcasté, 0 gas payé")
    # Mesure du coût d'un revert : swap avec amountOutMin impossible, broadcast sur le fork
    txh = send_signed(uni_router.functions.swapExactTokensForTokens(
        100_000, 10**12, [USDC, WETH], me, deadline))
    rc = w3.eth.wait_for_transaction_receipt(txh)
    revert_gas_usd = rc["gasUsed"] * rc["effectiveGasPrice"] / 1e18 * ETH_PRICE_USD
    log("cout_revert_mesure_fork", tx_status=rc["status"], gas_used=rc["gasUsed"],
        gas_price_gwei=round(rc["effectiveGasPrice"] / 1e9, 4),
        cout_revert_usd=round(revert_gas_usd, 4),
        note="revert provoqué exprès sur le fork (ETH fictif) pour chiffrer le "
             "coût — en live on l'évite par le SKIP off-chain (0 $)")

    results["summary"] = {
        "fork_block": block,
        "spread_naturel_pct": round(100 * (price_aero / price_uni - 1), 4),
        "spread_synthetique_pct": round(spread, 3),
        "cas_gagnant": {"loan_usd": loan_usd,
                        "net_python_usd": decision["expected_net_usd"],
                        "net_onchain_usd": round(net_onchain, 2),
                        "usdc_recupere": round(usdc_back, 2),
                        "flash_fee_usd": round(flash_fee, 2),
                        "gas_estime_units": gas_total_units,
                        "gas_cost_usd": round(gas_cost, 4),
                        "verdict": "WIN"},
        "cas_perdant": {"decision_offchain": decision0["action"],
                        "gas_paye_si_skip_usd": 0.0,
                        "cout_revert_si_broadcast_usd": round(revert_gas_usd, 4),
                        "gas_revert": rc["gasUsed"],
                        "verdict": "SKIP (0 gas) / revert mesuré on-chain"},
        "meme_reel_trouve": meme_candidate,
        "aave_usdc_disponible_usd": round(atoken_usdc, 2),
        "contrat_compile_deploye": False,
        "blocage": "compilation forge bloquée : contenu lib/ en attente de confirmation (voir FORK_TEST_RESULTS.md)",
        "constats": [
            "Aerodrome Router N'A PAS l'interface V2 (vérifié par sélecteurs on-chain) : "
            "le contrat v1 ne peut pas l'utiliser tel quel — il faut les routes "
            "(from, to, stable, factory) ou un adaptateur. Uni V2 + Sushi V2 OK en V2.",
            "Sushi V2 WETH/USDC quasi vide (~2,8k $) : inutilisable comme jambe de vente.",
            "Aave V3 : la liquidité USDC est dans le aToken aBasUSDC (~13,66 M $), "
            "pas dans le Pool (123 $).",
            "Anvil 1.10 + fork : les tx legacy (gasPrice) échouent — utiliser EIP-1559.",
        ],
    }
    Path("fork_results.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n=== RÉSUMÉ FORK (sans compilation) ===")
    print(json.dumps(results["summary"], indent=2, default=str))
    print("Résultats détaillés : fork_results.json")


if __name__ == "__main__":
    main()
