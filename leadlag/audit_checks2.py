"""audit_checks2.py — ROOT-CAUSE AUDIT, part 2 (read-only).

G. measurements.jsonl: Binance move sizes, DEX gap, reversal rate.
H. paper entries: direction distribution (LONG vs SHORT), SHORT executability,
   QuoterV2 q1k anchor vs mono-tick model (model validation).
I. Live RTT probes (read-only): Binance vision depth, Alchemy eth_call,
   public Base RPC eth_call. Alchemy URL loaded in-process, NEVER printed.
J. GeckoTerminal top pools Base: venue share (Aerodrome/Pancake/V4/UniV3).
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

LEAD = Path(str(Path(__file__).resolve().parents[1] / 'leadlag'))
ENTRIES = LEAD / "paper_entries.jsonl"
MEAS = LEAD / "measurements.jsonl"


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


# ---------------------------------------------------------------- G. lead-lag data
print("=" * 78)
print("[G] measurements.jsonl — Binance moves, DEX gap, reversals (LIVE)")
m = load_jsonl(MEAS)
bin_trades = [r for r in m if r.get("src") == "binance"]
base_q = [r for r in m if r.get("src") == "base"]
poly_q = [r for r in m if r.get("src") == "polygon"]
print(f"    records: binance={len(bin_trades)} base={len(base_q)} "
      f"polygon={len(poly_q)} errors={len(m)-len(bin_trades)-len(base_q)-len(poly_q)}")
# Binance trade arrival staleness (LIVE): trade_T_ms vs t_ms
stale = [(r["t_ms"] - r["trade_T_ms"]) / 1000.0 for r in bin_trades
         if "trade_T_ms" in r and "t_ms" in r]
if stale:
    print(f"    Binance trade staleness (t_ms - trade_T_ms): med={pct(stale,50):.2f}s "
          f"p95={pct(stale,95):.2f}s max={max(stale):.2f}s n={len(stale)}")
rtts = [r["rtt_ms"] for r in bin_trades if "rtt_ms" in r]
if rtts:
    print(f"    Binance REST rtt_ms: med={pct(rtts,50):.0f} p95={pct(rtts,95):.0f} "
          f"max={max(rtts):.0f}")
# Binance price moves per symbol, 2s and 4s bins (LIVE)
for sym in ("BTCUSDT", "ETHUSDT"):
    px = sorted([(r["t_ms"], r["px"]) for r in bin_trades
                 if r.get("sym") == sym and r.get("px")], key=lambda x: x[0])
    if len(px) < 10:
        print(f"    {sym}: only {len(px)} trades")
        continue
    # 2s bins: last price per bin
    bins2, bins4 = {}, {}
    for t, p in px:
        bins2[int(t // 2000)] = p
        bins4[int(t // 4000)] = p
    def moves(bins):
        ks = sorted(bins)
        return [abs(bins[ks[i+1]] / bins[ks[i]] - 1) * 100 for i in range(len(ks)-1)]
    m2, m4 = moves(bins2), moves(bins4)
    print(f"    {sym}: {len(px)} trades | |mv 2s| med={pct(m2,50):.4f}% "
          f"p95={pct(m2,95):.4f}% max={max(m2):.4f}% "
          f"| |mv 4s| med={pct(m4,50):.4f}% p95={pct(m4,95):.4f}% max={max(m4):.4f}% "
          f"| 2s moves >0.1%: {sum(1 for v in m2 if v>0.1)}/{len(m2)}")
    # reversal: a 2s move >0.05% followed by opposite move >50% of it next bin?
    rev = tot = 0
    ks = sorted(bins2)
    for i in range(len(ks)-2):
        d1 = bins2[ks[i+1]]/bins2[ks[i]] - 1
        d2 = bins2[ks[i+2]]/bins2[ks[i+1]] - 1
        if abs(d1)*100 > 0.05:
            tot += 1
            if d1*d2 < 0 and abs(d2) > 0.5*abs(d1):
                rev += 1
    print(f"        2s moves >0.05%: {tot}, of which >50% reversed next bin: {rev} "
          f"({100*rev/max(1,tot):.0f}%)")

# ---------------------------------------------------------------- H. entries
print("\n[H] paper entries — directions, SHORT, model validation (LIVE)")
recs = load_jsonl(ENTRIES)
dirs = Counter(r.get("direction") for r in recs if r.get("kind") == "eval")
print("    direction counts:", dict(dirs))
notes = Counter("SHORT" in str(r.get("decision_reason")) for r in recs)
# q1k anchor vs mono-tick: compare logged q1k impact_pct with analytic impact
# (we just count how many q1k anchors exist and their impact range)
q_imp = []
for r in recs:
    for fee, q in (r.get("q1k") or {}).items():
        if q.get("impact_pct") is not None:
            q_imp.append((r["pair"], fee, q["impact_pct"]))
print(f"    q1k anchors logged: {len(q_imp)}")
if q_imp:
    vals = [v for _, _, v in q_imp]
    print(f"    q1k $1000 impact_pct: med={pct(vals,50):.4f}% p95={pct(vals,95):.4f}% "
          f"max={max(vals):.4f}% min={min(vals):.4f}%")
    by_pair = defaultdict(list)
    for p, f, v in q_imp:
        by_pair[(p, f)].append(v)
    for k in sorted(by_pair):
        print(f"        {k[0]} fee {k[1]}: n={len(by_pair[k])} "
              f"med impact={pct(by_pair[k],50):.4f}%")
# cycle time from t_ms deltas (LIVE)
ts = sorted(r["t_ms"] for r in recs if r.get("kind") == "eval")
dts = [(ts[i+1]-ts[i])/1000.0 for i in range(len(ts)-1) if 0 < ts[i+1]-ts[i] < 30000]
# per-pair cycle: evals come 4 per cycle; use first record of each cycle
print(f"    eval t_ms span: {(ts[-1]-ts[0])/1000:.0f}s over {len(ts)} evals")

# ---------------------------------------------------------------- I. live RTT
print("\n[I] LIVE RTT probes (read-only, just now)")
def http_get(url, timeout=15):
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "audit-probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return (time.monotonic()-t0)*1000.0, len(body)

def rpc_time(url, timeout=15):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber",
                          "params": []}).encode()
    t0 = time.monotonic()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    return (time.monotonic()-t0)*1000.0

for _ in range(3):
    try:
        ms, n = http_get("https://data-api.binance.vision/api/v3/depth?symbol=ETHUSDT&limit=100")
        print(f"    Binance vision depth ETHUSDT: {ms:.0f} ms ({n} bytes)")
    except Exception as e:
        print("    Binance vision depth ERROR:", e)
for _ in range(3):
    try:
        print(f"    Base public eth_blockNumber: {rpc_time('https://mainnet.base.org'):.0f} ms")
    except Exception as e:
        print("    Base public RPC ERROR:", e)
# Alchemy URL loaded in-process, never printed
try:
    txt = Path(str(Path(__file__).resolve().parents[1] / 'config.yaml')).read_text()
    mm = re.search(r'rpc_url:\s*"([^"]+)"', txt)
    if mm:
        for _ in range(3):
            print(f"    Alchemy Base eth_blockNumber: {rpc_time(mm.group(1)):.0f} ms")
except Exception as e:
    print("    Alchemy probe ERROR:", type(e).__name__)

# ---------------------------------------------------------------- J. GeckoTerminal
print("\n[J] GeckoTerminal top pools Base — venue share (LIVE, just now)")
try:
    req = urllib.request.Request(
        "https://api.geckoterminal.com/api/v2/networks/base/pools?page=1",
        headers={"User-Agent": "audit-probe", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        gt = json.load(r)
    pools = gt.get("data", [])
    print(f"    page 1: {len(pools)} pools")
    by_dex = Counter()
    vol_dex = defaultdict(float)
    res_dex = defaultdict(float)
    for p in pools:
        a = p.get("attributes", {})
        rel = p.get("relationships", {})
        dex = None
        # dex id lives in relationships.dex.data.id in v2
        try:
            dex = rel.get("dex", {}).get("data", {}).get("id")
        except Exception:
            pass
        name = a.get("name", "")
        by_dex[dex or name.split(" / ")[0]] += 1
        try:
            vol_dex[dex or "unknown"] += float(a.get("volume_usd", {}).get("h24") or 0)
            res_dex[dex or "unknown"] += float(a.get("reserve_in_usd") or 0)
        except Exception:
            pass
    tot_vol = sum(vol_dex.values()) or 1
    tot_res = sum(res_dex.values()) or 1
    print("    by dex (count / vol24 share / reserve share):")
    for d, c in by_dex.most_common(12):
        print(f"      {d}: n={c} vol24={100*vol_dex[d]/tot_vol:.1f}% "
              f"reserve={100*res_dex[d]/tot_res:.1f}%")
    # also print raw names to see dex naming
    print("    sample names:", [p["attributes"]["name"] for p in pools[:8]])
except Exception as e:
    print("    GeckoTerminal ERROR:", type(e).__name__, str(e)[:200])
