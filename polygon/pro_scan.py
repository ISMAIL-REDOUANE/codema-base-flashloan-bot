#!/usr/bin/env python3
"""
pro_scan.py — Scan PRO Polygon v4.3 (réponse à Ismail : « mymknch Polygon
kamla mykonch fiha foras — 9leb ka wahd pro, V2 V3 V4 »).

Couverture NON mesurée jusque-là, mesurée ici LIVE (lecture seule) :
  1. INTRA-UNISWAP (priorité #1) : pour chaque paire major, TOUS les pools
     Uniswap V3 par fee tier (0,01 / 0,05 / 0,3 / 1 % via factory getPool)
     ET les pools Uniswap V4 (PoolManager, clés standard sans hooks +
     poolIds découverts via DexScreener). Spreads cross-tier ET cross-
     version (V3 vs V4) + net via polygon_guard (règle net > 0 $).
  2. MID-CAPS : LINK, AAVE, GHST, SAND, QUICK, MAI vs USDC.e / USDT sur
     Uni V3 + QuickSwap V3 (Algebra) + QuickSwap V2 / Sushi V2.
     Adresses résolues via DexScreener PUIS vérifiées on-chain
     (eth_getCode non vide + symbol() on-chain) — jamais devinées.
  3. WATCHLIST : les 5 paires à 2 venues de watchlist.json (FUL, Rp,
     VOLLAR, COMP, axlUSDC) — comptées mais jamais cotées jusqu'ici.
  4. V4 : inclus partout où un pool V4 existe (même méthode que V3).

Constat technique V4 (vérifié on-chain 2026-11-24, voir PRO_SCAN_POLYGON.md) :
  - PoolManager 0x6736… a du code (24 009 o) mais n'expose PAS getSlot0 /
    getLiquidity (sélecteurs absents du bytecode) : l'état se lit via
    extsload (pools mapping slot 6 — validé : tick <-> sqrtPrice cohérents
    sur 3 pools V4 connus).
  - Le Quoter V4 0x31AB… pointe bien vers ce PoolManager mais n'expose PAS
    quoteExactInputSingle (sélecteur absent ; tous les appels revertent
    vides) : les quotes V4 se font par réserves virtuelles (comme Algebra
    dans big_pools.py), pas par quoter. Aucune valeur n'est inventée.

Règle : net > 0 $ après TOUS les coûts (polygon_guard v4.1).
MODE = MONITOR-ONLY : lecture seule, AUCUN broadcast, AUCUNE clé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from eth_abi import encode
from eth_utils import keccak
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import big_pools as bp  # noqa: E402
from math_engine import Pool, amm_out  # noqa: E402
from polygon_gas import read_gas_price_gwei  # noqa: E402
from polygon_guard import polygon_decide, tranche, tranche_counts  # noqa: E402

MODE = "MONITOR-ONLY"
RPC_URL = "https://polygon.drpc.org"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search?q="
DEX_TOKEN_PAIRS = "https://api.dexscreener.com/token-pairs/v1/polygon/"
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"
COINGECKO_MID = ("https://api.coingecko.com/api/v3/simple/price"
                 "?ids=chainlink,aave,aavegotchi,the-sandbox,quickswap,mimatic"
                 "&vs_currencies=usd")

SIZES_USD = [1_000.0, 5_000.0, 20_000.0]

# --- Registre tokens (symbole -> infos) ; synchronisé avec bp.TOKENS ---
TOKEN_INFO: dict = {}


def register_token(symbol: str, address: str, decimals: int,
                   price_usd: float | None = None) -> dict:
    addr = Web3.to_checksum_address(address)
    info = {"address": addr, "decimals": decimals, "price_usd": price_usd}
    TOKEN_INFO[symbol] = info
    bp.TOKENS[symbol] = (addr, decimals)
    return info


for _sym, (_addr, _dec) in list(bp.TOKENS.items()):
    register_token(_sym, _addr, _dec, bp.DEFAULT_PRICES_USD.get(_sym))

# Adresses vérifiées (code + symbol on-chain, 2026-11-24).
V3_FACTORY = Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984")
POOL_MANAGER = Web3.to_checksum_address("0x67366782805870060151383f4bbff9dab53e5cd6")
# Quoter V4 0x31AB… : NON UTILISABLE (pas de quoteExactInputSingle — voir
# docstring). Gardé ici comme preuve documentée, jamais appelé.
V4_QUOTER = Web3.to_checksum_address("0x31AB0Dea31FC0ad5A54F03cD59C896eCD067447B")
V4_QUOTER_USABLE = False
ZERO_ADDRESS = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")

V3_FEE_TIERS = [100, 500, 3000, 10000]
V4_TICK_SPACINGS = {100: 1, 500: 10, 3000: 60, 10000: 200}
POOLS_MAPPING_SLOT = 6  # validé on-chain (tick <-> sqrtPrice cohérents)
DYNAMIC_FEE_FLAG = 0x800000

MAJOR_PAIRS = [
    ("WMATIC", "USDC.e"),
    ("WMATIC", "USDT"),
    ("WETH", "USDC.e"),
    ("USDC.e", "USDT"),
]
MIDCAPS = ["LINK", "AAVE", "GHST", "SAND", "QUICK", "MAI"]
MIDCAP_QUOTES = ["USDC.e", "USDT"]
COINGECKO_IDS = {"LINK": "chainlink", "AAVE": "aave", "GHST": "aavegotchi",
                 "SAND": "the-sandbox", "QUICK": "quickswap", "MAI": "mimatic"}
# Prix par défaut si CoinGecko + DexScreener sont muets (repli seulement ;
# la source effective est notée dans le rapport).
MIDCAP_DEFAULT_PRICES = {"LINK": 15.0, "AAVE": 180.0, "GHST": 0.5,
                         "SAND": 0.3, "QUICK": 0.05, "MAI": 1.0}

V3_FACTORY_ABI = [
    {"name": "getPool", "outputs": [{"type": "address"}],
     "inputs": [{"name": "tokenA", "type": "address"},
                {"name": "tokenB", "type": "address"},
                {"name": "fee", "type": "uint24"}],
     "stateMutability": "view", "type": "function"},
]
PM_EXT_ABI = [
    {"name": "extsload", "outputs": [{"type": "bytes32"}],
     "inputs": [{"name": "slot", "type": "bytes32"}],
     "stateMutability": "view", "type": "function"},
]
ERC20_ABI = [
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
ERC20_BYTES32_ABI = [
    {"name": "symbol", "outputs": [{"type": "bytes32"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]

S = requests.Session()
S.headers.update({"User-Agent": "CODEMA-pro-scan/4.3", "Accept": "application/json"})


def connect():
    return bp.connect()


# ---------------------------------------------------------------- ERC20 ---
def erc20_symbol(w3, addr: str) -> str | None:
    c = w3.eth.contract(address=addr, abi=ERC20_ABI)
    try:
        return c.functions.symbol().call()
    except Exception:  # noqa: BLE001
        pass
    c32 = w3.eth.contract(address=addr, abi=ERC20_BYTES32_ABI)
    try:
        raw = c32.functions.symbol().call()
        return raw.rstrip(b"\x00").decode("utf-8", "ignore") or None
    except Exception:  # noqa: BLE001
        return None


def erc20_decimals(w3, addr: str) -> int | None:
    c = w3.eth.contract(address=addr, abi=ERC20_ABI)
    try:
        return int(c.functions.decimals().call())
    except Exception:  # noqa: BLE001
        return None


def verify_token(w3, addr: str, expected_symbol: str) -> dict | None:
    """Vérifie un token on-chain : code non vide + symbol() == attendu.
    Retourne {"address","decimals"} ou None (à skipper, jamais deviné)."""
    try:
        addr = Web3.to_checksum_address(addr)
    except Exception:  # noqa: BLE001
        return None
    if len(w3.eth.get_code(addr)) == 0:
        return None
    if erc20_symbol(w3, addr) != expected_symbol:
        return None
    dec = erc20_decimals(w3, addr)
    if dec is None:
        return None
    return {"address": addr, "decimals": dec}


# ------------------------------------------------------------------ V3 ---
def discover_v3_tiers(w3, addr_a: str, addr_b: str) -> list:
    """Tous les pools Uni V3 d'une paire, par fee tier (factory getPool)."""
    fac = w3.eth.contract(address=V3_FACTORY, abi=V3_FACTORY_ABI)
    a, b = sorted([addr_a, addr_b], key=lambda x: x.lower())
    out = []
    for fee in V3_FEE_TIERS:
        try:
            pool = fac.functions.getPool(a, b, fee).call()
        except Exception:  # noqa: BLE001
            continue
        if pool and int(pool, 16) != 0:
            out.append({"dex": "uniswap", "pair": pool, "kind": "v3-uni",
                        "fee_tier": fee, "liq_usd": None})
    return out


# ------------------------------------------------------------------ V4 ---
def v4_pool_id(c0: str, c1: str, fee: int, tick_spacing: int, hooks: str) -> bytes:
    """PoolId V4 = keccak256(abi.encode(PoolKey))."""
    return keccak(encode(["address", "address", "uint24", "int24", "address"],
                         [Web3.to_checksum_address(c0),
                          Web3.to_checksum_address(c1),
                          fee, tick_spacing,
                          Web3.to_checksum_address(hooks)]))


def v4_pool_state(w3, pool_id: bytes) -> dict | None:
    """État d'un pool V4 via PoolManager.extsload (slot0 + liquidité).
    Layout du struct Pool V4 : slot0 à base, feeGrowthGlobal0X128 à
    base+1, feeGrowthGlobal1X128 à base+2, liquidité (uint128) à base+3.
    (CORRECTION 2026-11-24 : base+1 est feeGrowthGlobal0X128, PAS la
    liquidité — sa valeur ~1e26-1e30 gonflait les réserves virtuelles
    et fabriquait de faux spreads +62% / +13%.)
    Retourne None si le pool n'existe pas (sqrtPriceX96 == 0)."""
    pm = w3.eth.contract(address=POOL_MANAGER, abi=PM_EXT_ABI)
    base = keccak(encode(["bytes32", "uint256"], [pool_id, POOLS_MAPPING_SLOT]))
    try:
        v0 = int.from_bytes(pm.functions.extsload(base).call(), "big")
    except Exception:  # noqa: BLE001
        return None
    sqrt = v0 & (2**160 - 1)
    if sqrt == 0:
        return None
    tick = (v0 >> 160) & 0xFFFFFF
    if tick >= 2**23:
        tick -= 2**24
    lp_fee = (v0 >> 208) & 0xFFFFFF
    liq_slot = (int.from_bytes(base, "big") + 3).to_bytes(32, "big")
    try:
        liq = int.from_bytes(pm.functions.extsload(liq_slot).call(), "big")
    except Exception:  # noqa: BLE001
        liq = 0
    return {"sqrt_price_x96": sqrt, "tick": tick, "lp_fee": lp_fee,
            "liquidity": liq, "pool_id": pool_id.hex()}


def v4_virtual_reserves(state: dict, dec_a: int, dec_b: int,
                        token0_is_a: bool) -> tuple:
    """Réserves virtuelles V4 (comme Algebra) + fee en bps.
    fee_bps None si fee dynamique (inconnue -> non cotable)."""
    sqrt_p = state["sqrt_price_x96"] / 2**96
    liq = state["liquidity"]
    x_raw = liq / sqrt_p    # token0 brut
    y_raw = liq * sqrt_p    # token1 brut
    if token0_is_a:
        res_a, res_b = x_raw / 10**dec_a, y_raw / 10**dec_b
    else:
        res_a, res_b = y_raw / 10**dec_a, x_raw / 10**dec_b
    fee_bps = (state["lp_fee"] // 100
               if state["lp_fee"] != DYNAMIC_FEE_FLAG else None)
    return res_a, res_b, fee_bps


def discover_v4_standard(w3, addr_a: str, addr_b: str) -> list:
    """Pools V4 sans hooks pour une paire (clés standard par fee tier)."""
    a, b = sorted([addr_a, addr_b], key=lambda x: x.lower())
    out = []
    for fee, ts in V4_TICK_SPACINGS.items():
        pid = v4_pool_id(a, b, fee, ts, ZERO_ADDRESS)
        try:
            st = v4_pool_state(w3, pid)
        except Exception:  # noqa: BLE001
            continue
        if st and st["liquidity"] > 0:
            out.append({"dex": "uniswap-v4", "pair": "0x" + pid.hex(),
                        "kind": "v4", "fee_tier": fee,
                        "pool_id": "0x" + pid.hex(), "liq_usd": None,
                        "state": st})
    return out


# --------------------------------------------------------- DexScreener ---
def dex_token_pairs(token_addr: str) -> list:
    """Paires live d'un token sur Polygon (DexScreener token-pairs v1)."""
    try:
        r = S.get(DEX_TOKEN_PAIRS + token_addr, timeout=20)
        if r.status_code != 200:
            return []
        return [p for p in (r.json() or []) if p.get("chainId") == "polygon"]
    except Exception:  # noqa: BLE001
        return []


def dex_pairs_for_tokens(token_a_addr: str, token_b_addr: str) -> list:
    """Paires DexScreener entre deux tokens exacts (toutes venues)."""
    addrs = {token_a_addr.lower(), token_b_addr.lower()}
    out, seen = [], set()
    for tok in (token_a_addr, token_b_addr):
        for p in dex_token_pairs(tok):
            if p.get("dexId") == "balancer":
                continue
            bt = (p.get("baseToken") or {}).get("address", "").lower()
            qt = (p.get("quoteToken") or {}).get("address", "").lower()
            if {bt, qt} != addrs:
                continue
            key = ((p.get("dexId"), (p.get("pairAddress") or "").lower()))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        time.sleep(0.3)
    return out


def dex_price_usd(token_addr: str, symbol: str) -> float | None:
    """Prix USD d'un token via DexScreener (paire où il est baseToken)."""
    for p in dex_token_pairs(token_addr):
        bt = (p.get("baseToken") or {})
        if (bt.get("address", "").lower() == token_addr.lower()
                and (bt.get("symbol") or "").upper() == symbol.upper()):
            try:
                return float(p.get("priceUsd"))
            except (TypeError, ValueError):
                continue
    return None


def coingecko_mid_prices() -> dict:
    try:
        r = S.get(COINGECKO_MID, timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {sym: d[cid]["usd"] for sym, cid in COINGECKO_IDS.items()
                    if cid in d and "usd" in d[cid]}
    except Exception:  # noqa: BLE001
        pass
    return {}


def resolve_midcap(w3, symbol: str) -> dict | None:
    """Adresse d'un mid-cap : DexScreener search -> vérif on-chain.
    None = non vérifiable -> SKIP explicite (jamais deviné)."""
    queries = [symbol]
    if symbol == "MAI":
        queries.append("mimatic")
    for q in queries:
        try:
            r = S.get(DEX_SEARCH + q, timeout=20)
            if r.status_code != 200:
                continue
            cands = []
            for p in (r.json().get("pairs") or []):
                if p.get("chainId") != "polygon":
                    continue
                for side in ("baseToken", "quoteToken"):
                    t = p.get(side) or {}
                    if (t.get("symbol") or "").upper() == symbol.upper():
                        cands.append((t.get("address"),
                                      (p.get("liquidity") or {}).get("usd") or 0))
            cands.sort(key=lambda x: -x[1])
            seen = set()
            for addr, _liq in cands:
                if not addr or addr.lower() in seen:
                    continue
                seen.add(addr.lower())
                v = verify_token(w3, addr, symbol)
                if v:
                    return v
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.5)
    return None


# ------------------------------------------------------------- quoting ---
def prepare_venue(w3, venue: dict, token_a: str, token_b: str) -> dict | None:
    """Lit les réserves d'une venue ; None si illisible / liquidité nulle."""
    addr_a, dec_a = bp.TOKENS[token_a]
    addr_b, dec_b = bp.TOKENS[token_b]
    kind = venue["kind"]
    try:
        if kind == "v4":
            st = venue.get("state")
            if st is None:
                pid = bytes.fromhex(venue["pool_id"][2:])
                st = v4_pool_state(w3, pid)
            if st is None or st["liquidity"] == 0:
                venue["skip_reason"] = "pool V4 absent ou liquidité nulle"
                return None
            a0, b0 = sorted([addr_a, addr_b], key=lambda x: x.lower())
            res_a, res_b, fee = v4_virtual_reserves(
                st, dec_a, dec_b, token0_is_a=(a0.lower() == addr_a.lower()))
            if fee is None:
                venue["skip_reason"] = "fee V4 dynamique (inconnue)"
                return None
            if res_a <= 0 or res_b <= 0:
                venue["skip_reason"] = "réserves virtuelles V4 nulles"
                return None
            return {**venue, "res_a": res_a, "res_b": res_b, "fee_bps": fee}
        res_a, res_b, fee = bp.venue_reserves(w3, kind, venue["pair"],
                                              token_a, token_b)
        if res_a <= 0 or res_b <= 0:
            venue["skip_reason"] = "réserves nulles"
            return None
        return {**venue, "res_a": res_a, "res_b": res_b, "fee_bps": fee}
    except Exception as e:  # noqa: BLE001
        venue["skip_reason"] = str(e)[:100]
        return None


def quote_generic(w3, venue: dict, token_in_addr: str, token_out_addr: str,
                  amount_in_raw: int) -> tuple:
    """Quote on-chain d'un sens. Retourne (amount_out_raw, méthode).
    V3-Uni : QuoterV2 exact. V2 avec router : getAmountsOut exact.
    V2 sans router, Algebra, V4 : AMM virtuel sur réserves orientées
    (exact pour V2 constant-product ; approximation documentée pour
    V3-concentré/Algebra/V4, comme dans big_pools.py)."""
    kind = venue["kind"]
    if kind == "v3-uni":
        return bp.quote_venue(w3, kind, venue["pair"], token_in_addr,
                              token_out_addr, amount_in_raw,
                              venue.get("router"), None)
    if kind == "v2" and venue.get("router"):
        return bp.quote_venue(w3, kind, venue["pair"], token_in_addr,
                              token_out_addr, amount_in_raw,
                              venue.get("router"), None)
    dec_map = {info["address"].lower(): info["decimals"]
               for info in TOKEN_INFO.values()}
    dec_in = dec_map[token_in_addr.lower()]
    dec_out = dec_map[token_out_addr.lower()]
    sym_in = sym_out = None
    for sym, info in TOKEN_INFO.items():
        if info["address"].lower() == token_in_addr.lower():
            sym_in = sym
        if info["address"].lower() == token_out_addr.lower():
            sym_out = sym
    if venue.get("token_a") == sym_in:
        r_in, r_out = venue["res_a"], venue["res_b"]
    else:
        r_in, r_out = venue["res_b"], venue["res_a"]
    out = amm_out(amount_in_raw / 10**dec_in, r_in, r_out, venue["fee_bps"])
    return int(out * 10**dec_out), f"{kind}-virtual"


def measure_generic(w3, label: str, token_a: str, token_b: str,
                    venues: list, gas_gwei: float, prices_usd: dict) -> dict:
    """Mesure spread + net d'une paire sur une liste de venues préparées.
    Si un prix de référence manque (ex. CoinGecko/DexScreener en 429),
    la paire est SKIPée proprement au lieu de faire planter l'échantillon."""
    addr_a, dec_a = bp.TOKENS[token_a]
    addr_b, dec_b = bp.TOKENS[token_b]
    if token_a not in prices_usd or token_b not in prices_usd:
        return {"pair": label, "block": w3.eth.block_number,
                "venues": [], "skipped": [{"dex": "-", "pair": "-",
                                           "kind": "price",
                                           "reason": "prix introuvable : "
                                                     f"{token_a}/{token_b}"}],
                "sizes": {}}
    price_a_usd, price_b_usd = prices_usd[token_a], prices_usd[token_b]
    prepared = []
    skipped = []
    for v in venues:
        pv = prepare_venue(w3, v, token_a, token_b)
        if pv is not None:
            pv["token_a"], pv["token_b"] = token_a, token_b
            prepared.append(pv)
        else:
            skipped.append({"dex": v["dex"], "pair": v["pair"],
                            "kind": v.get("kind"),
                            "reason": v.get("skip_reason")})
    block = w3.eth.block_number
    sizes = {}
    for size_usd in SIZES_USD:
        buy_prices, sell_prices = [], []
        for v in prepared:
            try:
                price_a_per_b = v["res_b"] / v["res_a"] if v["res_a"] else 0
                if price_a_per_b <= 0:
                    continue
                amt_in_b = int((size_usd / price_b_usd) * 10**dec_b)
                out_a = quote_generic(w3, v, addr_b, addr_a, amt_in_b)[0]
                if out_a > 0:
                    buy_prices.append((size_usd / (out_a / 10**dec_a), v))
                amt_in_a = int((size_usd / (price_a_per_b * price_b_usd))
                               * 10**dec_a)
                out_b = quote_generic(w3, v, addr_a, addr_b, amt_in_a)[0]
                if out_b > 0:
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
        net_info = None
        try:
            pools = {}
            for venue, role in ((best_buy[1], "buy"), (best_sell[1], "sell")):
                pools[role] = Pool(
                    f"{venue['dex']}-{venue['kind']}",
                    venue["res_b"] * price_b_usd,
                    venue["res_a"],
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
    return {"pair": label, "block": block,
            "venues": [{"dex": v["dex"], "pair": v["pair"], "kind": v["kind"],
                        "fee_tier": v.get("fee_tier"),
                        "fee_bps": v.get("fee_bps"),
                        "liq_usd": v.get("liq_usd")} for v in prepared],
            "skipped": skipped,
            "sizes": sizes}


# ------------------------------------------------------------- sections ---
def section_intra_uni(w3, gas_gwei: float, prices_usd: dict) -> list:
    """Section 1 : intra-Uniswap V3 tiers + V4, paires majors."""
    out = []
    for pair in MAJOR_PAIRS:
        a, b = pair
        addr_a, addr_b = bp.TOKENS[a][0], bp.TOKENS[b][0]
        venues = discover_v3_tiers(w3, addr_a, addr_b)
        venues += discover_v4_standard(w3, addr_a, addr_b)
        # V4 découverts via DexScreener (poolIds, hooks éventuels)
        for p in dex_pairs_for_tokens(addr_a, addr_b):
            if p.get("dexId") != "uniswap-v4":
                continue
            pid = (p.get("pairAddress") or "")
            if len(pid) == 66 and pid.startswith("0x"):
                venues.append({"dex": "uniswap-v4", "pair": pid, "kind": "v4",
                               "pool_id": pid,
                               "liq_usd": (p.get("liquidity") or {}).get("usd")})
        res = measure_generic(w3, f"{a}/{b} (intra-Uni)", a, b, venues,
                              gas_gwei, prices_usd)
        res["section"] = "intra-uni"
        out.append(res)
        print(f"  intra-Uni {a}/{b} : " + ", ".join(
            f"${s}: spread {res['sizes'][s].get('spread_pct')}%"
            + (f" net {res['sizes'][s]['net'].get('expected_net_usd')}$"
               if isinstance(res['sizes'][s].get('net'), dict)
               and 'expected_net_usd' in res['sizes'][s]['net'] else "")
            for s in ("1000.0", "5000.0", "20000.0")), flush=True)
    return out


def section_midcaps(w3, gas_gwei: float, prices_usd: dict,
                    resolved: dict) -> list:
    """Section 2 : mid-caps vs USDC.e / USDT, toutes venues."""
    out = []
    for sym, info in resolved.items():
        for quote in MIDCAP_QUOTES:
            addr_a, addr_b = info["address"], bp.TOKENS[quote][0]
            venues = []
            for p in dex_pairs_for_tokens(addr_a, addr_b):
                dex = p.get("dexId")
                pair_addr = p.get("pairAddress") or ""
                liq = (p.get("liquidity") or {}).get("usd")
                if dex == "uniswap-v4" and len(pair_addr) == 66:
                    venues.append({"dex": dex, "pair": pair_addr, "kind": "v4",
                                   "pool_id": pair_addr, "liq_usd": liq})
                    continue
                if not Web3.is_address(pair_addr):
                    continue
                kind = bp.classify_pool(w3, pair_addr)
                if kind == "unknown":
                    continue
                router = None
                if kind == "v2":
                    router = (bp.QUICKSWAP_V2_ROUTER if dex == "quickswap"
                              else bp.SUSHI_V2_ROUTER if dex == "sushiswap"
                              else None)
                venues.append({"dex": dex, "pair": pair_addr, "kind": kind,
                               "router": router, "liq_usd": liq})
            res = measure_generic(w3, f"{sym}/{quote}", sym, quote, venues,
                                  gas_gwei, prices_usd)
            res["section"] = "midcaps"
            out.append(res)
            print(f"  midcap {sym}/{quote} : " + ", ".join(
                f"${s}: spread {res['sizes'][s].get('spread_pct')}%"
                + (f" net {res['sizes'][s]['net'].get('expected_net_usd')}$"
                   if isinstance(res['sizes'][s].get('net'), dict)
                   and 'expected_net_usd' in res['sizes'][s]['net'] else "")
                for s in ("1000.0", "5000.0", "20000.0")), flush=True)
    return out


def section_watchlist(w3, gas_gwei: float, prices_usd: dict) -> list:
    """Section 3 : les 5 tokens watchlist à 2 venues — enfin cotés."""
    wl_path = Path(__file__).parent / "watchlist.json"
    wl = json.loads(wl_path.read_text())
    out = []
    for tok_addr, entry in wl["tokens"].items():
        venues_map = entry.get("venues") or {}
        n_dex = len(entry.get("dexs") or [])
        if n_dex < 2 and len(venues_map) < 2:
            continue
        sym = (entry.get("name") or tok_addr).split(" / ")[0].split(" ")[0]
        # Enregistrer le token (symbole/décimales on-chain).
        if sym not in TOKEN_INFO:
            v = verify_token(w3, tok_addr, sym)
            if v is None:
                # symbole DexScreener parfois différent : on prend l'adresse
                # + décimales via on-chain sans exiger le symbole exact.
                dec = erc20_decimals(w3, tok_addr)
                if dec is None:
                    print(f"  watchlist {sym} : token non vérifiable, SKIP",
                          flush=True)
                    continue
                register_token(sym, tok_addr, dec, None)
            else:
                register_token(sym, tok_addr, v["decimals"], None)
        # Paires live DexScreener pour ce token -> contreparties.
        pairs = dex_token_pairs(tok_addr)
        by_counter: dict = {}
        for p in pairs:
            bt = (p.get("baseToken") or {})
            qt = (p.get("quoteToken") or {})
            if bt.get("address", "").lower() == tok_addr.lower():
                counter = qt
            elif qt.get("address", "").lower() == tok_addr.lower():
                counter = bt
            else:
                continue
            c_sym = (counter.get("symbol") or "").upper()
            c_addr = counter.get("address") or ""
            if not c_sym or not c_addr:
                continue
            by_counter.setdefault(c_sym, {"address": c_addr, "pairs": []})
            by_counter[c_sym]["pairs"].append(p)
        for c_sym, cdata in by_counter.items():
            c_addr = cdata["address"]
            if c_sym not in TOKEN_INFO:
                dec = erc20_decimals(w3, c_addr)
                if dec is None:
                    continue
                c_price = None
                if c_sym in ("USDT", "USDC", "USDC.E", "DAI"):
                    c_price = 1.0
                elif c_sym in ("WPOL", "WMATIC", "POL"):
                    c_price = prices_usd.get("WMATIC")
                register_token(c_sym, c_addr, dec, c_price)
            if TOKEN_INFO[c_sym]["price_usd"] is None:
                px = dex_price_usd(c_addr, c_sym)
                if px:
                    TOKEN_INFO[c_sym]["price_usd"] = px
                    prices_usd[c_sym] = px
            if TOKEN_INFO[sym]["price_usd"] is None:
                px = dex_price_usd(tok_addr, sym)
                if px:
                    TOKEN_INFO[sym]["price_usd"] = px
                    prices_usd[sym] = px
            if (TOKEN_INFO[sym]["price_usd"] is None
                    or TOKEN_INFO[c_sym]["price_usd"] is None):
                print(f"  watchlist {sym}/{c_sym} : prix introuvable, SKIP",
                      flush=True)
                continue
            # TOKEN_INFO est un cache module (persiste entre échantillons)
            # mais prices_usd est refait à chaque échantillon : resync.
            prices_usd[sym] = TOKEN_INFO[sym]["price_usd"]
            prices_usd[c_sym] = TOKEN_INFO[c_sym]["price_usd"]
            venues = []
            for p in cdata["pairs"]:
                dex = p.get("dexId")
                pair_addr = p.get("pairAddress") or ""
                liq = (p.get("liquidity") or {}).get("usd")
                if dex == "uniswap-v4" and len(pair_addr) == 66:
                    venues.append({"dex": dex, "pair": pair_addr, "kind": "v4",
                                   "pool_id": pair_addr, "liq_usd": liq})
                    continue
                if not Web3.is_address(pair_addr):
                    continue
                kind = bp.classify_pool(w3, pair_addr)
                if kind == "unknown":
                    continue
                router = None
                if kind == "v2":
                    router = (bp.QUICKSWAP_V2_ROUTER if dex == "quickswap"
                              else bp.SUSHI_V2_ROUTER if dex == "sushiswap"
                              else None)
                venues.append({"dex": dex, "pair": pair_addr, "kind": kind,
                               "router": router, "liq_usd": liq})
            if len(venues) < 2:
                print(f"  watchlist {sym}/{c_sym} : {len(venues)} venue(s) "
                      f"live (< 2), SKIP", flush=True)
                continue
            res = measure_generic(w3, f"{sym}/{c_sym} (watchlist)", sym,
                                  c_sym, venues, gas_gwei, prices_usd)
            res["section"] = "watchlist"
            out.append(res)
            print(f"  watchlist {sym}/{c_sym} : " + ", ".join(
                f"${s}: spread {res['sizes'][s].get('spread_pct')}%"
                + (f" net {res['sizes'][s]['net'].get('expected_net_usd')}$"
                   if isinstance(res['sizes'][s].get('net'), dict)
                   and 'expected_net_usd' in res['sizes'][s]['net'] else "")
                for s in ("1000.0", "5000.0", "20000.0")), flush=True)
    return out


def measure_all_sections(w3, gas_gwei: float, prices_usd: dict,
                         resolved_midcaps: dict) -> dict:
    ts = datetime.now(timezone.utc)
    sample = {"date": ts.isoformat(), "chain": "polygon", "chain_id": 137,
              "block": w3.eth.block_number,
              "gas_price_gwei": round(gas_gwei, 2),
              "gas_usd_per_trade": round(450_000 * gas_gwei * 1e-9
                                         * prices_usd["WMATIC"], 6),
              "reference_prices_usd": dict(prices_usd),
              "sections": {}}
    print(f"--- Section 1 : intra-Uni (bloc {sample['block']}) ---", flush=True)
    try:
        sample["sections"]["intra_uni"] = section_intra_uni(
            w3, gas_gwei, prices_usd)
    except Exception as e:  # noqa: BLE001 — une section ne tue pas l'échantillon
        print(f"  !! section intra_uni en erreur : {e}", flush=True)
        sample["sections"]["intra_uni"] = []
    print("--- Section 2 : mid-caps ---", flush=True)
    try:
        sample["sections"]["midcaps"] = section_midcaps(
            w3, gas_gwei, prices_usd, resolved_midcaps)
    except Exception as e:  # noqa: BLE001
        print(f"  !! section midcaps en erreur : {e}", flush=True)
        sample["sections"]["midcaps"] = []
    print("--- Section 3 : watchlist 2 venues ---", flush=True)
    try:
        sample["sections"]["watchlist"] = section_watchlist(
            w3, gas_gwei, prices_usd)
    except Exception as e:  # noqa: BLE001
        print(f"  !! section watchlist en erreur : {e}", flush=True)
        sample["sections"]["watchlist"] = []
    return sample


def aggregate(samples: list) -> dict:
    """Agrégat : meilleurs spread/net + tranches par section et au total."""
    agg = {"n_samples": len(samples), "sections": {}, "total": {}}
    all_nets: list = []
    for sec in ("intra_uni", "midcaps", "watchlist"):
        nets, spreads = [], []
        best = {"spread_pct": None, "net_usd": None, "where": None}
        n_measures = 0
        for s in samples:
            for pair in s["sections"].get(sec, []):
                for size, v in pair["sizes"].items():
                    net = v.get("net") or {}
                    if "expected_net_usd" in net:
                        n_measures += 1
                        nets.append(net["expected_net_usd"])
                        spreads.append(v.get("spread_pct"))
                        if (best["net_usd"] is None
                                or net["expected_net_usd"] > best["net_usd"]):
                            best = {"spread_pct": v.get("spread_pct"),
                                    "net_usd": net["expected_net_usd"],
                                    "where": f"{pair['pair']} ${size} "
                                             f"(bloc {pair['block']})"}
        agg["sections"][sec] = {
            "n_measures": n_measures,
            "best_spread_pct": max([x for x in spreads if x is not None],
                                   default=None),
            "best_net_usd": best["net_usd"],
            "best_where": best["where"],
            "tranches": tranche_counts(nets),
        }
        all_nets += nets
    agg["total"] = {"n_measures": len(all_nets),
                    "best_net_usd": max(all_nets) if all_nets else None,
                    "tranches": tranche_counts(all_nets)}
    return agg


def write_report(samples: list, agg: dict, resolved_midcaps: dict,
                 skipped_midcaps: list, path: Path) -> None:
    lines = []
    lines.append("# PRO SCAN Polygon v4.3 — V2 / V3 / V4, grosses pools ou petites ?")
    lines.append("")
    lines.append(f"Date : {datetime.now(timezone.utc).isoformat()} — "
                 f"{agg['n_samples']} échantillons, blocs "
                 + ", ".join(str(s["block"]) for s in samples) + ".")
    lines.append("")
    lines.append("## VERDICT")
    lines.append("")
    best = agg["total"]["best_net_usd"]
    if best is not None and best > 0:
        lines.append(f"**PROFIT TROUVÉ : meilleur net mesuré {best:.2f} $ "
                     f"({agg['sections']}) — voir détail ci-dessous.**")
    else:
        lines.append(f"**AUCUN PROFIT MESURÉ : {agg['total']['n_measures']} "
                     f"mesures, 0 net > 0 $ — meilleur net "
                     f"{best if best is not None else 'n/a'} $.**")
        lines.append("Ni V2, ni V3, ni V4 ; ni grosses pools, ni petites : "
                     "sur les échantillons mesurés, aucun spread ne couvre "
                     "les frais + gas + budget revert.")
    lines.append("")
    lines.append("## Agrégat par section")
    lines.append("")
    lines.append("| Section | Mesures | Meilleur spread | Meilleur net | "
                 ">0$ | ≥0,50$ | ≥3$ |")
    lines.append("|---|---|---|---|---|---|---|")
    for sec, a in agg["sections"].items():
        t = a["tranches"]
        lines.append(f"| {sec} | {a['n_measures']} | {a['best_spread_pct']} % | "
                     f"{a['best_net_usd']} $ | {t['>0$']} | {t['>=0.50$']} | "
                     f"{t['>=3$']} |")
    t = agg["total"]["tranches"]
    lines.append(f"| **TOTAL** | {agg['total']['n_measures']} | — | "
                 f"{agg['total']['best_net_usd']} $ | {t['>0$']} | "
                 f"{t['>=0.50$']} | {t['>=3$']} |")
    lines.append("")
    lines.append("## Mid-caps résolus (vérifiés on-chain)")
    lines.append("")
    for sym, info in resolved_midcaps.items():
        lines.append(f"- {sym} : `{info['address']}` décimales "
                     f"{info['decimals']}, prix {info.get('price_usd')} $ "
                     f"(source : {info.get('price_source')}).")
    for sym, why in skipped_midcaps:
        lines.append(f"- {sym} : SKIPPÉ — {why}.")
    lines.append("")
    lines.append("## Détail par paire et par échantillon")
    lines.append("")
    for i, s in enumerate(samples, 1):
        lines.append(f"### Échantillon {i} — {s['date']} — bloc {s['block']} "
                     f"— gas {s['gas_price_gwei']} gwei "
                     f"({s['gas_usd_per_trade']} $/trade)")
        lines.append("")
        for sec, pairs in s["sections"].items():
            for p in pairs:
                lines.append(f"**{sec} — {p['pair']}** (bloc {p['block']})")
                for v in p["venues"]:
                    lines.append(f"  - {v['dex']} / {v['kind']} "
                                 f"{v['pair'][:18]}… fee_tier "
                                 f"{v.get('fee_tier')} fee {v.get('fee_bps')} "
                                 f"bps liq {v.get('liq_usd')}")
                for sk in p.get("skipped", []):
                    lines.append(f"  - SKIP {sk['dex']} / {sk['kind']} "
                                 f"{str(sk['pair'])[:18]}… : {sk['reason']}")
                for size, v in p["sizes"].items():
                    net = v.get("net") or {}
                    lines.append(f"  - ${size} : spread {v.get('spread_pct')} % "
                                 f"| net {net.get('expected_net_usd')} $ "
                                 f"| loan optimal "
                                 f"{net.get('optimal_loan_usd')} $ "
                                 f"| {net.get('action')}")
                lines.append("")
    lines.append("## Notes techniques V4")
    lines.append("")
    lines.append("- PoolManager 0x6736… : code présent mais pas de getSlot0 / "
                 "getLiquidity (sélecteurs absents) — état lu via extsload "
                 "(pools mapping slot 6, validé : tick <-> sqrtPrice "
                 "cohérents sur 3 pools V4 connus).")
    lines.append("- Quoter V4 0x31AB… : pointe vers le bon PoolManager mais "
                 "n'expose pas quoteExactInputSingle (sélecteur absent ; "
                 "tous les appels revertent vides) — quotes V4 par réserves "
                 "virtuelles (comme Algebra), méthode notée dans les données.")
    lines.append("- Méthode : spreads = meilleur achat vs meilleure vente "
                 "sur toutes les venues de la paire ; net via polygon_guard "
                 "(flash 0 %, frais de swap, gas + budget revert) ; "
                 "tranches cumulées >0$ / ≥0,50$ / ≥3$.")
    lines.append("")
    path.write_text("\n".join(lines))
    print(f"Rapport écrit : {path}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--interval", type=int, default=180,
                    help="secondes entre échantillons")
    ap.add_argument("--out", type=str, default="pro_scan_samples.jsonl")
    args = ap.parse_args()

    w3 = connect()
    print(f"Connecté Polygon, bloc {w3.eth.block_number}", flush=True)
    # Vérification infra V4 (code présent) — sans elle, section V4 = N/A.
    print(f"PoolManager code : {len(w3.eth.get_code(POOL_MANAGER))} o ; "
          f"V4 Quoter code : {len(w3.eth.get_code(V4_QUOTER))} o "
          f"(quoter NON utilisable, voir docstring)", flush=True)

    # Résolution mid-caps (une fois — adresses stables).
    print("Résolution mid-caps (DexScreener + vérif on-chain)…", flush=True)
    cg = coingecko_mid_prices()
    resolved, skipped = {}, []
    for sym in MIDCAPS:
        info = resolve_midcap(w3, sym)
        if info is None:
            skipped.append((sym, "adresse non vérifiable on-chain "
                                 "(DexScreener sans candidat Polygon ou "
                                 "symbol/code non confirmé)"))
            print(f"  {sym} : SKIPPÉ (non vérifiable)", flush=True)
            continue
        price = dex_price_usd(info["address"], sym) or cg.get(sym) \
            or MIDCAP_DEFAULT_PRICES[sym]
        src = ("dexscreener" if dex_price_usd(info["address"], sym)
               else "coingecko" if sym in cg else "défaut")
        register_token(sym, info["address"], info["decimals"], price)
        info["price_usd"] = price
        info["price_source"] = src
        resolved[sym] = info
        print(f"  {sym} : {info['address']} dec {info['decimals']} "
              f"prix {price} $ ({src})", flush=True)

    samples = []
    for i in range(args.samples):
        print(f"=== Échantillon {i + 1}/{args.samples} "
              f"({datetime.now(timezone.utc).isoformat()}) ===", flush=True)
        gas_gwei = read_gas_price_gwei()
        prices_usd = bp.reference_prices_usd()
        for sym, info in resolved.items():
            prices_usd[sym] = info["price_usd"]
        sample = measure_all_sections(w3, gas_gwei, prices_usd, resolved)
        samples.append(sample)
        with open(args.out, "a") as f:
            f.write(json.dumps(sample) + "\n")
        fname = ("pro_scan_measurement_"
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M')}.json")
        Path(fname).write_text(json.dumps(sample, indent=2))
        print(f"Échantillon sauvé : {fname} (+ {args.out})", flush=True)
        if i + 1 < args.samples:
            print(f"Attente {args.interval}s avant l'échantillon suivant…",
                  flush=True)
            time.sleep(args.interval)

    agg = aggregate(samples)
    print("=== AGRÉGAT ===", flush=True)
    for sec, a in agg["sections"].items():
        print(f"  {sec}: {a['n_measures']} mesures, meilleur net "
              f"{a['best_net_usd']} $, tranches {a['tranches']}", flush=True)
    print(f"  TOTAL: {agg['total']['n_measures']} mesures, meilleur net "
          f"{agg['total']['best_net_usd']} $, tranches "
          f"{agg['total']['tranches']}", flush=True)
    write_report(samples, agg, resolved, skipped,
                 Path(__file__).parent / "PRO_SCAN_POLYGON.md")


if __name__ == "__main__":
    main()
