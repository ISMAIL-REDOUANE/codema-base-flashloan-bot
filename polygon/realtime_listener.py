#!/usr/bin/env python3
"""
realtime_listener.py — Ecoute temps reel Polygon v4.4 (Ismail, 2026-11-25).

« Bruit des blocs, pas du polling » : au lieu de relancer un scan toutes
les 2-4 h, on s'abonne aux nouveaux blocs (websocket newHeads) et on
re-cote TOUTE la couverture pro-scan A CHAQUE BLOC (~2 s) :
  - intra-Uniswap : paires majors, tous tiers V3 (0,01/0,05/0,3/1 %) + V4
  - mid-caps : LINK, AAVE, GHST, SAND, QUICK, MAI vs USDC.e / USDT
  - watchlist : paires a 2 venues (axlUSDC/USDC, ...)
Evaluation net > 0 $ via polygon_guard (flash 0 %, frais de swap, gas +
budget revert, gas = baseFee du bloc, sinon 0,0095 $ prudent).

EFFICACITE : 1 seul appel Multicall3 aggregate3 par bloc (~78 lectures
d'etat) + calcul local (approximation reserves virtuelles, meme methode
documentee que big_pools.py / pro_scan.py pour Algebra et V4 ; exacte
pour V2). Si Multicall3 est indisponible, repli = rotation d'un sous-
ensemble de paires par bloc (lectures individuelles), declaree
explicitement. Aucun appel HTTP DexScreener / CoinGecko par bloc
(les prix de reference sont rafraichis toutes les 10 min, au mieux).

MODE = MONITOR-ONLY : lecture seule + eth_call. Aucun envoi on-chain,
aucun portefeuille, aucune cle. Un signal net > 0 $ est LOGUE (pas
execute) puis re-verifie par quote exacte (QuoterV2 / getAmountsOut)
quand c'est possible ; la porte d'audit avant tout usage live reste
en place.

Transport : wss newHeads (drpc d'abord, publicnode en repli). Si aucun
wss ne fonctionne : polling rapide eth_blockNumber toutes les 2 s.
Reconnexion avec backoff ; apres N echecs, arret propre (fail-closed),
jamais de boucle infinie.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets
from eth_abi import decode, encode
from eth_utils import keccak
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import big_pools as bp  # noqa: E402
from math_engine import Pool, amm_out  # noqa: E402
from polygon_guard import (ONCHAIN_MIN_PROFIT_USD, polygon_costs,
                         polygon_decide, tranche)  # noqa: E402

try:
    import pro_scan as ps  # noqa: E402
    HAS_PRO_SCAN = True
except Exception:  # noqa: BLE001 - pro_scan en cours d'edition par un autre agent
    ps = None  # type: ignore
    HAS_PRO_SCAN = False

MODE = "MONITOR-ONLY"
RPC_URL = "https://polygon.drpc.org"
MULTICALL3 = Web3.to_checksum_address(
    "0xcA11bde05977b3631167028862bE2a173976CA11")
MULTICALL3_ABI = [{
    "name": "aggregate3",
    "outputs": [{"components": [
        {"name": "success", "type": "bool"},
        {"name": "returnData", "type": "bytes"}],
        "name": "returnData", "type": "tuple[]"}],
    "inputs": [{"components": [
        {"name": "target", "type": "address"},
        {"name": "allowFailure", "type": "bool"},
        {"name": "callData", "type": "bytes"}],
        "name": "calls", "type": "tuple[]"}],
    "stateMutability": "view", "type": "function"}]

WSS_ENDPOINTS = [
    "wss://polygon.drpc.org",
    "wss://polygon-bor-rpc.publicnode.com",
]
SIZES_USD = [1_000.0, 5_000.0, 20_000.0]
MAX_SUBCALLS_PER_BATCH = 100
DEFAULT_GAS_GWEI = 279.0       # repli si baseFee absente
DEFAULT_MATIC_PRICE = 0.0758
PRICE_REFRESH_SECONDS = 600
BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30]
MAX_RECONNECTS = 10
MULTICALL_RETRIES = 3  # tentatives aggregate3 avant bascule rotation
POLL_INTERVAL_SECONDS = 2.0
V2_PAIR_ABI_MIN = [
    {"name": "getReserves", "outputs": [{"type": "uint112"},
                                        {"type": "uint112"},
                                        {"type": "uint32"}],
     "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
V3_POOL_ABI_MIN = [
    {"name": "slot0", "outputs": [{"type": "uint160"}, {"type": "int24"},
                                  {"type": "uint16"}, {"type": "uint16"},
                                  {"type": "uint16"}, {"type": "uint8"},
                                  {"type": "bool"}],
     "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "liquidity", "outputs": [{"type": "uint128"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "fee", "outputs": [{"type": "uint24"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
ALGEBRA_ABI_MIN = [
    {"name": "globalState", "outputs": [{"type": "uint160"},
                                        {"type": "int24"},
                                        {"type": "uint16"},
                                        {"type": "uint16"},
                                        {"type": "uint8"},
                                        {"type": "uint8"},
                                        {"type": "bool"}],
     "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "liquidity", "outputs": [{"type": "uint128"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
PM_EXT_ABI_MIN = [
    {"name": "extsload", "outputs": [{"type": "bytes32"}],
     "inputs": [{"name": "slot", "type": "bytes32"}],
     "stateMutability": "view", "type": "function"},
]
POOL_MANAGER = Web3.to_checksum_address(
    "0x67366782805870060151383f4bbff9dab53e5cd6")
POOLS_MAPPING_SLOT = 6
DYNAMIC_FEE_FLAG = 0x800000

# Selecteurs calcules (jamais codes en dur a la main).
SEL = {name: Web3.keccak(text=sig)[:4] for name, sig in {
    "getReserves": "getReserves()",
    "slot0": "slot0()",
    "liquidity": "liquidity()",
    "fee": "fee()",
    "token0": "token0()",
    "globalState": "globalState()",
    "extsload": "extsload(bytes32)",
}.items()}


def backoff_delay(attempt: int) -> float:
    """Delai de reconnexion (s) : 1, 2, 4, 8, 16, 30, 30, ..."""
    if attempt < 0:
        return BACKOFF_SECONDS[0]
    idx = min(attempt, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[idx]


def chunk_calls(calls: list, max_n: int = MAX_SUBCALLS_PER_BATCH) -> list:
    """Decoupe une liste d'appels Multicall en lots de max_n."""
    return [calls[i:i + max_n] for i in range(0, len(calls), max_n)]


def v4_pool_id_local(c0: str, c1: str, fee: int, tick_spacing: int,
                     hooks: str) -> bytes:
    """PoolId V4 = keccak256(abi.encode(PoolKey)) — repli local si
    pro_scan n'est pas importable."""
    return keccak(encode(
        ["address", "address", "uint24", "int24", "address"],
        [Web3.to_checksum_address(c0), Web3.to_checksum_address(c1),
         fee, tick_spacing, Web3.to_checksum_address(hooks)]))


def v4_slots(pool_id: bytes) -> tuple:
    """Slots extsload d'un pool V4 : slot0 a la base, liquidite a base+3."""
    base = keccak(encode(["bytes32", "uint256"],
                         [pool_id, POOLS_MAPPING_SLOT]))
    liq = (int.from_bytes(base, "big") + 3).to_bytes(32, "big")
    return base, liq


# ------------------------------------------------------------------ inventaire
def latest_pro_scan_measurement() -> Path | None:
    """Dernier fichier de mesure pro_scan (inventaire des venues)."""
    files = sorted(
        glob.glob(str(Path(__file__).parent
                      / "pro_scan_measurement_*.json")),
        key=lambda p: Path(p).stat().st_mtime)
    return Path(files[-1]) if files else None


def parse_pair_label(label: str) -> tuple:
    """'WMATIC/USDC.e (intra-Uni)' -> ('WMATIC', 'USDC.e')."""
    core = label.split(" (")[0]
    a, b = core.split("/")
    return a.strip(), b.strip()


def load_inventory_from_measurement(path: Path) -> dict:
    """Inventaire (paires + venues) depuis un fichier de mesure pro_scan.
    Retourne {"pairs": [...], "prices": {...}, "gas_gwei": float}."""
    data = json.loads(path.read_text())
    pairs = []
    for section, plist in data.get("sections", {}).items():
        for p in plist:
            token_a, token_b = parse_pair_label(p["pair"])
            venues = []
            for v in p.get("venues", []):
                venues.append({
                    "dex": v.get("dex"), "pair": v.get("pair"),
                    "kind": v.get("kind"), "fee_tier": v.get("fee_tier"),
                    "fee_bps": v.get("fee_bps"),
                    "liq_usd": v.get("liq_usd")})
            pairs.append({"label": p["pair"], "section": section,
                          "token_a": token_a, "token_b": token_b,
                          "venues": venues})
    return {"pairs": pairs,
            "prices": dict(data.get("reference_prices_usd", {})),
            "gas_gwei": float(data.get("gas_price_gwei")
                              or DEFAULT_GAS_GWEI),
            "source": str(path)}


def resolve_tokens(w3, inventory: dict) -> dict:
    """Adresses + decimales de tous les tokens de l'inventaire.
    Majors : big_pools.TOKENS. Mid-caps : pro_scan.resolve_midcap
    (DexScreener + verif on-chain). Watchlist : watchlist.json +
    pro_scan.verify_token. Retourne {sym: {"address","decimals"}}.
    Un token non resolvable fait SKIPPER ses paires (jamais devine)."""
    resolved = {}
    for sym, (addr, dec) in bp.TOKENS.items():
        resolved[sym] = {"address": addr, "decimals": dec}
    needed = set()
    for pair in inventory["pairs"]:
        needed.add(pair["token_a"])
        needed.add(pair["token_b"])
    wl_path = Path(__file__).parent / "watchlist.json"
    wl_tokens = {}
    if wl_path.exists():
        try:
            wl_tokens = json.loads(wl_path.read_text()).get("tokens", {})
        except Exception:  # noqa: BLE001
            wl_tokens = {}
    for sym in sorted(needed):
        if sym in resolved:
            continue
        info = None
        if ps is not None and hasattr(ps, "resolve_midcap"):
            try:
                info = ps.resolve_midcap(w3, sym)
            except Exception:  # noqa: BLE001
                info = None
        if info is None:
            for addr, entry in wl_tokens.items():
                name = (entry.get("name") or "").split(" / ")[0].split(" ")[0]
                if name.upper() == sym.upper():
                    if ps is not None and hasattr(ps, "verify_token"):
                        info = ps.verify_token(w3, addr, sym)
                    if info is None:
                        dec = ps.erc20_decimals(w3, addr) if ps else None
                        if dec is not None:
                            info = {"address": addr, "decimals": dec}
                    break
        if info is not None:
            resolved[sym] = {"address": info["address"],
                             "decimals": info["decimals"]}
            if ps is not None and hasattr(ps, "register_token"):
                try:
                    ps.register_token(
                        sym, info["address"], info["decimals"],
                        inventory["prices"].get(sym))
                except Exception:  # noqa: BLE001
                    pass
    return resolved


def resolve_prices(w3, inventory: dict, resolved: dict) -> dict:
    """Prix USD de reference : fichier de mesure, puis DexScreener
    (pro_scan.dex_price_usd) pour les absents (ex. axlUSDC)."""
    prices = dict(inventory["prices"])
    for sym in resolved:
        if sym in prices and prices[sym]:
            continue
        px = None
        if ps is not None and hasattr(ps, "dex_price_usd"):
            try:
                px = ps.dex_price_usd(resolved[sym]["address"], sym)
            except Exception:  # noqa: BLE001
                px = None
        if px:
            prices[sym] = px
    return prices


def prepare_static_venue(w3, venue: dict, token_a: str,
                         token_b: str) -> dict | None:
    """Donnees statiques d'une venue (lues UNE fois au demarrage) :
    token0 et fee (V3). Pour V4 : slots extsload. None si illisible."""
    kind = venue["kind"]
    addr = venue["pair"]
    try:
        if kind == "v4":
            pid = bytes.fromhex(addr[2:])
            slot0, liq_slot = v4_slots(pid)
            return {**venue, "pool_id": addr, "slot0_slot": slot0,
                    "liq_slot": liq_slot}
        if kind == "v2":
            c = w3.eth.contract(address=addr, abi=V2_PAIR_ABI_MIN)
            t0 = c.functions.token0().call()
            # Router reconstruit par dex (absent du JSON de mesure) :
            # QuickSwap V2 / Sushi V2, sinon None (AMM local).
            router = None
            if (venue.get("dex") or "") == "quickswap":
                router = bp.QUICKSWAP_V2_ROUTER
            elif (venue.get("dex") or "") == "sushiswap":
                router = bp.SUSHI_V2_ROUTER
            return {**venue, "token0": t0, "fee_bps": 30,
                    "router": router}
        if kind == "v3-uni":
            c = w3.eth.contract(address=addr, abi=V3_POOL_ABI_MIN)
            t0 = c.functions.token0().call()
            fee = c.functions.fee().call()
            return {**venue, "token0": t0, "fee_bps": fee // 100}
        if kind == "algebra":
            c = w3.eth.contract(address=addr, abi=ALGEBRA_ABI_MIN)
            t0 = c.functions.token0().call()
            return {**venue, "token0": t0}  # fee lue par bloc (dynamique)
    except Exception as e:  # noqa: BLE001
        venue["skip_reason"] = str(e)[:100]
        return None
    return None


# ------------------------------------------------------- lecture Multicall
def build_multicall_calls(pairs: list) -> tuple:
    """Construit la liste des sous-appels Multicall3 pour toutes les
    venues, et la table de decodage [(pair_idx, venue_idx, kind, slot)].
    Retourne (calls, decoding)."""
    calls, decoding = [], []
    for pi, pair in enumerate(pairs):
        for vi, v in enumerate(pair["venues"]):
            if v.get("skip"):
                continue
            kind = v["kind"]
            addr = v["pair"]
            if kind == "v2":
                calls.append((addr, True, SEL["getReserves"]))
                decoding.append((pi, vi, "v2-reserves"))
            elif kind == "v3-uni":
                calls.append((addr, True, SEL["slot0"]))
                decoding.append((pi, vi, "v3-slot0"))
                calls.append((addr, True, SEL["liquidity"]))
                decoding.append((pi, vi, "v3-liquidity"))
            elif kind == "algebra":
                calls.append((addr, True, SEL["globalState"]))
                decoding.append((pi, vi, "alg-state"))
                calls.append((addr, True, SEL["liquidity"]))
                decoding.append((pi, vi, "alg-liquidity"))
            elif kind == "v4":
                calls.append((POOL_MANAGER, True,
                              SEL["extsload"] + v["slot0_slot"]))
                decoding.append((pi, vi, "v4-slot0"))
                calls.append((POOL_MANAGER, True,
                              SEL["extsload"] + v["liq_slot"]))
                decoding.append((pi, vi, "v4-liquidity"))
    return calls, decoding


def multicall_aggregate3(w3, calls: list,
                         block_identifier=None) -> list | None:
    """Un appel aggregate3 (eventuellement par lots). Retourne la liste
    des (success, returnData) ou None en cas d'echec total."""
    if not calls:
        return []
    mc = w3.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)
    out = []
    for batch in chunk_calls(calls):
        try:
            res = mc.functions.aggregate3(batch).call(
                block_identifier=block_identifier)
        except Exception:  # noqa: BLE001
            return None
        out.extend([(bool(s), bytes(d)) for s, d in res])
    return out


def decode_states(results: list, decoding: list, pairs: list,
                  resolved: dict) -> None:
    """Decode les retours Multicall et remplit res_a / res_b / fee_bps
    de chaque venue (unites humaines). Les venues en echec sont
    marquees skip pour ce bloc."""
    raw = {}
    for (pi, vi, slot), (ok, data) in zip(decoding, results):
        if not ok or not data:
            raw.setdefault((pi, vi), {})[slot] = None
            continue
        try:
            if slot == "v2-reserves":
                r0, r1, _ts = decode(
                    ["uint112", "uint112", "uint32"], data)
                raw.setdefault((pi, vi), {})[slot] = (r0, r1)
            elif slot == "v3-slot0":
                sqrt_x96 = decode(
                    ["uint160", "int24", "uint16", "uint16", "uint16",
                     "uint8", "bool"], data)[0]
                raw.setdefault((pi, vi), {})[slot] = sqrt_x96
            elif slot in ("v3-liquidity", "alg-liquidity", "v4-liquidity"):
                liq = decode(["uint128"], data)[0]
                raw.setdefault((pi, vi), {})[slot] = liq
            elif slot == "alg-state":
                price, _tick, fee = decode(
                    ["uint160", "int24", "uint16", "uint16", "uint8",
                     "uint8", "bool"], data)[:3]
                raw.setdefault((pi, vi), {})[slot] = (price, fee)
            elif slot == "v4-slot0":
                v0 = int.from_bytes(decode(["bytes32"], data)[0], "big")
                raw.setdefault((pi, vi), {})[slot] = v0
        except Exception:  # noqa: BLE001
            raw.setdefault((pi, vi), {})[slot] = None
    for pi, pair in enumerate(pairs):
        token_a, token_b = pair["token_a"], pair["token_b"]
        dec_a = resolved[token_a]["decimals"]
        dec_b = resolved[token_b]["decimals"]
        addr_a = resolved[token_a]["address"].lower()
        for vi, v in enumerate(pair["venues"]):
            if v.get("skip"):
                continue
            kind = v["kind"]
            st = raw.get((pi, vi), {})
            try:
                if kind == "v2":
                    r = st.get("v2-reserves")
                    if r is None:
                        raise ValueError("getReserves vide")
                    r0, r1 = r
                    t0 = v["token0"].lower()
                    if t0 == addr_a:
                        res_a, res_b = r0 / 10**dec_a, r1 / 10**dec_b
                    else:
                        res_a, res_b = r1 / 10**dec_a, r0 / 10**dec_b
                    v["res_a"], v["res_b"] = res_a, res_b
                    v["fee_bps"] = 30
                elif kind == "v3-uni":
                    sqrt_x96, liq = st.get("v3-slot0"), st.get("v3-liquidity")
                    if sqrt_x96 is None or liq is None or liq == 0:
                        raise ValueError("slot0/liquidite vides")
                    sqrt_p = sqrt_x96 / 2**96
                    x_raw, y_raw = liq / sqrt_p, liq * sqrt_p
                    t0 = v["token0"].lower()
                    if t0 == addr_a:
                        res_a, res_b = (x_raw / 10**dec_a,
                                        y_raw / 10**dec_b)
                    else:
                        res_a, res_b = (y_raw / 10**dec_a,
                                        x_raw / 10**dec_b)
                    v["res_a"], v["res_b"] = res_a, res_b
                elif kind == "algebra":
                    gs, liq = st.get("alg-state"), st.get("alg-liquidity")
                    if gs is None or liq is None or liq == 0:
                        raise ValueError("globalState/liquidite vides")
                    price, fee = gs
                    sqrt_p = price / 2**96
                    x_raw, y_raw = liq / sqrt_p, liq * sqrt_p
                    t0 = v["token0"].lower()
                    if t0 == addr_a:
                        res_a, res_b = (x_raw / 10**dec_a,
                                        y_raw / 10**dec_b)
                    else:
                        res_a, res_b = (y_raw / 10**dec_a,
                                        x_raw / 10**dec_b)
                    v["res_a"], v["res_b"] = res_a, res_b
                    v["fee_bps"] = fee // 100
                elif kind == "v4":
                    v0, liq = st.get("v4-slot0"), st.get("v4-liquidity")
                    if v0 is None or liq is None or liq == 0:
                        raise ValueError("extsload/liquidite vides")
                    sqrt = v0 & (2**160 - 1)
                    if sqrt == 0:
                        raise ValueError("sqrtPrice V4 nul")
                    sqrt_p = sqrt / 2**96
                    x_raw, y_raw = liq / sqrt_p, liq * sqrt_p
                    a0 = sorted([addr_a,
                                 resolved[token_b]["address"].lower()])[0]
                    if a0 == addr_a:
                        res_a, res_b = (x_raw / 10**dec_a,
                                        y_raw / 10**dec_b)
                    else:
                        res_a, res_b = (y_raw / 10**dec_a,
                                        x_raw / 10**dec_b)
                    v["res_a"], v["res_b"] = res_a, res_b
                    state = {"sqrt_price_x96": sqrt, "liquidity": liq,
                             "lp_fee": (v0 >> 208) & 0xFFFFFF}
                    if ps is not None and hasattr(ps, "v4_virtual_reserves"):
                        _ra, _rb, fee = ps.v4_virtual_reserves(
                            state, dec_a, dec_b, a0 == addr_a)
                        v["fee_bps"] = fee
                    else:
                        lp_fee = state["lp_fee"]
                        v["fee_bps"] = (lp_fee // 100 if lp_fee
                                        != DYNAMIC_FEE_FLAG else None)
                    if v.get("fee_bps") is None:
                        raise ValueError("fee V4 dynamique (inconnue)")
                if v.get("res_a", 0) <= 0 or v.get("res_b", 0) <= 0:
                    raise ValueError("reserves nulles")
            except Exception as e:  # noqa: BLE001
                v["skip_reason"] = str(e)[:100]
                v.pop("res_a", None)
                v.pop("res_b", None)


def quote_local(venue: dict, token_in_addr: str, token_out_addr: str,
                amount_in_raw: int, resolved: dict) -> int:
    """Quote locale (aucun appel reseau) : AMM sur reserves virtuelles.
    Exacte pour V2 ; approximation documentee pour V3-concentre /
    Algebra / V4 (meme methode que pro_scan.quote_generic, branche
    virtuelle)."""
    dec_in = resolved_by_addr(resolved, token_in_addr)["decimals"]
    dec_out = resolved_by_addr(resolved, token_out_addr)["decimals"]
    addr_a = venue["_addr_a"].lower()
    if token_in_addr.lower() == addr_a:
        r_in, r_out = venue["res_a"], venue["res_b"]
    else:
        r_in, r_out = venue["res_b"], venue["res_a"]
    out = amm_out(amount_in_raw / 10**dec_in, r_in, r_out,
                  venue["fee_bps"])
    return int(out * 10**dec_out)


def resolved_by_addr(resolved: dict, addr: str) -> dict:
    for info in resolved.values():
        if info["address"].lower() == addr.lower():
            return info
    raise ValueError(f"adresse inconnue : {addr}")


def evaluate_pair(pair: dict, gas_gwei: float, matic_price: float,
                  prices_usd: dict, resolved: dict, block: int) -> dict:
    """Evalue une paire sur ses venues preparees (reserves fraiches).
    Meme logique que pro_scan.measure_generic, en local uniquement.
    Retourne {"pair","block","sizes":{...}} avec spread + net par taille."""
    token_a, token_b = pair["token_a"], pair["token_b"]
    addr_a = resolved[token_a]["address"]
    addr_b = resolved[token_b]["address"]
    dec_a = resolved[token_a]["decimals"]
    dec_b = resolved[token_b]["decimals"]
    price_a = prices_usd.get(token_a)
    price_b = prices_usd.get(token_b)
    if not price_a or not price_b:
        return {"pair": pair["label"], "block": block, "sizes": {},
                "skipped_reason": "prix de reference manquant"}
    prepared = []
    for v in pair["venues"]:
        if v.get("skip") or "res_a" not in v or "res_b" not in v:
            continue
        v["_addr_a"] = addr_a
        prepared.append(v)
    sizes = {}
    for size_usd in SIZES_USD:
        buy_prices, sell_prices = [], []
        for v in prepared:
            try:
                price_a_per_b = v["res_b"] / v["res_a"] if v["res_a"] else 0
                if price_a_per_b <= 0:
                    continue
                amt_in_b = int((size_usd / price_b) * 10**dec_b)
                out_a = quote_local(v, addr_b, addr_a, amt_in_b, resolved)
                if out_a > 0:
                    buy_prices.append((size_usd / (out_a / 10**dec_a), v))
                amt_in_a = int((size_usd / (price_a_per_b * price_b))
                               * 10**dec_a)
                out_b = quote_local(v, addr_a, addr_b, amt_in_a, resolved)
                if out_b > 0:
                    sell_prices.append(
                        (((out_b / 10**dec_b) * price_b)
                         / (amt_in_a / 10**dec_a), v))
            except Exception:  # noqa: BLE001
                continue
        if not buy_prices or not sell_prices:
            sizes[str(size_usd)] = {"spread_pct": None,
                                    "note": "pas assez de venues cotees"}
            continue
        best_buy = min(buy_prices, key=lambda x: x[0])
        best_sell = max(sell_prices, key=lambda x: x[0])
        spread = 100 * (best_sell[0] / best_buy[0] - 1)
        net_info = None
        try:
            pools = {}
            for venue, role in ((best_buy[1], "buy"),
                                (best_sell[1], "sell")):
                pools[role] = Pool(
                    f"{venue['dex']}-{venue['kind']}",
                    venue["res_b"] * price_b, venue["res_a"],
                    venue["fee_bps"])
            d = polygon_decide(pools["buy"], pools["sell"], gas_gwei,
                               matic_price)
            net_info = {"action": d["action"],
                        "optimal_loan_usd": d["optimal_loan_usd"],
                        "expected_net_usd": d["expected_net_usd"],
                        "tranche": ("EXECUTE" if d["action"] == "EXECUTE"
                                    else "SKIP"),
                        "gas_trade_usd": d["gas_trade_usd"],
                        "total_cost_usd": d["total_cost_usd"]}
        except Exception as e:  # noqa: BLE001
            net_info = {"error": str(e)[:150]}
        sizes[str(size_usd)] = {
            "spread_pct": round(spread, 4),
            "best_buy": {"dex": best_buy[1]["dex"],
                         "pair": best_buy[1]["pair"],
                         "kind": best_buy[1]["kind"],
                         "price_usd_per_unit": round(best_buy[0], 6)},
            "best_sell": {"dex": best_sell[1]["dex"],
                          "pair": best_sell[1]["pair"],
                          "kind": best_sell[1]["kind"],
                          "price_usd_per_unit": round(best_sell[0], 6)},
            "venues_quoted": len(buy_prices),
            "net": net_info}
    return {"pair": pair["label"], "block": block, "sizes": sizes,
            "section": pair.get("section")}


def _exact_quote(w3, venue: dict, token_in_addr: str, token_out_addr: str,
                 amount_in_raw: int, resolved: dict, block="latest") -> tuple:
    """Quote exacte d'une jambe : QuoterV2 (V3-Uni), getAmountsOut
    (V2 avec router). V2 sans router : AMM local sur reserves orientees
    (meme methode que la quote virtuelle)."""
    kind = venue["kind"]
    if kind in ("v3-uni", "v2"):
        router = venue.get("router")
        if kind == "v3-uni" or router:
            return bp.quote_venue(w3, kind, venue["pair"], token_in_addr,
                                  token_out_addr, amount_in_raw, router,
                                  None, block_identifier=block)
        # Local reserve snapshots are not exact on-chain verification.
        raise ValueError("V2 without a verified router cannot pass exact verification")
    raise ValueError(f"pas de quote exacte pour kind={kind}")


def _exact_cycle_net(w3, buy_v: dict, sell_v: dict, addr_a: str,
                     addr_b: str, dec_a: int, dec_b: int, size_usd: float,
                     price_b: float, gas_gwei: float, matic_price: float,
                     resolved: dict, block="latest") -> dict:
    """Un aller-retour EXACT chaîné (audit #10) : l'achat B -> A est
    quoté on-chain, puis sa sortie EXACTE out_a devient l'entrée de la
    vente A -> B (jamais un montant recalculé depuis un prix spot).
    Le net = retour en $ - mise - frais flash exacts (Morpho 0 %) - gas
    exact (trade + budget revert, polygon_costs). Tout en $ (pas de %).
    """
    amt_in_b = int((size_usd / price_b) * 10**dec_b)
    out_a = _exact_quote(w3, buy_v, addr_b, addr_a, amt_in_b, resolved, block)[0]
    if out_a <= 0:
        raise ValueError("quote achat nulle")
    out_b = _exact_quote(w3, sell_v, addr_a, addr_b, out_a, resolved, block)[0]
    if out_b <= 0:
        raise ValueError("quote vente nulle")
    usdc_back = (out_b / 10**dec_b) * price_b
    total_gas = polygon_costs(gas_gwei, matic_price).gas_usd
    buy_price = size_usd / (out_a / 10**dec_a)
    sell_price = usdc_back / (out_a / 10**dec_a)
    return {"size_usd": size_usd,
            "out_a_raw": out_a, "out_b_raw": out_b,
            "usdc_back": usdc_back,
            "gross_usd": usdc_back - size_usd,
            "flash_fee_usd": 0.0,  # Morpho 0 % — le seul provider autorisé
            "gas_total_usd": total_gas,
            "net_usd": usdc_back - size_usd - total_gas,
            "spread_pct": 100 * (sell_price / buy_price - 1)}


def verify_signal_exact(w3, pair: dict, size_usd: float, meas: dict,
                        prices_usd: dict, resolved: dict,
                        block: int) -> dict | None:
    """Re-vérification d'un signal par quotes EXACTES chaînées (audit
    #10 — CORRIGÉ).

    AVANT (bug confirmé par l'audit) : l'entrée de vente était recalculée
    depuis un prix spot (res_b/res_a) au lieu de out_a, et le net venait
    de polygon_decide sur réserves approximatives — le net ne dépendait
    PAS de la quote de vente (contre-exemple : vente à 1 $ -> toujours
    +0,47 $ EXECUTE).

    APRÈS : les deux jambes sont chaînées (out_a = entrée de vente),
    le retour est converti en $ depuis out_b, les coûts exacts sont
    soustraits, et le verdict découle de ce net à la taille testée.
    Si la taille optimale approximative (polygon_decide) diffère de
    > 10 % de la taille testée, on re-quote exactement à cette taille et
    on garde le meilleur des deux nets. Retourne None si la vérification
    n'est pas possible (Algebra / V4 : pas de quoter exact ; venues
    introuvables).
    """
    token_a, token_b = pair["token_a"], pair["token_b"]
    addr_a = resolved[token_a]["address"]
    addr_b = resolved[token_b]["address"]
    dec_a = resolved[token_a]["decimals"]
    dec_b = resolved[token_b]["decimals"]
    price_b = prices_usd[token_b]
    buy_v = next((v for v in pair["venues"]
                  if v["pair"] == meas["best_buy"]["pair"]), None)
    sell_v = next((v for v in pair["venues"]
                   if v["pair"] == meas["best_sell"]["pair"]), None)
    if buy_v is None or sell_v is None:
        return None
    if buy_v["kind"] in ("algebra", "v4") \
            or sell_v["kind"] in ("algebra", "v4"):
        return None  # pas de quoter exact : verification impossible
    gas_gwei = meas.get("gas_gwei", DEFAULT_GAS_GWEI)
    matic_price = prices_usd.get("WMATIC", DEFAULT_MATIC_PRICE)
    try:
        best = _exact_cycle_net(w3, buy_v, sell_v, addr_a, addr_b, dec_a,
                                dec_b, size_usd, price_b, gas_gwei,
                                matic_price, resolved, block)
        # Revalidation de la taille optimale (audit #10) : si
        # polygon_decide suggère une autre taille, on la re-quote
        # exactement et on garde le meilleur net des deux.
        optimal = (meas.get("net") or {}).get("optimal_loan_usd")
        size_revalidated = False
        if optimal and optimal > 0 \
                and abs(optimal - size_usd) > 0.10 * size_usd:
            alt = _exact_cycle_net(w3, buy_v, sell_v, addr_a, addr_b,
                                   dec_a, dec_b, optimal, price_b,
                                   gas_gwei, matic_price, resolved, block)
            size_revalidated = True
            if alt["net_usd"] > best["net_usd"]:
                best = alt
        net = best["net_usd"]
        # Le contrat on-chain exige minProfit = 0,01 $ : un net dans
        # ]0 ; 0,01] reverrait à l'exécution — il n'est pas EXECUTE.
        action = "EXECUTE" if net > ONCHAIN_MIN_PROFIT_USD else "SKIP"
        return {"method": "exact-quote",
                "quote_block": block, "out_a_raw": best["out_a_raw"], "out_b_raw": best["out_b_raw"],
                "spread_pct": round(best["spread_pct"], 4),
                "expected_net_usd": net,
                "action": action,
                "optimal_loan_usd": best["size_usd"],
                "size_tested_usd": size_usd,
                "size_optimal_approx_usd": optimal,
                "size_revalidated": size_revalidated,
                "usdc_back_usd": best["usdc_back"],
                "gross_usd": best["gross_usd"],
                "flash_fee_usd": best["flash_fee_usd"],
                "gas_total_usd": best["gas_total_usd"],
                "onchain_min_profit_usd": ONCHAIN_MIN_PROFIT_USD,
                "above_onchain_floor": net > ONCHAIN_MIN_PROFIT_USD}
    except Exception:  # noqa: BLE001
        return {"method": "exact-quote",
                "error": "verification echouee"}


# ------------------------------------------------------------- rotation (repli)
def rotation_subset(pairs: list, block: int, n_per_block: int) -> list:
    """Repli si Multicall3 echoue : un sous-ensemble tournant de paires
    par bloc (round-robin), pour ne pas marteler le RPC. Retourne les
    indices des paires a traiter a ce bloc."""
    if not pairs:
        return []
    n = len(pairs)
    if n_per_block >= n:
        return list(range(n))
    start = (block * n_per_block) % n
    return [(start + i) % n for i in range(n_per_block)]


# ------------------------------------------------------------------- listener
class Listener:
    def __init__(self, w3, inventory: dict, resolved: dict,
                 prices_usd: dict, out_path: Path,
                 duration_minutes: float = 30.0):
        self.w3 = w3
        self.pairs = inventory["pairs"]
        self.resolved = resolved
        self.prices = dict(prices_usd)
        self.out_path = out_path
        self.duration = duration_minutes * 60.0
        self.started_at = time.time()
        self.last_block = 0
        self.blocks_processed = 0
        self.blocks_missed = 0
        self.quotes = 0
        self.signals = 0
        self.signals_verified = 0
        self.latencies_ms = []
        self.rpc_errors = 0
        self.multicall_ok = len(w3.eth.get_code(MULTICALL3)) > 0
        self.rotation_mode = not self.multicall_ok
        self.transport = "?"
        self.closest_misses = []  # top-5 nets <= 0 (net desc)
        self.last_price_refresh = time.time()
        self._out = open(out_path, "a", encoding="utf-8")
        self._write({"type": "run_start",
                     "timestamp": datetime.now(timezone.utc).isoformat(),
                     "mode": MODE, "transport": None,
                     "multicall_ok": self.multicall_ok,
                     "rotation_mode": self.rotation_mode,
                     "pairs": len(self.pairs),
                     "venues": sum(len(p["venues"]) for p in self.pairs),
                     "duration_minutes": duration_minutes})

    def _write(self, rec: dict) -> None:
        self._out.write(json.dumps(rec) + "\n")
        self._out.flush()

    def close(self):
        try:
            self._write(self.summary_record())
            self._out.close()
        except Exception:  # noqa: BLE001
            pass

    def summary_record(self) -> dict:
        lat = self.latencies_ms
        return {"type": "run_end",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "transport": self.transport,
                "blocks_processed": self.blocks_processed,
                "blocks_missed": self.blocks_missed,
                "quotes": self.quotes,
                "signals": self.signals,
                "signals_verified": self.signals_verified,
                "rpc_errors": self.rpc_errors,
                "avg_latency_ms": (round(sum(lat) / len(lat), 1)
                                   if lat else None),
                "max_latency_ms": round(max(lat), 1) if lat else None,
                "rotation_mode": self.rotation_mode,
                "closest_misses_top5": self.closest_misses}

    def refresh_prices(self):
        """Rafraichit les prix de reference (toutes les 10 min, au mieux)."""
        if time.time() - self.last_price_refresh < PRICE_REFRESH_SECONDS:
            return
        self.last_price_refresh = time.time()
        try:
            fresh = bp.reference_prices_usd()
            self.prices.update({k: v for k, v in fresh.items() if v})
            if ps is not None and hasattr(ps, "coingecko_mid_prices"):
                self.prices.update(ps.coingecko_mid_prices())
        except Exception:  # noqa: BLE001
            pass

    def process_block(self, block: int, gas_gwei: float,
                      received_at: float) -> dict:
        """Traite UN bloc : lecture d'etat + evaluation de toutes les
        paires. Retourne le resume du bloc (signaux inclus)."""
        if block <= self.last_block:
            return {"block": block, "skipped": "deja traite"}
        missed = block - self.last_block - 1 if self.last_block else 0
        if missed > 0:
            self.blocks_missed += missed
        self.last_block = block
        self.refresh_prices()
        matic_price = self.prices.get("WMATIC", DEFAULT_MATIC_PRICE)
        t0 = time.time()
        results = []
        signals = []
        try:
            if self.rotation_mode:
                results = self._process_rotation(block, gas_gwei,
                                                 matic_price)
            else:
                results = self._process_multicall(block, gas_gwei,
                                                  matic_price)
        except Exception as e:  # noqa: BLE001
            self.rpc_errors += 1
            if not self.rotation_mode:
                # Bascule en mode rotation SEULEMENT apres echecs repetes
                # (les retries sont dans _process_multicall) ; l'erreur
                # sous-jacente est loguee, pas avalee.
                self.rotation_mode = True
                print(f"  !! Multicall en erreur ({str(e)[:120]}) : "
                      f"bascule en mode rotation", flush=True)
                try:
                    results = self._process_rotation(block, gas_gwei,
                                                     matic_price)
                except Exception:  # noqa: BLE001
                    self.rpc_errors += 1
                    results = []
        latency_ms = (time.time() - t0) * 1000.0
        rpc_latency_ms = (time.time() - received_at) * 1000.0
        self.latencies_ms.append(rpc_latency_ms)
        self.blocks_processed += 1
        for res in results:
            for size_s, meas in res.get("sizes", {}).items():
                net = (meas.get("net") or {}).get("expected_net_usd")
                if net is None:
                    continue
                self.quotes += 1
                if net > 0:
                    sig = self._make_signal(res, size_s, meas, block,
                                            gas_gwei)
                    signals.append(sig)
                    self.signals += 1
                    self._write(sig)
                    if sig.get("verification"):
                        self.signals_verified += 1
                else:
                    self._track_miss(net, meas.get("spread_pct"), res,
                                     size_s, block)
        if self.blocks_processed % 100 == 0:
            self._write({"type": "stats",
                         "timestamp": datetime.now(timezone.utc).isoformat(),
                         "block": block,
                         "blocks_processed": self.blocks_processed,
                         "blocks_missed": self.blocks_missed,
                         "quotes": self.quotes,
                         "signals": self.signals,
                         "rpc_errors": self.rpc_errors,
                         "avg_latency_ms": round(
                             sum(self.latencies_ms)
                             / len(self.latencies_ms), 1),
                         "rotation_mode": self.rotation_mode})
            print(f"  [stats] bloc {block} : {self.blocks_processed} blocs, "
                  f"{self.quotes} quotes, {self.signals} signaux, "
                  f"latence moy. "
                  f"{sum(self.latencies_ms) / len(self.latencies_ms):.0f} ms",
                  flush=True)
        return {"block": block, "results": len(results),
                "signals": len(signals), "latency_ms": round(latency_ms, 1),
                "block_to_quote_ms": round(rpc_latency_ms, 1),
                "rotation_mode": self.rotation_mode}

    def _make_signal(self, res: dict, size_s: str, meas: dict, block: int,
                     gas_gwei: float) -> dict:
        pair = next((p for p in self.pairs
                     if p["label"] == res["pair"]), None)
        sig = {"type": "signal",
               "timestamp": datetime.now(timezone.utc).isoformat(),
               "block": block, "pair": res["pair"],
               "section": res.get("section"),
               "size_usd": float(size_s),
               "spread_pct": meas.get("spread_pct"),
               "net_usd": meas["net"]["expected_net_usd"],
               "optimal_loan_usd": meas["net"].get("optimal_loan_usd"),
               "buy_venue": meas.get("best_buy"),
               "sell_venue": meas.get("best_sell"),
               "gas_gwei": round(gas_gwei, 2),
               "gas_usd_per_trade": meas["net"].get("gas_trade_usd"),
               "method": "virtual-reserves+guard",
               "verification": None}
        if pair is not None:
            meas2 = dict(meas)
            meas2["gas_gwei"] = gas_gwei
            try:
                sig["verification"] = verify_signal_exact(
                    self.w3, pair, float(size_s), meas2, self.prices,
                    self.resolved, block)
            except Exception:  # noqa: BLE001
                sig["verification"] = {"method": "exact-quote",
                                       "error": "verification echouee"}
        return sig

    def _track_miss(self, net: float, spread, res: dict, size_s: str,
                    block: int):
        entry = {"net_usd": round(net, 4), "spread_pct": spread,
                 "pair": res["pair"], "size_usd": float(size_s),
                 "block": block}
        self.closest_misses.append(entry)
        self.closest_misses.sort(key=lambda e: -e["net_usd"])
        self.closest_misses = self.closest_misses[:5]

    def _process_multicall(self, block: int, gas_gwei: float,
                           matic_price: float) -> list:
        calls, decoding = build_multicall_calls(self.pairs)
        results = None
        last_err = "inconnu"
        for attempt in range(MULTICALL_RETRIES):
            try:
                results = multicall_aggregate3(
                    self.w3, calls, block_identifier=block)
            except Exception as e:  # noqa: BLE001
                results = None
                last_err = str(e)[:120]
            if results is not None:
                break
            if attempt < MULTICALL_RETRIES - 1:
                time.sleep(0.5)
        if results is None:
            raise RuntimeError(f"aggregate3 a echoue (RPC) : {last_err}")
        decode_states(results, decoding, self.pairs, self.resolved)
        out = []
        for pair in self.pairs:
            out.append(evaluate_pair(pair, gas_gwei, matic_price,
                                     self.prices, self.resolved, block))
        return out

    def _process_rotation(self, block: int, gas_gwei: float,
                          matic_price: float) -> list:
        """Repli : lectures individuelles sur un sous-ensemble tournant."""
        idxs = rotation_subset(self.pairs, block, n_per_block=5)
        out = []
        for idx in idxs:
            pair = self.pairs[idx]
            for v in pair["venues"]:
                if v.get("skip"):
                    continue
                try:
                    if v["kind"] == "v4":
                        # V4 : pas de slot0() sur le PoolManager — extsload.
                        if ps is None:
                            continue
                        pid = bytes.fromhex(v["pair"][2:])
                        st = ps.v4_pool_state(self.w3, pid)
                        if st is None or st["liquidity"] == 0:
                            continue
                        a0 = sorted([self.resolved[pair["token_a"]]
                                     ["address"].lower(),
                                     self.resolved[pair["token_b"]]
                                     ["address"].lower()])[0]
                        res_a, res_b, fee = ps.v4_virtual_reserves(
                            st, self.resolved[pair["token_a"]]["decimals"],
                            self.resolved[pair["token_b"]]["decimals"],
                            a0 == self.resolved[pair["token_a"]]
                            ["address"].lower())
                        if fee is None:
                            continue
                        v["res_a"], v["res_b"], v["fee_bps"] = (
                            res_a, res_b, fee)
                        continue
                    res_a, res_b, fee = bp.venue_reserves(
                        self.w3, v["kind"], v["pair"], pair["token_a"],
                        pair["token_b"])
                    v["res_a"], v["res_b"], v["fee_bps"] = (
                        res_a, res_b, fee)
                except Exception:  # noqa: BLE001
                    continue
            out.append(evaluate_pair(pair, gas_gwei, matic_price,
                                     self.prices, self.resolved, block))
        return out

    def time_left(self) -> float:
        return self.duration - (time.time() - self.started_at)


# ------------------------------------------------------------------ transport
async def ws_listen(listener: Listener, stop_at: float):
    """Boucle websocket : abonnement newHeads, reconnexion avec backoff,
    fail-closed apres MAX_RECONNECTS echecs."""
    attempts = 0
    endpoint_idx = 0
    while time.time() < stop_at and attempts < MAX_RECONNECTS:
        url = WSS_ENDPOINTS[endpoint_idx % len(WSS_ENDPOINTS)]
        try:
            async with websockets.connect(
                    url, open_timeout=10, close_timeout=5,
                    ping_interval=20, ping_timeout=10) as ws:
                await ws.send(json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe",
                     "params": ["newHeads"]}))
                sub = json.loads(await asyncio.wait_for(ws.recv(),
                                                       timeout=10))
                if "error" in sub:
                    raise RuntimeError(f"subscribe refuse : {sub['error']}")
                listener.transport = f"ws:{url}"
                print(f"  [ws] connecte a {url} "
                      f"(abonnement newHeads)", flush=True)
                attempts = 0
                queue: asyncio.Queue = asyncio.Queue(maxsize=16)
                worker = asyncio.create_task(
                    _ws_worker(listener, queue, stop_at))
                try:
                    while time.time() < stop_at:
                        try:
                            raw = await asyncio.wait_for(ws.recv(),
                                                       timeout=30)
                        except asyncio.TimeoutError:
                            # Pas de message en 30 s : le flux est
                            # suspect, on reconnecte.
                            raise RuntimeError("aucun bloc recu en 30 s")
                        msg = json.loads(raw)
                        hdr = (msg.get("params") or {}).get("result") or {}
                        number = hdr.get("number")
                        if not number:
                            continue
                        block = int(number, 16)
                        base_fee = hdr.get("baseFeePerGas")
                        gas_gwei = (int(base_fee, 16) / 1e9
                                    if base_fee else DEFAULT_GAS_GWEI)
                        try:
                            queue.put_nowait((block, gas_gwei,
                                              time.time()))
                        except asyncio.QueueFull:
                            # File pleine : on garde le bloc le plus
                            # recent, les anciens sont comptes manques.
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            queue.put_nowait((block, gas_gwei,
                                              time.time()))
                finally:
                    worker.cancel()
                    try:
                        await worker
                    except asyncio.CancelledError:
                        pass
                if time.time() >= stop_at:
                    return
                raise RuntimeError("connexion ws fermee")
        except Exception as e:  # noqa: BLE001
            attempts += 1
            listener.rpc_errors += 1
            print(f"  !! ws {url} coupe ({str(e)[:100]}) — tentative "
                  f"{attempts}/{MAX_RECONNECTS}", flush=True)
            if attempts % 2 == 0:
                endpoint_idx += 1
            if attempts >= MAX_RECONNECTS or time.time() >= stop_at:
                break
            await asyncio.sleep(backoff_delay(attempts - 1))
    if attempts >= MAX_RECONNECTS:
        print("  !! FAIL-CLOSED : trop d'echecs de reconnexion, arret "
              "propre (aucune boucle infinie).", flush=True)


async def _ws_worker(listener: Listener, queue: asyncio.Queue,
                     stop_at: float):
    """Consomme les blocs (le plus recent d'abord, anciens abandonnes)."""
    while time.time() < stop_at:
        item = await queue.get()
        # Ne garder que le bloc le plus recent de la file. Les blocs
        # abandonnes sont comptes UNE SEULE FOIS, dans process_block
        # (ecart entre blocs traites) — pas ici (double comptage).
        while not queue.empty():
            try:
                newer = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if newer[0] > item[0]:
                item = newer
        block, gas_gwei, received_at = item
        res = await asyncio.get_running_loop().run_in_executor(
            None, listener.process_block, block, gas_gwei, received_at)
        if res.get("signals"):
            print(f"  !!! SIGNAL bloc {block} : {res['signals']} net > 0 $",
                  flush=True)


def poll_listen(listener: Listener, stop_at: float):
    """Repli : polling eth_blockNumber toutes les 2 s."""
    listener.transport = "poll:eth_blockNumber/2s"
    print("  [poll] mode polling (2 s) — aucun wss utilisable",
          flush=True)
    while time.time() < stop_at:
        try:
            block = listener.w3.eth.block_number
            try:
                gas_gwei = (listener.w3.eth.gas_price / 1e9)
            except Exception:  # noqa: BLE001
                gas_gwei = DEFAULT_GAS_GWEI
            res = listener.process_block(block, gas_gwei, time.time())
            if res.get("signals"):
                print(f"  !!! SIGNAL bloc {block} : {res['signals']} "
                      f"net > 0 $", flush=True)
        except Exception as e:  # noqa: BLE001
            listener.rpc_errors += 1
            print(f"  !! poll en erreur : {str(e)[:100]}", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)


async def run_live(listener: Listener, duration_minutes: float,
                   transport: str):
    stop_at = time.time() + duration_minutes * 60.0
    if transport == "poll":
        await asyncio.get_running_loop().run_in_executor(
            None, poll_listen, listener, stop_at)
        return
    await ws_listen(listener, stop_at)
    # Si le ws a echoue avant la fin (fail-closed ou fin de tentatives)
    # et qu'il reste du temps : repli polling, une seule fois, avec
    # un message clair (le ws reste le mode prefere).
    if time.time() < stop_at and listener.blocks_processed == 0:
        print("  [repli] ws indisponible des le demarrage : bascule "
              "polling pour le temps restant", flush=True)
        await asyncio.get_running_loop().run_in_executor(
            None, poll_listen, listener, stop_at)


# ------------------------------------------------------------------ demarrage
def build_listener(w3, out_path: Path,
                   duration_minutes: float) -> Listener:
    meas_path = latest_pro_scan_measurement()
    if meas_path is None:
        raise RuntimeError("aucun fichier pro_scan_measurement_*.json "
                           "trouve (inventaire manquant)")
    inventory = load_inventory_from_measurement(meas_path)
    print(f"  Inventaire : {len(inventory['pairs'])} paires, "
          f"{sum(len(p['venues']) for p in inventory['pairs'])} venues "
          f"(source : {meas_path.name})", flush=True)
    resolved = resolve_tokens(w3, inventory)
    prices = resolve_prices(w3, inventory, resolved)
    # Paires dont un token n'est pas resolu -> SKIP explicite.
    kept = []
    for pair in inventory["pairs"]:
        if (pair["token_a"] in resolved and pair["token_b"] in resolved
                and pair["token_a"] in prices
                and pair["token_b"] in prices):
            kept.append(pair)
        else:
            print(f"  SKIP paire {pair['label']} : token/prix non resolu",
                  flush=True)
    inventory["pairs"] = kept
    # Donnees statiques des venues (token0, fee, slots V4).
    n_static = 0
    for pair in inventory["pairs"]:
        for v in pair["venues"]:
            sv = prepare_static_venue(w3, v, pair["token_a"],
                                      pair["token_b"])
            if sv is None:
                v["skip"] = True
            else:
                v.update(sv)
                n_static += 1
    print(f"  Venues preparees (statique) : {n_static} / "
          f"{sum(len(p['venues']) for p in inventory['pairs'])}",
          flush=True)
    if len(w3.eth.get_code(MULTICALL3)) == 0:
        print("  !! Multicall3 SANS code : mode rotation des le demarrage",
              flush=True)
    return Listener(w3, inventory, resolved, prices, out_path,
                    duration_minutes)


def connect_http():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), "RPC Polygon injoignable"
    return w3


def main():
    global MAX_RECONNECTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-minutes", type=float, default=30.0)
    ap.add_argument("--once", action="store_true",
                    help="un seul bloc, puis arret")
    ap.add_argument("--live", action="store_true", default=True,
                    help="mode live (defaut)")
    ap.add_argument("--transport", choices=["ws", "poll"], default="ws")
    ap.add_argument("--out", type=str, default="realtime_signals.jsonl")
    ap.add_argument("--max-reconnects", type=int, default=MAX_RECONNECTS)
    args = ap.parse_args()

    MAX_RECONNECTS = args.max_reconnects

    w3 = connect_http()
    print(f"Connecte Polygon, bloc {w3.eth.block_number}", flush=True)
    listener = build_listener(w3, Path(args.out), args.duration_minutes)
    try:
        if args.once:
            block = w3.eth.block_number
            try:
                gas_gwei = w3.eth.gas_price / 1e9
            except Exception:  # noqa: BLE001
                gas_gwei = DEFAULT_GAS_GWEI
            res = listener.process_block(block, gas_gwei, time.time())
            print(f"Bloc {block} : {res}", flush=True)
            print(f"Signaux : {listener.signals} | "
                  f"proches : {listener.closest_misses}", flush=True)
            return
        asyncio.run(run_live(listener, args.duration_minutes,
                             args.transport))
    finally:
        listener.close()
        s = listener.summary_record()
        print("=== FIN ===", flush=True)
        print(f"Transport : {s['transport']} | blocs traites : "
              f"{s['blocks_processed']} | manques : {s['blocks_missed']} | "
              f"quotes : {s['quotes']} | signaux net > 0 $ : {s['signals']} "
              f"(verifies : {s['signals_verified']}) | erreurs RPC : "
              f"{s['rpc_errors']} | latence moy. bloc->quote : "
              f"{s['avg_latency_ms']} ms | rotation : {s['rotation_mode']}",
              flush=True)
        print(f"Top-5 proches (net <= 0 $) : {s['closest_misses_top5']}",
              flush=True)


if __name__ == "__main__":
    main()
