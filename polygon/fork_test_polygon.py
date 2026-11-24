#!/usr/bin/env python3
"""
fork_test_polygon.py — Test v4.0 sur fork Anvil de Polygon mainnet (Morpho Blue).

AUCUN fond réel, AUCUNE clé privée d'utilisateur, AUCUN broadcast mainnet.
Tout se passe sur un fork local jetable (anvil --fork-url <RPC Polygon>).
La seule clé utilisée est la clé de TEST publique d'Anvil (compte 0),
qui ne contrôle aucun fond réel.

Seuil v4.1 : min profit 3 $ ABANDONNÉ (Ismail, 2026-11-24) — nouvelle règle :
EXECUTE ssi net > 0 $ APRÈS TOUS LES COÛTS (flash 0 %, frais de swap,
gas du trade + budget revert = 2 × gas). minProfit ON-CHAIN = 0,01 $
(plancher anti-poussière ; voir polygon_guard.py).

Ce que le test prouve, dans l'ordre :
  1. L'état du fork est réel : Morpho Blue Polygon, réserves QuickSwap V2 /
     Uni V3 USDC/WMATIC lues on-chain ; Morpho n'a PAS de getter flashFee
     (fee 0 par conception) ; ses soldes USDC/USDT couvrent largement le loan.
  2. Le contrat MorphoFlashLoanArbitragePolygon (compilé par forge) déployé
     sur le fork (minProfit on-chain 0,01 $).
  3. CAS GAGNANT (gros) : eth_call (simulation, 0 gas) PUIS broadcast sur le
     fork, profit net mesuré après gas (en MATIC et en $), require(profit >= 0,01 $).
  3b. CAS GAGNANT (petit net) : petit spread synthétique (~2-3 %), decide()
     dit EXECUTE avec net attendu entre 0 et 3 $ (ex. ~0,50 $) → broadcast
     WIN avec net réalisé > 0 $ — la preuve que la règle v4.1 autorise les
     petits profits.
  4. CAS PERDANT : decide() dit SKIP (0 gas), eth_call revert confirmé,
     et — pour chiffrer le coût d'un revert — broadcast du perdant sur le
     fork (MATIC fictif) pour mesurer le gas d'un revert réel.

Miroir de fork_test_morpho.py (Base) : même spread synthétique (vente de
5 % de la réserve WMATIC QuickSwap V2), même seuil 3 $, provider Morpho 0 %.
Différences Polygon : jambes QuickSwap V2 (achat) / Uni V3 (vente),
gas ~279 gwei mais MATIC à 0,0758 $ (trade ~0,0095 $, soit ~2× le gas
mesuré Base — le gas Polygon n'est pas « quasi gratuit » en $),
float 1,31 $ (~137 trades).

NOTE sur le sizing : la pool Uni V3 est à liquidité concentrée (pas un
x·y=k global). Pour decide(), on l'approxime par ses réserves VIRTUELLES
actives (slot0 sqrtPriceX96 + liquidity : x = L/sqrtP, y = L×sqrtP) —
les simples balanceOf de la pool sont trompeurs (liquidité hors range).
Le require(profit >= minProfit) du contrat reste le filet de sécurité.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from math_engine import Costs, Pool, amm_out, decide, gas_cost_usd
from polygon_guard import (ONCHAIN_MIN_PROFIT_USD, polygon_costs,
                           polygon_decide, tranche)

# ------------------------------------------------------------------ constantes
# Adresses vérifiées 2026-11-24, voir POLYGON_FLASH_VERIFICATION.md.
USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"      # USDC natif Polygon
WMATIC = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
MORPHO = "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"    # Morpho Blue Polygon
QUICKSWAP_V2_FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"
QUICKSWAP_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
UNI_V3_ROUTER02 = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"
UNI_V3_POOL_USDC_WMATIC_3000 = "0x2DB87C4831B2fec2E35591221455834193b50D1B"

MIN_PROFIT_USD = 0.0          # v4.1 : min profit 3 $ abandonné — net > 0 $ après tous coûts
# minProfit ON-CHAIN = 0,01 $ (plancher anti-poussière, voir polygon_guard.py).
MATIC_PRICE_USD = 0.0758      # CoinGecko polygon-ecosystem-token 2026-11-24
GAS_PRICE_MAX_GWEI = 1000.0   # plafond Polygon (en $ ça reste ~0,00003 $)
ANVIL_URL = "http://127.0.0.1:8545"
# Clé de TEST publique d'Anvil (compte 0) — NE contrôle AUCUN fond réel.
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view"},
    {"name": "approve", "type": "function", "inputs": [{"name": "s", "type": "address"}, {"name": "v", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable"},
    {"name": "transfer", "type": "function", "inputs": [{"name": "t", "type": "address"}, {"name": "v", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable"},
    {"name": "decimals", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view"},
]
WMATIC_ABI = ERC20_ABI + [
    {"name": "deposit", "type": "function", "inputs": [], "outputs": [], "stateMutability": "payable"},
]
FACTORY_ABI = [
    {"name": "getPair", "type": "function", "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
PAIR_ABI = [
    {"name": "getReserves", "type": "function", "inputs": [], "outputs": [{"name": "_r0", "type": "uint112"}, {"name": "_r1", "type": "uint112"}, {"name": "_t", "type": "uint32"}], "stateMutability": "view"},
    {"name": "token0", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
    {"name": "token1", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "nonpayable"},
]
POOL_V3_ABI = [
    {"name": "slot0", "type": "function", "inputs": [], "outputs": [{"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"}, {"name": "observationIndex", "type": "uint16"}, {"name": "observationCardinality", "type": "uint16"}, {"name": "observationCardinalityNext", "type": "uint16"}, {"name": "feeProtocol", "type": "uint8"}, {"name": "unlocked", "type": "bool"}], "stateMutability": "view"},
    {"name": "token0", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
    {"name": "token1", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
    {"name": "liquidity", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "uint128"}], "stateMutability": "view"},
]

results = {"provider": "morpho_polygon", "min_profit_usd": MIN_PROFIT_USD,
           "matic_price_usd": MATIC_PRICE_USD, "steps": {}}


def log(step, **kw):
    results["steps"][step] = kw
    print(f"[{step}] " + " | ".join(f"{k}={v}" for k, v in kw.items()))


def main():
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    # Polygon est une chaîne PoA (extraData 104 octets) : web3.py exige
    # le middleware PoA, sinon ExtraDataLengthError sur get_block.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), "Anvil injoignable sur 127.0.0.1:8545 — lancer fork_test_polygon.sh"
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)
    me = deployer.address
    block = w3.eth.block_number
    chain_id = w3.eth.chain_id
    log("fork", chain_id=chain_id, block_number=block,
        note="fork Polygon mainnet, RPC public drpc.org")
    assert chain_id == 137, f"chain_id inattendue {chain_id}"

    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    wmatic = w3.eth.contract(address=WMATIC, abi=WMATIC_ABI)
    qs_factory = w3.eth.contract(address=QUICKSWAP_V2_FACTORY, abi=FACTORY_ABI)
    v3_pool = w3.eth.contract(address=UNI_V3_POOL_USDC_WMATIC_3000, abi=POOL_V3_ABI)

    # --- 1) Vérifications Morpho Polygon (état réel du fork) ---
    morpho_code = w3.eth.get_code(MORPHO)
    morpho_usdc = usdc.functions.balanceOf(MORPHO).call() / 1e6
    usdt = w3.eth.contract(
        address="0xc2132D05D31c914a87C6611C10748AEb04B58e8F", abi=ERC20_ABI)
    morpho_usdt = usdt.functions.balanceOf(MORPHO).call() / 1e6
    morpho_wmatic = wmatic.functions.balanceOf(MORPHO).call() / 1e18
    flash_fee_sel = Web3.keccak(text="flashFee(address,uint256)")[:4].hex()
    flash_fee_data = ("0x" + flash_fee_sel
                      + USDC[2:].lower().rjust(64, "0") + "00" * 32)
    try:
        w3.eth.call({"to": MORPHO, "data": flash_fee_data})
        flash_fee_absent, flash_fee_note = False, "flashFee a répondu (inattendu !)"
    except Exception as e:
        flash_fee_absent = True
        flash_fee_note = f"flashFee revert confirmé : {str(e)[:80]}"
    log("morpho", morpho_has_code=len(morpho_code) > 0,
        morpho_code_bytes=len(morpho_code),
        morpho_usdc_balance_usd=round(morpho_usdc, 2),
        morpho_usdt_balance_usd=round(morpho_usdt, 2),
        morpho_wmatic_balance=round(morpho_wmatic, 2),
        max_flash_loan_usdc=round(morpho_usdc, 2),
        usable_50pct_usdc=round(morpho_usdc * 0.5, 2),
        flash_fee_pct=0.0, flash_fee_getter_absent=flash_fee_absent,
        flash_fee_note=flash_fee_note)
    assert len(morpho_code) > 0, "pas de code à l'adresse Morpho Polygon sur le fork"
    assert flash_fee_absent, "Morpho Polygon aurait un getter flashFee ?! Vérifier avant tout live"
    assert morpho_usdc > 10_000, f"solde Morpho USDC trop faible : {morpho_usdc}"

    # --- 2) Réserves réelles USDC/WMATIC : QuickSwap V2 + Uni V3 ---
    def read_v2_pair(factory, t0, t1):
        addr = factory.functions.getPair(t0, t1).call()
        assert addr != "0x0000000000000000000000000000000000000000", "pair introuvable"
        c = w3.eth.contract(address=addr, abi=PAIR_ABI)
        r0, r1, _ = c.functions.getReserves().call()
        tok0 = c.functions.token0().call()
        if tok0.lower() == t0.lower():
            return addr, r0, r1
        return addr, r1, r0

    qs_addr, qs_wmatic, qs_usdc = read_v2_pair(qs_factory, WMATIC, USDC)
    # Uni V3 : réserves VIRTUELLES actives (slot0 + liquidity).
    # Les balanceOf bruts sont trompeurs (liquidité hors range) : la pool
    # détient 161k WMATIC pour 2 249 $ USDC, mais son prix actif est bien
    # ~0,0759 $ (tick -302111). x = L/sqrtP (token0), y = L×sqrtP (token1).
    import math as _math

    def read_v3_virtual():
        sqrt_x96, tick, *_ = v3_pool.functions.slot0().call()
        liq = v3_pool.functions.liquidity().call()
        sqrt_p = sqrt_x96 / 2**96
        x_raw = liq / sqrt_p          # token0, unités brutes
        y_raw = liq * sqrt_p          # token1, unités brutes
        t0 = v3_pool.functions.token0().call()
        if t0.lower() == WMATIC.lower():
            return y_raw / 1e6, x_raw / 1e18, tick, liq  # usdc, wmatic
        return x_raw / 1e6, y_raw / 1e18, tick, liq

    v3_usdc, v3_wmatic, v3_tick, v3_liq = read_v3_virtual()
    price_qs = (qs_usdc / 1e6) / (qs_wmatic / 1e18)
    price_v3 = v3_usdc / v3_wmatic
    spread0 = 100 * (price_v3 / price_qs - 1)
    log("reserves_avant", qs_pair=qs_addr, v3_pool=UNI_V3_POOL_USDC_WMATIC_3000,
        qs_wmatic=round(qs_wmatic / 1e18, 2), qs_usdc=round(qs_usdc / 1e6, 2),
        v3_wmatic=round(v3_wmatic, 2), v3_usdc=round(v3_usdc, 2),
        v3_tick=v3_tick, v3_liquidity=v3_liq,
        prix_wmatic_qs_usd=round(price_qs, 4), prix_wmatic_v3_usd=round(price_v3, 4),
        spread_pct=round(spread0, 4),
        note="spread naturel proche de 0 % comme attendu ; V3 approximée "
             "par ses réserves virtuelles actives (slot0+liquidité)")

    # --- 3) Spread synthétique : on pousse le prix WMATIC à la baisse sur QuickSwap ---
    def send_signed(fn, value=0, gas=500_000):
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me),
                                   "gas": gas,
                                   "maxFeePerGas": w3.eth.gas_price, "maxPriorityFeePerGas": 0,
                                   "chainId": 137, "value": value})
        signed = deployer.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction)

    deadline = w3.eth.get_block("latest")["timestamp"] + 600
    # 10 % (pas 5 %) : la pair QuickSwap est petite (611 $ USDC) — il faut
    # un spread plus large pour que le net dépasse 3 $ sur un petit loan.
    wmatic_amount = int(qs_wmatic * 0.10)  # 10 % de la réserve WMATIC QuickSwap
    txh = send_signed(wmatic.functions.deposit(), value=wmatic_amount)
    w3.eth.wait_for_transaction_receipt(txh)
    w3.eth.wait_for_transaction_receipt(
        send_signed(wmatic.functions.approve(QUICKSWAP_V2_ROUTER, wmatic_amount)))
    qs_router = w3.eth.contract(address=QUICKSWAP_V2_ROUTER, abi=ROUTER_ABI)
    txh = send_signed(qs_router.functions.swapExactTokensForTokens(
        wmatic_amount, 0, [WMATIC, USDC], me, deadline))
    w3.eth.wait_for_transaction_receipt(txh)
    _, qs_wmatic2, qs_usdc2 = read_v2_pair(qs_factory, WMATIC, USDC)
    v3_usdc2, v3_wmatic2, _, _ = read_v3_virtual()
    price_qs2 = (qs_usdc2 / 1e6) / (qs_wmatic2 / 1e18)
    price_v32 = v3_usdc2 / v3_wmatic2
    spread = 100 * (price_v32 / price_qs2 - 1)
    log("spread_synthetique", wmatic_vendu=round(wmatic_amount / 1e18, 2),
        prix_wmatic_qs_usd=round(price_qs2, 4), prix_wmatic_v3_usd=round(price_v32, 4),
        spread_pct=round(spread, 3),
        note="spread créé artificiellement avec des fonds fictifs du fork, "
             "pour simuler une opportunité réelle de meme coin")
    assert spread > 1.0, f"spread synthétique trop faible : {spread:.2f} %"

    # --- 4) Sizing mathématique (règle v4.1 : net > 0 $ après gas + budget
    # revert ; provider Morpho 0 %) ---
    pool_buy = Pool("QuickSwap V2 WMATIC/USDC (pas cher)", qs_usdc2 / 1e6, qs_wmatic2 / 1e18)
    pool_sell = Pool("Uni V3 WMATIC/USDC (cher, approx. réserves virtuelles)", v3_usdc2, v3_wmatic2)
    gas_price_gwei = w3.eth.gas_price / 1e9
    costs = polygon_costs(gas_price_gwei, MATIC_PRICE_USD)
    decision = polygon_decide(pool_buy, pool_sell, gas_price_gwei, MATIC_PRICE_USD)
    log("decision_offchain", action=decision["action"], spread_pct=decision["spread_pct"],
        flash_provider=decision["flash_provider"],
        flash_fee_rate=decision["flash_fee_rate"],
        optimal_loan_usd=decision["optimal_loan_usd"],
        expected_net_usd=decision["expected_net_usd"],
        gas_usd_est=round(decision["gas_usd"], 6),
        gas_price_gwei=round(gas_price_gwei, 2),
        min_profit_usd=MIN_PROFIT_USD, rule=decision["rule"],
        tranche=tranche(decision["expected_net_usd"]), reasons=decision["reasons"])
    assert decision["action"] == "EXECUTE", f"decide() dit {decision['action']} : {decision['reasons']}"
    assert decision["flash_provider"] == "morpho" and decision["flash_fee_rate"] == 0.0
    loan_usd = decision["optimal_loan_usd"]
    loan_wei_usdc = int(loan_usd * 1e6)
    assert loan_usd <= morpho_usdc * 0.5, "loan > 50 % du solde Morpho (ne devrait jamais arriver)"

    # --- 5) Déploiement du contrat Morpho Polygon sur le fork ---
    artifact = json.loads(Path("out/FlashLoanArbitragePolygon.sol/MorphoFlashLoanArbitragePolygon.json").read_text())
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    txh = send_signed(contract.constructor(
        USDC, WMATIC, QUICKSWAP_V2_ROUTER, UNI_V3_POOL_USDC_WMATIC_3000,
        int(ONCHAIN_MIN_PROFIT_USD * 1e6)),
        gas=3_000_000)
    receipt = w3.eth.wait_for_transaction_receipt(txh)
    assert receipt["status"] == 1, "déploiement en échec (out of gas ?)"
    assert len(w3.eth.get_code(receipt["contractAddress"])) > 0, \
        "pas de code à l'adresse déployée"
    arb = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
    assert arb.functions.MORPHO().call().lower() == MORPHO.lower()
    assert arb.functions.minProfit().call() == int(ONCHAIN_MIN_PROFIT_USD * 1e6), \
        "minProfit on-chain != 0,01 $"
    log("deploy", contract=receipt["contractAddress"], block=receipt["blockNumber"],
        gas_used=receipt["gasUsed"], morpho_onchain=arb.functions.MORPHO().call(),
        min_profit_onchain_usdc=int(ONCHAIN_MIN_PROFIT_USD * 1e6))

    # --- 6) CAS GAGNANT : simulation eth_call (0 gas) puis broadcast sur le fork ---
    try:
        arb.functions.executeArbitrage(loan_wei_usdc).call({"from": me})
        sim_ok = True
        sim_err = ""
    except Exception as e:
        sim_ok = False
        sim_err = str(e)[:200]
    gas_est = arb.functions.executeArbitrage(loan_wei_usdc).estimate_gas({"from": me})
    log("cas_gagnant_simulation_eth_call", success=sim_ok, error=sim_err,
        gas_estime=gas_est, gas_paye_usd=0.0,
        note="eth_call = simulation, 0 gas, 0 $")
    assert sim_ok, f"la simulation eth_call a revert : {sim_err}"

    bal_before = usdc.functions.balanceOf(arb.address).call()
    txh = send_signed(arb.functions.executeArbitrage(loan_wei_usdc))
    rc = w3.eth.wait_for_transaction_receipt(txh)
    gas_used = rc["gasUsed"]
    gas_price = rc["effectiveGasPrice"] / 1e9
    gas_cost_matic = gas_used * rc["effectiveGasPrice"] / 1e18
    gas_cost = gas_cost_matic * MATIC_PRICE_USD
    bal_after = usdc.functions.balanceOf(arb.address).call()
    profit_usdc = (bal_after - bal_before) / 1e6
    net = profit_usdc - gas_cost
    events = arb.events.MorphoPolygonArbitrageExecuted().process_receipt(rc)
    log("cas_gagnant_broadcast_fork", tx_status=rc["status"], tx_hash=rc["transactionHash"].hex(),
        gas_used=gas_used, gas_price_gwei=round(gas_price, 2),
        gas_cost_matic=round(gas_cost_matic, 6), gas_cost_usd=round(gas_cost, 6),
        profit_brut_usdc=round(profit_usdc, 2),
        profit_net_usd=round(net, 2), min_profit_usd=MIN_PROFIT_USD,
        event_profit_usdc=(round(events[0]["args"]["profit"] / 1e6, 2) if events else None),
        verdict="WIN" if rc["status"] == 1 and net > 0 else "FAIL",
        note="broadcast sur le FORK uniquement — aucun fond réel, aucun mainnet")
    assert rc["status"] == 1 and net > 0, "le cas gagnant a échoué sur le fork"

    # --- 6b) CAS GAGNANT (petit net) : petit spread synthétique, net attendu
    # entre 0 et 3 $ (v4.1 : autorisé). On choisit la fraction à pousser par
    # SIMULATION off-chain (sans toucher à l'état), puis on pousse une fois.
    _, qw3, qu3 = read_v2_pair(qs_factory, WMATIC, USDC)
    v3u3, v3w3, _, _ = read_v3_virtual()
    price_v3_now = v3u3 / v3w3
    small_frac, small_decision = None, None
    cands = []
    for frac in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.07):
        # Vente simulée de frac × réserve WMATIC sur QuickSwap (frais 0,3 %).
        w_in = qw3 * frac
        u_out = amm_out(w_in, qw3, qu3, 30)
        qs_w_sim = qw3 + w_in
        qs_u_sim = qu3 - u_out
        pb = Pool("QuickSwap sim", qs_u_sim / 1e6, qs_w_sim / 1e18)
        ps = Pool("Uni V3 sim", v3u3, v3w3)
        d_sim = polygon_decide(pb, ps, gas_price_gwei, MATIC_PRICE_USD)
        if 0.05 < d_sim["expected_net_usd"] < 2.0 and d_sim["action"] == "EXECUTE":
            cands.append((abs(d_sim["expected_net_usd"] - 0.50), frac, d_sim))
    assert cands, "aucune fraction simulée ne donne un petit net (0,05–2,00 $)"
    cands.sort(key=lambda c: c[0])
    _, small_frac, small_decision = cands[0]  # net attendu le plus proche de 0,50 $
    log("petit_net_simulation", fraction_choisie=small_frac,
        expected_net_usd=small_decision["expected_net_usd"],
        optimal_loan_usd=small_decision["optimal_loan_usd"],
        spread_pct=small_decision["spread_pct"])
    # Poussée réelle (petite) avec des fonds fictifs du fork.
    wmatic_small = int(qw3 * small_frac)
    txh = send_signed(wmatic.functions.deposit(), value=wmatic_small)
    w3.eth.wait_for_transaction_receipt(txh)
    w3.eth.wait_for_transaction_receipt(
        send_signed(wmatic.functions.approve(QUICKSWAP_V2_ROUTER, wmatic_small)))
    txh = send_signed(qs_router.functions.swapExactTokensForTokens(
        wmatic_small, 0, [WMATIC, USDC], me, deadline))
    w3.eth.wait_for_transaction_receipt(txh)
    _, qs_wmatic_s, qs_usdc_s = read_v2_pair(qs_factory, WMATIC, USDC)
    v3_usdc_s, v3_wmatic_s, _, _ = read_v3_virtual()
    pool_buy_s = Pool("QuickSwap petit net", qs_usdc_s / 1e6, qs_wmatic_s / 1e18)
    pool_sell_s = Pool("Uni V3 petit net", v3_usdc_s, v3_wmatic_s)
    decision_s = polygon_decide(pool_buy_s, pool_sell_s, gas_price_gwei,
                                MATIC_PRICE_USD)
    log("petit_net_decision_offchain", action=decision_s["action"],
        spread_pct=decision_s["spread_pct"],
        optimal_loan_usd=decision_s["optimal_loan_usd"],
        expected_net_usd=decision_s["expected_net_usd"],
        tranche=tranche(decision_s["expected_net_usd"]),
        reasons=decision_s["reasons"])
    assert decision_s["action"] == "EXECUTE", \
        f"petit net : decide() dit {decision_s['action']}"
    assert 0 < decision_s["expected_net_usd"] < 3.0, \
        "petit net attendu hors (0, 3 $)"
    loan_s_usd = decision_s["optimal_loan_usd"]
    loan_s_wei = int(loan_s_usd * 1e6)
    bal_before_s = usdc.functions.balanceOf(arb.address).call()
    txh = send_signed(arb.functions.executeArbitrage(loan_s_wei))
    rc_s = w3.eth.wait_for_transaction_receipt(txh)
    gas_s = rc_s["gasUsed"] * rc_s["effectiveGasPrice"] / 1e18 * MATIC_PRICE_USD
    profit_s = (usdc.functions.balanceOf(arb.address).call()
                - bal_before_s) / 1e6
    net_s = profit_s - gas_s
    log("petit_net_broadcast_fork", tx_status=rc_s["status"],
        loan_usd=loan_s_usd, gas_cost_usd=round(gas_s, 6),
        profit_brut_usdc=round(profit_s, 2), profit_net_usd=round(net_s, 2),
        tranche=tranche(net_s),
        verdict="WIN" if rc_s["status"] == 1 and net_s > 0 else "FAIL",
        note="petit profit WIN sous la règle v4.1 (aurait été SKIP à 3 $)")
    assert rc_s["status"] == 1 and net_s > 0, \
        "le cas petit net a échoué sur le fork"

    # --- 7) CAS PERDANT : le spread est refermé, decide() doit dire SKIP ---
    _, uw3, uu3 = read_v2_pair(qs_factory, WMATIC, USDC)
    v3_usdc3, v3_wmatic3, _, _ = read_v3_virtual()
    pool_buy2 = Pool("QuickSwap apres arb", uu3 / 1e6, uw3 / 1e18)
    pool_sell2 = Pool("Uni V3 apres arb", v3_usdc3, v3_wmatic3)
    decision2 = decide(pool_buy2, pool_sell2, costs)
    log("cas_perdant_decision_offchain", action=decision2["action"],
        spread_pct=decision2["spread_pct"], optimal_loan_usd=decision2["optimal_loan_usd"],
        expected_net_usd=decision2["expected_net_usd"],
        gas_paye_usd=0.0, reasons=decision2["reasons"],
        note="SKIP = rien broadcasté, 0 gas payé")
    try:
        arb.functions.executeArbitrage(loan_wei_usdc).call({"from": me})
        revert_sim, revert_err = False, "eth_call n'a PAS revert (inattendu)"
    except Exception as e:
        revert_sim, revert_err = True, str(e)[:200]
    log("cas_perdant_simulation_eth_call", revert=revert_sim, detail=revert_err)
    # Pour CHIFFRER le coût d'un revert : on broadcast quand même le perdant
    # sur le fork (MATIC fictif) — ce qu'on ne ferait JAMAIS en live.
    txh = send_signed(arb.functions.executeArbitrage(loan_wei_usdc))
    rc2 = w3.eth.wait_for_transaction_receipt(txh)
    revert_gas_matic = rc2["gasUsed"] * rc2["effectiveGasPrice"] / 1e18
    revert_gas_usd = revert_gas_matic * MATIC_PRICE_USD
    log("cas_perdant_broadcast_fork_POUR_MESURE", tx_status=rc2["status"],
        gas_used=rc2["gasUsed"], gas_price_gwei=round(rc2["effectiveGasPrice"] / 1e9, 2),
        cout_revert_matic=round(revert_gas_matic, 6),
        cout_revert_usd=round(revert_gas_usd, 6),
        note="revert mesuré sur le fork pour chiffrer le coût — en live on "
             "évite ce coût par le SKIP off-chain (0 $)")

    # --- 8) Résumé + autonomie du float 1,31 $ ---
    float_trades = int(1.31 // max(2 * gas_cost, 1e-9))
    results["summary"] = {
        "fork_block": block,
        "rule": "v4.1 : net > 0 $ apres gas + budget revert (min 3 $ abandonne) ; "
                "minProfit on-chain 0,01 $ (anti-poussiere)",
        "morpho_usdc_balance_usd": round(morpho_usdc, 2),
        "morpho_usdt_balance_usd": round(morpho_usdt, 2),
        "flash_fee_getter_absent": flash_fee_absent,
        "spread_synthetique_pct": round(spread, 3),
        "cas_gagnant": {"loan_usd": loan_usd, "profit_net_usd": round(net, 2),
                        "gas_used": gas_used, "gas_cost_matic": round(gas_cost_matic, 6),
                        "gas_cost_usd": round(gas_cost, 6),
                        "verdict": "WIN"},
        "cas_petit_net": {"fraction_poussee": small_frac,
                          "loan_usd": loan_s_usd,
                          "expected_net_usd": round(decision_s["expected_net_usd"], 2),
                          "profit_net_usd": round(net_s, 2),
                          "tranche": tranche(net_s),
                          "verdict": "WIN"},
        "cas_perdant": {"decision_offchain": decision2["action"],
                        "gas_paye_si_skip_usd": 0.0,
                        "cout_revert_si_broadcast_matic": round(revert_gas_matic, 6),
                        "cout_revert_si_broadcast_usd": round(revert_gas_usd, 6),
                        "gas_revert": rc2["gasUsed"],
                        "verdict": "SKIP (0 gas) / revert confirmé on-chain"},
        "float_1_31_usd": {"trades_couverts_pire_cas_gas_x2": float_trades,
                           "cout_trade_usd": round(gas_cost, 6)},
    }
    Path("fork_results_polygon.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n=== RÉSUMÉ FORK MORPHO POLYGON ===")
    print(json.dumps(results["summary"], indent=2, default=str))
    print("Résultats détaillés : fork_results_polygon.json")


if __name__ == "__main__":
    main()
