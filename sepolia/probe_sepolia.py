"""PHASE 1 — Probe Base Sepolia (84532): what actually exists on-chain.
Reads RPC from sepolia_config.json (key never printed)."""
import json, os
from web3 import Web3

BASE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(BASE, "sepolia_config.json")))

CANDIDATES = {
    # Uniswap V3 (Base mainnet addresses — to verify on Sepolia)
    "Uni V3 Factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    "Uni V3 SwapRouter02": "0x2626664c2603336E57B271c5C0b26F421741e481",
    "Uni V3 QuoterV2": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
    # Uniswap V2 (Base mainnet addresses)
    "Uni V2 Factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
    "Uni V2 Router02": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
    # Aave V3 (Base mainnet addresses)
    "Aave PoolAddressesProvider": "0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D",
    "Aave V3 Pool (mainnet addr)": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
    # Morpho Blue (canonical CREATE2 — same address on all chains where deployed)
    "Morpho Blue": "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",
    # Tokens
    "WETH (predeploy)": "0x4200000000000000000000000000000000000006",
    "USDC Base Sepolia (Circle)": "0x036CbD53842c5426634e7929541eC2318f3dCF7eb",
    "USDC Base mainnet addr": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    # Misc
    "Multicall3": "0xcA11bde05977b3631167028862bE2a173976CA11",
}

def probe(rpc_url, label):
    print(f"--- {label} ---")
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        print("connected:", w3.is_connected(), "| chain_id:", w3.eth.chain_id, "| block:", w3.eth.block_number)
        out = {}
        for name, addr in CANDIDATES.items():
            try:
                code = w3.eth.get_code(Web3.to_checksum_address(addr))
                out[name] = len(code)
                print(f"  {name:32s} {addr}  code={len(code)} bytes")
            except Exception as e:
                out[name] = f"ERR {e}"
                print(f"  {name:32s} ERR {e}")
        return out
    except Exception as e:
        print("  CONNECTION FAILED:", e)
        return None

res = probe(cfg["rpc_url"], "Alchemy Base Sepolia")
if res is None:
    res = probe(cfg["rpc_fallback"], "Public sepolia.base.org (fallback)")
with open(os.path.join(BASE, "probe_sepolia.json"), "w") as f:
    json.dump(res, f, indent=2)
print("saved probe_sepolia.json")
