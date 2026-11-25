"""Pinned-block quotes and complete atomic fork simulation. No public-chain sends."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, getcontext
from pathlib import Path

from eth_abi import decode, encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from web3 import Web3

getcontext().prec = 70
ROOT = Path(__file__).resolve().parents[1]
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
ORACLE = "0x420000000000000000000000000000000000000F"
EXECUTOR = to_checksum_address(f"0x{0xc0deaa0001:040x}")
# Public Anvil fixture, used ONLY to serialize a fee estimate, never broadcast.
LOCAL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
LOCAL_OWNER = Account.from_key(LOCAL_KEY).address
VENUES = {
    "uniswap": {"factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
                "quoter": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
                "fees": [100, 500, 3000, 10000], "kind": 0},
    "pancake": {"factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
                "quoter": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
                "fees": [100, 500, 2500, 10000], "kind": 1},
}
TOKENS = {"USDC": USDC, "WETH": WETH, "cbBTC": CBBTC}
LEG_TYPE = "(address,address,address,uint8,uint256)"
PLAN_TYPE = f"(address,uint256,{LEG_TYPE},{LEG_TYPE},uint256,uint256,uint256)"


class Unavailable(RuntimeError):
    """Missing evidence: never a positive execution decision."""


class RPC:
    def __init__(self, url):
        self.w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
        self.url = url

    def request(self, method, params):
        out = self.w3.provider.make_request(method, params)
        if "error" in out:
            # Do not echo credentials from provider exceptions or URLs.
            raise Unavailable(f"{method}: {out['error'].get('message', 'RPC error')[:250]}")
        if "result" not in out:
            raise Unavailable(f"{method}: missing result")
        return out["result"]

    def call(self, to, signature, types=(), values=(), block="latest", outputs=("uint256",)):
        data = keccak(text=signature)[:4] + encode(types, values)
        raw = self.request("eth_call", [{"to": to_checksum_address(to), "data": "0x" + data.hex()}, tag(block)])
        return decode(outputs, bytes.fromhex(raw[2:]))

    def calls(self, calls, block):
        """Pinned JSON-RPC batches, matched by id; errors stay attached to each call."""
        results = []
        for start in range(0, len(calls), 80):
            group = calls[start:start+80]
            payload = []
            for i, (to, signature, types, values, outputs) in enumerate(group):
                data = keccak(text=signature)[:4] + encode(types, values)
                payload.append({"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [
                    {"to": addr(to), "data": "0x" + data.hex()}, tag(block)]})
            request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "codema-atomic/1"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    rows = json.load(response)
            except Exception:
                raise Unavailable("batch RPC unavailable") from None
            if not isinstance(rows, list):
                raise Unavailable("provider does not support JSON-RPC batches")
            indexed = {x.get("id"): x for x in rows}
            if len(indexed) != len(group):
                raise Unavailable("incomplete batch response")
            for i, call in enumerate(group):
                row = indexed.get(i, {})
                try:
                    if "error" in row:
                        raise Unavailable("on-chain batch call reverted")
                    results.append(decode(call[4], bytes.fromhex(row["result"][2:])))
                except Exception:
                    results.append(Unavailable("on-chain batch call unavailable"))
        return results

    def block(self, block="latest"):
        out = self.request("eth_getBlockByNumber", [tag(block), False])
        if not out:
            raise Unavailable("block not available")
        return out


def tag(block):
    return hex(block) if isinstance(block, int) else block


def addr(value):
    return to_checksum_address(value)


@dataclass(frozen=True)
class Token:
    symbol: str
    address: str
    decimals: int


@dataclass(frozen=True)
class Pool:
    venue: str
    address: str
    token0: str
    token1: str
    fee: int  # millionths, NOT basis points
    sqrt_price: int
    liquidity: int

    def spot(self, token_in):
        p = Decimal(self.sqrt_price) ** 2 / Decimal(2 ** 192)
        return p if self.token0.lower() == token_in.lower() else 1 / p


def read_pool(rpc, venue, pool, block, expected_tokens=None, expected_fee=None):
    spec = VENUES[venue]
    t0 = rpc.call(pool, "token0()", block=block, outputs=("address",))[0]
    t1 = rpc.call(pool, "token1()", block=block, outputs=("address",))[0]
    factory = rpc.call(pool, "factory()", block=block, outputs=("address",))[0]
    fee = rpc.call(pool, "fee()", block=block)[0]
    if factory.lower() != spec["factory"].lower():
        raise Unavailable("unrecognized pool factory")
    registered = rpc.call(factory, "getPool(address,address,uint24)",
                          ("address", "address", "uint24"), (t0, t1, fee), block, ("address",))[0]
    if registered.lower() != pool.lower():
        raise Unavailable("pool is not registered by its factory")
    if expected_tokens and {t0.lower(), t1.lower()} != {t.lower() for t in expected_tokens}:
        raise Unavailable("pool token mismatch")
    if expected_fee is not None and fee != expected_fee:
        raise Unavailable("pool fee mismatch")
    # Both supported slot0 ABIs begin with sqrtPriceX96, tick. Decode just that prefix.
    slot = rpc.request("eth_call", [{"to": addr(pool), "data": "0x" + keccak(text="slot0()")[:4].hex()}, tag(block)])
    sqrt_price = decode(("uint160",), bytes.fromhex(slot[2:])[:32])[0]
    liquidity = rpc.call(pool, "liquidity()", block=block)[0]
    if not sqrt_price or not liquidity:
        raise Unavailable("empty or uninitialized pool")
    return Pool(venue, addr(pool), addr(t0), addr(t1), fee, sqrt_price, liquidity)


def discover(rpc, block):
    if int(rpc.request("eth_chainId", []), 16) != 8453:
        raise Unavailable("this configuration requires Base chain 8453")
    decimals = rpc.calls([(a, "decimals()", (), (), ("uint256",)) for a in TOKENS.values()], block)
    if any(isinstance(x, Exception) for x in decimals):
        raise Unavailable("token decimals unavailable")
    tokens = [Token(s, a, d[0]) for (s, a), d in zip(TOKENS.items(), decimals)]
    jobs = [(v, a, b, f) for i, a in enumerate(tokens) for b in tokens[i+1:]
            for v, spec in VENUES.items() for f in spec["fees"]]

    registered = rpc.calls([(VENUES[v]["factory"], "getPool(address,address,uint24)",
        ("address", "address", "uint24"), (a.address, b.address, fee), ("address",)) for v,a,b,fee in jobs], block)
    errors, known, reads = [], [], []
    def error(job, message):
        v,a,b,fee = job
        return {"venue": v, "pair": f"{a.symbol}/{b.symbol}", "fee": fee, "error": message}
    for job, value in zip(jobs, registered):
        if isinstance(value, Exception):
            errors.append(error(job, "factory lookup unavailable"))
            continue
        pool = value[0]
        if not int(pool, 16):
            continue
        known.append((job, pool))
        for signature, out in [("token0()", "address"), ("token1()", "address"), ("factory()", "address"),
                               ("fee()", "uint256"), ("slot0()", "uint160"), ("liquidity()", "uint256")]:
            # ABI decoders accept trailing tuple words in slot0.
            reads.append((pool, signature, (), (), (out,)))
    values = rpc.calls(reads, block)
    pools = []
    for i, (job, address) in enumerate(known):
        v,a,b,fee = job
        row = values[i*6:(i+1)*6]
        if any(isinstance(x, Exception) for x in row):
            errors.append(error(job, "pool state unavailable"))
            continue
        t0,t1,factory,actual_fee,sqrt_price,liq = [x[0] for x in row]
        if ({t0.lower(),t1.lower()} != {a.address.lower(),b.address.lower()}
                or factory.lower() != VENUES[v]["factory"].lower() or actual_fee != fee):
            errors.append(error(job, "pool identity mismatch"))
            continue
        if not sqrt_price or not liq:
            errors.append(error(job, "empty or uninitialized pool"))
            continue
        pools.append(Pool(v, addr(address), addr(t0), addr(t1), fee, sqrt_price, liq))
    return tokens, pools, errors


def prices(tokens, pools):
    """USDC accounting numeraire; no claim that the stablecoin always equals one USD."""
    result = {USDC.lower(): Decimal(1)}
    usdc = next(t for t in tokens if t.address.lower() == USDC.lower())
    for token in tokens:
        if token.address.lower() in result:
            continue
        pair = [p for p in pools if {p.token0.lower(), p.token1.lower()} == {USDC.lower(), token.address.lower()}]
        if not pair:
            raise Unavailable(f"no verified USDC valuation pool for {token.symbol}")
        # Same token pair: raw liquidity is comparable; choose the deepest active pool.
        pool = max(pair, key=lambda p: p.liquidity)
        result[token.address.lower()] = pool.spot(token.address) * Decimal(10 ** token.decimals) / Decimal(10 ** usdc.decimals)
    return result


def quote(rpc, pool, token_in, token_out, amount, block):
    data = keccak(text="quoteExactInputSingle((address,address,uint256,uint24,uint160))")[:4]
    data += encode(("(address,address,uint256,uint24,uint160)",), ((token_in, token_out, amount, pool.fee, 0),))
    raw = rpc.request("eth_call", [{"to": VENUES[pool.venue]["quoter"], "data": "0x" + data.hex()}, tag(block)])
    values = decode(("uint256", "uint160", "uint32", "uint256"), bytes.fromhex(raw[2:]))
    if values[0] <= 0:
        raise Unavailable("zero quoter output")
    return values[0]


def quote_spec(pool, token_in, token_out, amount):
    return (VENUES[pool.venue]["quoter"], "quoteExactInputSingle((address,address,uint256,uint24,uint160))",
            ("(address,address,uint256,uint24,uint160)",), ((token_in, token_out, amount, pool.fee, 0),),
            ("uint256", "uint160", "uint32", "uint256"))


def artifact(name="AtomicArbitrage", source="AtomicArbitrage.sol"):
    path = ROOT / "out" / source / f"{name}.json"
    if not path.exists():
        raise Unavailable("compiled contract missing; run npm ci && npm run build")
    return json.loads(path.read_text())


def anvil_binary():
    candidates = [os.environ.get("ANVIL_BIN"), shutil.which("anvil"),
                  str(ROOT / "node_modules/@foundry-rs/anvil-linux-amd64/bin/anvil"),
                  str(ROOT / "node_modules/.bin/anvil")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise Unavailable("Anvil missing; npm ci, or set ANVIL_BIN")


class Fork:
    """All writes in this class go to our own localhost child process only."""
    def __init__(self, rpc_url=None, block=None, gas_price=None):
        self.process = None
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        args = [anvil_binary(), "--host", "127.0.0.1", "--port", str(port), "--silent"]
        if rpc_url:
            args += ["--fork-url", rpc_url, "--fork-block-number", str(block), "--chain-id", "8453",
                     "--disable-min-priority-fee"]
        if gas_price is not None:
            args += ["--gas-price", str(gas_price)]
        # Do not log command lines: a private RPC URL could contain credentials.
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.rpc = RPC(f"http://127.0.0.1:{port}")
        for _ in range(300):
            if self.process.poll() is not None:
                self.close()
                raise Unavailable("Anvil exited during startup")
            try:
                self.rpc.block()
                break
            except Exception:
                time.sleep(.1)
        else:
            self.close()
            raise Unavailable("Anvil startup timed out")

    def install(self, lender=MORPHO):
        compiled = artifact()
        creation = compiled["bytecode"]["object"] + encode(("address", "address"), (lender, LOCAL_OWNER)).hex()
        runtime = self.rpc.request("eth_call", [{"from": LOCAL_OWNER, "data": creation}, "latest"])
        self.rpc.request("anvil_setCode", [addr(EXECUTOR), runtime])
        self.rpc.request("anvil_setBalance", [LOCAL_OWNER, hex(10 ** 21)])

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def plan_for(token, other, buy, sell, amount, min_profit, block, timestamp, bought=0, slippage_bps=1):
    def leg(pool, tin, tout, floor):
        return (pool.address, tin, tout, VENUES[pool.venue]["kind"], floor)
    return (token.address, amount,
            leg(buy, token.address, other.address, bought * (10000 - slippage_bps) // 10000),
            leg(sell, other.address, token.address, amount + min_profit),
            min_profit, timestamp + 30, block + 2)


def calldata(plan):
    return "0x" + (keccak(text=f"execute({PLAN_TYPE})")[:4] + encode((PLAN_TYPE,), (plan,))).hex()


def transaction(plan, gas_price, gas_limit=1200000, to=EXECUTOR, sender=LOCAL_OWNER):
    return {"from": addr(sender), "to": addr(to), "data": calldata(plan),
            "value": "0x0", "gas": hex(gas_limit), "gasPrice": hex(gas_price)}


def serialized_envelope(tx, nonce=0, chain_id=8453):
    """Complete signed envelope for getL1Fee; this public fixture is never sent."""
    signed = Account.sign_transaction({"chainId": chain_id, "nonce": nonce,
        "to": addr(tx["to"]), "value": 0, "data": tx["data"],
        "gas": int(tx["gas"], 16), "gasPrice": int(tx["gasPrice"], 16)}, LOCAL_KEY)
    return bytes(signed.raw_transaction)


def full_cost(rpc, tx, gas_used, eth_price, block, margin=Decimal("1.25")):
    envelope = serialized_envelope(tx)
    l1 = rpc.call(ORACLE, "getL1Fee(bytes)", ("bytes",), (envelope,), block)[0]
    if l1 <= 0:
        raise Unavailable("L1 oracle returned zero; fee evidence unavailable")
    gas_price = int(tx["gasPrice"], 16)
    l2 = gas_used * gas_price
    # Let the pinned oracle apply the network's current operator-fee formula.
    # Missing method/error is unavailable evidence, never a silent zero.
    operator = rpc.call(ORACLE, "getOperatorFee(uint256)", ("uint256",), (gas_used,), block)[0]
    total = Decimal(l1 + l2 + operator) / Decimal(10 ** 18) * eth_price * margin
    return {"gas_units": gas_used, "gas_price_wei": gas_price, "l1_fee_wei": l1,
            "operator_fee_wei": operator, "envelope_bytes": len(envelope),
            "cost_margin": str(margin), "total_usdc": str(total)}


def verify_atomic(rpc, fork, token, other, buy, sell, amount, bought, returned,
                  valuations, block, header, min_net, gas_price):
    unit_value = valuations[token.address.lower()] / Decimal(10 ** token.decimals)
    gross = Decimal(returned - amount) * unit_value
    provisional = plan_for(token, other, buy, sell, amount, 0, block, int(header["timestamp"], 16), bought)
    tx = transaction(provisional, gas_price)
    result = fork.rpc.request("eth_call", [tx, "latest"])
    profit = decode(("uint256",), bytes.fromhex(result[2:]))[0]
    if profit != returned - amount:
        raise Unavailable("full-cycle output differs from chained quoters")
    estimated = int(fork.rpc.request("eth_estimateGas", [tx]), 16)
    tx["gas"] = hex((estimated * 120 + 99) // 100)
    costs = full_cost(rpc, tx, int(tx["gas"], 16), valuations[WETH.lower()], block)
    needed = int(((Decimal(costs["total_usdc"]) + min_net) / unit_value).to_integral_value(rounding=ROUND_CEILING))
    final_plan = plan_for(token, other, buy, sell, amount, needed, block, int(header["timestamp"], 16), bought)
    final_tx = transaction(final_plan, gas_price, int(tx["gas"], 16))
    # Encoding the final profit floor changes the compressed L1 data cost. Reprice
    # until the floor covers the actual envelope, then simulate that exact calldata.
    for _ in range(8):
        costs = full_cost(rpc, final_tx, int(final_tx["gas"], 16), valuations[WETH.lower()], block)
        required = int(((Decimal(costs["total_usdc"]) + min_net) / unit_value).to_integral_value(rounding=ROUND_CEILING))
        if required <= needed:
            break
        needed = required
        final_plan = plan_for(token, other, buy, sell, amount, needed, block, int(header["timestamp"], 16), bought)
        final_tx = transaction(final_plan, gas_price, int(tx["gas"], 16))
    else:
        raise Unavailable("fee floor did not converge")
    net = gross - Decimal(costs["total_usdc"])
    if net < min_net:
        return {"status": "BELOW_MIN_NET", "gross_usdc": str(gross), "net_usdc": str(net), "costs": costs}
    final_profit = decode(("uint256",), bytes.fromhex(fork.rpc.request("eth_call", [final_tx, "latest"])[2:]))[0]
    if final_profit != profit:
        raise Unavailable("final guarded transaction output mismatch")
    # Hash check catches reorgs while the fork and quotes were being prepared.
    if rpc.block(block)["hash"] != header["hash"]:
        raise Unavailable("block reorg during verification")
    latest = int(rpc.block()["number"], 16)
    return {"status": "HISTORICAL_VERIFIED" if latest - block > 2 else "SIMULATED_OPPORTUNITY",
            "gross_usdc": str(gross), "net_usdc": str(net), "costs": costs,
            "profit_raw": str(final_profit), "min_profit_raw": str(needed),
            "simulation_block": block, "expires_block": block + 2,
            "transaction_template": final_tx,
            "deployment_required": True}


def scan(rpc_url, sizes, min_net=Decimal("0.01"), block=None, max_routes=None, fork_verify=True):
    started = time.monotonic()
    rpc = RPC(rpc_url)
    header = rpc.block(block if block is not None else "latest")
    block = int(header["number"], 16)
    tokens, pools, errors = discover(rpc, block)
    valuations = prices(tokens, pools)
    gas_price = max(int(header.get("baseFeePerGas", "0x0"), 16) * 2,
                    int(rpc.request("eth_gasPrice", []), 16))
    if gas_price > 2 * 10 ** 9:
        raise Unavailable("gas price exceeds 2 gwei budget")
    quotes = []
    route_count = 0
    below_spot = 0
    fork = None
    jobs = []
    balances = rpc.calls([(t.address, "balanceOf(address)", ("address",), (MORPHO,), ("uint256",)) for t in tokens], block)
    if any(isinstance(x, Exception) for x in balances):
        raise Unavailable("Morpho inventory unavailable")
    balances = {t.address.lower(): x[0] for t,x in zip(tokens,balances)}
    try:
        for token in tokens:
            for other in tokens:
                if token == other:
                    continue
                group = [p for p in pools if {p.token0.lower(), p.token1.lower()} == {token.address.lower(), other.address.lower()}]
                for buy in group:
                    for sell in group:
                        if buy == sell:
                            continue
                        route_count += 1
                        upper = buy.spot(token.address) * sell.spot(other.address)
                        upper *= Decimal(1000000 - buy.fee) * Decimal(1000000 - sell.fee) / Decimal(10 ** 12)
                        # Each independent exact-input CL swap has worse execution
                        # than its current marginal price. This is an upper bound.
                        if upper <= 1:
                            below_spot += 1
                            continue
                        if max_routes is not None and len(jobs) >= max_routes:
                            continue
                        available = balances[token.address.lower()]
                        for size in sizes:
                            amount = int(size / valuations[token.address.lower()] * Decimal(10 ** token.decimals))
                            if amount <= 0 or amount * 2 > available:
                                continue
                            jobs.append((token, other, buy, sell, amount, size))
        # All buys in one batch stage, then all sells from their EXACT outputs.
        # Deduplicate identical buys shared by several sell venues.
        buy_specs = list(dict.fromkeys(quote_spec(buy, token.address, other.address, amount)
            for token,other,buy,sell,amount,size in jobs))
        buy_results = dict(zip(buy_specs, rpc.calls(buy_specs, block)))
        sell_specs = []
        for token,other,buy,sell,amount,size in jobs:
            result = buy_results[quote_spec(buy, token.address, other.address, amount)]
            if not isinstance(result, Exception) and result[0] > 0:
                sell_specs.append(quote_spec(sell, other.address, token.address, result[0]))
        sell_specs = list(dict.fromkeys(sell_specs))
        sell_results = dict(zip(sell_specs, rpc.calls(sell_specs, block)))
        for token,other,buy,sell,amount,size in jobs:
            row = {"loan": token.symbol, "other": other.symbol,
                                   "buy": asdict(buy), "sell": asdict(sell), "size_usdc": str(size),
                                   "amount_raw": str(amount), "block": block}
            try:
                result = buy_results[quote_spec(buy, token.address, other.address, amount)]
                if isinstance(result, Exception) or result[0] <= 0:
                    raise Unavailable("buy quote unavailable")
                bought = result[0]
                result = sell_results[quote_spec(sell, other.address, token.address, bought)]
                if isinstance(result, Exception) or result[0] <= 0:
                    raise Unavailable("sell quote unavailable")
                returned = result[0]
                gross = Decimal(returned - amount) / Decimal(10 ** token.decimals) * valuations[token.address.lower()]
                row.update(gross_usdc=str(gross), bought_raw=str(bought), returned_raw=str(returned), status="CHAINED_QUOTE_LOSS")
                if gross > 0:
                    row["status"] = "UNVERIFIED_CANDIDATE"
                    if fork_verify:
                        if fork is None:
                            fork = Fork(rpc_url, block)
                            fork.install()
                        row.update(verify_atomic(rpc, fork, token, other, buy, sell, amount, bought, returned,
                                                 valuations, block, header, min_net, gas_price))
            except Exception as e:
                row.update(status="UNAVAILABLE", error=str(e) if isinstance(e, Unavailable) else type(e).__name__)
            quotes.append(row)
    finally:
        if fork:
            fork.close()
    latest = int(rpc.block()["number"], 16)
    if latest < block:
        raise Unavailable("RPC head is behind the verified block")
    if rpc.block(block)["hash"] != header["hash"]:
        raise Unavailable("snapshot block reorged during scan")
    return {"block": block, "block_hash": header["hash"], "accounting_unit": "USDC",
            "elapsed_seconds": round(time.monotonic() - started, 3), "latest_block": latest,
            "snapshot_age_blocks": latest - block,
            "pools": len(pools), "routes": route_count, "routes_below_spot_breakeven": below_spot,
            "discovery_errors": errors, "sizes_usdc": [str(x) for x in sizes],
            "min_net_usdc": str(min_net), "mode": "read_only",
            "quotes": quotes, "profitable": sum(q["status"] in ("HISTORICAL_VERIFIED", "SIMULATED_OPPORTUNITY") for q in quotes),
            "coverage": "Pinned block snapshots, Uni V3 and Pancake V3 majors only. No intra-block coverage."}
