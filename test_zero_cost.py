"""Tests v3.2 — Mode $0 TOTAL (zero_cost.py + intégration executor/sponsor).
Ismail paie 0 $, pas même 1 $.
Lancer : python3 test_zero_cost.py (stdlib only).
Ou : python3 -m pytest test_zero_cost.py -v"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from executor import run
from math_engine import Costs, Pool
from scanner import MemeCandidate
from sponsor import SponsorLedger
from zero_cost import ZeroCostGuard, load_from_config, trade_from_result


def _fresh_guard(**kw):
    """Garde neuve, sans fichiers (aucun état persisté)."""
    kw.setdefault("trades_path", None)
    return ZeroCostGuard(**kw)


def _morpho_trade(**over):
    t = {"provider": "morpho", "flash_fee_rate": 0.0, "loan_usd": 790.16,
         "expected_net_usd": 73.07, "gas_usd": 0.0066, "gas_payer": "sponsor",
         "prefund_remaining_usd": 20.0, "ismail_cost_usd": 0.0}
    t.update(over)
    return t


def _win_candidate():
    return MemeCandidate("0xAAA", "MEME-WIN", "uniswap", "sushi",
                         Pool("Aero", 20_000, 20_000_000),
                         Pool("UniV2", 18_000, 15_000_000),
                         liquidity_usd=36_000, holders=150, age_hours=10)


def _lose_candidate():
    return MemeCandidate("0xBBB", "MEME-LOSE", "uniswap", "sushi",
                         Pool("Aero", 50_000, 50_000_000),
                         Pool("UniV2", 50_000, 49_000_000),
                         liquidity_usd=100_000, holders=200, age_hours=5)


def _config_path() -> str:
    """Config pour les tests (audit #13) : config.yaml si présent, sinon
    config.yaml.example — un checkout propre sans config.yaml passe."""
    from pathlib import Path as _P
    return "config.yaml" if _P("config.yaml").exists() else "config.yaml.example"


def test_morpho_allowed():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade())
    assert ok, why
    assert "0,00" in why or "0.00" in why or "0 $" in why
    assert g.ismail_paid_usd == 0.0


def test_aave_blocked_zero_cost():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade(
        provider="aave", flash_fee_rate=0.0005, expected_net_usd=72.68,
        flash_fee_usd=0.40))
    assert not ok, "Aave doit être BLOQUÉ en mode $0"
    assert "ZERO_COST" in why
    assert "aave" in why.lower()
    assert g.ismail_paid_usd == 0.0


def test_gas_exceeds_prefund_blocked():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade(
        gas_usd=25.0, prefund_remaining_usd=20.0))
    assert not ok, "gas > prefund sponsor doit être bloqué (Ismail ne paie pas la différence)"
    assert "ZERO_COST" in why
    assert g.ismail_paid_usd == 0.0


def test_gas_payer_ismail_blocked():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade(gas_payer="ismail"))
    assert not ok
    assert "ZERO_COST" in why


def test_cdp_credits_pending_blocked_then_allowed():
    g = _fresh_guard(cdp_credits_approved=False)
    ok, why = g.check_zero_cost(_morpho_trade(gas_payer="cdp-credits"))
    assert not ok, "crédits CDP non approuvés -> bloqué"
    assert "CDP" in why
    g2 = _fresh_guard(cdp_credits_approved=True)
    ok, why = g2.check_zero_cost(_morpho_trade(gas_payer="cdp-credits"))
    assert ok, why


def test_flash_fee_not_covered_blocked():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade(
        flash_fee_usd=5.0, expected_net_usd=3.0))
    assert not ok, "prime non couverte par le profit -> bloqué"
    assert "ZERO_COST" in why


def test_ismail_cost_blocked():
    g = _fresh_guard()
    ok, why = g.check_zero_cost(_morpho_trade(ismail_cost_usd=1.0))
    assert not ok, "1 $ à la charge d'Ismail -> bloqué (max 0,00 $)"
    assert "1.00" in why


def test_kill_switch_on_any_ismail_charge():
    g = _fresh_guard()
    assert g.charge_ismail(0.0)  # 0 $ : rien ne se passe
    assert not g.tripped
    assert g.charge_ismail(0.01, "test") is False  # même 0,01 $ déclenche
    assert g.tripped
    assert g.ismail_paid_usd == 0.01
    ok, why = g.check_zero_cost(_morpho_trade())
    assert not ok, "après déclenchement, TOUS les trades sont bloqués"
    assert "kill switch" in why.lower()


def test_disabled_guard_inactive():
    g = _fresh_guard(enabled=False)
    ok, why = g.check_zero_cost(_morpho_trade(provider="aave"))
    assert ok, "garde désactivée = inactive (documenté, à ne jamais faire sans raison)"


def test_load_from_config():
    g = load_from_config(_config_path())
    assert g.enabled is True
    assert g.ismail_pays_usd_max == 0.0
    assert g.allowed_flash_providers == ("morpho",)
    assert g.rpc == "alchemy-free"
    assert g.gas_payer == "sponsor"
    assert g.cdp_credits_approved is False
    assert g.infra_cost_usd == 0.0


def test_append_ledger_writes_ismail_paid_zero():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        g = _fresh_guard(trades_path=path)
        entry = g.append_ledger("MEME-WIN", 73.07, 0.0066, "morpho")
        assert entry["ismail_paid_usd"] == 0.0
        assert entry["zero_cost"] is True
        lines = open(path).read().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["ismail_paid_usd"] == 0.0


def test_executor_aave_forced_blocked_by_zero_cost():
    # Vault presque vide -> select_provider retombe sur Aave -> le garde $0 bloque.
    g = _fresh_guard()
    results = run([_win_candidate()], Costs(), sponsor=None, zero_cost=g,
                  vault_balances={"USDC": 100.0})
    assert len(results) == 1
    r = results[0]
    assert r.provider == "aave", r.provider
    assert r.action == "SKIP", (r.action, r.reasons)
    assert any("ZERO_COST" in x for x in r.reasons), r.reasons
    assert g.ismail_paid_usd == 0.0


def test_executor_morpho_allowed_and_logged():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        sponsor = SponsorLedger(state_path=None, trades_path=path)
        g = _fresh_guard(trades_path=path)
        results = run([_win_candidate()], Costs(), sponsor=sponsor,
                      zero_cost=g)
        assert len(results) == 1
        r = results[0]
        assert r.provider == "morpho", r.provider
        assert r.action == "EXECUTE", (r.action, r.reasons)
        assert g.ismail_paid_usd == 0.0
        lines = open(path).read().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["ismail_paid_usd"] == 0.0
        assert entry["zero_cost"] is True
        assert entry["sponsor_share_usd"] == 18.27
        assert entry["ismail_share_usd"] == 54.80


def test_ismail_paid_zero_across_20_trades():
    # 20 trades (10 gagnants / 10 perdants) : Ismail ne paie jamais 1 centime,
    # et chaque ligne du ledger le prouve.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        sponsor = SponsorLedger(state_path=None, trades_path=path,
                                daily_cap_usd=10_000.0)  # plafond levé pour le test
        g = _fresh_guard(trades_path=path)
        opps = []
        for i in range(10):
            opps.append(_win_candidate())
            opps.append(_lose_candidate())
        results = run(opps, Costs(), sponsor=sponsor, zero_cost=g)
        assert len(results) == 20
        assert g.ismail_paid_usd == 0.0
        executed = [r for r in results if r.action == "EXECUTE"]
        assert len(executed) == 10, f"attendu 10 EXECUTE, vu {len(executed)}"
        assert all(r.provider == "morpho" for r in executed)
        lines = open(path).read().strip().split("\n")
        assert len(lines) == 10, f"attendu 10 lignes ledger, vu {len(lines)}"
        for line in lines:
            entry = json.loads(line)
            assert entry["ismail_paid_usd"] == 0.0, entry
            assert entry["zero_cost"] is True


def test_trade_from_result():
    from executor import simulate
    g = _fresh_guard()
    r = simulate(_win_candidate(), Costs())
    assert r.provider == "morpho"
    t = trade_from_result(r, gas_payer="sponsor", prefund_remaining_usd=20.0)
    assert t["flash_fee_usd"] == 0.0
    ok, why = g.check_zero_cost(t)
    assert ok, why


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"OK {name}")
        except Exception as e:
            failed += 1
            print(f"ÉCHEC {name} : {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests $0 PASSENT."
          if failed == 0 else f"\n{failed} ÉCHEC(S) sur {len(tests)} tests.")
    raise SystemExit(1 if failed else 0)
