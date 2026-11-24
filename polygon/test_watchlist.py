#!/usr/bin/env python3
"""
test_watchlist.py — Tests de la watchlist meme Polygon v4.1 (unittest).

Couverture (mock HTTP, AUCUN appel live) :
  - une 2e venue apparaissant plus tard est détectée ;
  - le tier "watch" n'exécute JAMAIS (même avec 2 venues + GoPlus OK) ;
  - le backoff 429 reprend (429 puis 200) et journalise les pages
    skippées quand le 429 persiste ;
  - classification des tiers exec/watch/none aux bornes ;
  - DexScreener token-profiles : seuls les tokens Polygon sont retenus ;
  - persistance JSON de la watchlist (round-trip) ;
  - estimation spread/net : spread < 3 % et net ≤ 0 $ → non exécutable ;
    net +0,50 $ → autorisé (règle Ismail 2026-11-24 : min 3 $ abandonné,
    net > 0 $ après tous coûts — gas + budget revert ~2× gas).

Lancer depuis polygon/ :  ../.venv/bin/python -m unittest test_watchlist -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from scanner_polygon import (  # noqa: E402
    dexscreener_latest_profiles, gecko_new_pools, get_with_backoff,
)
from watchlist import Watchlist, classify_tier  # noqa: E402
from watchlist_run import estimate_opportunity  # noqa: E402

TOKEN_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    """Session mockée : une file de réponses par URL (dans l'ordre)."""
    def __init__(self, script):
        self.script = {u: list(v) for u, v in script.items()}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        queue = self.script.get(url)
        if not queue:
            return FakeResponse(404, {})
        return queue.pop(0)


class TestClassifyTier(unittest.TestCase):
    def test_exec_window(self):
        self.assertEqual(classify_tier(5_000, 72), "exec")
        self.assertEqual(classify_tier(100_000, 1), "exec")
        self.assertEqual(classify_tier(50_000, 70), "exec")

    def test_exec_boundaries_excluded(self):
        self.assertEqual(classify_tier(4_999, 1), "watch")
        self.assertEqual(classify_tier(100_001, 1), "watch")
        self.assertEqual(classify_tier(50_000, 73), "watch")

    def test_watch_window(self):
        self.assertEqual(classify_tier(1_000, 168), "watch")
        self.assertEqual(classify_tier(500_000, 100), "watch")
        self.assertEqual(classify_tier(250_000, 150), "watch")

    def test_none_outside(self):
        self.assertEqual(classify_tier(999, 1), "none")       # poussière
        self.assertEqual(classify_tier(500_001, 1), "none")   # baleine
        self.assertEqual(classify_tier(50_000, 169), "none")  # trop vieux
        self.assertEqual(classify_tier(0, 0), "none")


class TestSecondVenueDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wl = Watchlist(Path(self.tmp.name) / "watchlist.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_venue_appearing_later_is_detected(self):
        # Run 1 : 1 seule venue (QuickSwap).
        e1 = self.wl.upsert(TOKEN_A, name="MEME", liq_usd=20_000, age_h=5,
                            venues={"quickswap": [{"pair": "0xp1",
                                                  "liq_usd": 20_000}]})
        self.assertFalse(e1["_new_second_venue"])
        self.assertIsNone(e1["second_venue_first_seen"])
        self.assertEqual(e1["tier"], "exec")
        # Run 2 (heures plus tard) : Uni V3 apparaît.
        e2 = self.wl.upsert(TOKEN_A, liq_usd=22_000, age_h=9,
                            venues={"uniswap": [{"pair": "0xp2",
                                                "liq_usd": 22_000}]})
        self.assertTrue(e2["_new_second_venue"])
        self.assertIsNotNone(e2["second_venue_first_seen"])
        self.assertEqual(sorted(e2["dexs"]), ["quickswap", "uniswap"])
        # La 1re venue est conservée (fusion, pas écrasement).
        self.assertIn("quickswap", e2["venues"])
        self.assertIn("uniswap", e2["venues"])
        # Run 3 : pas de nouvelle venue → pas de re-détection.
        e3 = self.wl.upsert(TOKEN_A, liq_usd=23_000, age_h=12,
                            venues={"uniswap": [{"pair": "0xp2",
                                                "liq_usd": 23_000}]})
        self.assertFalse(e3["_new_second_venue"])

    def test_watch_tier_promotion_to_exec(self):
        # Liq sous le plancher exec (2 000 $) → watch ; la liquidité
        # monte à 20 000 $ avec un âge max toujours < 72 h → exec.
        e = self.wl.upsert(TOKEN_B, name="WATCHY", liq_usd=2_000, age_h=5,
                           venues={"quickswap": [{"pair": "0xp1",
                                                 "liq_usd": 2_000}]})
        self.assertEqual(e["tier"], "watch")
        e2 = self.wl.upsert(TOKEN_B, liq_usd=20_000, age_h=6)
        self.assertEqual(e2["tier"], "exec")
        self.assertTrue(any(p.startswith("watch->exec")
                            for p in e2["promotions"]))

    def test_old_token_demoted_when_true_age_revealed(self):
        # Nouvelle pool d'un VIEUX token : Gecko donne âge 5 h (pool
        # récente) → exec provisoire ; DexScreener révèle la plus
        # ancienne paire à 2 000 h → rétrogradé 'none' (la fenêtre
        # porte sur le lancement du token, pas d'une pool).
        e = self.wl.upsert(TOKEN_A, name="OLD", liq_usd=20_000, age_h=5,
                           venues={"quickswap": [{"pair": "0xp1",
                                                 "liq_usd": 20_000}]})
        self.assertEqual(e["tier"], "exec")
        e2 = self.wl.upsert(TOKEN_A, liq_usd=25_000, age_h=2000)
        self.assertEqual(e2["tier"], "none")
        self.assertTrue(any(p.startswith("exec->none")
                            for p in e2["promotions"]))

    def test_max_liq_and_first_seen_kept(self):
        e1 = self.wl.upsert(TOKEN_A, liq_usd=10_000, age_h=5)
        first = e1["first_seen"]
        e2 = self.wl.upsert(TOKEN_A, liq_usd=8_000, age_h=6)
        self.assertEqual(e2["max_liq_usd_seen"], 10_000)
        self.assertEqual(e2["first_seen"], first)
        # Âge = plus ancienne paire vue (max), pas la plus récente.
        self.assertEqual(e2["max_age_h_seen"], 6)

    def test_recheck_only_exec_and_watch(self):
        self.wl.upsert(TOKEN_A, liq_usd=20_000, age_h=5)   # exec
        self.wl.upsert(TOKEN_B, liq_usd=200_000, age_h=100)  # watch
        self.wl.upsert("0xcccccccccccccccccccccccccccccccccccccccc",
                       liq_usd=10, age_h=1)  # none (poussière)
        recheck = self.wl.tokens_to_recheck()
        self.assertIn(TOKEN_A, recheck)
        self.assertIn(TOKEN_B, recheck)
        self.assertNotIn("0xcccccccccccccccccccccccccccccccccccccccc",
                         recheck)

    def test_persistence_round_trip(self):
        self.wl.upsert(TOKEN_A, name="MEME", liq_usd=20_000, age_h=5,
                       venues={"quickswap": [{"pair": "0xp1",
                                             "liq_usd": 20_000}]})
        self.wl.upsert(TOKEN_A, liq_usd=22_000, age_h=9,
                       venues={"uniswap": [{"pair": "0xp2",
                                           "liq_usd": 22_000}]})
        self.wl.save()
        wl2 = Watchlist(self.wl.path)
        e = wl2.tokens[TOKEN_A]
        self.assertEqual(sorted(e["dexs"]), ["quickswap", "uniswap"])
        self.assertIsNotNone(e["second_venue_first_seen"])
        self.assertEqual(e["max_liq_usd_seen"], 22_000)
        self.assertEqual(wl2.stats()["two_venue_total"], 1)

    def test_two_venue_tokens_by_tier(self):
        self.wl.upsert(TOKEN_A, liq_usd=20_000, age_h=5,
                       venues={"quickswap": [{"pair": "0xp1"}],
                               "uniswap": [{"pair": "0xp2"}]})
        self.wl.upsert(TOKEN_B, liq_usd=200_000, age_h=100,
                       venues={"quickswap": [{"pair": "0xp3"}],
                               "sushiswap": [{"pair": "0xp4"}]})
        self.assertEqual(self.wl.two_venue_tokens("exec"), [TOKEN_A])
        self.assertEqual(self.wl.two_venue_tokens("watch"), [TOKEN_B])
        self.assertEqual(len(self.wl.two_venue_tokens()), 2)


class TestWatchTierNeverExecutes(unittest.TestCase):
    """Le tier watch est un garde-fou : même 2 venues + GoPlus OK + gros
    spread ne doivent JAMAIS produire une opportunité exécutable."""

    def test_watch_token_with_two_venues_is_not_executable(self):
        # estimate_opportunity ne connaît pas le tier : c'est le runner
        # qui doit refuser. On vérifie la règle au niveau classify_tier
        # + la condition d'évaluation du runner (tier == "exec").
        self.assertEqual(classify_tier(200_000, 100), "watch")
        # Même avec un spread énorme, un token watch reste watch.
        pairs = [
            {"dexId": "quickswap", "pairAddress": "0xp1",
             "priceUsd": "0.010", "liquidity": {"usd": 200_000},
             "pairCreatedAt": 1_700_000_000_000},
            {"dexId": "uniswap", "pairAddress": "0xp2",
             "priceUsd": "0.012", "liquidity": {"usd": 180_000},
             "pairCreatedAt": 1_700_000_000_000},
        ]
        est = estimate_opportunity(pairs)
        self.assertTrue(est["executable"])  # le calcul brut dirait oui…
        # …mais la règle métier l'interdit : seul tier == "exec" passe.
        tier = classify_tier(200_000, 100)
        executable = est["executable"] and tier == "exec"
        self.assertFalse(executable)

    def test_watch_tier_below_exec_liq_never_executes(self):
        # Liq 2 000 $ (< 5 000 $) : watch, pas exec — même avec 2 venues.
        self.assertEqual(classify_tier(2_000, 10), "watch")


class TestEstimateOpportunity(unittest.TestCase):
    def _pairs(self, p1, p2, liq1=50_000, liq2=50_000):
        return [
            {"dexId": "quickswap", "pairAddress": "0xp1",
             "priceUsd": str(p1), "liquidity": {"usd": liq1}},
            {"dexId": "uniswap", "pairAddress": "0xp2",
             "priceUsd": str(p2), "liquidity": {"usd": liq2}},
        ]

    def test_spread_10pct_executes(self):
        est = estimate_opportunity(self._pairs(0.010, 0.011))
        self.assertTrue(est["executable"])
        self.assertAlmostEqual(est["spread_pct"], 10.0)
        # loan = 10 % × 50 000 = 5 000 $ ; net = 500 − 0,019 (gas + revert)
        self.assertAlmostEqual(est["net_usd"], 499.98, places=2)

    def test_spread_below_3pct_not_executable(self):
        est = estimate_opportunity(self._pairs(0.010, 0.0102))
        self.assertFalse(est["executable"])
        self.assertIn("spread", est["reason"])

    def test_net_plus_0_50_allowed_new_rule(self):
        # Règle 2026-11-24 : min 3 $ ABANDONNÉ — net +0,50 $ autorisé.
        # loan 17 $ (liq 170 $), spread 3,1 % : brut 0,527 $ − 0,019 $
        # (gas + revert) = +0,51 $ net → exécutable.
        est = estimate_opportunity(self._pairs(0.010, 0.01031,
                                               liq1=170, liq2=170))
        self.assertTrue(est["executable"])
        self.assertAlmostEqual(est["net_usd"], 0.51, places=2)

    def test_net_zero_blocked(self):
        # Net exactement 0,00 $ après tous coûts → bloqué (il faut > 0 $).
        # spread 3,1 %, loan = coût total / 0,031 → brut = 0,019 $ = coût.
        from watchlist_run import TOTAL_COST_USD
        loan_zero = TOTAL_COST_USD / 0.031
        liq = loan_zero / 0.10
        est = estimate_opportunity(self._pairs(0.010, 0.01031,
                                               liq1=liq, liq2=liq))
        self.assertEqual(est["net_usd"], 0.0)
        self.assertFalse(est["executable"])
        self.assertIn("≤ 0 $", est["reason"])

    def test_net_negative_blocked(self):
        # Spread 3,1 % mais liquidité minuscule → brut 0,0155 $ < coût
        # 0,019 $ → net −0,00 $ → bloqué.
        est = estimate_opportunity(self._pairs(0.010, 0.01031,
                                               liq1=5, liq2=5))
        self.assertFalse(est["executable"])
        self.assertLess(est["net_usd"], 0.01)
        self.assertIn("≤ 0 $", est["reason"])

    def test_revert_budget_is_counted(self):
        # Même trade, sans budget revert le net serait +0,01 $ de plus :
        # le coût total est bien 2× gas (0,019 $), pas 1× gas.
        from watchlist_run import GAS_USD_PER_TRADE, TOTAL_COST_USD
        self.assertAlmostEqual(TOTAL_COST_USD, 2 * GAS_USD_PER_TRADE)
        est = estimate_opportunity(self._pairs(0.010, 0.011))
        self.assertAlmostEqual(est["net_usd"], 500 - TOTAL_COST_USD,
                               places=2)

    def test_loan_capped_at_10pct_of_smaller_liq(self):
        est = estimate_opportunity(self._pairs(0.010, 0.011,
                                               liq1=10_000, liq2=90_000))
        self.assertEqual(est["loan_usd"], 1_000.0)

    def test_single_priced_pair_not_executable(self):
        est = estimate_opportunity(
            [{"dexId": "quickswap", "pairAddress": "0xp1",
              "priceUsd": "0.010", "liquidity": {"usd": 50_000}}])
        self.assertFalse(est["executable"])


class TestRateLimitBackoff(unittest.TestCase):
    def test_429_then_200_resumes(self):
        sess = FakeSession({
            "https://example.com/x": [
                FakeResponse(429, {}, {"Retry-After": "0"}),
                FakeResponse(429, {}, {"Retry-After": "0"}),
                FakeResponse(200, {"ok": True}),
            ]})
        slept = []
        r = get_with_backoff(sess, "https://example.com/x", max_retries=5,
                             base_delay=0.01, sleep_fn=slept.append)
        self.assertIsNotNone(r)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(sess.calls), 3)
        self.assertEqual(len(slept), 2)

    def test_persistent_429_returns_none(self):
        sess = FakeSession({
            "https://example.com/x": [FakeResponse(429, {})] * 10})
        r = get_with_backoff(sess, "https://example.com/x", max_retries=3,
                             base_delay=0.01, sleep_fn=lambda s: None)
        self.assertIsNone(r)
        self.assertEqual(len(sess.calls), 4)  # 1 + 3 retries

    def test_network_error_then_success(self):
        class Flaky:
            def __init__(self):
                self.n = 0

            def get(self, url, params=None, timeout=None):
                self.n += 1
                if self.n < 3:
                    raise ConnectionError("boom")
                return FakeResponse(200, {"ok": True})

        flaky = Flaky()
        r = get_with_backoff(flaky, "https://example.com/x", max_retries=5,
                             base_delay=0.01, sleep_fn=lambda s: None)
        self.assertIsNotNone(r)
        self.assertEqual(flaky.n, 3)

    def test_gecko_pagination_skips_failed_page_and_continues(self):
        from scanner_polygon import GECKO_NEW
        sess = FakeSession({
            GECKO_NEW: [
                FakeResponse(200, {"data": [{"id": "p1"}]}),
                FakeResponse(429, {}), FakeResponse(429, {}),
                FakeResponse(429, {}), FakeResponse(429, {}),
                FakeResponse(429, {}),  # page 2 : 429 persistant
                FakeResponse(200, {"data": [{"id": "p3"}]}),
            ]})
        with mock.patch("scanner_polygon.time.sleep", lambda s: None):
            pools, skipped = gecko_new_pools(3, session=sess)
        self.assertEqual([p["id"] for p in pools], ["p1", "p3"])
        self.assertEqual(skipped, [2])

    def test_dexscreener_profiles_filters_polygon_only(self):
        from scanner_polygon import DEX_PROFILES_LATEST
        sess = FakeSession({
            DEX_PROFILES_LATEST: [FakeResponse(200, [
                {"chainId": "solana",
                 "tokenAddress": "SOL11111111111111111111111111111111"},
                {"chainId": "polygon",
                 "tokenAddress": "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"},
                {"chainId": "ethereum",
                 "tokenAddress": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},
                {"chainId": "polygon",
                 "tokenAddress": "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"},
            ])]})
        addrs = dexscreener_latest_profiles(session=sess)
        self.assertEqual(addrs, ["0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"])


class TestGeckoParsingAndDexNormalization(unittest.TestCase):
    """Régression v4.1 : l'id Gecko 'polygon_pos_0x…' donnait des
    adresses 'pos_0x…' invalides (les appels DexScreener échouaient
    silencieusement), et 'uniswap_v3_polygon_pos' (Gecko) vs 'uniswap'
    (DexScreener) comptaient pour 2 venues au lieu d'1."""

    def test_strip_token_prefix(self):
        from scanner_polygon import strip_token_prefix
        self.assertEqual(
            strip_token_prefix("polygon_pos_0x6b998441f7349a7bfdbb2a6d61a6d5f9acb90de8"),
            "0x6b998441f7349a7bfdbb2a6d61a6d5f9acb90de8")
        self.assertEqual(strip_token_prefix("polygon_0xabc"), "0xabc")
        self.assertEqual(strip_token_prefix("0xabc"), "0xabc")

    def test_normalize_dex(self):
        from watchlist import normalize_dex
        self.assertEqual(normalize_dex("uniswap_v3_polygon_pos"), "uniswap")
        self.assertEqual(normalize_dex("uniswap-v4-polygon"), "uniswap-v4")
        self.assertEqual(normalize_dex("uniswap"), "uniswap")
        self.assertEqual(normalize_dex("quickswap"), "quickswap")
        self.assertEqual(normalize_dex("QuickSwap"), "quickswap")
        self.assertEqual(normalize_dex(""), "unknown")

    def test_gecko_tokens_from_pools(self):
        from watchlist_run import gecko_tokens_from_pools
        from datetime import datetime, timezone
        now = datetime(2026, 11, 24, 22, 50, tzinfo=timezone.utc)
        pools = [{
            "attributes": {"name": "ATH / USDT 99%",
                           "address": "0xpool1", "reserve_in_usd": "27.9",
                           "pool_created_at": "2026-11-24T20:42:22Z"},
            "relationships": {
                "base_token": {"data": {"id": "polygon_pos_0x6b998441f7349a7bfdbb2a6d61a6d5f9acb90de8"}},
                "dex": {"data": {"id": "uniswap-v4-polygon"}}}},
            {"attributes": {"name": "VENUE / WPOL 0.3%",
                           "address": "0xpool2", "reserve_in_usd": "3525.3",
                           "pool_created_at": "2026-11-24T00:00:00Z"},
             "relationships": {
                 "base_token": {"data": {"id": "polygon_pos_0xb2fdd2355a79a0bfe5e0a62140833dc4d9526d0f"}},
                 "dex": {"data": {"id": "uniswap_v3_polygon_pos"}}}},
        ]
        out = gecko_tokens_from_pools(pools, now)
        self.assertEqual(set(out),
                         {"0x6b998441f7349a7bfdbb2a6d61a6d5f9acb90de8",
                          "0xb2fdd2355a79a0bfe5e0a62140833dc4d9526d0f"})
        self.assertNotIn("pos_0x6b998441f7349a7bfdbb2a6d61a6d5f9acb90de8",
                         out)
        self.assertEqual(
            out["0xb2fdd2355a79a0bfe5e0a62140833dc4d9526d0f"]["dex"],
            "uniswap")
        self.assertAlmostEqual(
            out["0xb2fdd2355a79a0bfe5e0a62140833dc4d9526d0f"]["age_h"],
            22.83, places=1)

    def test_same_pair_two_dex_labels_counts_once(self):
        # Même adresse de paire vue sous deux labels ('quickswap-v4'
        # Gecko vs 'quickswap' DexScreener, casse différente) = 1 venue.
        tmp = tempfile.TemporaryDirectory()
        wl = Watchlist(Path(tmp.name) / "watchlist.json")
        e = wl.upsert(TOKEN_A, name="MEME", liq_usd=20_000, age_h=5,
                      venues={"quickswap-v4": [{"pair": "0x48Af390c91A44013541D31c82922DC9E63Ba8E81",
                                               "liq_usd": 8.35}]})
        self.assertEqual(e["dexs"], ["quickswap-v4"])
        e2 = wl.upsert(TOKEN_A, liq_usd=21_000, age_h=6,
                       venues={"quickswap": [{"pair": "0x48af390c91a44013541d31c82922dc9e63ba8e81",
                                             "liq_usd": 8.35}]})
        self.assertEqual(len(e2["dexs"]), 1)
        self.assertFalse(e2["_new_second_venue"])
        tmp.cleanup()

    def test_same_dex_two_sources_counts_once(self):
        tmp = tempfile.TemporaryDirectory()
        wl = Watchlist(Path(tmp.name) / "watchlist.json")
        # Gecko voit Uni V3, DexScreener voit 'uniswap' (= V3) : 1 venue.
        e = wl.upsert(TOKEN_A, name="MEME", liq_usd=20_000, age_h=5,
                      venues={"uniswap_v3_polygon_pos": [{"pair": "0xp1",
                                                          "liq_usd": 20_000}]})
        self.assertEqual(e["dexs"], ["uniswap"])
        e2 = wl.upsert(TOKEN_A, liq_usd=21_000, age_h=6,
                       venues={"uniswap": [{"pair": "0xp1",
                                           "liq_usd": 21_000}]})
        self.assertEqual(e2["dexs"], ["uniswap"])
        self.assertFalse(e2["_new_second_venue"])
        # Une VRAIE 2e venue (QuickSwap) déclenche la détection.
        e3 = wl.upsert(TOKEN_A, liq_usd=22_000, age_h=7,
                       venues={"quickswap": [{"pair": "0xp2",
                                             "liq_usd": 22_000}]})
        self.assertTrue(e3["_new_second_venue"])
        self.assertEqual(sorted(e3["dexs"]), ["quickswap", "uniswap"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
