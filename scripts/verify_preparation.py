#!/usr/bin/env python3
"""Integration check of the REAL prepare path on localhost, never a mainnet send."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arb.runtime import Fork, EXECUTOR, LOCAL_OWNER
from arb.live import prepare

candidate = {"loan": "USDC", "other": "WETH", "size_usdc": "300",
    "buy": {"venue": "pancake", "address": "0x72AB388E2E2F6FaceF59E3C3FA2C4E29011c2D38"},
    "sell": {"venue": "uniswap", "address": "0xb4CB800910B228ED3d0834cF79D697127BBB00e5"}}

if __name__ == "__main__":
    with Fork(os.environ.get("BASE_RPC_URL", "https://base-rpc.publicnode.com"), 61989637, 10000000) as fork:
        fork.install()
        result = prepare(fork.rpc.url, EXECUTOR, LOCAL_OWNER, candidate, ".01", ".05")
        result.pop("transaction")
        result["network"] = "localhost historical fork only"
        print(json.dumps(result, indent=2))
