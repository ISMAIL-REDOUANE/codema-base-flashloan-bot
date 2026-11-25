// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockToken is ERC20 {
    constructor(string memory name_) ERC20(name_, name_) {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

interface ILoanCallback { function onMorphoFlashLoan(uint256 assets, bytes calldata data) external; }
interface ISwapCallbacks {
    function uniswapV3SwapCallback(int256, int256, bytes calldata) external;
    function pancakeV3SwapCallback(int256, int256, bytes calldata) external;
}

contract MockMorpho {
    function flashLoan(address token, uint256 assets, bytes calldata data) external {
        ERC20(token).transfer(msg.sender, assets);
        ILoanCallback(msg.sender).onMorphoFlashLoan(assets, data);
        ERC20(token).transferFrom(msg.sender, address(this), assets);
    }
}

/// @dev Synthetic liquidity, explicitly not a market profit measurement.
contract MockCLPool {
    address public token0;
    address public token1;
    uint256 public numerator;
    uint256 public denominator;
    uint8 public kind;
    uint8 public attack;
    constructor(address t0, address t1, uint256 n, uint256 d, uint8 k) {
        token0 = t0; token1 = t1; numerator = n; denominator = d; kind = k;
    }
    function setAttack(uint8 value) external { attack = value; }
    function swap(address recipient, bool z, int256 amount, uint160, bytes calldata) external returns (int256 d0, int256 d1) {
        uint256 input = uint256(amount);
        uint256 output = input * numerator / denominator;
        uint256 owed = attack == 1 ? input + 1 : (attack == 2 ? input / 2 : input);
        ERC20(z ? token1 : token0).transfer(recipient, output);
        d0 = z ? int256(owed) : -int256(output);
        d1 = z ? -int256(output) : int256(owed);
        if (kind == 0) ISwapCallbacks(msg.sender).uniswapV3SwapCallback(d0, d1, "");
        else ISwapCallbacks(msg.sender).pancakeV3SwapCallback(d0, d1, "");
    }
}
