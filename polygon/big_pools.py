#!/usr/bin/env python3
"""
big_pools.py — Mesure LIVE des spreads cross-DEX sur les GROSSES pools
Polygon (v4.1).

PRIORITÉ d'Ismail (2026-11-24) : les grosses pools auraient moins de
concurrence sur Polygon. On MESURE, on ne promet rien : le spread naturel
WMATIC/USDC était 0,03 % sur le fork — très serré.

Paires majors (liquidité ≥ 500 000 $ quelque part, pas de plafond) :
  WMATIC/USDC.e, WMATIC/USDT, WETH/USDC.e, USDC.e/USDT, WMATIC/WETH,
  USDC.e/DAI — et WMATIC/USDC natif quand il existe.
Venues : Uniswap V3 Polygon (QuoterV2), QuickSwap V2 + Sushi V2
(getAmountsOut), QuickSwap V3 / Algebra (réserves virtuelles + fee live).
Les venues sont découvertes live via DexScreener (top 6 par paire) avec
un repli sur la liste statique vérifiée si DexScreener est injoignable.

Méthode par paire et par taille (1 000 $, 5 000 $, 20 000 $) :
  - tailles en $ converties en unités via le prix de référence USD du
    token (CoinGecko, repli : valeurs par défaut) et le prix propre de
    chaque venue (réserves) — chaque venue reçoit le même montant en $ ;
  - quote on-chain des deux sens sur chaque venue (QuoterV2 pour V3 Uni,
    getAmountsOut pour V2, réserves virtuelles pour Algebra) ;
  - meilleur prix d'ACHAT (le moins cher, en $ par unité) vs meilleur
    prix de VENTE (le plus cher) → spread cross-DEX ;
  - net via polygon_guard (règle v4.1 : net > 0 $ après flash 0 %,
    frais de swap, gas + budget revert) avec les réserves des pools
    (réelles V2, virtuelles V3, quote côté exprimé en $) ;
    tranches >0$ / ≥0,50$ / ≥3$.

Règle d'évaluation : le tier grosses pools devient EXÉCUTABLE seulement
si des spreads ≥ ~0,1 % (net ≥ 3 $ sur loan 5 000 $) apparaissent avec
une fréquence mesurable ; sinon il reste MONITOR-ONLY (comme les triangles).

Usage :
  python3 big_pools.py [--samples N] [--interval S] [--out FILE]
  Un échantillon = une mesure complète de toutes les paires (bloc noté).
  Les échantillons sont ajoutés à big_pools_samples.jsonl.
Simulation seulement — lecture on-chain, aucun broadcast, aucune clé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from math_engine import Pool, amm_out  # noqa: E402
from polygon_gas import read_gas_price_gwei  # noqa: E402
from polygon_guard import polygon_decide  # noqa: E402

RPC_URL = "https://polygon.drpc.org"
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"
COINGECKO = ("https://api.coingecko.com/api/v3/simple/price"
             "?ids=polygon-ecosystem-token,weth,tether,usd-coin,dai"
             "&vs_currencies=usd")

TOKENS = {
    "WMATIC": ("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", 18),
    "USDC": ("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),    # natif
    "USDC.e": ("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 6),  # bridgé
    "USDT": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),
    "WETH": ("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", 18),
    "DAI": ("0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063", 18),
}

PAIRS = [
    ("WMATIC", "USDC.e"),
    ("WMATIC", "USDT"),
    ("WETH", "USDC.e"),
    ("USDC.e", "USDT"),
    ("WMATIC", "WETH"),
    ("USDC.e", "DAI"),
    ("WMATIC", "USDC"),
]

# Liste statique vérifiée (repli si DexScreener est injoignable).
# Adresses vérifiées on-chain 2026-11-24 (classification V2 / V3 / Algebra).
STATIC_VENUES = {
    ("WMATIC", "USDC.e"): [
        ("quickswap-v2", "0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827"),
        ("uniswap-v3", "0xA374094527e1673A86dE625aa59517c5dE346d32"),
        ("sushiswap-v2", "0xcd353F79d9FADe311fC3119B841e1f456b54e858"),
        ("algebra-v3", "0xAE81FAc689A1b4b1e06e7ef4a2ab4CD8aC0A087D"),
    ],
    ("WMATIC", "USDT"): [
        ("uniswap-v3", "0x9B08288C3Be4F62bbf8d1C20Ac9C5e6f9467d8B7"),
        ("quickswap-v2", "0x604229c960e5CACF2aaEAc8Be68Ac07BA9dF81c3"),
        ("sushiswap-v2", "0x55FF76BFFC3Cdd9D5FdbBC2ece4528ECcE45047e"),
        ("algebra-v3", "0x5b41EEDCfC8e0AE47493d4945Aa1AE4fe05430ff"),
    ],
    ("WMATIC", "USDC"): [
        ("uniswap-v3", "0x2DB87C4831B2fec2E35591221455834193b50D1B"),
        ("quickswap-v2", "0x6D9e8dbB2779853db00418D4DcF96F3987CFC9D2"),
    ],
}

QUICKSWAP_V2_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
SUSHI_V2_ROUTER = "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"

SIZES_USD = [1_000.0, 5_000.0, 20_000.0]
MIN_LIQ_VENUE_USD = 10_000.0  # une venue sous 10 k $ ne compte pas (trop fine)
DEFAULT_PRICES_USD = {"WMATIC": 0.0758, "USDC": 1.0, "USDC.e": 1.0,
                      "USDT": 1.0, "WETH": 3300.0, "DAI": 1.0}

V2_PAIR_ABI = [
    {"name": "getReserves", "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
]
V2_ROUTER_ABI = [
    {"name": "getAmountsOut", "outputs": [{"type": "uint256[]"}], "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}], "stateMutability": "view", "type": "function"},
]
V3_POOL_ABI = [
    {"name": "slot0", "outputs": [{"type": "uint160"}, {"type": "int24"}, {"type": "uint16"}, {"type": "uint16"}, {"type": "uint16"}, {"type": "uint8"}, {"type": "bool"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "fee", "outputs": [{"type": "uint24"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "liquidity", "outputs": [{"type": "uint128"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
]
ALGEBRA_ABI = [
    {"name": "globalState", "outputs": [{"type": "uint160", "name": "price"}, {"type": "int24", "name": "tick"}, {"type": "uint16", "name": "fee"}, {"type": "uint16", "name": "timepointIndex"}, {"type": "uint8", "name": "communityFeeToken0"}, {"type": "uint8", "name": "communityFeeToken1"}, {"type": "bool", "name": "unlocked"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "liquidity", "outputs": [{"type": "uint128"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
]
QUOTER_ABI = [
    {"name": "quoteExactInputSingle", "outputs": [{"type": "uint256", "name": "amountOut"}, {"type": "uint160", "name": "sqrtPriceX96After"}, {"type": "uint32", "name": "initializedTicksCrossed"}, {"type": "uint256", "name": "gasEstimate"}], "inputs": [{"components": [{"type": "address", "name": "tokenIn"}, {"type": "address", "name": "tokenOut"}, {"type": "uint256", "name": "amountIn"}, {"type": "uint24", "name": "fee"}, {"type": "uint160", "name": "sqrtPriceLimitX96"}], "type": "tuple", "name": "params"}], "stateMutability": "nonpayable", "type": "function"},
]

S = requests.Session()
S.headers.update({"User-Agent": "CODEMA-big-pools/4.1", "Accept": "application/json"})


def connect():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), "RPC Polygon injoignable"
    return w3


def reference_prices_usd() -> dict:
    """Prix USD de référence (CoinGecko ; repli = valeurs par défaut)."""
    prices = dict(DEFAULT_PRICES_USD)
    try:
        r = S.get(COINGECKO, timeout=15)
        if r.status_code == 200:
            d = r.json()
            prices["WMATIC"] = d["polygon-ecosystem-token"]["usd"]
            prices["WETH"] = d["weth"]["usd"]
            prices["USDT"] = d["tether"]["usd"]
            prices["USDC"] = d["usd-coin"]["usd"]
            prices["USDC.e"] = d["usd-coin"]["usd"]
            prices["DAI"] = d["dai"]["usd"]
    except Exception:  # noqa: BLE001
        pass
    return prices


def classify_pool(w3, addr: str) -> str:
    """v2 / v3-uni / algebra / unknown — par sondage on-chain (pas deviné)."""
    if not Web3.is_address(addr or ""):
        return "unknown"
    v2 = w3.eth.contract(address=addr, abi=V2_PAIR_ABI)
    try:
        v2.functions.getReserves().call()
        return "v2"
    except Exception:  # noqa: BLE001
        pass
    v3 = w3.eth.contract(address=addr, abi=V3_POOL_ABI)
    try:
        v3.functions.slot0().call()
        return "v3-uni"
    except Exception:  # noqa: BLE001
        pass
    alg = w3.eth.contract(address=addr, abi=ALGEBRA_ABI)
    try:
        alg.functions.globalState().call()
        return "algebra"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def discover_venues(pair) -> list:
    """Top venues DexScreener pour une paire (par liquidité, Polygon)."""
    a, b = pair
    addrs = {TOKENS[a][0].lower(), TOKENS[b][0].lower()}
    out = []
    for tok in (a, b):
        try:
            r = S.get(DEX_TOKENS + TOKENS[tok][0], timeout=20)
            if r.status_code != 200:
                continue
            for p in (r.json().get("pairs") or []):
                if p.get("chainId") != "polygon":
                    continue
                # Balancer : pairAddress composite « pool-tokens » (pas une
                # adresse) — et Balancer est MORT (BIP-928) de toute façon.
                if p.get("dexId") == "balancer":
                    continue
                pair_addr = p.get("pairAddress") or ""
                if not Web3.is_address(pair_addr):
                    continue
                bt = (p.get("baseToken") or {}).get("address", "").lower()
                qt = (p.get("quoteToken") or {}).get("address", "").lower()
                if {bt, qt} != addrs:
                    continue
                liq = (p.get("liquidity") or {}).get("usd") or 0
                if liq < MIN_LIQ_VENUE_USD:
                    continue
                out.append({"dex": p.get("dexId"), "pair": p.get("pairAddress"),
                            "liq_usd": liq})
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.3)
    seen, uniq = set(), []
    for v in sorted(out, key=lambda x: -x["liq_usd"]):
        key = (v["dex"], v["pair"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(v)
    return uniq[:6]


def venue_reserves(w3, kind, addr, token_a, token_b):
    """(réserve A humaine, réserve B humaine, fee_bps) pour une venue."""
    dec_a = TOKENS[token_a][1]
    dec_b = TOKENS[token_b][1]
    if kind == "v2":
        c = w3.eth.contract(address=addr, abi=V2_PAIR_ABI)
        r0, r1, _ = c.functions.getReserves().call()
        t0 = c.functions.token0().call()
        if t0.lower() == TOKENS[token_a][0].lower():
            return r0 / 10**dec_a, r1 / 10**dec_b, 30
        return r1 / 10**dec_a, r0 / 10**dec_b, 30
    algebra = kind == "algebra"
    abi = ALGEBRA_ABI if algebra else V3_POOL_ABI
    c = w3.eth.contract(address=addr, abi=abi)
    if algebra:
        price, _tick, fee, *_ = c.functions.globalState().call()
        sqrt_p = price / 2**96
    else:
        sqrt_x96, _tick, *_ = c.functions.slot0().call()
        fee = c.functions.fee().call()
        sqrt_p = sqrt_x96 / 2**96
    liq = c.functions.liquidity().call()
    t0 = c.functions.token0().call()
    x_raw = liq / sqrt_p   # token0 brut
    y_raw = liq * sqrt_p   # token1 brut
    if t0.lower() == TOKENS[token_a][0].lower():
        return x_raw / 10**dec_a, y_raw / 10**dec_b, fee // 100
    return y_raw / 10**dec_a, x_raw / 10**dec_b, fee // 100


def quote_venue(w3, kind, addr, token_in, token_out, amount_in_raw,
                router=None, reserves=None, block_identifier="latest"):
    """Quote on-chain d'un sens. Retourne (amount_out_raw, méthode).
    token_in / token_out = adresses (décimales résolues par adresse)."""
    addr_map = {a.lower(): (s, d) for s, (a, d) in TOKENS.items()}
    dec_in = addr_map[token_in.lower()][1]
    dec_out = addr_map[token_out.lower()][1]
    if kind == "v2":
        if router:
            r = w3.eth.contract(address=router, abi=V2_ROUTER_ABI)
            amounts = r.functions.getAmountsOut(
                amount_in_raw, [token_in, token_out]).call(block_identifier=block_identifier)
            return amounts[1], "getAmountsOut"
        r_a, r_b = reserves[0], reserves[1]  # (réserve in, réserve out) humaines
        out = amm_out(amount_in_raw / 10**dec_in, r_a, r_b, 30)
        return int(out * 10**dec_out), "reserves-amm"
    if kind == "v3-uni":
        q = w3.eth.contract(address=QUOTER_V2, abi=QUOTER_ABI)
        fee = w3.eth.contract(address=addr, abi=V3_POOL_ABI).functions.fee().call(block_identifier=block_identifier)
        res = q.functions.quoteExactInputSingle(
            (token_in, token_out, amount_in_raw, fee, 0)).call(block_identifier=block_identifier)
        return res[0], "QuoterV2"
    if kind == "algebra":
        r_a, r_b, fee = reserves  # (réserve in, réserve out) humaines + fee_bps
        out = amm_out(amount_in_raw / 10**dec_in, r_a, r_b, fee)
        return int(out * 10**dec_out), "algebra-virtual"
    raise ValueError(f"kind inconnu : {kind}")


def measure_pair(w3, pair, gas_gwei, prices_usd):
    """Mesure complète d'une paire : spreads + nets par taille."""
    a, b = pair
    addr_a, dec_a = TOKENS[a]
    addr_b, dec_b = TOKENS[b]
    price_a_usd, price_b_usd = prices_usd[a], prices_usd[b]
    venues = discover_venues(pair)
    if not venues:
        venues = [{"dex": d, "pair": p, "liq_usd": None}
                  for d, p in STATIC_VENUES.get(pair, [])]
    classified = []
    for v in venues:
        kind = classify_pool(w3, v["pair"])
        if kind == "unknown":
            continue
        router = None
        if kind == "v2":
            router = (QUICKSWAP_V2_ROUTER if v["dex"] == "quickswap"
                      else SUSHI_V2_ROUTER if v["dex"] == "sushiswap" else None)
        try:
            r_a, r_b, fee = venue_reserves(w3, kind, v["pair"], a, b)
        except Exception as e:  # noqa: BLE001
            v.setdefault("errors", []).append(str(e)[:100])
            continue
        classified.append({**v, "kind": kind, "router": router,
                           "res_a": r_a, "res_b": r_b, "fee_bps": fee})
    block = w3.eth.block_number
    sizes = {}
    for size_usd in SIZES_USD:
        buy_prices, sell_prices = [], []
        for v in classified:
            try:
                # Prix propre de la venue : B par A.
                price_a_per_b = v["res_b"] / v["res_a"] if v["res_a"] else 0
                if price_a_per_b <= 0:
                    continue
                # Acheter A avec B : montant en B = size $ / prix B.
                amt_in_b = int((size_usd / price_b_usd) * 10**dec_b)
                out_a = quote_venue(w3, v["kind"], v["pair"], addr_b, addr_a,
                                    amt_in_b, v["router"],
                                    (v["res_b"], v["res_a"], v["fee_bps"]))[0]
                if out_a > 0:
                    # $ payés par unité de A.
                    buy_prices.append((size_usd / (out_a / 10**dec_a), v))
                # Vendre A contre B : montant en A = size $ / prix A.
                amt_in_a = int((size_usd / (price_a_per_b * price_b_usd))
                               * 10**dec_a)
                out_b = quote_venue(w3, v["kind"], v["pair"], addr_a, addr_b,
                                    amt_in_a, v["router"],
                                    (v["res_a"], v["res_b"], v["fee_bps"]))[0]
                if out_b > 0:
                    # $ reçus par unité de A.
                    sell_prices.append(
                        (((out_b / 10**dec_b) * price_b_usd)
                         / (amt_in_a / 10**dec_a), v))
            except Exception as e:  # noqa: BLE001
                v.setdefault("errors", []).append(str(e)[:100])
                continue
        if not buy_prices or not sell_prices:
            sizes[str(size_usd)] = {"spread_pct": None,
                                    "note": "pas assez de venues cotées"}
            continue
        best_buy = min(buy_prices, key=lambda x: x[0])
        best_sell = max(sell_prices, key=lambda x: x[0])
        spread = 100 * (best_sell[0] / best_buy[0] - 1)
        # Net via le garde v4.1 : pools des meilleures venues,
        # côté quote exprimé en $ (réserves B × prix B).
        net_info = None
        try:
            pools = {}
            for venue, role in ((best_buy[1], "buy"), (best_sell[1], "sell")):
                pools[role] = Pool(
                    f"{venue['dex']}-{venue['kind']}",
                    venue["res_b"] * price_b_usd,   # quote en $
                    venue["res_a"],                 # base en unités
                    venue["fee_bps"])
            d = polygon_decide(pools["buy"], pools["sell"], gas_gwei,
                               prices_usd["WMATIC"])
            net_info = {"action": d["action"],
                        "optimal_loan_usd": d["optimal_loan_usd"],
                        "expected_net_usd": d["expected_net_usd"],
                        "tranche": ("EXECUTE" if d["action"] == "EXECUTE"
                                    else "SKIP")}
        except Exception as e:  # noqa: BLE001
            net_info = {"error": str(e)[:150]}
        sizes[str(size_usd)] = {
            "spread_pct": round(spread, 4),
            "best_buy": {"dex": best_buy[1]["dex"], "pair": best_buy[1]["pair"],
                         "kind": best_buy[1]["kind"],
                         "price_usd_per_unit": round(best_buy[0], 6)},
            "best_sell": {"dex": best_sell[1]["dex"], "pair": best_sell[1]["pair"],
                          "kind": best_sell[1]["kind"],
                          "price_usd_per_unit": round(best_sell[0], 6)},
            "venues_quoted": len(buy_prices),
            "net": net_info,
        }
    return {"pair": f"{a}/{b}", "block": block,
            "venues": [{"dex": v["dex"], "pair": v["pair"], "kind": v["kind"],
                        "liq_usd": v.get("liq_usd"),
                        "fee_bps": v["fee_bps"]} for v in classified],
            "sizes": sizes}


def measure_all():
    w3 = connect()
    gas_gwei = read_gas_price_gwei()
    prices_usd = reference_prices_usd()
    ts = datetime.now(timezone.utc)
    sample = {"date": ts.isoformat(), "chain": "polygon", "chain_id": 137,
              "block": w3.eth.block_number,
              "gas_price_gwei": round(gas_gwei, 2),
              "gas_usd_per_trade": round(450_000 * gas_gwei * 1e-9
                                         * prices_usd["WMATIC"], 6),
              "reference_prices_usd": prices_usd,
              "pairs": []}
    for pair in PAIRS:
        try:
            res = measure_pair(w3, pair, gas_gwei, prices_usd)
            sample["pairs"].append(res)
            line = ", ".join(
                f"${s}: spread {res['sizes'][s].get('spread_pct')}%"
                + (f" net {res['sizes'][s]['net'].get('expected_net_usd')}$"
                   if isinstance(res['sizes'][s].get('net'), dict)
                   and 'expected_net_usd' in res['sizes'][s]['net'] else "")
                for s in ("1000.0", "5000.0", "20000.0"))
            print(f"  {pair[0]}/{pair[1]} : {line}")
        except Exception as e:  # noqa: BLE001
            sample["pairs"].append({"pair": f"{pair[0]}/{pair[1]}",
                                    "error": str(e)[:200]})
            print(f"  {pair[0]}/{pair[1]} : ERREUR {str(e)[:120]}")
    return sample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--interval", type=int, default=300,
                    help="secondes entre échantillons")
    ap.add_argument("--out", type=str, default="big_pools_samples.jsonl")
    args = ap.parse_args()
    for i in range(args.samples):
        print(f"=== Échantillon {i + 1}/{args.samples} "
              f"({datetime.now(timezone.utc).isoformat()}) ===")
        sample = measure_all()
        with open(args.out, "a") as f:
            f.write(json.dumps(sample) + "\n")
        fname = ("big_pools_measurement_"
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M')}.json")
        Path(fname).write_text(json.dumps(sample, indent=2))
        print(f"Échantillon sauvé : {fname} (+ {args.out})")
        if i + 1 < args.samples:
            print(f"Attente {args.interval}s avant l'échantillon suivant…")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
