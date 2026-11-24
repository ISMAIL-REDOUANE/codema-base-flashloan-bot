#!/usr/bin/env bash
# fork_test_polygon.sh — Lance un fork Anvil de Polygon mainnet (AUCUN fond réel,
# AUCUNE clé privée, AUCUN broadcast mainnet) puis le test fork Morpho Polygon v4.0.
# Usage : bash fork_test_polygon.sh
# Arrête Anvil à la fin (trap). Le fork tourne sur 127.0.0.1:8545.
# Le RPC est public (drpc.org) — aucune clé API.
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.foundry/bin:$PATH"

ANVIL_LOG="anvil_fork_polygon.log"
FORK_URL="https://polygon.drpc.org"
GAS_PRICE_GWEI=279   # mesuré live 2026-11-24 (bloc 97 901 602)

echo "=== v4.0 fork test Morpho Polygon — fork mainnet Polygon (anvil) ==="
echo "Fork URL : $FORK_URL (public, sans clé)"
echo "Gas price fork : ${GAS_PRICE_GWEI} gwei | Seuil min_profit_usd : 3 $"

# Nettoyer un ancien Anvil éventuel sur le port 8545
pkill -f "anvil.*8545" 2>/dev/null || true
sleep 1

anvil --fork-url "$FORK_URL" --chain-id 137 --port 8545 \
  --gas-price "${GAS_PRICE_GWEI}000000000" --no-rate-limit \
  > "$ANVIL_LOG" 2>&1 &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null || true' EXIT

# Attendre qu'Anvil réponde (max 120 s — le 1er fork télécharge l'état)
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

echo "--- Test fork Morpho Polygon (python) ---"
../.venv/bin/python fork_test_polygon.py
STATUS=$?

echo "--- Anvil arrêté (fork jetable, aucune donnée persistée) ---"
exit $STATUS
