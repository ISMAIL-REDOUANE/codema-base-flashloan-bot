#!/usr/bin/env python3
"""
simulate_self_fee.py — Fork simulation "pay the fees to myself" (Polygon).

Ismail's idea: use a flash mint / flash swap, borrow/mint from a pool he
owns, so the swap fees return to himself as LP.

Method (fork Anvil of Polygon mainnet, port 8546, NO real funds, NO keys
except the public Anvil test keys, NO mainnet broadcast):
  * Two fresh V2 pairs (canonical Uniswap V2 factory/router code) for the
    same token pair (TKA/TKB, TKB = 1 $ proxy), seeded 50 000 / 50 000.
  * Pool A = "OURS" in setups 1; Pool B = external. In setup 2 the owner
    seeds BOTH pools.
  * An EXTERNAL trader (account 2) swaps 2 500 TKB -> TKA on pool B,
    creating a real ~10 % spread (no hand-edited reserves).
  * Optimal arb size from the repo's guard math (polygon_decide), executed
    via a V2 flash swap (SelfFeeArb): borrow TKA from A, sell on B, repay.
  * Four cases, same branch point (anvil snapshots):
      (i)   HOLD            — owner LP of A only, no trade.
      (ii)  SELF-ARB BOTH   — owner LP of A AND B, owner arbs.
      (iii) EXTERNAL-ARB    — owner LP of A only, a stranger arbs.
      (iv)  OWN-ONE-PAIR    — owner LP of A only, owner arbs.
  * TOTAL P&L (owner) = LP value at the fair (post-arb converged) price
    + wallet balances - gas paid. Fees decomposed per leg.

Run via: bash run_sim.sh   (starts anvil, runs this, stops anvil)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from math_engine import Pool, amm_out  # noqa: E402
from polygon_guard import polygon_decide  # noqa: E402

ANVIL_URL = "http://127.0.0.1:8546"
GAS_PRICE_GWEI = 279.0
MATIC_PRICE_USD = 0.0758
SEED = 50_000 * 10**18          # 50 000 TKA + 50 000 TKB per pool
MOVE = 2_500 * 10**18           # external swap on B (creates the spread)
DEC = 10**18

# Anvil public test keys (comptes 0/1/2) — NE contrôlent AUCUN fond réel.
# Dérivés de la mnémonique de test standard d'Anvil (jamais de clé en dur
# recopiée à la main : une faute de frappe donne une adresse vierge).
from eth_account import Account as _Account
_Account.enable_unaudited_hdwallet_features()
ACCTS = [
    _Account.from_mnemonic(
        "test test test test test test test test test test test junk",
        account_path=f"m/44'/60'/0'/0/{i}")
    for i in range(3)
]

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent


def load_artifact(path, name):
    d = json.load(open(path))
    for k, v in d["contracts"].items():
        if k.endswith(":" + name):
            return v["abi"], v["bin"]
    raise KeyError(name)


def load_forge_artifact(path):
    d = json.load(open(path))
    return d["abi"], d["bytecode"]["object"]


# ------------------------------------------------------------------ web3
w3 = Web3(Web3.HTTPProvider(ANVIL_URL, request_kwargs={"timeout": 120}))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
ADDR = [a.address for a in ACCTS]


def send_tx(fn, acct, gas=3_000_000):
    """Build, sign and send a contract call; return the receipt."""
    tx = fn.build_transaction({
        "from": acct.address,
        "gas": gas,
        "gasPrice": int(GAS_PRICE_GWEI * 1e9),
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": 137,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash)


def deploy(abi, bytecode, acct, *args):
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    receipt = send_tx(c.constructor(*args), acct, gas=5_000_000)
    return w3.eth.contract(address=receipt.contractAddress, abi=abi), receipt


def snapshot():
    return w3.provider.make_request("evm_snapshot", [])["result"]


def revert(snap_id):
    ok = w3.provider.make_request("evm_revert", [snap_id])["result"]
    assert ok, "evm_revert failed"


def gas_usd(receipt):
    return receipt["gasUsed"] * GAS_PRICE_GWEI * 1e9 / 1e18 * MATIC_PRICE_USD


# ------------------------------------------------------------------ AMM helpers
def get_amount_in(amount_out, reserve_in, reserve_out):
    """Exact UniswapV2Library.getAmountIn (integer math)."""
    return (reserve_in * amount_out * 1000) // ((reserve_out - amount_out) * 997) + 1


def reserves_tka_tkb(pair, tka, tkb):
    """Return (x_TKA, y_TKB) reserves regardless of token order."""
    r0, r1, _ = pair.functions.getReserves().call()
    t0 = pair.functions.token0().call()
    if t0.lower() == tka.lower():
        return r0, r1
    return r1, r0


def pair_price(pair, tka, tkb):
    x, y = reserves_tka_tkb(pair, tka, tkb)
    return y / x if x else 0.0


def lp_share(pair, owner):
    bal = pair.functions.balanceOf(owner).call()
    tot = pair.functions.totalSupply().call()
    return bal / tot if tot else 0.0


def owner_wealth(pair_a, pair_b, share_a, share_b, tka, tkb, owner, price):
    """Owner total wealth in TKB (= $) at price P (TKB per TKA)."""
    xa, ya = reserves_tka_tkb(pair_a, tka, tkb)
    xb, yb = reserves_tka_tkb(pair_b, tka, tkb)
    lp = share_a * (xa * price + ya) + share_b * (xb * price + yb)
    wallet = (
        ERC20(tka).functions.balanceOf(owner).call() * price
        + ERC20(tkb).functions.balanceOf(owner).call()
    ) / DEC
    return lp / DEC + wallet


ERC20_ABI = None  # set in main from TestToken artifact


def ERC20(addr):
    return w3.eth.contract(address=addr, abi=ERC20_ABI)


# ------------------------------------------------------------------ main
def main():
    assert w3.is_connected(), "anvil not reachable on 8546 — run bash run_sim.sh"
    fork_block = w3.eth.block_number
    print(f"fork block: {fork_block} | gas {GAS_PRICE_GWEI} gwei | MATIC ${MATIC_PRICE_USD}")
    owner, lp_b_acct, ext = ADDR[0], ADDR[1], ADDR[2]

    # ---- deploy tokens / factories / routers / pairs / arb contract
    tok_abi, tok_bin = load_forge_artifact(BASE / "out/TestToken.sol/TestToken.json")
    global ERC20_ABI
    ERC20_ABI = tok_abi
    fac_abi, fac_bin = load_artifact(REPO / "sepolia/artifacts-v2/factory-0.5.16.json", "UniswapV2Factory")
    rou_abi, rou_bin = load_artifact(REPO / "sepolia/artifacts-v2/router-0.6.6.json", "UniswapV2Router02")
    pair_abi, _ = load_artifact(REPO / "sepolia/artifacts-v2/factory-0.5.16.json", "UniswapV2Pair")
    arb_abi, arb_bin = load_forge_artifact(BASE / "out/SelfFeeArb.sol/SelfFeeArb.json")

    tka_c, _ = deploy(tok_abi, tok_bin, ACCTS[0], "Token A", "TKA")
    tkb_c, _ = deploy(tok_abi, tok_bin, ACCTS[0], "Token B", "TKB")
    TKA, TKB = tka_c.address, tkb_c.address
    fac1, _ = deploy(fac_abi, fac_bin, ACCTS[0], owner)
    fac2, _ = deploy(fac_abi, fac_bin, ACCTS[0], owner)
    rou1, _ = deploy(rou_abi, rou_bin, ACCTS[0], fac1.address, TKB)
    rou2, _ = deploy(rou_abi, rou_bin, ACCTS[0], fac2.address, TKB)
    send_tx(fac1.functions.createPair(TKA, TKB), ACCTS[0])
    send_tx(fac2.functions.createPair(TKA, TKB), ACCTS[0])
    pair_a = w3.eth.contract(address=fac1.functions.getPair(TKA, TKB).call(), abi=pair_abi)
    pair_b = w3.eth.contract(address=fac2.functions.getPair(TKA, TKB).call(), abi=pair_abi)
    print(f"TKA={TKA}\nTKB={TKB}\nPairA={pair_a.address} (factory1)\nPairB={pair_b.address} (factory2)")

    arb_c, _ = deploy(arb_abi, arb_bin, ACCTS[0], pair_a.address, rou2.address, TKA, TKB)
    print(f"SelfFeeArb={arb_c.address} (borrow from A, sell on B via router2)")

    snap_deployed = [snapshot()]  # list so setup() can re-take it after revert

    results = {"fork_block": fork_block, "gas_price_gwei": GAS_PRICE_GWEI,
               "matic_price_usd": MATIC_PRICE_USD, "seed_per_pool_usd": SEED // DEC,
               "external_move_tkb": MOVE // DEC, "cases": {}}

    def setup(owner_seeds_b):
        """Revert to deployed state, mint exact amounts, seed pools, move price."""
        revert(snap_deployed[0])
        snap_deployed[0] = snapshot()  # re-take: evm_revert consumes the id
        # mint exact amounts (clean wallets: no leftover inventory)
        send_tx(tka_c.functions.mint(owner, SEED * (2 if owner_seeds_b else 1)), ACCTS[0])
        send_tx(tkb_c.functions.mint(owner, SEED * (2 if owner_seeds_b else 1)), ACCTS[0])
        if not owner_seeds_b:
            send_tx(tka_c.functions.mint(lp_b_acct, SEED), ACCTS[0])
            send_tx(tkb_c.functions.mint(lp_b_acct, SEED), ACCTS[0])
        send_tx(tkb_c.functions.mint(ext, MOVE), ACCTS[0])
        deadline = w3.eth.get_block("latest")["timestamp"] + 3600
        # seed A (owner, always)
        for acct, rou in ((ACCTS[0], rou1),):
            send_tx(ERC20(TKA).functions.approve(rou.address, SEED), acct)
            send_tx(ERC20(TKB).functions.approve(rou.address, SEED), acct)
            send_tx(rou.functions.addLiquidity(TKA, TKB, SEED, SEED, 0, 0, acct.address, deadline), acct)
        # seed B (owner if setup 2, else account 1)
        b_acct = ACCTS[0] if owner_seeds_b else ACCTS[1]
        send_tx(ERC20(TKA).functions.approve(rou2.address, SEED), b_acct)
        send_tx(ERC20(TKB).functions.approve(rou2.address, SEED), b_acct)
        send_tx(rou2.functions.addLiquidity(TKA, TKB, SEED, SEED, 0, 0, b_acct.address, deadline), b_acct)
        # external trader moves B's price: swap 2 500 TKB -> TKA on B
        send_tx(ERC20(TKB).functions.approve(rou2.address, MOVE), ACCTS[2])
        r = send_tx(rou2.functions.swapExactTokensForTokens(
            MOVE, 0, [TKB, TKA], ext, deadline), ACCTS[2])
        assert r["status"] == 1, "external move failed"
        return r

    def sizing():
        """Optimal arb size from the repo's guard math (post-move reserves)."""
        xa, ya = reserves_tka_tkb(pair_a, TKA, TKB)
        xb, yb = reserves_tka_tkb(pair_b, TKA, TKB)
        buy = Pool("A(cheap)", ya / DEC, xa / DEC)
        sell = Pool("B(dear)", yb / DEC, xb / DEC)
        d = polygon_decide(buy, sell, GAS_PRICE_GWEI)
        loan_usd = d["optimal_loan_usd"]
        borrow_tka = int(amm_out(loan_usd, ya / DEC, xa / DEC) * DEC)
        repay_tkb = get_amount_in(borrow_tka, ya, xa)
        return d, loan_usd, borrow_tka, repay_tkb, (xa, ya), (xb, yb)

    def run_arb(caller_acct):
        """Execute the flash-swap arb via SelfFeeArb; return receipt + metrics."""
        d, loan_usd, borrow_tka, repay_tkb, res_a, res_b = sizing()
        t0 = pair_a.functions.token0().call()
        if t0.lower() == TKA.lower():
            a0, a1 = borrow_tka, 0
        else:
            a0, a1 = 0, borrow_tka
        # dry-run first (0 gas if it reverts)
        arb_c.functions.arb(borrow_tka, repay_tkb, a0, a1).call({"from": caller_acct.address})
        r = send_tx(arb_c.functions.arb(borrow_tka, repay_tkb, a0, a1), caller_acct, gas=1_500_000)
        assert r["status"] == 1, "arb tx reverted on fork"
        res_a_after = reserves_tka_tkb(pair_a, TKA, TKB)
        res_b_after = reserves_tka_tkb(pair_b, TKA, TKB)
        return r, d, loan_usd, borrow_tka, repay_tkb, res_a, res_b, res_a_after, res_b_after

    def fee_split(borrow_tka, repay_tkb, res_a, res_b):
        """Exact fee accounting per leg (in TKB units, whole tokens)."""
        xa, ya = res_a
        xb, yb = res_b
        # leg A (borrow): fee = repay - no-fee repay
        repay_no_fee = borrow_tka * ya // (xa - borrow_tka)
        fee_a = (repay_tkb - repay_no_fee) / DEC
        # leg B (sale): fee = no-fee sale - actual sale
        sale_actual = int(amm_out(borrow_tka / DEC, xb / DEC, yb / DEC) * DEC)
        sale_no_fee = borrow_tka * yb // (xb + borrow_tka)
        fee_b = (sale_no_fee - sale_actual) / DEC
        return fee_a, fee_b

    def case_record(name, share_a, share_b, price, gas_paid_usd, extra=None):
        w = owner_wealth(pair_a, pair_b, share_a, share_b, TKA, TKB, owner, price)
        rec = {"owner_wealth_usd": round(w - gas_paid_usd, 4),
               "lp_plus_wallet_usd": round(w, 4),
               "gas_paid_usd": round(gas_paid_usd, 6),
               "fair_price_tkb_per_tka": round(price, 6),
               "lp_share_a": round(share_a, 6), "lp_share_b": round(share_b, 6)}
        if extra:
            rec.update(extra)
        results["cases"][name] = rec
        return rec

    # ================= SETUP 1 — owner LP of A only =================
    move_r = setup(owner_seeds_b=False)
    snap_moved = snapshot()
    print(f"\n--- SETUP 1 (owner = 100% LP of A only) ---")
    print(f"external move tx: {move_r['transactionHash'].hex()} block {move_r['blockNumber']}")
    xa, ya = reserves_tka_tkb(pair_a, TKA, TKB)
    xb, yb = reserves_tka_tkb(pair_b, TKA, TKB)
    print(f"post-move: A price={ya/xa:.4f} B price={yb/xb:.4f} spread={100*(yb/xb/(ya/xa)-1):.2f}%")

    # (iv) OWN-ONE-PAIR first (gives the converged fair price P*)
    r_iv, d_iv, loan_iv, borrow_iv, repay_iv, res_a_iv, res_b_iv, res_a_iv2, res_b_iv2 = run_arb(ACCTS[0])
    pa_iv = pair_price(pair_a, TKA, TKB)
    pb_iv = pair_price(pair_b, TKA, TKB)
    p_star = (pa_iv + pb_iv) / 2
    fee_a_iv, fee_b_iv = fee_split(borrow_iv, repay_iv, res_a_iv, res_b_iv)
    gas_iv = gas_usd(r_iv)
    rec_iv = case_record("iv_own_one_pair_self_arb", lp_share(pair_a, owner), 0.0, p_star, gas_iv, {
        "tx_hash": r_iv["transactionHash"].hex(), "block": r_iv["blockNumber"],
        "guard_action": d_iv["action"], "guard_expected_net_usd": d_iv["expected_net_usd"],
        "optimal_loan_usd": loan_iv, "borrow_tka": borrow_iv / DEC,
        "repay_tkb": repay_iv / DEC, "fee_leg_a_usd": round(fee_a_iv, 4),
        "fee_leg_b_usd": round(fee_b_iv, 4),
        "price_a_after": round(pa_iv, 6), "price_b_after": round(pb_iv, 6),
        "reserves_a_before": [res_a_iv[0] / DEC, res_a_iv[1] / DEC],
        "reserves_a_after": [res_a_iv2[0] / DEC, res_a_iv2[1] / DEC],
        "reserves_b_before": [res_b_iv[0] / DEC, res_b_iv[1] / DEC],
        "reserves_b_after": [res_b_iv2[0] / DEC, res_b_iv2[1] / DEC],
        "gas_units": r_iv["gasUsed"]})
    print(f"(iv) self-arb (own A): tx {r_iv['transactionHash'].hex()[:18]}... "
          f"gas {r_iv['gasUsed']} = ${gas_iv:.4f} | P*={p_star:.4f} | "
          f"wealth=${rec_iv['owner_wealth_usd']:.2f}")

    # (iii) EXTERNAL-ARB (revert to post-move, stranger arbs)
    revert(snap_moved)
    snap_moved = snapshot()
    r_iii, d_iii, loan_iii, borrow_iii, repay_iii, res_a_iii, res_b_iii, res_a_iii2, res_b_iii2 = run_arb(ACCTS[2])
    gas_iii_owner = 0.0  # the stranger pays the gas, not the owner
    fee_a_iii, fee_b_iii = fee_split(borrow_iii, repay_iii, res_a_iii, res_b_iii)
    # the stranger's arb profit = the TKB the contract sent them (they held
    # 0 TKB before the arb — all 2 500 went into the price-moving swap).
    profit_ext = ERC20(TKB).functions.balanceOf(ext).call() / DEC
    rec_iii = case_record("iii_external_arb", lp_share(pair_a, owner), 0.0, p_star, gas_iii_owner, {
        "tx_hash": r_iii["transactionHash"].hex(), "block": r_iii["blockNumber"],
        "guard_action": d_iii["action"], "guard_expected_net_usd": d_iii["expected_net_usd"],
        "optimal_loan_usd": loan_iii, "borrow_tka": borrow_iii / DEC,
        "repay_tkb": repay_iii / DEC, "fee_leg_a_usd": round(fee_a_iii, 4),
        "fee_leg_b_usd": round(fee_b_iii, 4),
        "external_arber_profit_usd": round(profit_ext, 4),
        "reserves_a_before": [res_a_iii[0] / DEC, res_a_iii[1] / DEC],
        "reserves_a_after": [res_a_iii2[0] / DEC, res_a_iii2[1] / DEC],
        "reserves_b_before": [res_b_iii[0] / DEC, res_b_iii[1] / DEC],
        "reserves_b_after": [res_b_iii2[0] / DEC, res_b_iii2[1] / DEC],
        "gas_units": r_iii["gasUsed"],
        "gas_paid_by_stranger_usd": round(gas_usd(r_iii), 6)})
    print(f"(iii) external arb: stranger profit = ${rec_iii['external_arber_profit_usd']:.2f} "
          f"(gas paid by stranger ${rec_iii['gas_paid_by_stranger_usd']:.4f}) | "
          f"owner wealth=${rec_iii['owner_wealth_usd']:.2f}")

    # (i) HOLD (revert to post-move, no trade; value at the same P*)
    revert(snap_moved)
    rec_i = case_record("i_hold", lp_share(pair_a, owner), 0.0, p_star, 0.0, {
        "note": "no tx; LP valued at the same converged price P* as the arb cases"})
    print(f"(i) hold: owner wealth=${rec_i['owner_wealth_usd']:.2f}")

    # ================= SETUP 2 — owner LP of A AND B =================
    move_r2 = setup(owner_seeds_b=True)
    snap_moved2 = snapshot()
    print(f"\n--- SETUP 2 (owner = 100% LP of A AND B) ---")
    print(f"external move tx: {move_r2['transactionHash'].hex()} block {move_r2['blockNumber']}")

    # (ii) SELF-ARB owning both
    r_ii, d_ii, loan_ii, borrow_ii, repay_ii, res_a_ii, res_b_ii, res_a_ii2, res_b_ii2 = run_arb(ACCTS[0])
    pa_ii = pair_price(pair_a, TKA, TKB)
    pb_ii = pair_price(pair_b, TKA, TKB)
    p_star2 = (pa_ii + pb_ii) / 2
    fee_a_ii, fee_b_ii = fee_split(borrow_ii, repay_ii, res_a_ii, res_b_ii)
    gas_ii = gas_usd(r_ii)
    rec_ii = case_record("ii_self_arb_own_both", lp_share(pair_a, owner), lp_share(pair_b, owner),
                         p_star2, gas_ii, {
        "tx_hash": r_ii["transactionHash"].hex(), "block": r_ii["blockNumber"],
        "guard_action": d_ii["action"], "guard_expected_net_usd": d_ii["expected_net_usd"],
        "optimal_loan_usd": loan_ii, "borrow_tka": borrow_ii / DEC,
        "repay_tkb": repay_ii / DEC, "fee_leg_a_usd": round(fee_a_ii, 4),
        "fee_leg_b_usd": round(fee_b_ii, 4),
        "price_a_after": round(pa_ii, 6), "price_b_after": round(pb_ii, 6),
        "reserves_a_before": [res_a_ii[0] / DEC, res_a_ii[1] / DEC],
        "reserves_a_after": [res_a_ii2[0] / DEC, res_a_ii2[1] / DEC],
        "reserves_b_before": [res_b_ii[0] / DEC, res_b_ii[1] / DEC],
        "reserves_b_after": [res_b_ii2[0] / DEC, res_b_ii2[1] / DEC],
        "gas_units": r_ii["gasUsed"]})
    print(f"(ii) self-arb (own both): gas {r_ii['gasUsed']} = ${gas_ii:.4f} | P*={p_star2:.4f} | "
          f"wealth=${rec_ii['owner_wealth_usd']:.2f}")

    # HOLD-both baseline (same P*)
    revert(snap_moved2)
    rec_i2 = case_record("i_hold_both_baseline", lp_share(pair_a, owner), lp_share(pair_b, owner),
                         p_star2, 0.0, {"note": "owner LP of both, no trade, valued at P*"})
    print(f"(i-both) hold both: owner wealth=${rec_i2['owner_wealth_usd']:.2f}")

    # ---- deltas vs the matching hold
    delta_iv = rec_iv["owner_wealth_usd"] - rec_i["owner_wealth_usd"]
    delta_iii = rec_iii["owner_wealth_usd"] - rec_i["owner_wealth_usd"]
    delta_ii = rec_ii["owner_wealth_usd"] - rec_i2["owner_wealth_usd"]
    results["deltas_vs_hold_usd"] = {
        "iv_own_one_pair_minus_hold": round(delta_iv, 4),
        "iii_external_minus_hold": round(delta_iii, 4),
        "ii_own_both_minus_hold_both": round(delta_ii, 4),
        "iv_minus_iii": round(rec_iv["owner_wealth_usd"] - rec_iii["owner_wealth_usd"], 4),
    }
    print("\n=== DELTAS vs HOLD (owner, $) ===")
    for k, v in results["deltas_vs_hold_usd"].items():
        print(f"  {k}: {v:+.4f} $")
    print(f"\nplain arb profit (guard expected net): ${d_iv['expected_net_usd']:.2f} "
          f"| fee leg A: ${fee_a_iv:.4f} (returns to owner in iv) | "
          f"fee leg B: ${fee_b_iv:.4f} (goes to others in iv)")

    out = BASE / "simulation_results.json"
    json.dump(results, open(out, "w"), indent=2)
    print(f"\nresults -> {out}")
    return results


if __name__ == "__main__":
    main()
