#!/usr/bin/env python3
"""Post-process cross_venue_results.json — corrections found by verification.

1. DEDUP: the same pool can appear twice in a group (DexScreener lists it
   under both tokens of the pair). Dedup by pair_address.
2. LIQUID mid gap: recompute mid_gap over liquid pools only
   (TVL >= $100 and txns_h24 >= 1). Dead pools (TVL $0.31, 1 txn) made the
   raw gap absurd (SPCXc 4e37%, WETH 1.5e28%).
3. VERIFICATION of nets (the AMZNc lesson): the analytic mono-tick model
   assumes a pool's current-tick liquidity persists across the whole tick.
   A pool whose liquidity sits in a ~1-tick range holding $1.38 total can
   show net +$2.085 while the on-chain quoter returns ~$0 for the same
   trade. A net counts as VERIFIED only if, for BOTH legs:
     - pool TVL >= 10x the trade size (a $100 trade needs >= $1,000 TVL/leg)
     - pool is not v2_mid_excluded
     - for Uniswap / PancakeSwap legs: a quoter cross-check exists and
       agrees with the analytic quote within 2% (validated to ~1e-6% on
       liquid pools; Aerodrome quoter checks are NOT used for validation —
       the MixedQuoter tag addresses (factory, tickSpacing), not a pool, so
       two pools of the same pair+tickSpacing return identical values and
       pools from the unverified 0x9cb2... factory cannot be addressed)
   REAL iff a VERIFIED net > $0 exists at some size. Otherwise ARTIFACT.
4. Re-sorts groups by verified best net at $100.

Writes corrected cross_venue_results.json (raw copy kept as
cross_venue_results_raw.json). Read-only w.r.t. chain (no new RPC calls).
"""
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / "cross_venue_results.json"
RAW_COPY = BASE / "cross_venue_results_raw.json"

TVL_MIN_LIQUID = 100.0
TVL_MULT = 10.0
QUOTER_TOL_PCT = 2.0


def pool_ok_for_size(pool, size):
    tvl = pool.get("liq_usd_ds")
    if tvl is None or tvl < TVL_MULT * size:
        return False, f"TVL ${tvl} < ${TVL_MULT * size:.0f} needed for ${size} trade"
    if pool.get("v2_mid_excluded"):
        return False, "V2 mid excluded (deviates >5% from CL median)"
    if pool.get("fee_bps") is None:
        return False, "fee unknown"
    venue = (pool.get("venue") or "").lower()
    if venue in ("uniswap", "pancakeswap"):
        qc = pool.get("quoter_check") or {}
        diff = qc.get("diff_pct")
        if diff is None:
            return False, f"{venue} quoter check missing"
        if abs(diff) > QUOTER_TOL_PCT:
            return False, f"{venue} quoter disagrees {diff:.2f}% (> {QUOTER_TOL_PCT}%)"
    return True, ""


def main():
    if not RAW_COPY.exists():
        shutil.copyfile(RAW, RAW_COPY)
    d = json.loads(RAW.read_text())
    n_dedup = 0
    for g in d["groups"]:
        # 1. dedup pools
        seen = {}
        for p in g["pools"]:
            if p["pair_address"].lower() not in seen:
                seen[p["pair_address"].lower()] = p
            else:
                n_dedup += 1
        g["pools"] = list(seen.values())
        # 2. liquid mid gap
        liq_pools = [p for p in g["pools"]
                     if (p.get("liq_usd_ds") or 0) >= TVL_MIN_LIQUID
                     and (p.get("txns_h24") or 0) >= 1
                     and p.get("mid_price_live")
                     and not p.get("v2_mid_excluded")]
        mids = [p["mid_price_live"] for p in liq_pools]
        if len(mids) >= 2:
            g["mid_gap_liquid_pct"] = round((max(mids) - min(mids)) / min(mids) * 100.0, 4)
        else:
            g["mid_gap_liquid_pct"] = None
        g["liquid_pool_count"] = len(liq_pools)
        # 3. verify tier pairs
        by_pool = {p["pair_address"].lower(): p for p in g["pools"]}
        seen_tp = set()
        verified_net = {}
        verified_pair = {}
        notes = []
        for tp in g.get("tier_pairs", []):
            key = (tp["buy_pair"].lower(), tp["sell_pair"].lower(), tp["size_usd"])
            if key in seen_tp:
                continue
            seen_tp.add(key)
            bp = by_pool.get(tp["buy_pair"].lower())
            sp = by_pool.get(tp["sell_pair"].lower())
            if not bp or not sp:
                continue
            ok_b, why_b = pool_ok_for_size(bp, tp["size_usd"])
            ok_s, why_s = pool_ok_for_size(sp, tp["size_usd"])
            tp["verified"] = bool(ok_b and ok_s)
            tp["verify_note"] = "" if tp["verified"] else f"buy: {why_b}; sell: {why_s}"
            if tp["verified"]:
                s = tp["size_usd"]
                if s not in verified_net or tp["net_usd"] > verified_net[s]:
                    verified_net[s] = tp["net_usd"]
                    verified_pair[s] = (f"buy {tp['buy_venue']}:{tp['buy_pair'][:10]}.. "
                                       f"-> sell {tp['sell_venue']}:{tp['sell_pair'][:10]}..")
        g["verified_net_usd"] = {str(s): verified_net.get(s) for s in (100, 500, 1000)}
        g["verified_pair"] = {str(s): verified_pair.get(s) for s in (100, 500, 1000)}
        # dedup tier_pairs list itself (keep first occurrence of each key)
        kept, seen_keys = [], set()
        for tp in g["tier_pairs"]:
            k = (tp["buy_pair"].lower(), tp["sell_pair"].lower(), tp["size_usd"])
            if k not in seen_keys:
                seen_keys.add(k)
                kept.append(tp)
        g["tier_pairs"] = kept
        # 4. reclassify
        best_verified = max((v for v in verified_net.values() if v is not None), default=None)
        best_analytic = max((v for v in g["best_net_usd"].values() if v is not None), default=None)
        if best_verified is not None and best_verified > 0:
            g["classification"] = "REAL"
            g["reason"] = (f"VERIFIED net > $0 at sizes "
                           f"{[s for s, v in verified_net.items() if v is not None and v > 0]} "
                           f"(TVL >= 10x size both legs, quoter-agreed)")
        else:
            g["classification"] = "ARTIFACT"
            if best_analytic is not None and best_analytic > 0:
                g["reason"] = (f"analytic net +${best_analytic:.2f} but NOT verified: "
                               f"best verified net ${best_verified} — thin/micro pool "
                               f"(TVL < 10x size) or quoter disagreement; "
                               f"mono-tick model overstates output on 1-tick-range liquidity")
            else:
                g["reason"] = g.get("reason", "") + " | verified net <= $0 at every size"
    d["real_gaps"] = [g for g in d["groups"] if g["classification"] == "REAL"]
    d["groups"].sort(key=lambda x: -((x.get("verified_net_usd") or {}).get("100") or -1e9))
    RAW.write_text(json.dumps(d, indent=1))
    print(f"deduped {n_dedup} duplicate pool rows; groups={len(d['groups'])}, "
          f"REAL(verified)={len(d['real_gaps'])} -> {RAW}")
    for g in d["groups"]:
        print(f"  {g['token_symbol']:8s} mid_gap={g['mid_gap_pct_live']:.3f}% "
              f"liquid_gap={g['mid_gap_liquid_pct']} nets={g['best_net_usd']} "
              f"verified={g['verified_net_usd']} -> {g['classification']}")


if __name__ == "__main__":
    main()
