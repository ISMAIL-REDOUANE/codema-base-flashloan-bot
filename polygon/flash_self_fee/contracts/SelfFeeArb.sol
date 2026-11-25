// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IUniswapV2Pair {
    function swap(uint256 amount0Out, uint256 amount1Out, address to, bytes calldata data) external;
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
}

interface IUniswapV2Router02 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

/// @notice Fork-only flash-swap arbitrage executor (Uniswap V2 flash swap).
/// Flow: flash-borrow `tokenBorrow` from `pairBorrow`, sell it on the
/// router's pair, repay `pairBorrow` exactly `repayAmount` of `tokenPay`,
/// send the leftover `tokenPay` (profit) to the caller.
/// The 0.3% fee on the borrow leg stays in pairBorrow's reserves (accrues
/// to its LPs); the 0.3% fee on the router leg stays in that pair's
/// reserves (accrues to its LPs). There is NO separate flash fee.
contract SelfFeeArb {
    address public immutable pairBorrow;
    address public immutable router;
    address public immutable tokenBorrow;
    address public immutable tokenPay;

    constructor(address _pairBorrow, address _router, address _tokenBorrow, address _tokenPay) {
        pairBorrow = _pairBorrow;
        router = _router;
        tokenBorrow = _tokenBorrow;
        tokenPay = _tokenPay;
    }

    /// @param amountBorrow tokenBorrow units flash-borrowed from pairBorrow
    /// @param repayAmount exact tokenPay units to repay pairBorrow (off-chain
    ///        computed via getAmountIn, so the pair's K-check passes)
    /// @param amount0Out/amount1Out set from pairBorrow's token order
    function arb(uint256 amountBorrow, uint256 repayAmount, uint256 amount0Out, uint256 amount1Out) external {
        require(amountBorrow > 0, "no borrow");
        bytes memory data = abi.encode(repayAmount, msg.sender);
        IUniswapV2Pair(pairBorrow).swap(amount0Out, amount1Out, address(this), data);
    }

    function uniswapV2Call(address sender, uint256 amount0, uint256 amount1, bytes calldata data) external {
        require(msg.sender == pairBorrow, "not pairBorrow");
        require(sender == address(this), "not self");
        (uint256 repayAmount, address beneficiary) = abi.decode(data, (uint256, address));
        uint256 borrowed = amount0 > 0 ? amount0 : amount1;
        // Sell the borrowed token on the router's pair (the expensive leg).
        IERC20(tokenBorrow).approve(router, borrowed);
        address[] memory path = new address[](2);
        path[0] = tokenBorrow;
        path[1] = tokenPay;
        IUniswapV2Router02(router).swapExactTokensForTokens(borrowed, 0, path, address(this), block.timestamp);
        // Repay the flash borrow exactly.
        require(IERC20(tokenPay).balanceOf(address(this)) >= repayAmount, "insufficient repay");
        IERC20(tokenPay).transfer(pairBorrow, repayAmount);
        // Leftover tokenPay = profit, to the caller.
        uint256 profit = IERC20(tokenPay).balanceOf(address(this));
        if (profit > 0) {
            IERC20(tokenPay).transfer(beneficiary, profit);
        }
    }
}
