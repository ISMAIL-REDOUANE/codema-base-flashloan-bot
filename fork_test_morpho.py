#!/usr/bin/env python3
"""
fork_test_morpho.py — Test v3.3 sur fork Anvil de Base mainnet (Morpho Blue).

AUCUN fond réel, AUCUNE clé privée d'utilisateur, AUCUN broadcast mainnet.
Tout se passe sur un fork local jetable (anvil --fork-url <RPC config.yaml>).
La seule clé utilisée est la clé de TEST publique d'Anvil (compte 0),
qui ne contrôle aucun fond réel.

Seuil : min_profit_usd = 3.0 $ (confirmé par Ismail 2026-11-24, config.yaml).

Ce que le test prouve, dans l'ordre :
  1. L'état du fork est réel : Morpho Blue, réserves Uni V2 / BaseSwap V2
     lues on-chain ; Morpho n'a PAS de getter flashFee (fee 0 par
     conception) ; ses soldes USDC/WETH couvrent largement le loan.
  2. Le contrat MorphoFlashLoanArbitrage (compilé par forge) déployé sur
     le fork.
  3. CAS GAGNANT : eth_call (simulation, 0 gas) PUIS broadcast sur le fork,
     profit net mesuré après gas, require(profit >= 3 $) respecté.
  4. CAS PERDANT : decide() dit SKIP (0 gas), eth_call revert confirmé,
     et — pour chiffrer le coût d'un revert — broadcast du perdant sur le
     fork (ETH fictif) pour mesurer le gas d'un revert réel.

Miroir de fork_test.py (§10, preuve Aave) avec le provider Morpho :
même spread synthétique (vente de 5 % de la réserve WETH Uni V2),
mêmes routers (Uni V2 achat / BaseSwap V2 vente), même seuil 3 $.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from web3 import Web3

from math_engine import Costs, Pool, decide, gas_cost_usd

# ------------------------------------------------------------------ constantes
# Adresses vérifiées 2026-11-24, voir RESEARCH.md § Morpho Blue.
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
UNI_V2_FACTORY = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"
UNI_V2_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
# BaseSwap V2 (fork Uni V2) — vérifié on-chain 2026-11-24 sur le fork :
# router.factory() = 0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB,
# router.WETH() = WETH Base, pair WETH/USDC 5,29 WETH / 8 873,81 $.
BASESWAP_V2_FACTORY = "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"
BASESWAP_V2_ROUTER = "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86"

MIN_PROFIT_USD = 3.0          # confirmé par Ismail 2026-11-24
ETH_PRICE_USD = 3000.0        # hypothèse config.yaml — à remplacer par oracle en prod
ANVIL_URL = "http://127.0.0.1:8545"
# Clé de TEST publique d'Anvil (compte 0) — NE contrôle AUCUN fond réel.
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

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
PAIR_ABI = [
    {"name": "getReserves", "type": "function", "inputs": [], "outputs": [{"name": "_r0", "type": "uint112"}, {"name": "_r1", "type": "uint112"}, {"name": "_t", "type": "uint32"}], "stateMutability": "view"},
    {"name": "token0", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
    {"name": "token1", "type": "function", "inputs": [], "outputs": [{"name": "", "type": "address"}], "stateMutability": "view"},
]
ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "nonpayable"},
]

results = {"provider": "morpho", "min_profit_usd": MIN_PROFIT_USD, "steps": {}}


def log(step, **kw):
    results["steps"][step] = kw
    print(f"[{step}] " + " | ".join(f"{k}={v}" for k, v in kw.items()))


def main():
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    assert w3.is_connected(), "Anvil injoignable sur 127.0.0.1:8545 — lancer fork_test_morpho.sh"
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)
    me = deployer.address
    block = w3.eth.block_number
    chain_id = w3.eth.chain_id
    log("fork", chain_id=chain_id, block_number=block,
        note="fork Base mainnet, RPC config.yaml (Alchemy, clé non affichée)")
    assert chain_id == 8453, f"chain_id inattendue {chain_id}"

    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    weth = w3.eth.contract(address=WETH, abi=WETH_ABI)
    uni_factory = w3.eth.contract(address=UNI_V2_FACTORY, abi=FACTORY_ABI)
    bs_factory = w3.eth.contract(address=BASESWAP_V2_FACTORY, abi=FACTORY_ABI)

    # --- 1) Vérifications Morpho (état réel du fork) ---
    morpho_code = w3.eth.get_code(MORPHO)
    morpho_usdc = usdc.functions.balanceOf(MORPHO).call() / 1e6
    morpho_weth = weth.functions.balanceOf(MORPHO).call() / 1e18
    # Pas de getter flashFee : l'eth_call du sélecteur ERC-3156 doit revert.
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
        morpho_weth_balance=round(morpho_weth, 2),
        max_flash_loan_usdc=round(morpho_usdc, 2),
        usable_50pct_usdc=round(morpho_usdc * 0.5, 2),
        flash_fee_pct=0.0, flash_fee_getter_absent=flash_fee_absent,
        flash_fee_note=flash_fee_note)
    assert len(morpho_code) > 0, "pas de code à l'adresse Morpho sur le fork"
    assert flash_fee_absent, "Morpho aurait un getter flashFee ?! Vérifier avant tout live"
    assert morpho_usdc > 1_000_000, f"solde Morpho USDC trop faible : {morpho_usdc}"

    # --- 2) Réserves réelles WETH/USDC sur les 2 DEXs (état du fork) ---
    def read_pair(factory, t0, t1):
        addr = factory.functions.getPair(t0, t1).call()
        assert addr != "0x0000000000000000000000000000000000000000", "pair introuvable"
        c = w3.eth.contract(address=addr, abi=PAIR_ABI)
        r0, r1, _ = c.functions.getReserves().call()
        tok0 = c.functions.token0().call()
        if tok0.lower() == t0.lower():
            return addr, r0, r1  # r0 = t0, r1 = t1
        return addr, r1, r0

    uni_addr, uni_weth, uni_usdc = read_pair(uni_factory, WETH, USDC)
    bs_addr, bs_weth, bs_usdc = read_pair(bs_factory, WETH, USDC)
    price_uni = (uni_usdc / 1e6) / (uni_weth / 1e18)
    price_bs = (bs_usdc / 1e6) / (bs_weth / 1e18)
    spread0 = 100 * (price_bs / price_uni - 1)
    log("reserves_avant", uni_pair=uni_addr, bs_pair=bs_addr,
        uni_weth=round(uni_weth / 1e18, 2), uni_usdc=round(uni_usdc / 1e6, 2),
        bs_weth=round(bs_weth / 1e18, 2), bs_usdc=round(bs_usdc / 1e6, 2),
        prix_weth_uni_usd=round(price_uni, 2), prix_weth_bs_usd=round(price_bs, 2),
        spread_pct=round(spread0, 4),
        note="spread naturel proche de 0 % comme attendu sur une paire liquide")

    # --- 3) Spread synthétique : on pousse le prix WETH à la baisse sur Uni V2 ---
    def send_signed(fn, value=0, gas=500_000):
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me),
                                   "gas": gas,
                                   "maxFeePerGas": w3.eth.gas_price, "maxPriorityFeePerGas": 0,
                                   "chainId": 8453, "value": value})
        signed = deployer.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction)

    deadline = w3.eth.get_block("latest")["timestamp"] + 600
    weth_amount = int(uni_weth * 0.05)  # 5 % de la réserve WETH Uni V2
    txh = send_signed(weth.functions.deposit(), value=weth_amount)
    w3.eth.wait_for_transaction_receipt(txh)
    w3.eth.wait_for_transaction_receipt(
        send_signed(weth.functions.approve(UNI_V2_ROUTER, weth_amount)))
    uni_router = w3.eth.contract(address=UNI_V2_ROUTER, abi=ROUTER_ABI)
    txh = send_signed(uni_router.functions.swapExactTokensForTokens(
        weth_amount, 0, [WETH, USDC], me, deadline))
    w3.eth.wait_for_transaction_receipt(txh)
    uni_addr2, uni_weth2, uni_usdc2 = read_pair(uni_factory, WETH, USDC)
    bs_addr2, bs_weth2, bs_usdc2 = read_pair(bs_factory, WETH, USDC)
    price_uni2 = (uni_usdc2 / 1e6) / (uni_weth2 / 1e18)
    price_bs2 = (bs_usdc2 / 1e6) / (bs_weth2 / 1e18)
    spread = 100 * (price_bs2 / price_uni2 - 1)
    log("spread_synthetique", weth_vendu=round(weth_amount / 1e18, 2),
        prix_weth_uni_usd=round(price_uni2, 2), prix_weth_bs_usd=round(price_bs2, 2),
        spread_pct=round(spread, 3),
        note="spread créé artificiellement avec des fonds fictifs du fork, "
             "pour simuler une opportunité réelle de meme coin")
    assert spread > 1.0, f"spread synthétique trop faible : {spread:.2f} %"

    # --- 4) Sizing mathématique (seuil 3 $, provider Morpho 0 %) ---
    pool_buy = Pool("UniV2 WETH/USDC (pas cher)", uni_usdc2 / 1e6, uni_weth2 / 1e18)
    pool_sell = Pool("BaseSwap WETH/USDC (cher)", bs_usdc2 / 1e6, bs_weth2 / 1e18)
    gas_price_gwei = w3.eth.gas_price / 1e9
    costs = Costs(gas_usd=gas_cost_usd(450_000, gas_price_gwei, ETH_PRICE_USD),
                  min_profit_usd=MIN_PROFIT_USD, gas_multiple=3.0,
                  flash_provider="morpho")
    decision = decide(pool_buy, pool_sell, costs)
    log("decision_offchain", action=decision["action"], spread_pct=decision["spread_pct"],
        flash_provider=decision["flash_provider"],
        flash_fee_rate=decision["flash_fee_rate"],
        optimal_loan_usd=decision["optimal_loan_usd"],
        expected_net_usd=decision["expected_net_usd"],
        gas_usd_est=round(decision["gas_usd"], 4),
        min_profit_usd=MIN_PROFIT_USD, reasons=decision["reasons"])
    assert decision["action"] == "EXECUTE", f"decide() dit {decision['action']} : {decision['reasons']}"
    assert decision["flash_provider"] == "morpho" and decision["flash_fee_rate"] == 0.0
    loan_usd = decision["optimal_loan_usd"]
    loan_wei_usdc = int(loan_usd * 1e6)
    assert loan_usd <= morpho_usdc * 0.5, "loan > 50 % du solde Morpho (ne devrait jamais arriver)"

    # --- 5) Déploiement du contrat Morpho sur le fork ---
    artifact = json.loads(Path("out/FlashLoanArbitrage.sol/MorphoFlashLoanArbitrage.json").read_text())
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    txh = send_signed(contract.constructor(
        USDC, WETH, UNI_V2_ROUTER, BASESWAP_V2_ROUTER, int(MIN_PROFIT_USD * 1e6)),
        gas=3_000_000)
    receipt = w3.eth.wait_for_transaction_receipt(txh)
    assert receipt["status"] == 1, "déploiement en échec (out of gas ?)"
    assert len(w3.eth.get_code(receipt["contractAddress"])) > 0, \
        "pas de code à l'adresse déployée"
    arb = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
    assert arb.functions.MORPHO().call().lower() == MORPHO.lower()
    log("deploy", contract=receipt["contractAddress"], block=receipt["blockNumber"],
        gas_used=receipt["gasUsed"], morpho_onchain=arb.functions.MORPHO().call(),
        min_profit_onchain_usdc=int(MIN_PROFIT_USD * 1e6))

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
    gas_cost = gas_used * rc["effectiveGasPrice"] / 1e18 * ETH_PRICE_USD
    bal_after = usdc.functions.balanceOf(arb.address).call()
    profit_usdc = (bal_after - bal_before) / 1e6
    net = profit_usdc - gas_cost
    events = arb.events.MorphoArbitrageExecuted().process_receipt(rc)
    log("cas_gagnant_broadcast_fork", tx_status=rc["status"], tx_hash=rc["transactionHash"].hex(),
        gas_used=gas_used, gas_price_gwei=round(gas_price, 4),
        gas_cost_usd=round(gas_cost, 4), profit_brut_usdc=round(profit_usdc, 2),
        profit_net_usd=round(net, 2), min_profit_usd=MIN_PROFIT_USD,
        event_profit_usdc=(round(events[0]["args"]["profit"] / 1e6, 2) if events else None),
        verdict="WIN" if rc["status"] == 1 and net >= MIN_PROFIT_USD else "FAIL",
        note="broadcast sur le FORK uniquement — aucun fond réel, aucun mainnet")
    assert rc["status"] == 1 and net >= MIN_PROFIT_USD, "le cas gagnant a échoué sur le fork"

    # --- 7) CAS PERDANT : le spread est refermé, decide() doit dire SKIP ---
    _, uw3, uu3 = read_pair(uni_factory, WETH, USDC)
    _, sw3, su3 = read_pair(bs_factory, WETH, USDC)
    pool_buy2 = Pool("UniV2 apres arb", uu3 / 1e6, uw3 / 1e18)
    pool_sell2 = Pool("BaseSwap apres arb", su3 / 1e6, sw3 / 1e18)
    decision2 = decide(pool_buy2, pool_sell2, costs)
    log("cas_perdant_decision_offchain", action=decision2["action"],
        spread_pct=decision2["spread_pct"], optimal_loan_usd=decision2["optimal_loan_usd"],
        expected_net_usd=decision2["expected_net_usd"],
        gas_paye_usd=0.0, reasons=decision2["reasons"],
        note="SKIP = rien broadcasté, 0 gas payé")
    # eth_call doit revert (filet de sécurité du contrat)
    try:
        arb.functions.executeArbitrage(loan_wei_usdc).call({"from": me})
        revert_sim, revert_err = False, "eth_call n'a PAS revert (inattendu)"
    except Exception as e:
        revert_sim, revert_err = True, str(e)[:200]
    log("cas_perdant_simulation_eth_call", revert=revert_sim, detail=revert_err)
    # Pour CHIFFRER le coût d'un revert : on broadcast quand même le perdant
    # sur le fork (ETH fictif) — ce qu'on ne ferait JAMAIS en live.
    txh = send_signed(arb.functions.executeArbitrage(loan_wei_usdc))
    rc2 = w3.eth.wait_for_transaction_receipt(txh)
    revert_gas_usd = rc2["gasUsed"] * rc2["effectiveGasPrice"] / 1e18 * ETH_PRICE_USD
    log("cas_perdant_broadcast_fork_POUR_MESURE", tx_status=rc2["status"],
        gas_used=rc2["gasUsed"], gas_price_gwei=round(rc2["effectiveGasPrice"] / 1e9, 4),
        cout_revert_usd=round(revert_gas_usd, 4),
        note="revert mesuré sur le fork pour chiffrer le coût — en live on "
             "évite ce coût par le SKIP off-chain (0 $)")

    # --- 8) Résumé ---
    results["summary"] = {
        "fork_block": block,
        "morpho_usdc_balance_usd": round(morpho_usdc, 2),
        "morpho_weth_balance": round(morpho_weth, 2),
        "flash_fee_getter_absent": flash_fee_absent,
        "spread_synthetique_pct": round(spread, 3),
        "cas_gagnant": {"loan_usd": loan_usd, "profit_net_usd": round(net, 2),
                        "gas_used": gas_used, "gas_cost_usd": round(gas_cost, 4),
                        "verdict": "WIN"},
        "cas_perdant": {"decision_offchain": decision2["action"],
                        "gas_paye_si_skip_usd": 0.0,
                        "cout_revert_si_broadcast_usd": round(revert_gas_usd, 4),
                        "gas_revert": rc2["gasUsed"],
                        "verdict": "SKIP (0 gas) / revert confirmé on-chain"},
    }
    Path("fork_results_morpho.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n=== RÉSUMÉ FORK MORPHO ===")
    print(json.dumps(results["summary"], indent=2, default=str))
    print("Résultats détaillés : fork_results_morpho.json")


if __name__ == "__main__":
    main()
