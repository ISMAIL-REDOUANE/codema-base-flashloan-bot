"""PHASE 1c — Morpho identity check + V3 pools existing + gas price."""
import json, os
from web3 import Web3

BASE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(BASE, "sepolia_config.json")))
w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"], request_kwargs={"timeout": 30}))
morpho = Web3.to_checksum_address("0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb")
usdc = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
weth = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")

# Morpho DOMAIN_SEPARATOR() — proves live Morpho Blue (selector 0xdb7ebf4d? use ABI)
MORPHO_ABI = [{"name":"DOMAIN_SEPARATOR","outputs":[{"type":"bytes32"}],"inputs":[],"stateMutability":"view","type":"function"}]
try:
    m = w3.eth.contract(address=morpho, abi=MORPHO_ABI)
    ds = m.functions.DOMAIN_SEPARATOR().call()
    print("Morpho DOMAIN_SEPARATOR:", ds.hex(), "(non-zero = live Morpho Blue)")
except Exception as e:
    print("Morpho DOMAIN_SEPARATOR failed:", str(e)[:150])

# V3 factory getPool(USDC, WETH, fee) for fee tiers
V3F_ABI = [{"name":"getPool","outputs":[{"type":"address"}],"inputs":[{"name":"t0","type":"address"},{"name":"t1","type":"address"},{"name":"fee","type":"uint24"}],"stateMutability":"view","type":"function"}]
v3f = w3.eth.contract(address=Web3.to_checksum_address("0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"), abi=V3F_ABI)
for fee in (100, 500, 3000, 10000):
    try:
        p = v3f.functions.getPool(usdc, weth, fee).call()
        print(f"V3 pool USDC/WETH fee {fee}: {p} code={len(w3.eth.get_code(p)) if p!='0x0000000000000000000000000000000000000000' else 0}")
    except Exception as e:
        print(f"V3 pool fee {fee}: ERR {str(e)[:100]}")

print("gas price (wei):", w3.eth.gas_price, "= gwei:", w3.eth.gas_price/1e9)
print("block:", w3.eth.block_number)
