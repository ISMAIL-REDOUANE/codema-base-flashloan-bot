#!/usr/bin/env python3
"""
test_big_pools_triangle.py — Tests grosses pools + triangle (Polygon v4.1).

Couverture :
  - math pure du cycle triangulaire (frais sur chaque jambe déjà dans les
    quotes ; gas + budget revert comptés en plus ; règle v4.1 net > 0 $) ;
  - tranches >0$ / ≥0,50$ / ≥3$ ;
  - MONITOR-ONLY : triangle_detector.py ne contient AUCUN code de
    broadcast (vérification statique du source) et ne peut pas exécuter ;
  - big_pools.py est lecture seule lui aussi ;
  - découverte DexScreener : Balancer (pairAddress composite) exclu,
    adresse invalide exclue ;
  - classify_pool : adresse invalide -> "unknown" sans appel on-chain.
Aucun appel réseau live dans ces tests (DexScreener mocké).
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import big_pools as bp  # noqa: E402
import triangle_detector as td  # noqa: E402
from polygon_guard import tranche, tranche_counts  # noqa: E402

HERE = Path(__file__).parent


class TestTriangleNetMath(unittest.TestCase):
    def test_fees_on_every_leg_counted(self):
        # 3 jambes : chacune perd 0,1 % (frais + impact déjà dans les quotes).
        # Départ 1 000 $ -> final 997,00 $ ; gas 0,013 $ + revert 0,013 $.
        r = td.triangle_net_usd(1000.0, 997.0, 0.013)
        self.assertAlmostEqual(r["gross_usd"], -3.0, places=2)
        self.assertAlmostEqual(r["total_cost_usd"], 0.026, places=3)
        self.assertAlmostEqual(r["net_usd"], -3.026, places=3)
        self.assertEqual(r["action"], "SKIP")
        self.assertEqual(r["tranche"], "<=0$")

    def test_positive_net_logs(self):
        # Gain brut +5 $ sur 1 000 $ -> net +4,97 $ -> LOG, tranche >=3$.
        r = td.triangle_net_usd(1000.0, 1005.0, 0.013)
        self.assertEqual(r["action"], "LOG")
        self.assertEqual(r["tranche"], ">=3$")
        self.assertGreater(r["net_usd"], 0)

    def test_small_net_050_logs(self):
        # Règle v4.1 : un petit net +0,50 $ est une opportunité (LOG).
        r = td.triangle_net_usd(1000.0, 1000.53, 0.013)
        self.assertEqual(r["action"], "LOG")
        self.assertEqual(r["tranche"], ">=0.50$")
        self.assertAlmostEqual(r["net_usd"], 0.504, places=3)

    def test_zero_net_blocked(self):
        # Net exactement 0,00 $ -> bloqué (pas de LOG, pas d'exécution).
        r = td.triangle_net_usd(1000.0, 1000.026, 0.013)
        self.assertAlmostEqual(r["net_usd"], 0.0, places=2)
        self.assertEqual(r["action"], "SKIP")

    def test_negative_net_blocked(self):
        r = td.triangle_net_usd(1000.0, 990.0, 0.013)
        self.assertEqual(r["action"], "SKIP")
        self.assertLess(r["net_usd"], 0)

    def test_revert_budget_equals_gas(self):
        # Pire cas budgété : gas + gas de revert = 2 x gas.
        r = td.triangle_net_usd(1000.0, 1000.0, 0.02)
        self.assertAlmostEqual(r["revert_budget_usd"], 0.02, places=4)
        self.assertAlmostEqual(r["total_cost_usd"], 0.04, places=4)
        self.assertAlmostEqual(r["net_usd"], -0.04, places=4)

    def test_gas_grows_with_size_estimate(self):
        # 600 000 unités : le gas d'un triangle coûte ~1,33 x celui d'un
        # trade simple (450 000 unités) au même prix du gas.
        self.assertEqual(td.TRIANGLE_GAS_UNITS, 600_000)


class TestTrancheDistribution(unittest.TestCase):
    def test_tranche_counts(self):
        nets = [5.0, 0.75, 0.5, 0.12, 0.0, -1.0, 3.0, 2.99]
        counts = tranche_counts(nets)
        self.assertEqual(counts[">0$"], 6)
        self.assertEqual(counts[">=0.50$"], 5)  # 5.0, 0.75, 0.5, 3.0, 2.99
        self.assertEqual(counts[">=3$"], 2)
        self.assertEqual(counts["<=0$"], 2)

    def test_tranche_boundaries(self):
        self.assertEqual(tranche(0.0), "<=0$")
        self.assertEqual(tranche(0.01), ">0$")
        self.assertEqual(tranche(0.49), ">0$")
        self.assertEqual(tranche(0.50), ">=0.50$")
        self.assertEqual(tranche(2.99), ">=0.50$")
        self.assertEqual(tranche(3.0), ">=3$")


class TestMonitorOnly(unittest.TestCase):
    def test_mode_is_monitor_only(self):
        self.assertEqual(td.MODE, "MONITOR-ONLY")

    @staticmethod
    def _code_without_docstring(path: Path) -> str:
        """Code source sans la docstring du module (les mots « broadcast »
        etc. y figurent pour expliquer l'absence de broadcast)."""
        src = path.read_text()
        parts = src.split('"""', 2)
        return parts[2] if len(parts) == 3 else src

    def test_triangle_detector_has_no_broadcast_code(self):
        src = self._code_without_docstring(HERE / "triangle_detector.py")
        forbidden = ["send_transaction", "sendTransaction", "build_transaction",
                     "sign_transaction", "private_key", "PrivateKey",
                     "eth_send", "raw_transaction", "broadcast",
                     "w3.eth.account", "Account.from_key"]
        for token in forbidden:
            self.assertNotIn(token, src,
                             f"triangle_detector.py ne doit pas contenir {token!r}")

    def test_triangle_detector_never_calls_execute(self):
        # Le seul "action" possible est LOG / SKIP — pas d'EXECUTE.
        src = (HERE / "triangle_detector.py").read_text()
        self.assertNotIn('"EXECUTE"', src)
        self.assertNotIn("'EXECUTE'", src)

    def test_big_pools_is_read_only(self):
        src = self._code_without_docstring(HERE / "big_pools.py")
        forbidden = ["send_transaction", "sendTransaction", "build_transaction",
                     "sign_transaction", "private_key", "PrivateKey",
                     "eth_send", "raw_transaction", "broadcast"]
        for token in forbidden:
            self.assertNotIn(token, src,
                             f"big_pools.py ne doit pas contenir {token!r}")

    def test_no_execution_function_in_either_module(self):
        self.assertFalse(hasattr(td, "execute_cycle"))
        self.assertFalse(hasattr(td, "execute"))
        self.assertFalse(hasattr(bp, "execute"))


class TestDiscoverVenuesFiltering(unittest.TestCase):
    def _dex_payload(self, pairs):
        return {"pairs": pairs}

    def test_balancer_composite_address_excluded(self):
        payload = self._dex_payload([
            {"chainId": "polygon", "dexId": "balancer",
             "pairAddress": "0x0297e37f1873D2DAb4487Aa67cD56B58E2F27875"
                            "-0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
                            "-0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
             "baseToken": {"address": bp.TOKENS["WMATIC"][0]},
             "quoteToken": {"address": bp.TOKENS["USDC.e"][0]},
             "liquidity": {"usd": 41057.32}},
            {"chainId": "polygon", "dexId": "quickswap",
             "pairAddress": "0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827",
             "baseToken": {"address": bp.TOKENS["WMATIC"][0]},
             "quoteToken": {"address": bp.TOKENS["USDC.e"][0]},
             "liquidity": {"usd": 530363.04}},
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        with patch.object(bp.S, "get", return_value=resp):
            venues = bp.discover_venues(("WMATIC", "USDC.e"))
        dexes = [v["dex"] for v in venues]
        self.assertNotIn("balancer", dexes)
        self.assertIn("quickswap", dexes)

    def test_invalid_pair_address_excluded(self):
        payload = self._dex_payload([
            {"chainId": "polygon", "dexId": "weird-dex",
             "pairAddress": "not-an-address",
             "baseToken": {"address": bp.TOKENS["WMATIC"][0]},
             "quoteToken": {"address": bp.TOKENS["USDC.e"][0]},
             "liquidity": {"usd": 99999.0}},
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        with patch.object(bp.S, "get", return_value=resp):
            venues = bp.discover_venues(("WMATIC", "USDC.e"))
        self.assertEqual(venues, [])

    def test_non_polygon_and_thin_venues_excluded(self):
        payload = self._dex_payload([
            {"chainId": "ethereum", "dexId": "uniswap",
             "pairAddress": "0xA374094527e1673A86dE625aa59517c5dE346d32",
             "baseToken": {"address": bp.TOKENS["WMATIC"][0]},
             "quoteToken": {"address": bp.TOKENS["USDC.e"][0]},
             "liquidity": {"usd": 137225.26}},
            {"chainId": "polygon", "dexId": "quickswap",
             "pairAddress": "0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827",
             "baseToken": {"address": bp.TOKENS["WMATIC"][0]},
             "quoteToken": {"address": bp.TOKENS["USDC.e"][0]},
             "liquidity": {"usd": 500.0}},  # trop fine (< 10 k $)
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        with patch.object(bp.S, "get", return_value=resp):
            venues = bp.discover_venues(("WMATIC", "USDC.e"))
        self.assertEqual(venues, [])


class TestClassifyPool(unittest.TestCase):
    def test_invalid_address_is_unknown_without_rpc(self):
        self.assertEqual(bp.classify_pool(None, "not-an-address"), "unknown")
        self.assertEqual(bp.classify_pool(None, ""), "unknown")
        self.assertEqual(bp.classify_pool(None, None), "unknown")

    def test_balancer_composite_id_is_unknown(self):
        composite = ("0x0297e37f1873D2DAb4487Aa67cD56B58E2F27875"
                     "-0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
                     "-0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        self.assertEqual(bp.classify_pool(None, composite), "unknown")


class TestBigPoolsConfig(unittest.TestCase):
    def test_pairs_and_sizes(self):
        self.assertEqual(len(bp.PAIRS), 7)
        self.assertIn(("WMATIC", "USDC.e"), bp.PAIRS)
        self.assertIn(("WMATIC", "USDT"), bp.PAIRS)
        self.assertIn(("WETH", "USDC.e"), bp.PAIRS)
        self.assertIn(("USDC.e", "USDT"), bp.PAIRS)
        self.assertIn(("WMATIC", "WETH"), bp.PAIRS)
        self.assertIn(("USDC.e", "DAI"), bp.PAIRS)
        self.assertEqual(bp.SIZES_USD, [1000.0, 5000.0, 20000.0])
        self.assertEqual(bp.MIN_LIQ_VENUE_USD, 10_000.0)

    def test_static_fallback_venues_are_real_addresses(self):
        from web3 import Web3
        for pair, venues in bp.STATIC_VENUES.items():
            for dex, addr in venues:
                self.assertTrue(Web3.is_address(addr),
                                f"{pair} {dex} : adresse invalide {addr}")


if __name__ == "__main__":
    unittest.main()
