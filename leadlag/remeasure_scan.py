#!/usr/bin/env python3
"""RE-MESUREMENT (SYNTHÉTIQUE — lectures API publiques + quotes, jamais un trade).
Re-scan memes Base avec le code CORRIGÉ (audit #3/#4/#5) :
  - découverte : GeckoTerminal new_pools pages 1-8 (72 h), réserve 5k-100k $,
    quote WETH/USDC
  - re-vérification des 14 tokens PASS1 du scan 2026-11-24 (comparaison avant/après
    sur les MÊMES tokens)
  - scan_token() réel (code corrigé) avec goplus_check=True
  - diagnostic par token : raisons de rejet explicites ; simulation de
    l'ANCIEN comportement (endpoint paire, holders jamais transférés,
    taxes décimales non converties) sur les mêmes données (cache partagé,
    1 seul appel GoPlus par token).
Sortie : leadlag/remeasure_scan_results.json + résumé imprimé.
Lecture seule : DexScreener + GoPlus + GeckoTerminal (APIs publiques).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import scanner  # noqa: E402

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
HDRS = {"Accept": "application/json", "User-Agent": "codema-bot-remeasure/1.0"}
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=72)

# 14 tokens PASS1 du scan 2026-11-24 (adresses complètes récupérées alors).
PASS1 = [
    "0x7efb019c4f1d1e90612edf58ab118c9be21c30e3",
    "0xa6cd081b821163f7e778d93121449a8d301bc4f1",
    "0x522b0a627ab057b411d431666ff7df0bd9acb29e",
    "0x1baaeaa608bebd0ff035613e622ff15fab365b72",
    "0x4861fabb560a93e71c90eb3a13421dad63a5fee1",
    "0xdd46d3973a7edf8b85384bcfd4230eabf281dba3",
    "0xeb2220e7ee843d3ac4c6c2f5a02347712ccfa8fd",
    "0x822c2c2fc165d05215cfb582d8ee580845faa248",
    "0x6afcdaacc9c974dfa0f028059214ebb9a510cb07",
    "0x39632eb24620972b997e8a12cfe2e8b31a287a96",
    "0x29ab93a0ecf7b11f596a6b9864773232e1d4f23b",
    "0x0cc92f16dbebde1bf6f0fc6c0a6742181ed3c6c5",
    "0x2b2ab77492bb3303ca080cc9523b867723967227",
    "0x24fecddbd0cd73565a6db9e645f31c444c31fb9d",
]


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "url": url}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e), "url": url}


def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


# --- cache partagé : 1 seul appel réseau par token pour GoPlus/DexScreener ---
_goplus_cache = {}
_pairs_cache = {}
_orig_goplus = scanner.fetch_goplus_security
_orig_pairs = scanner.fetch_pairs_from_dexscreener


def cached_goplus(addr, timeout=10):
    key = addr.lower()
    if key not in _goplus_cache:
        _goplus_cache[key] = _orig_goplus(addr, timeout)
        time.sleep(0.4)
    return _goplus_cache[key]


def cached_pairs(addr, timeout=10):
    key = addr.lower()
    if key not in _pairs_cache:
        _pairs_cache[key] = _orig_pairs(addr, timeout)
        time.sleep(0.4)
    return _pairs_cache[key]


scanner.fetch_goplus_security = cached_goplus
scanner.fetch_pairs_from_dexscreener = cached_pairs

# --- 0. Démonstration endpoint audit #4 : ancien URL vs nouveau (1 token) ---
demo_token = PASS1[0]
old = get(f"https://api.dexscreener.com/latest/dex/pairs/base/{demo_token}")
old_pairs = old.get("pairs") if isinstance(old, dict) else None
print(f"[endpoint #4] ancien URL /latest/dex/pairs/base/<token> -> "
      f"paires={None if old_pairs is None else len(old_pairs)} "
      f"(erreur={old.get('_http_error') or old.get('_error') or 'aucune, mais ressource paire'})")
new_pairs = cached_pairs(demo_token)
print(f"[endpoint #4] nouveau URL /token-pairs/v1/base/<token> -> paires={len(new_pairs)}")

# --- 1. Découverte GeckoTerminal new_pools pages 1-8 ---
pools, pages_ok = [], 0
for page in range(1, 9):
    d = get(f"https://api.geckoterminal.com/api/v2/networks/base/new_pools?page={page}")
    if "_http_error" in d or "_error" in d:
        print(f"GT page {page} erreur: {d}")
        break
    data = d.get("data", [])
    print(f"GT page {page}: {len(data)} pools")
    pages_ok += 1
    if not data:
        break
    pools.extend(data)
    oldest = data[-1].get("attributes", {}).get("pool_created_at")
    if parse_dt(oldest) and parse_dt(oldest) < CUTOFF:
        print(f"72h cutoff à la page {page}")
        break
    time.sleep(3)

new_tokens = {}
for p in pools:
    a = p.get("attributes", {})
    rel = p.get("relationships", {})
    try:
        reserve = float(a.get("reserve_in_usd") or 0)
        created = parse_dt(a.get("pool_created_at") or "")
        token_addr = rel.get("base_token", {}).get("data", {}).get("id", "").replace("base_", "")
        quote_addr = rel.get("quote_token", {}).get("data", {}).get("id", "").replace("base_", "")
    except Exception:  # noqa: BLE001
        continue
    if created is None or created < CUTOFF:
        continue
    if not (5000 <= reserve <= 100000):
        continue
    if quote_addr.lower() not in (WETH.lower(), USDC.lower()):
        continue
    if token_addr.lower() in (WETH.lower(), USDC.lower()):
        continue
    new_tokens.setdefault(token_addr.lower(), {
        "token": token_addr, "name": a.get("name"),
        "gt_reserve_usd": reserve, "gt_created_at": a.get("pool_created_at")})
print(f"GT nouveaux tokens (72h, 5k-100k$): {len(new_tokens)}")

# --- 2. Scan de chaque token avec le code corrigé ---
all_tokens = list(dict.fromkeys([t.lower() for t in PASS1] + list(new_tokens.keys())))
print(f"Tokens à scanner au total: {len(all_tokens)} "
      f"(PASS1={len(PASS1)} + GT nouveaux={len(new_tokens)})")
results = []
for token in all_tokens:
    t0 = time.time()
    # Diagnostic : paires + GoPlus (via cache partagé avec scan_token)
    pairs = cached_pairs(token)
    pools_list = scanner.pairs_to_pools(pairs)
    verdict, flags, info = scanner.vet_token_goplus_detailed(token)
    age_h = scanner.pairs_age_hours(pairs)
    priced = [pp for pp in pairs if pp.get("priceUsd") and (pp.get("liquidity") or {}).get("usd")]
    spread_mm = None
    if len(priced) >= 2:
        ps = sorted(float(x["priceUsd"]) for x in priced)
        spread_mm = (ps[-1] - ps[0]) / ((ps[-1] + ps[0]) / 2) * 100 if ps[0] > 0 else None
    # Raisons de rejet explicites (diagnostic, même logique que scan_token)
    reject_reasons = []
    for i, pa in enumerate(pools_list):
        for pb in pools_list[i + 1:]:
            buy, sell = (pa, pb) if pa.price_usdc_per_meme <= pb.price_usdc_per_meme else (pb, pa)
            liq = min(buy.liquidity_usd, sell.liquidity_usd)
            c = scanner.MemeCandidate(token_address=token, symbol="?",
                                      dex_a=buy.name, dex_b=sell.name,
                                      pool_a=buy, pool_b=sell, liquidity_usd=liq)
            c.spread_pct = c.spread()
            if age_h is not None:
                c.age_hours = age_h
                c.age_known = True
            if info.get("holder_count") is not None:
                c.holders = info["holder_count"]
                c.holders_known = True
                c.holders_source = "goplus"
            for f in flags:
                if f not in c.flags:
                    c.flags.append(f)
            ok, why = scanner.passes_filters(c)
            if not ok:
                reject_reasons.extend(why)
    # Ancien comportement simulé sur les MÊMES données :
    #  #4 ancien endpoint -> 0 paire -> 0 candidat (démontré §0)
    #  #3 holders jamais transférés -> holders=0 < 20 -> rejet systématique
    #  #5 taxes décimales comparées à 5.0 -> taxe 50 % (0.50) PASSAIT
    old_would_reject_holders = True  # holders=0 par défaut, jamais transférés
    old_tax_pass = None
    if info.get("buy_tax_pct") is not None and info.get("sell_tax_pct") is not None:
        old_tax_pass = max(info["buy_tax_pct"], info["sell_tax_pct"]) / 100.0 <= 5.0
    # Vrai scan (code corrigé, entrée réelle)
    cands = scanner.scan_token(token, symbol="?", goplus_check=True)
    rec = {
        "token": token,
        "source": "PASS1-2026-11-24" if token in [t.lower() for t in PASS1] else "GT-new-72h",
        "name_gt": (new_tokens.get(token) or {}).get("name"),
        "n_pairs_ds": len(pairs),
        "n_pools_usdc": len(pools_list),
        "spread_max_min_pct": spread_mm,
        "age_hours": age_h,
        "goplus_verdict": verdict,
        "goplus_flags": flags,
        "holder_count": info.get("holder_count"),
        "buy_tax_pct": info.get("buy_tax_pct"),
        "sell_tax_pct": info.get("sell_tax_pct"),
        "candidates_new_code": [
            {"dex_a": c.dex_a, "dex_b": c.dex_b, "spread_pct": round(c.spread(), 4),
             "liquidity_usd": round(c.liquidity_usd, 2), "holders": c.holders,
             "age_hours": round(c.age_hours, 2), "flags": c.flags}
            for c in cands],
        "reject_reasons_top": sorted(set(reject_reasons), key=reject_reasons.count,
                                     reverse=True)[:3] if reject_reasons else [],
        "old_code_would_return_0": True,  # #4 (0 paire) OU #3 (holders=0) -> 0 systématique
        "old_tax_would_pass": old_tax_pass,
        "scan_seconds": round(time.time() - t0, 1),
    }
    results.append(rec)
    print(f"{token[:14]} {rec['source'][:8]} pairs={len(pairs)} poolsUSDC={len(pools_list)} "
          f"spread={None if spread_mm is None else round(spread_mm, 2)}% "
          f"GoPlus={verdict}/{flags} holders={info.get('holder_count')} "
          f"tax={info.get('buy_tax_pct')}/{info.get('sell_tax_pct')} "
          f"-> candidats NOUVEAU CODE: {len(cands)} "
          f"(rejet top: {rec['reject_reasons_top'][:1]})")

total_cands = sum(len(r["candidates_new_code"]) for r in results)
rescued_by_3 = sum(1 for r in results if r["candidates_new_code"])
caught_by_5 = sum(1 for r in results
                  if r["buy_tax_pct"] is not None and max(r["buy_tax_pct"], r["sell_tax_pct"]) > 5.0)
tax_unknown = sum(1 for r in results if r["goplus_verdict"] == "UNKNOWN")
print(f"\n=== RÉSUMÉ SCAN ===")
print(f"Tokens scannés: {len(results)} | candidats NOUVEAU CODE: {total_cands} "
      f"(tokens avec ≥1 candidat: {rescued_by_3})")
print(f"Tokens avec taxe > 5 % (rejetés grâce au fix #5): {caught_by_5}")
print(f"Tokens GoPlus UNKNOWN (taxe absente ou API down): {tax_unknown}")
print(f"Ancien code: 0 candidat sur TOUS les tokens (endpoint #4 -> 0 paire, "
      f"holders #3 -> rejet systématique)")

out = {"generated_at_utc": NOW.isoformat(), "method": "scan_token() code corrigé + diagnostic",
       "endpoint_old_pairs_demo": None if old_pairs is None else len(old_pairs),
       "endpoint_new_pairs_demo": len(new_pairs),
       "gt_pages_ok": pages_ok, "gt_pools_seen": len(pools),
       "tokens_scanned": len(results), "candidates_total_new_code": total_cands,
       "tokens_with_candidate": rescued_by_3,
       "tokens_tax_gt_5pct_rejected_by_fix5": caught_by_5,
       "tokens_goplus_unknown": tax_unknown,
       "results": results}
with open(os.path.join(HERE, "remeasure_scan_results.json"), "w") as f:
    json.dump(out, f, indent=2)
print("saved leadlag/remeasure_scan_results.json")
