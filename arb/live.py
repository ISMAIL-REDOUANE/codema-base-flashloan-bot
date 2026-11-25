"""Validate deployed code and prepare transactions. Only submit() signs/sends.

Deployment/approval of a gas budget belongs to the wallet operator. A quote from
the scan is only a route hint: this module re-reads and simulates the REAL contract.
"""
import os
from decimal import Decimal, ROUND_CEILING
from eth_account import Account
from eth_abi import decode, encode

from .runtime import (RPC, MORPHO, WETH, LOCAL_KEY, Unavailable, addr,
    artifact, discover, prices, quote, plan_for, transaction, full_cost)


def deployment_transaction(owner):
    """Unsigned creation transaction, reviewable by the wallet operator."""
    return {"chainId": 8453, "from": addr(owner), "value": "0x0",
            "data": artifact()["bytecode"]["object"] + encode(("address", "address"), (MORPHO, addr(owner))).hex()}


def validate_deployment(rpc, contract, owner, block):
    if int(rpc.request("eth_chainId", []), 16) != 8453:
        raise Unavailable("Base chain 8453 required")
    observed_owner = rpc.call(contract, "owner()", block=block, outputs=("address",))[0]
    observed_lender = rpc.call(contract, "morpho()", block=block, outputs=("address",))[0]
    if observed_owner.lower() != owner.lower() or observed_lender.lower() != MORPHO.lower():
        raise Unavailable("executor owner/lender mismatch")
    # Reconstruct runtime with the correct immutable owner and lender values.
    expected = rpc.request("eth_call", [{"from": addr(owner), "data": deployment_transaction(owner)["data"]}, hex(block)])
    deployed = rpc.request("eth_getCode", [addr(contract), hex(block)])
    if expected.lower() != deployed.lower():
        raise Unavailable("executor bytecode differs from this build")


def prepare(rpc_url, contract, owner, candidate, min_net, max_network_cost):
    """Requote a candidate and simulate deployed code, returning unsigned calldata.

    Never changes a stale template's destination or trusts its old profit amount.
    Costs are conservatively padded and include the complete envelope. The
    wallet MUST revalidate immediately before submission; any included revert
    still consumes gas. A positive simulation is not guaranteed inclusion.
    """
    minimum, budget = Decimal(min_net), Decimal(max_network_cost)
    if not minimum.is_finite() or not budget.is_finite() or minimum <= 0 or budget <= 0:
        raise ValueError("positive finite min-net and max-network-cost are required")
    rpc = RPC(rpc_url)
    header = rpc.block()
    block = int(header["number"], 16)
    validate_deployment(rpc, contract, owner, block)
    tokens, pools, errors = discover(rpc, block)
    valuations = prices(tokens, pools)
    token = next(t for t in tokens if t.symbol == candidate["loan"])
    other = next(t for t in tokens if t.symbol == candidate["other"])
    # Discovery has already validated pool tokens, factory and fee at this exact
    # block. Reuse that evidence instead of fourteen redundant serial RPC calls.
    def selected(leg):
        matches = [p for p in pools if p.venue == leg["venue"] and p.address.lower() == leg["address"].lower()
            and {p.token0.lower(), p.token1.lower()} == {token.address.lower(), other.address.lower()}]
        if len(matches) != 1:
            raise Unavailable("candidate pool unavailable or unsupported by the verified registry")
        return matches[0]
    buy, sell = selected(candidate["buy"]), selected(candidate["sell"])
    if buy.address == sell.address:
        raise Unavailable("identical pools")
    # Use the explicitly selected size, never an unchecked raw integer from a file.
    size = Decimal(candidate["size_usdc"])
    if not size.is_finite() or size <= 0 or size > 100000:
        raise Unavailable("position value outside supported bounds")
    unit = valuations[token.address.lower()] / Decimal(10 ** token.decimals)
    amount = int(size / unit)
    balance = rpc.call(token.address, "balanceOf(address)", ("address",), (MORPHO,), block)[0]
    if amount <= 0 or amount * 2 > balance:
        raise Unavailable("insufficient flash liquidity")
    bought = quote(rpc, buy, token.address, other.address, amount, block)
    returned = quote(rpc, sell, other.address, token.address, bought, block)
    gross = Decimal(returned - amount) * unit
    if gross <= minimum:
        raise Unavailable("requote is below the requested minimum")
    gas_price = max(int(header["baseFeePerGas"], 16) * 2, int(rpc.request("eth_gasPrice", []), 16))
    if gas_price > 2 * 10 ** 9:
        raise Unavailable("gas price exceeds 2 gwei cap")
    floor = int((minimum / unit).to_integral_value(rounding=ROUND_CEILING))
    nonce = int(rpc.request("eth_getTransactionCount", [addr(owner), "pending"]), 16)
    tx = None
    for _ in range(8):
        plan = plan_for(token, other, buy, sell, amount, floor, block, int(header["timestamp"], 16), bought)
        tx = transaction(plan, gas_price, to=contract, sender=owner)
        simulated = decode(("uint256",), bytes.fromhex(rpc.request("eth_call", [tx, hex(block)])[2:]))[0]
        if simulated != returned - amount:
            raise Unavailable("deployed atomic execution differs from exact quotes")
        estimated = int(rpc.request("eth_estimateGas", [tx, hex(block)]), 16)
        tx["gas"] = hex((estimated * 120 + 99) // 100)
        # Fee upper bound avoids relying on the signature of the public fixture.
        costs = full_cost(rpc, tx, int(tx["gas"], 16), valuations[WETH.lower()], block)
        upper_l1 = rpc.call("0x420000000000000000000000000000000000000F", "getL1FeeUpperBound(uint256)",
            ("uint256",), (costs["envelope_bytes"] + 32,), block)[0]
        padded_l1_extra = max(0, upper_l1 - costs["l1_fee_wei"])
        padded_extra = Decimal(padded_l1_extra) / Decimal(10 ** 18) * valuations[WETH.lower()] * Decimal(costs["cost_margin"])
        total = Decimal(costs["total_usdc"]) + padded_extra
        costs.update(total_usdc=str(total), l1_upper_bound_wei=upper_l1)
        if total > budget or gross - total < minimum:
            raise Unavailable("network budget or net profit requirement failed")
        required = int(((total + minimum) / unit).to_integral_value(rounding=ROUND_CEILING))
        if required <= floor:
            break
        floor = required
    else:
        raise Unavailable("fee floor did not converge")
    if rpc.block(block)["hash"] != header["hash"]:
        raise Unavailable("reorg during preparation")
    latest = int(rpc.block()["number"], 16)
    if latest < block or latest - block > 2:
        raise Unavailable("simulation stale; faster/private RPC required")
    native_balance = int(rpc.request("eth_getBalance", [addr(owner), "pending"]), 16)
    worst_fee = int(tx["gas"], 16) * gas_price + max(costs["l1_fee_wei"], upper_l1) + costs["operator_fee_wei"]
    if native_balance < worst_fee:
        raise Unavailable("owner ETH balance cannot cover the transaction")
    if int(rpc.request("eth_getTransactionCount", [addr(owner), "pending"]), 16) != nonce:
        raise Unavailable("owner nonce changed during preparation")
    tx.update(chainId=8453, nonce=hex(nonce))
    return {"status": "UNSIGNED_REVALIDATED", "block": block, "block_hash": header["hash"],
            "expires_block": block + 2, "gross_usdc": str(gross), "net_usdc": str(gross - total),
            "loan_unit_value_usdc": str(unit), "min_profit_raw": str(floor),
            "costs": costs, "eth_price_usdc": str(valuations[WETH.lower()]),
            "transaction": tx}


def submit(rpc_url, contract, owner, candidate, min_net, max_network_cost, key_env):
    """One explicitly requested transaction. Not called by scan, watch, or prepare.

    The caller opts in via the trade --broadcast command and sets an explicit
    gas budget. This is never invoked by default or during market verification.
    """
    key = os.environ.get(key_env)
    if not key:
        raise Unavailable("private key environment variable is unset")
    try:
        account = Account.from_key(key)
    except Exception:
        raise Unavailable("invalid signer key") from None
    if key.lower().removeprefix("0x") == LOCAL_KEY.removeprefix("0x"):
        raise Unavailable("the public Anvil fixture cannot be used on Base")
    if account.address.lower() != owner.lower():
        raise Unavailable("signer does not match the requested owner")
    prepared = prepare(rpc_url, contract, owner, candidate, min_net, max_network_cost)
    rpc = RPC(rpc_url)
    tx = prepared["transaction"]
    signed = account.sign_transaction({"chainId": 8453, "nonce": int(tx["nonce"], 16),
        "to": addr(tx["to"]), "value": 0, "data": tx["data"],
        "gas": int(tx["gas"], 16), "gasPrice": int(tx["gasPrice"], 16)})
    # Check the ACTUAL signed payload's fees against the caller's explicit budget.
    header = rpc.block()
    block = int(header["number"], 16)
    if block < prepared["block"] or block > prepared["expires_block"]:
        raise Unavailable("transaction expired before submission")
    oracle = "0x420000000000000000000000000000000000000F"
    l1 = rpc.call(oracle, "getL1Fee(bytes)", ("bytes",), (bytes(signed.raw_transaction),), block)[0]
    operator = rpc.call(oracle, "getOperatorFee(uint256)", ("uint256",), (int(tx["gas"], 16),), block)[0]
    cost = Decimal(int(tx["gas"], 16) * int(tx["gasPrice"], 16) + l1 + operator) / Decimal(10 ** 18)
    cost *= Decimal(prepared["eth_price_usdc"]) * Decimal("1.25")
    if cost > Decimal(max_network_cost) or Decimal(prepared["gross_usdc"]) - cost < Decimal(min_net):
        raise Unavailable("signed transaction exceeds budget or minimum net")
    unit = Decimal(prepared["loan_unit_value_usdc"])
    if Decimal(prepared["min_profit_raw"]) * unit < cost + Decimal(min_net):
        raise Unavailable("contract profit floor no longer covers network fees; reprepare")
    if rpc.block(prepared["block"])["hash"] != prepared["block_hash"]:
        raise Unavailable("reorg before submission")
    if int(rpc.request("eth_getTransactionCount", [account.address, "pending"]), 16) != int(tx["nonce"], 16):
        raise Unavailable("nonce changed before submission")
    # Final whole-cycle eth_call uses the deployed contract and actual sender.
    pending_result = rpc.request("eth_call", [{k: v for k,v in tx.items() if k not in ("chainId", "nonce")}, "pending"])
    pending_profit = decode(("uint256",), bytes.fromhex(pending_result[2:]))[0]
    pending_net = Decimal(pending_profit) * unit - cost
    if pending_net < Decimal(min_net):
        raise Unavailable("pending atomic profit is below the minimum net")
    if int(rpc.block()["number"], 16) > prepared["expires_block"]:
        raise Unavailable("simulation expired; nothing sent")
    # No retry here: a timeout could mean the sequencer already accepted it.
    # The locally computed hash lets the operator query before ever resubmitting.
    try:
        tx_hash = rpc.request("eth_sendRawTransaction", ["0x" + bytes(signed.raw_transaction).hex()])
    except Exception:
        return {"status": "SUBMISSION_UNKNOWN", "transaction_hash": "0x" + bytes(signed.hash).hex(),
                "message": "Query this hash before retrying; acceptance is unknown."}
    return {"status": "SUBMITTED", "transaction_hash": tx_hash,
            "expected_net_usdc": str(pending_net), "realized_profit": None,
            "message": "Submission is not a receipt. Included reverts consume gas."}
