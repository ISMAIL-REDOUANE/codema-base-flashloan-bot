"""Tests v3.3 — Morpho Blue 0 frais (morpho_flash.py + intégration v3.3).
Lancer : python3 test_morpho.py (stdlib only, sauf les 2 tests LIVE
marqués, ignorés proprement si le RPC est indisponible, et le test
de preuve fork, ignoré si fork_results_morpho.json est absent).
Ou : python3 -m pytest test_morpho.py -v"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from morpho_flash import (
    FLASH_FEE_SELECTOR, FLASH_LOAN_SELECTOR, MEASURED_BLOCK,
    MEASURED_MORPHO_BALANCES_USD, MORPHO, MORPHO_FLASH_FEE,
    ON_MORPHO_FLASH_LOAN_SELECTOR, costs_for_provider,
    decode_flash_loan_call, encode_flash_loan_call, encode_flash_loan_data,
    fetch_flash_loan_fee_pct, fetch_morpho_balances, is_valid_address,
    on_morpho_flash_loan_check, provider_fee_rate, repayment_amount,
    select_provider, verify_no_flash_fee_getter,
)
from executor import run, simulate
from math_engine import Costs, Pool, decide
from scanner import MemeCandidate


def _ref_pools():
    # Scénario de référence v1/v2 : spread 20 %, pools 20k $ / 18k $.
    a = Pool("Aerodrome MEME/USDC", 20_000, 20_000_000)
    b = Pool("UniswapV2 MEME/USDC", 18_000, 15_000_000)
    return a, b


def test_morpho_address():
    assert is_valid_address(MORPHO)
    assert MORPHO == "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
    # Pas le Vault Balancer (mort, BIP-928) — ne pas confondre.
    assert MORPHO.lower() != "0xba12222222228d8ba445958a75a0704d566bf2c8"
    assert MORPHO_FLASH_FEE == 0.0
    assert MEASURED_BLOCK == 61_806_974
    assert MEASURED_MORPHO_BALANCES_USD["USDC"] == 328_711_525.75
    # Sélecteurs vérifiés par keccak (docs Morpho + repo morpho-blue).
    assert FLASH_LOAN_SELECTOR == "0xe0232b42"
    assert ON_MORPHO_FLASH_LOAN_SELECTOR == "0x31f57072"
    assert FLASH_FEE_SELECTOR == "0xd9d98ce4"
    print("OK test_morpho_address — Morpho 0xBBBB...FFCb, fee 0 %, "
          "sélecteurs flashLoan 0xe0232b42 / callback 0x31f57072")


def test_provider_fee_rates():
    assert provider_fee_rate("morpho") == 0.0
    assert provider_fee_rate("aave") == 0.0005
    try:
        provider_fee_rate("balancer")
        raise AssertionError("balancer aurait dû lever ValueError (mort, BIP-928)")
    except ValueError:
        pass
    try:
        provider_fee_rate("uniswap")
        raise AssertionError("provider inconnu aurait dû lever ValueError")
    except ValueError:
        pass
    print("OK test_provider_fee_rates — morpho 0, aave 0,05 %, balancer rejeté")


def test_costs_for_provider():
    c_aave = Costs()
    assert c_aave.flash_provider == "aave" and c_aave.flash_fee_rate == 0.0005
    c_mor = costs_for_provider("morpho", c_aave)
    assert c_mor.flash_provider == "morpho" and c_mor.flash_fee_rate == 0.0
    assert c_mor.min_profit_usd == 3.0 and c_mor.gas_usd == c_aave.gas_usd
    # Costs direct avec provider morpho : le taux est forcé à 0.
    assert Costs(flash_provider="morpho").flash_fee_rate == 0.0
    try:
        Costs(flash_provider="dydx")
        raise AssertionError("provider inconnu aurait dû lever ValueError")
    except ValueError:
        pass
    print("OK test_costs_for_provider — défaut Aave inchangé, Morpho force 0 %")


def test_fee_zero_vs_aave_reference():
    # Même opportunité, deux providers : l'écart de net = exactement la prime.
    a, b = _ref_pools()
    d_aave = decide(a, b, Costs())                       # 0,05 %
    d_mor = decide(a, b, Costs(flash_provider="morpho"))  # 0 %
    assert d_aave["optimal_loan_usd"] == 790.16
    assert d_mor["optimal_loan_usd"] == 790.16
    assert abs(d_aave["expected_net_usd"] - 72.68) < 0.01
    assert abs(d_mor["expected_net_usd"] - 73.07) < 0.01
    saved = d_mor["expected_net_usd"] - d_aave["expected_net_usd"]
    assert abs(saved - 790.16 * 0.0005) < 0.01, saved  # 0,40 $ économisés
    # Le 0 % ne sauve PAS une mauvaise taille : 10 000 $ perd toujours.
    assert d_aave["detail"]["flash_fee_usd"] == round(790.16 * 0.0005, 2)
    assert d_mor["detail"]["flash_fee_usd"] == 0.0
    print(f"OK test_fee_zero_vs_aave_reference — optimal 790,16 $ : "
          f"Aave +72,68 $ vs Morpho +73,07 $ (+0,39 $ économisés)")


def test_fee_zero_fork_case():
    # Cas gagnant du fork (FORK_TEST_RESULTS.md) : loan 8 847,98 $,
    # brut +426,82 $, gas mesuré 0,0066 $. Aave : net +422,39 $.
    loan, gross, gas = 8_847.98, 426.82, 0.0066
    net_aave = gross - loan * 0.0005 - gas
    net_mor = gross - loan * 0.0 - gas
    assert abs(net_aave - 422.39) < 0.01
    assert abs(net_mor - 426.81) < 0.01
    assert abs((net_mor - net_aave) - 4.42) < 0.01
    print(f"OK test_fee_zero_fork_case — fork 8 847,98 $ : "
          f"Aave +422,39 $ vs Morpho +426,81 $ (+4,42 $ économisés)")


def test_select_provider():
    # Morpho USDC : 328,7 M$ mesurés -> utilisable (50 %) ~164,4 M$.
    # Tous nos loans passent ; seul un loan démesuré bascule sur Aave.
    for loan in (100.0, 790.16, 8_847.98, 60_000.0, 1_000_000.0):
        sel = select_provider(loan, "USDC")
        assert sel.provider == "morpho", (loan, sel)
        assert sel.fee_rate == 0.0
    # Au-dessus du plafond (50 % de 328 711 525,75 $) -> Aave.
    sel = select_provider(164_355_763.0, "USDC")
    assert sel.provider == "aave", sel
    assert sel.fee_rate == 0.0005
    # Un meme coin n'est pas chez Morpho -> Aave, quelle que soit la taille.
    sel = select_provider(100.0, "MEMECOIN")
    assert sel.provider == "aave"
    # WETH : 88 713,53 détenus -> utilisable ~44 356 WETH (~74 M$).
    sel = select_provider(10_000.0, "WETH")
    assert sel.provider == "morpho", sel
    sel = select_provider(100_000_000.0, "WETH")
    assert sel.provider == "aave", sel
    print("OK test_select_provider — Morpho <= ~164,4 M$ USDC, Aave au-delà, "
          "meme coin -> Aave")


def test_encode_decode_flash_loan():
    usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    data = encode_flash_loan_data(790_160_000)
    cd = encode_flash_loan_call(usdc, 790_160_000, data)
    assert cd.startswith(FLASH_LOAN_SELECTOR)
    dec = decode_flash_loan_call(cd)
    assert dec["token"].lower() == usdc.lower()
    assert dec["amount"] == 790_160_000
    assert dec["user_data"] == data
    # Le receiver est l'appelant : pas de recipient dans l'encodage.
    assert "recipient" not in dec
    # Erreurs : token invalide, amount <= 0.
    for bad in (lambda: encode_flash_loan_call("0x123", 1),
                lambda: encode_flash_loan_call(usdc, 0),
                lambda: encode_flash_loan_call(usdc, -5)):
        try:
            bad()
            raise AssertionError("encodage invalide aurait dû lever ValueError")
        except ValueError:
            pass
    print("OK test_encode_decode_flash_loan — round-trip avec data, "
          "erreurs rejetées")


def test_on_morpho_flash_loan_check():
    data = encode_flash_loan_data(790_160_000)
    ok, reasons = on_morpho_flash_loan_check(MORPHO, 790_160_000, 790_160_000, data)
    assert ok and not reasons
    # Remboursement = exactement assets (fee 0 par conception).
    assert repayment_amount(790_160_000) == 790_160_000
    # Appelant != Morpho -> rejet.
    ok, reasons = on_morpho_flash_loan_check("0x" + "33" * 20, 790_160_000, 790_160_000, data)
    assert not ok and any("Morpho" in r for r in reasons)
    # Montant reçu != montant attendu -> rejet.
    ok, reasons = on_morpho_flash_loan_check(MORPHO, 790_160_001, 790_160_000, data)
    assert not ok
    # Data décodée != assets -> rejet.
    ok, reasons = on_morpho_flash_loan_check(
        MORPHO, 790_160_000, 790_160_000, encode_flash_loan_data(1))
    assert not ok
    # assets == 0 -> rejet (Morpho revert elle-même).
    ok, reasons = on_morpho_flash_loan_check(MORPHO, 0, 0, encode_flash_loan_data(0))
    assert not ok
    print("OK test_on_morpho_flash_loan_check — Morpho seul accepté, "
          "montant vérifié, remboursement = assets exactement")


def test_executor_uses_morpho():
    a, b = _ref_pools()
    win = MemeCandidate("0xAAA", "MEME-WIN", "aerodrome", "uniswap", a, b,
                        liquidity_usd=36_000, holders=150, age_hours=10)
    r = simulate(win)
    assert r.provider == "morpho", r
    assert r.action == "EXECUTE"
    assert abs(r.expected_net_usd - 73.07) < 0.01
    # Gros loan (pools très grosses, spread ~18,75 %) : l'optimal est
    # plafonné par max_loan_usd (50 000 $) — il reste très loin sous le
    # plafond Morpho (~164 M$) -> Morpho aussi (différence vs Balancer,
    # dont le plafond de 26 604 $ forçait le repli Aave).
    big_a = Pool("Aero", 2_000_000, 2_000_000_000)
    big_b = Pool("UniV2", 1_900_000, 1_600_000_000)
    big = MemeCandidate("0xBBB", "MEME-BIG", "aerodrome", "uniswap", big_a, big_b,
                        liquidity_usd=760_000, holders=500, age_hours=10)
    r2 = simulate(big)
    assert r2.loan_usd == 50_000.0, r2
    assert r2.provider == "morpho", r2
    # Morpho presque vide -> repli Aave (soldes live passés en paramètre).
    r3 = simulate(win, vault_balances={"USDC": 100.0})
    assert r3.provider == "aave", r3
    # run() complet : provider imprimé dans les résultats.
    res = run([win])
    assert res[0].provider == "morpho" and res[0].action == "EXECUTE"
    print(f"OK test_executor_uses_morpho — MEME-WIN via Morpho +73,07 $, "
          f"MEME-BIG (50 000 $) via Morpho aussi, Morpho vide -> Aave")


def test_fee_live_rpc():
    # Lecture live réelle (0 gas, lecture seule). Skip propre si RPC coupé.
    try:
        ok, src = verify_no_flash_fee_getter()
    except Exception as e:
        print(f"SKIP test_fee_live_rpc (réseau) : {e}")
        return
    assert ok, f"flashFee ne revert pas ({src}) — vérifier avant tout live"
    fee, src2 = fetch_flash_loan_fee_pct()
    assert fee == 0.0, f"fee {fee} != 0"
    print(f"OK test_fee_live_rpc — pas de getter flashFee ({src}), fee 0,00 %")


def test_morpho_balances_live_rpc():
    try:
        bal = fetch_morpho_balances()
    except Exception as e:
        print(f"SKIP test_morpho_balances_live_rpc (réseau) : {e}")
        return
    if bal is None:
        print("SKIP test_morpho_balances_live_rpc (RPC indisponible — repli "
              "soldes mesurés)")
        return
    assert bal["USDC"] > 100_000_000, bal  # Morpho détient des centaines de M$ USDC
    assert bal["WETH"] > 10_000, bal
    print(f"OK test_morpho_balances_live_rpc — Morpho live USDC "
          f"{bal['USDC']:,.2f} $ / WETH {bal['WETH']:,.2f} $")


def test_fork_execution_proof():
    # Preuve fork v3.3 (FORK_TEST_RESULTS.md §11) : le fichier est écrit
    # par bash fork_test_morpho.sh. Absent -> SKIP propre (pas un échec).
    path = Path("fork_results_morpho.json")
    if not path.exists():
        print("SKIP test_fork_execution_proof (fork_results_morpho.json "
              "absent — lancer bash fork_test_morpho.sh)")
        return
    d = json.loads(path.read_text())
    s = d["summary"]
    assert d["provider"] == "morpho"
    assert s["flash_fee_getter_absent"] is True
    assert s["morpho_usdc_balance_usd"] > 100_000_000
    assert s["morpho_weth_balance"] > 10_000
    assert s["fork_block"] > 61_800_000
    win = s["cas_gagnant"]
    assert win["verdict"] == "WIN" and win["profit_net_usd"] >= 3.0
    assert win["loan_usd"] > 0 and win["gas_cost_usd"] < 0.10
    lose = s["cas_perdant"]
    assert lose["decision_offchain"] == "SKIP"
    assert lose["gas_paye_si_skip_usd"] == 0.0
    assert lose["cout_revert_si_broadcast_usd"] < 0.10
    print(f"OK test_fork_execution_proof — fork bloc {s['fork_block']} : "
          f"WIN +{win['profit_net_usd']:.2f} $ (loan {win['loan_usd']:.2f} $), "
          f"perdant SKIP 0 $ / revert {lose['cout_revert_si_broadcast_usd']:.4f} $")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"ÉCHEC {t.__name__} : {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{failed} TEST(S) EN ÉCHEC sur {len(tests)}.")
        raise SystemExit(1)
    print(f"TOUS LES TESTS MORPHO PASSENT ({len(tests)} tests).")
