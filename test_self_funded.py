"""Tests v3.4 — Mode GAS AUTOFINANCÉ (self_funded.py + interrupteur de
mode zero_cost.py + intégration executor/sponsor/dry_run).
Ismail finance le gas lui-même (~20 $ float) et garde 100 % du profit.
Le flash loan reste Morpho 0 % seulement ; Aave 0,05 % toujours BLOQUÉ.
Lancer : python3 test_self_funded.py (stdlib only).
Ou : python3 -m pytest test_self_funded.py -v"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from executor import run
from math_engine import Costs, Pool
from scanner import MemeCandidate
from self_funded import FloatLedger, load_from_config as load_funding
from sponsor import SponsorLedger
from zero_cost import ZeroCostGuard, load_from_config as load_zero_cost


def _fresh_float(**kw):
    """Float neuf, sans fichiers (aucun état persisté)."""
    kw.setdefault("state_path", None)
    kw.setdefault("trades_path", None)
    return FloatLedger(**kw)


def _fresh_guard_self_funded(**kw):
    kw.setdefault("trades_path", None)
    return ZeroCostGuard(mode="self_funded", **kw)


def _self_funded_trade(**over):
    t = {"provider": "morpho", "flash_fee_rate": 0.0, "loan_usd": 790.16,
         "expected_net_usd": 73.07, "gas_usd": 0.0066, "gas_payer": "ismail",
         "float_remaining_usd": 20.0, "min_profit_usd": 3.0,
         "ismail_cost_usd": 0.0}
    t.update(over)
    return t


def _win_candidate():
    return MemeCandidate("0xAAA", "MEME-WIN", "aerodrome", "uniswap",
                         Pool("Aero", 20_000, 20_000_000),
                         Pool("UniV2", 18_000, 15_000_000),
                         liquidity_usd=36_000, holders=150, age_hours=10)


def _lose_candidate():
    return MemeCandidate("0xBBB", "MEME-LOSE", "aerodrome", "uniswap",
                         Pool("Aero", 50_000, 50_000_000),
                         Pool("UniV2", 50_000, 49_000_000),
                         liquidity_usd=100_000, holders=200, age_hours=5)


def test_load_funding_from_config():
    f = load_funding("config.yaml")
    assert f.payer == "ismail", f.payer
    assert f.float_usd == 20.0, f.float_usd
    assert f.sponsor_share_pct == 0.0, f.sponsor_share_pct
    assert f.gas_payer == "ismail", f.gas_payer
    assert f.min_profit_usd == 3.0
    assert f.float_remaining_usd == 20.0
    assert f.ismail_paid_usd == 0.0
    assert f.profits_usd == 0.0


def test_guard_mode_switch_from_config():
    # config.yaml `funding.payer == "ismail"` -> le garde démarre en
    # mode self_funded. La section `zero_cost:` reste inchangée
    # (gas_payer "sponsor" = mode $0 historique, conservé).
    g = load_zero_cost("config.yaml")
    assert g.mode == "self_funded", g.mode
    assert g.gas_payer == "sponsor", g.gas_payer
    assert g.allowed_flash_providers == ("morpho",)


def test_split_100_0():
    f = _fresh_float()
    assert f.split_profit(100.0) == (0.0, 100.0)
    assert f.split_profit(73.07) == (0.0, 73.07)
    assert f.split_profit(0.0) == (0.0, 0.0)
    assert f.split_profit(-5.0) == (0.0, 0.0)
    # Même règle côté sponsor avec part 0 % (sponsor.py v3.4).
    s = SponsorLedger(sponsor_share_pct=0.0, state_path=None, trades_path=None)
    assert s.split_profit(100.0) == (0.0, 100.0)
    # Ledger sponsor DÉSACTIVÉ : Ismail garde 100 % (jamais 0/0 par erreur).
    s2 = SponsorLedger(enabled=False, state_path=None, trades_path=None)
    assert s2.split_profit(100.0) == (0.0, 100.0)


def test_float_accounting_20_trades():
    # 10 gagnants (net 73,07 $, gas 0,07 $) + 5 reverts (net 0, gas 0,07 $)
    # + 5 SKIP (jamais enregistrés : 0 $ / 0 $).
    f = _fresh_float()
    for i in range(10):
        e = f.record_trade(f"WIN-{i}", 73.07, 0.07, "morpho")
        assert not e["blocked"], e
        assert e["funding_mode"] == "self_funded"
        assert e["sponsor_share_usd"] == 0.0
        assert e["ismail_share_usd"] == 73.07
    assert f.ismail_paid_usd == 0.70, f.ismail_paid_usd
    assert f.profits_usd == 730.70, f.profits_usd
    assert f.float_remaining_usd == 19.30, f.float_remaining_usd
    for i in range(5):
        e = f.record_trade(f"REVERT-{i}", 0.0, 0.07, "morpho")
        assert not e["blocked"], e
        assert e["sponsor_share_usd"] == 0.0
        assert e["ismail_share_usd"] == 0.0
    assert f.ismail_paid_usd == 1.05, f.ismail_paid_usd
    assert f.profits_usd == 730.70, "un revert ne crée pas de profit"
    assert f.float_remaining_usd == 18.95, f.float_remaining_usd
    assert f.trades_executed == 15, f.trades_executed
    assert f.float_status_line() == (
        "FINANCEMENT : Ismail — float 20.00 $ / dépensé 1.05 $ / "
        "restant 18.95 $ / profit 730.70 $")


def test_block_when_float_exhausted():
    f = _fresh_float(float_usd=0.10)
    # Pire cas 0,14 $ (gas 0,07 $ + budget revert 0,07 $) > float 0,10 $.
    ok, why = f.can_afford(0.07)
    assert not ok, "pire cas > float -> bloqué"
    assert "SELF_FUNDED" in why
    e = f.record_trade("MEME-WIN", 73.07, 0.07, "morpho")
    assert e["blocked"] is True
    assert f.ismail_paid_usd == 0.0, "rien ne doit être déduit après blocage"
    assert f.float_remaining_usd == 0.10
    # Float 0,20 $ : 1er trade OK (reste 0,13 $), 2e bloqué (0,14 $ > 0,13 $).
    f2 = _fresh_float(float_usd=0.20)
    e1 = f2.record_trade("T1", 73.07, 0.07, "morpho")
    assert not e1["blocked"], e1
    assert f2.float_remaining_usd == 0.13
    ok, why = f2.can_afford(0.07)
    assert not ok
    e2 = f2.record_trade("T2", 73.07, 0.07, "morpho")
    assert e2["blocked"] is True
    assert f2.trades_executed == 1


def test_kill_switch_at_zero():
    # Float à 0 dès le départ : kill switch immédiat, tout est bloqué.
    f = _fresh_float(float_usd=0.0)
    ok, why = f.can_afford(0.07)
    assert not ok
    assert f.tripped, "le kill switch doit se déclencher à 0 $"
    assert "kill switch" in why.lower() or "épuisé" in why.lower()
    e = f.record_trade("X", 73.07, 0.07, "morpho")
    assert e["blocked"] is True
    # Charge directe jusqu'à 0 : le kill switch se déclenche aussi.
    f2 = _fresh_float(float_usd=0.07)
    assert f2.charge_gas(0.07) is False, "float tombé à 0 -> kill switch"
    assert f2.tripped
    assert f2.float_remaining_usd == 0.0
    ok, _ = f2.can_afford(0.07)
    assert not ok
    # Recharge : le kill switch se réarme, le trading peut reprendre.
    assert f2.top_up(20.0) == 20.0
    assert not f2.tripped
    ok, _ = f2.can_afford(0.07)
    assert ok


def test_morpho_only_enforcement_self_funded():
    # Le garde self-funded bloque Aave comme le garde $0 (Morpho 0 % seul).
    g = _fresh_guard_self_funded()
    ok, why = g.check_zero_cost(_self_funded_trade(
        provider="aave", flash_fee_rate=0.0005, expected_net_usd=72.68,
        flash_fee_usd=0.40))
    assert not ok, "Aave doit être BLOQUÉ aussi en mode autofinancé"
    assert "aave" in why.lower()
    assert "SELF_FUNDED" in why or "ZERO_COST" in why
    # Morpho est autorisé (gas Ismail depuis le float).
    ok, why = g.check_zero_cost(_self_funded_trade())
    assert ok, why
    assert "100 %" in why


def test_executor_aave_forced_blocked_self_funded():
    # Vault presque vide -> select_provider retombe sur Aave -> le garde
    # self-funded bloque (comme le garde $0).
    g = _fresh_guard_self_funded()
    f = _fresh_float()
    results = run([_win_candidate()], Costs(), funding=f, zero_cost=g,
                  vault_balances={"USDC": 100.0})
    assert len(results) == 1
    r = results[0]
    assert r.provider == "aave", r.provider
    assert r.action == "SKIP", (r.action, r.reasons)
    assert any("SELF_FUNDED" in x or "ZERO_COST" in x for x in r.reasons), r.reasons
    assert f.ismail_paid_usd == 0.0, "rien dépensé sur un trade bloqué"


def test_min_profit_after_gas():
    # Le net simulé doit rester >= 3 $ APRÈS gas + prime (règle d'Ismail).
    g = _fresh_guard_self_funded()
    ok, why = g.check_zero_cost(_self_funded_trade(expected_net_usd=2.50))
    assert not ok, "net 2,50 $ < min 3 $ -> bloqué"
    assert "3" in why
    ok, why = g.check_zero_cost(_self_funded_trade(expected_net_usd=3.00))
    assert not ok, "net == min 3,00 $ -> bloqué (règle stricte, comme decide())"
    ok, why = g.check_zero_cost(_self_funded_trade(expected_net_usd=3.01))
    assert ok, why
    ok, why = g.check_zero_cost(_self_funded_trade(expected_net_usd=73.07))
    assert ok, why


def test_gas_payer_ismail_allowed_with_float():
    g = _fresh_guard_self_funded()
    # Gas Ismail + float suffisant -> autorisé (c'est le mode normal v3.4).
    ok, why = g.check_zero_cost(_self_funded_trade())
    assert ok, why
    # Float épuisé -> bloqué (pire cas > float restant).
    ok, why = g.check_zero_cost(_self_funded_trade(float_remaining_usd=0.0))
    assert not ok
    assert "SELF_FUNDED" in why
    # Gas payé par un sponsor en mode autofinancé -> incohérent, bloqué.
    ok, why = g.check_zero_cost(_self_funded_trade(gas_payer="sponsor"))
    assert not ok
    assert "SELF_FUNDED" in why
    # Coût hors-gas à la charge d'Ismail -> bloqué (le float ne couvre
    # QUE le gas, pas d'autres frais surprises).
    ok, why = g.check_zero_cost(_self_funded_trade(ismail_cost_usd=1.0))
    assert not ok


def test_executor_self_funded_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        funding = _fresh_float(trades_path=path)
        g = _fresh_guard_self_funded(trades_path=path)
        results = run([_win_candidate(), _lose_candidate()], Costs(),
                      funding=funding, zero_cost=g)
        assert len(results) == 2
        win, lose = results
        assert win.action == "EXECUTE", (win.action, win.reasons)
        assert win.provider == "morpho", win.provider
        assert lose.action == "SKIP", lose.action
        # Comptabilité : gas SIMULÉ déduit (0,0675 $ -> 0,07 $), profit 100 %.
        assert funding.ismail_paid_usd == 0.07, funding.ismail_paid_usd
        assert funding.profits_usd == 73.07, funding.profits_usd
        assert funding.float_remaining_usd == 19.93, funding.float_remaining_usd
        lines = open(path).read().strip().split("\n")
        assert len(lines) == 1, f"1 seul EXECUTE logué, vu {len(lines)}"
        entry = json.loads(lines[0])
        assert entry["funding_mode"] == "self_funded"
        assert entry["sponsor_share_usd"] == 0.0
        assert entry["ismail_share_usd"] == 73.07
        assert entry["ismail_paid_usd"] == 0.07
        assert entry["float_remaining_usd"] == 19.93
        assert entry["simulated"] is True


def test_executor_float_exhausted_blocks():
    # Float 0,10 $ : pire cas 0,14 $ > float -> le WIN devient SKIP.
    funding = _fresh_float(float_usd=0.10)
    g = _fresh_guard_self_funded()
    results = run([_win_candidate()], Costs(), funding=funding, zero_cost=g)
    assert len(results) == 1
    r = results[0]
    assert r.action == "SKIP", (r.action, r.reasons)
    assert any("SELF_FUNDED" in x for x in r.reasons), r.reasons
    assert funding.ismail_paid_usd == 0.0


def test_executor_self_funded_without_guard():
    # Sans garde $0, le float reste le garde-fou (can_afford) : float
    # suffisant -> EXECUTE ; float épuisé -> SKIP.
    f1 = _fresh_float()
    results = run([_win_candidate()], Costs(), funding=f1)
    assert results[0].action == "EXECUTE"
    assert f1.ismail_paid_usd == 0.07
    f2 = _fresh_float(float_usd=0.10)
    results = run([_win_candidate()], Costs(), funding=f2)
    assert results[0].action == "SKIP"
    assert any("SELF_FUNDED" in x for x in results[0].reasons)
    assert f2.ismail_paid_usd == 0.0


def test_sponsor_ledger_self_funded_entries():
    # SponsorLedger part 0 % en mode self_funded : entrées taguées,
    # 100 % à Ismail, gas déduit du prefund (float).
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trades.jsonl")
        s = SponsorLedger(sponsor_share_pct=0.0, funding_mode="self_funded",
                          state_path=None, trades_path=path)
        e = s.record_trade("MEME-WIN", 100.0, 0.07, "morpho")
        assert not e["blocked"], e
        assert e["funding_mode"] == "self_funded"
        assert e["sponsor_share_usd"] == 0.0
        assert e["ismail_share_usd"] == 100.0
        lines = open(path).read().strip().splitlines()
        assert json.loads(lines[0])["funding_mode"] == "self_funded"


def test_float_status_line():
    f = _fresh_float()
    assert f.float_status_line() == (
        "FINANCEMENT : Ismail — float 20.00 $ / dépensé 0.00 $ / "
        "restant 20.00 $ / profit 0.00 $")
    f.record_trade("MEME-WIN", 73.07, 0.07, "morpho")
    assert f.float_status_line() == (
        "FINANCEMENT : Ismail — float 20.00 $ / dépensé 0.07 $ / "
        "restant 19.93 $ / profit 73.07 $")


def test_worst_case_cost():
    f = _fresh_float()
    # Par défaut : pire cas = gas + budget revert (= gas) = 2 × gas.
    assert f.worst_case_cost(0.07) == 0.14
    # 0,0066 $ arrondi au centime = 0,01 $ de gas + 0,01 $ de revert = 0,02 $.
    assert f.worst_case_cost(0.0066) == 0.02
    assert f.worst_case_cost(0.07, revert_budget_usd=0.20) == 0.27


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
    print(f"\n{len(tests) - failed}/{len(tests)} tests autofinancé PASSENT."
          if failed == 0 else f"\n{failed} ÉCHEC(S) sur {len(tests)} tests.")
    raise SystemExit(1 if failed else 0)
