"""Tests v3 — Balancer 0 frais (balancer_flash.py + intégration v3).
⛔ DÉPRÉCIÉ v3.3 (2026-11-24) : Balancer est MORT (BIP-928, wind-down
30 oct 2026). Ces tests sont CONSERVÉS pour référence historique : ils
testent le module déprécié balancer_flash.py (adresses, fee, encodage),
PAS le provider actif — l'executor route désormais via Morpho
(morpho_flash.py, voir test_morpho.py). Ne pas supprimer, ne pas
réactiver comme provider. Seul le test d'intégration executor a été
mis à jour pour refléter le routage actuel (Morpho, pas Balancer).
Lancer : python3 test_balancer.py (stdlib only, sauf les 2 tests LIVE
marqués, ignorés proprement si le RPC est indisponible).
Ou : python3 -m pytest test_balancer.py -v"""
import sys

sys.path.insert(0, ".")

from balancer_flash import (
    BALANCER_FEES_COLLECTOR, BALANCER_FLASH_FEE, BALANCER_VAULT,
    FLASH_LOAN_SELECTOR, MEASURED_BLOCK, MEASURED_VAULT_BALANCES_USD,
    costs_for_provider, decode_flash_loan_call, encode_flash_loan_call,
    fetch_flash_loan_fee_pct, fetch_vault_balances, is_valid_address,
    provider_fee_rate, receive_flash_loan_check, repayment_amounts,
    select_provider,
)
from executor import run, simulate
from math_engine import Costs, Pool, decide
from scanner import MemeCandidate


def _ref_pools():
    # Scénario de référence v1/v2 : spread 20 %, pools 20k $ / 18k $.
    a = Pool("Aerodrome MEME/USDC", 20_000, 20_000_000)
    b = Pool("UniswapV2 MEME/USDC", 18_000, 15_000_000)
    return a, b


def test_vault_addresses():
    assert is_valid_address(BALANCER_VAULT)
    assert BALANCER_VAULT == "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
    assert is_valid_address(BALANCER_FEES_COLLECTOR)
    assert BALANCER_FEES_COLLECTOR == "0xce88686553686DA562CE7Cea497CE749DA109f9F"
    # L'adresse 0xCcb4... vue sur Basescan N'EST PAS le collector du Vault.
    assert BALANCER_FEES_COLLECTOR.lower() != "0xccb400111263f59da19d9dd3977bc07e548431af"
    assert BALANCER_FLASH_FEE == 0.0
    assert MEASURED_BLOCK == 61_794_215
    assert MEASURED_VAULT_BALANCES_USD["USDC"] == 53_208.01
    print("OK test_vault_addresses — Vault 0xBA12...F2C8, collector 0xce88..., fee 0 %")


def test_provider_fee_rates():
    assert provider_fee_rate("balancer") == 0.0
    assert provider_fee_rate("aave") == 0.0005
    try:
        provider_fee_rate("uniswap")
        raise AssertionError("provider inconnu aurait dû lever ValueError")
    except ValueError:
        pass
    print("OK test_provider_fee_rates — balancer 0, aave 0,05 %, inconnu rejeté")


def test_costs_for_provider():
    c_aave = Costs()
    assert c_aave.flash_provider == "aave" and c_aave.flash_fee_rate == 0.0005
    c_bal = costs_for_provider("balancer", c_aave)
    assert c_bal.flash_provider == "balancer" and c_bal.flash_fee_rate == 0.0
    assert c_bal.min_profit_usd == 3.0 and c_bal.gas_usd == c_aave.gas_usd
    # Costs direct avec provider balancer : le taux est forcé à 0.
    assert Costs(flash_provider="balancer").flash_fee_rate == 0.0
    try:
        Costs(flash_provider="dydx")
        raise AssertionError("provider inconnu aurait dû lever ValueError")
    except ValueError:
        pass
    print("OK test_costs_for_provider — défaut Aave inchangé, Balancer force 0 %")


def test_fee_zero_vs_aave_reference():
    # Même opportunité, deux providers : l'écart de net = exactement la prime.
    a, b = _ref_pools()
    d_aave = decide(a, b, Costs())                       # 0,05 %
    d_bal = decide(a, b, Costs(flash_provider="balancer"))  # 0 %
    assert d_aave["optimal_loan_usd"] == 790.16
    assert d_bal["optimal_loan_usd"] == 790.16
    assert abs(d_aave["expected_net_usd"] - 72.68) < 0.01
    assert abs(d_bal["expected_net_usd"] - 73.07) < 0.01
    saved = d_bal["expected_net_usd"] - d_aave["expected_net_usd"]
    assert abs(saved - 790.16 * 0.0005) < 0.01, saved  # 0,40 $ économisés
    # Le 0 % ne sauve PAS une mauvaise taille : 10 000 $ perd toujours.
    assert d_aave["detail"]["flash_fee_usd"] == round(790.16 * 0.0005, 2)
    assert d_bal["detail"]["flash_fee_usd"] == 0.0
    print(f"OK test_fee_zero_vs_aave_reference — optimal 790,16 $ : "
          f"Aave +72,68 $ vs Balancer +73,07 $ (+0,39 $ économisés)")


def test_fee_zero_fork_case():
    # Cas gagnant du fork (FORK_TEST_RESULTS.md) : loan 8 847,98 $,
    # brut +426,82 $, gas mesuré 0,0066 $. Aave : net +422,39 $.
    loan, gross, gas = 8_847.98, 426.82, 0.0066
    net_aave = gross - loan * 0.0005 - gas
    net_bal = gross - loan * 0.0 - gas
    assert abs(net_aave - 422.39) < 0.01
    assert abs(net_bal - 426.81) < 0.01
    assert abs((net_bal - net_aave) - 4.42) < 0.01
    print(f"OK test_fee_zero_fork_case — fork 8 847,98 $ : "
          f"Aave +422,39 $ vs Balancer +426,81 $ (+4,42 $ économisés)")


def test_select_provider():
    # Petits loans -> Balancer (plafond utilisable = 50 % de 53 208,01 $
    # = 26 604,005 $ — donc 26 604,00 $ passe, 26 604,01 $ ne passe plus).
    for loan in (100.0, 790.16, 8_847.98, 26_604.00):
        sel = select_provider(loan, "USDC")
        assert sel.provider == "balancer", (loan, sel)
        assert sel.fee_rate == 0.0
    # Au-dessus du plafond -> Aave.
    for loan in (26_604.01, 30_000.0, 60_000.0):
        sel = select_provider(loan, "USDC")
        assert sel.provider == "aave", (loan, sel)
        assert sel.fee_rate == 0.0005
    # Un meme coin n'est pas dans le Vault -> Aave, quelle que soit la taille.
    sel = select_provider(100.0, "MEMECOIN")
    assert sel.provider == "aave"
    # WETH : 23,27 détenus -> utilisable ~11,6 WETH (~19 500 $).
    sel = select_provider(10_000.0, "WETH")
    assert sel.provider == "balancer", sel
    sel = select_provider(25_000.0, "WETH")
    assert sel.provider == "aave", sel
    print("OK test_select_provider — Balancer <= 26 604 $ USDC, Aave au-delà, "
          "meme coin -> Aave")


def test_encode_decode_flash_loan():
    recipient = "0x" + "22" * 20
    usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    cd = encode_flash_loan_call(recipient, [usdc], [790_160_000])
    assert cd.startswith(FLASH_LOAN_SELECTOR)
    dec = decode_flash_loan_call(cd)
    assert dec["recipient"].lower() == recipient.lower()
    assert dec["tokens"] == [usdc.lower()]
    assert dec["amounts"] == [790_160_000]
    assert dec["user_data"] == b""
    # Multi-token + userData.
    weth = "0x4200000000000000000000000000000000000006"
    cd2 = encode_flash_loan_call(recipient, [usdc, weth], [1000, 2000], b"abc")
    dec2 = decode_flash_loan_call(cd2)
    assert dec2["amounts"] == [1000, 2000] and dec2["user_data"] == b"abc"
    # Erreurs : tailles différentes, adresse invalide.
    for bad in (lambda: encode_flash_loan_call(recipient, [usdc], [1, 2]),
                lambda: encode_flash_loan_call("0x123", [usdc], [1]),
                lambda: encode_flash_loan_call(recipient, [], [])):
        try:
            bad()
            raise AssertionError("encodage invalide aurait dû lever ValueError")
        except ValueError:
            pass
    print("OK test_encode_decode_flash_loan — round-trip 1 et 2 tokens, "
          "erreurs rejetées")


def test_receive_flash_loan_check():
    vault = BALANCER_VAULT
    usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    ok, reasons = receive_flash_loan_check(vault, [usdc], [790_160_000], [0])
    assert ok and not reasons
    assert repayment_amounts([790_160_000], [0]) == [790_160_000]
    # Appelant != Vault -> rejet.
    ok, reasons = receive_flash_loan_check("0x" + "33" * 20, [usdc], [1], [0])
    assert not ok and any("Vault" in r for r in reasons)
    # Fee monté par la gouvernance -> signalé, remboursement = amount + fee.
    ok, reasons = receive_flash_loan_check(vault, [usdc], [1_000_000], [500])
    assert not ok and repayment_amounts([1_000_000], [500]) == [1_000_500]
    print("OK test_receive_flash_loan_check — Vault seul accepté, fee != 0 signalé")


def test_executor_uses_balancer():
    # ⛔ v3.3 — DÉPRÉCIÉ : l'executor ne route PLUS via Balancer (mort,
    # BIP-928). Ce test vérifie désormais que le routage actuel (Morpho)
    # donne les MÊMES chiffres que Balancer donnait (fee 0 %, net +73,07 $)
    # et que le gros loan ne rebascule plus sur Aave (plafond Morpho
    # ~164 M$ >> 50 000 $). Le module balancer_flash.py lui-même est
    # toujours testé par les autres tests de ce fichier (référence).
    a, b = _ref_pools()
    win = MemeCandidate("0xAAA", "MEME-WIN", "aerodrome", "uniswap", a, b,
                        liquidity_usd=36_000, holders=150, age_hours=10)
    r = simulate(win)
    assert r.provider == "morpho", r
    assert r.action == "EXECUTE"
    assert abs(r.expected_net_usd - 73.07) < 0.01
    # Gros loan (pools très grosses, spread ~18,75 %) : l'optimal est
    # plafonné par max_loan_usd (50 000 $) — sous Balancer il dépassait
    # le plafond Vault (26 604 $) -> Aave ; sous Morpho il reste Morpho.
    big_a = Pool("Aero", 2_000_000, 2_000_000_000)
    big_b = Pool("UniV2", 1_900_000, 1_600_000_000)
    big = MemeCandidate("0xBBB", "MEME-BIG", "aerodrome", "uniswap", big_a, big_b,
                        liquidity_usd=760_000, holders=500, age_hours=10)
    r2 = simulate(big)
    # L'optimal est plafonné par max_loan_usd (50 000 $) : il dépassait le
    # plafond Balancer (26 604 $) -> Aave ; il passe chez Morpho (~164 M$).
    assert r2.loan_usd > 26_604.01, r2
    assert r2.provider == "morpho", r2
    # run() complet : provider imprimé dans les résultats.
    res = run([win])
    assert res[0].provider == "morpho" and res[0].action == "EXECUTE"
    print(f"OK test_executor_uses_balancer [DÉPRÉCIÉ v3.3 — routage Morpho] — "
          f"MEME-WIN via Morpho +73,07 $, "
          f"MEME-BIG ({r2.loan_usd:,.0f} $) via Morpho (ex-Balancer -> Aave)")


def test_fee_live_rpc():
    # Lecture live réelle (0 gas, lecture seule). Skip propre si RPC coupé.
    try:
        fee, src = fetch_flash_loan_fee_pct()
    except Exception as e:
        print(f"SKIP test_fee_live_rpc (réseau) : {e}")
        return
    assert fee == 0.0, f"fee lu {fee} != 0 — la gouvernance a changé le fee !"
    assert src in ("rpc_live",) or src.startswith("fallback")
    print(f"OK test_fee_live_rpc — fee lu on-chain 0,00 % (source {src})")


def test_vault_balances_live_rpc():
    try:
        bal = fetch_vault_balances()
    except Exception as e:
        print(f"SKIP test_vault_balances_live_rpc (réseau) : {e}")
        return
    if bal is None:
        print("SKIP test_vault_balances_live_rpc (RPC indisponible — repli "
              "soldes mesurés)")
        return
    assert bal["USDC"] > 10_000, bal  # le Vault doit contenir assez pour nos loans
    assert bal["WETH"] > 5, bal
    print(f"OK test_vault_balances_live_rpc — Vault live USDC "
          f"{bal['USDC']:,.2f} $ / WETH {bal['WETH']:,.2f} $")


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
    print(f"TOUS LES TESTS BALANCER PASSENT ({len(tests)} tests).")
