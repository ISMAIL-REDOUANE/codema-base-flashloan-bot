"""audit_checks.py — ROOT-CAUSE AUDIT (read-only).

Recomputes everything from OUR OWN data/logs. No broadcast, no wallet,
no keys, no funds. Numbers printed here are:
  - LIVE: measured from our logs / live read-only calls
  - SYNTHETIC: reconstructed / recomputed (labelled as such in output)
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v3_quote import v3_quote_python  # noqa: E402

LEAD = Path(str(Path(__file__).resolve().parents[1] / 'leadlag'))
ENTRIES = LEAD / "paper_entries.jsonl"
MEAS = LEAD / "measurements.jsonl"
SCAN = LEAD / "expert_scan_results.json"

GAS_TOTAL_X2 = 0.00889   # LIVE: paper_run1.log gas_total
GAS_TOTAL_X1 = 0.00445   # LIVE: half of it (one trade, no revert budget)


def load_jsonl(p):
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def pct(vals, q):
    if not vals:
        return None
    a = sorted(vals)
    i = min(len(a) - 1, max(0, int(math.ceil(q / 100.0 * len(a))) - 1))
    return a[i]


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return 0.0, 0.0, n
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return 0.0, 0.0, n
    return sxy / math.sqrt(sxx * syy), sxy / sxx, n


def sqrt_from_mid(mid, asset_dec, asset_is_token0):
    """Reconstruct sqrtPriceX96 from a human mid price (SYNTHETIC recon)."""
    adj = 10.0 ** (asset_dec - 6)
    if asset_is_token0:
        sqrt_p = math.sqrt(mid / adj)
    else:
        sqrt_p = math.sqrt(adj / mid)
    return int(sqrt_p * (2 ** 96))


def price_from_sqrt(sqrt_x96, asset_dec, asset_is_token0):
    sqrt_p = sqrt_x96 / 2 ** 96
    adj = 10.0 ** (asset_dec - 6)
    if asset_is_token0:
        return sqrt_p * sqrt_p * adj
    return adj / (sqrt_p * sqrt_p)


def roundtrip(size_usd, sqrt_x96, liq, fee_tier, asset_dec, is_t0):
    """SYNTHETIC: mono-tick round-trip cost at zero move (same model as
    paper_trade.threshold_for_tier). Returns (cost_usd, impact_pct)."""
    bps = max(1, fee_tier // 100)
    buy = v3_quote_python(size_usd * 1e6, float(liq), sqrt_x96,
                          fee_bps=bps, zero_for_one=not is_t0)
    if buy.amount_out <= 0:
        return None
    mid = price_from_sqrt(sqrt_x96, asset_dec, is_t0)
    exec_px = size_usd / (buy.amount_out / 10 ** asset_dec)
    impact = (exec_px - mid) / mid * 100.0 if mid > 0 else 0.0
    if abs(impact) > 1.0:
        return None
    sell = v3_quote_python(buy.amount_out, float(liq), sqrt_x96,
                           fee_bps=bps, zero_for_one=is_t0)
    return size_usd - sell.amount_out / 1e6, impact


def net_at_move(size_usd, sqrt_x96, liq, fee_tier, asset_dec, is_t0,
                move_pct, gas_total):
    """SYNTHETIC: net of a trade that captures move_pct (mono-tick)."""
    bps = max(1, fee_tier // 100)
    buy = v3_quote_python(size_usd * 1e6, float(liq), sqrt_x96,
                          fee_bps=bps, zero_for_one=not is_t0)
    if buy.amount_out <= 0:
        return None
    mid = price_from_sqrt(sqrt_x96, asset_dec, is_t0)
    exec_px = size_usd / (buy.amount_out / 10 ** asset_dec)
    impact = (exec_px - mid) / mid * 100.0 if mid > 0 else 0.0
    if abs(impact) > 1.0:
        return None
    f = math.sqrt(1.0 + move_pct / 100.0)
    sqrt_fut = int(sqrt_x96 * f) if is_t0 else int(sqrt_x96 / f)
    sell = v3_quote_python(buy.amount_out, float(liq), sqrt_fut,
                           fee_bps=bps, zero_for_one=is_t0)
    return sell.amount_out / 1e6 - size_usd - gas_total, impact


def main():
    print("=" * 78)
    print("ROOT-CAUSE AUDIT — checks on OUR OWN data (LIVE vs SYNTHETIC labelled)")
    print("=" * 78)

    # ---------------------------------------------------------------- A. entries
    recs = load_jsonl(ENTRIES)
    print(f"\n[A] paper_entries.jsonl: {len(recs)} records (LIVE log)")
    dec = Counter((r.get("pair"), r.get("decision")) for r in recs
                  if r.get("kind") == "eval")
    for k in sorted(dec):
        print(f"    {k[0]:12s} {k[1]:12s} {dec[k]}")
    cyc = [r for r in recs if r.get("kind") == "summary"]
    print("    summary records:", cyc)

    print("\n[A2] Calibration records (LIVE):")
    for r in recs:
        if r.get("kind") == "calibration":
            print("   ", json.dumps(r, sort_keys=True)[:600])

    # --- time series per pair from eval records (LIVE)
    series = defaultdict(list)  # pair -> [(t_ms, bin_mid, imb01, imb05, dex_mid)]
    for r in recs:
        if r.get("kind") != "eval" or r.get("phase") != "live":
            continue
        series[r["pair"]].append(r)
    # also include calibration-phase evals for the series (they have bin_mid)
    for r in recs:
        if r.get("kind") != "eval" or r.get("phase") != "calibration":
            continue
        series[r["pair"]].append(r)
    for p in series:
        series[p].sort(key=lambda r: r["t_ms"])

    print("\n[B] SIGNAL — imbalance -> forward move (LIVE, recomputed from evals)")
    for p, rows in series.items():
        has_bin = any(r.get("bin_mid") is not None for r in rows)
        if not has_bin:
            print(f"    {p}: NO Binance signal (not listed)")
            continue
        # forward move +1 cycle and +2 cycles on Binance mid
        xs1, ys1, xs2, ys2 = [], [], [], []
        for i in range(len(rows) - 2):
            b0 = rows[i].get("bin_mid")
            b1 = rows[i + 1].get("bin_mid")
            b2 = rows[i + 2].get("bin_mid")
            if None in (b0, b1, b2):
                continue
            xs1.append(rows[i].get("imb_01") or 0.0)
            ys1.append((b1 - b0) / b0 * 100.0)
            xs2.append(rows[i].get("imb_01") or 0.0)
            ys2.append((b2 - b0) / b0 * 100.0)
        c1, s1, n1 = pearson(xs1, ys1)
        c2, s2, n2 = pearson(xs2, ys2)
        max_imb = max(abs(x) for x in xs1) if xs1 else 0.0
        print(f"    {p}: n={n1} corr imb01->+1cyc={c1:.3f} slope={s1:.4f} "
              f"| ->+2cyc={c2:.3f} slope={s2:.4f} | max|imb|={max_imb:.3f} "
              f"| MAX predicted move (slope x max|imb|) = {abs(s1)*max_imb:.4f}% "
              f"(+1cyc) / {abs(s2)*max_imb:.4f}% (+2cyc)")
        # conditional: extreme imbalance vs calm (thresholds adapt to data)
        hi = [abs(y) for x, y in zip(xs1, ys1) if abs(x) > 0.2]
        lo = [abs(y) for x, y in zip(xs1, ys1) if abs(x) < 0.05]
        def _stat(v):
            return (len(v), round(sum(v)/len(v), 4) if v else None,
                    round(max(v), 4) if v else None)
        print(f"        |mv+1| when |imb|>0.2: n/mean/max={_stat(hi)} "
              f"| when |imb|<0.05: n/mean/max={_stat(lo)}")
        # base rate of moves > 0.1%
        big = [y for y in ys1 if abs(y) > 0.1]
        print(f"        base rate |Binance mv+1| > 0.1%: {len(big)}/{len(ys1)} "
              f"= {100*len(big)/max(1,len(ys1)):.2f}%")

    print("\n[C] DEX MOVE DISTRIBUTIONS (LIVE, from dex_mv_1c_pct / dex_mv_2c_pct)")
    for p, rows in series.items():
        m1 = [abs(r["dex_mv_1c_pct"]) for r in rows
              if r.get("dex_mv_1c_pct") is not None]
        m2 = [abs(r["dex_mv_2c_pct"]) for r in rows
              if r.get("dex_mv_2c_pct") is not None]
        if not m1:
            continue
        print(f"    {p}: n1={len(m1)} |mv1c| med={pct(m1,50):.4f}% p90={pct(m1,90):.4f}% "
              f"p95={pct(m1,95):.4f}% p99={pct(m1,99):.4f}% max={max(m1):.4f}% "
              f"| n2={len(m2)} |mv2c| med={pct(m2,50):.4f}% p95={pct(m2,95):.4f}% "
              f"max={max(m2):.4f}%")
        # persistence: moves that exceed 0.1% at +1c but are gone at +2c?
        gone = stayed = 0
        for r in rows:
            a = r.get("dex_mv_1c_pct")
            b = r.get("dex_mv_2c_pct")
            if a is None or b is None:
                continue
            if abs(a) > 0.1 and abs(b) <= 0.1:
                gone += 1
            if abs(a) > 0.1 and abs(b) > 0.1:
                stayed += 1
        print(f"        |mv1c|>0.1% : {gone+stayed} cycles — reverted by +2c: {gone}, "
              f"persisted: {stayed}")

    print("\n[D] THRESHOLD CURVE BY SIZE (SYNTHETIC recompute, mono-tick model)")
    # SOSO case from the OPP record (LIVE state): mid 0.296333, L 5.21e17,
    # fee tier 100 (0.01%), SOSO is token0 (0x62.. < 0x83.. USDC), dec 18.
    cases = [
        ("SOSO/USDC fee100", 0.296333, 520771945735401923, 100, 18, True),
    ]
    # ETH/USDC 0.01% tier state (LIVE, from paper_run1.log): L=1.09e17, mid ~1646.93
    cases.append(("ETH/USDC fee100", 1646.93, 1.09e17, 100, 18, False))
    # AERO/USDC 0.05% tier (LIVE): L=2.56e17, mid from entries
    aero_mid = None
    for r in recs:
        if r.get("pair") == "AERO/USDC" and r.get("dex_mid"):
            aero_mid = r["dex_mid"]
            break
    if aero_mid:
        cases.append(("AERO/USDC fee500", aero_mid, 2.56e17, 500, 18, True))
    for name, mid, liq, fee, dec, is_t0 in cases:
        sq = sqrt_from_mid(mid, dec, is_t0)
        print(f"    --- {name} (mid={mid}, L={liq:.3g}) ---")
        for s in (25, 50, 100, 250, 500, 1000, 5000):
            rt = roundtrip(float(s), sq, liq, fee, dec, is_t0)
            if rt is None:
                print(f"        ${s:>5}: model invalid (impact>1%)")
                continue
            cost, imp = rt
            th2 = (cost + GAS_TOTAL_X2) / s * 100.0
            th1 = (cost + GAS_TOTAL_X1) / s * 100.0
            print(f"        ${s:>5}: roundtrip=${cost:.4f} impact={imp:.4f}% "
                  f"threshold gasx2={th2:.4f}% gasx1={th1:.4f}% "
                  f"(gas share of threshold: {100*GAS_TOTAL_X2/(cost+GAS_TOTAL_X2):.0f}%)")
    # SOSO move 0.1741% at each size (SYNTHETIC net)
    print("\n[D2] SOSO move 0.1741% — net by size (SYNTHETIC, mono-tick)")
    sq = sqrt_from_mid(0.296333, 18, True)
    for s in (25, 50, 100, 250, 500, 1000):
        n2 = net_at_move(float(s), sq, 520771945735401923, 100, 18, True,
                         0.1741, GAS_TOTAL_X2)
        n1 = net_at_move(float(s), sq, 520771945735401923, 100, 18, True,
                         0.1741, GAS_TOTAL_X1)
        print(f"    ${s:>5}: net gasx2={n2[0] if n2 else None} "
              f"net gasx1={n1[0] if n1 else None} "
              f"(impact={n2[1]:.4f}%)" if n2 else f"    ${s:>5}: invalid")

    print("\n[E] LEAD-LAG measurements.jsonl (LIVE, 12 min)")
    m = load_jsonl(MEAS)
    print(f"    {len(m)} records")
    # count Binance moves > 0.1% per 4s bin — reuse: binance trades
    # (records have source field? print keys of first few)
    keys = Counter(tuple(sorted(r.keys())) for r in m[:50])
    print("    record key sets:", dict(keys))

    print("\n[F] COVERAGE — expert scan (LIVE data from expert_scan_results.json)")
    try:
        scan = json.load(open(SCAN))
        print("    keys:", list(scan.keys()))
        res = scan.get("results", [])
        print(f"    {len(res)} candidates")
        for r in res:
            print("   ", json.dumps(r)[:400])
    except Exception as e:
        print("    scan json error:", e)


if __name__ == "__main__":
    main()
