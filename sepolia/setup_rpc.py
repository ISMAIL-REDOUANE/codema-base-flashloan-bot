"""Extract Alchemy key from config.yaml (never printed) and write Sepolia RPC config."""
import re, json, os
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = open(os.path.join(base, "config.yaml")).read()
m = re.search(r"rpc_url:\s*\"https://base-mainnet\.g\.alchemy\.com/v2/([A-Za-z0-9_-]+)\"", cfg)
assert m, "Alchemy key not found in config.yaml"
key = m.group(1)
out = {
    "chain": "Base Sepolia",
    "chain_id": 84532,
    "rpc_url": f"https://base-sepolia.g.alchemy.com/v2/{key}",
    "rpc_fallback": "https://sepolia.base.org",
    "explorer": "https://sepolia.basescan.org",
}
with open(os.path.join(base, "sepolia", "sepolia_config.json"), "w") as f:
    json.dump(out, f, indent=2)
print("OK - sepolia_config.json written, key length:", len(key))
