// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @notice Test-only meme token for the Base Sepolia REAL arbitrage test.
/// TESTNET ONLY — no value, minted freely to the deployer for pool seeding.
contract TestMeme is ERC20 {
    constructor() ERC20("TestMeme Sepolia", "TMEME") {
        _mint(msg.sender, 1_000_000 * 10 ** decimals());
    }
}
