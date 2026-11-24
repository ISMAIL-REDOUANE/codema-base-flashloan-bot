#!/usr/bin/env python3
"""
test_revert_protection.py — Tests du routeur revert Polygon v4.2
(unittest, sans dépendance, offline sauf mention contraire).

Couverture : un trade qui revert en re-simulation est DROPPÉ avant
broadcast (0 $ gas) ; quote trop vieille DROP ; net <= 0 DROP ;
repli fail-closed quand la route privée est down (par défaut NE PAS
ENVOYER) ; repli public autorisé seulement si explicitement activé ;
journal des issues correct ; coût attendu des reverts résiduels ;
parse des réponses eth_call (succès / revert).

Lancer depuis polygon/ :  ../.venv/bin/python -m unittest test_revert_protection -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from revert_protection import (  # noqa: E402
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    PRIVATE_ROUTE_VERIFIED_FOR_REVERT,
    REVERT_GAS_USD_MEASURED,
    REVERT_GAS_USD_PRUDENT,
    DryRunSender,
    RevertRouter,
    RouteOutcome,
    SendResult,
    SimResult,
    eth_call_simulate,
    expected_revert_cost_usd,
    parse_eth_call_response,
    router_from_config,
)

TX = {"from": "0x0000000000000000000000000000000000000001",
      "to": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67",
      "data": "0x", "value": "0x0", "gas": "0x6d60"}
NOW = 1_800_000_000.0


def _ok(tx):
    return SimResult(success=True, net_usd=0.5, block_number=97_902_229)


def _revert(tx):
    return SimResult(success=False, reason="revert simulé (pool vidée)")


class _RecordingSender:
    """Faux sender qui enregistre les appels et répond ce qu'on lui dit."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result or SendResult(
            status="sent", tx_hash="0xabc", gas_paid_usd=0.0028,
            reason="envoyé (faux sender)")

    def send(self, route, raw_tx):
        self.calls.append((route, raw_tx))
        return self.result


class TestParseEthCall(unittest.TestCase):
    def test_success_result_parses_ok(self):
        r = parse_eth_call_response({"jsonrpc": "2.0", "id": 1,
                                     "result": "0x000000000000000000000000000000000000000000000000000000000000002a"})
        self.assertTrue(r.success)

    def test_error_parses_as_revert(self):
        r = parse_eth_call_response({"jsonrpc": "2.0", "id": 1,
                                     "error": {"code": 3,
                                               "message": "execution reverted"}})
        self.assertFalse(r.success)
        self.assertIn("reverted", r.reason)

    def test_empty_response_is_failure(self):
        self.assertFalse(parse_eth_call_response({}).success)
        self.assertFalse(parse_eth_call_response({"error": {}}).success)


class TestRevertRouterDrops(unittest.TestCase):
    def test_would_revert_trade_dropped_before_broadcast_zero_gas(self):
        """(i) Le cas central : trade qui revert en re-sim -> DROP, 0 $ gas,
        le sender n'est JAMAIS appelé (rien n'atteint la chaîne)."""
        sender = _RecordingSender()
        r = RevertRouter(log_file=None, simulate_fn=_revert, sender=sender)
        out = r.route_trade(TX, NOW, 0.5, raw_tx="0xdead", now=NOW)
        self.assertEqual(out.decision, "dropped_presend")
        self.assertEqual(out.gas_paid_usd, 0.0)
        self.assertEqual(sender.calls, [])
        self.assertIn("DROP", out.reason)

    def test_stale_quote_dropped(self):
        r = RevertRouter(log_file=None, simulate_fn=_ok,
                         sender=_RecordingSender())
        out = r.route_trade(TX, NOW - DEFAULT_MAX_QUOTE_AGE_SECONDS - 1,
                            0.5, now=NOW)
        self.assertEqual(out.decision, "dropped_presend")
        self.assertEqual(out.gas_paid_usd, 0.0)
        self.assertIn("vieille", out.reason)

    def test_fresh_quote_at_limit_passes_freshness(self):
        sender = _RecordingSender()
        r = RevertRouter(log_file=None, simulate_fn=_ok, sender=sender)
        out = r.route_trade(TX, NOW - DEFAULT_MAX_QUOTE_AGE_SECONDS,
                            0.5, now=NOW)
        self.assertEqual(out.decision, "sent")
        self.assertEqual(len(sender.calls), 1)

    def test_nonpositive_net_dropped(self):
        sender = _RecordingSender()
        r = RevertRouter(log_file=None, simulate_fn=_ok, sender=sender)
        for net in (0.0, -0.5):
            out = r.route_trade(TX, NOW, net, now=NOW)
            self.assertEqual(out.decision, "dropped_presend")
            self.assertEqual(out.gas_paid_usd, 0.0)
        self.assertEqual(sender.calls, [])

    def test_profitable_fresh_trade_goes_through(self):
        sender = _RecordingSender()
        r = RevertRouter(log_file=None, simulate_fn=_ok, sender=sender)
        out = r.route_trade(TX, NOW, 0.5, raw_tx="0xdead", now=NOW)
        self.assertEqual(out.decision, "sent")
        self.assertEqual(out.tx_hash, "0xabc")
        self.assertAlmostEqual(out.gas_paid_usd, 0.0028)
        self.assertEqual(sender.calls[0][0], "public")

    def test_default_sender_is_dry_run_and_sends_nothing(self):
        r = RevertRouter(log_file=None, simulate_fn=_ok)
        out = r.route_trade(TX, NOW, 0.5, now=NOW)
        self.assertEqual(out.decision, "dry_run")
        self.assertEqual(out.gas_paid_usd, 0.0)
        self.assertIsNone(out.tx_hash)


class TestPrivateRouteFallback(unittest.TestCase):
    def test_private_route_without_endpoint_refused_at_construction(self):
        with self.assertRaises(ValueError):
            RevertRouter(route="private", private_endpoint=None,
                         log_file=None)

    def test_private_route_down_fail_closed_by_default(self):
        """(ii) Route privée down + défaut fail-closed -> NE PAS ENVOYER."""
        sender = _RecordingSender()
        r = RevertRouter(route="private",
                         private_endpoint="https://127.0.0.1:9/nope",
                         private_timeout_seconds=0.1,
                         log_file=None, simulate_fn=_ok, sender=sender)
        out = r.route_trade(TX, NOW, 0.5, now=NOW)
        self.assertEqual(out.decision, "dropped_route_down")
        self.assertEqual(out.gas_paid_usd, 0.0)
        self.assertEqual(sender.calls, [])

    def test_private_route_down_public_fallback_when_explicitly_allowed(self):
        sender = _RecordingSender()
        r = RevertRouter(route="private",
                         private_endpoint="https://127.0.0.1:9/nope",
                         private_timeout_seconds=0.1,
                         allow_public_fallback=True,
                         log_file=None, simulate_fn=_ok, sender=sender)
        out = r.route_trade(TX, NOW, 0.5, now=NOW)
        self.assertEqual(out.decision, "sent")
        self.assertEqual(out.route, "public")
        self.assertEqual(len(sender.calls), 1)

    def test_private_route_never_claims_zero_revert(self):
        self.assertFalse(PRIVATE_ROUTE_VERIFIED_FOR_REVERT)
        r = RevertRouter(route="private",
                         private_endpoint="https://127.0.0.1:9/nope",
                         log_file=None)
        self.assertFalse(r.private_revert_guarantee)

    def test_private_endpoint_reachable_false_without_endpoint(self):
        r = RevertRouter(log_file=None)
        self.assertFalse(r.private_endpoint_reachable())

    def test_unknown_route_rejected(self):
        with self.assertRaises(ValueError):
            RevertRouter(route="sidechain", log_file=None)


class TestLedgerAndAccounting(unittest.TestCase):
    def test_ledger_records_outcome_correctly(self):
        """(iii) Chaque tentative est journalisée avec sa vraie issue."""
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "rp.jsonl")
            sender = _RecordingSender()
            r = RevertRouter(log_file=log, simulate_fn=_ok, sender=sender)
            r.route_trade(TX, NOW, 0.5, raw_tx="0xdead", now=NOW)
            r2 = RevertRouter(log_file=log, simulate_fn=_revert)
            r2.route_trade(TX, NOW, 0.5, now=NOW)
            with open(log, encoding="utf-8") as f:
                lines = [json.loads(x) for x in f]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["decision"], "sent")
            self.assertEqual(lines[0]["gas_paid_usd"], 0.0028)
            self.assertEqual(lines[0]["net_usd"], 0.5)
            self.assertEqual(lines[1]["decision"], "dropped_presend")
            self.assertEqual(lines[1]["gas_paid_usd"], 0.0)
            for line in lines:
                self.assertIn("timestamp", line)
                self.assertIn("route", line)

    def test_reverted_onchain_outcome_records_gas_paid(self):
        sender = _RecordingSender(SendResult(
            status="reverted_onchain", tx_hash="0xbad",
            gas_paid_usd=REVERT_GAS_USD_MEASURED,
            reason="revert on-chain (race)"))
        r = RevertRouter(log_file=None, simulate_fn=_ok, sender=sender)
        out = r.route_trade(TX, NOW, 0.5, now=NOW)
        self.assertEqual(out.decision, "reverted_onchain")
        self.assertAlmostEqual(out.gas_paid_usd, REVERT_GAS_USD_MEASURED)

    def test_expected_revert_cost_math(self):
        self.assertAlmostEqual(expected_revert_cost_usd(0.05), 0.000475)
        self.assertAlmostEqual(expected_revert_cost_usd(0.0), 0.0)
        self.assertAlmostEqual(
            expected_revert_cost_usd(0.10, REVERT_GAS_USD_MEASURED),
            0.00024)
        with self.assertRaises(ValueError):
            expected_revert_cost_usd(1.5)
        with self.assertRaises(ValueError):
            expected_revert_cost_usd(0.05, -1.0)

    def test_log_failure_never_blocks_routing(self):
        r = RevertRouter(log_file="/nonexistent_dir/rp.jsonl",
                         simulate_fn=_ok)
        out = r.route_trade(TX, NOW, 0.5, now=NOW)
        self.assertEqual(out.decision, "dry_run")


class TestRouterFromConfig(unittest.TestCase):
    def test_defaults_are_fail_closed(self):
        r = router_from_config({})
        self.assertEqual(r.route, "public")
        self.assertIsNone(r.private_endpoint)
        self.assertFalse(r.allow_public_fallback)
        self.assertEqual(r.max_quote_age_seconds,
                         DEFAULT_MAX_QUOTE_AGE_SECONDS)
        self.assertAlmostEqual(r.revert_budget_usd, REVERT_GAS_USD_PRUDENT)

    def test_config_values_applied(self):
        cfg = {"revert_protection": {
            "route": "public", "max_quote_age_seconds": 10,
            "allow_public_fallback": True,
            "revert_budget_usd": 0.0024, "log_file": None},
            "chain": {"rpc_url": "https://polygon.drpc.org"}}
        r = router_from_config(cfg)
        self.assertEqual(r.max_quote_age_seconds, 10)
        self.assertTrue(r.allow_public_fallback)
        self.assertAlmostEqual(r.revert_budget_usd, 0.0024)

    def test_config_private_without_endpoint_raises(self):
        with self.assertRaises(ValueError):
            router_from_config({"revert_protection": {
                "route": "private", "private_endpoint": None}})


if __name__ == "__main__":
    unittest.main()
