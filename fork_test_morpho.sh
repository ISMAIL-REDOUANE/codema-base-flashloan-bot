#!/usr/bin/env bash
# fork_test_morpho.sh — Lance un fork Anvil de Base mainnet (AUCUN fond réel,
# AUCUNE clé privée, AUCUN broadcast mainnet) puis le test fork Morpho v3.3.
# Usage : bash fork_test_morpho.sh
# Arrête Anvil à la fin (trap). Le fork tourne sur 127.0.0.1:8545.
# Le RPC vient de config.yaml (chain.rpc_url, Alchemy Base-Bot) — il n'est
# JAMAIS affiché ; le log Anvil est expurgé de toute clé à la fin.
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.foundry/bin:$PATH"

ANVIL_LOG="anvil_fork_morpho.log"
FORK_URL="$(python3 -c "import re; print(re.search(r'rpc_url:\s*\"([^\"]+)\"', open('config.yaml').read()).group(1))")"

echo "=== v3.3 fork test Morpho — Base mainnet fork (anvil) ==="
echo "Fork URL : <config.yaml chain.rpc_url, clé masquée>"
echo "Seuil min_profit_usd : 3 $ (confirmé par Ismail 2026-11-24)"

# Nettoyer un ancien Anvil éventuel sur le port 8545
pkill -f "anvil.*8545" 2>/dev/null || true
sleep 1

anvil --fork-url "$FORK_URL" --chain-id 8453 --port 8545 \
  --gas-price 50000000 --no-rate-limit \
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

echo "--- Test fork Morpho (python) ---"
.venv/bin/python fork_test_morpho.py
STATUS=$?

# Expurger toute clé API éventuelle du log Anvil (jamais de clé en clair).
sed -i 's|\(g\.alchemy\.com/v2/\)[^ "]*|\1[REDACTED]|g' "$ANVIL_LOG" 2>/dev/null || true

echo "--- Anvil arrêté (fork jetable, aucune donnée persistée) ---"
exit $STATUS
