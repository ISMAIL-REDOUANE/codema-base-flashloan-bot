#!/usr/bin/env python3
"""
test_pro_scan.py — Tests scan PRO Polygon v4.3.

Couverture :
  - V4 : calcul du PoolId (déterministe), décodage de l'état via extsload
    (slot0 + liquidité), réserves virtuelles + orientation, fee dynamique
    -> non cotable ;
  - V3 : découverte des fee tiers via factory (mockée) ;
  - mid-caps : token non vérifiable -> SKIP (None), jamais deviné ;
  - agrégat : meilleurs spread/net + tranches sur échantillons synthétiques ;
  - MONITOR-ONLY : pro_scan.py ne contient AUCUN code de broadcast
    (vérification statique du source) et n'exécute rien.
Aucun appel réseau live dans ces tests (RPC / DexScreener mockés).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pro_scan as ps  # noqa: E402
from polygon_guard import tranche_counts  # noqa: E402

HERE = Path(__file__).parent
ZERO = "0x0000000000000000000000000000000000000000"


def _slot0_bytes(sqrt_price_x96: int, tick: int, lp_fee: int) -> bytes:
    """Encode un Slot0 V4 (uint160 + int24 + uint24 proto + uint24 lp)."""
    tick_u = tick & 0xFFFFFF
    v = (sqrt_price_x96 & (2**160 - 1)) | (tick_u << 160) | (lp_fee << 208)
    return v.to_bytes(32, "big")


class TestV4PoolId(unittest.TestCase):
    def test_deterministic_and_fee_sensitive(self):
        a = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
        b = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        pid1 = ps.v4_pool_id(a, b, 500, 10, ZERO)
        pid2 = ps.v4_pool_id(a, b, 500, 10, ZERO)
        pid3 = ps.v4_pool_id(a, b, 3000, 60, ZERO)
        pid4 = ps.v4_pool_id(b, a, 500, 10, ZERO)  # ordre inversé
        self.assertEqual(len(pid1), 32)
        self.assertEqual(pid1, pid2)
        self.assertNotEqual(pid1, pid3)
        # L'ordre des tokens compte dans le hash : c'est l'appelant qui
        # trie (currency0 < currency1) avant d'appeler v4_pool_id.
        self.assertNotEqual(pid1, pid4)

    def test_pool_id_is_32_bytes_for_any_key(self):
        # La formule produit un id stable de 32 octets pour n'importe quelle
        # clé (la validation réelle est la lecture extsload live, pas ici).
        pid = ps.v4_pool_id("0xef87ea7da714ac5140b7fc49f84f2a3914875120",
                            "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
                            500, 10, ZERO)
        self.assertEqual(len(pid), 32)


class TestV4PoolState(unittest.TestCase):
    def _mock_w3(self, slot0: bytes, liq: int):
        mock_pm = MagicMock()
        calls = [slot0, liq.to_bytes(32, "big")]
        mock_pm.functions.extsload.return_value.call.side_effect = calls
        w3 = MagicMock()
        w3.eth.contract.return_value = mock_pm
        self._mock_pm = mock_pm
        return w3

    def test_liquidity_read_at_base_plus_3(self):
        # CORRECTION v4.3 : la liquidité est à base+3 (base+1 = feeGrowth).
        from eth_abi import encode as _enc
        from eth_utils import keccak as _k
        pid = bytes.fromhex("aa" * 32)
        base = _k(_enc(["bytes32", "uint256"], [pid, ps.POOLS_MAPPING_SLOT]))
        w3 = self._mock_w3(_slot0_bytes(2**96, 123, 3000), 10**18)
        st = ps.v4_pool_state(w3, pid)
        self.assertEqual(st["liquidity"], 10**18)
        called_slots = [c.args[0] for c in
                        self._mock_pm.functions.extsload.call_args_list]
        self.assertEqual(called_slots[0], base)
        self.assertEqual(called_slots[1],
                         (int.from_bytes(base, "big") + 3).to_bytes(32, "big"))

    def test_decode_slot0_and_liquidity(self):
        sqrt = 2**96  # prix 1
        st = ps.v4_pool_state(
            self._mock_w3(_slot0_bytes(sqrt, 123, 3000), 10**18),
            bytes.fromhex("aa" * 32))
        self.assertIsNotNone(st)
        self.assertEqual(st["sqrt_price_x96"], sqrt)
        self.assertEqual(st["tick"], 123)
        self.assertEqual(st["lp_fee"], 3000)
        self.assertEqual(st["liquidity"], 10**18)

    def test_negative_tick_decoded(self):
        st = ps.v4_pool_state(
            self._mock_w3(_slot0_bytes(2**96, -500, 500), 42),
            bytes.fromhex("bb" * 32))
        self.assertEqual(st["tick"], -500)
        self.assertEqual(st["lp_fee"], 500)

    def test_absent_pool_returns_none(self):
        st = ps.v4_pool_state(
            self._mock_w3(_slot0_bytes(0, 0, 0), 0),
            bytes.fromhex("cc" * 32))
        self.assertIsNone(st)


class TestV4VirtualReserves(unittest.TestCase):
    def test_price_one_equal_reserves(self):
        st = {"sqrt_price_x96": 2**96, "tick": 0, "lp_fee": 3000,
              "liquidity": 10**24, "pool_id": "00"}
        # token0 18 déc, token1 6 déc ; liquidité 1e24 brut.
        res_a, res_b, fee = ps.v4_virtual_reserves(st, 18, 6, True)
        self.assertAlmostEqual(res_a, 10**24 / 10**18, places=6)
        self.assertAlmostEqual(res_b, 10**24 / 10**6, places=6)
        self.assertEqual(fee, 30)

    def test_orientation_token0_is_b(self):
        st = {"sqrt_price_x96": 2**96, "tick": 0, "lp_fee": 500,
              "liquidity": 10**24, "pool_id": "00"}
        res_a, res_b, fee = ps.v4_virtual_reserves(st, 18, 6, False)
        # token0 (= B ici) : res_b doit être la réserve token0.
        self.assertAlmostEqual(res_b, 10**24 / 10**6, places=6)
        self.assertAlmostEqual(res_a, 10**24 / 10**18, places=6)
        self.assertEqual(fee, 5)

    def test_dynamic_fee_not_quotable(self):
        st = {"sqrt_price_x96": 2**96, "tick": 0,
              "lp_fee": ps.DYNAMIC_FEE_FLAG, "liquidity": 10**24,
              "pool_id": "00"}
        _ra, _rb, fee = ps.v4_virtual_reserves(st, 18, 6, True)
        self.assertIsNone(fee)


class TestV3TierDiscovery(unittest.TestCase):
    def test_all_tiers_found(self):
        mock_fac = MagicMock()
        pools = ["0x1111111111111111111111111111111111111111",
                 "0x2222222222222222222222222222222222222222",
                 ZERO,
                 "0x4444444444444444444444444444444444444444"]
        mock_fac.functions.getPool.return_value.call.side_effect = pools
        w3 = MagicMock()
        w3.eth.contract.return_value = mock_fac
        out = ps.discover_v3_tiers(
            w3, "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        self.assertEqual([v["fee_tier"] for v in out], [100, 500, 10000])
        self.assertTrue(all(v["kind"] == "v3-uni" for v in out))

    def test_no_pool_returns_empty(self):
        mock_fac = MagicMock()
        mock_fac.functions.getPool.return_value.call.return_value = ZERO
        w3 = MagicMock()
        w3.eth.contract.return_value = mock_fac
        out = ps.discover_v3_tiers(
            w3, "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        self.assertEqual(out, [])


class TestMidcapResolution(unittest.TestCase):
    def _search_resp(self, pairs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"pairs": pairs}
        return resp

    def test_no_polygon_candidate_skipped(self):
        resp = self._search_resp([
            {"chainId": "ethereum", "dexId": "uniswap",
             "baseToken": {"symbol": "MAI",
                           "address": "0x3C9d6cA5B9F9e8a3c5D6e7F8a9B0c1D2e3F4a5B6"},
             "quoteToken": {"symbol": "USDC", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
             "liquidity": {"usd": 100000}},
        ])
        with patch.object(ps.S, "get", return_value=resp):
            self.assertIsNone(ps.resolve_midcap(MagicMock(), "MAI"))

    def test_symbol_mismatch_skipped(self):
        resp = self._search_resp([
            {"chainId": "polygon", "dexId": "quickswap",
             "baseToken": {"symbol": "MAI",
                           "address": "0x3C9d6cA5B9F9e8a3c5D6e7F8a9B0c1D2e3F4a5B6"},
             "quoteToken": {"symbol": "USDC", "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"},
             "liquidity": {"usd": 50000}},
        ])
        w3 = MagicMock()
        w3.eth.get_code.return_value = b"\x60\x60\x60"
        with patch.object(ps.S, "get", return_value=resp), \
             patch.object(ps, "verify_token", return_value=None):
            self.assertIsNone(ps.resolve_midcap(w3, "MAI"))

    def test_verified_token_returned(self):
        resp = self._search_resp([
            {"chainId": "polygon", "dexId": "uniswap",
             "baseToken": {"symbol": "LINK",
                           "address": "0x53E0bca35eC356BD5ddDFebbD1Fc0fD03FaBad39"},
             "quoteToken": {"symbol": "USDC",
                            "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"},
             "liquidity": {"usd": 340827}},
        ])
        w3 = MagicMock()
        with patch.object(ps.S, "get", return_value=resp), \
             patch.object(ps, "verify_token",
                          return_value={"address": "0x53E0bca35eC356BD5ddDFebbD1Fc0fD03FaBad39",
                                        "decimals": 18}):
            out = ps.resolve_midcap(w3, "LINK")
        self.assertEqual(out["decimals"], 18)
        self.assertEqual(out["address"],
                         "0x53E0bca35eC356BD5ddDFebbD1Fc0fD03FaBad39")


class TestMeasureGenericMissingPrice(unittest.TestCase):
    def test_missing_price_skips_pair_without_crash(self):
        # Un prix de référence absent (CoinGecko/DexScreener en 429) ne
        # doit plus faire planter l'échantillon (KeyError v4.3, échant. 2).
        w3 = MagicMock()
        w3.eth.block_number = 123456
        res = ps.measure_generic(w3, "WETH/USDC.e (test)", "WETH", "USDC.e",
                                 [], 200.0, {"USDC.e": 1.0})
        self.assertEqual(res["sizes"], {})
        self.assertEqual(res["skipped"][0]["kind"], "price")
        self.assertIn("WETH", res["skipped"][0]["reason"])


class TestAggregate(unittest.TestCase):
    def _sample(self, block, nets):
        # nets : liste de (spread_pct, expected_net_usd) par paire/taille
        pairs = []
        for i, (sp, net) in enumerate(nets):
            pairs.append({
                "pair": f"P{i}", "block": block,
                "venues": [], "skipped": [],
                "sizes": {"1000.0": {"spread_pct": sp,
                                     "net": {"expected_net_usd": net,
                                             "action": "EXECUTE" if net > 0
                                             else "SKIP"}}},
            })
        return {"date": "2026-11-24", "block": block,
                "sections": {"intra_uni": pairs, "midcaps": [],
                             "watchlist": []}}

    def test_best_net_and_tranches(self):
        s1 = self._sample(100, [(0.5, 1.25), (-0.1, -0.02)])
        s2 = self._sample(200, [(0.05, 0.10), (-0.2, -0.05)])
        agg = ps.aggregate([s1, s2])
        self.assertEqual(agg["n_samples"], 2)
        self.assertEqual(agg["sections"]["intra_uni"]["n_measures"], 4)
        self.assertAlmostEqual(agg["total"]["best_net_usd"], 1.25)
        self.assertEqual(agg["total"]["tranches"][">0$"], 2)
        self.assertEqual(agg["total"]["tranches"][">=0.50$"], 1)
        self.assertEqual(agg["total"]["tranches"][">=3$"], 0)
        self.assertEqual(agg["total"]["tranches"]["<=0$"], 2)

    def test_empty_samples(self):
        agg = ps.aggregate([])
        self.assertEqual(agg["total"]["n_measures"], 0)
        self.assertIsNone(agg["total"]["best_net_usd"])
        self.assertEqual(agg["total"]["tranches"][">0$"], 0)


class TestMonitorOnly(unittest.TestCase):
    def test_mode_is_monitor_only(self):
        self.assertEqual(ps.MODE, "MONITOR-ONLY")
        self.assertFalse(ps.V4_QUOTER_USABLE)

    @staticmethod
    def _code_without_docstring(path: Path) -> str:
        src = path.read_text()
        parts = src.split('"""', 2)
        return parts[2] if len(parts) == 3 else src

    def test_pro_scan_has_no_broadcast_code(self):
        src = self._code_without_docstring(HERE / "pro_scan.py")
        forbidden = ["send_transaction", "sendTransaction",
                     "build_transaction", "sign_transaction",
                     "private_key", "PrivateKey", "eth_send",
                     "raw_transaction", "broadcast", "w3.eth.account",
                     "Account.from_key"]
        for token in forbidden:
            self.assertNotIn(token, src,
                             f"pro_scan.py ne doit pas contenir {token!r}")

    def test_no_execution_function(self):
        self.assertFalse(hasattr(ps, "execute"))
        self.assertFalse(hasattr(ps, "execute_cycle"))
        self.assertFalse(hasattr(ps, "send_trade"))

    def test_v4_quoter_never_called(self):
        # Le quoter V4 non utilisable : aucun appel (seulement la constante
        # documentée et des mentions dans la docstring / commentaires).
        src = (HERE / "pro_scan.py").read_text()
        self.assertNotIn("V4_QUOTER_ABI", src)
        self.assertNotIn(".functions.quoteExactInputSingle", src)


class TestConfig(unittest.TestCase):
    def test_sections_and_sizes(self):
        self.assertEqual(ps.MAJOR_PAIRS, [
            ("WMATIC", "USDC.e"), ("WMATIC", "USDT"),
            ("WETH", "USDC.e"), ("USDC.e", "USDT")])
        self.assertEqual(ps.MIDCAPS,
                         ["LINK", "AAVE", "GHST", "SAND", "QUICK", "MAI"])
        self.assertEqual(ps.SIZES_USD, [1000.0, 5000.0, 20000.0])
        self.assertEqual(ps.V3_FEE_TIERS, [100, 500, 3000, 10000])
        self.assertEqual(ps.POOLS_MAPPING_SLOT, 6)

    def test_registered_major_tokens(self):
        for sym in ("WMATIC", "USDC.e", "USDT", "WETH", "DAI", "USDC"):
            self.assertIn(sym, ps.TOKEN_INFO)
            self.assertIn(sym, ps.bp.TOKENS)


if __name__ == "__main__":
    unittest.main()
