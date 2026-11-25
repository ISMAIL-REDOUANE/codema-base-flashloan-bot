"""PHASE 1b — Deep probe, all calls guarded."""
import json, os
from web3 import Web3

BASE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(BASE, "sepolia_config.json")))
w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"], request_kwargs={"timeout": 30}))
print("chain:", w3.eth.chain_id, "block:", w3.eth.block_number)
results = {}

def code(addr):
    try:
        return len(w3.eth.get_code(Web3.to_checksum_address(addr)))
    except Exception as e:
        return f"ERR {e}"

def raw_call(addr, selector_hex, label):
    try:
        data = w3.eth.call({"to": Web3.to_checksum_address(addr), "data": selector_hex})
        print(f"  {label}: OK data={data.hex()}")
        return data.hex()
    except Exception as e:
        print(f"  {label}: REVERT/ERR {str(e)[:120]}")
        return f"ERR {str(e)[:120]}"

ERC20_ABI = [
    {"name":"name","outputs":[{"type":"string"}],"inputs":[],"stateMutability":"view","type":"function"},
    {"name":"symbol","outputs":[{"type":"string"}],"inputs":[],"stateMutability":"view","type":"function"},
    {"name":"decimals","outputs":[{"type":"uint8"}],"inputs":[],"stateMutability":"view","type":"function"},
    {"name":"balanceOf","outputs":[{"type":"uint256"}],"inputs":[{"name":"a","type":"address"}],"stateMutability":"view","type":"function"},
]
usdc = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
weth = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
results["usdc"] = usdc
morpho = Web3.to_checksum_address("0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb")
for label, addr in [("USDC", usdc), ("WETH", weth)]:
    t = w3.eth.contract(address=addr, abi=ERC20_ABI)
    bal = t.functions.balanceOf(morpho).call()
    print(f"Morpho balance {label}: {bal}")
    results[f"morpho_{label.lower()}"] = bal

# V2 router 0x4752... — raw selectors
v2r = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
print(f"Uni V2 Router02 {v2r} code={code(v2r)}")
results["v2_router_code"] = code(v2r)
raw_call(v2r, "0xc45a0155", "factory()")
raw_call(v2r, "0xad5c4648", "WETH()")
# Also try getAmountsOut selector? No — need factory first.

for label, addr in [("Sushi V2 Factory", "0xC0AEe478e3658E2610c5F7A4A2E1777cE9e4C2Ac"),
                    ("Sushi V2 Router02", "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"),
                    ("Uni V3 Factory canonical", "0x1F98431c8aD98523631AE4a59f267346ea31F984"),
                    ("Uni V3 SwapRouter02 Sepolia?", "0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4")]:
    c = code(addr)
    print(f"{label}: code={c}")
    results[label] = c

# V3 router Sepolia -> factory() raw
raw_call("0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4", "0xc45a0155", "V3Router.factory()")

PROVIDER_ABI = [{"name":"getPool","outputs":[{"type":"address"}],"inputs":[],"stateMutability":"view","type":"function"}]
for label, addr in [("Aave Provider A", "0xd449FeD49d9C443688d6816fE6872F21402e41de"),
                    ("Aave Provider B", "0xE4C23309117Aa30342BFaae6c95c6478e0A4Ad00")]:
    c = code(addr)
    pool = None
    if isinstance(c, int) and c > 0:
        try:
            pool = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=PROVIDER_ABI).functions.getPool().call()
        except Exception as e:
            pool = f"getPool ERR {str(e)[:100]}"
    print(f"{label} {addr}: code={c} getPool={pool}")
    results[label] = {"code": c, "getPool": pool}
for label, addr in [("Aave Pool A", "0x07eA79F68B2B3df564D0A34F8e19D9B1e339814b"),
                    ("Aave Pool B", "0x8bAB6d1b75f19e9eD9fCe8b9BD338844fF79aE27")]:
    c = code(addr)
    print(f"{label} {addr}: code={c}")
    results[label] = c

with open(os.path.join(BASE, "probe2_sepolia.json"), "w") as f:
    json.dump(results, f, indent=2)
print("saved probe2_sepolia.json")
