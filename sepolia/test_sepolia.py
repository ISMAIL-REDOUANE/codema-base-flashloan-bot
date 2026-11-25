"""test_sepolia.py — tests for the Base Sepolia REAL test (testnet only).

Run:  .venv/bin/python -m unittest sepolia.test_sepolia -v
All live checks are READ-ONLY (eth_call / eth_getCode / eth_getBalance).
Nothing is broadcast, no key is ever printed (tests assert that).
"""
import json
import os
import re
import subprocess
import sys
import unittest

from web3 import Web3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _run_py(args, timeout=120):
    return subprocess.run(
        [sys.executable] + args, capture_output=True, text=True,
        cwd=ROOT, timeout=timeout)


class TestArtifacts(unittest.TestCase):
    def test_forge_artifacts_load(self):
        for path in ["out/FlashLoanArbitrage.sol/MorphoFlashLoanArbitrage.json",
                     "out/TestMeme.sol/TestMeme.json"]:
            d = json.load(open(os.path.join(HERE, path)))
            self.assertTrue(d["abi"], path)
            bc = d["bytecode"]["object"] if isinstance(d["bytecode"], dict) else d["bytecode"]
            self.assertTrue(bc.startswith("0x") and len(bc) > 100, path)

    def test_v2_artifacts_load(self):
        fac = json.load(open(os.path.join(HERE, "artifacts-v2", "factory-0.5.16.json")))
        rou = json.load(open(os.path.join(HERE, "artifacts-v2", "router-0.6.6.json")))
        names = {k.split(":")[-1] for k in fac["contracts"]}
        self.assertIn("UniswapV2Factory", names)
        self.assertIn("UniswapV2Pair", names)
        names_r = {k.split(":")[-1] for k in rou["contracts"]}
        self.assertIn("UniswapV2Router02", names_r)

    def test_v2_hash_consistency(self):
        """Router must embed OUR factory's pair creation-code hash."""
        fac = json.load(open(os.path.join(HERE, "artifacts-v2", "factory-0.5.16.json")))
        rou = json.load(open(os.path.join(HERE, "artifacts-v2", "router-0.6.6.json")))

        def get(d, name):
            for k, v in d["contracts"].items():
                if k.endswith(":" + name):
                    return v
            raise KeyError(name)

        pair_bin = get(fac, "UniswapV2Pair")["bin"]
        rou_rt = get(rou, "UniswapV2Router02")["bin-runtime"]
        my_hash = Web3.keccak(hexstr=pair_bin).hex()[2:]
        self.assertIn(my_hash, rou_rt, "router does not embed our factory hash")
        self.assertNotIn("96e8ac4277198ff8b6f785478aa9a39f403cb768dd02cbee326c3e7da348845f", rou_rt)

    def test_v2_sizes_match_mainnet(self):
        fac = json.load(open(os.path.join(HERE, "artifacts-v2", "factory-0.5.16.json")))
        rou = json.load(open(os.path.join(HERE, "artifacts-v2", "router-0.6.6.json")))

        def get(d, name):
            for k, v in d["contracts"].items():
                if k.endswith(":" + name):
                    return v
            raise KeyError(name)

        self.assertEqual(len(get(fac, "UniswapV2Factory")["bin-runtime"]) // 2, 13859)
        self.assertEqual(len(get(rou, "UniswapV2Router02")["bin-runtime"]) // 2, 17891)


class TestSizing(unittest.TestCase):
    def test_optimal_loan_L_50pct(self):
        """L pools (0.10 WETH) + 50% spread -> loan ~$14.86, net ~+$3.28."""
        from math_engine import Pool, Costs, find_optimal_loan
        usd = 0.10 * 1676.0
        pool_a = Pool("A", reserve_usdc=usd, reserve_meme=usd / 1.676, fee_bps=30)
        pool_b = Pool("B", reserve_usdc=usd, reserve_meme=usd / 2.514, fee_bps=30)
        costs = Costs(gas_usd=0.01, flash_provider="morpho")
        r = find_optimal_loan(pool_a, pool_b, costs, max_loan_usd=10_000, max_pct_liquidity=0.5)
        self.assertGreater(r["net_usd"], 3.0, r)
        self.assertAlmostEqual(r["optimal_loan_usd"], 14.86, delta=1.0)
        self.assertAlmostEqual(r["net_usd"], 3.28, delta=0.5)


class TestSafety(unittest.TestCase):
    def test_wallet_and_config_gitignored(self):
        out = subprocess.run(["git", "check-ignore", "sepolia/.test-wallet.json",
                              "sepolia/sepolia_config.json"],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertIn(".test-wallet.json", out.stdout)
        self.assertIn("sepolia_config.json", out.stdout)

    def test_setup_rpc_does_not_leak_key(self):
        main = open(os.path.join(ROOT, "config.yaml")).read()
        key = re.search(r"base-mainnet\.g\.alchemy\.com/v2/([A-Za-z0-9_-]+)", main).group(1)
        r = _run_py(["sepolia/setup_rpc.py"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(key, r.stdout)
        cfg = json.load(open(os.path.join(HERE, "sepolia_config.json")))
        self.assertEqual(cfg["chain_id"], 84532)
        self.assertTrue(cfg["rpc_url"].startswith("https://base-sepolia.g.alchemy.com/v2/"))
        self.assertNotIn("base-mainnet", cfg["rpc_url"])

    def test_deploy_script_never_prints_private_key(self):
        key = json.load(open(os.path.join(HERE, ".test-wallet.json")))["private_key"]
        r = _run_py(["sepolia/deploy_sepolia.py", "--check-funding"])
        self.assertNotIn(key, r.stdout)
        self.assertNotIn(key, r.stderr)


class TestLiveReadOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = json.load(open(os.path.join(HERE, "sepolia_config.json")))
        cls.w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"], request_kwargs={"timeout": 30}))

    def test_chain_is_sepolia(self):
        self.assertEqual(self.w3.eth.chain_id, 84532)

    def test_morpho_live_with_liquidity(self):
        morpho = Web3.to_checksum_address("0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb")
        self.assertEqual(len(self.w3.eth.get_code(morpho)), 15623)
        erc20 = [{"name": "balanceOf", "outputs": [{"type": "uint256"}],
                  "inputs": [{"name": "a", "type": "address"}],
                  "stateMutability": "view", "type": "function"}]
        usdc = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
        weth = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
        usdc_bal = self.w3.eth.contract(address=usdc, abi=erc20).functions.balanceOf(morpho).call()
        weth_bal = self.w3.eth.contract(address=weth, abi=erc20).functions.balanceOf(morpho).call()
        self.assertGreater(usdc_bal, 0, "Morpho holds no USDC on Sepolia")
        self.assertGreater(weth_bal, 0, "Morpho holds no WETH on Sepolia")

    def test_funding_gate_blocks_without_eth(self):
        """Wallet has 0 ETH -> --check-funding must exit 2 with exact steps."""
        r = _run_py(["sepolia/deploy_sepolia.py", "--check-funding"])
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("FUNDING REQUIRED", r.stdout)
        self.assertIn("faucets.chain.link/base-sepolia", r.stdout)

    def test_deploy_dryrun_builds_all_contracts(self):
        r = _run_py(["sepolia/deploy_sepolia.py", "--dry-run", "--step", "deploy"])
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        for label in ["TestMeme", "Factory A", "Router A", "Factory B", "Router B",
                      "MorphoFlashLoanArbitrage"]:
            self.assertIn(label, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(HERE, "deployment.json")),
                         "dry-run must not persist fake addresses")


if __name__ == "__main__":
    unittest.main()
