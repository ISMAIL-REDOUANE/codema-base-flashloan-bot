import json
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from eth_account import Account
from eth_abi import decode, encode
from eth_utils import keccak

from arb import live
from arb.runtime import (LOCAL_KEY, LOCAL_OWNER, RPC, USDC, WETH, Pool, Token, Unavailable,
                         full_cost, optimize_route_size, serialized_envelope, transaction, PLAN_TYPE)
from v3_quote import encode_quote_single


def test_quoter_matches_independent_abi():
    data = encode_quote_single(USDC, WETH, 100, 100_000_000)
    assert data[:4] == keccak(text="quoteExactInputSingle((address,address,uint256,uint24,uint160))")[:4]
    fields = decode(("address", "address", "uint256", "uint24", "uint160"), data[4:])
    assert fields[2:] == (100_000_000, 100, 0)


def test_cost_uses_complete_transaction_and_operator_fee():
    rpc = Mock()
    rpc.call.side_effect = [(1000,), (1500,)]
    tx = {"to": USDC, "data": "0x12345678", "gas": hex(500000), "gasPrice": hex(10000000)}
    result = full_cost(rpc, tx, 500000, Decimal(2000), 123)
    payload = rpc.call.call_args_list[0].args[3][0]
    assert len(payload) > 70
    assert Account.recover_transaction(payload) == LOCAL_OWNER
    assert rpc.call.call_args_list[1].args[1] == "getOperatorFee(uint256)"
    assert result["operator_fee_wei"] == 1500
    expected = Decimal(500000 * 10000000 + 1000 + 1500) / Decimal(10**18) * 2000 * Decimal("1.25")
    assert Decimal(result["total_usdc"]) == expected


def test_cost_oracle_failure_is_not_zero():
    rpc = Mock()
    rpc.call.side_effect = Unavailable("oracle unreachable")
    with pytest.raises(Unavailable):
        full_cost(rpc, {"to": USDC, "data": "0x", "gas": "0x100", "gasPrice": "0x1"}, 256, Decimal(2000), 123)


def test_zero_l1_fee_cannot_validate_opportunity():
    rpc = Mock()
    rpc.call.return_value = (0,)
    with pytest.raises(Unavailable, match="zero"):
        full_cost(rpc, {"to": USDC, "data": "0x", "gas": "0x100", "gasPrice": "0x1"}, 256, Decimal(2000), 123)


def test_small_tolerated_quote_differences_cannot_create_profit():
    # The previous verifier accepted two 0.4 bp errors then kept the analytic
    # +0.00326 net. Exact chained cashflows are negative for this same fixture.
    from leadlag.test_route_verify import synth_cl_state, POOL_A, POOL_B
    import route_verify as rv
    buy = synth_cl_state(POOL_A, 1640, 18, 6, 100)
    sell = synth_cl_state(POOL_B, 1640 * 1.00038, 18, 6, 100)
    seen = []
    def quoter(factory, tin, tout, fee, spacing, amount, block):
        seen.append(amount)
        state = buy if len(seen) == 1 else sell
        actual, _, _ = rv.mono_tick_out(amount, state["liq"], state["sqrt_x96"], fee,
                                        zero_for_one=(len(seen) == 2), tick_spacing=spacing)
        return int(actual * .99996), "independent_fixture"
    with patch.object(rv, "quoter_for_pool", side_effect=quoter):
        result = rv.verify_cycle(POOL_A, POOL_B, WETH, USDC, 100, 1, 123,
                                 states=(buy, sell), decimals=(18, 6), gas_usd=.0024)
    assert result["analytic_net_usd"] > 0
    assert result["net_usd"] < 0
    assert seen[1] == result["quoter_guards"]["buy"]["out_raw"]
    assert result["net_source"] == "chained_onchain_quotes"


def test_legacy_router_quotes_cannot_approve_atomic_execution():
    # Exercise the real run path using a profitable mathematical candidate.
    import executor
    from preflight import PreflightResult
    candidate = Mock(token_address=USDC)
    simulated = Mock(action="EXECUTE", loan_usd=100, provider="morpho", gas_paid_usd=0,
                     symbol="T", spread_pct=1, expected_net_usd=1, gas_usd=.01, reasons=[])
    pf = Mock(status="WIN", block_number=123, net_usd=1, gas_cost_usd=.01)
    with patch.object(executor, "simulate", return_value=simulated), \
         patch.object(executor, "simulate_evm", return_value=pf), \
         patch("preflight.get_block_number", return_value=123):
        result = executor.run([candidate], rpc_url="http://unused", vault_balances={"USDC":1000})
    assert result[0].action == "SKIP"
    assert "atomic" in result[0].reasons[0]


def test_public_fixture_key_cannot_broadcast(monkeypatch):
    monkeypatch.setenv("TEST_SIGNER", LOCAL_KEY)
    with patch.object(live, "prepare") as prepare:
        with pytest.raises(Unavailable, match="public Anvil"):
            live.submit("unused", USDC, LOCAL_OWNER, {}, ".01", ".10", "TEST_SIGNER")
    prepare.assert_not_called()


def test_unset_signer_cannot_broadcast(monkeypatch):
    monkeypatch.delenv("TEST_SIGNER", raising=False)
    with pytest.raises(Unavailable, match="unset"):
        live.submit("unused", USDC, LOCAL_OWNER, {}, ".01", ".10", "TEST_SIGNER")


def test_expired_transaction_cannot_reach_broadcast(monkeypatch):
    key = Account.create()
    monkeypatch.setenv("TEST_SIGNER", key.key.hex())
    prepared = {"block": 100, "expires_block": 102,
        "transaction": {"to": USDC, "data": "0x1234", "gas": "0x80000", "gasPrice": "0x989680", "nonce": "0x0"}}
    rpc = Mock()
    rpc.block.return_value = {"number": hex(103)}
    with patch.object(live, "prepare", return_value=prepared), patch.object(live, "RPC", return_value=rpc):
        with pytest.raises(Unavailable, match="expired"):
            live.submit("unused", USDC, key.address, {}, ".01", ".10", "TEST_SIGNER")
    rpc.request.assert_not_called()


def test_one_explicit_submission_and_no_automatic_retry(monkeypatch):
    key = Account.create()
    monkeypatch.setenv("TEST_SIGNER", key.key.hex())
    prepared = {"block": 100, "block_hash": "0xabc", "expires_block": 102,
        "gross_usdc": "1", "net_usdc": ".99", "eth_price_usdc": "2000",
        "loan_unit_value_usdc": ".000001", "min_profit_raw": "30000",
        "transaction": {"to": USDC, "from": key.address, "data": "0x1234",
                        "gas": "0x80000", "gasPrice": "0x989680", "nonce": "0x0", "chainId": 8453}}
    rpc = Mock()
    rpc.block.return_value = {"number": hex(100), "hash": "0xabc"}
    rpc.call.side_effect = [(1000,), (0,)]
    def request(method, params):
        if method == "eth_getTransactionCount": return "0x0"
        if method == "eth_call": return "0x" + encode(("uint256",), (1000000,)).hex()
        if method == "eth_sendRawTransaction": raise Unavailable("timeout after acceptance possible")
        raise AssertionError(method)
    rpc.request.side_effect = request
    with patch.object(live, "prepare", return_value=prepared), patch.object(live, "RPC", return_value=rpc):
        result = live.submit("unused", USDC, key.address, {}, ".01", ".10", "TEST_SIGNER")
    assert result["status"] == "SUBMISSION_UNKNOWN"
    assert len(result["transaction_hash"]) == 66
    assert sum(c.args[0] == "eth_sendRawTransaction" for c in rpc.request.call_args_list) == 1


# --- Size optimizer: mock CL quoter with a constant-product curve -----------
# The fake quoter models the same curve as MockCLPool kind=2 (see
# test_atomic.py::test_mock_cpamm_curve_and_trade, which validates the curve
# on-chain): out = eff * reserve_out / (reserve_in + eff), eff = amount net
# of the pool fee. The chained gross has a known interior optimum, computed
# in-test by a fine grid over the same formula.

class FakeCLQuoter:
    """Mock RPC whose batched calls are CPAMM quotes (synthetic, not a market)."""
    def __init__(self, curves):
        # curves: {(token_in, token_out, fee): (reserve_in_raw, reserve_out_raw)}
        self.curves = curves
        self.batches = 0

    def calls(self, specs, block):
        self.batches += 1
        out = []
        for _quoter, _sig, _types, values, _outputs in specs:
            tin, tout, amount, fee, _sqrt = values[0]
            r_in, r_out = self.curves[(tin.lower(), tout.lower(), fee)]
            eff = amount * (1_000_000 - fee) // 1_000_000
            out.append((eff * r_out // (r_in + eff) if eff > 0 else 0, 0, 0, 0))
        return out


def _cpamm_fixture(edge_bps=50):
    usdc, weth = Token("USDC", USDC, 6), Token("WETH", WETH, 18)
    buy = Pool("pancake", "0x" + "11" * 20, WETH, USDC, 100, 0, 10 ** 18)
    sell = Pool("uniswap", "0x" + "22" * 20, WETH, USDC, 100, 0, 10 ** 18)
    buy_price, sell_price = 2000, 2000 + edge_bps // 5  # edge in $/WETH
    curves = {
        (USDC.lower(), WETH.lower(), 100): (2_000_000 * 10 ** 6, 1000 * 10 ** 18),
        (WETH.lower(), USDC.lower(), 100): (1000 * 10 ** 18, sell_price * 1000 * 10 ** 6),
    }
    valuations = {USDC.lower(): Decimal(1), WETH.lower(): Decimal(buy_price)}
    return usdc, weth, buy, sell, curves, valuations


def _cpamm_gross(curves, size_usdc):
    amount = int(size_usdc * 10 ** 6)
    eff = amount * 999900 // 1_000_000
    bought = eff * (1000 * 10 ** 18) // (2_000_000 * 10 ** 6 + eff)
    eff2 = bought * 999900 // 1_000_000
    sell_price = curves[(WETH.lower(), USDC.lower(), 100)][1] // (1000 * 10 ** 6)
    returned = eff2 * (sell_price * 1000 * 10 ** 6) // (1000 * 10 ** 18 + eff2)
    return Decimal(returned - amount) / Decimal(10 ** 6)


def _true_optimum(curves, lo=Decimal(10), hi=Decimal(500000)):
    best = (lo, _cpamm_gross(curves, lo))
    for i in range(4001):
        size = lo * (hi / lo) ** (Decimal(i) / Decimal(4000))
        gross = _cpamm_gross(curves, size)
        if gross > best[1]:
            best = (size, gross)
    return best


def test_optimizer_finds_known_cpamm_optimum():
    usdc, weth, buy, sell, curves, valuations = _cpamm_fixture()
    rpc = FakeCLQuoter(curves)
    result = optimize_route_size(rpc, usdc, weth, buy, sell, 2_000_000 * 10 ** 6,
                                 valuations, 123)
    true_size, true_gross = _true_optimum(curves)
    assert result["optimal_size_usdc"] is not None
    found_size = Decimal(result["optimal_size_usdc"])
    found_gross = Decimal(result["optimal_gross_usdc"])
    assert abs(found_size - true_size) / true_size <= Decimal("0.10")
    assert abs(found_gross - true_gross) / true_gross <= Decimal("0.05")
    assert found_gross > 0
    assert result["evaluated"] <= 30  # 12 + 9 + 9 batched sizes, not ~80 round trips
    assert rpc.batches <= 6  # 2 batches per level (buys, then sells)


def test_optimizer_respects_balance_cap():
    usdc, weth, buy, sell, curves, valuations = _cpamm_fixture()
    rpc = FakeCLQuoter(curves)
    true_size, _ = _true_optimum(curves)
    # Unconstrained optimum (~$2.5k) is above the available/2 bound of $2,000,
    # so the optimum must sit on the bound.
    assert true_size > 2000
    result = optimize_route_size(rpc, usdc, weth, buy, sell, 4_000 * 10 ** 6,
                                 valuations, 123)
    found = Decimal(result["optimal_size_usdc"])
    assert found <= Decimal(2000) and found >= Decimal(2000) * Decimal("0.99")


def test_optimizer_respects_size_cap():
    usdc, weth, buy, sell, curves, valuations = _cpamm_fixture()
    rpc = FakeCLQuoter(curves)
    true_size, _ = _true_optimum(curves)
    cap = (true_size / 2).quantize(Decimal("1"))
    result = optimize_route_size(rpc, usdc, weth, buy, sell, 200_000_000 * 10 ** 6,
                                 valuations, 123, size_cap_usdc=cap)
    found = Decimal(result["optimal_size_usdc"])
    assert found <= cap and found >= cap * Decimal("0.99")


def test_optimizer_returns_none_when_range_empty():
    usdc, weth, buy, sell, curves, valuations = _cpamm_fixture()
    rpc = FakeCLQuoter(curves)
    assert optimize_route_size(rpc, usdc, weth, buy, sell, 10 * 10 ** 6,
                               valuations, 123) is None  # available/2 = 5 < min 10


def test_optimizer_picks_smallest_size_when_no_edge():
    usdc, weth, buy, sell, curves, valuations = _cpamm_fixture(edge_bps=0)
    rpc = FakeCLQuoter(curves)
    result = optimize_route_size(rpc, usdc, weth, buy, sell, 2_000_000 * 10 ** 6,
                                 valuations, 123)
    assert Decimal(result["optimal_gross_usdc"]) < 0  # fees + impact, no edge
    assert Decimal(result["optimal_size_usdc"]) == Decimal(10)  # least-bad size
