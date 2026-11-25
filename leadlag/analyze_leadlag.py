"""Offline analysis of leadlag measurements.jsonl. Pure math, no network."""
from pathlib import Path
import json, math, statistics, sys
from collections import defaultdict

F = str(Path(__file__).resolve().parents[1] / 'leadlag/measurements.jsonl')
CLOCK_SKEW_MS = 1190.0  # Binance serverTime - local mid, median of 10 samples (see report)
BIN_S = 2.0

recs = [json.loads(l) for l in open(F) if l.strip()]
print(f"records: {len(recs)}")
by_src = defaultdict(int)
for r in recs:
    by_src[r["src"]] += 1
print("by src:", dict(by_src))
errs = [r for r in recs if "error" in r]
print(f"errors: {len(errs)} ({len(errs)/max(1,len(recs))*100:.1f}%)")

# --- build 2 s-bin series (price = last observation in bin) ---
def series(src, key, pxkey="px", tkey="t_ms", tcorr=0.0):
    pts = {}
    for r in recs:
        if r.get("src") != src or key not in str(r.get("sym", r.get("pair", ""))):
            continue
        if "px" not in r:
            continue
        t = (r[tkey] + tcorr) / 1000.0
        b = int(t // BIN_S)
        pts[b] = r["px"]
    return pts

bin_btc = series("binance", "BTCUSDT", tkey="trade_T_ms", tcorr=-CLOCK_SKEW_MS)
bin_eth = series("binance", "ETHUSDT", tkey="trade_T_ms", tcorr=-CLOCK_SKEW_MS)
base_weth = series("base", "WETH/USDC")
base_btc = series("base", "cbBTC/USDC")
poly_weth = series("polygon", "WETH/USDC.e")
for name, s in [("binance BTC", bin_btc), ("binance ETH", bin_eth), ("base WETH", base_weth),
                ("base cbBTC", base_btc), ("polygon WETH", poly_weth)]:
    if s:
        ks = sorted(s)
        print(f"{name}: {len(s)} bins, {ks[0]*BIN_S:.0f}..{ks[-1]*BIN_S:.0f}s, px0={s[ks[0]]:.2f} px1={s[ks[-1]]:.2f}")

def logrets(s):
    ks = sorted(s)
    return {k: math.log(s[k] / s[k - 1]) for k in ks if (k - 1) in s}

def xcorr(a, b, maxlag=5):
    """corr of a[t] vs b[t+lag] (lag>0 => b follows a). Returns {lag_bins: corr}."""
    ra, rb = logrets(a), logrets(b)
    out = {}
    for lag in range(-maxlag, maxlag + 1):
        xs, ys = [], []
        for t, va in ra.items():
            if (t + lag) in rb:
                xs.append(va); ys.append(rb[t + lag])
        if len(xs) >= 10:
            mx, my = statistics.mean(xs), statistics.mean(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
            out[lag] = round(num / den, 3) if den else None
    return out

def beta(a, b, lag=0):
    ra, rb = logrets(a), logrets(b)
    xs, ys = [], []
    for t, va in ra.items():
        if (t + lag) in rb:
            xs.append(va); ys.append(rb[t + lag])
    if len(xs) < 10:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(cov / var, 3) if var else None

print("\n== cross-correlation Binance -> DEX (lag in 2s bins; +lag = DEX follows Binance) ==")
for nm, a, b in [("ETH bin->base WETH", bin_eth, base_weth),
                 ("BTC bin->base cbBTC", bin_btc, base_btc),
                 ("ETH bin->poly WETH", bin_eth, poly_weth)]:
    print(nm, "xcorr:", xcorr(a, b), "beta@lag0:", beta(a, b, 0), "beta@lag1:", beta(a, b, 1))

# --- moves: Binance 2 s move > 0.1% -> DEX gap at +2 s / +4 s ---
def moves(a, b, thresh=0.001):
    ra = logrets(a)
    res = []
    for t, va in sorted(ra.items()):
        if abs(va) < thresh:
            continue
        gaps = {}
        for h in (1, 2):
            if t in a and (t + h) in b:
                gaps[h] = (a[t] - b[t + h]) / b[t + h]  # >0: Binance above DEX (DEX lagging up-move)
        res.append({"t": t, "bin_move_pct": round(va * 100, 3), "gaps_pct": {str(k): round(v * 100, 3) for k, v in gaps.items()}})
    return res

print("\n== Binance moves >0.1% per 2s bin, DEX gap afterwards (gap>0 means DEX still below Binance) ==")
for nm, a, b in [("ETH -> base WETH", bin_eth, base_weth),
                 ("BTC -> base cbBTC", bin_btc, base_btc),
                 ("ETH -> poly WETH", bin_eth, poly_weth)]:
    mv = moves(a, b)
    n = len(mv)
    if not n:
        print(nm, ": no moves >0.1%")
        continue
    for h in ("1", "2"):
        gs = [m["gaps_pct"][h] for m in mv if h in m["gaps_pct"]]
        if gs:
            over = sum(1 for g in gs if abs(g) > 0.10)
            print(f"{nm} +{int(h)*2}s: n={len(gs)} moves, gap median {statistics.median(gs):+.3f}%, "
                  f"|gap|>0.1%: {over}/{len(gs)} ({over/max(1,len(gs))*100:.0f}%), max|gap| {max(abs(g) for g in gs):.3f}%")
    for m in mv[:12]:
        print("   ", m)

# --- Binance REST staleness + quote health ---
rtts = [r["rtt_ms"] for r in recs if r.get("src") == "binance" and "rtt_ms" in r]
if rtts:
    print(f"\nBinance REST aggTrades RTT: n={len(rtts)} median {statistics.median(rtts):.0f} ms p95 {sorted(rtts)[int(0.95*len(rtts))-1]:.0f} ms")
    lags = [r["t_ms"] - (r["trade_T_ms"] - CLOCK_SKEW_MS) for r in recs
            if r.get("src") == "binance" and "trade_T_ms" in r]
    if lags:
        print(f"trade receipt lag (local recv - corrected trade time): median {statistics.median(lags):.0f} ms p95 {sorted(lags)[int(0.95*len(lags))-1]:.0f} ms")
print("done")
