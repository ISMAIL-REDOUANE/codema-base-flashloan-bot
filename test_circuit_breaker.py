#!/usr/bin/env python3
"""Tests circuit_breaker.py (audit #15) — une seule méthode
d'enregistrement d'un reçu (record_receipt) avec compteurs de pertes
et pause mis à jour ensemble, sans double comptage.
Lancer : python3 test_circuit_breaker.py (stdlib only).
"""
import sys
import time

sys.path.insert(0, ".")

from circuit_breaker import CircuitBreaker


def _fresh(**kw):
    kw.setdefault("state_path", None)
    return CircuitBreaker(**kw)


def test_three_losing_real_trades_pause():
    """Contre-exemple de l'audit : 3 × record_real_trade(-0,1 $) doivent
    mettre en pause (l'ancien code comptait le revert SANS pause)."""
    b = _fresh()
    for _ in range(3):
        b.record_real_trade(-0.1, "0xAAA")
    assert b.consecutive_reverts == 3, b.consecutive_reverts
    assert abs(b.net_today_usd - (-0.3)) < 1e-9, b.net_today_usd
    assert b.trades_today == 3
    assert time.time() < b.paused_until, "pause non déclenchée"
    ok, _ = b.can_trade("0xAAA")
    assert ok is False
    print("OK test_three_losing_real_trades_pause — 3 trades à -0,10 $ "
          "-> pause 1 h (avant : aucune pause)")


def test_three_reverts_count_gas_and_trades():
    """Contre-exemple de l'audit : 3 × record_revert doivent compter le
    gas comme perte ET compter les trades (l'ancien code ne comptait
    ni l'un ni l'autre)."""
    b = _fresh()
    for i in range(3):
        b.record_revert(gas_usd=0.01, token_address="0xBBB",
                        tx_hash=f"0xhash{i}")
    assert b.consecutive_reverts == 3
    assert abs(b.net_today_usd - (-0.03)) < 1e-9, b.net_today_usd
    assert b.trades_today == 3, b.trades_today
    assert time.time() < b.paused_until
    ok, _ = b.can_trade()
    assert ok is False
    print("OK test_three_reverts_count_gas_and_trades — 3 reverts à "
          "0,01 $ -> net -0,03 $, 3 trades, pause")


def test_duplicate_tx_hash_counted_once():
    """Un même hash ne compte jamais deux fois (audit #15)."""
    b = _fresh()
    assert b.record_receipt("revert", gas_usd=0.05, tx_hash="0xabc") == "recorded"
    assert b.record_receipt("revert", gas_usd=0.05, tx_hash="0xABC") == "duplicate"
    assert b.record_receipt("success", net_usd=10.0, tx_hash="0xabc") == "duplicate"
    assert b.trades_today == 1, b.trades_today
    assert abs(b.net_today_usd - (-0.05)) < 1e-9, b.net_today_usd
    assert b.consecutive_reverts == 1
    print("OK test_duplicate_tx_hash_counted_once — 3 enregistrements, "
          "1 seul compté")


def test_success_resets_reverts_and_simulated_counts_nothing():
    b = _fresh()
    b.record_revert(gas_usd=0.01)
    b.record_revert(gas_usd=0.01)
    assert b.consecutive_reverts == 2
    b.record_receipt("success", net_usd=5.0, token_address="0xAAA")
    assert b.consecutive_reverts == 0
    assert abs(b.net_today_usd - (5.0 - 0.02)) < 1e-9, b.net_today_usd
    assert b.trades_today == 3
    assert b.record_receipt("simulated", net_usd=100.0) == "simulated"
    assert b.trades_today == 3  # la simulation ne compte pas
    assert abs(b.net_today_usd - (5.0 - 0.02)) < 1e-9
    print("OK test_success_resets_reverts_and_simulated_counts_nothing")


def test_record_receipt_rejects_unknown_status():
    b = _fresh()
    try:
        b.record_receipt("nope")
    except ValueError:
        print("OK test_record_receipt_rejects_unknown_status")
        return
    raise AssertionError("statut inconnu accepté")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ÉCHEC {name} : {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{failed} ÉCHEC(S) sur {len(tests)} tests.")
        sys.exit(1)
    print(f"TOUS LES TESTS CIRCUIT BREAKER PASSENT ({len(tests)} tests).")
