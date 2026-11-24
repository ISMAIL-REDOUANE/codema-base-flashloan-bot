#!/usr/bin/env python3
"""
watchlist_run.py — Runner de la watchlist meme Polygon (v4.1).

Conçu pour tourner toutes les 2–4 h (cron) : à chaque run il
  1. découvre les nouveaux tokens (GeckoTerminal new pools, pages 1–N,
     + DexScreener token-profiles latest — 2e source),
  2. RE-VÉRIFIE tous les tokens exec/watch de la watchlist (une 2e venue
     peut apparaître des heures/jours après le launch),
  3. évalue les tokens "exec" à 2 venues (GoPlus + spread ≥ 3 % + net
     > 0 $ après TOUS les coûts : flash 0 %, gas + budget revert
     ~2× gas — règle Ismail 2026-11-24, min profit 3 $ ABANDONNÉ
     sur Polygon) — SIMULATION seulement,
  4. append un log JSONL (watchlist_runs.jsonl) + un JSON détaillé par run.

Les tokens "watch" ne sont JAMAIS évalués pour exécution, même avec
2 venues : ils servent uniquement à détecter la 2e venue et à être
promus "exec" quand ils rentrent dans la fenêtre 5k–100k $ / <72 h.

Aucun broadcast mainnet, aucun fonds réel, aucune clé privée.

Usage :
  python3 watchlist_run.py [--gecko-pages 6] [--profiles-limit 100]
                           [--pair-check-limit 150]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scanner_polygon import (  # noqa: E402
    S, dexscreener_latest_profiles, dex_pairs, gecko_new_pools, goplus_ok,
    strip_token_prefix,
)
from watchlist import Watchlist, classify_tier, normalize_dex  # noqa: E402

# Gardes d'exécution — règle Ismail 2026-11-24 (min profit 3 $ ABANDONNÉ
# sur Polygon) : on entre dans N'IMPORTE QUEL trade dont le net simulé
# est > 0 $ après TOUS les coûts (flash 0 % Morpho, frais de swap dans
# les quotes, gas, ET budget revert pire cas = gas + gas de revert).
# polygon_config.yaml est mis à jour par Ismail lui-même (min_profit_usd
# 3,0 → 0,0) — NE PAS le toucher ici ; la règle vit dans ce fichier.
MIN_SPREAD_PCT = 3.0
MIN_PROFIT_USD = 0.0  # net > 0 $ strictement (3 $ abandonné 2026-11-24)
MAX_PCT_LIQUIDITY = 0.10
MAX_LOAN_USD = 50_000.0
GAS_USD_PER_TRADE = 0.0095  # 450 000 × 279 gwei × 0,0758 $/MATIC, mesuré 2026-11-24
REVERT_GAS_USD = GAS_USD_PER_TRADE  # un revert coûte ~1× gas de plus
TOTAL_COST_USD = GAS_USD_PER_TRADE + REVERT_GAS_USD  # pire cas ~2× gas

HERE = Path(__file__).parent
RUN_LOG = HERE / "watchlist_runs.jsonl"


def _age_h_from_iso(created: str | None, now: datetime) -> float:
    if not created:
        return 9999.0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (now - dt).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return 9999.0


def _venues_from_pairs(pairs: list) -> dict:
    """{dexId normalisé: [{pair, liq_usd}]} — une entrée par venue."""
    venues: dict = {}
    for p in pairs:
        dex = normalize_dex(p.get("dexId"))
        liq = p.get("liquidity", {}) or {}
        venues.setdefault(dex, []).append({
            "pair": str(p.get("pairAddress") or "").lower(),
            "liq_usd": liq.get("usd"),
            "price_usd": p.get("priceUsd"),
        })
    return venues


def gecko_tokens_from_pools(pools: list, now: datetime) -> dict:
    """Extrait {adresse 0x: {name, liq_usd, age_h, dex, pool}} des pools
    GeckoTerminal. L'id base_token est 'polygon_pos_0x…' : on retire
    le préfixe réseau complet (strip_token_prefix)."""
    out = {}
    for p in pools:
        a = p.get("attributes", {})
        rel = p.get("relationships", {})
        base = (rel.get("base_token", {}).get("data", {}) or {}).get("id", "")
        base = strip_token_prefix(base).lower()
        if not base or not base.startswith("0x"):
            continue
        liq = float(a.get("reserve_in_usd") or 0)
        age_h = _age_h_from_iso(a.get("pool_created_at"), now)
        dex_id = (rel.get("dex", {}).get("data", {}) or {}).get("id", "")
        out.setdefault(base, {
            "name": a.get("name"), "liq_usd": liq, "age_h": age_h,
            "dex": normalize_dex(dex_id), "pool": a.get("address")})
    return out


def estimate_opportunity(pairs: list) -> dict:
    """Estimation spread/net à partir des prix DexScreener par venue.

    spread = (max-min)/min sur priceUsd ; loan = min(10 % de la plus
    petite liquidité venue, 50 000 $) ; net = loan*spread - coût total
    pire cas (gas + budget revert ≈ 2× gas) — le flash est à 0 % Morpho
    et les frais de swap sont déjà dans les quotes (prix spot).
    Exécutable si spread ≥ 3 % ET net > 0 $ (règle Ismail 2026-11-24 :
    min profit 3 $ abandonné sur Polygon).
    Retourne {"spread_pct", "loan_usd", "net_usd", "executable"}.
    C'est une ESTIMATION (prix spot, pas de simulation fork) : un
    "executable" ici = candidat à vérifier sur fork Amoy, pas un ordre.
    """
    priced = [(float(p.get("priceUsd")), p) for p in pairs
              if p.get("priceUsd") not in (None, "")]
    liqs = [float((p.get("liquidity") or {}).get("usd") or 0)
            for p in pairs]
    if len(priced) < 2 or not liqs or min(liqs) <= 0:
        return {"spread_pct": 0.0, "loan_usd": 0.0, "net_usd": 0.0,
                "executable": False, "reason": "prix/liq insuffisants"}
    prices = [x[0] for x in priced]
    lo, hi = min(prices), max(prices)
    spread = (hi - lo) / lo * 100 if lo > 0 else 0.0
    loan = min(min(liqs) * MAX_PCT_LIQUIDITY, MAX_LOAN_USD)
    net = loan * spread / 100 - TOTAL_COST_USD
    net_r = round(net, 2)  # décision au centime : 0,000003 $ = 0,00 $ = bloqué
    if spread < MIN_SPREAD_PCT:
        reason = f"spread {spread:.2f} % < {MIN_SPREAD_PCT} %"
    elif net_r <= MIN_PROFIT_USD:
        reason = (f"net {net_r:.2f} $ ≤ 0 $ après tous coûts "
                  f"(gas + revert {TOTAL_COST_USD:.4f} $)")
    else:
        reason = "candidat (à vérifier sur fork)"
    return {"spread_pct": round(spread, 2), "loan_usd": round(loan, 2),
            "net_usd": net_r,
            "executable": spread >= MIN_SPREAD_PCT and net_r > MIN_PROFIT_USD,
            "reason": reason}


def run(gecko_pages: int = 6, profiles_limit: int = 100,
        pair_check_limit: int = 150, watchlist_path=None,
        run_log_path=None) -> dict:
    now = datetime.now(timezone.utc)
    wl = Watchlist(watchlist_path)
    stats_before = wl.stats()

    # --- 1. Découverte GeckoTerminal -------------------------------------
    pools, skipped_pages = gecko_new_pools(gecko_pages)
    gecko_tokens = gecko_tokens_from_pools(pools, now)
    for addr, t in gecko_tokens.items():
        venues = ({t["dex"]: [{"pair": t["pool"], "liq_usd": t["liq_usd"],
                               "price_usd": None}]} if t["dex"] else {})
        wl.upsert(addr, name=t["name"], venues=venues,
                  liq_usd=t["liq_usd"], age_h=t["age_h"],
                  source="geckoterminal")

    # --- 2. Découverte DexScreener token-profiles latest ------------------
    profile_addrs = dexscreener_latest_profiles(limit=profiles_limit)
    profiles_new = 0
    for addr in profile_addrs:
        if addr not in wl.tokens:
            profiles_new += 1
        # L'âge/liq viennent des paires (étape 3) ; on enregistre la source.
        wl.upsert(addr, source="dexscreener-profiles")

    # --- 3. Vérification des venues (nouveaux + recheck watchlist) -------
    to_check = list(gecko_tokens.keys())
    for addr in profile_addrs:
        if addr not in to_check:
            to_check.append(addr)
    for addr in wl.tokens_to_recheck():
        if addr not in to_check:
            to_check.append(addr)
    to_check = to_check[:pair_check_limit]

    new_second_venues, exec_opps, watch_two_venue = [], [], []
    evaluated_exec = []  # exec 2 venues, GoPlus OK — pour la distribution net
    checked = 0
    for addr in to_check:
        pairs = dex_pairs(addr)
        checked += 1
        if pairs:
            # Âge = plus ancienne paire ; liq = plus grosse paire.
            created_ms = [p.get("pairCreatedAt") for p in pairs
                          if p.get("pairCreatedAt")]
            age_h = ((now.timestamp() * 1000 - min(created_ms)) / 3_600_000
                     if created_ms else 9999.0)
            liq = max(float((p.get("liquidity") or {}).get("usd") or 0)
                      for p in pairs)
            name = None
            bt = (pairs[0].get("baseToken") or {})
            if bt.get("address", "").lower() == addr:
                name = bt.get("symbol")
            entry = wl.upsert(addr, name=name,
                              venues=_venues_from_pairs(pairs),
                              liq_usd=liq, age_h=age_h)
            if entry.get("_new_second_venue"):
                new_second_venues.append({
                    "token": addr, "name": entry.get("name"),
                    "dexs": entry.get("dexs"),
                    "tier": entry.get("tier")})
        else:
            entry = wl.tokens.get(addr, {})
        time.sleep(0.25)  # DexScreener : 300 req/min

        # --- 4. Évaluation : exec SEULEMENT (watch jamais exécuté) -------
        entry = wl.tokens.get(addr, {})
        if len(entry.get("dexs") or []) >= 2:
            if entry.get("tier") == "exec":
                ok, why = goplus_ok(addr)
                wl.set_goplus(addr, ok, why)
                est = estimate_opportunity(pairs)
                rec = {"token": addr, "name": entry.get("name"),
                       "dexs": entry.get("dexs"),
                       "goplus_ok": ok, "goplus_note": why, **est}
                if ok:
                    evaluated_exec.append(rec)
                if ok and est["executable"]:
                    exec_opps.append(rec)
                    print(f"  ✅ OPPORTUNITÉ {rec['name']} {addr} "
                          f"spread={est['spread_pct']}% net~{est['net_usd']}$")
                else:
                    print(f"  ❌ exec 2 venues {rec['name']} "
                          f"goplus_ok={ok} ({why}) spread={est['spread_pct']}% "
                          f"net~{est['net_usd']}$")
            elif entry.get("tier") == "watch":
                watch_two_venue.append({"token": addr,
                                        "name": entry.get("name"),
                                        "dexs": entry.get("dexs")})
                print(f"  👀 WATCH 2 venues (jamais exécuté) "
                      f"{entry.get('name')} {addr} dexs={entry.get('dexs')}")

    wl.save()
    stats_after = wl.stats()

    # Distribution du net (tranches) sur les exec 2 venues GoPlus OK :
    # montre l'effet du changement de règle (min 3 $ → net > 0 $).
    net_dist = {
        "evaluated_exec_goplus_ok": len(evaluated_exec),
        "net_gt_0": sum(1 for r in evaluated_exec if r["net_usd"] > 0),
        "net_ge_0_50": sum(1 for r in evaluated_exec if r["net_usd"] >= 0.50),
        "net_ge_3": sum(1 for r in evaluated_exec if r["net_usd"] >= 3.0),
        "net_le_0": sum(1 for r in evaluated_exec if r["net_usd"] <= 0),
    }

    result = {
        "date": now.isoformat(), "chain": "polygon", "chain_id": 137,
        "sources": {"geckoterminal_pages": gecko_pages,
                    "geckoterminal_pools_read": len(pools),
                    "geckoterminal_skipped_pages": skipped_pages,
                    "dexscreener_profiles_polygon": len(profile_addrs),
                    "dexscreener_profiles_new_tokens": profiles_new},
        "tokens_checked_pairs": checked,
        "watchlist_before": stats_before,
        "watchlist_after": stats_after,
        "new_second_venues": new_second_venues,
        "watch_two_venue": watch_two_venue,
        "exec_opportunities": exec_opps,
        "net_distribution": net_dist,
        "filters": {"exec_liq_usd": [5_000.0, 100_000.0],
                    "exec_max_age_h": 72,
                    "watch_liq_usd": [1_000.0, 500_000.0],
                    "watch_max_age_h": 168,
                    "min_spread_pct": MIN_SPREAD_PCT,
                    "min_profit_usd": MIN_PROFIT_USD,
                    "min_profit_rule": "net > 0 $ après tous coûts "
                                       "(gas + budget revert ~2× gas) — "
                                       "min 3 $ abandonné 2026-11-24",
                    "max_pct_liquidity": MAX_PCT_LIQUIDITY,
                    "gas_usd_per_trade": GAS_USD_PER_TRADE,
                    "revert_budget_usd": REVERT_GAS_USD,
                    "total_cost_worst_case_usd": TOTAL_COST_USD},
    }
    fname = HERE / f"watchlist_scan_{now.strftime('%Y-%m-%d_%H%M')}.json"
    fname.write_text(json.dumps(result, indent=2))
    log_path = Path(run_log_path) if run_log_path else RUN_LOG
    with log_path.open("a") as f:
        f.write(json.dumps({
            "date": result["date"],
            "pools_read": len(pools), "skipped_pages": skipped_pages,
            "profiles_polygon": len(profile_addrs),
            "tokens_checked": checked,
            "watchlist_total": stats_after["total_tokens"],
            "tier_exec": stats_after["tier_exec"],
            "tier_watch": stats_after["tier_watch"],
            "two_venue_exec": stats_after["two_venue_exec"],
            "two_venue_watch": stats_after["two_venue_watch"],
            "new_second_venues": len(new_second_venues),
            "exec_opportunities": len(exec_opps),
            "net_distribution": net_dist}) + "\n")

    print(f"\n=== WATCHLIST RUN {now.strftime('%Y-%m-%d %H:%M UTC')} ===")
    print(f"Pools Gecko lues : {len(pools)} "
          f"(pages skippées : {skipped_pages or 'aucune'})")
    print(f"Profils DexScreener Polygon : {len(profile_addrs)} "
          f"({profiles_new} nouveaux tokens)")
    print(f"Tokens vérifiés (paires) : {checked}")
    print(f"Watchlist : {stats_after['total_tokens']} tokens "
          f"(exec {stats_after['tier_exec']} / watch "
          f"{stats_after['tier_watch']} / none {stats_after['tier_none']})")
    print(f"2 venues : total {stats_after['two_venue_total']} "
          f"(exec {stats_after['two_venue_exec']} / "
          f"watch {stats_after['two_venue_watch']} / "
          f"none {stats_after['two_venue_total'] - stats_after['two_venue_exec'] - stats_after['two_venue_watch']})")
    print(f"Nouvelles 2e venues détectées ce run : {len(new_second_venues)}")
    print(f"Opportunités exec (GoPlus OK + spread ≥3 % + net > 0 $) : "
          f"{len(exec_opps)}")
    print(f"Distribution net (exec 2 venues, GoPlus OK, "
          f"n={net_dist['evaluated_exec_goplus_ok']}) : "
          f">0 $ : {net_dist['net_gt_0']} | ≥0,50 $ : "
          f"{net_dist['net_ge_0_50']} | ≥3 $ : {net_dist['net_ge_3']} | "
          f"≤0 $ : {net_dist['net_le_0']}")
    print(f"Détail : {fname.name} — log : {log_path.name}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gecko-pages", type=int, default=6)
    ap.add_argument("--profiles-limit", type=int, default=100)
    ap.add_argument("--pair-check-limit", type=int, default=150)
    args = ap.parse_args()
    run(gecko_pages=args.gecko_pages, profiles_limit=args.profiles_limit,
        pair_check_limit=args.pair_check_limit)


if __name__ == "__main__":
    main()
