#!/usr/bin/env bash
# fork_test_curve.sh — Lance un fork Anvil de Polygon mainnet (AUCUN fond réel,
# AUCUNE clé privée, AUCUN broadcast mainnet) puis le test fork de la jambe
# Curve v4.5 (CurveFlashArbPolygon, 4 swaps).
# Usage : bash fork_test_curve.sh
# Arrête Anvil à la fin (trap). Le fork tourne sur 127.0.0.1:8545.
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.foundry/bin:$PATH"

ANVIL_LOG="anvil_fork_curve.log"
FORK_URL="https://polygon.drpc.org"
GAS_PRICE_GWEI=280   # mesuré live 2026-11-25 (bloc ~97 922 000)

echo "=== v4.5 fork test jambe Curve — fork mainnet Polygon (anvil) ==="
echo "Fork URL : $FORK_URL (public, sans clé)"
echo "Gas price fork : ${GAS_PRICE_GWEI} gwei"

pkill -x anvil 2>/dev/null || true  # -x : nom exact, sinon pkill -f se tue lui-même via sa propre ligne de commande
sleep 1

anvil --fork-url "$FORK_URL" --chain-id 137 --port 8545 \
  --gas-price "${GAS_PRICE_GWEI}000000000" --no-rate-limit \
  > "$ANVIL_LOG" 2>&1 &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  if curl -s -X POST http://127.0.0.1:8545 \
      -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      | grep -q result; then
    echo "Anvil UP (pid $ANVIL_PID)"
    break
  fi
  sleep 2
done

BLOCK=$(curl -s -X POST http://127.0.0.1:8545 -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}')
echo "Bloc fork : $BLOCK"

echo "--- Compilation du contrat (forge build) ---"
forge build

echo "--- Test fork jambe Curve (python) ---"
../.venv/bin/python fork_test_curve.py
STATUS=$?

echo "--- Anvil arrêté (fork jetable, aucune donnée persistée) ---"
exit $STATUS
