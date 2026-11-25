// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Wrapper so `forge build` in this Sepolia project compiles the repo's
// MorphoFlashLoanArbitrage (root contracts/, UNCHANGED, 0.8.20).
// Uniswap V2 (0.5.16/0.6.6) is compiled separately with the matching
// solc binaries — see compile_v2.sh (pragma-incompatible with 0.8.20).
import {MorphoFlashLoanArbitrage} from "@root/contracts/FlashLoanArbitrage.sol";
