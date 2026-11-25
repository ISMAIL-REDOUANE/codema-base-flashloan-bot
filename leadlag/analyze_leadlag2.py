"""Round 2: 4 s bins (fixes Polygon 4 s cadence), standing gap distribution, move sizes."""
from pathlib import Path
import json, math, statistics
from collections import defaultdict

F = str(Path(__file__).resolve().parents[1] / 'leadlag/measurements.jsonl')
CLOCK_SKEW_MS = 1190.0
BIN_S = 4.0

recs = [json.loads(l) for l in open(F) if l.strip()]

def series(src, key, tkey="t_ms", tcorr=0.0):
    pts = {}
    for r in recs:
        if r.get("src") != src or key not in str(r.get("sym", r.get("pair", ""))):
            continue
        if "px" not in r:
            continue
        b = int(((r[tkey] + tcorr) / 1000.0) // BIN_S)
        pts[b] = r["px"]
    return pts

bin_btc = series("binance", "BTCUSDT", tkey="trade_T_ms", tcorr=-CLOCK_SKEW_MS)
bin_eth = series("binance", "ETHUSDT", tkey="trade_T_ms", tcorr=-CLOCK_SKEW_MS)
base_weth = series("base", "WETH/USDC")
base_btc = series("base", "cbBTC/USDC")
poly_weth = series("polygon", "WETH/USDC.e")

def logrets(s):
    ks = sorted(s)
    return {k: math.log(s[k] / s[k - 1]) for k in ks if (k - 1) in s}

def xcorr(a, b, maxlag=4):
    ra, rb = logrets(a), logrets(b)
    out = {}
    for lag in range(-maxlag, maxlag + 1):
        xs = [va for t, va in ra.items() if (t + lag) in rb]
        ys = [rb[t + lag] for t in ra if (t + lag) in rb]
        if len(xs) >= 10:
            mx, my = statistics.mean(xs), statistics.mean(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
            out[lag] = round(num / den, 3) if den else None
    return out

def beta(a, b, lag):
    ra, rb = logrets(a), logrets(b)
    xs = [va for t, va in ra.items() if (t + lag) in rb]
    ys = [rb[t + lag] for t in ra if (t + lag) in rb]
    if len(xs) < 10:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var, 3) if var else None

print("== 4 s bins, xcorr Binance -> DEX (lag in 4 s bins) ==")
for nm, a, b in [("ETH bin->base WETH", bin_eth, base_weth),
                 ("BTC bin->base cbBTC", bin_btc, base_btc),
                 ("ETH bin->poly WETH", bin_eth, poly_weth)]:
    print(nm, "xcorr:", xcorr(a, b), "beta@0:", beta(a, b, 0), "beta@+1:", beta(a, b, 1))

print("\n== move sizes (Binance, per 4 s bin) ==")
for nm, s in [("BTC", bin_btc), ("ETH", bin_eth)]:
    r = [abs(v) * 100 for v in logrets(s).values()]
    r.sort()
    print(f"{nm}: n={len(r)} max {r[-1]:.3f}% p95 {r[int(0.95*len(r))-1]:.3f}% p50 {statistics.median(r):.3f}%  n>0.1%: {sum(1 for x in r if x>0.1)}")

print("\n== standing gap (Binance px - DEX px)/DEX px, aligned 4 s bins ==")
for nm, a, b in [("ETH: bin vs base WETH", bin_eth, base_weth),
                 ("BTC: bin vs base cbBTC", bin_btc, base_btc),
                 ("ETH: bin vs poly WETH", bin_eth, poly_weth)]:
    gs = [(a[k] - b[k]) / b[k] * 100 for k in sorted(a) if k in b]
    if gs:
        gs_sorted = sorted(gs)
        print(f"{nm}: n={len(gs)} median {statistics.median(gs):+.3f}% p5 {gs_sorted[int(0.05*len(gs))]:+.3f}% "
              f"p95 {gs_sorted[int(0.95*len(gs))-1]:+.3f}% min {min(gs):+.3f}% max {max(gs):+.3f}% "
              f"|gap|>0.1%: {sum(1 for g in gs if abs(g)>0.1)}/{len(gs)}")
