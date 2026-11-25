"""Lead-lag measurement: Binance (REST, Vision endpoint) vs Base/Polygon DEX quotes.
Read-only. No keys, no accounts, no trading. Logs to measurements.jsonl.
Duration default 720 s. Threads: Binance 2 s, Base 2 s, Polygon 4 s."""
from pathlib import Path
import json, sys, threading, time, urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'polygon'))
from v3_quote import quote_v3_onchain

OUT = str(Path(__file__).resolve().parents[1] / 'leadlag/measurements.jsonl')
DURATION_S = float(sys.argv[1]) if len(sys.argv) > 1 else 720.0
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CBBTC_BASE = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
BASE_RPC = "https://mainnet.base.org"
POLY_RPC = "https://polygon.drpc.org"

lock = threading.Lock()
stop_at = time.time() + DURATION_S

def log(rec):
    rec["t_ms"] = int(time.time() * 1000)
    with lock:
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")

def http_get_json(url, timeout=10):
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "leadlag-measurement"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, (time.monotonic() - t0) * 1000

def binance_thread():
    while time.time() < stop_at:
        t_start = time.time()
        try:
            for sym in ("BTCUSDT", "ETHUSDT"):
                try:
                    trades, rtt = http_get_json(
                        f"https://data-api.binance.vision/api/v3/aggTrades?symbol={sym}&limit=5")
                    if trades:
                        last = trades[-1]
                        log({"src": "binance", "sym": sym, "px": float(last["p"]),
                             "qty": float(last["q"]), "trade_T_ms": int(last["T"]),
                             "rtt_ms": round(rtt, 1), "n_trades": len(trades)})
                except Exception as e:
                    log({"src": "binance", "sym": sym, "error": type(e).__name__ + ": " + str(e)[:100]})
        except Exception as e:
            log({"src": "binance", "error": type(e).__name__ + ": " + str(e)[:100]})
        dt = 2.0 - (time.time() - t_start)
        if dt > 0:
            time.sleep(dt)

def base_thread():
    while time.time() < stop_at:
        t_start = time.time()
        try:
            blk = None
            try:
                payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}).encode()
                req = urllib.request.Request(BASE_RPC, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    blk = int(json.loads(r.read().decode())["result"], 16)
            except Exception:
                pass
            for name, tok, dec, fee in (("WETH", WETH_BASE, 18, 500), ("cbBTC", CBBTC_BASE, 8, 500)):
                q = quote_v3_onchain(USDC_BASE, tok, fee, 1000_000_000, BASE_RPC, timeout=12)
                if q.source == "quoter_v2_onchain":
                    px = 1000.0 / (q.amount_out / 10 ** dec)
                    log({"src": "base", "pair": name + "/USDC", "fee": fee, "px": px, "block": blk})
                else:
                    log({"src": "base", "pair": name + "/USDC", "fee": fee, "error": str(q.error)[:100]})
        except Exception as e:
            log({"src": "base", "error": type(e).__name__ + ": " + str(e)[:100]})
        dt = 2.0 - (time.time() - t_start)
        if dt > 0:
            time.sleep(dt)

def polygon_thread():
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(POLY_RPC, request_kwargs={"timeout": 12}))
    qabi = [{"name": "quoteExactInputSingle",
             "outputs": [{"type": "uint256"}, {"type": "uint160"}, {"type": "uint32"}, {"type": "uint256"}],
             "inputs": [{"type": "tuple", "components": [
                 {"type": "address", "name": "tokenIn"}, {"type": "address", "name": "tokenOut"},
                 {"type": "uint256", "name": "amountIn"}, {"type": "uint24", "name": "fee"},
                 {"type": "uint160", "name": "sqrtPriceLimitX96"}]}],
             "stateMutability": "nonpayable", "type": "function"}]
    q = w3.eth.contract(address=Web3.to_checksum_address("0x61fFE014bA17989E743c5F6cB21bF9697530B21e"), abi=qabi)
    USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
    while time.time() < stop_at:
        t_start = time.time()
        try:
            amt = 1000_000_000
            out = q.functions.quoteExactInputSingle(
                (Web3.to_checksum_address(USDCE), Web3.to_checksum_address(WETH), amt, 500, 0)).call()[0]
            px = 1000.0 / (out / 1e18)
            log({"src": "polygon", "pair": "WETH/USDC.e", "fee": 500, "px": px, "block": w3.eth.block_number})
        except Exception as e:
            log({"src": "polygon", "pair": "WETH/USDC.e", "error": type(e).__name__ + ": " + str(e)[:100]})
        dt = 4.0 - (time.time() - t_start)
        if dt > 0:
            time.sleep(dt)

if __name__ == "__main__":
    print(f"lead-lag stream: {DURATION_S:.0f}s -> {OUT}", flush=True)
    ts = [threading.Thread(target=binance_thread, daemon=True),
          threading.Thread(target=base_thread, daemon=True),
          threading.Thread(target=polygon_thread, daemon=True)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("done", flush=True)
