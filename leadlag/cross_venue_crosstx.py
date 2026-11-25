#!/usr/bin/env python3
"""CROSS-TX — same pool pair across CONSECUTIVE blocks (Ismail 2026-11-25 11:19).

Question: after a big trade moves pool A (block N), pool B has not repriced
yet — how big is the gap that appears between A and B, and how many blocks
does it survive? If a gap lives only 1 block, you must enter IN that block.

Method (read-only, no broadcast):
  * pool pairs taken from cross_venue_results.json (most liquid group first,
    top 2 pools per group, up to 2 groups)
  * poll each new block for ~DURATION_S seconds; at every block read each
    pool's mid price (CL: slot0 sqrtPriceX96 or Algebra globalState;
    V2: reserve ratio) at that exact block
  * gap% = (mid_B - mid_A) / mid_A * 100
  * an "episode" starts when |gap| > threshold (the tier-pair breakeven from
    the main scan) and ends when |gap| < 0.05% again; duration in blocks
  * a "big trade in A" is flagged when mid_A moves > 0.05% between two
    consecutive blocks — episodes are attributed to it when they start on
    the same block

Output: leadlag/cross_venue_crosstx.json + printed summary.
Every number is a LIVE measurement (not a quote, not synthetic).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
import cross_venue as cv

RESULTS_JSON = cv.OUT_JSON  # cross_venue_results.json
OUT_JSON = cv.BASE_DIR / "cross_venue_crosstx.json"

DURATION_S = 600          # 10 minutes of blocks (~300 blocks on Base)
GAP_CLOSE_PCT = 0.05      # episode ends when |gap| falls below this
BIG_MOVE_PCT = 0.05       # "big trade in A" = mid_A moves more than this in 1 block
MAX_GROUPS = 2
MAX_POOLS_PER_GROUP = 2


def mid_at_block(pool_rec, block):
    """Mid price (quote per token) of one pool at a pinned block."""
    pt = pool_rec.get("pool_type")
    addr = pool_rec["pair_address"]
    dec = pool_rec["_dec_token"]
    qdec = pool_rec["_dec_quote"]
    tok_is_t0 = pool_rec.get("token_is_token0")
    if pt == "cl":
        if pool_rec.get("mid_method") == "algebra_globalState":
            alg = cv.algebra_state(addr, block)
            if not alg:
                return None
            return cv.price_from_sqrt(alg["sqrt_x96"], dec, qdec, tok_is_t0)
        st = cv.pool_state(addr, block)
        if "sqrt_x96" not in st:
            return None
        return cv.price_from_sqrt(st["sqrt_x96"], dec, qdec, tok_is_t0)
    if pt == "v2":
        res = cv.v2_reserves(addr, block)
        if not res:
            return None
        if tok_is_t0:
            return (res[1] / 10 ** qdec) / (res[0] / 10 ** dec)
        return (res[0] / 10 ** qdec) / (res[1] / 10 ** dec)
    return None


def main():
    cv.init_selectors()
    t0 = time.time()
    data = json.loads(RESULTS_JSON.read_text())
    scan_block = data["block"]
    groups = []
    for g in data["groups"]:
        pools = [p for p in g["pools"]
                 if p.get("mid_price_live") and not p.get("v2_mid_excluded")]
        if len(pools) < 2:
            continue
        # most liquid pool of each of the top 2 venues (cross-venue pair:
        # repricing lag is a cross-venue phenomenon)
        by_venue = {}
        for p in pools:
            v = (p.get("venue") or "?").lower()
            if v not in by_venue or (p.get("liq_usd_ds") or 0) > (by_venue[v].get("liq_usd_ds") or 0):
                by_venue[v] = p
        venue_rank = sorted(by_venue.values(), key=lambda p: -(p.get("liq_usd_ds") or 0))
        pools = venue_rank[:MAX_POOLS_PER_GROUP]
        if len(pools) < 2:
            continue
        dec = cv.token_decimals(g["token_addr"])
        qdec = cv.token_decimals(g["quote_addr"])
        for p in pools:
            p["_dec_token"] = dec
            p["_dec_quote"] = qdec
            # token_is_token0 is not stored in the JSON — fetch once on-chain
            try:
                t0a = "0x" + cv.eth_call(p["pair_address"], "0x" + cv.SEL_TOKEN0, "latest")[-40:]
                p["token_is_token0"] = (t0a.lower() == g["token_addr"].lower())
            except Exception:
                p["token_is_token0"] = None
        # threshold for the pair = min breakeven over sizes (from tier_pairs)
        thr = None
        for tp in g.get("tier_pairs", []):
            if {tp["buy_pair"], tp["sell_pair"]} == {pools[0]["pair_address"], pools[1]["pair_address"]}:
                thr = tp["threshold_pct"] if thr is None else min(thr, tp["threshold_pct"])
        groups.append({"token": g["token_symbol"], "token_addr": g["token_addr"],
                       "quote_addr": g["quote_addr"], "pools": pools,
                       "threshold_pct": thr if thr is not None else 0.10})
        if len(groups) >= MAX_GROUPS:
            break
    if not groups:
        print("no usable groups in results JSON — run cross_venue.py first")
        return
    for g in groups:
        print(f"tracking {g['token']}: " +
              " vs ".join(f"{p['venue']}:{p['pair_address'][:10]}.." for p in g["pools"]) +
              f" | threshold {g['threshold_pct']:.4f}% (scan block {scan_block})", flush=True)

    # state per group
    series = {i: [] for i in range(len(groups))}       # (block, gap_pct, midA, midB)
    episodes = {i: [] for i in range(len(groups))}
    open_ep = {i: None for i in range(len(groups))}
    prev_mid = {i: (None, None) for i in range(len(groups))}
    last_block = None
    n_blocks = 0

    with ThreadPoolExecutor(max_workers=8) as ex:
        while time.time() - t0 < DURATION_S:
            try:
                blk = int(cv.rpc_call("eth_blockNumber", []), 16)
            except Exception as e:
                print("block poll error:", str(e)[:100], flush=True)
                time.sleep(1)
                continue
            if blk == last_block:
                time.sleep(0.4)
                continue
            last_block = blk
            n_blocks += 1
            for gi, g in enumerate(groups):
                pa, pb = g["pools"][0], g["pools"][1]
                try:
                    ma, mb = list(ex.map(lambda p: mid_at_block(p, blk), [pa, pb]))
                except Exception as e:
                    print(f"  block {blk}: quote error {str(e)[:80]}", flush=True)
                    continue
                if ma is None or mb is None or ma <= 0:
                    continue
                gap = (mb - ma) / ma * 100.0
                # big move in A?
                prev_a, _ = prev_mid[gi]
                big_a = (prev_a is not None and abs(ma / prev_a - 1.0) * 100.0 > BIG_MOVE_PCT)
                prev_mid[gi] = (ma, mb)
                series[gi].append({"block": blk, "gap_pct": round(gap, 5),
                                   "mid_a": ma, "mid_b": mb, "big_move_a": big_a})
                thr = g["threshold_pct"]
                ep = open_ep[gi]
                if ep is None and abs(gap) > thr:
                    open_ep[gi] = {"start_block": blk, "max_gap_pct": gap,
                                   "max_abs_gap_pct": abs(gap), "big_move_a": big_a,
                                   "threshold_pct": thr}
                elif ep is not None:
                    if abs(gap) > ep["max_abs_gap_pct"]:
                        ep["max_gap_pct"] = gap
                        ep["max_abs_gap_pct"] = abs(gap)
                    if abs(gap) < GAP_CLOSE_PCT:
                        ep["end_block"] = blk
                        ep["duration_blocks"] = blk - ep["start_block"] + 1
                        episodes[gi].append(ep)
                        open_ep[gi] = None
            if n_blocks % 25 == 0:
                print(f"  ... {n_blocks} blocks, {time.time() - t0:.0f}s elapsed", flush=True)
    # close still-open episodes
    for gi, ep in open_ep.items():
        if ep is not None:
            ep["end_block"] = last_block
            ep["duration_blocks"] = last_block - ep["start_block"] + 1
            ep["still_open"] = True
            episodes[gi].append(ep)

    out_groups = []
    for gi, g in enumerate(groups):
        gaps = [s["gap_pct"] for s in series[gi]]
        agaps = sorted(abs(x) for x in gaps)
        n = len(agaps)
        def pct(p):
            return round(agaps[min(n - 1, int(p * n))] if n else 0, 5)
        big_moves = sum(1 for s in series[gi] if s["big_move_a"])
        out_groups.append({
            "token": g["token"], "token_addr": g["token_addr"],
            "quote_addr": g["quote_addr"],
            "pool_a": {"venue": g["pools"][0]["venue"], "pair_address": g["pools"][0]["pair_address"],
                       "fee_bps": g["pools"][0].get("fee_bps")},
            "pool_b": {"venue": g["pools"][1]["venue"], "pair_address": g["pools"][1]["pair_address"],
                       "fee_bps": g["pools"][1].get("fee_bps")},
            "threshold_pct": g["threshold_pct"],
            "blocks_observed": n,
            "first_block": series[gi][0]["block"] if series[gi] else None,
            "last_block": series[gi][-1]["block"] if series[gi] else None,
            "gap_abs_median_pct": pct(0.5),
            "gap_abs_p95_pct": pct(0.95),
            "gap_abs_max_pct": round(max(agaps) if agaps else 0, 5),
            "blocks_above_threshold": sum(1 for x in agaps if x > g["threshold_pct"]),
            "big_moves_in_a": big_moves,
            "episodes": episodes[gi],
            "series": series[gi],
        })
    result = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scan_block_reference": scan_block,
        "duration_s": round(time.time() - t0, 1),
        "gap_close_pct": GAP_CLOSE_PCT,
        "big_move_pct": BIG_MOVE_PCT,
        "groups": out_groups,
    }
    OUT_JSON.write_text(json.dumps(result, indent=1))
    print(f"\nDONE in {result['duration_s']}s -> {OUT_JSON}", flush=True)
    for g in out_groups:
        print(f"  {g['token']}: {g['blocks_observed']} blocks, "
              f"|gap| median {g['gap_abs_median_pct']}% p95 {g['gap_abs_p95_pct']}% "
              f"max {g['gap_abs_max_pct']}% | above thr {g['threshold_pct']}%: "
              f"{g['blocks_above_threshold']} blocks, {len(g['episodes'])} episodes, "
              f"big moves in A: {g['big_moves_in_a']}", flush=True)
        for ep in g["episodes"]:
            print(f"    episode blocks {ep['start_block']}->{ep['end_block']} "
                  f"({ep['duration_blocks']} blocks), max gap {ep['max_gap_pct']:.4f}%, "
                  f"after big move in A: {ep['big_move_a']}", flush=True)
    return result


if __name__ == "__main__":
    main()
