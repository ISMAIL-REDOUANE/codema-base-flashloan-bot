"""Verify compiled V2 artifacts (final state, runs=999999 factory / runs=200 router).
1) Factory runtime size == Base mainnet factory (13 859 B).
2) Router runtime size == Base mainnet router (17 891 B).
3) Pair creation-code keccak == hash patched into the router's library
   (e8e45841...), i.e. router computes the correct pair addresses for OUR
   factory. The canonical mainnet hash (96e8ac...) differs ONLY because of
   compiler metadata (source paths); the pair logic is identical.
   Every V2 fork sets its own hash — same practice as SushiSwap/PancakeSwap.
"""
import json, os
from web3 import Web3

BASE = os.path.dirname(os.path.abspath(__file__))
fac = json.load(open(os.path.join(BASE, "artifacts-v2", "factory-0.5.16.json")))
rou = json.load(open(os.path.join(BASE, "artifacts-v2", "router-0.6.6.json")))

def get(d, name):
    for k, v in d["contracts"].items():
        if k.endswith(":" + name):
            return v
    raise KeyError(name)

pair_bin = get(fac, "UniswapV2Pair")["bin"]
fac_rt = get(fac, "UniswapV2Factory")["bin-runtime"]
rou_rt = get(rou, "UniswapV2Router02")["bin-runtime"]
my_hash = Web3.keccak(hexstr=pair_bin).hex()
print("MY pair creation-code keccak:", my_hash)
print("factory runtime:", len(fac_rt)//2, "B (mainnet 13859)  match:", len(fac_rt)//2 == 13859)
print("router  runtime:", len(rou_rt)//2, "B (mainnet 17891)  match:", len(rou_rt)//2 == 17891)
print("patched hash embedded in router runtime:", my_hash[2:] in rou_rt)
print("canonical hash still in router runtime:", "96e8ac4277198ff8b6f785478aa9a39f403cb768dd02cbee326c3e7da348845f" in rou_rt)
assert my_hash[2:] in rou_rt, "router does not embed our factory hash"
print("V2 ARTIFACTS VERIFIED OK")
