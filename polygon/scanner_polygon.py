#!/usr/bin/env python3
"""
scanner_polygon.py — Scan live des meme pools Polygon (v4.0).

Cherche des tokens listés sur DEUX venues (ex : QuickSwap V2 + Uni V3) :
sans 2e paire, pas d'arbitrage 2-DEX possible — le scan dit 0 honnêtement.

Sources (gratuites, sans clé) :
  - GeckoTerminal : newest pools Polygon (filtre liquidité 5k–100k $, âge <72h)
  - DexScreener : paires par token (compte des venues sur Polygon)
  - GoPlus : sécurité du token (honeypot/taxe) — best-effort, UNKNOWN = rejet

Usage : python3 scanner_polygon.py [--max-candidates 20]
Sortie : meme_scan_polygon_<date>.json + résumé imprimé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

MIN_LIQ_USD = 5_000.0
MAX_LIQ_USD = 100_000.0
MAX_AGE_HOURS = 72
MAX_TAX_PCT = 5.0

GECKO_NEW = "https://api.geckoterminal.com/api/v2/networks/polygon_pos/new_pools"
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"
GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/137"

S = requests.Session()
S.headers.update({"User-Agent": "CODEMA-polygon-scanner/4.0",
                  "Accept": "application/json"})


def gecko_new_pools(pages: int = 2) -> list:
    pools = []
    for page in range(1, pages + 1):
        try:
            r = S.get(GECKO_NEW, params={"page": page}, timeout=20)
            if r.status_code != 200:
                print(f"GeckoTerminal page {page} : HTTP {r.status_code}")
                break
            pools += r.json().get("data", [])
        except Exception as e:  # noqa: BLE001
            print(f"GeckoTerminal page {page} : {e}")
            break
        time.sleep(1.5)  # rate limit : 30 appels/min
    return pools


def dex_pairs(token: str) -> list:
    try:
        r = S.get(DEX_TOKENS + token, timeout=20)
        if r.status_code != 200:
            return []
        return [p for p in (r.json().get("pairs") or [])
                if p.get("chainId") == "polygon"]
    except Exception:  # noqa: BLE001
        return []


def goplus_ok(token: str) -> tuple[bool, str]:
    try:
        r = S.get(GOPLUS, params={"contract_addresses": token}, timeout=20)
        d = (r.json().get("result") or {}).get(token.lower()) or {}
        if not d:
            return False, "UNKNOWN (pas de données GoPlus)"
        if d.get("is_honeypot") == "1":
            return False, "HONEYPOT"
        if d.get("is_open_source") == "0":
            return False, "contrat non vérifié"
        buy = float(d.get("buy_tax") or 0)
        sell = float(d.get("sell_tax") or 0)
        if max(buy, sell) > MAX_TAX_PCT:
            return False, f"taxe {buy}/{sell} % > {MAX_TAX_PCT} %"
        return True, f"taxe {buy}/{sell} %"
    except Exception as e:  # noqa: BLE001
        return False, f"UNKNOWN (erreur GoPlus : {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-candidates", type=int, default=20)
    ap.add_argument("--pages", type=int, default=2)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    pools = gecko_new_pools(args.pages)
    print(f"Pools récentes lues (GeckoTerminal) : {len(pools)}")
    candidates, two_venue, rejected = [], [], []
    # Audit du filtre : pourquoi les pools sont écartées AVANT le stade candidat
    rejected_pre, max_liq_seen = [], 0.0
    seen_tokens = set()
    for p in pools:
        a = p.get("attributes", {})
        liq = float(a.get("reserve_in_usd") or 0)
        max_liq_seen = max(max_liq_seen, liq)
        created = a.get("pool_created_at")
        try:
            age_h = (now - datetime.fromisoformat(
                created.replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            age_h = 9999
        if not (MIN_LIQ_USD <= liq <= MAX_LIQ_USD and age_h <= MAX_AGE_HOURS):
            rejected_pre.append({"name": a.get("name"),
                                 "liq_usd": round(liq, 2),
                                 "age_h": round(age_h, 1),
                                 "reason": ("liq hors 5k-100k $"
                                            if not (MIN_LIQ_USD <= liq <= MAX_LIQ_USD)
                                            else "age > 72h")})
            continue
        rel = p.get("relationships", {})
        base = (rel.get("base_token", {}).get("data", {}) or {}).get("id", "")
        base = base.replace("polygon_", "")
        if not base or base in seen_tokens:
            continue
        seen_tokens.add(base)
        candidates.append({"token": base, "name": a.get("name"),
                           "pool": a.get("address"), "liq_usd": round(liq, 2),
                           "age_h": round(age_h, 1)})
        if len(candidates) >= args.max_candidates:
            break

    print(f"Candidats (liq 5k–100k $, <72h) : {len(candidates)}")
    for c in candidates:
        pairs = dex_pairs(c["token"])
        venues = sorted({(p.get("dexId"), p.get("pairAddress")) for p in pairs})
        c["venues"] = len(venues)
        c["dexs"] = sorted({p.get("dexId") for p in pairs})
        c["pairs"] = [{"dex": p.get("dexId"), "pair": p.get("pairAddress"),
                       "liq": p.get("liquidity", {}).get("usd"),
                       "price_usd": p.get("priceUsd")} for p in pairs]
        ok, why = goplus_ok(c["token"])
        c["goplus_ok"] = ok
        c["goplus_note"] = why
        if len(venues) >= 2 and ok:
            two_venue.append(c)
            print(f"  ✅ 2 VENUES {c['name']} {c['token']} liq={c['liq_usd']}$ "
                  f"dexs={c['dexs']} goplus={why}")
        else:
            rejected.append({**c, "reason":
                             ("1 seule venue" if len(venues) < 2 else "GoPlus : " + why)})
            print(f"  ❌ {c['name']} venues={len(venues)} goplus_ok={ok} ({why})")
        time.sleep(0.4)

    out = {"date": now.isoformat(), "chain": "polygon", "chain_id": 137,
           "pools_lus": len(pools), "candidats": len(candidates),
           "deux_venues": len(two_venue), "two_venue": two_venue,
           "rejected": rejected,
           "rejected_pre_filter": {"count": len(rejected_pre),
                                   "max_liq_usd_seen": round(max_liq_seen, 2),
                                   "examples": rejected_pre[:10]},
           "filter": {"liq_usd": [MIN_LIQ_USD, MAX_LIQ_USD],
                      "max_age_h": MAX_AGE_HOURS}}
    fname = f"meme_scan_polygon_{now.strftime('%Y-%m-%d')}.json"
    Path(fname).write_text(json.dumps(out, indent=2))
    print(f"\n=== VERDICT POLYGON : {len(two_venue)} token(s) avec 2 venues "
          f"sur {len(candidates)} candidats ===")
    print(f"Détail : {fname}")
    if not two_venue:
        print("Aucun arbitrage meme 2-DEX sur Polygon en ce moment — "
              "le scan doit tourner toutes les 2–4 h (watchlist).")


if __name__ == "__main__":
    main()
