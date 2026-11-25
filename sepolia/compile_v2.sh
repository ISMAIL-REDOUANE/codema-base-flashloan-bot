#!/bin/bash
# Compile Uniswap V2 with the matching solc binaries (pragma-incompatible
# with the 0.8.20 forge build).
# Canonical optimizer settings (verified vs Base mainnet on-chain code):
#   Factory+Pair (solc 0.5.16): runs=999999 -> runtime 13 859 B = mainnet
#   Router (solc 0.6.6):        runs=200    -> runtime 17 891 B = mainnet
# Run from the repo root. Artifacts -> sepolia/artifacts-v2/
set -e
R="$(cd "$(dirname "$0")/.." && pwd)"
"$HOME/.svm/0.5.16/solc-0.5.16" --combined-json abi,bin,bin-runtime \
  --optimize --optimize-runs 999999 --allow-paths "$R" \
  "$R/lib/v2-core/contracts/UniswapV2Factory.sol" \
  > "$R/sepolia/artifacts-v2/factory-0.5.16.json"
"$HOME/.svm/0.6.6/solc-0.6.6" --combined-json abi,bin,bin-runtime \
  --optimize --optimize-runs 200 --allow-paths "$R" \
  "@uniswap/v2-core/=$R/lib/v2-core/" "@uniswap/lib/=$R/lib/uniswap-lib/" \
  "$R/lib/v2-periphery/contracts/UniswapV2Router02.sol" \
  > "$R/sepolia/artifacts-v2/router-0.6.6.json"
echo "V2 artifacts written to sepolia/artifacts-v2/"
