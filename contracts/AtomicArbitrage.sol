// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IMorphoAtomic {
    function flashLoan(address token, uint256 assets, bytes calldata data) external;
}

interface IConcentratedPool {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function swap(address recipient, bool zeroForOne, int256 amountSpecified,
                  uint160 sqrtPriceLimitX96, bytes calldata data) external returns (int256, int256);
}

/// @notice Two exact-input CL swaps, including cross-venue routes, in one Morpho loan.
/// @dev Supports the Uniswap and Pancake callback ABIs. No assumption about token decimals.
/// The owner selects the pools; the runner independently verifies their factory identities.
/// @dev All execution state lives in TRANSIENT storage (EIP-1153, solc >= 0.8.24):
/// the state is only ever needed inside one atomic transaction, so persistent
/// slots (20,000 gas per first write, plus reset costs) are pure waste. Transient
/// slots cost 100 gas per write and are cleared automatically at the end of the tx.
/// @dev No SafeERC20: the only tokens ever moved here are the known loan/intermediate
/// tokens (USDC, WETH, cbBTC on Base), all of which return a bool from transfer /
/// approve. The return value is still checked explicitly on every call.
/// @dev Approval is per-trade and exact: the callback approves precisely the
/// borrowed amount, Morpho pulls it, the allowance returns to 0 (verified in
/// execute). A standing max approval was measured and REJECTED: it saves the
/// 20,000-gas approve SSTORE but loses the 4,800-gas clear refund and adds an
/// allowance read, for a net receipt-gas wash (+981 gas on the historical fork),
/// while leaving a standing allowance to the lender. Exact per-trade approval
/// is cheaper in fact and smaller in trust.
contract AtomicArbitrage {
    struct Leg { address pool; address tokenIn; address tokenOut; uint8 kind; uint256 minOut; }
    struct Plan {
        address loanToken;
        uint256 amount;
        Leg buy;
        Leg sell;
        uint256 minProfit; // loan token units, AFTER repaying the loan, BEFORE network costs
        uint256 deadline;
        uint256 lastBlock;
    }

    address public immutable owner;
    address public immutable morpho;
    bytes32 private transient pending;
    address private transient activePool;
    address private transient activeToken;
    uint256 private transient remainingInput;
    uint8 private transient activeKind;
    bool private transient activeInputIsToken0;
    bool private transient running;
    bool private transient inCallback;
    event Arbitrage(address indexed loanToken, uint256 amount, uint256 profit);

    constructor(address lender, address controller) {
        require(lender != address(0) && controller != address(0), "zero address");
        morpho = lender;
        owner = controller;
    }

    /// @dev Checked transfer for known bool-returning tokens (USDC, WETH, cbBTC).
    function _transfer(address token, address to, uint256 amount) private {
        require(IERC20(token).transfer(to, amount), "transfer");
    }

    /// @dev Checked approve for known bool-returning tokens. Per-trade exact
    /// approval: allowance starts at 0 and returns to 0 after Morpho's pull.
    function _approve(address token, address spender, uint256 amount) private {
        require(IERC20(token).approve(spender, amount), "approve");
    }

    function execute(Plan calldata plan) external returns (uint256 profit) {
        require(msg.sender == owner && !running, "owner/busy");
        require(block.timestamp <= plan.deadline && block.number <= plan.lastBlock, "expired");
        require(plan.amount > 0 && plan.amount <= uint256(type(int256).max), "amount");
        require(plan.buy.tokenIn == plan.loanToken && plan.sell.tokenOut == plan.loanToken
                && plan.buy.tokenOut == plan.sell.tokenIn
                && plan.buy.tokenIn != plan.buy.tokenOut
                && plan.buy.pool != plan.sell.pool, "route");
        require(plan.buy.kind <= 1 && plan.sell.kind <= 1, "kind");
        uint256 beforeBalance = IERC20(plan.loanToken).balanceOf(address(this));
        running = true;
        bytes memory data = abi.encode(plan, beforeBalance);
        pending = keccak256(data);
        IMorphoAtomic(morpho).flashLoan(plan.loanToken, plan.amount, data);
        require(pending == bytes32(0), "missing callback");
        uint256 afterBalance = IERC20(plan.loanToken).balanceOf(address(this));
        require(afterBalance >= beforeBalance + plan.minProfit, "profit");
        // Morpho must have pulled exactly the approved principal by now.
        require(IERC20(plan.loanToken).allowance(address(this), morpho) == 0, "unpaid loan");
        profit = afterBalance - beforeBalance;
        running = false;
        emit Arbitrage(plan.loanToken, plan.amount, profit);
    }

    function onMorphoFlashLoan(uint256 assets, bytes calldata data) external {
        require(msg.sender == morpho && running && !inCallback
                && pending != bytes32(0) && pending == keccak256(data), "loan callback");
        pending = bytes32(0);
        inCallback = true;
        (Plan memory plan, uint256 beforeBalance) = abi.decode(data, (Plan, uint256));
        require(assets == plan.amount
                && IERC20(plan.loanToken).balanceOf(address(this)) >= beforeBalance + assets, "principal");
        uint256 bought = _swap(plan.buy, assets);
        _swap(plan.sell, bought);
        require(IERC20(plan.loanToken).balanceOf(address(this)) >=
                beforeBalance + assets + plan.minProfit, "profit");
        _approve(plan.loanToken, morpho, assets);
        inCallback = false;
    }

    function _swap(Leg memory leg, uint256 amount) private returns (uint256 received) {
        require(amount > 0 && amount <= uint256(type(int256).max), "swap amount");
        address t0 = IConcentratedPool(leg.pool).token0();
        address t1 = IConcentratedPool(leg.pool).token1();
        bool zeroForOne = leg.tokenIn == t0;
        require((zeroForOne && leg.tokenOut == t1)
                || (leg.tokenIn == t1 && leg.tokenOut == t0), "pool tokens");
        uint256 beforeOut = IERC20(leg.tokenOut).balanceOf(address(this));
        activePool = leg.pool;
        activeToken = leg.tokenIn;
        remainingInput = amount;
        activeKind = leg.kind;
        activeInputIsToken0 = zeroForOne;
        IConcentratedPool(leg.pool).swap(address(this), zeroForOne, int256(amount),
            zeroForOne ? uint160(4295128740) : uint160(1461446703485210103287273052203988822378723970341), "");
        // Reject partial fills at a price limit; they cannot silently consume inventory.
        require(remainingInput == 0, "partial fill");
        activePool = address(0);
        activeToken = address(0);
        received = IERC20(leg.tokenOut).balanceOf(address(this)) - beforeOut;
        require(received >= leg.minOut && received > 0, "min out");
    }

    function uniswapV3SwapCallback(int256 d0, int256 d1, bytes calldata) external { _pay(d0, d1, 0); }
    function pancakeV3SwapCallback(int256 d0, int256 d1, bytes calldata) external { _pay(d0, d1, 1); }

    function _pay(int256 d0, int256 d1, uint8 kind) private {
        require(inCallback && msg.sender == activePool && kind == activeKind, "swap callback");
        bool input0 = activeInputIsToken0;
        require(input0 ? (d0 > 0 && d1 < 0) : (d1 > 0 && d0 < 0), "deltas");
        uint256 owed = uint256(input0 ? d0 : d1);
        require(owed <= remainingInput, "input budget");
        remainingInput -= owed;
        _transfer(activeToken, msg.sender, owed);
    }

    function withdraw(address token) external {
        require(msg.sender == owner && !running, "owner/busy");
        _transfer(token, owner, IERC20(token).balanceOf(address(this)));
    }
}
