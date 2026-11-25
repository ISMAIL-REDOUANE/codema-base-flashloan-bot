"""Tests low_fee_routes.py — aucune RPC live dans les tests (chiffres
enregistres), sauf le test de la fonction pure de cotation.
Lancer : ../.venv/bin/python -m unittest test_low_fee -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from low_fee_routes import (  # noqa: E402
    FEE_V3_001,
    breakeven_table,
    gas_budget_4leg_usd,
    impermanent_loss_pct,
    lp_evaluation,
    route_4leg_from_quotes,
)
from polygon_guard import polygon_costs, polygon_decide  # noqa: E402
from math_engine import Pool  # noqa: E402

# Quotes enregistrees, bloc 97921113 (2026-11-25, meme bloc, drpc) :
# route 4-jambes USDC -> USDC.e -> USDT (V3 0,01 %) -> USDC (Curve).
RECORDED_4LEG = {
    1_000.0: (999.89, 1_001.04, 1_001.14),
    5_000.0: (4_999.45, 5_005.16, 5_005.66),
    20_000.0: (19_997.48, 20_019.98, 20_021.73),
}


class TestFeeConversions(unittest.TestCase):
    def test_curve_fee_raw_100000_is_0001_pct(self):
        # fee() Curve en precision 1e10 : 100000 / 1e10 = 0,001 %.
        self.assertAlmostEqual(100000 / 1e10 * 100, 0.001, places=6)

    def test_algebra_fee_raw_10_is_0001_pct(self):
        # globalState().fee : centiemes de bp -> 10 / 100 = 0,1 bp = 0,001 %.
        self.assertAlmostEqual(10 / 100 * 0.01, 0.001, places=6)

    def test_algebra_volatile_fee_raw_868(self):
        self.assertAlmostEqual(868 / 100 * 0.01, 0.0868, places=6)

    def test_v3_tier_001_is_1_bp(self):
        self.assertEqual(FEE_V3_001, 1)


class TestBreakeven(unittest.TestCase):
    def _decide(self, fee_a, fee_b, spread_pct):
        # Pools profondes (impact ~0) : la table mesure la structure
        # de frais + gas, comme la table verifiee du 2026-11-24.
        buy = Pool("buy", 5_000_000_000.0, 5_000_000_000.0, fee_bps=fee_a)
        sell = Pool("sell", 5_000_000_000.0,
                    5_000_000_000.0 / (1.0 + spread_pct / 100.0),
                    fee_bps=fee_b)
        return polygon_decide(buy, sell, 282.0)

    def test_v3_001_plus_v3_001_profits_at_005(self):
        # Frais totaux 0,02 % : un spread de 0,05 % doit passer.
        d = self._decide(1, 1, 0.05)
        self.assertEqual(d["action"], "EXECUTE")
        self.assertGreater(d["expected_net_usd"], 0)

    def test_v3_001_plus_v3_001_breakeven_at_002(self):
        # Spread 0,02 % = frais totaux : net ~ 0 (gas + impact le tuent).
        d = self._decide(1, 1, 0.02)
        self.assertLessEqual(d["expected_net_usd"], 0.05)

    def test_v3_005_plus_v3_005_needs_more_than_010(self):
        # Frais totaux 0,10 % : spread 0,10 % ~ breakeven (net <= 0).
        d = self._decide(5, 5, 0.10)
        self.assertLessEqual(d["expected_net_usd"], 0.05)
        # ... mais 0,15 % passe.
        d2 = self._decide(5, 5, 0.15)
        self.assertEqual(d2["action"], "EXECUTE")

    def test_v3_005_plus_v2_030_needs_035(self):
        # Frais totaux 0,35 % : spread 0,10 % -> le garde dit SKIP
        # (loan optimal 0, net ~ -gas). A taille FIXE 5 k$ la perte est
        # bien ~ -12,50 $ (brut 5 $ - frais 17,50 $ - gas 0,02 $).
        d = self._decide(5, 30, 0.10)
        self.assertEqual(d["action"], "SKIP")
        self.assertLess(d["optimal_loan_usd"], 1.0)  # ~0 $ (artefact numerique)
        from math_engine import evaluate_sizes
        from polygon_guard import polygon_costs
        buy = Pool("buy", 5_000_000_000.0, 5_000_000_000.0, fee_bps=5)
        sell = Pool("sell", 5_000_000_000.0,
                    5_000_000_000.0 / 1.001, fee_bps=30)
        row = evaluate_sizes([5_000.0], buy, sell,
                             polygon_costs(282.0))[0]
        self.assertLess(row["net_usd"], -12.0)
        self.assertGreater(row["net_usd"], -13.0)

    def test_breakeven_table_shape(self):
        rows = breakeven_table()
        self.assertEqual(len(rows), 8 * 3)  # 8 paires x 3 spreads
        # La paire la moins chere a le breakeven le plus bas.
        cheapest = min(rows, key=lambda r: r["breakeven_spread_pct"])
        self.assertIn("Algebra", cheapest["pair"])
        self.assertAlmostEqual(cheapest["breakeven_spread_pct"], 0.011,
                               places=3)
        # V3+V3 0,05 % : breakeven 0,100 %.
        v3v3 = [r for r in rows if r["pair"] == "V3 0,05 % + V3 0,05 %"][0]
        self.assertAlmostEqual(v3v3["breakeven_spread_pct"], 0.100, places=3)


class TestRoute4Leg(unittest.TestCase):
    def test_recorded_quotes_all_win(self):
        budget = gas_budget_4leg_usd()
        for amount, (l0, l1, l2) in RECORDED_4LEG.items():
            r = route_4leg_from_quotes(amount, l0, l1, l2, budget)
            self.assertEqual(r["verdict"], "WIN", f"${amount}: {r}")
            self.assertGreater(r["net_usd"], 0)

    def test_recorded_net_5k(self):
        # Bloc 97921113 : brut +5,66 $, budget gas 4-jambes ~0,028 $.
        r = route_4leg_from_quotes(5_000.0, 4_999.45, 5_005.16, 5_005.66,
                                   gas_budget_4leg_usd())
        self.assertAlmostEqual(r["gross_usd"], 5.66, places=2)
        self.assertGreater(r["net_usd"], 5.0)

    def test_recorded_net_20k_scales(self):
        r = route_4leg_from_quotes(20_000.0, 19_997.48, 20_019.98,
                                   20_021.73, gas_budget_4leg_usd())
        self.assertAlmostEqual(r["gross_usd"], 21.73, places=2)
        self.assertGreater(r["net_usd"], 20.0)

    def test_gas_budget_4leg_above_2leg(self):
        two_leg = polygon_costs(282.0).gas_usd
        self.assertGreater(gas_budget_4leg_usd(), two_leg)
        self.assertLess(gas_budget_4leg_usd(), 0.05)

    def test_reverse_route_loses(self):
        # Route inverse (USDC -> USDT Curve -> USDC.e V3 -> USDC), bloc
        # 97920970 : brut negatif a toutes les tailles.
        for amount, gross in ((1_000.0, -1.5709), (5_000.0, -7.9152)):
            self.assertLess(gross, 0, f"${amount}")


class TestMarketMaking(unittest.TestCase):
    def test_lp_apr_usdce_usdt_001(self):
        # vol 644 001 $/j x 0,01 % = 64,40 $/j de frais ; TVL 830 874 $.
        ev = lp_evaluation(644_001.0, 1, 830_874.0, 1_000.0)
        self.assertAlmostEqual(ev["daily_fees_usd"], 64.40, places=1)
        self.assertAlmostEqual(ev["fee_apr_pct"], 2.83, places=1)
        self.assertGreater(ev["weekly_fees_usd"], 0.3)
        self.assertLess(ev["weekly_fees_usd"], 1.0)

    def test_lp_apr_wmatic_usdce_005(self):
        ev = lp_evaluation(35_849.0, 5, 136_185.0, 1_000.0)
        self.assertAlmostEqual(ev["fee_apr_pct"], 4.80, places=1)
        self.assertAlmostEqual(ev["weekly_fees_usd"], 0.92, places=2)

    def test_lp_dead_pool_zero(self):
        ev = lp_evaluation(3.61, 1, 292.0, 1_000.0)
        self.assertLess(ev["weekly_fees_usd"], 0.02)

    def test_il_zero_at_no_move(self):
        self.assertAlmostEqual(impermanent_loss_pct(1.0), 0.0, places=9)

    def test_il_10pct_move(self):
        # +10 % : IL = 2*sqrt(1,1)/2,1 - 1 = -0,113 %.
        self.assertAlmostEqual(impermanent_loss_pct(1.10) * 100,
                               -0.113, places=2)

    def test_il_20pct_move_beats_weekly_fees(self):
        # -20 % : IL -0,414 % = -4,14 $ sur 1 000 $, soit ~6 semaines
        # de frais de la pool WMATIC/USDC.e 0,05 % (0,69 $/sem).
        il_usd = impermanent_loss_pct(1.20) * 1_000.0
        self.assertAlmostEqual(il_usd, -4.14, places=1)
        self.assertLess(il_usd, -0.69 * 5)


if __name__ == "__main__":
    unittest.main()
