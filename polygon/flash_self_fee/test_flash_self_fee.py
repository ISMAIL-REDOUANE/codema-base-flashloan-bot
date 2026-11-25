#!/usr/bin/env python3
"""Tests for the flash_self_fee fork simulation (Polygon, fork only).

Pure Python — no anvil needed, except the decomposition test which reads
the JSON produced by a real fork run (bash run_sim.sh).
Run:  ../../.venv/bin/python -m unittest test_flash_self_fee -v
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
sys.path.insert(0, str(BASE.parent.parent))

import simulate_self_fee as sim  # noqa: E402
from math_engine import Pool, amm_out  # noqa: E402
from polygon_guard import polygon_decide  # noqa: E402

DEC = 10**18
TKA = "0x00000000000000000000000000000000000000aa"
TKB = "0x00000000000000000000000000000000000000bb"


def _fake_pair(r0, r1, token0_addr):
    p = MagicMock()
    p.functions.getReserves.return_value.call.return_value = (r0, r1, 0)
    p.functions.token0.return_value.call.return_value = token0_addr
    return p


class _FakeBal:
    def __init__(self, v):
        self._v = v

    def call(self):
        return self._v


class _FakeFns:
    def __init__(self, bal):
        self._bal = bal

    def balanceOf(self, owner):
        return _FakeBal(self._bal)


class _FakeERC20:
    def __init__(self, bal):
        self.functions = _FakeFns(bal)


class TestV2FeeMath(unittest.TestCase):
    def test_swap_fee_is_0_3_pct_of_input(self):
        """amm_out with fee == no-fee output of a 0.997x smaller input."""
        out_fee = amm_out(1000.0, 50_000.0, 50_000.0, fee_bps=30)
        out_nofee = amm_out(1000.0, 50_000.0, 50_000.0, fee_bps=0)
        out_reduced = amm_out(1000.0 * 0.997, 50_000.0, 50_000.0, fee_bps=0)
        self.assertAlmostEqual(out_fee, out_reduced, places=9)
        # the fee in output terms is positive but slightly below 0.3% of input
        # (the fee also reduces the price impact)
        self.assertGreater(out_nofee - out_fee, 0)
        self.assertLess(out_nofee - out_fee, 1000.0 * 0.003)

    def test_k_grows_by_the_fee(self):
        """After a swap, K grows: the fee stays in the reserves (LP accrual)."""
        x, y = 50_000.0, 50_000.0
        amount_in = 2_500.0
        out = amm_out(amount_in, y, x, fee_bps=30)
        k_before = x * y
        k_after = (x - out) * (y + amount_in)
        self.assertGreater(k_after, k_before)
        # K growth ≈ fee * (something small) — positive and tiny, not zero
        self.assertAlmostEqual(k_after / k_before - 1, 0.000149, delta=0.00001)

    def test_get_amount_in_satisfies_k_check(self):
        """getAmountIn (repayment) passes the pair's K-check; minus 1 wei fails."""
        xa, ya = 50_000 * DEC, 50_000 * DEC
        borrow = 1_115 * DEC
        repay = sim.get_amount_in(borrow, ya, xa)
        # pair K-check: (bal0*1000 - in0*3) * (bal1*1000 - in1*3) >= r0*r1*1000^2
        # borrow token0 out, repay token1 in:
        bal0, bal1 = xa - borrow, ya + repay
        lhs = (bal0 * 1000) * (bal1 * 1000 - repay * 3)
        rhs = xa * ya * 1000**2
        self.assertGreaterEqual(lhs, rhs)
        # one wei less must FAIL (proves the +1 / exact fee accounting)
        repay_less = repay - 1
        bal1_less = ya + repay_less
        lhs_less = (bal0 * 1000) * (bal1_less * 1000 - repay_less * 3)
        self.assertLess(lhs_less, rhs)

    def test_repay_is_loan_plus_fee_not_more(self):
        """getAmountIn(amm_out(L)) == L up to dust; the leg fee is ~0.3%."""
        xa, ya = 50_000 * DEC, 50_000 * DEC
        loan = 1_144 * DEC
        borrow = int(amm_out(loan / DEC, ya / DEC, xa / DEC) * DEC)
        repay = sim.get_amount_in(borrow, ya, xa)
        # exact in real arithmetic; integer/float rounding leaves only dust
        self.assertLess(abs(repay - loan), 10**7)  # < 1e-11 $ of dust
        # the fee embedded in the repayment is ~0.3% of the repayment
        repay_no_fee = borrow * ya // (xa - borrow)
        fee = repay - repay_no_fee
        self.assertAlmostEqual(fee / repay, 0.003, delta=0.0001)


class TestWealthAccounting(unittest.TestCase):
    def test_owner_wealth_hand_computed(self):
        """LP share 0.5 of a (50000,50000) pool at P=1.05 + wallet 100/200."""
        pair_a = _fake_pair(50_000 * DEC, 50_000 * DEC, TKA)
        pair_b = _fake_pair(50_000 * DEC, 50_000 * DEC, TKA)
        balances = {TKA: 100 * DEC, TKB: 200 * DEC}
        sim.ERC20 = lambda addr: _FakeERC20(balances[addr])
        w = sim.owner_wealth(pair_a, pair_b, 0.5, 0.0, TKA, TKB, "0xowner", 1.05)
        # 0.5 * (50000*1.05 + 50000) + 100*1.05 + 200 = 51250 + 305
        self.assertAlmostEqual(w, 51_555.0, places=4)

    def test_owner_wealth_token_order_independent(self):
        """Reserves are mapped by token address, not by slot order."""
        pair_a = _fake_pair(50_000 * DEC, 50_000 * DEC, TKB)  # token0 = TKB
        pair_b = _fake_pair(50_000 * DEC, 50_000 * DEC, TKB)
        balances = {TKA: 0, TKB: 0}
        sim.ERC20 = lambda addr: _FakeERC20(balances[addr])
        w = sim.owner_wealth(pair_a, pair_b, 1.0, 0.0, TKA, TKB, "0xowner", 1.05)
        self.assertAlmostEqual(w, 102_500.0, places=4)


class TestGuardSizing(unittest.TestCase):
    def test_guard_executes_on_10_pct_spread(self):
        buy = Pool("A(cheap)", 50_000.0, 50_000.0)
        sell = Pool("B(dear)", 52_500.0, 47_625.85)
        d = polygon_decide(buy, sell, 279.0)
        self.assertEqual(d["action"], "EXECUTE")
        self.assertGreater(d["expected_net_usd"], 0)
        self.assertGreater(d["optimal_loan_usd"], 0)
        self.assertLessEqual(d["optimal_loan_usd"], 5_000.0)

    def test_guard_skips_on_flat_market(self):
        buy = Pool("A", 50_000.0, 50_000.0)
        sell = Pool("B", 50_000.0, 50_000.0)
        d = polygon_decide(buy, sell, 279.0)
        self.assertEqual(d["action"], "SKIP")


class TestNoBroadcast(unittest.TestCase):
    def test_sim_script_is_localhost_only(self):
        src = (BASE / "simulate_self_fee.py").read_text()
        self.assertIn("127.0.0.1:8546", src)
        self.assertNotIn("https://polygon.drpc.org", src)
        self.assertNotIn("https://mainnet.base.org", src)
        self.assertNotIn("polygon-rpc.com", src)
        self.assertIn("evm_snapshot", src)
        self.assertIn("evm_revert", src)

    def test_no_real_key_material(self):
        src = (BASE / "simulate_self_fee.py").read_text()
        self.assertNotIn("codemaofficiel", src)
        self.assertNotIn("PRIVATE_KEY", src)
        # only the public anvil test mnemonic (derives the funded test accounts)
        self.assertIn("test test test test test test test test test test test junk", src)


class TestForkResultsDecomposition(unittest.TestCase):
    """Reads simulation_results.json and re-verifies every identity."""

    @classmethod
    def setUpClass(cls):
        cls.r = json.load(open(BASE / "simulation_results.json"))

    def test_guard_prediction_matches_realized_profit(self):
        iv = self.r["cases"]["iv_own_one_pair_self_arb"]
        iii = self.r["cases"]["iii_external_arb"]
        self.assertEqual(iv["guard_action"], "EXECUTE")
        self.assertAlmostEqual(iv["guard_expected_net_usd"],
                               iii["external_arber_profit_usd"], delta=0.05)

    def test_trader_profit_identity(self):
        """L_A + L_B - fee_A - fee_B == stranger's realized profit."""
        iv = self.r["cases"]["iv_own_one_pair_self_arb"]
        iii = self.r["cases"]["iii_external_arb"]
        P = iv["fair_price_tkb_per_tka"]

        def val(res):
            return res[0] * P + res[1]
        d_a = val(iv["reserves_a_after"]) - val(iv["reserves_a_before"])
        d_b = val(iv["reserves_b_after"]) - val(iv["reserves_b_before"])
        l_a = iv["fee_leg_a_usd"] - d_a
        l_b = iv["fee_leg_b_usd"] - d_b
        profit = l_a + l_b - iv["fee_leg_a_usd"] - iv["fee_leg_b_usd"]
        self.assertAlmostEqual(profit, iii["external_arber_profit_usd"], delta=0.01)

    def test_own_one_pair_is_half_the_plain_profit(self):
        """(iv) delta == L_B - fee_B - gas ≈ half the plain arb profit."""
        iv = self.r["cases"]["iv_own_one_pair_self_arb"]
        iii = self.r["cases"]["iii_external_arb"]
        d = self.r["deltas_vs_hold_usd"]
        P = iv["fair_price_tkb_per_tka"]

        def val(res):
            return res[0] * P + res[1]
        d_b = val(iv["reserves_b_after"]) - val(iv["reserves_b_before"])
        l_b = iv["fee_leg_b_usd"] - d_b
        self.assertAlmostEqual(d["iv_own_one_pair_minus_hold"],
                               l_b - iv["fee_leg_b_usd"] - iv["gas_paid_usd"],
                               delta=0.01)
        # within $1 of half the plain (stranger's) profit
        self.assertAlmostEqual(d["iv_own_one_pair_minus_hold"],
                               iii["external_arber_profit_usd"] / 2, delta=1.0)

    def test_own_both_is_minus_gas_exactly(self):
        d = self.r["deltas_vs_hold_usd"]
        ii = self.r["cases"]["ii_self_arb_own_both"]
        self.assertAlmostEqual(d["ii_own_both_minus_hold_both"],
                               -ii["gas_paid_usd"], delta=0.001)

    def test_self_arb_beats_external_by_the_arbers_profit(self):
        d = self.r["deltas_vs_hold_usd"]
        iii = self.r["cases"]["iii_external_arb"]
        self.assertAlmostEqual(d["iv_minus_iii"],
                               iii["external_arber_profit_usd"] - iii["gas_paid_by_stranger_usd"],
                               delta=0.01)

    def test_external_arb_costs_the_owner(self):
        """Letting a stranger arb costs the owner L_A - fee_A (> 0)."""
        d = self.r["deltas_vs_hold_usd"]
        self.assertLess(d["iii_external_minus_hold"], 0)


if __name__ == "__main__":
    unittest.main()
