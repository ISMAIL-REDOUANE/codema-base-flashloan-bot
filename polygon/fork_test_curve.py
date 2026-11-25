#!/usr/bin/env python3
"""
fork_test_curve.py — Test v4.5 de la jambe Curve sur fork Anvil Polygon.

AUCUN fond réel, AUCUNE clé privée d'utilisateur, AUCUN broadcast mainnet.
Tout se passe sur un fork local jetable (anvil --fork-url <RPC Polygon>).
La seule clé utilisée est la clé de TEST publique d'Anvil (compte 0).

RÉSULTAT ATTENDU (découvert par ce test, 2026-11-25) : la route est
INEXÉCUTABLE — pas à cause du contrat, mais parce que la jambe Curve
revert dans Aave v2. La quote dit WIN (papier), l'exécution revert :
  exchange_underlying -> LendingPool.deposit(USDT) -> ValidationLogic
  -> revert Error('3') = VL_RESERVE_FROZEN (Aave v2 USDT gelé).
Les réserves DAI / USDC.e / USDT d'Aave v2 Polygon sont TOUTES gelées
(gouvernance : v2 dépréciée au profit de v3). Il n'existe pas d'autre
pool Curve sur Polygon (API Curve : 2 pools seulement, amWBTC/renBTC
et amDAI/amUSDC/amUSDT).

Ce que le test prouve, dans l'ordre :
  1. L'état du fork est réel : Morpho Blue Polygon + solde USDC natif,
     underlying_coins(1) du am3pool == USDC.e (la correction).
  2. Aave v2 gelé : flags isFrozen lus on-chain (DAI/USDC.e/USDT = 1).
  3. Quote live de la route corrigée au bloc du fork : WIN sur papier
     (net +1,01 / +5,08 / +19,20 $ à 1k/5k/20k, bloc 97 922 005).
  4. Le contrat CurveFlashArbPolygon déployé sur le fork.
  5. EXÉCUTION 5 000 $ : eth_call PUIS broadcast -> REVERT avec la
     raison '3' (VL_RESERVE_FROZEN), gas du revert MESURÉ (~489k unités).
     La raison '3' ne peut venir que du deposit Aave dans la jambe
     Curve — donc Morpho + les 2 jambes V3 ont RÉUSSI avant (prouvé
     aussi par la trace `cast trace` : swaps V3 + callbacks OK).
  6. GARDE loan trop gros : 100 000 $ > solde Morpho (75 540 $) ->
     revert chez Morpho (avant tout swap), gas mesuré.
  7. GARDE off-chain : route_guard_decision() dit SKIP (aave_v2_frozen)
     même avec net > 0 — c'est le garde qui empêche de brûler du gas.
     (Le require minProfit on-chain est inatteignable tant que la jambe
     Curve est bloquée : il est couvert par les tests unitaires
     test_curve_leg.py, pas ici.)
  8. Fenêtre après : re-quote — l'edge papier survit (le pool Curve
     n'a pas bougé puisqu'aucun trade n'a abouti).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from curve_route import (AAVE_VL_RESERVE_FROZEN, CURVE_AM3POOL,
                         GAS_UNITS_4SWAP, MATIC_PRICE_USD, MORPHO_POLYGON,
                         ONCHAIN_MIN_PROFIT_USD, POOL_USDC_USDCE_100,
                         POOL_USDCE_USDT_100, USDC_NATIVE, USDCE, USDT,
                         check_aave_frozen, quote_route_4swap_usdc,
                         route_guard_decision)

# ------------------------------------------------------------------ constantes
MATIC_PRICE = MATIC_PRICE_USD
ANVIL_URL = "http://127.0.0.1:8545"
# Clé de TEST publique d'Anvil (compte 0) — NE contrôle AUCUN fond réel.
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view"},
]

results = {"route": "curve_4swap_corrected", "min_profit_usd": ONCHAIN_MIN_PROFIT_USD,
           "matic_price_usd": MATIC_PRICE, "steps": {}}


def trace_revert_reason(w3, tx_hash_hex):
    """Raison du revert le plus profond, via debug_traceTransaction
    (callTracer) sur le fork Anvil. web3.py ne remonte que
    ('execution reverted', '0x') : la raison est dans le sous-appel.
    Retourne la chaîne Error(string) décodée (ex. '3'), ou None."""
    resp = w3.provider.make_request(
        "debug_traceTransaction", [tx_hash_hex, {"tracer": "callTracer"}])
    res = resp.get("result") or {}

    def deepest(n):
        best = None
        for c in n.get("calls", []):
            r = deepest(c)
            if r is not None:
                best = r
        out = n.get("output") or ""
        if n.get("error") and out.startswith("0x08c379a0"):
            raw = bytes.fromhex(out[2:])
            ln = int.from_bytes(raw[36:68], "big")
            return raw[68:68 + ln].decode(errors="replace")
        return best

    return deepest(res)


def log(step, **kw):
    results["steps"][step] = kw
    print(f"[{step}] " + " | ".join(f"{k}={v}" for k, v in kw.items()))


def main():
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), "Anvil injoignable sur 127.0.0.1:8545 — lancer fork_test_curve.sh"
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)
    me = deployer.address
    block = w3.eth.block_number
    chain_id = w3.eth.chain_id
    log("fork", chain_id=chain_id, block_number=block,
        note="fork Polygon mainnet, RPC public drpc.org")
    assert chain_id == 137, f"chain_id inattendue {chain_id}"

    usdc = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)

    # --- 1) Morpho Polygon (état réel du fork) ---
    morpho_code = w3.eth.get_code(MORPHO_POLYGON)
    morpho_usdc = usdc.functions.balanceOf(MORPHO_POLYGON).call() / 1e6
    log("morpho", morpho_has_code=len(morpho_code) > 0,
        morpho_code_bytes=len(morpho_code),
        morpho_usdc_balance_usd=round(morpho_usdc, 2),
        usable_50pct_usdc=round(morpho_usdc * 0.5, 2))
    assert len(morpho_code) > 0, "pas de code Morpho sur le fork"
    assert morpho_usdc > 10_000, f"solde Morpho USDC trop faible : {morpho_usdc}"

    # --- 1b) Curve : underlying_coins(1) == USDC.e (la correction) ---
    cabi = [
        {"name": "underlying_coins", "outputs": [{"type": "address"}], "inputs": [{"type": "uint256", "name": "i"}], "stateMutability": "view", "type": "function"},
        {"name": "fee", "outputs": [{"type": "uint256"}], "inputs": [], "stateMutability": "view", "type": "function"},
    ]
    curve = w3.eth.contract(address=CURVE_AM3POOL, abi=cabi)
    uc1 = curve.functions.underlying_coins(1).call()
    log("curve_pool", underlying_1=uc1,
        underlying_1_is_usdce=uc1.lower() == USDCE.lower(),
        underlying_1_is_usdc_native=uc1.lower() == USDC_NATIVE.lower(),
        fee_pct=curve.functions.fee().call() / 1e10,
        note="underlying(1) DOIT être USDC.e (0x2791…) — c'est la correction")
    assert uc1.lower() == USDCE.lower(), "underlying(1) != USDC.e"

    # --- 2) Aave v2 gelé (le bloqueur) ---
    frozen = check_aave_frozen(w3)
    log("aave_v2_frozen", block=frozen["block"], frozen=frozen["frozen"],
        any_frozen=frozen["any_frozen"],
        note="isFrozen=1 sur DAI/USDC.e/USDT : tout deposit Aave v2 revert")
    assert frozen["any_frozen"], "Aave v2 ne serait plus gelé ? Re-vérifier"

    # --- 3) Quote live de la route corrigée au bloc du fork (papier) ---
    gas_price_gwei = w3.eth.gas_price / 1e9
    quotes = {}
    for amt in (1_000.0, 5_000.0, 20_000.0):
        q = quote_route_4swap_usdc(amt, w3, gas_price_gwei=gas_price_gwei)
        quotes[amt] = q
        log(f"quote_live_{int(amt)}", block=q["block"], loan_usd=amt,
            leg0=q["leg0_usdc_to_usdce"], leg1=q["leg1_usdce_to_usdt"],
            leg2_curve_usdce=q["leg2_usdt_to_usdce_curve"],
            leg3=q["leg3_usdce_to_usdc"], gross_usd=q["gross_usd"],
            gas_budget_usd=q["gas_budget_usd"], net_usd=q["net_usd"],
            min_dy_usdce=q["min_dy_usdce"], verdict=q["verdict"])
    assert all(q["verdict"] == "WIN" for q in quotes.values()), \
        "la fenêtre papier est fermée au bloc du fork"

    # --- 3b) Garde off-chain : SKIP malgré net > 0 (Aave gelé) ---
    for amt, q in quotes.items():
        d = route_guard_decision(q["net_usd"], frozen["any_frozen"])
        log(f"garde_offchain_{int(amt)}", action=d["action"], reason=d["reason"],
            net_usd=q["net_usd"], detail=d["detail"])
        assert d["action"] == "SKIP" and d["reason"] == "aave_v2_frozen"

    # --- 4) Déploiement du contrat Curve sur le fork ---
    def send_signed(fn, value=0, gas=2_000_000):
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me),
                                   "gas": gas,
                                   "maxFeePerGas": w3.eth.gas_price, "maxPriorityFeePerGas": 0,
                                   "chainId": 137, "value": value})
        signed = deployer.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction)

    artifact = json.loads(Path("out/CurveFlashArbPolygon.sol/CurveFlashArbPolygon.json").read_text())
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    txh = send_signed(contract.constructor(
        USDC_NATIVE, USDCE, USDT, POOL_USDC_USDCE_100, POOL_USDCE_USDT_100,
        CURVE_AM3POOL, int(ONCHAIN_MIN_PROFIT_USD * 1e6)),
        gas=3_000_000)
    receipt = w3.eth.wait_for_transaction_receipt(txh)
    assert receipt["status"] == 1, "déploiement en échec"
    assert len(w3.eth.get_code(receipt["contractAddress"])) > 0
    arb = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
    assert arb.functions.MORPHO().call().lower() == MORPHO_POLYGON.lower()
    assert arb.functions.minProfit().call() == int(ONCHAIN_MIN_PROFIT_USD * 1e6)
    log("deploy", contract=receipt["contractAddress"], block=receipt["blockNumber"],
        gas_used=receipt["gasUsed"],
        min_profit_onchain_usdc=int(ONCHAIN_MIN_PROFIT_USD * 1e6))

    # --- 5) EXÉCUTION 5 000 $ : revert attendu VL_RESERVE_FROZEN ('3') ---
    q5 = quotes[5_000.0]
    loan5 = int(5_000 * 1e6)
    min_dy5 = q5["min_dy_usdce"]
    try:
        arb.functions.executeArbitrage(loan5, min_dy5).call({"from": me})
        sim_revert, sim_err = False, "eth_call n'a PAS revert (inattendu)"
    except Exception as e:
        sim_revert, sim_err = True, str(e)[:300]
    log("execution_5k_simulation_eth_call", revert=sim_revert, detail=sim_err,
        note="revert attendu : jambe Curve -> Aave v2 gelé. web3.py ne "
             "remonte que ('execution reverted', '0x') : la raison est "
             "dans le sous-appel, lue par debug_traceTransaction ci-après.")
    assert sim_revert, "l'exécution aurait dû revert (Aave v2 gelé)"
    txh = send_signed(arb.functions.executeArbitrage(loan5, min_dy5))
    rc = w3.eth.wait_for_transaction_receipt(txh)
    revert_gas_usd = rc["gasUsed"] * rc["effectiveGasPrice"] / 1e18 * MATIC_PRICE
    reason = trace_revert_reason(w3, rc["transactionHash"].hex())
    log("execution_5k_broadcast_fork", tx_status=rc["status"],
        tx_hash=rc["transactionHash"].hex(), block=rc["blockNumber"],
        gas_used=rc["gasUsed"], gas_price_gwei=round(rc["effectiveGasPrice"] / 1e9, 2),
        cout_revert_usd=round(revert_gas_usd, 6),
        raison_revert_profond=reason,
        raison_attendue="3 = VL_RESERVE_FROZEN (Aave v2 Errors.sol)",
        note="broadcast sur le FORK pour mesurer le coût du revert — "
             "en live, le garde off-chain DOIT dropper avant (0 $). "
             "La raison '3' ne peut venir que du deposit Aave dans la "
             "jambe Curve : Morpho + les 2 jambes V3 ont donc RÉUSSI avant.")
    assert rc["status"] == 0, "l'exécution aurait dû revert sur le fork"
    assert reason == AAVE_VL_RESERVE_FROZEN, \
        f"raison attendue '3' (VL_RESERVE_FROZEN), obtenue : {reason!r}"
    assert 400_000 < rc["gasUsed"] < 600_000, (
        f"gas du revert inattendu : {rc['gasUsed']} (attendu ~489k, "
        "signature d'un revert profond, après les 2 swaps V3)")
    # Le revert est atomique : le contrat n'a rien gardé, Morpho rien perdu.
    assert usdc.functions.balanceOf(arb.address).call() == 0, \
        "le contrat aurait dû rester à 0 USDC après revert"

    # --- 6) GARDE loan trop gros : 100 000 $ > solde Morpho ---
    try:
        arb.functions.executeArbitrage(int(100_000 * 1e6), min_dy5).call({"from": me})
        sim_revert_c, err_c = False, "eth_call n'a PAS revert (inattendu)"
    except Exception as e:
        sim_revert_c, err_c = True, str(e)[:200]
    txh = send_signed(arb.functions.executeArbitrage(int(100_000 * 1e6), min_dy5))
    rc_c = w3.eth.wait_for_transaction_receipt(txh)
    reason_c = trace_revert_reason(w3, rc_c["transactionHash"].hex())
    log("garde_loan_trop_gros", eth_call_revert=sim_revert_c, detail=err_c,
        tx_hash=rc_c["transactionHash"].hex(),
        raison_revert_profond=reason_c,
        tx_status=rc_c["status"], gas_used=rc_c["gasUsed"],
        cout_revert_usd=round(rc_c["gasUsed"] * rc_c["effectiveGasPrice"] / 1e18 * MATIC_PRICE, 6),
        loan_demande_usd=100_000, morpho_usdc=round(morpho_usdc, 2),
        note="revert attendu chez Morpho (transfert > solde), avant tout swap")
    assert rc_c["status"] == 0, "loan > solde Morpho aurait dû revert"

    # --- 7) Fenêtre après : re-quote (l'edge papier survit) ---
    post = {}
    for amt in (1_000.0, 5_000.0, 20_000.0):
        q = quote_route_4swap_usdc(amt, w3, gas_price_gwei=gas_price_gwei)
        post[amt] = q
        log(f"fenetre_apres_{int(amt)}", block=q["block"],
            gross_usd=q["gross_usd"], net_usd=q["net_usd"], verdict=q["verdict"],
            note="l'edge papier survit : aucun trade n'a abouti, le pool "
                 "Curve n'a pas bougé")

    # --- 8) Résumé ---
    results["summary"] = {
        "fork_block": block,
        "verdict": "ROUTE INEXÉCUTABLE — Aave v2 gelé (VL_RESERVE_FROZEN '3'). "
                   "La quote dit WIN (papier), l'exécution revert. "
                   "Le contrat et les jambes V3 + Morpho fonctionnent "
                   "(prouvé par la trace : swaps V3 + callbacks OK avant Curve).",
        "morpho_usdc_balance_usd": round(morpho_usdc, 2),
        "gas_price_gwei": round(gas_price_gwei, 2),
        "aave_v2_frozen": frozen,
        "quotes_papier": {str(k): {"net_usd": v["net_usd"], "verdict": v["verdict"]}
                          for k, v in quotes.items()},
        "execution_5k": {"tx_hash": rc["transactionHash"].hex(),
                         "block": rc["blockNumber"],
                         "tx_status": rc["status"],
                         "gas_used": rc["gasUsed"],
                         "cout_revert_usd": round(revert_gas_usd, 6),
                         "raison": "VL_RESERVE_FROZEN ('3') — prouvée par "
                                   "debug_traceTransaction (callTracer) : "
                                   "le revert le plus profond est le deposit "
                                   "USDT d'Aave v2, appelé par le am3pool"},
        "garde_loan_trop_gros": {"tx_hash": rc_c["transactionHash"].hex(),
                                 "raison_revert_profond": reason_c,
                                 "tx_status": rc_c["status"],
                                 "gas_used": rc_c["gasUsed"],
                                 "cout_revert_usd": round(rc_c["gasUsed"] * rc_c["effectiveGasPrice"] / 1e18 * MATIC_PRICE, 6)},
        "gas_estime_750k_vs_revert_mesure": {
            "estime_unites_trade_complet": GAS_UNITS_4SWAP,
            "mesure_unites_revert": rc["gasUsed"],
            "note": "le trade complet n'a jamais abouti : le gas d'un trade "
                    "réussi reste INCONNU (estimation 750k non mesurée).",
        },
        "fenetre_apres": {str(k): {"net_usd": v["net_usd"], "verdict": v["verdict"]}
                          for k, v in post.items()},
    }
    Path("curve_fork_results.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n=== RÉSUMÉ FORK CURVE 4 SWAPS ===")
    print(json.dumps(results["summary"], indent=2, default=str))
    print("Résultats détaillés : curve_fork_results.json")


if __name__ == "__main__":
    main()
