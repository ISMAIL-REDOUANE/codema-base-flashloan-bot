#!/usr/bin/env python3
"""Reproduce a HISTORICAL opportunity on a LOCAL Base fork. No mainnet broadcast.

Default run: cold executor (zero balances), the first-trade gas.
--warm: seed 1 wei of USDC + 1 wei of WETH into the executor first (local-fork
impersonation only), so the measured trade is a steady-state trade with warm
balance slots and no first-write SSTORE for the token balances.
"""
import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from eth_abi import encode
from eth_utils import keccak

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arb.runtime import (RPC, Fork, Token, USDC, WETH, MORPHO, EXECUTOR, addr,
                         read_pool, quote, verify_atomic, Unavailable)


def seed_dust(fork):
    """Warm the executor's USDC/WETH balance slots with 1 wei each.

    Local fork only, via Anvil impersonation of real token holders (Morpho for
    USDC, the Uni WETH/USDC pool for WETH). Automine is paused so both seed
    transfers land in ONE block: the trade plan expires after 2 blocks, and two
    separately mined seed blocks would already consume the budget.
    """
    gas_price = 10000000
    which = os.environ.get("SEED_DUST", "both")  # usdc | weth | both (measurement only)
    pairs = {"usdc": ((MORPHO, USDC),),
             "weth": (("0xb4CB800910B228ED3d0834cF79D697127BBB00e5", WETH),),
             "both": ((MORPHO, USDC),
                      ("0xb4CB800910B228ED3d0834cF79D697127BBB00e5", WETH))}[which]
    fork.rpc.request("anvil_setAutomine", [False])
    hashes = []
    try:
        for whale, token in pairs:
            fork.rpc.request("anvil_setBalance", [addr(whale), hex(10 ** 18)])
            fork.rpc.request("anvil_impersonateAccount", [addr(whale)])
            try:
                data = "0x" + (keccak(text="transfer(address,uint256)")[:4]
                               + encode(("address", "uint256"), (addr(EXECUTOR), 1))).hex()
                hashes.append(fork.rpc.request("eth_sendTransaction", [
                    {"from": addr(whale), "to": addr(token), "data": data,
                     "value": "0x0", "gasPrice": hex(gas_price)}]))
            finally:
                fork.rpc.request("anvil_stopImpersonatingAccount", [addr(whale)])
        fork.rpc.request("anvil_mine", [])
        for tx_hash in hashes:
            receipt = fork.rpc.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status != 1:
                raise Unavailable("dust seeding failed")
    finally:
        fork.rpc.request("anvil_setAutomine", [True])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warm", action="store_true",
                        help="seed 1 wei USDC + 1 wei WETH first (steady-state gas)")
    args = parser.parse_args()
    rpc = RPC(os.environ.get("BASE_RPC_URL", "https://base-rpc.publicnode.com"))
    block = 61989637
    header = rpc.block(block)
    buy = read_pool(rpc, "pancake", "0x72AB388E2E2F6FaceF59E3C3FA2C4E29011c2D38", block)
    sell = read_pool(rpc, "uniswap", "0xb4CB800910B228ED3d0834cF79D697127BBB00e5", block)
    token, other = Token("USDC", USDC, 6), Token("WETH", WETH, 18)
    values = {USDC.lower(): Decimal(1), WETH.lower(): sell.spot(WETH) * Decimal(10 ** 12)}
    with Fork(rpc.url, block) as fork:
        fork.install()
        if args.warm:
            seed_dust(fork)
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
        dust = 1 if (args.warm and os.environ.get("SEED_DUST", "both") in ("both", "usdc")) else 0
        # 1 wei USDC seeded in warm mode (usdc/both) stays put; weth-only seeds no USDC.
        assert int(receipt["status"], 16) == 1 and before == after and profit == dust + returned - amount
        gas_used = int(receipt["gasUsed"], 16)
        result.pop("transaction_template")
        result.update({"block": block, "block_hash": header["hash"], "loan_usdc": 300,
            "buy_pool": buy.address, "sell_pool": sell.address,
            "local_receipt_status": int(receipt["status"], 16), "local_gas_used": gas_used,
            "local_gas_used_steady": gas_used if args.warm else None,
            "local_gas_steady_note": ("warm run: 1 wei USDC + 1 wei WETH dust seeded, "
                "warm balance slots, steady-state trade" if args.warm else
                "cold run: fresh executor, zero balances (first-trade gas)"),
            "lender_fully_repaid": before == after, "executor_profit_raw": str(profit),
            "historical_only": True, "broadcast_network": "localhost Anvil only",
            "fees_note": "L1 + operator fees read from Base at the historical block; L2 gas includes 20% gas-limit padding and 25% total-cost margin."})
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
