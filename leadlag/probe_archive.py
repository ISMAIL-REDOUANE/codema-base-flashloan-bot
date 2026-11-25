#!/usr/bin/env python3
"""Probe: archive access on Alchemy Base + pool factory/token0 (read-only)."""
import json, re, urllib.request
from pathlib import Path

txt = Path(str(Path(__file__).resolve().parents[1] / 'config.yaml')).read_text()
RPC = re.search(r'rpc_url:\s*"([^"]+)"', txt).group(1)

def call(method, params, timeout=25):
    p = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=p, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if "error" in out:
        raise RuntimeError(str(out["error"]))
    return out["result"]

def sel(sig):
    from web3 import Web3
    return "0x" + Web3.keccak(text=sig)[:4].hex()

cur = int(call("eth_blockNumber", []), 16)
print("current block:", cur)
print("scan block 62077712 is", cur - 62077712, "blocks ago (~%.1f h)" % ((cur - 62077712) * 0.2 / 3600))

for label, blk in [("scan block", 62077712),
                   ("24h before scan", 62077712 - 432000),
                   ("72h before scan", 62077712 - 1296000)]:
    try:
        r = call("eth_call", [{"to": "0xeC3c3755b9DED4a2960ef50C9b48C1694CE274C2",
                               "data": sel("slot0()")}, hex(blk)])
        print(f"{label} {blk}: slot0 OK ({len(r)} chars)")
    except Exception as e:
        print(f"{label} {blk}: FAIL: {str(e)[:180]}")

# pool factory() + token0() at latest (immutable) for the two route pools
for name, addr in [("BUY Aero", "0xeC3c3755b9DED4a2960ef50C9b48C1694CE274C2"),
                   ("SELL Aerodrome", "0x42d4a22CaD0F5a49681a5715cE994Af73A43B76b")]:
    try:
        fac = call("eth_call", [{"to": addr, "data": sel("factory()")}, "latest"])
        print(name, addr[:12], "factory:", "0x" + fac[-40:])
    except Exception as e:
        print(name, "factory() FAIL:", str(e)[:120])
    try:
        t0 = call("eth_call", [{"to": addr, "data": sel("token0()")}, "latest"])
        print(name, "token0:", "0x" + t0[-40:])
    except Exception as e:
        print(name, "token0() FAIL:", str(e)[:120])

# eth_getLogs test: Swap events on buy pool, 100-block window at scan block
try:
    logs = call("eth_getLogs", [{"fromBlock": hex(62077712 - 50), "toBlock": hex(62077712),
                                 "address": "0xeC3c3755b9DED4a2960ef50C9b48C1694CE274C2",
                                 "topics": ["0x" + __import__("web3").Web3.keccak(text="Swap(address,address,int256,int256,uint160,uint128,int24)").hex()]}])
    print("eth_getLogs 100 blocks @ scan:", len(logs), "Swap logs")
except Exception as e:
    print("eth_getLogs FAIL:", str(e)[:180])
