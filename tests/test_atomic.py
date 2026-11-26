"""Executable local-EVM invariants, with explicitly synthetic prices."""
import pytest
from eth_abi import decode
from arb.runtime import Fork, artifact, calldata, LOCAL_OWNER, PLAN_TYPE, transaction


@pytest.fixture(scope="module")
def market():
    with Fork() as fork:
        w3 = fork.rpc.w3
        def deploy(name, *args):
            a = artifact(name, "AtomicMocks.sol" if name != "AtomicArbitrage" else "AtomicArbitrage.sol")
            factory = w3.eth.contract(abi=a["abi"], bytecode=a["bytecode"]["object"])
            receipt = w3.eth.wait_for_transaction_receipt(factory.constructor(*args).transact({"from": LOCAL_OWNER}))
            return w3.eth.contract(address=receipt.contractAddress, abi=a["abi"])
        loan = deploy("MockToken", "LOAN")
        mid = deploy("MockToken", "MID")
        lender = deploy("MockMorpho")
        buy = deploy("MockCLPool", loan.address, mid.address, 2, 1, 0)
        sell = deploy("MockCLPool", loan.address, mid.address, 51, 100, 1)
        loss = deploy("MockCLPool", loan.address, mid.address, 49, 100, 1)
        atomic = deploy("AtomicArbitrage", lender.address, LOCAL_OWNER)
        for token in (loan, mid):
            for target in (lender, buy, sell, loss):
                token.functions.mint(target.address, 10 ** 24).transact({"from": LOCAL_OWNER})
        # Existing balances must survive a failed/unprofitable trade.
        loan.functions.mint(atomic.address, 123456).transact({"from": LOCAL_OWNER})
        mid.functions.mint(atomic.address, 77).transact({"from": LOCAL_OWNER})
        yield fork, loan, mid, lender, buy, sell, loss, atomic


def plan(m, losing=False, **changes):
    fork, loan, mid, lender, buy, sell, loss, atomic = m
    h = fork.rpc.w3.eth.get_block("latest")
    values = {"loan": loan.address, "amount": 1000000,
              "buy": (buy.address, loan.address, mid.address, 0, 1990000),
              "sell": ((loss if losing else sell).address, mid.address, loan.address, 1, 1),
              "profit": 10000, "deadline": h.timestamp + 100, "last": h.number + 100}
    values.update(changes)
    return tuple(values.values())


def test_mixed_venue_full_repayment_and_inventory(market):
    fork, loan, mid, lender, buy, sell, loss, atomic = market
    lender_before = loan.functions.balanceOf(lender.address).call()
    existing = loan.functions.balanceOf(atomic.address).call()
    assert atomic.functions.execute(plan(market)).call({"from": LOCAL_OWNER}) == 20000
    receipt = fork.rpc.w3.eth.wait_for_transaction_receipt(atomic.functions.execute(plan(market)).transact({"from": LOCAL_OWNER}))
    assert receipt.status == 1
    assert loan.functions.balanceOf(lender.address).call() == lender_before
    assert loan.functions.balanceOf(atomic.address).call() == existing + 20000
    assert mid.functions.balanceOf(atomic.address).call() == 77
    assert loan.functions.allowance(atomic.address, lender.address).call() == 0


def test_loss_reverts_without_subsidy(market):
    fork, loan, _, lender, _, _, _, atomic = market
    before = loan.functions.balanceOf(atomic.address).call()
    with pytest.raises(Exception, match="profit"):
        atomic.functions.execute(plan(market, losing=True)).call({"from": LOCAL_OWNER})
    assert loan.functions.balanceOf(atomic.address).call() == before


@pytest.mark.parametrize("callback,args", [
    ("onMorphoFlashLoan", (1, b"")),
    ("uniswapV3SwapCallback", (1, -1, b"")),
    ("pancakeV3SwapCallback", (1, -1, b"")),
])
def test_unrequested_callbacks_rejected(market, callback, args):
    atomic = market[-1]
    with pytest.raises(Exception, match="callback"):
        getattr(atomic.functions, callback)(*args).call({"from": LOCAL_OWNER})


@pytest.mark.parametrize("changes,reason", [
    ({"deadline": 0}, "expired"), ({"last": 0}, "expired"),
    ({"amount": 0}, "amount"), ({"profit": 30000}, "profit"),
])
def test_transaction_guards(market, changes, reason):
    with pytest.raises(Exception, match=reason):
        market[-1].functions.execute(plan(market, **changes)).call({"from": LOCAL_OWNER})


@pytest.mark.parametrize("attack,reason", [(1, "input budget"), (2, "partial fill")])
def test_swap_input_budget(market, attack, reason):
    fork, _, _, _, buy, _, _, atomic = market
    buy.functions.setAttack(attack).transact({"from": LOCAL_OWNER})
    try:
        with pytest.raises(Exception, match=reason):
            atomic.functions.execute(plan(market)).call({"from": LOCAL_OWNER})
    finally:
        buy.functions.setAttack(0).transact({"from": LOCAL_OWNER})


def test_independent_abi_encoding(market):
    p = plan(market)
    atomic = market[-1]
    assert calldata(p) == atomic.encode_abi("execute", args=[p])
    # The runtime's generic transaction succeeds against the actual deployed contract.
    tx = transaction(p, 2000000000, to=atomic.address)
    raw = market[0].rpc.request("eth_call", [tx, "latest"])
    assert decode(("uint256",), bytes.fromhex(raw[2:]))[0] == 20000


def test_mock_cpamm_curve_and_trade():
    """MockCLPool kind=2 is a constant-product curve (concave in size).

    Validates the curve the size-optimizer tests model: a $300 loan through a
    buy pool priced $2,000 and a sell pool priced $2,010 returns exactly the
    CPAMM prediction, and the lender is repaid. Synthetic prices, not a market.
    """
    with Fork() as fork:
        w3 = fork.rpc.w3
        def deploy(name, *args):
            a = artifact(name, "AtomicMocks.sol" if name != "AtomicArbitrage" else "AtomicArbitrage.sol")
            factory = w3.eth.contract(abi=a["abi"], bytecode=a["bytecode"]["object"])
            receipt = w3.eth.wait_for_transaction_receipt(factory.constructor(*args).transact({"from": LOCAL_OWNER}))
            return w3.eth.contract(address=receipt.contractAddress, abi=a["abi"])
        loan = deploy("MockToken", "LOAN")
        mid = deploy("MockToken", "MID")
        lender = deploy("MockMorpho")
        buy = deploy("MockCLPool", loan.address, mid.address, 1, 1, 2)
        sell = deploy("MockCLPool", mid.address, loan.address, 1, 1, 2)
        buy.functions.setReserves(2_000_000 * 10 ** 18, 1000 * 10 ** 18).transact({"from": LOCAL_OWNER})
        sell.functions.setReserves(1000 * 10 ** 18, 2_010_000 * 10 ** 18).transact({"from": LOCAL_OWNER})
        atomic = deploy("AtomicArbitrage", lender.address, LOCAL_OWNER)
        for token in (loan, mid):
            for target in (lender, buy, sell):
                token.functions.mint(target.address, 10 ** 24).transact({"from": LOCAL_OWNER})
        amount = 300 * 10 ** 18
        expected_buy = amount * (1000 * 10 ** 18) // (2_000_000 * 10 ** 18 + amount)
        expected_sell = expected_buy * (2_010_000 * 10 ** 18) // (1000 * 10 ** 18 + expected_buy)
        expected_profit = expected_sell - amount
        assert expected_profit > 0
        h = w3.eth.get_block("latest")
        values = {"loan": loan.address, "amount": amount,
                  "buy": (buy.address, loan.address, mid.address, 1, expected_buy * 9999 // 10000),
                  "sell": (sell.address, mid.address, loan.address, 1, amount + expected_profit // 2),
                  "profit": expected_profit // 2, "deadline": h.timestamp + 100, "last": h.number + 100}
        p = tuple(values.values())
        assert atomic.functions.execute(p).call({"from": LOCAL_OWNER}) == expected_profit
        lender_before = loan.functions.balanceOf(lender.address).call()
        receipt = w3.eth.wait_for_transaction_receipt(
            atomic.functions.execute(p).transact({"from": LOCAL_OWNER}))
        assert receipt.status == 1
        assert loan.functions.balanceOf(lender.address).call() == lender_before
        assert loan.functions.balanceOf(atomic.address).call() == expected_profit


def test_fork_runtime_install(market):
    from arb.runtime import EXECUTOR
    fork, loan, mid, lender, buy, sell, loss, atomic = market
    fork.install(lender.address)
    tx = transaction(plan(market), 2000000000)
    assert fork.rpc.w3.eth.get_code(EXECUTOR)
    result = fork.rpc.request("eth_call", [tx, "latest"])
    assert decode(("uint256",), bytes.fromhex(result[2:]))[0] == 20000
