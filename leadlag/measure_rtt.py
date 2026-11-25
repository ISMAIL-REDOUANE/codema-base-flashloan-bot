"""RTT measurement from this VM (read-only). No keys printed."""
import json, statistics, subprocess, time, urllib.request

def curl_ms(url, method="GET", data=None, n=20):
    times = []
    for _ in range(n):
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{time_total}", "-m", "10"]
        if method == "POST":
            cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", data]
        cmd.append(url)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            t = float(out.stdout.strip()) * 1000
            times.append(t)
        except Exception:
            pass
        time.sleep(0.05)
    times.sort()
    if not times:
        return None
    med = statistics.median(times)
    p95 = times[int(0.95 * len(times)) - 1] if len(times) > 1 else times[0]
    return {"n": len(times), "median_ms": round(med, 1), "p95_ms": round(p95, 1),
            "min_ms": round(times[0], 1), "max_ms": round(times[-1], 1)}

def ws_handshake_ms(url, n=5):
    import asyncio, websockets
    async def one():
        t0 = time.monotonic()
        async with websockets.connect(url, open_timeout=10) as ws:
            t1 = time.monotonic()
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            t2 = time.monotonic()
        return (t1 - t0) * 1000, (t2 - t0) * 1000
    hs, first = [], []
    for _ in range(n):
        try:
            h, f = asyncio.run(one())
            hs.append(h); first.append(f)
        except Exception as e:
            print("WS fail:", type(e).__name__, e)
        time.sleep(0.2)
    if not hs:
        return None
    return {"n": len(hs), "handshake_median_ms": round(statistics.median(hs), 1),
            "first_msg_median_ms": round(statistics.median(first), 1)}

if __name__ == "__main__":
    print("== Binance REST ==")
    print("api.binance.com ping:", curl_ms("https://api.binance.com/api/v3/ping"))
    print("== Base public RPC ==")
    print("mainnet.base.org eth_blockNumber:",
          curl_ms("https://mainnet.base.org", "POST", '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'))
    print("== Polygon drpc ==")
    print("polygon.drpc.org eth_blockNumber:",
          curl_ms("https://polygon.drpc.org", "POST", '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'))
    print("== Binance WS ==")
    print("stream.binance.com:", ws_handshake_ms("wss://stream.binance.com:9443/ws/btcusdt@trade"))
