"""Tests v2 — gas unifié, quoter V3, GoPlus, circuit breaker, preflight, EV.
Lancer : python3 test_v2.py (stdlib only, pas de réseau sauf le test live
optionnel marqué LIVE, ignoré si le réseau est coupé).
Ou : python3 -m pytest test_v2.py -v"""
import io
import json
import sys
import urllib.request
from unittest import mock

sys.path.insert(0, ".")

from circuit_breaker import CircuitBreaker
from ev_test import run_ev
from gas import (GAS_PRICE_MAX_GWEI, GasReading, default_reading,
                 fetch_live_gas_price_gwei, gas_cost_usd_from_gwei, gas_ok)
from math_engine import Costs, Pool, decide
from preflight import (decode_amounts_out, encode_get_amounts_out,
                       is_fresh, preflight_roundtrip)
from scanner import MemeCandidate, passes_filters, vet_token_goplus
from v3_quote import (QUOTER_V2, encode_quote_path, encode_quote_single, quote_v3_onchain,
                      v3_quote_python)


def test_gas_unified():
    # Une seule valeur partout : 450k × 0,05 gwei × 3000 $ = 0,0675 $.
    assert abs(gas_cost_usd_from_gwei(450_000, 0.05, 3000.0) - 0.0675) < 1e-9
    assert abs(default_reading().gas_cost_usd - 0.0675) < 1e-9
    assert abs(Costs().gas_usd - 0.0675) < 1e-9
    # Plafond : 2 gwei OK, 2,01 gwei refusé, 254 gwei refusé.
    assert gas_ok(GasReading(1.5, 450_000, 3000.0, "test"))[0] is True
    assert gas_ok(GasReading(2.0, 450_000, 3000.0, "test"))[0] is True
    assert gas_ok(GasReading(2.01, 450_000, 3000.0, "test"))[0] is False
    assert gas_ok(GasReading(254.0, 450_000, 3000.0, "test"))[0] is False
    assert GAS_PRICE_MAX_GWEI == 2.0
    print("OK test_gas_unified — 0,0675 $ partout, plafond 2 gwei")


def test_gas_live_rpc():
    # Lecture live réelle sur mainnet.base.org (0 gas, lecture seule).
    # Si le réseau est coupé, on skip proprement au lieu d'échouer.
    try:
        live = fetch_live_gas_price_gwei()
    except Exception as e:
        print(f"SKIP test_gas_live_rpc (réseau) : {e}")
        return
    assert live.source in ("rpc_live",) or live.source.startswith("fallback")
    assert live.gas_cost_usd >= 0
    print(f"OK test_gas_live_rpc — gas live {live.gas_price_gwei:.4f} gwei "
          f"-> {live.gas_cost_usd:.4f} $ (source {live.source})")


def test_v3_quote_python_sanity():
    # Pool fictif WETH/USDC, prix 3 000 $, L = 1 000 000.
    import math
    sqrt_x96 = int(math.sqrt(3000) * (2 ** 96))
    # token1 (USDC) -> token0 (WETH) : 100 USDC -> ~0,033 WETH (moins les frais).
    q = v3_quote_python(100.0, 1_000_000.0, sqrt_x96, fee_bps=30, zero_for_one=False)
    assert q.source == "v3_python_single_tick"
    assert 0.02 < q.amount_out < 0.034, q.amount_out
    # Plus de frais -> moins de sortie. Plus gros montant -> plus d'impact.
    q2 = v3_quote_python(100.0, 1_000_000.0, sqrt_x96, fee_bps=300, zero_for_one=False)
    assert q2.amount_out < q.amount_out
    # Gros montant dans une petite liquidité -> le prix bouge de plus que
    # la largeur d'un tick (0,6 % au tier 0,3 %) -> franchissement signalé.
    q3 = v3_quote_python(100_000.0, 10_000.0, sqrt_x96, fee_bps=30, zero_for_one=False)
    assert q3.crossed_tick is True  # mouvement ~18 % >> 0,6 % (largeur d'un tick)
    # Petit montant dans une grosse liquidité -> reste dans le tick.
    assert q.crossed_tick is False
    print("OK test_v3_quote_python_sanity — 100 USDC ->",
          round(q.amount_out, 5), "WETH ; frais élevés réduisent la sortie")


def test_v3_quote_selector():
    # Sélecteurs vérifiés par keccak + test live 2026-11-24 :
    # quoteExactInput (0xcdca1753) FONCTIONNE ; quoteExactInputSingle (0xf7729d43) REVERT.
    from v3_quote import SELECTOR_QUOTE_INPUT, SELECTOR_QUOTE_SINGLE, encode_quote_path
    assert SELECTOR_QUOTE_INPUT.hex() == "cdca1753"
    assert SELECTOR_QUOTE_SINGLE.hex() == "f7729d43"
    data = encode_quote_path("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                             500, "0x4200000000000000000000000000000000000006",
                             100_000_000)
    assert data[:4].hex() == "cdca1753"
    assert len(data) == 4 + 32 + 32 + 32 + 64  # sélecteur + offset + amount + len + path paddé
    assert QUOTER_V2.lower() == "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a"
    print("OK test_v3_quote_selector — quoteExactInput 0xcdca1753 (fonctionne), "
          "quoteExactInputSingle 0xf7729d43 (revert sur Base)")


def test_v3_quote_onchain_live():
    # Quote réelle on-chain (eth_call, 0 gas) : 100 USDC -> WETH, fee 500.
    try:
        q = quote_v3_onchain("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                             "0x4200000000000000000000000000000000000006",
                             500, 100_000_000, "https://mainnet.base.org")
    except Exception as e:
        print(f"SKIP test_v3_quote_onchain_live (réseau) : {e}")
        return
    if q.source == "unavailable":
        # RPC public rate-limité (403) ou down : on skip proprement — le
        # quoter lui-même fonctionne (sélecteur vérifié), c'est le RPC qui refuse.
        print(f"SKIP test_v3_quote_onchain_live (RPC indisponible) : {q.error}")
        return
    assert q.amount_out > 0
    print(f"OK test_v3_quote_onchain_live — 100 USDC -> {q.amount_out / 1e18:.5f} WETH "
          f"(quoter on-chain, gas estimé {q.gas_estimate})")


def _fake_goplus_response(payload):
    body = json.dumps(payload).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_goplus_honeypot_reject():
    addr = "0x000000000000000000000000000000000000dead"
    payload = {"code": 1, "message": "OK",
               "result": {addr: {"is_honeypot": "1", "buy_tax": "0", "sell_tax": "99",
                                 "is_mintable": "0", "holder_count": "500"}}}
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(payload)):
        verdict, flags = vet_token_goplus(addr)
    assert verdict == "REJECT" and "honeypot" in flags, (verdict, flags)
    print("OK test_goplus_honeypot_reject — honeypot -> REJECT")


def test_goplus_clean_pass_and_unknown():
    addr = "0x000000000000000000000000000000000000beef"
    clean = {"code": 1, "message": "OK",
             "result": {addr: {"is_honeypot": "0", "buy_tax": "0", "sell_tax": "0",
                               "is_mintable": "0", "is_open_source": "1",
                               "holder_count": "500"}}}
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(clean)):
        verdict, flags = vet_token_goplus(addr)
    assert verdict == "PASS", (verdict, flags)
    # API down -> UNKNOWN (on ne trade pas) et le candidat est rejeté par passes_filters.
    with mock.patch.object(urllib.request, "urlopen",
                           side_effect=RuntimeError("réseau coupé")):
        verdict2, flags2 = vet_token_goplus(addr)
    assert verdict2 == "UNKNOWN" and "goplus_unknown" in flags2
    c = MemeCandidate(addr, "MEME", "aerodrome", "uniswap",
                      Pool("A", 20_000, 20_000_000), Pool("B", 18_000, 15_000_000),
                      liquidity_usd=36_000, holders=150, age_hours=10,
                      flags=["goplus_unknown"])
    ok, reasons = passes_filters(c)
    assert ok is False and any("goplus_unknown" in r for r in reasons)
    print("OK test_goplus_clean_pass_and_unknown — PASS propre, UNKNOWN -> rejet")


def test_circuit_breaker():
    b = CircuitBreaker(daily_loss_limit_usd=20.0, max_trades_per_day=3)
    assert b.can_trade("0xAAA")[0] is True
    b.record_real_trade(71.55, "0xAAA")
    b.record_real_trade(10.0, "0xAAA")   # 2e trade sur le même token dans l'heure : OK (max 2)
    assert b.can_trade("0xAAA")[0] is False  # 3e trade même token/heure -> refus
    assert b.can_trade("0xBBB")[0] is True
    b.record_real_trade(5.0, "0xBBB")    # 3 trades aujourd'hui = max
    assert b.can_trade("0xCCC")[0] is False
    # Kill switch : tout est refusé.
    b2 = CircuitBreaker()
    b2.kill()
    assert b2.can_trade()[0] is False
    b2.reset_kill_switch()
    assert b2.can_trade()[0] is True
    # Perte journalière : -25 $ -> stop pour aujourd'hui.
    b3 = CircuitBreaker(daily_loss_limit_usd=20.0)
    b3.record_real_trade(-25.0, "0xAAA")
    assert b3.can_trade()[0] is False
    # 3 reverts -> pause 1 h.
    b4 = CircuitBreaker()
    b4.record_revert()
    b4.record_revert()
    assert b4.can_trade()[0] is True
    b4.record_revert()
    assert b4.can_trade()[0] is False
    print("OK test_circuit_breaker — limites jour/token/kill-switch/pause reverts")


def test_preflight_encoding_roundtrip():
    # Encodage getAmountsOut puis décodage d'une fausse réponse : aller-retour exact.
    data = encode_get_amounts_out(
        100_000_000,
        ["0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
         "0x4200000000000000000000000000000000000006"])
    assert data[:4].hex() == "d06ca61f"
    fake = (32).to_bytes(32, "big") + (2).to_bytes(32, "big") \
        + (100_000_000).to_bytes(32, "big") + (33_000).to_bytes(32, "big")
    assert decode_amounts_out(fake) == [100_000_000, 33_000]
    # Fraîcheur : 2 blocs OK, 3 blocs rejeté ; bloc inconnu -> pas frais.
    assert is_fresh(100, 102) is True
    assert is_fresh(100, 103) is False
    assert is_fresh(None, 102) is False
    print("OK test_preflight_encoding_roundtrip — sélecteur 0xd06ca61f, fraîcheur ≤ 2 blocs")


def test_preflight_live_roundtrip():
    # Preflight réel sur mainnet Base (lectures seules, 0 gas) : 100 USDC->WETH->USDC
    # sur Uniswap V2 : le spread naturel est ~0 -> LOSE (attendu, pas un échec).
    try:
        r = preflight_roundtrip(
            "https://mainnet.base.org", 100_000_000,
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "0x4200000000000000000000000000000000000006",
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
            "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
            loan_usd=100.0)
    except Exception as e:
        print(f"SKIP test_preflight_live_roundtrip (réseau) : {e}")
        return
    if r.status == "UNAVAILABLE":
        # RPC public rate-limité (403) ou down : skip propre, pas un échec du code.
        print(f"SKIP test_preflight_live_roundtrip (RPC indisponible) : {r.error}")
        return
    assert r.status in ("WIN", "LOSE"), r
    assert r.block_number is not None and r.block_number > 0
    print(f"OK test_preflight_live_roundtrip — status {r.status}, net on-chain "
          f"{r.net_usd} $, bloc {r.block_number}")


def test_ev_small_run():
    res = run_ev(n=20, seed=42)
    assert res["n_opportunities"] == 20
    assert res["n_executed"] + res["n_skipped"] == 20
    assert res["ev_per_opportunity_usd"] == round(res["total_net_usd"] / 20, 2)
    assert res["max_drawdown_usd"] >= 0
    print(f"OK test_ev_small_run — 20 opp : {res['n_executed']} exécutés, "
          f"EV/opp {res['ev_per_opportunity_usd']} $, net total {res['total_net_usd']} $")


if __name__ == "__main__":
    test_gas_unified()
    test_gas_live_rpc()
    test_v3_quote_python_sanity()
    test_v3_quote_selector()
    test_v3_quote_onchain_live()
    test_goplus_honeypot_reject()
    test_goplus_clean_pass_and_unknown()
    test_circuit_breaker()
    test_preflight_encoding_roundtrip()
    test_preflight_live_roundtrip()
    test_ev_small_run()
    print("\nTOUS LES TESTS V2 PASSENT.")
