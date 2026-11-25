#!/usr/bin/env python3
"""Tests du listener temps reel Polygon v4.4 (unittest, hors-ligne sauf
les tests marques live — aucun n'est live ici : le multicall et le
websocket sont moques)."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import realtime_listener as rl
from eth_abi import encode

HERE = Path(__file__).parent


def fake_v2_venue(pair_addr, token0, fee_bps=30):
    return {"dex": "quickswap", "pair": pair_addr, "kind": "v2",
            "fee_tier": None, "fee_bps": fee_bps, "liq_usd": 100000.0,
            "token0": token0}


def make_resolved():
    return {
        "AAA": {"address": "0x1111111111111111111111111111111111111111",
                "decimals": 6},
        "BBB": {"address": "0x2222222222222222222222222222222222222222",
                "decimals": 6},
        "WMATIC": {"address": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                   "decimals": 18},
    }


def make_listener(tmpdir, pairs, resolved, prices):
    mock_w3 = MagicMock()
    mock_w3.eth.get_code.return_value = b"\x60\x60\x60"
    inventory = {"pairs": pairs, "prices": prices,
                 "gas_gwei": 279.0, "source": "test"}
    out = Path(tmpdir) / "signals.jsonl"
    return rl.Listener(mock_w3, inventory, resolved, prices, out, 30.0)


class TestBackoffAndChunking(unittest.TestCase):
    def test_backoff_delay_sequence(self):
        self.assertEqual([rl.backoff_delay(i) for i in range(8)],
                         [1, 2, 4, 8, 16, 30, 30, 30])
        self.assertEqual(rl.backoff_delay(-1), 1)

    def test_chunk_calls(self):
        calls = list(range(250))
        chunks = rl.chunk_calls(calls)
        self.assertEqual([len(c) for c in chunks], [100, 100, 50])
        self.assertEqual(rl.chunk_calls([]), [])
        self.assertEqual(len(rl.chunk_calls(list(range(100)))), 1)


class TestInventory(unittest.TestCase):
    def test_parse_pair_label(self):
        self.assertEqual(rl.parse_pair_label("WMATIC/USDC.e (intra-Uni)"),
                         ("WMATIC", "USDC.e"))
        self.assertEqual(rl.parse_pair_label("LINK/USDT"),
                         ("LINK", "USDT"))

    def test_load_inventory_from_measurement(self):
        # Fichier epingle (connu au moment de l'ecriture du test) :
        # l'agent pro-scan peut ecrire un fichier plus recent apres.
        pinned = HERE / "pro_scan_measurement_2026-11-24T2359.json"
        meas = pinned if pinned.exists() else rl.latest_pro_scan_measurement()
        self.assertIsNotNone(meas)
        inv = rl.load_inventory_from_measurement(meas)
        self.assertEqual(len(inv["pairs"]), 15)
        n_venues = sum(len(p["venues"]) for p in inv["pairs"])
        self.assertEqual(n_venues, 44)
        kinds = {}
        for p in inv["pairs"]:
            for v in p["venues"]:
                kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
        self.assertEqual(kinds, {"v3-uni": 25, "v4": 6, "v2": 10,
                                 "algebra": 3})
        self.assertIn("WMATIC", inv["prices"])

    def test_v4_slots(self):
        pid = bytes.fromhex("ab" * 32)
        s0, liq = rl.v4_slots(pid)
        self.assertEqual(len(s0), 32)
        self.assertEqual(len(liq), 32)
        self.assertEqual(int.from_bytes(liq, "big")
                         - int.from_bytes(s0, "big"), 3)


class TestMulticallBuildDecode(unittest.TestCase):
    def test_build_calls_all_kinds(self):
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [
                fake_v2_venue("0x3333333333333333333333333333333333333333",
                              "0x1111111111111111111111111111111111111111"),
                {"dex": "uniswap", "pair":
                 "0x4444444444444444444444444444444444444444",
                 "kind": "v3-uni", "fee_tier": 500, "fee_bps": 5,
                 "liq_usd": 50000.0,
                 "token0": "0x1111111111111111111111111111111111111111"},
                {"dex": "quickswap", "pair":
                 "0x5555555555555555555555555555555555555555",
                 "kind": "algebra", "fee_tier": None, "fee_bps": None,
                 "liq_usd": 50000.0,
                 "token0": "0x1111111111111111111111111111111111111111"},
                {"dex": "uniswap-v4", "pair": "0x" + "cd" * 32,
                 "kind": "v4", "fee_tier": 500, "fee_bps": 5,
                 "liq_usd": 50000.0,
                 "slot0_slot": b"\x00" * 32, "liq_slot": b"\x01" * 32},
            ]}]
        calls, decoding = rl.build_multicall_calls(pairs)
        # v2:1 + v3:2 + algebra:2 + v4:2 = 7 sous-appels
        self.assertEqual(len(calls), 7)
        self.assertEqual(len(decoding), 7)
        self.assertEqual(calls[0][2], rl.SEL["getReserves"])
        self.assertEqual(calls[1][2], rl.SEL["slot0"])
        self.assertEqual(calls[2][2], rl.SEL["liquidity"])
        self.assertEqual(calls[3][2], rl.SEL["globalState"])
        self.assertEqual(calls[5][2][:4], rl.SEL["extsload"])
        self.assertEqual(calls[5][0], rl.POOL_MANAGER)

    def test_decode_states_v2(self):
        resolved = make_resolved()
        a = resolved["AAA"]["address"]
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [fake_v2_venue(
                "0x3333333333333333333333333333333333333333", a)]}]
        # res_a = 100 000 AAA, res_b = 1 BBB (token0 = AAA)
        data = encode(["uint112", "uint112", "uint32"],
                      [100_000 * 10**6, 1 * 10**6, 12345])
        rl.decode_states([(True, data)], [(0, 0, "v2-reserves")], pairs,
                         resolved)
        v = pairs[0]["venues"][0]
        self.assertAlmostEqual(v["res_a"], 100000.0)
        self.assertAlmostEqual(v["res_b"], 1.0)
        self.assertEqual(v["fee_bps"], 30)

    def test_decode_states_v3(self):
        resolved = make_resolved()
        a = resolved["AAA"]["address"]
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [{
                "dex": "uniswap",
                "pair": "0x4444444444444444444444444444444444444444",
                "kind": "v3-uni", "fee_tier": 500, "fee_bps": 5,
                "liq_usd": 50000.0, "token0": a}]}]
        # sqrt = 2**96 * 0.01, liq = 10**12 -> x = 10**14, y = 10**10
        sqrt = int(2**96 * 0.01)
        slot0 = encode(["uint160", "int24", "uint16", "uint16", "uint16",
                        "uint8", "bool"], [sqrt, 0, 0, 0, 0, 0, True])
        liq = encode(["uint128"], [10**12])
        rl.decode_states(
            [(True, slot0), (True, liq)],
            [(0, 0, "v3-slot0"), (0, 0, "v3-liquidity")], pairs, resolved)
        v = pairs[0]["venues"][0]
        self.assertAlmostEqual(v["res_a"], 10**14 / 10**6, delta=1.0)
        self.assertAlmostEqual(v["res_b"], 10**10 / 10**6, delta=1.0)


class TestEvaluatePair(unittest.TestCase):
    def _pair(self, res_buy, res_sell):
        a = "0x1111111111111111111111111111111111111111"
        return {
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [
                {**fake_v2_venue(
                    "0x3333333333333333333333333333333333333333", a),
                 "res_a": res_buy[0], "res_b": res_buy[1]},
                {**fake_v2_venue(
                    "0x4444444444444444444444444444444444444444", a),
                 "res_a": res_sell[0], "res_b": res_sell[1]},
            ]}

    def test_synthetic_positive_executes(self):
        # Venue achat : A bon marche (100 000 A / 1 000 B -> 0,01 $/A).
        # Venue vente : A cher (100 A / 10 000 B -> 100 $/A).
        # Les deux cotes B valent >= 1 000 $ : le cap de liquidite
        # (10 % de la plus petite reserve USDC) laisse passer un loan.
        pair = self._pair((100000.0, 1000.0), (100.0, 10000.0))
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        res = rl.evaluate_pair(pair, 279.0, 0.0758, prices,
                               make_resolved(), 123)
        net = res["sizes"]["1000.0"]["net"]
        self.assertEqual(net["action"], "EXECUTE")
        self.assertGreater(net["expected_net_usd"], 0)
        self.assertGreater(res["sizes"]["1000.0"]["spread_pct"], 0)

    def test_identical_venues_skip(self):
        pair = self._pair((1000.0, 1000.0), (1000.0, 1000.0))
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        res = rl.evaluate_pair(pair, 279.0, 0.0758, prices,
                               make_resolved(), 123)
        net = res["sizes"]["1000.0"]["net"]
        self.assertEqual(net["action"], "SKIP")
        self.assertLessEqual(net["expected_net_usd"], 0)

    def test_missing_price_skips_pair(self):
        pair = self._pair((100000.0, 1.0), (1.0, 100000.0))
        res = rl.evaluate_pair(pair, 279.0, 0.0758, {"AAA": 1.0},
                               make_resolved(), 123)
        self.assertEqual(res["sizes"], {})
        self.assertIn("skipped_reason", res)


class TestRotation(unittest.TestCase):
    def test_rotation_subset_covers_all(self):
        pairs = list(range(15))
        seen = set()
        for block in range(3):
            idxs = rl.rotation_subset(pairs, block, 5)
            self.assertEqual(len(idxs), 5)
            self.assertEqual(len(set(idxs)), 5)
            seen.update(idxs)
        self.assertEqual(seen, set(range(15)))
        # Rotation decalee d'un bloc.
        self.assertEqual(rl.rotation_subset(pairs, 0, 5), [0, 1, 2, 3, 4])
        self.assertEqual(rl.rotation_subset(pairs, 1, 5), [5, 6, 7, 8, 9])
        # n >= len(paires) : tout, tout le temps.
        self.assertEqual(rl.rotation_subset(pairs, 7, 20), list(range(15)))
        self.assertEqual(rl.rotation_subset([], 0, 5), [])


class TestBlockHandlerWithMockedMulticall(unittest.TestCase):
    def test_process_block_signals_and_logs(self):
        resolved = make_resolved()
        a = resolved["AAA"]["address"]
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [
                fake_v2_venue(
                    "0x3333333333333333333333333333333333333333", a),
                fake_v2_venue(
                    "0x4444444444444444444444444444444444444444", a),
            ]}]
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp, pairs, resolved, prices)
            # Resultats Multicall fabriques : venue 1 = A bon marche
            # (100 000 A / 1 000 B), venue 2 = A cher (100 A / 10 000 B)
            # — meme ordre que build_multicall_calls.
            r1 = encode(["uint112", "uint112", "uint32"],
                        [100_000 * 10**6, 1_000 * 10**6, 1])
            r2 = encode(["uint112", "uint112", "uint32"],
                        [100 * 10**6, 10_000 * 10**6, 1])
            fake_results = [(True, r1), (True, r2)]
            with patch.object(rl, "multicall_aggregate3",
                              return_value=fake_results):
                # Verification exacte moquee (pas de RPC) : on force
                # la verification a None (V2 sans router = locale).
                res = listener.process_block(100, 279.0, time.time())
            listener.close()
            self.assertEqual(res["block"], 100)
            self.assertGreaterEqual(res["signals"], 1)
            self.assertEqual(listener.blocks_processed, 1)
            self.assertGreater(listener.quotes, 0)
            lines = (Path(tmp) / "signals.jsonl").read_text().splitlines()
            recs = [json.loads(x) for x in lines]
            sigs = [r for r in recs if r.get("type") == "signal"]
            self.assertGreaterEqual(len(sigs), 1)
            sig = sigs[0]
            for field in ("block", "pair", "spread_pct", "net_usd",
                          "optimal_loan_usd", "buy_venue", "sell_venue",
                          "gas_gwei", "method"):
                self.assertIn(field, sig)
            self.assertGreater(sig["net_usd"], 0)
            self.assertEqual(sig["block"], 100)
            # Rejeu du meme bloc : ignore (pas de double comptage).
            with patch.object(rl, "multicall_aggregate3",
                              return_value=fake_results):
                res2 = listener.process_block(100, 279.0, time.time())
            self.assertEqual(res2.get("skipped"), "deja traite")

    def test_process_block_tracks_closest_misses(self):
        resolved = make_resolved()
        a = resolved["AAA"]["address"]
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [
                fake_v2_venue(
                    "0x3333333333333333333333333333333333333333", a),
                fake_v2_venue(
                    "0x4444444444444444444444444444444444444444", a),
            ]}]
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp, pairs, resolved, prices)
            # Reserves identiques : aucun signal, que des manques.
            r = encode(["uint112", "uint112", "uint32"],
                       [1000 * 10**6, 1000 * 10**6, 1])
            with patch.object(rl, "multicall_aggregate3",
                              return_value=[(True, r), (True, r)]):
                listener.process_block(101, 279.0, time.time())
            listener.close()
            self.assertEqual(listener.signals, 0)
            self.assertLessEqual(len(listener.closest_misses), 5)
            self.assertTrue(all(m["net_usd"] <= 0
                                for m in listener.closest_misses))
            self.assertEqual(
                listener.closest_misses,
                sorted(listener.closest_misses,
                       key=lambda e: -e["net_usd"]))


class TestMulticallRetryAndMissedCounting(unittest.TestCase):
    def _listener_and_results(self, tmp):
        resolved = make_resolved()
        a = resolved["AAA"]["address"]
        pairs = [{
            "label": "AAA/BBB", "section": "test", "token_a": "AAA",
            "token_b": "BBB",
            "venues": [
                fake_v2_venue(
                    "0x3333333333333333333333333333333333333333", a),
                fake_v2_venue(
                    "0x4444444444444444444444444444444444444444", a),
            ]}]
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        listener = make_listener(tmp, pairs, resolved, prices)
        r1 = encode(["uint112", "uint112", "uint32"],
                    [100_000 * 10**6, 1_000 * 10**6, 1])
        r2 = encode(["uint112", "uint112", "uint32"],
                    [100 * 10**6, 10_000 * 10**6, 1])
        return listener, [(True, r1), (True, r2)]

    def test_multicall_retry_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener, fake_results = self._listener_and_results(tmp)
            with patch.object(
                    rl, "multicall_aggregate3",
                    side_effect=[None, None, fake_results]):
                res = listener.process_block(200, 279.0, time.time())
            listener.close()
            self.assertFalse(listener.rotation_mode)
            self.assertEqual(listener.rpc_errors, 0)
            self.assertGreaterEqual(res["signals"], 1)

    def test_multicall_retry_exhausted_switches_to_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener, _ = self._listener_and_results(tmp)
            with patch.object(rl, "multicall_aggregate3",
                              return_value=None), \
                 patch.object(rl.bp, "venue_reserves",
                              return_value=(100000.0, 1000.0, 30)):
                res = listener.process_block(200, 279.0, time.time())
            listener.close()
            self.assertTrue(listener.rotation_mode)
            self.assertGreaterEqual(listener.rpc_errors, 1)
            self.assertIn("results", res)

    def test_missed_blocks_counted_once(self):
        # Ecart de 4 blocs entre deux blocs traites = 4 manques,
        # comptes une seule fois (pas de double comptage file + ecart).
        with tempfile.TemporaryDirectory() as tmp:
            listener, fake_results = self._listener_and_results(tmp)
            with patch.object(rl, "multicall_aggregate3",
                              return_value=fake_results):
                listener.process_block(100, 279.0, time.time())
                listener.process_block(105, 279.0, time.time())
            listener.close()
            self.assertEqual(listener.blocks_missed, 4)
            self.assertEqual(listener.blocks_processed, 2)


class TestReconnectFailClosed(unittest.TestCase):
    def test_ws_fails_closed_after_max_reconnects(self):
        resolved = make_resolved()
        prices = {"AAA": 1.0, "BBB": 1.0, "WMATIC": 0.0758}
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp, [], resolved, prices)
            with patch.object(rl, "WSS_ENDPOINTS",
                              ["ws://127.0.0.1:1"]), \
                 patch.object(rl, "MAX_RECONNECTS", 2):
                t0 = time.time()
                asyncio.run(rl.ws_listen(
                    listener, time.time() + 120.0))
                dt = time.time() - t0
            listener.close()
            # 2 tentatives + backoff 1 s : termine vite, sans boucle.
            self.assertLess(dt, 20)
            self.assertGreaterEqual(listener.rpc_errors, 2)


class TestNoBroadcastStatic(unittest.TestCase):
    def test_module_has_no_broadcast_surface(self):
        src = (HERE / "realtime_listener.py").read_text()
        for forbidden in ("send_transaction", "build_transaction",
                          "private_key"):
            self.assertNotIn(forbidden, src.lower(),
                             f"chaine interdite trouvee : {forbidden}")
        # Aucune cle / portefeuille dans le module.
        self.assertNotIn("eth_sendTransaction", src)
        self.assertNotIn("raw_transaction", src.lower())


if __name__ == "__main__":
    unittest.main()
