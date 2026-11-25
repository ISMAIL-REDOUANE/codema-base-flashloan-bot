"""
test_curve_leg.py — Tests unitaires de la jambe Curve (v4.5, purs, sans RPC).

Couvre la math de la route CORRIGÉE 4 swaps (curve_route.py) :
  - net à partir des 4 jambes (quotes enregistrées, bloc 97 922 005) ;
  - minDy (marge de slippage) ;
  - garde off-chain (net + Aave gelé) ;
  - la correction elle-même : l'ancienne route 3 swaps (jambe Curve
    traitée comme USDC natif) SURÉVALUE le net de exactement (leg2 - leg3) ;
  - le mapping d'erreur Aave v2 VL_RESERVE_FROZEN = '3' (Errors.sol
    officiel, vérifié 2026-11-25) — c'est la raison du revert mesuré
    sur le fork.

Lancer : ../.venv/bin/python -m unittest polygon.test_curve_leg -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curve_route import (AAVE_VL_RESERVE_FROZEN, GAS_UNITS_4SWAP,
                         ONCHAIN_MIN_PROFIT_USD, gas_budget_4swap_usd,
                         min_dy_for_quote, route_guard_decision,
                         route_net_from_legs)

# Quotes enregistrées, bloc 97 922 005 (4 swaps, lecture seule).
RECORDED = {
    1_000.0: (999.89, 1001.03, 1001.14, 1001.04),
    5_000.0: (4999.45, 5005.12, 5005.62, 5005.11),
    20_000.0: (19997.49, 20019.82, 20021.57, 20019.24),
}


class TestCurveRouteNet(unittest.TestCase):
    def test_gas_budget_4swap(self):
        # 750 000 unités x 280 gwei x 0,0758 $ x 2 (trade + revert).
        self.assertAlmostEqual(gas_budget_4swap_usd(), 0.031836, places=6)
        self.assertEqual(GAS_UNITS_4SWAP, 750_000)

    def test_net_quotes_enregistrees(self):
        budget = gas_budget_4swap_usd()
        expected = {1_000.0: 1.0082, 5_000.0: 5.0782, 20_000.0: 19.2082}
        for loan, (l0, l1, l2, l3) in RECORDED.items():
            r = route_net_from_legs(loan, l0, l1, l2, l3, budget)
            self.assertEqual(r["verdict"], "WIN")
            self.assertAlmostEqual(r["net_usd"], expected[loan], places=4)
            self.assertAlmostEqual(r["gross_usd"], l3 - loan, places=4)

    def test_net_negatif_devient_skip(self):
        # Spread inversé (route inverse) : net négatif -> SKIP.
        r = route_net_from_legs(1_000.0, 999.89, 998.50, 998.40, 998.30,
                                gas_budget_4swap_usd())
        self.assertEqual(r["verdict"], "SKIP")
        self.assertLess(r["net_usd"], 0)

    def test_correction_leg2_usdce_pas_usdc(self):
        # L'ancienne route traitait leg2 (USDC.e) comme de l'USDC natif :
        # elle surévaluait le brut de exactement (leg2 - leg3), le coût
        # de la 4e jambe USDC.e -> USDC natif.
        l0, l1, l2, l3 = RECORDED[5_000.0]
        budget = gas_budget_4swap_usd()
        nouveau = route_net_from_legs(5_000.0, l0, l1, l2, l3, budget)
        ancien_brut = l2 - 5_000.0  # leg2 traitée comme USDC final
        self.assertAlmostEqual(ancien_brut - nouveau["gross_usd"],
                               l2 - l3, places=4)
        self.assertAlmostEqual(l2 - l3, 0.51, places=2)
        # La correction coûte ~0,51 $ à 5 k$ : la route reste WIN, mais
        # le net annoncé avant (5,63 $) était surévalué de ~0,55 $.
        self.assertLess(nouveau["net_usd"], 5.63)


class TestMinDy(unittest.TestCase):
    def test_mindy_slippage(self):
        # quote 5 005,62 USDC.e x (1 - 0,05 %) = 5 003 117 190 (6 décimales).
        self.assertEqual(min_dy_for_quote(5005.62), 5_003_117_190)

    def test_mindy_inferieur_a_la_quote(self):
        for _, (_, _, l2, _) in RECORDED.items():
            self.assertLess(min_dy_for_quote(l2), int(l2 * 1e6))
            self.assertGreater(min_dy_for_quote(l2), int(l2 * 0.999 * 1e6))


class TestRouteGuard(unittest.TestCase):
    def test_skip_si_aave_gele_meme_avec_net_positif(self):
        # C'est le cas réel : net +5,08 $ mais Aave v2 gelé -> SKIP.
        d = route_guard_decision(5.08, aave_frozen=True)
        self.assertEqual(d["action"], "SKIP")
        self.assertEqual(d["reason"], "aave_v2_frozen")

    def test_execute_si_net_positif_et_aave_ok(self):
        d = route_guard_decision(5.08, aave_frozen=False)
        self.assertEqual(d["action"], "EXECUTE")

    def test_skip_si_net_negatif(self):
        d = route_guard_decision(-1.50, aave_frozen=False)
        self.assertEqual(d["action"], "SKIP")
        self.assertEqual(d["reason"], "net_negatif")

    def test_skip_si_net_sous_minprofit(self):
        # net 0,005 $ < minProfit on-chain 0,01 $ -> SKIP.
        d = route_guard_decision(0.005, aave_frozen=False)
        self.assertEqual(d["action"], "SKIP")
        self.assertEqual(d["reason"], "net_sous_minprofit")
        self.assertEqual(ONCHAIN_MIN_PROFIT_USD, 0.01)

    def test_execute_juste_au_dessus_minprofit(self):
        d = route_guard_decision(0.02, aave_frozen=False)
        self.assertEqual(d["action"], "EXECUTE")


class TestAaveErrorMapping(unittest.TestCase):
    def test_vl_reserve_frozen_est_3(self):
        # Aave v2 Errors.sol officiel :
        # VL_RESERVE_FROZEN = '3' ("Action cannot be performed because
        # the reserve is frozen"). C'est la raison du revert mesuré
        # sur le fork (tx 276e418b…, gas 489 126).
        self.assertEqual(AAVE_VL_RESERVE_FROZEN, "3")


if __name__ == "__main__":
    unittest.main()
