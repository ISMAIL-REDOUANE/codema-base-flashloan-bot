"""Round 2: Binance Vision endpoints + Alchemy Base (URL loaded in-process, NEVER printed)."""
import json, re, statistics, subprocess, time

def curl_ms(url, method="GET", data=None, n=20, label=""):
    times, codes = [], []
    for _ in range(n):
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}", "-m", "10"]
        if method == "POST":
            cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", data]
        cmd.append(url)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            code, t = out.stdout.strip().split()
            codes.append(code); times.append(float(t) * 1000)
        except Exception:
            pass
        time.sleep(0.05)
    times.sort()
    return {"endpoint": label, "n": len(times), "http_codes": sorted(set(codes)),
            "median_ms": round(statistics.median(times), 1),
            "p95_ms": round(times[int(0.95*len(times))-1], 1) if len(times) > 1 else None,
            "min_ms": round(times[0], 1), "max_ms": round(times[-1], 1)}

def ws_handshake_ms(url, n=5):
    import asyncio, websockets
    async def one():
        t0 = time.monotonic()
        async with websockets.connect(url, open_timeout=10) as ws:
            t1 = time.monotonic()
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            t2 = time.monotonic()
        return (t1-t0)*1000, (t2-t0)*1000, json.loads(msg)
    hs, first, sample = [], [], None
    for _ in range(n):
        try:
            h, f, m = asyncio.run(one())
            hs.append(h); first.append(f)
            if sample is None: sample = {k: m.get(k) for k in ("e", "s", "E", "p")}
        except Exception as e:
            print("WS fail:", type(e).__name__, str(e)[:120])
        time.sleep(0.2)
    if not hs: return None
    return {"n": len(hs), "handshake_median_ms": round(statistics.median(hs), 1),
            "first_msg_median_ms": round(statistics.median(first), 1), "sample_msg": sample}

if __name__ == "__main__":
    print(curl_ms("https://data-api.binance.vision/api/v3/ping", label="data-api.binance.vision ping"))
    print(curl_ms("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", label="data-api.binance.vision ticker"))
    # Alchemy Base: load URL from config.yaml in-process, never print it
    cfg = open("../config.yaml").read()
    m = re.search(r'rpc_url:\s*"([^"]+)"', cfg)
    alchemy = m.group(1)
    print(curl_ms(alchemy, "POST", '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}', label="alchemy-base eth_blockNumber"))
    print("WS data-stream.binance.vision:", ws_handshake_ms("wss://data-stream.binance.vision/ws/btcusdt@trade"))
