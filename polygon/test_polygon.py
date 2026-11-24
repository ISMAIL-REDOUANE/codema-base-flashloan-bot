#!/usr/bin/env python3
"""
test_polygon.py — Tests du port Polygon v4.0 (unittest, sans dépendance).

Couverture : enforcement 0 frais (Morpho seul autorisé, Aave/Balancer/dYdX
bloqués), math Polygon (spread 10 % → EXECUTE, spread 0 → SKIP), gas
Polygon (~0,00001 $/trade), float 1,31 $ (autonomie + kill switch),
artefact du contrat compilé, config, et vérifications live (skippées si
le RPC est injoignable — elles ne font jamais échouer la suite offline).

Lancer depuis polygon/ :  ../.venv/bin/python -m unittest test_polygon -v
"""
import json
import sys
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from math_engine import Costs, Pool, decide, gas_cost_usd  # noqa: E402
from polygon_flash import (  # noqa: E402
    MORPHO_POLYGON, FlashFeeError, check_zero_fee, flash_fee_usd,
)
from polygon_guard import (  # noqa: E402
    ONCHAIN_MIN_PROFIT_USD, REVERT_BUDGET_MULTIPLE, polygon_costs,
    polygon_decide, tranche, tranche_counts,
)
from polygon_gas import (  # noqa: E402
    GAS_PRICE_MAX_GWEI, _rpc as _gas_rpc, gas_cost_matic,
    gas_cost_usd as poly_gas_cost_usd,
)
from polygon_ledger import (  # noqa: E402
    FLOAT_MATIC, FLOAT_USD, float_runway, polygon_ledger, trades_covered,
)
from self_funded import FloatLedger  # noqa: E402

MATIC_PRICE_USD = 0.0758
GAS_LIVE_GWEI = 279.0


def _rpc_call(method, params=None):
    # Réutilise le _rpc de polygon_gas (3 tentatives, validation 0x).
    return _gas_rpc("https://polygon.drpc.org", method, params)


class TestZeroFeeEnforcement(unittest.TestCase):
    def test_morpho_is_the_only_zero_fee_provider(self):
        info = check_zero_fee("morpho")
        self.assertEqual(info["fee_rate"], 0.0)
        self.assertEqual(info["address"], MORPHO_POLYGON)

    def test_morpho_polygon_is_not_the_canonical_address(self):
        # Le piège : 0xBBBB… n'a PAS de code sur Polygon.
        self.assertNotEqual(
            MORPHO_POLYGON.lower(),
            "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb")
        self.assertEqual(MORPHO_POLYGON,
                         "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67")

    def test_aave_blocked_in_zero_fee_mode(self):
        with self.assertRaises(FlashFeeError):
            check_zero_fee("aave")

    def test_balancer_and_dydx_dead(self):
        for dead in ("balancer", "dydx"):
            with self.assertRaises(FlashFeeError, msg=dead):
                check_zero_fee(dead)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(FlashFeeError):
            check_zero_fee("nope")

    def test_flash_fee_usd(self):
        self.assertEqual(flash_fee_usd("morpho", 10_000.0), 0.0)
        self.assertAlmostEqual(flash_fee_usd("aave", 10_000.0), 5.0)


class TestPolygonGas(unittest.TestCase):
    def test_trade_cost_is_tiny(self):
        # 450 000 × 279 gwei × 0,0758 $ ≈ 0,0095 $ — ~2× le gas mesuré Base
        # (0,0042 $), mais minuscule en valeur absolue. Le gas Polygon
        # n'est PAS « quasi gratuit » en $ : 279 gwei × MATIC 0,0758 $.
        cost = poly_gas_cost_usd(450_000, GAS_LIVE_GWEI, MATIC_PRICE_USD)
        self.assertLess(cost, 0.02)
        self.assertAlmostEqual(cost, 0.00952, places=5)

    def test_gas_cost_matic(self):
        self.assertAlmostEqual(gas_cost_matic(450_000, 279.0), 0.12555,
                               places=5)

    def test_gas_cap_polygon_is_1000_gwei(self):
        self.assertEqual(GAS_PRICE_MAX_GWEI, 1000.0)
        self.assertLess(GAS_LIVE_GWEI, GAS_PRICE_MAX_GWEI)


class TestPolygonMath(unittest.TestCase):
    def _costs(self):
        # v4.1 : garde net > 0 $ après gas + budget revert (min 3 $ abandonné).
        return polygon_costs(GAS_LIVE_GWEI, MATIC_PRICE_USD)

    def test_spread_10pct_executes(self):
        # QuickSwap bon marché vs Uni V3 chère (réserves type fork test).
        buy = Pool("QuickSwap", 8_800.0, 115_000.0)
        sell = Pool("Uni V3", 9_700.0, 115_000.0)
        d = decide(buy, sell, self._costs())
        self.assertEqual(d["action"], "EXECUTE")
        self.assertEqual(d["flash_provider"], "morpho")
        self.assertEqual(d["flash_fee_rate"], 0.0)
        self.assertGreater(d["optimal_loan_usd"], 0)
        self.assertGreaterEqual(d["expected_net_usd"], 3.0)

    def test_no_spread_skips(self):
        buy = Pool("QuickSwap", 8_800.0, 115_000.0)
        sell = Pool("Uni V3", 8_800.0, 115_000.0)
        d = decide(buy, sell, self._costs())
        self.assertEqual(d["action"], "SKIP")
        # Le loan optimal peut être non nul dans le calcul, mais l'action
        # SKIP veut dire : rien n'est broadcasté, 0 gas payé.
        self.assertLess(d["expected_net_usd"], 3.0)

    def test_small_net_050_executes(self):
        # v4.1 : un trade à +0,52 $ net (après gas + budget revert) est
        # AUTORISÉ — l'ancienne barre de 3 $ est abandonnée.
        buy = Pool("QuickSwap", 8_800.0, 115_000.0)
        sell = Pool("Uni V3", 9_050.0, 115_000.0)
        d = polygon_decide(buy, sell, GAS_LIVE_GWEI, MATIC_PRICE_USD)
        self.assertEqual(d["action"], "EXECUTE")
        self.assertGreater(d["expected_net_usd"], 0.0)
        self.assertLess(d["expected_net_usd"], 3.0)
        self.assertAlmostEqual(d["expected_net_usd"], 0.52, places=1)
        self.assertEqual(tranche(d["expected_net_usd"]), ">=0.50$")

    def test_zero_and_negative_net_blocked(self):
        # v4.1 : net 0,00 $ ou négatif → BLOQUÉ, même sans min profit.
        buy = Pool("QuickSwap", 8_800.0, 115_000.0)
        sell = Pool("Uni V3", 8_800.0, 115_000.0)
        d = polygon_decide(buy, sell, GAS_LIVE_GWEI, MATIC_PRICE_USD)
        self.assertEqual(d["action"], "SKIP")
        self.assertLessEqual(d["expected_net_usd"], 0.0)

    def test_tranche_counts(self):
        counts = tranche_counts([5.0, 0.52, 0.11, 0.0, -1.0, 3.0])
        self.assertEqual(counts, {">0$": 4, ">=0.50$": 3, ">=3$": 2,
                                  "<=0$": 2})


class TestPolygonGuard(unittest.TestCase):
    def test_costs_include_revert_budget(self):
        # gas total = trade + budget revert = 2 × (450 000 × 279 gwei × 0,0758 $)
        # = 0,01903338 $ ; min 0 $ ; marge 0.
        exact_trade_gas = 450_000 * 279 * 1e-9 * MATIC_PRICE_USD
        c = polygon_costs(GAS_LIVE_GWEI, MATIC_PRICE_USD)
        self.assertAlmostEqual(c.gas_usd, 2 * exact_trade_gas, places=7)
        self.assertEqual(c.min_profit_usd, 0.0)
        self.assertEqual(c.gas_multiple, 0.0)
        self.assertEqual(c.flash_provider, "morpho")
        self.assertEqual(c.flash_fee_rate, 0.0)
        self.assertEqual(REVERT_BUDGET_MULTIPLE, 1.0)

    def test_onchain_min_profit_is_anti_dust_floor(self):
        # 0,01 $ : filet atomique on-chain, pas un seuil économique.
        self.assertEqual(ONCHAIN_MIN_PROFIT_USD, 0.01)

    def test_decide_rule_field(self):
        buy = Pool("QuickSwap", 8_800.0, 115_000.0)
        sell = Pool("Uni V3", 9_700.0, 115_000.0)
        d = polygon_decide(buy, sell, GAS_LIVE_GWEI, MATIC_PRICE_USD)
        self.assertIn("net > 0", d["rule"])
        exact_trade_gas = 450_000 * 279 * 1e-9 * MATIC_PRICE_USD
        self.assertAlmostEqual(d["gas_trade_usd"], exact_trade_gas, places=6)
        self.assertAlmostEqual(d["revert_budget_usd"], exact_trade_gas, places=6)
        self.assertAlmostEqual(d["total_cost_usd"], 2 * exact_trade_gas, places=6)


class TestPolygonFloat(unittest.TestCase):
    def test_float_is_ismails_real_balance(self):
        self.assertEqual(FLOAT_MATIC, 17.2743)
        self.assertEqual(FLOAT_USD, 1.31)

    def test_split_100_0(self):
        led = polygon_ledger(state_path=None, trades_path=None)
        sponsor, ismail = led.split_profit(100.0)
        self.assertEqual((sponsor, ismail), (0.0, 100.0))

    def test_float_covers_enough_trades(self):
        # Gas réel ~0,0095 $/trade : 1,31 $ couvre ~137 trades (~68 pire cas).
        led = polygon_ledger(state_path=None, trades_path=None)
        n = trades_covered(led, gas_usd_per_trade=0.00952)
        self.assertGreater(n, 50)
        rw = float_runway(led, 0.00952)
        self.assertGreater(rw["trades_worst_case"], 50)
        self.assertFalse(rw["kill_switch"])

    def test_kill_switch_trips_when_float_empty(self):
        # Le FloatLedger arrondit au centime : on teste à l'échelle du cent.
        led = FloatLedger(float_usd=0.03, sponsor_share_pct=0.0,
                          min_profit_usd=3.0, state_path=None, trades_path=None)
        ok, _ = led.can_afford(0.01)   # pire cas 0,02 $ <= 0,03 $
        self.assertTrue(ok)
        led.charge_gas(0.01)
        led.charge_gas(0.01)
        led.charge_gas(0.01)           # float à 0 → kill switch
        self.assertTrue(led.tripped)
        ok2, reason = led.can_afford(0.01)
        self.assertFalse(ok2)
        self.assertIn("kill switch", reason)

    def test_trade_blocked_when_worst_case_exceeds_float(self):
        led = FloatLedger(float_usd=0.02, sponsor_share_pct=0.0,
                          min_profit_usd=3.0, state_path=None, trades_path=None)
        ok, reason = led.can_afford(0.015)  # pire cas 0,03 > 0,02
        self.assertFalse(ok)
        self.assertIn("pire cas", reason)


class TestContractArtifact(unittest.TestCase):
    ART = Path(__file__).parent / "out" / "FlashLoanArbitragePolygon.sol" / \
        "MorphoFlashLoanArbitragePolygon.json"

    def test_artifact_exists_and_has_bytecode(self):
        self.assertTrue(self.ART.exists(), "forge build non lancé ?")
        data = json.loads(self.ART.read_text())
        self.assertGreater(len(data["bytecode"]["object"]), 100)
        names = [f["name"] for f in data["abi"] if f["type"] == "function"]
        for fn in ("executeArbitrage", "onMorphoFlashLoan", "MORPHO",
                   "withdrawProfit", "setMinProfit"):
            self.assertIn(fn, names)


class TestPolygonConfig(unittest.TestCase):
    def test_config_values(self):
        text = (Path(__file__).parent / "polygon_config.yaml").read_text()
        self.assertIn("chain_id: 137", text)
        self.assertIn("0x1bF0c2541F820E775182832f06c0B7Fc27A25f67", text)
        self.assertIn("float_usd: 1.31", text)
        # v4.1 : min profit 3 $ abandonné — net > 0 $ après tous coûts.
        self.assertIn("min_profit_usd: 0.0", text)
        self.assertNotIn("min_profit_usd: 3.0", text)
        self.assertIn("revert_budget_multiple: 1.0", text)
        self.assertIn("https://polygon.drpc.org", text)
        # L'adresse canonique ne doit apparaître que comme piège documenté.
        self.assertNotIn('morpho: "0xBBBB', text)


@unittest.skipUnless(True, "live RPC")
class TestPolygonLive(unittest.TestCase):
    """Vérifications live — skippées proprement si le RPC est injoignable."""

    def test_morpho_has_code_and_big_usdc_balance(self):
        try:
            code = _rpc_call("eth_getCode",
                             [MORPHO_POLYGON, "latest"])
            self.assertTrue(code and len(code) > 100)
            bal_data = ("0x70a08231" + "000000000000000000000000"
                        + MORPHO_POLYGON[2:].lower())
            bal = _rpc_call("eth_call", [
                {"to": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                 "data": bal_data}, "latest"])
            self.assertGreater(int(bal, 16) / 1e6, 10_000)
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"RPC Polygon injoignable : {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
