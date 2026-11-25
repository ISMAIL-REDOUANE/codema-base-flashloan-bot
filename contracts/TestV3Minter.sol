// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Helper de TEST (fork uniquement) : mint de liquidité V3.
/// Détient les deux tokens et les paie au pool via uniswapV3MintCallback.
/// Aucune valeur, jamais déployé sur mainnet.
interface IUniswapV3PoolMint {
    function mint(address recipient, int24 tickLower, int24 tickUpper,
                  uint128 amount, bytes calldata data)
        external returns (uint256 amount0, uint256 amount1);
    function token0() external view returns (address);
    function token1() external view returns (address);
}

interface IERC20Minimal {
    function transfer(address to, uint256 amount) external returns (bool);
}

contract TestV3Minter {
    function mint(address pool, int24 tickLower, int24 tickUpper,
                  uint128 amount) external {
        IUniswapV3PoolMint(pool).mint(address(this), tickLower, tickUpper,
                                     amount, "");
    }

    function uniswapV3MintCallback(uint256 amount0Owed, uint256 amount1Owed,
                                   bytes calldata /* data */) external {
        address pool = msg.sender;
        address t0 = IUniswapV3PoolMint(pool).token0();
        address t1 = IUniswapV3PoolMint(pool).token1();
        if (amount0Owed > 0) IERC20Minimal(t0).transfer(pool, amount0Owed);
        if (amount1Owed > 0) IERC20Minimal(t1).transfer(pool, amount1Owed);
    }
}
