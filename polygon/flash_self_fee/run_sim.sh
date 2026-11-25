#!/usr/bin/env bash
# run_sim.sh — Lance un fork Anvil de Polygon mainnet (AUCUN fond réel,
# AUCUNE clé privée d'utilisateur, AUCUN broadcast mainnet) puis la
# simulation "fees to myself" (4 cas : hold / self-arb 2 pools / external
# arb / own-one-pair). Le fork tourne sur 127.0.0.1:8546.
# Usage : bash run_sim.sh
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.foundry/bin:$PATH"

ANVIL_LOG="anvil_self_fee.log"
FORK_URL="https://polygon.drpc.org"
GAS_PRICE_GWEI=279   # mesuré live 2026-11-24 (bloc 97 901 602)

echo "=== Simulation flash mint/swap 'fees to myself' — fork Polygon (anvil) ==="
echo "Fork URL : $FORK_URL (public, sans clé) | port 8546 | gas 279 gwei"

pkill -f "anvil.*8546" 2>/dev/null || true
sleep 1

anvil --fork-url "$FORK_URL" --chain-id 137 --port 8546 \
  --gas-price "${GAS_PRICE_GWEI}000000000" --no-rate-limit \
  > "$ANVIL_LOG" 2>&1 &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  if curl -s -X POST http://127.0.0.1:8546 \
      -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      | grep -q result; then
    echo "Anvil UP (pid $ANVIL_PID)"
    break
  fi
  sleep 2
done

BLOCK=$(curl -s -X POST http://127.0.0.1:8546 -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}')
echo "Bloc fork : $BLOCK"

echo "--- Simulation (python) ---"
../../.venv/bin/python simulate_self_fee.py
STATUS=$?

echo "--- Anvil arrêté (fork jetable, aucune donnée persistée) ---"
exit $STATUS
