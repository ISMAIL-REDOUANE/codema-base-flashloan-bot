"""Tests v3.1 — Modèle sponsor (sponsor.py + intégration executor/dry_run).
Lancer : python3 test_sponsor.py (stdlib only).
Ou : python3 -m pytest test_sponsor.py -v"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from executor import run
from math_engine import Costs, Pool
from scanner import MemeCandidate
from sponsor import SponsorLedger, load_from_config


def _fresh():
    """Ledger neuf, sans fichiers (aucun état persisté)."""
    return SponsorLedger(state_path=None, trades_path=None)


def _config_path() -> str:
    """Config pour les tests (audit #13) : config.yaml si présent, sinon
    config.yaml.example — un checkout propre sans config.yaml passe."""
    from pathlib import Path as _P
    return "config.yaml" if _P("config.yaml").exists() else "config.yaml.example"


def test_split_100():
    s = _fresh()
    sponsor, ismail = s.split_profit(100.0)
    assert sponsor == 25.0, sponsor
    assert ismail == 75.0, ismail


def test_split_zero():
    s = _fresh()
    assert s.split_profit(0.0) == (0.0, 0.0)
    assert s.split_profit(-10.0) == (0.0, 0.0)


def test_split_reference_balancer():
    # Cas de référence Balancer v3 : net +73,07 $ -> 25 % = 18,27 $.
    s = _fresh()
    sponsor, ismail = s.split_profit(73.07)
    assert sponsor == 18.27, sponsor
    assert ismail == 54.80, ismail
    assert round(sponsor + ismail, 2) == 73.07


def test_split_self_funded():
    # Ismail s'auto-finance : sponsor_share_pct = 0 -> 100 % pour lui.
    s = SponsorLedger(sponsor_share_pct=0.0, state_path=None, trades_path=None)
    assert s.split_profit(100.0) == (0.0, 100.0)


def test_daily_cap_blocks_sixth_trade():
    # 5 trades à 16 $ de net = 4 $ de part sponsor chacun = 20 $ (plafond).
    # Le 6e trade (même net) doit être BLOQUÉ avec une raison STOP.
    s = _fresh()
    for i in range(5):
        e = s.record_trade(f"T{i}", 16.0, 0.01, "balancer")
        assert not e["blocked"], e
    assert s.sponsor_paid_today_usd == 20.0, s.sponsor_paid_today_usd
    ok, reason, sp, ism = s.check_trade(16.0)
    assert not ok, "le 6e trade doit être bloqué par le plafond"
    assert "plafond" in reason.lower() or "STOP" in reason, reason
    assert sp == 4.0 and ism == 12.0
    e = s.record_trade("T5", 16.0, 0.01, "balancer")
    assert e["blocked"] is True
    assert s.sponsor_paid_today_usd == 20.0, "rien ne doit être ajouté après blocage"


def test_prefund_alert_below_5():
    s = _fresh()  # prefund 20 $
    assert not s.prefund_low()
    assert s.prefund_alert() is None
    # Net 40 $ (part sponsor 10 $, sous le plafond 20 $) + gas 15,50 $.
    s.record_trade("A", 40.0, 15.50, "balancer")  # gas 15,50 $ -> reste 4,50 $
    assert s.prefund_remaining() == 4.50, s.prefund_remaining()
    assert s.prefund_low()
    assert s.prefund_alert() is not None
    assert "4.50" in s.prefund_alert()


def test_prefund_exhausted_blocks():
    s = _fresh()
    # Net 40 $ (part sponsor 10 $) + gas 20 $ = tout le prefund.
    s.record_trade("A", 40.0, 20.0, "balancer")
    assert s.prefund_remaining() == 0.0
    ok, reason = s.can_trade()
    assert not ok
    assert "prefund" in reason.lower()


def test_kill_switch_blocks_all():
    s = _fresh()
    s.kill_switch = True
    ok, reason = s.can_trade()
    assert not ok
    assert "KILL SWITCH" in reason
    ok, reason, _, _ = s.check_trade(100.0)
    assert not ok
    e = s.record_trade("X", 100.0, 0.01, "balancer")
    assert e["blocked"] is True


def test_record_trade_writes_jsonl():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        s = SponsorLedger(state_path=None, trades_path=path)
        e = s.record_trade("MEME-WIN", 73.07, 0.0066, "balancer")
        assert e["sponsor_share_usd"] == 18.27
        assert e["ismail_share_usd"] == 54.80
        assert e["prefund_remaining_usd"] == 19.9934, e  # audit #9 : 20 - 0,0066 exact
        lines = open(path).read().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["symbol"] == "MEME-WIN"
        assert row["provider"] == "balancer"
        assert row["blocked"] is False


def test_load_from_config():
    # config.yaml réel du projet : section sponsorship: lue sans PyYAML.
    # v3.4 : la section sponsorship: est INACTIVE (Ismail autofinance,
    # part sponsor 0 %) — les valeurs ci-dessous reflètent la config
    # actuelle, pas l'ancien deal sponsor.
    s = load_from_config(_config_path())
    assert s.enabled is False, "v3.4 : sponsorship INACTIVE"
    assert s.prefund_usd == 20.0, s.prefund_usd
    assert s.sponsor_share_pct == 0.0, s.sponsor_share_pct
    assert s.funding_mode == "self_funded", s.funding_mode
    assert s.daily_cap_usd == 20.0, s.daily_cap_usd
    assert s.low_prefund_alert_usd == 5.0
    assert s.sponsor_wallet == ""


def test_executor_logs_split():
    # Intégration : un WOULD-EXECUTE logue le partage, un SKIP logue 0 $/0 $.
    import io
    from contextlib import redirect_stdout
    s = _fresh()
    s.trades_path = None
    costs = Costs()
    win = MemeCandidate("0xAAA", "MEME-WIN", "uniswap", "sushi",
                        Pool("Aero", 20_000, 20_000_000),
                        Pool("UniV2", 18_000, 15_000_000),
                        liquidity_usd=36_000, holders=150, age_hours=10)
    lose = MemeCandidate("0xBBB", "MEME-LOSE", "uniswap", "sushi",
                         Pool("Aero", 50_000, 50_000_000),
                         Pool("UniV2", 50_000, 49_000_000),
                         liquidity_usd=100_000, holders=200, age_hours=5)
    buf = io.StringIO()
    with redirect_stdout(buf):
        results = run([win, lose], costs, sponsor=s)
    out = buf.getvalue()
    assert results[0].action == "EXECUTE"
    assert results[1].action == "SKIP"
    # Le partage du gagnant (net ~73 $ Balancer) apparaît dans la sortie.
    assert "sponsor 18.27 $" in out, out
    assert "Ismail 54.80 $" in out, out
    # Le perdant SKIP : 0 $ / 0 $.
    assert out.count("sponsor 0.00 $ / Ismail 0.00 $") >= 1, out
    # Le trade gagnant a été enregistré dans le ledger du jour.
    assert s.sponsor_paid_today_usd == 18.27, s.sponsor_paid_today_usd


def test_executor_sponsor_cap_blocks_execute():
    # Plafond déjà atteint -> l'EXECUTE devient SKIP avec raison sponsor.
    import io
    from contextlib import redirect_stdout
    s = _fresh()
    for i in range(5):
        s.record_trade(f"T{i}", 16.0, 0.01, "balancer")
    costs = Costs()
    win = MemeCandidate("0xAAA", "MEME-WIN", "uniswap", "sushi",
                        Pool("Aero", 20_000, 20_000_000),
                        Pool("UniV2", 18_000, 15_000_000),
                        liquidity_usd=36_000, holders=150, age_hours=10)
    buf = io.StringIO()
    with redirect_stdout(buf):
        results = run([win], costs, sponsor=s)
    assert results[0].action == "SKIP", results[0]
    assert "sponsor" in "; ".join(results[0].reasons).lower()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__} : {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests sponsor PASSENT."
          if not failed else f"\n{failed} ÉCHEC(S) sur {len(tests)} tests.")
    sys.exit(1 if failed else 0)
