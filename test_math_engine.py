"""Tests unitaires — math_engine.py. Lancer : python3 -m pytest test_math_engine.py -v
ou : python3 test_math_engine.py (sans pytest, mode simple)."""
import sys
sys.path.insert(0, ".")

from math_engine import (Pool, Costs, amm_out, net_profit, find_optimal_loan,
                         evaluate_sizes, kelly_fraction, kelly_size, decide,
                         gas_cost_usd, kelly_fraction_honest, wilson_lower_bound)

# v2 : coûts UNIFIÉS — gas 0,0675 $ (450k × 0,05 gwei × 3 000 $), min profit 3 $.
COSTS = Costs()


def test_amm_out_basic():
    # Sans frais, 100 $ dans un pool 10 000 / 10 000 000 -> ~99 009 tokens
    out = amm_out(100, 10_000, 10_000_000, fee_bps=0)
    assert abs(out - 99_009.90) < 1.0, out
    # Avec frais 0,3 %, la sortie est plus petite
    assert amm_out(100, 10_000, 10_000_000, fee_bps=30) < out
    assert amm_out(0, 10_000, 10_000_000) == 0.0
    print("OK test_amm_out_basic")


def test_scenario_1_small_meme_20pct_spread():
    """Scénario 1 (le cas d'Ismail) : meme coin sghira, pools 20k/18k $,
    spread 20 %. 500 $ gagne, 10 000 $ perd — preuve par le calcul."""
    a = Pool("Aerodrome", 20_000, 20_000_000)
    b = Pool("UniswapV2", 18_000, 15_000_000)
    rows = {r["loan_usd"]: r for r in evaluate_sizes([100, 500, 2000, 10000], a, b, COSTS)}
    assert rows[500]["net_usd"] > 50, rows[500]        # ~ +62 $
    assert rows[10000]["net_usd"] < -1000, rows[10000]  # ~ -4 487 $
    assert rows[2000]["net_usd"] < 0, rows[2000]        # ~ -66 $
    opt = find_optimal_loan(a, b, COSTS)
    assert 500 < opt["optimal_loan_usd"] < 1200, opt    # ~ 790 $
    assert opt["net_usd"] > 60, opt                     # ~ +71 $
    d = decide(a, b, COSTS)
    assert d["action"] == "EXECUTE", d
    assert d["optimal_loan_usd"] == opt["optimal_loan_usd"]
    print("OK test_scenario_1_small_meme_20pct_spread — optimal",
          opt["optimal_loan_usd"], "$ net", opt["net_usd"], "$")


def test_scenario_2_tiny_spread_2pct_skip():
    """Scénario 2 : spread 2 % seulement. Avec le gas unifié (0,0675 $),
    le net est ~+1,10 $ : positif mais < min 3 $ -> SKIP, 0 gas.
    (En v1, avec gas 1,20 $, le net était de -0,03 $ — même verdict, autre raison.)"""
    a = Pool("Aerodrome", 50_000, 50_000_000)   # prix 0,001
    b = Pool("UniswapV2", 50_000, 49_000_000)   # prix ~0,00102 (+2 %)
    d = decide(a, b, COSTS)
    assert d["action"] == "SKIP", d
    assert d["gas_paid_if_skipped_usd"] == 0.0
    assert any("profit minimum" in r for r in d["reasons"]), d["reasons"]
    print("OK test_scenario_2_tiny_spread_2pct_skip —", d["reasons"])


def test_scenario_3_deep_pools_5pct_spread():
    """Scénario 3 : grosses pools (500k $), spread 5 %. L'optimal est
    beaucoup plus grand qu'en scénario 1, et 5 000 $ peut gagner."""
    a = Pool("Aerodrome", 500_000, 500_000_000)
    b = Pool("UniswapV2", 480_000, 457_142_857)  # prix ~0,00105 (+5 %)
    rows = {r["loan_usd"]: r for r in evaluate_sizes([500, 5000, 20000], a, b, COSTS)}
    assert rows[500]["net_usd"] > 0, rows[500]
    assert rows[5000]["net_usd"] > rows[500]["net_usd"], rows
    opt = find_optimal_loan(a, b, COSTS)
    assert opt["optimal_loan_usd"] > 5000, opt
    assert opt["net_usd"] > 100, opt
    d = decide(a, b, COSTS)
    assert d["action"] == "EXECUTE", d
    print("OK test_scenario_3_deep_pools_5pct_spread — optimal",
          opt["optimal_loan_usd"], "$ net", opt["net_usd"], "$")


def test_kelly():
    # Edge clair : p=60 %, win 100 $, loss 50 $ -> Kelly plein ~0,40, quart plafonné 0,25
    f = kelly_fraction(0.60, 100, 50)
    assert 0.20 < f <= 0.25, f
    # Pas d'edge : p=30 %, gain 100 / perte 50 (b=2) -> f* = 0,30 - 0,70/2 < 0 -> 0
    assert kelly_fraction(0.30, 100, 50) == 0.0
    k = kelly_size(10_000, 0.60, 100, 50)
    assert k["size_usd"] == 2_500.0, k  # 10 000 * 0,25
    print("OK test_kelly —", k)


def test_gas_cost():
    # v2 UNIFIÉ : 450k units * 0,05 gwei * 3000 $/ETH = 0,0675 $ — plus de plancher 0,10 $.
    assert abs(gas_cost_usd() - 0.0675) < 0.001, gas_cost_usd()
    assert abs(Costs().gas_usd - 0.0675) < 0.001, Costs().gas_usd
    assert Costs().min_profit_usd == 3.0  # min confirmé par Ismail
    assert abs(gas_cost_usd(450_000, 1.0, 3000.0) - 1.35) < 0.01
    print("OK test_gas_cost — défaut unifié 0,0675 $, min 3 $")


def test_gas_cap_skips_on_spike():
    """v2 finding #4 : pic de gas (254 gwei, 29 oct 2026) -> SKIP, même si
    le trade serait gagnant avec un gas normal. On n'envoie rien quand
    le gas explose."""
    a = Pool("Aerodrome", 20_000, 20_000_000)
    b = Pool("UniswapV2", 18_000, 15_000_000)
    spike = Costs(gas_price_gwei=254.0)  # gas auto = 450k × 254 × 3000 ≈ 342,90 $
    d = decide(a, b, spike)
    assert d["action"] == "SKIP", d
    assert any("gas trop cher" in r for r in d["reasons"]), d["reasons"]
    # Juste sous le plafond (2 gwei) : le trade gagnant passe toujours.
    ok_costs = Costs(gas_price_gwei=1.5)
    assert decide(a, b, ok_costs)["action"] == "EXECUTE"
    print("OK test_gas_cap_skips_on_spike — 254 gwei SKIP, 1,5 gwei EXECUTE")


def test_optimal_loan_subcent_precision():
    """Audit #9 : le moteur arrondissait le profit optimal au centime
    AVANT decide() — un net de +0,0001 $ devenait 0,00 $ et le trade
    était rejeté (min_profit=0 sur Polygon). Cas : spread 0,05 %,
    fees 0,01 %/jambe, gas 0,001 $ -> net optimal +0,000126 $.
    decide() doit dire EXECUTE avec le net NON arrondi."""
    a = Pool("A", 100_000, 100_000_000, fee_bps=1)
    b = Pool("B", 100_000, 99_950_000, fee_bps=1)
    c = Costs(gas_usd=0.001, flash_provider="morpho", min_profit_usd=0.0,
              gas_multiple=0.0)
    opt = find_optimal_loan(a, b, c)
    assert 0 < opt["net_usd"] < 0.005, opt  # sub-cent, mais > 0
    assert opt["net_usd"] != round(opt["net_usd"], 2), \
        "le net ne doit plus être arrondi au centime avant decide()"
    d = decide(a, b, c)
    assert d["action"] == "EXECUTE", d
    assert d["expected_net_usd"] == opt["net_usd"], d
    print(f"OK test_optimal_loan_subcent_precision — net optimal "
          f"{opt['net_usd']:.6f} $ (sub-cent) -> EXECUTE, non arrondi")


def test_find_optimal_loan_small_sizes():
    """Audit #11 : la grille commençait à 10 $ et éliminait les tailles
    < 10 $. Petites pools (cap 4,50 $) : l'optimal (~3-4 $) est désormais
    trouvé au lieu de 'liquidité trop faible'."""
    a = Pool("A", 50, 50_000)
    b = Pool("B", 45, 37_500)  # spread 20 %, cap = 10 % × 45 = 4,50 $
    c = Costs(gas_usd=0.001, flash_provider="morpho", min_profit_usd=0.0,
              gas_multiple=0.0)
    opt = find_optimal_loan(a, b, c)
    assert opt["optimal_loan_usd"] > 0, opt
    assert 1.0 <= opt["optimal_loan_usd"] <= 4.50, opt
    assert opt["net_usd"] > 0, opt
    print(f"OK test_find_optimal_loan_small_sizes — optimal "
          f"{opt['optimal_loan_usd']:.2f} $ (cap 4,50 $), net "
          f"{opt['net_usd']:.4f} $")


def test_kelly_honest():
    """v2 recherche §4.2 : sans trades mesurés -> Kelly = 0 (on ne mise pas
    sur un edge non mesuré). < 30 trades -> cap 0,10x. Borne de Wilson :
    8/10 gains (p=0,80) -> borne inf ~0,49, pas 0,80."""
    assert kelly_fraction_honest(0.60, 100, 50, n_trades=0) == 0.0
    f_new = kelly_fraction_honest(0.80, 100, 50, n_trades=10)
    assert 0.0 < f_new <= 0.10, f_new  # cap 0,10x stratégie neuve
    w = wilson_lower_bound(0.80, 10)
    assert 0.40 < w < 0.60, w
    f_old = kelly_fraction_honest(0.60, 100, 50, n_trades=100)
    assert 0.0 < f_old <= 0.25, f_old
    print("OK test_kelly_honest — n=0 -> 0 ; n=10 cap 0,10 ; Wilson(0,80/10) =", round(w, 3))


if __name__ == "__main__":
    test_amm_out_basic()
    test_scenario_1_small_meme_20pct_spread()
    test_scenario_2_tiny_spread_2pct_skip()
    test_scenario_3_deep_pools_5pct_spread()
    test_kelly()
    test_gas_cost()
    test_gas_cap_skips_on_spike()
    test_kelly_honest()
    test_optimal_loan_subcent_precision()
    test_find_optimal_loan_small_sizes()
    print("\nTOUS LES TESTS PASSENT.")
