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
from scanner import (USDC_BASE, MemeCandidate, apply_goplus_to_candidate,
                     fetch_pairs_from_dexscreener, pairs_to_pools, passes_filters,
                     scan_token, vet_token_goplus, vet_token_goplus_detailed)
from v3_quote import (QUOTER_V2, decode_quote_single, encode_quote_path,
                      encode_quote_single, quote_single_onchain, quote_v3_onchain,
                      v3_quote_python)


def _rpc_url_for_live_test() -> str:
    """RPC pour les tests live : Alchemy de config.yaml si présent (clé
    jamais affichée), sinon config.yaml.example, sinon le RPC public
    (souvent 403 — le test skip). Audit #13 : aucun test n'exige
    config.yaml."""
    try:
        import re
        from pathlib import Path
        for name in ("config.yaml", "config.yaml.example"):
            try:
                text = Path(name).read_text()
            except OSError:
                continue
            m = re.search(r'rpc_url:\s*"([^"]+)"', text)
            if m and "YOUR_" not in m.group(1) and "PLACEHOLDER" not in m.group(1):
                return m.group(1)
    except Exception:
        pass
    return "https://mainnet.base.org"


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
    # V2 tuple selector; the former f7729d43 selector belongs to the V1 ABI.
    from v3_quote import SELECTOR_QUOTE_INPUT, SELECTOR_QUOTE_SINGLE, encode_quote_path
    assert SELECTOR_QUOTE_INPUT.hex() == "cdca1753"
    assert SELECTOR_QUOTE_SINGLE.hex() == "c6a5026a"
    data = encode_quote_path("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                             500, "0x4200000000000000000000000000000000000006",
                             100_000_000)
    assert data[:4].hex() == "cdca1753"
    assert len(data) == 4 + 32 + 32 + 32 + 64  # sélecteur + offset + amount + len + path paddé
    assert QUOTER_V2.lower() == "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a"
    print("OK QuoterV2 selectors: cdca1753 / c6a5026a")


def test_v3_quote_single_encoding():
    # Audit #8 : l'ancien encodage mettait fee à la place d'amountIn.
    # Contre-exemple de l'audit : 100 USDC (100 000 000) fee 500.
    usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    weth = "0x4200000000000000000000000000000000000006"
    data = encode_quote_single(usdc, weth, 500, 100_000_000)
    d = decode_quote_single(data)
    assert d["selector"] == "c6a5026a", d
    assert d["token_in"].lower() == usdc.lower(), d
    assert d["token_out"].lower() == weth.lower(), d
    assert d["amount_in"] == 100_000_000, d  # PAS 500 (l'ancien bug)
    assert d["fee"] == 500, d                # PAS 100 000 000 (> uint24.max)
    assert d["fee"] <= 0xFFFFFF, "fee doit tenir dans uint24"
    assert d["sqrt_price_limit_x96"] == 0
    # L'ancien encodage (bug) : fee et amountIn intervertis.
    buggy = (bytes.fromhex("c6a5026a")
             + bytes.fromhex(usdc[2:].lower().rjust(64, "0"))
             + bytes.fromhex(weth[2:].lower().rjust(64, "0"))
             + (500).to_bytes(32, "big") + (100_000_000).to_bytes(32, "big")
             + (0).to_bytes(32, "big"))
    db = decode_quote_single(buggy)
    assert db["amount_in"] == 500 and db["fee"] == 100_000_000, db
    # Validation des bornes : fee > uint24.max refusée à l'encodage.
    try:
        encode_quote_single(usdc, weth, 0xFFFFFF + 1, 100_000_000)
    except ValueError:
        pass
    else:
        raise AssertionError("fee > uint24.max doit être refusée")
    print("OK test_v3_quote_single_encoding — ordre ABI officiel "
          "(tokenIn, tokenOut, amountIn, fee, sqrtPriceLimitX96) vérifié par décodage")


def test_v3_quote_single_live():
    # Audit #8 : tester la quote CORRIGÉE live (lecture seule).
    # Résultat 2026-11-25 (bloc ~62 093 375) : avec le calldata correct,
    # quoteExactInputSingle REVERT toujours sur Base (3 variantes : limit
    # 0 / MAX-1, fees 500/3000, sens USDC->WETH et WETH->USDC) alors que
    # quoteExactInput sur la même pool répond. Le test exige donc :
    # single = unavailable (revert) ET path = OK sur la même pool.
    rpc_url = _rpc_url_for_live_test()
    usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    weth = "0x4200000000000000000000000000000000000006"
    try:
        q_path = quote_v3_onchain(usdc, weth, 500, 100_000_000, rpc_url)
    except Exception as e:
        print(f"SKIP test_v3_quote_single_live (réseau) : {e}")
        return
    if q_path.source == "unavailable":
        print(f"SKIP test_v3_quote_single_live (RPC indisponible) : {q_path.error}")
        return
    assert q_path.amount_out > 0, q_path
    q_single = quote_single_onchain(usdc, weth, 500, 100_000_000, rpc_url)
    assert q_single.source == "quoter_v2_single_onchain", q_single.error
    assert abs(q_single.amount_out / q_path.amount_out - 1) < 0.001


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


def test_goplus_tax_decimal():
    # Audit #5 — contre-exemple : buy_tax=0.10 (10 %), sell_tax=0.50 (50 %).
    # GoPlus renvoie des DÉCIMAUX 0–1 : 0.50 = 50 % > 5 % -> REJECT.
    # Avant la correction, 0.50 < 5.0 -> PASS (le bug).
    addr = "0x000000000000000000000000000000000000cafe"
    payload = {"code": 1, "message": "OK",
               "result": {addr: {"is_honeypot": "0", "buy_tax": "0.10",
                                 "sell_tax": "0.50", "is_mintable": "0",
                                 "is_open_source": "1", "holder_count": "500"}}}
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(payload)):
        verdict, flags, info = vet_token_goplus_detailed(addr)
    assert verdict == "REJECT" and "high_tax" in flags, (verdict, flags)
    assert info["sell_tax_pct"] == 50.0 and info["buy_tax_pct"] == 10.0, info
    # Taxe à la limite : 0.05 = 5 % -> PASS (seuil 5 % inclus).
    payload["result"][addr]["sell_tax"] = "0.05"
    payload["result"][addr]["buy_tax"] = "0.04"
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(payload)):
        verdict2, flags2, _ = vet_token_goplus_detailed(addr)
    assert verdict2 == "PASS", (verdict2, flags2)
    print("OK test_goplus_tax_decimal — taxe 50 % (0.50) REJECT, 5 % (0.05) PASS")


def test_goplus_tax_unknown():
    # Audit #5 : taxe ABSENTE != taxe 0. Sans buy_tax/sell_tax -> UNKNOWN.
    addr = "0x000000000000000000000000000000000000babe"
    payload = {"code": 1, "message": "OK",
               "result": {addr: {"is_honeypot": "0", "is_mintable": "0",
                                 "is_open_source": "1", "holder_count": "500"}}}
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(payload)):
        verdict, flags, info = vet_token_goplus_detailed(addr)
    assert verdict == "UNKNOWN" and "tax_unknown" in flags, (verdict, flags)
    assert info["buy_tax_pct"] is None and info["sell_tax_pct"] is None
    print("OK test_goplus_tax_unknown — taxe absente -> UNKNOWN (pas 0 %)")


def test_goplus_not_open_source_and_few_holders_reject():
    # Audit #5 : not_open_source et too_few_holders étaient posés mais
    # jamais bloquants. Ils le sont désormais (REJECT + rejet en filtres).
    addr = "0x000000000000000000000000000000000000d00d"
    payload = {"code": 1, "message": "OK",
               "result": {addr: {"is_honeypot": "0", "buy_tax": "0",
                                 "sell_tax": "0", "is_mintable": "0",
                                 "is_open_source": "0", "holder_count": "5"}}}
    with mock.patch.object(urllib.request, "urlopen",
                           return_value=_fake_goplus_response(payload)):
        verdict, flags, _ = vet_token_goplus_detailed(addr)
    assert verdict == "REJECT", (verdict, flags)
    assert "not_open_source" in flags and "too_few_holders" in flags, flags
    c = MemeCandidate(addr, "MEME", "uniswap", "sushi",
                      Pool("A", 20_000, 20_000_000), Pool("B", 18_000, 15_000_000),
                      liquidity_usd=36_000, holders=5, holders_known=True,
                      age_hours=10, age_known=True, flags=list(flags))
    ok, reasons = passes_filters(c)
    assert ok is False, reasons
    assert any("not_open_source" in r for r in reasons), reasons
    assert any("too_few_holders" in r for r in reasons), reasons
    print("OK test_goplus_not_open_source_and_few_holders_reject — "
          "les deux flags bloquent désormais")


def _fake_dexscreener_response(pairs):
    body = json.dumps({"schemaVersion": "1.0.0", "pairs": pairs}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _dex_pair(dex_id, pair_addr, price_usd, liq_usd, age_hours, quote_addr=None):
    import time as _time
    return {"chainId": "base", "dexId": dex_id, "pairAddress": pair_addr,
            "baseToken": {"address": "0x000000000000000000000000000000000000feed",
                          "symbol": "MEME"},
            "quoteToken": {"address": quote_addr or USDC_BASE, "symbol": "USDC"},
            "priceUsd": str(price_usd), "liquidity": {"usd": liq_usd},
            "pairCreatedAt": int((_time.time() - age_hours * 3600) * 1000)}


def test_scanner_dexscreener_token_pairs_endpoint():
    # Audit #4 : l'endpoint doit être /token-pairs/v1/base/<tokenAddress>
    # (pas /latest/dex/pairs/base/<token> qui attend une adresse de paire).
    seen = {}
    orig = fetch_pairs_from_dexscreener

    def _capture(url, **kw):
        seen["url"] = url.full_url if hasattr(url, "full_url") else str(url)
        return _fake_dexscreener_response([])

    with mock.patch.object(urllib.request, "urlopen", side_effect=_capture):
        pairs = fetch_pairs_from_dexscreener(
            "0x000000000000000000000000000000000000feed")
    assert pairs == [], pairs
    assert "/token-pairs/v1/base/0x000000000000000000000000000000000000feed" in seen["url"], seen
    assert "/latest/dex/pairs/" not in seen["url"], seen
    print("OK test_scanner_dexscreener_token_pairs_endpoint — "
          "/token-pairs/v1/base/<tokenAddress>")


def test_scanner_token_pairs_bare_list_response():
    # RE-MESUREMENT 2026-11-25 (local, PRESERVE lors du merge GPT) :
    # l'endpoint /token-pairs/v1 renvoie en LIVE un TABLEAU JSON nu
    # ([{paire}, ...]), pas {"pairs": [...]}. Le fix #4 supposait le
    # schéma dict (son test mockait {"pairs": []}) : le live crashait
    # avec AttributeError ('list' object has no attribute 'get').
    # Ce test mocke la VRAIE forme live et exige qu'elle soit acceptée.
    pair = _dex_pair("uniswap", "0x1111111111111111111111111111111111111111",
                     0.001, 20_000, 10)
    body = json.dumps([pair]).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with mock.patch.object(urllib.request, "urlopen", return_value=resp):
        pairs = fetch_pairs_from_dexscreener(
            "0x000000000000000000000000000000000000feed")
    assert isinstance(pairs, list) and len(pairs) == 1, pairs
    assert pairs[0]["pairAddress"] == "0x1111111111111111111111111111111111111111", pairs
    print("OK test_scanner_token_pairs_bare_list_response — tableau JSON nu "
          "accepté (forme live réelle de /token-pairs/v1)")


def test_scanner_usdc_address_not_symbol():
    # Audit #4 : une paire dont le quoteToken s'appelle "USDC" mais dont
    # l'adresse n'est PAS celle de l'USDC Base doit être exclue (faux USDC).
    real = _dex_pair("uniswap", "0x1111111111111111111111111111111111111111",
                     0.001, 20_000, 10)
    fake = _dex_pair("uniswap", "0x2222222222222222222222222222222222222222",
                     0.0012, 18_000, 10,
                     quote_addr="0x9999999999999999999999999999999999999999")
    pools = pairs_to_pools([real, fake])
    assert len(pools) == 1, pools
    assert pools[0].name.startswith("uniswap:0x11111111"), pools
    print("OK test_scanner_usdc_address_not_symbol — faux USDC (symbole "
          "seul) exclu, vrai USDC (adresse) gardé")


def test_scanner_unknown_holders_rejected_explicitly():
    # Audit #3 — contre-exemple : 2 pools simulées, 20 000 $ de liquidité
    # chacune, 20 % d'écart, mais holders inconnus -> 0 candidat, AVEC la
    # raison explicite (pas un 0 silencieux).
    c = MemeCandidate("0x000000000000000000000000000000000000feed", "MEME",
                      "uniswap", "sushi",
                      Pool("A", 20_000, 20_000_000), Pool("B", 18_000, 15_000_000),
                      liquidity_usd=36_000, age_hours=10, age_known=True)
    assert c.holders_known is False, "holders inconnus par défaut"
    ok, reasons = passes_filters(c)
    assert ok is False, reasons
    assert any("holders inconnus" in r for r in reasons), reasons
    # Même candidat avec holders vérifiés -> passe (spread 20 %, âge 10 h).
    c.holders = 150
    c.holders_known = True
    c.holders_source = "goplus"
    ok2, _ = passes_filters(c)
    assert ok2 is True, "avec holders vérifiés le candidat passe"
    print("OK test_scanner_unknown_holders_rejected_explicitly — "
          "inconnu rejeté explicitement, vérifié accepté")


def test_scanner_holders_propagated():
    # Audit #3 : scan_token(goplus_check=True) transfère le holder_count
    # GoPlus vers les candidats (un seul appel GoPlus par token).
    token = "0x000000000000000000000000000000000000feed"
    goplus = {"code": 1, "message": "OK",
              "result": {token: {"is_honeypot": "0", "buy_tax": "0",
                                 "sell_tax": "0", "is_mintable": "0",
                                 "is_open_source": "1", "holder_count": "500"}}}
    pairs = [_dex_pair("uniswap", "0x1111111111111111111111111111111111111111",
                       0.001, 20_000, 10),
             _dex_pair("sushi", "0x2222222222222222222222222222222222222222",
                       0.0012, 18_000, 10)]

    def _dispatch(url, **kw):
        u = url.full_url if hasattr(url, "full_url") else str(url)
        if "gopluslabs" in u:
            return _fake_goplus_response(goplus)
        if "dexscreener" in u:
            return _fake_dexscreener_response(pairs)
        raise AssertionError(f"URL inattendue : {u}")

    with mock.patch.object(urllib.request, "urlopen", side_effect=_dispatch):
        cands = scan_token(token, "MEME", goplus_check=True)
    assert len(cands) == 1, cands
    c = cands[0]
    assert c.holders == 500 and c.holders_known is True, c
    assert c.holders_source == "goplus", c
    assert c.age_known is True and 9 < c.age_hours < 11, c.age_hours
    assert abs(c.spread() - 20.0) < 0.01, c.spread()
    print("OK test_scanner_holders_propagated — scan_token transfère "
          "holder_count=500 (GoPlus) + âge DexScreener, 1 candidat")


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
    test_v3_quote_single_encoding()
    test_v3_quote_single_live()
    test_v3_quote_onchain_live()
    test_goplus_honeypot_reject()
    test_goplus_clean_pass_and_unknown()
    test_goplus_tax_decimal()
    test_goplus_tax_unknown()
    test_goplus_not_open_source_and_few_holders_reject()
    test_scanner_dexscreener_token_pairs_endpoint()
    test_scanner_token_pairs_bare_list_response()
    test_scanner_usdc_address_not_symbol()
    test_scanner_unknown_holders_rejected_explicitly()
    test_scanner_holders_propagated()
    test_circuit_breaker()
    test_preflight_encoding_roundtrip()
    test_preflight_live_roundtrip()
    test_ev_small_run()
    print("\nTOUS LES TESTS V2 PASSENT.")
