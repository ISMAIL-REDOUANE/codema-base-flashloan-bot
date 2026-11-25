#!/usr/bin/env python3
"""Reproduce a HISTORICAL opportunity on a LOCAL Base fork. No mainnet broadcast."""
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arb.runtime import (RPC, Fork, Token, USDC, WETH, MORPHO, EXECUTOR, read_pool,
                         quote, verify_atomic)


def main():
    rpc = RPC(os.environ.get("BASE_RPC_URL", "https://base-rpc.publicnode.com"))
    block = 61989637
    header = rpc.block(block)
    buy = read_pool(rpc, "pancake", "0x72AB388E2E2F6FaceF59E3C3FA2C4E29011c2D38", block)
    sell = read_pool(rpc, "uniswap", "0xb4CB800910B228ED3d0834cF79D697127BBB00e5", block)
    token, other = Token("USDC", USDC, 6), Token("WETH", WETH, 18)
    values = {USDC.lower(): Decimal(1), WETH.lower(): sell.spot(WETH) * Decimal(10 ** 12)}
    with Fork(rpc.url, block) as fork:
        fork.install()
        amount = 300 * 10 ** 6
        bought = quote(rpc, buy, USDC, WETH, amount, block)
        returned = quote(rpc, sell, WETH, USDC, bought, block)
        result = verify_atomic(rpc, fork, token, other, buy, sell, amount, bought, returned,
                               values, block, header, Decimal(".01"), int(header["baseFeePerGas"], 16) * 2)
        if result["status"] != "HISTORICAL_VERIFIED":
            raise RuntimeError("historical fixture no longer verifies")
        before = fork.rpc.call(USDC, "balanceOf(address)", ("address",), (MORPHO,))[0]
        tx_hash = fork.rpc.request("eth_sendTransaction", [result["transaction_template"]])
        # Anvil can proxy an early receipt lookup to the upstream archive while
        # its local transaction is still mining. Retry that transient lookup.
        receipt = None
        for _ in range(300):
            try:
                receipt = fork.rpc.request("eth_getTransactionReceipt", [tx_hash])
            except Exception:
                pass
            if receipt:
                break
            time.sleep(.2)
        if not receipt:
            raise RuntimeError("local transaction did not mine within the receipt polling window")
        after = fork.rpc.call(USDC, "balanceOf(address)", ("address",), (MORPHO,))[0]
        profit = fork.rpc.call(USDC, "balanceOf(address)", ("address",), (EXECUTOR,))[0]
        assert int(receipt["status"], 16) == 1 and before == after and profit == returned - amount
        result.pop("transaction_template")
        result.update({"block": block, "block_hash": header["hash"], "loan_usdc": 300,
            "buy_pool": buy.address, "sell_pool": sell.address,
            "local_receipt_status": int(receipt["status"], 16), "local_gas_used": int(receipt["gasUsed"], 16),
            "lender_fully_repaid": before == after, "executor_profit_raw": str(profit),
            "historical_only": True, "broadcast_network": "localhost Anvil only",
            "fees_note": "L1 + operator fees read from Base at the historical block; L2 gas includes 20% gas-limit padding and 25% total-cost margin."})
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
