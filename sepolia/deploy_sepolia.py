#!/usr/bin/env python3
"""deploy_sepolia.py — REAL end-to-end test on Base Sepolia (84532).

Pipeline (all real transactions, testnet only):
  1. Deploy TestMeme (ERC20 test) + 2x Uniswap V2 Factory/Router (real V2 code).
  2. Wrap ETH -> WETH, create WETH/MEME pairs on both venues, seed liquidity
     at DIFFERENT prices (DEX A: 1 MEME = 0.001 WETH, DEX B: 1 MEME = 0.0015
     WETH -> 50% spread, created deliberately to test the pipeline).
  3. Deploy MorphoFlashLoanArbitrage (repo contract, UNCHANGED).
     Loan token = WETH (not USDC): Morpho Sepolia holds 1.35 WETH and
     120 324 USDC; WETH is used because pool seeding with Circle USDC would
     need ~20 000 USDC (faucet drips are 10-20 USDC) while WETH comes from
     wrapping the faucet ETH. The contract is token-agnostic (its `USDC`
     parameter is just the loan-token address) — the flash-loan code path
     exercised is identical.
  4. Preflight: live on-chain quotes via both routers for several loan
     sizes; pick the best net. eth_call simulation of executeArbitrage.
  5. Execute the REAL flash-loan arbitrage, withdraw the profit.

The private key is loaded from sepolia/.test-wallet.json and NEVER printed.
Usage:
  python3 deploy_sepolia.py --check-funding   # read-only: balance + requirements
  python3 deploy_sepolia.py --dry-run         # simulate everything, send nothing
  python3 deploy_sepolia.py --all             # full real pipeline
  python3 deploy_sepolia.py --step deploy|seed|arb   # resume from a step
State is saved to sepolia/deployment.json (addresses + tx hashes).
"""
import argparse
import json
import os
import sys
import time

from eth_account import Account
from web3 import Web3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# --- Test parameters (documented, deterministic) ---------------------------
WETH_ADDR = "0x4200000000000000000000000000000000000006"
MORPHO_ADDR = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
POOL_WETH_WEI = 10 ** 17          # 0.10 WETH per pool
POOL_A_MEME_WEI = 100 * 10 ** 18  # 100 MEME -> 1 MEME = 0.001 WETH
POOL_B_MEME_WEI = 66666666666666666667  # 66.666... MEME -> 1 MEME = 0.0015 WETH
WRAP_WEI = 2 * POOL_WETH_WEI     # 0.20 ETH wrapped for seeding
MIN_BALANCE_WEI = WRAP_WEI + 10 ** 16  # 0.21 ETH (seed + gas reserve)
MIN_PROFIT_WEI = 10 ** 15         # 0.001 WETH (~$1.68) — test-scale minimum
LOAN_CANDIDATES_WEI = [2 * 10 ** 15, 4 * 10 ** 15, 6 * 10 ** 15,
                       8 * 10 ** 15, 8866000000000000, 10 ** 16, 12 * 10 ** 15]

ERC20_ABI = [
    {"name": "approve", "outputs": [{"type": "bool"}], "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "balanceOf", "outputs": [{"type": "uint256"}], "inputs": [{"name": "a", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "allowance", "outputs": [{"type": "uint256"}], "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "stateMutability": "view", "type": "function"},
]
WETH_ABI = ERC20_ABI + [
    {"name": "deposit", "outputs": [], "inputs": [], "stateMutability": "payable", "type": "function"},
]
PAIR_ABI = [
    {"name": "getReserves", "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
]


def load_artifact_forge(name):
    p = os.path.join(HERE, "out", "FlashLoanArbitrage.sol", name + ".json")
    if not os.path.exists(p):
        p = os.path.join(HERE, "out", "TestMeme.sol", name + ".json")
    d = json.load(open(p))
    bc = d["bytecode"]
    if isinstance(bc, dict):  # Foundry artifact: {"object": "0x...", ...}
        bc = bc["object"]
    return d["abi"], bc


def load_artifact_v2(filename, name):
    d = json.load(open(os.path.join(HERE, "artifacts-v2", filename)))
    for k, v in d["contracts"].items():
        if k.endswith(":" + name):
            return v["abi"], v["bin"]
    raise KeyError(name)


class Deployer:
    def __init__(self, dry_run=False):
        cfg = json.load(open(os.path.join(HERE, "sepolia_config.json")))
        self.w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"], request_kwargs={"timeout": 60}))
        assert self.w3.is_connected(), "RPC not connected"
        assert self.w3.eth.chain_id == 84532, f"wrong chain {self.w3.eth.chain_id}"
        wallet = json.load(open(os.path.join(HERE, ".test-wallet.json")))
        self.acct = Account.from_key(wallet["private_key"])
        self.addr = self.acct.address
        self.dry_run = dry_run
        self.nonce = self.w3.eth.get_transaction_count(self.addr, "pending")
        self.state = self._load_state()
        print(f"wallet: {self.addr} (testnet only)")
        print(f"block: {self.w3.eth.block_number} | gas price: {self.w3.eth.gas_price / 1e9:.4f} gwei")

    def _load_state(self):
        p = os.path.join(HERE, "deployment.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def _save_state(self):
        if self.dry_run:
            return  # never persist fake dry-run addresses
        with open(os.path.join(HERE, "deployment.json"), "w") as f:
            json.dump(self.state, f, indent=2)

    def check_funding(self):
        bal = self.w3.eth.get_balance(self.addr)
        print(f"ETH balance: {bal / 1e18:.6f} ETH | required: {MIN_BALANCE_WEI / 1e18:.2f} ETH")
        return bal >= MIN_BALANCE_WEI

    def send(self, fn_call, value=0, gas_limit=3_000_000):
        """Build, sign and send a tx (or simulate it in dry-run). Returns tx hash or None."""
        tx = fn_call.build_transaction({
            "from": self.addr, "nonce": self.nonce,
            "gas": gas_limit, "gasPrice": self.w3.eth.gas_price,
            "chainId": 84532, "value": value,
        })
        if self.dry_run:
            try:
                gas_est = self.w3.eth.estimate_gas({**tx, "gas": None} if False else tx)
                print(f"  [dry-run] estimated gas: {gas_est}")
            except Exception as e:
                print(f"  [dry-run] estimate_gas FAILED: {str(e)[:200]}")
                raise
            print("  [dry-run] NOT sent")
            return None
        signed = self.acct.sign_transaction(tx)
        txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  tx: {txh.hex()}")
        rcpt = self.w3.eth.wait_for_transaction_receipt(txh, timeout=180)
        assert rcpt["status"] == 1, f"tx FAILED: {txh.hex()}"
        print(f"  confirmed in block {rcpt['blockNumber']}, gas used {rcpt['gasUsed']}")
        self.nonce += 1
        return txh.hex(), rcpt

    def deploy(self, abi, bytecode, args=(), label=""):
        print(f"deploying {label}...")
        factory = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        tx = factory.constructor(*args).build_transaction({
            "from": self.addr, "nonce": self.nonce,
            "gas": 5_000_000, "gasPrice": self.w3.eth.gas_price, "chainId": 84532,
        })
        if self.dry_run:
            print("  [dry-run] NOT sent")
            return "0x" + "00" * 20
        signed = self.acct.sign_transaction(tx)
        txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  tx: {txh.hex()}")
        rcpt = self.w3.eth.wait_for_transaction_receipt(txh, timeout=180)
        assert rcpt["status"] == 1, "deploy FAILED"
        addr = rcpt["contractAddress"]
        print(f"  deployed at {addr} (block {rcpt['blockNumber']}, gas {rcpt['gasUsed']})")
        self.nonce += 1
        return addr

    # --- steps -------------------------------------------------------------
    def step_deploy(self):
        meme_abi, meme_bin = load_artifact_forge("TestMeme")
        fac_abi, fac_bin = load_artifact_v2("factory-0.5.16.json", "UniswapV2Factory")
        rou_abi, rou_bin = load_artifact_v2("router-0.6.6.json", "UniswapV2Router02")
        arb_abi, arb_bin = load_artifact_forge("MorphoFlashLoanArbitrage")
        self.state.setdefault("contracts", {})
        if "meme" not in self.state["contracts"]:
            self.state["contracts"]["meme"] = self.deploy(meme_abi, meme_bin, label="TestMeme")
        if "factoryA" not in self.state["contracts"]:
            self.state["contracts"]["factoryA"] = self.deploy(fac_abi, fac_bin, (self.addr,), "V2 Factory A (DEX A)")
        if "routerA" not in self.state["contracts"]:
            self.state["contracts"]["routerA"] = self.deploy(rou_abi, rou_bin, (self.state["contracts"]["factoryA"], WETH_ADDR), "V2 Router A")
        if "factoryB" not in self.state["contracts"]:
            self.state["contracts"]["factoryB"] = self.deploy(fac_abi, fac_bin, (self.addr,), "V2 Factory B (DEX B)")
        if "routerB" not in self.state["contracts"]:
            self.state["contracts"]["routerB"] = self.deploy(rou_abi, rou_bin, (self.state["contracts"]["factoryB"], WETH_ADDR), "V2 Router B")
        if "arb" not in self.state["contracts"]:
            c = self.state["contracts"]
            self.state["contracts"]["arb"] = self.deploy(
                arb_abi, arb_bin,
                (WETH_ADDR, c["meme"], c["routerA"], c["routerB"], MIN_PROFIT_WEI),
                "MorphoFlashLoanArbitrage (loan=WETH, minProfit=0.001 WETH)")
        self._save_state()

    def step_seed(self):
        c = self.state["contracts"]
        weth = self.w3.eth.contract(address=WETH_ADDR, abi=WETH_ABI)
        meme = self.w3.eth.contract(address=c["meme"], abi=ERC20_ABI)
        fac_abi, _ = load_artifact_v2("factory-0.5.16.json", "UniswapV2Factory")
        rou_abi, _ = load_artifact_v2("router-0.6.6.json", "UniswapV2Router02")
        facA = self.w3.eth.contract(address=c["factoryA"], abi=fac_abi)
        facB = self.w3.eth.contract(address=c["factoryB"], abi=fac_abi)
        rouA = self.w3.eth.contract(address=c["routerA"], abi=rou_abi)
        rouB = self.w3.eth.contract(address=c["routerB"], abi=rou_abi)

        print("wrapping 0.20 ETH -> WETH...")
        self.send(weth.functions.deposit(), value=WRAP_WEI)
        print(f"WETH balance: {weth.functions.balanceOf(self.addr).call() / 1e18:.6f}")

        for label, fac, rou, meme_amt in [("A", facA, rouA, POOL_A_MEME_WEI), ("B", facB, rouB, POOL_B_MEME_WEI)]:
            print(f"creating pair WETH/MEME on DEX {label}...")
            self.send(fac.functions.createPair(WETH_ADDR, c["meme"]))
            pair_addr = fac.functions.getPair(WETH_ADDR, c["meme"]).call()
            print(f"  pair {label}: {pair_addr}")
            self.state.setdefault("pairs", {})[label] = pair_addr
            print(f"approving router {label} (WETH + MEME)...")
            self.send(weth.functions.approve(rou.address, POOL_WETH_WEI))
            self.send(meme.functions.approve(rou.address, meme_amt))
            deadline = self.w3.eth.get_block("latest")["timestamp"] + 3600
            print(f"adding liquidity {label}: 0.10 WETH + {meme_amt / 1e18:.4f} MEME...")
            self.send(rou.functions.addLiquidity(
                WETH_ADDR, c["meme"], POOL_WETH_WEI, meme_amt, 0, 0, self.addr, deadline))
            pair = self.w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
            r0, r1, _ = pair.functions.getReserves().call()
            t0 = pair.functions.token0().call()
            print(f"  reserves {label}: token0={t0[:10]}... r0={r0} r1={r1}")
        self._save_state()

    def step_arb(self):
        c = self.state["contracts"]
        rou_abi, _ = load_artifact_v2("router-0.6.6.json", "UniswapV2Router02")
        rouA = self.w3.eth.contract(address=c["routerA"], abi=rou_abi)
        rouB = self.w3.eth.contract(address=c["routerB"], abi=rou_abi)
        arb_abi, _ = load_artifact_forge("MorphoFlashLoanArbitrage")
        arb = self.w3.eth.contract(address=c["arb"], abi=arb_abi)
        weth = self.w3.eth.contract(address=WETH_ADDR, abi=ERC20_ABI)

        print("live quotes (buy on A, sell on B) for candidate loan sizes:")
        best = None
        for loan in LOAN_CANDIDATES_WEI:
            try:
                bought = rouA.functions.getAmountsOut(loan, [WETH_ADDR, c["meme"]]).call()[1]
                back = rouB.functions.getAmountsOut(bought, [c["meme"], WETH_ADDR]).call()[1]
                net = back - loan
                print(f"  loan {loan/1e18:.6f} WETH -> buy {bought/1e18:.6f} MEME -> back {back/1e18:.6f} WETH | net {net/1e18:+.6f} WETH")
                if best is None or net > best[1]:
                    best = (loan, net)
            except Exception as e:
                print(f"  loan {loan/1e18:.6f} WETH -> quote FAILED: {str(e)[:120]}")
        assert best and best[1] > MIN_PROFIT_WEI, f"no profitable loan (best net {best[1] if best else 'n/a'} <= minProfit)"
        loan, net = best
        print(f"BEST: loan {loan/1e18:.6f} WETH, expected net {net/1e18:.6f} WETH")

        print("preflight: eth_call executeArbitrage (simulation, 0 gas)...")
        try:
            arb.functions.executeArbitrage(loan).call({"from": self.addr})
            print("  simulation OK (no revert)")
        except Exception as e:
            print(f"  simulation REVERTED: {str(e)[:300]}")
            raise SystemExit("preflight failed — aborting, nothing broadcast")

        bal_before = weth.functions.balanceOf(self.addr).call()
        print(f"wallet WETH before: {bal_before/1e18:.6f}")
        print("EXECUTING real flash-loan arbitrage...")
        res = self.send(arb.functions.executeArbitrage(loan), gas_limit=1_000_000)
        if res is None:
            print("[dry-run] execution skipped")
            return
        txh, rcpt = res
        bal_after = weth.functions.balanceOf(self.addr).call()
        arb_bal = weth.functions.balanceOf(c["arb"]).call()
        print(f"contract WETH balance (profit): {arb_bal/1e18:.6f} WETH")
        print(f"gas used: {rcpt['gasUsed']} | tx: {txh}")
        print("withdrawing profit...")
        res2 = self.send(arb.functions.withdrawProfit())
        bal_final = weth.functions.balanceOf(self.addr).call()
        print(f"wallet WETH after withdraw: {bal_final/1e18:.6f} (delta vs before: {(bal_final-bal_before)/1e18:+.6f} WETH)")
        self.state["arbitrage"] = {
            "loan_wei": loan, "expected_net_wei": net,
            "execute_tx": txh, "gas_used": rcpt["gasUsed"],
            "profit_wei": arb_bal, "withdraw_tx": res2[0] if res2 else None,
            "wallet_weth_before_wei": bal_before, "wallet_weth_after_wei": bal_final,
        }
        self._save_state()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-funding", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--step", choices=["deploy", "seed", "arb"])
    args = ap.parse_args()

    d = Deployer(dry_run=args.dry_run)
    if args.check_funding:
        ok = d.check_funding()
        if not ok:
            print("\nFUNDING REQUIRED — the test wallet has no Sepolia ETH.")
            print("Ismail must do this (browser, ~2 min, $0):")
            print("  1. Go to https://faucets.chain.link/base-sepolia")
            print("  2. Connect HIS OWN MetaMask wallet (not the test wallet).")
            print(f"  3. Claim 0.5 test ETH (+ 25 test LINK).")
            print(f"  4. Send 0.25 test ETH to the test wallet: {d.addr}")
            print("  5. Tell Muse it is done -> rerun this script.")
            sys.exit(2)
        print("funding OK")
        return
    if args.all or args.step == "deploy":
        d.step_deploy()
    if args.all or args.step == "seed":
        if not d.check_funding():
            print("FUNDING REQUIRED — run --check-funding for the steps.")
            sys.exit(2)
        d.step_seed()
    if args.all or args.step == "arb":
        d.step_arb()
    if not (args.all or args.step):
        print("nothing to do — use --all, --step, --check-funding or --dry-run")


if __name__ == "__main__":
    main()
