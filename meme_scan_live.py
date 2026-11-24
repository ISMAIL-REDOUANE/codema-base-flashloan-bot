#!/usr/bin/env python3
"""Live meme-pool scan — recovery + pass 3.
Re-fetches GT new_pools pages 9-18 (recovers pass-2 full addresses, extends coverage),
re-checks all candidates via DexScreener, GoPlus compact for top 8.
Saves JSON next to this script (workspace persists across restarts).
"""
import json, time, urllib.request, urllib.error, os
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = datetime(2026, 11, 24, 19, 47, 27, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=72)
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
HDRS = {"Accept": "application/json", "User-Agent": "codema-bot-research/1.0"}

# Pass-1 candidates, full addresses recovered from the first scan's detailed dump.
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
    except Exception as e:
        return {"_error": str(e), "url": url}

def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def ds_pairs(token):
    d = get(f"https://api.dexscreener.com/latest/dex/tokens/{token}")
    time.sleep(0.4)
    if not isinstance(d, dict) or "pairs" not in d:
        return [], d
    out = []
    for pp in d["pairs"]:
        if pp.get("chainId") != "base":
            continue
        out.append({"dex": pp.get("dexId"), "labels": pp.get("labels"),
                    "pair": pp.get("pairAddress"), "price_usd": pp.get("priceUsd"),
                    "liquidity_usd": (pp.get("liquidity") or {}).get("usd"),
                    "volume_h24": (pp.get("volume") or {}).get("h24"),
                    "txns_h24": (pp.get("txns") or {}).get("h24"),
                    "created_at": pp.get("pairCreatedAt"),
                    "fdv": pp.get("fdv"), "market_cap": pp.get("marketCap"),
                    "base_symbol": (pp.get("baseToken") or {}).get("symbol"),
                    "base_name": (pp.get("baseToken") or {}).get("name"),
                    "url": pp.get("url")})
    return out, None

# 1) GT new_pools pages 9-18 (rate-limit friendly: 3s between calls)
pools, oldest, pages_ok = [], None, 0
for page in range(9, 19):
    d = get(f"https://api.geckoterminal.com/api/v2/networks/base/new_pools?page={page}")
    if "_http_error" in d or "_error" in d:
        print(f"GT page {page} error: {d}")
        break
    data = d.get("data", [])
    print(f"GT page {page}: {len(data)} pools")
    pages_ok += 1
    if not data:
        break
    pools.extend(data)
    oldest = data[-1].get("attributes", {}).get("pool_created_at")
    if parse_dt(oldest) and parse_dt(oldest) < CUTOFF:
        print(f"72h cutoff at page {page}")
        break
    time.sleep(3)
print(f"pages 9-18 pools: {len(pools)}, oldest: {oldest}")

new_cands, n_checked = {}, 0
for p in pools:
    a = p.get("attributes", {}); rel = p.get("relationships", {})
    n_checked += 1
    try:
        reserve = float(a.get("reserve_in_usd") or 0)
        created = parse_dt(a.get("pool_created_at") or "")
        token_addr = rel.get("base_token", {}).get("data", {}).get("id", "").replace("base_", "")
        quote_addr = rel.get("quote_token", {}).get("data", {}).get("id", "").replace("base_", "")
        dex_id = rel.get("dex", {}).get("data", {}).get("id", "")
    except Exception:
        continue
    if created is None or created < CUTOFF:
        continue
    if not (5000 <= reserve <= 100000):
        continue
    if quote_addr.lower() not in (WETH.lower(), USDC.lower()):
        continue
    if token_addr.lower() in (WETH.lower(), USDC.lower()):
        continue
    new_cands.setdefault(token_addr.lower(), {"token": token_addr, "name": a.get("name"), "gt_pools": []})
    new_cands[token_addr.lower()]["gt_pools"].append({
        "pair": a.get("address"), "dex_gt": dex_id, "reserve_usd": reserve,
        "created_at": a.get("pool_created_at"), "price_usd": a.get("base_token_price_usd"),
        "volume_h24": (a.get("volume_usd") or {}).get("h24"), "fdv_usd": a.get("fdv_usd")})
print(f"candidates pages 9-18 (incl. pass-2 recovered): {len(new_cands)}")

# 2) DexScreener check for ALL tokens (pass1 recovered + new)
all_tokens = list(dict.fromkeys([t.lower() for t in PASS1] + list(new_cands.keys())))
results = []
for token in all_tokens:
    pairs, err = ds_pairs(token)
    info = {"token": token,
            "name": (new_cands.get(token) or {}).get("name"),
            "ds_pairs": pairs, "n_pairs": len(pairs), "ds_error": err}
    if token in new_cands:
        info["gt_pools"] = new_cands[token]["gt_pools"]
        info["name"] = new_cands[token]["name"]
    priced = [x for x in pairs if x["price_usd"] and x["liquidity_usd"]]
    info["spread_pct_max_min"] = None
    if len(priced) >= 2:
        ps = sorted(float(x["price_usd"]) for x in priced)
        info["spread_pct_max_min"] = (ps[-1]-ps[0])/((ps[-1]+ps[0])/2)*100 if ps[0] > 0 else None
    if not info["name"] and pairs:
        info["name"] = pairs[0].get("base_name")
        info["symbol"] = pairs[0].get("base_symbol")
    results.append(info)
    print(token[:14], info.get("name"), "pairs=", len(pairs), "spread=", info["spread_pct_max_min"])
    for pp in pairs:
        print("   ", pp["dex"], pp.get("labels"), pp["pair"][:14] if pp["pair"] else None,
              "price=", pp["price_usd"], "liq=", pp["liquidity_usd"], "vol24=", pp["volume_h24"])

# 3) GoPlus compact, top 8 by DS volume
def vol(c):
    return max([float((pp.get("volume_h24") or 0)) for pp in c.get("ds_pairs", [])] + [0])
top = sorted(results, key=vol, reverse=True)[:8]
addrs = ",".join(c["token"] for c in top)
g = get(f"https://api.gopluslabs.io/api/v1/token_security/8453?contract_addresses={addrs}")
res = g.get("result", {}) if isinstance(g, dict) else {}
print("\n=== GOPLUS top 8 by volume ===")
for c in top:
    r = res.get(c["token"], res.get(c["token"].lower(), {}))
    if not r:
        print(c["token"][:14], c.get("name"), "-> NO GOPLUS DATA"); continue
    print(f"{c['token'][:14]} {c.get('name')}: honeypot={r.get('is_honeypot')} buy_tax={r.get('buy_tax')} "
          f"sell_tax={r.get('sell_tax')} mintable={r.get('is_mintable')} pausable={r.get('transfer_pausable')} "
          f"holders={r.get('holder_count')} owner%={r.get('owner_percent')} creator%={r.get('creator_percent')} "
          f"blacklist={r.get('is_blacklisted')} open_source={r.get('is_open_source')} proxy={r.get('is_proxy')}")

out = {"generated_at_utc": "2026-11-24T19:50:00Z", "now_local": "2026-11-24 19:50 Africa/Casablanca",
       "gt_pages_9_18_pools": len(pools), "oldest_pool_seen": oldest,
       "candidates": results, "goplus_top8": res}
with open(os.path.join(HERE, "meme_scan_2026-11-24.json"), "w") as f:
    json.dump(out, f, indent=2)
print("saved meme_scan_2026-11-24.json")
print(f"TOTAL tokens checked: {len(results)}, with >=2 pairs: {sum(1 for r in results if r['n_pairs'] >= 2)}")
