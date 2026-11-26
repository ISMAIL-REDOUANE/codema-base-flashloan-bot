#!/usr/bin/env python3
"""Base arbitrage runner. Scan/watch/prepare are read-only; trade needs --broadcast."""
import argparse
import json
import os
import sys
import time
from decimal import Decimal

from arb.runtime import RPC, scan, Unavailable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan", "watch", "deployment", "prepare", "trade"])
    parser.add_argument("--rpc-url", default=os.environ.get("BASE_RPC_URL", "https://base-rpc.publicnode.com"))
    parser.add_argument("--sizes", default=None, help="position values in USDC, not raw token amounts; omit for the per-route size optimizer")
    parser.add_argument("--size-cap", default="500000", help="optimizer upper bound per trade, USDC (only without --sizes)")
    parser.add_argument("--min-net", default="0.01", help="minimum profit after padded network costs, USDC")
    parser.add_argument("--block", type=int, help="historical snapshot; scan only")
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--iterations", type=int, default=0, help="watch snapshots; zero means until interrupted")
    parser.add_argument("--quotes-only", action="store_true", help="unverified quotes; never a verified opportunity")
    parser.add_argument("--owner", help="public wallet address")
    parser.add_argument("--contract", help="deployed AtomicArbitrage address")
    parser.add_argument("--candidate", help="JSON file containing one candidate row from scan output")
    parser.add_argument("--max-network-cost", help="explicit transaction network cost budget, USDC")
    parser.add_argument("--broadcast", action="store_true", help="explicitly send ONE freshly verified trade")
    parser.add_argument("--key-env", default="CODEMA_PRIVATE_KEY", help="environment variable name; never a key on the command line")
    args = parser.parse_args()
    sizes = [Decimal(x) for x in args.sizes.split(",")] if args.sizes is not None else None
    minimum = Decimal(args.min_net)
    size_cap = Decimal(args.size_cap)
    if sizes is not None and (not sizes or any(not x.is_finite() or x <= 0 or x > 100000 for x in sizes)):
        parser.error("sizes must be finite and between 0 and 100000 USDC")
    if not size_cap.is_finite() or size_cap <= 0:
        parser.error("size-cap must be positive")
    if not minimum.is_finite() or minimum <= 0:
        parser.error("min-net must be positive")
    if args.command == "watch" and args.block is not None:
        parser.error("historical --block is only supported with scan")
    if args.interval <= 0 or args.iterations < 0:
        parser.error("interval must be positive; iterations cannot be negative")
    if args.broadcast and args.command != "trade":
        parser.error("--broadcast is only valid with trade")
    if args.command == "trade" and not args.broadcast:
        parser.error("trade requires explicit --broadcast; use prepare for an unsigned transaction")
    if args.command in ("deployment", "prepare", "trade"):
        if not args.owner:
            parser.error("--owner is required")
        from arb.live import deployment_transaction, prepare, submit
        try:
            if args.command == "deployment":
                result = {"status": "UNSIGNED_DEPLOYMENT", "transaction": deployment_transaction(args.owner)}
            else:
                if not args.contract or not args.candidate or not args.max_network_cost:
                    parser.error("prepare requires --contract, --candidate, --max-network-cost")
                with open(args.candidate) as f:
                    candidate = json.load(f)
                if args.command == "trade":
                    result = submit(args.rpc_url, args.contract, args.owner, candidate,
                                    minimum, args.max_network_cost, args.key_env)
                else:
                    result = prepare(args.rpc_url, args.contract, args.owner, candidate,
                                     minimum, args.max_network_cost)
            print(json.dumps(result))
            return 0
        except Exception as e:
            print(json.dumps({"status": "UNAVAILABLE", "error": str(e) if isinstance(e, Unavailable) else type(e).__name__}), file=sys.stderr)
            return 2
    seen = None
    count = 0
    try:
        while True:
            head = args.block if args.block is not None else int(RPC(args.rpc_url).block()["number"], 16)
            if head != seen:
                result = scan(args.rpc_url, sizes, minimum, head, fork_verify=not args.quotes_only,
                              size_cap_usdc=size_cap)
                result["skipped_blocks_since_previous"] = max(0, result["block"] - seen - 1) if seen is not None else 0
                print(json.dumps(result), flush=True)
                seen = result["block"]
                count += 1
            if args.command == "scan" or (args.iterations and count >= args.iterations):
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        # Avoid dumping request objects, credentials, or RPC URLs in tracebacks.
        print(json.dumps({"status": "UNAVAILABLE", "error": str(e) if isinstance(e, Unavailable) else type(e).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
