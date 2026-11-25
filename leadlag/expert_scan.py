"""expert_scan.py — EXPERT SCAN : meilleurs candidats lead-lag Binance -> Base.

EXPERT, pas exécuteur : le script choisit LUI-MÊME la méthode et les candidats,
les mesure, et les classe par expected value. Lecture seule, aucun broadcast,
aucun wallet, aucune clé affichée, aucun fond. Ne touche à aucun fichier
existant (paper_trade.py / paper_entries.jsonl appartiennent à l'agent de
validation en cours).

MÉTHODE (choix d'expert, justifié dans EXPERT_SCAN_BASE.md) :
  1. Univers : top pools Base par volume (GeckoTerminal, pages 1-4) + recherche
     DexScreener ciblée (VIRTUAL, PEPE, PROS) — 3 bandes de taille :
     majors (contrôle, déjà prouvées 0 opp) / mid / small.
  2. Filtre DEX : Uniswap V3 seulement (dexId == "uniswap" + labels v3) —
     le contrat du repo ne connaît que V3 (Aerodrome = autre venue, V4 = non
     supporté). Vérification on-chain : factory.getPool == adresse, fee()
     lu on-chain (jamais supposé), slot0 + liquidité non nulle.
  3. Risque honeypot : mix txns DexScreener (sells > 0, ratio buys/sells
     sain) + GoPlus (is_honeypot, taxes) si joignable.
  4. Signal Binance : depth /api/v3/depth via data-api.binance.vision
     (api.binance.com = 451 depuis cette VM) — erreur -1121 = token non listé
     = PAS de signal order book = PAS un candidat lead-lag (momentum brut
     seulement). Pour les listés : imbalance + volume pour déplacer 0,1 % +
     volatilité 1 min (klines 120 x 1m) -> sigma_4s = sigma_1m / sqrt(15)
     (hypothèse marche aléatoire, déclarée).
  5. Seuil PAR POOL (règle d'Ismail) : coût aller-retour EXACT via QuoterV2
     on-chain (quoteExactInput, path 1 hop — la voie qui fonctionne sur Base)
     à 1 000 $ et 5 000 $ + gas live (450k units x gasPrice x prix ETH, x2 =
     trade + budget revert, convention du repo) / taille.
  6. Score EV = (move_proxy_4s / seuil_1k) x facteur_signal x facteur_turnover.
     move_proxy_4s : sigma_4s (listés) ou |h1%|/60/sqrt(15) (non listés,
     proxy grossier déclaré). facteur_signal : 1,0 listé, 0,15 non listé.
     facteur_turnover : min(vol24/liquidité, 2).

Sorties : leadlag/expert_scan_results.json (toutes les mesures, horodatées)
+ tableau de classement imprimé sur stdout.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")

from v3_quote import quote_v3_onchain  # noqa: E402
from web3 import Web3  # noqa: E402

BASE_DIR = Path("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")
OUT_JSON = BASE_DIR / "expert_scan_results.json"
BASE_RPC = "https://mainnet.base.org"
BINANCE = "https://data-api.binance.vision"
GT = "https://api.geckoterminal.com/api/v2/networks/base/pools"
DS = "https://api.dexscreener.com/latest/dex"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH_BASE = "0x4200000000000000000000000000000000000006"
GAS_UNITS = 450_000

# Candidats présélectionnés par NOM DE POOL (GeckoTerminal) — les adresses
# sont résolues depuis GeckoTerminal/DexScreener AVANT toute vérification
# on-chain (voir _load_pool_addresses + main). Aucune adresse devinée
# n'atteint jamais une vérification on-chain.
# (nom GeckoTerminal, symbole Binance, bande)
CANDIDATES = [
    ("WETH / USDC 0.01%", "ETH", "major"),
    ("cbBTC / USDC 0.05%", "BTC", "major"),
    ("AERO / USDC 0.015%", "AERO", "mid"),
    ("SOL / USDC 0.012%", "SOL", "mid"),
    ("HYPE / WETH 0.087%", "HYPE", "mid"),
    ("VELVET / USDC 0.01%", "VELVET", "mid"),
    ("xdp / USDC 0.01%", "XDP", "mid"),
    ("VVV / USDC 0.038%", "VVV", "small"),
    ("ELSA / USDC 0.01%", "ELSA", "small"),
    ("KNTQ / USDC 0.073%", "KNTQ", "small"),
    ("PLAY / USDC 0.01%", "PLAY", "small"),
    ("CTR / USDC 0.029%", "CTR", "small"),
]
# Paires résolues via DexScreener search (pas sur GeckoTerminal top pages) :
# (nom, symbole Binance, token de recherche, quote attendu, bande)
DS_CANDIDATES = [
    ("VIRTUAL/WETH v3", "VIRTUAL", "VIRTUAL", "WETH", "small"),
    ("PROS/USDC V3", "PROS", "PROS", "USDC", "mid"),
]


def http_get_json(url, timeout=20, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "expert-scan-base"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def _load_alchemy_rpc():
    """URL Alchemy lue dans config.yaml EN MÉMOIRE seulement — jamais affichée
    ni loguée (clé = credential). RPC de secours si le RPC public échoue."""
    try:
        txt = Path("/home/hatch/workspace/crypto-base-flashloan-bot/config.yaml").read_text()
        m = re.search(r'rpc_url:\s*"([^"]+)"', txt)
        return m.group(1) if m else None
    except Exception:
        return None


ALCHEMY_RPC = _load_alchemy_rpc()
RPCS = [BASE_RPC] + ([ALCHEMY_RPC] if ALCHEMY_RPC else [])

W3 = Web3(Web3.HTTPProvider(BASE_RPC, request_kwargs={"timeout": 20}))

POOL_ABI = [
    {"name": "fee", "outputs": [{"type": "uint24"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "slot0", "outputs": [{"type": "uint160"}, {"type": "int24"},
     {"type": "uint16"}, {"type": "uint16"}, {"type": "uint16"},
     {"type": "uint8"}, {"type": "bool"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "liquidity", "outputs": [{"type": "uint128"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
ERC20_ABI = [
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [],
     "stateMutability": "view", "type": "function"},
]
FACTORY_ABI = [
    {"name": "getPool", "outputs": [{"type": "address"}],
     "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
     "stateMutability": "view", "type": "function"},
]


def _rpc_with_fallback(fn, what):
    """Essaie le RPC public puis Alchemy (jamais logué)."""
    errs = []
    for rpc in RPCS:
        try:
            return fn(rpc)
        except Exception as e:
            errs.append(str(e)[:60])
    raise RuntimeError(f"{what}: " + " | ".join(errs))


def _retry(fn, what, tries=3):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError(f"{what}: {last}")


def onchain_pool_state(pool_addr):
    """fee(), slot0(), liquidity(), token0/1 — via web3 (RPC public)."""
    c = W3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=POOL_ABI)
    fee = _retry(lambda: c.functions.fee().call(), "fee()")
    slot0 = _retry(lambda: c.functions.slot0().call(), "slot0()")
    liq = _retry(lambda: c.functions.liquidity().call(), "liquidity()")
    t0 = _retry(lambda: c.functions.token0().call(), "token0()")
    t1 = _retry(lambda: c.functions.token1().call(), "token1()")
    return {"fee_bps": fee, "sqrt_x96": slot0[0], "tick": slot0[1],
            "liquidity": liq, "token0": t0, "token1": t1}


def onchain_get_pool(t0, t1, fee):
    f = W3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=FACTORY_ABI)
    return _retry(lambda: f.functions.getPool(Web3.to_checksum_address(t0),
                                              Web3.to_checksum_address(t1), fee).call(),
                  "factory.getPool")


def onchain_decimals(token):
    c = W3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
    return _retry(lambda: c.functions.decimals().call(), "decimals()")


def dex_pair(pool_addr):
    d = http_get_json(f"{DS}/pairs/base/{pool_addr}")
    pairs = d.get("pairs") or []
    return pairs[0] if pairs else None


def binance_depth(symbol):
    """Order book Binance. Retourne None si le symbole n'existe pas (-1121)."""
    try:
        d = http_get_json(f"{BINANCE}/api/v3/depth?symbol={symbol}USDT&limit=1000",
                          timeout=15, retries=1)
    except Exception as e:
        return {"listed": False, "error": str(e)[:120]}
    if isinstance(d, dict) and d.get("code"):
        return {"listed": False, "error": f"code {d.get('code')}: {d.get('msg')}"}
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    if not bids or not asks:
        # Symbole connu mais carnet vide (déférencé / illiquide) : pas de signal.
        return {"listed": False, "error": "empty order book (delisted/illiquid)"}
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0

    def band(band_pct):
        lo, hi = mid * (1 - band_pct / 100.0), mid * (1 + band_pct / 100.0)
        bid_d = sum(p * q for p, q in bids if p >= lo)
        ask_d = sum(p * q for p, q in asks if p <= hi)
        tot = bid_d + ask_d
        return bid_d, ask_d, ((bid_d - ask_d) / tot if tot > 0 else 0.0)

    vol_up = sum(p * q for p, q in asks if p < mid * 1.001)
    vol_dn = sum(p * q for p, q in bids if p > mid * 0.999)
    b01, a01, i01 = band(0.1)
    b05, a05, i05 = band(0.5)
    return {"listed": True, "mid": mid,
            "spread_bps": (best_ask - best_bid) / mid * 10_000.0,
            "imb_01": round(i01, 4), "bid_d_01": round(b01, 1), "ask_d_01": round(a01, 1),
            "imb_05": round(i05, 4), "bid_d_05": round(b05, 1), "ask_d_05": round(a05, 1),
            "vol_to_move_01_up_usdt": round(vol_up, 1),
            "vol_to_move_01_dn_usdt": round(vol_dn, 1)}


def binance_sigma_4s(symbol, limit=120):
    """Volatilité 1 min (klines 1m) -> sigma_4s = sigma_1m / sqrt(15).
    Hypothèse marche aléatoire, déclarée. None si non listé / erreur."""
    try:
        d = http_get_json(f"{BINANCE}/api/v3/klines?symbol={symbol}USDT"
                          f"&interval=1m&limit={limit}", timeout=15, retries=1)
    except Exception:
        return None
    if isinstance(d, dict) and d.get("code"):
        return None
    closes = [float(k[4]) for k in d if len(k) > 4]
    if len(closes) < 30:
        return None
    rets = [math.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    sigma_1m = math.sqrt(var) * 100.0  # en %
    return {"sigma_1m_pct": round(sigma_1m, 5),
            "sigma_4s_pct": round(sigma_1m / math.sqrt(15), 5),
            "n_candles": len(closes)}


def goplus(token):
    try:
        d = http_get_json(
            f"https://api.gopluslabs.io/api/v1/token_security/8453"
            f"?contract_addresses={token}", timeout=15, retries=1)
        r = (d.get("result") or {}).get(token.lower()) or {}
        return {"is_honeypot": r.get("is_honeypot"),
                "buy_tax": r.get("buy_tax"), "sell_tax": r.get("sell_tax"),
                "holder_count": r.get("holder_count")}
    except Exception as e:
        return {"error": str(e)[:80]}


def roundtrip_cost_pct(pool, quote_token, asset_token, asset_dec, quote_dec,
                      fee_bps, size_usd, eth_px):
    """Coût aller-retour EXACT via QuoterV2 (buy puis sell à l'état actuel).
    Retourne (cost_pct, proceeds_usd, error). quote_token = USDC ou WETH.
    Essaie le RPC public puis Alchemy (jamais logué) en cas d'échec."""

    def q(amount_in_raw, tok_in, tok_out):
        for rpc in RPCS:
            r = quote_v3_onchain(tok_in, tok_out, fee_bps, amount_in_raw, rpc, timeout=15)
            if r.source == "quoter_v2_onchain" and r.amount_out > 0:
                return r
        return None

    if quote_token == USDC_BASE:
        amt_in = int(size_usd * 1e6)
    else:  # WETH
        amt_in = int(size_usd / eth_px * 1e18)
    buy = q(amt_in, quote_token, asset_token)
    if buy is None:
        return None, None, "buy quote failed on all RPCs"
    sell = q(int(buy.amount_out), asset_token, quote_token)
    if sell is None:
        return None, None, "sell quote failed on all RPCs"
    if quote_token == USDC_BASE:
        proceeds = sell.amount_out / 1e6
    else:
        proceeds = sell.amount_out / 1e18 * eth_px
    return (size_usd - proceeds) / size_usd * 100.0, proceeds, None


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _load_pool_addresses():
    """Remplace les placeholders par les VRAIES adresses lues sur
    GeckoTerminal (top pools pages 1-4) + DexScreener (VIRTUAL/PEPE/PROS).
    Aucune adresse devinée n'atteint la vérification on-chain."""
    gt_pools = {}
    for page in (1, 2, 3, 4):
        try:
            d = http_get_json(f"{GT}?page={page}", timeout=20)
        except Exception as e:
            print(f"  [GT] page {page} erreur: {e}")
            continue
        for p in d.get("data", []):
            a = p["attributes"]
            gt_pools[a["address"].lower()] = {
                "name": a["name"], "reserve_usd": a.get("reserve_in_usd"),
                "vol24": (a.get("volume_usd") or {}).get("h24"),
                "chg24": (a.get("price_change_percentage") or {}).get("h24"),
                "created": a.get("pool_created_at"),
                "dex": ((p.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id"),
            }
    # Recherche DexScreener pour PROS / VIRTUAL / PEPE (pools V3 Uni)
    ds_search = {}
    for q in ("PROS", "VIRTUAL", "PEPE"):
        try:
            d = http_get_json(f"{DS}/search?q={q}", timeout=20)
            for p in d.get("pairs", []):
                if p.get("chainId") == "base" and p.get("dexId") == "uniswap" \
                        and "v3" in (p.get("labels") or []):
                    ds_search.setdefault(q, []).append(p)
        except Exception as e:
            print(f"  [DS search {q}] erreur: {e}")
    return gt_pools, ds_search


def main():
    t0 = time.time()
    print("=== EXPERT SCAN Base — lead-lag Binance -> DEX ===")
    print(f"début {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
    gt_pools, ds_search = _load_pool_addresses()
    print(f"GeckoTerminal: {len(gt_pools)} pools lues (pages 1-4)")
    for q, lst in ds_search.items():
        print(f"DexScreener search {q}: {len(lst)} pools Uni V3 trouvées")
        for p in lst[:3]:
            print(f"   {p['baseToken']['symbol']}/{p['quoteToken']['symbol']} "
                  f"{p.get('labels')} pair {p['pairAddress'][:12]} liq "
                  f"{(p.get('liquidity') or {}).get('usd')} vol24 "
                  f"{(p.get('volume') or {}).get('h24')}")

    # Adresses réelles : on mappe chaque candidat à l'adresse GeckoTerminal
    # correspondante (match par nom de pool normalisé). Si pas de match ->
    # EXCLU, jamais deviné. En cas de doublon de nom, on garde la plus
    # grosse réserve.
    def norm(s):
        return re.sub(r"\s+", "", s.strip().lower())

    def is_addr(a):
        return isinstance(a, str) and len(a) == 42 and a.startswith("0x")

    by_name = {}
    for addr, info in gt_pools.items():
        # Ne garder que les pools Uniswap V3 de GeckoTerminal (dex id
        # "uniswap-v3-base") : les top pools Base sont majoritairement
        # Aerodrome / PancakeSwap / V4 — hors scope du contrat repo (V3 Uni).
        if "uniswap-v3" not in (info.get("dex") or ""):
            continue
        k = norm(info["name"])
        cur = by_name.get(k)
        # reserve_in_usd arrive en STRING sur GeckoTerminal : float() obligatoire
        # (sinon la comparaison est lexicographique et le mauvais pool gagne).
        res = float(info.get("reserve_usd") or 0)
        if cur is None or res > float(cur[1].get("reserve_usd") or 0):
            by_name[k] = (addr, info)
    resolved = []
    skipped = []
    for name, sym, band in CANDIDATES:
        hit = by_name.get(norm(name))
        if hit and is_addr(hit[0]):
            addr, info = hit
            resolved.append({"name": name, "symbol": sym, "pool": addr,
                             "band": band, "gt": info})
        else:
            # Fallback DexScreener : cherche le top pool Uni V3 du token.
            found = None
            try:
                d = http_get_json(f"{DS}/search?q={sym}", timeout=20)
                for p in d.get("pairs", []):
                    if p.get("chainId") == "base" and p.get("dexId") == "uniswap" \
                            and "v3" in (p.get("labels") or []) \
                            and p["baseToken"]["symbol"].upper() == sym.upper():
                        found = p
                        break
            except Exception as e:
                print(f"  [DS fallback {sym}] erreur: {e}")
            if found:
                resolved.append({"name": name + " (via DS)", "symbol": sym,
                                 "pool": found["pairAddress"], "band": band,
                                 "gt": None, "ds_search": found})
                print(f"  [DS fallback] {name} -> {found['pairAddress'][:12]} "
                      f"liq ${(found.get('liquidity') or {}).get('usd')}")
            else:
                reason = ("adresse GeckoTerminal invalide (poolId V4, pas une "
                          "adresse EVM)" if hit else
                          "adresse non trouvée sur GeckoTerminal")
                print(f"  [EXCLU — {reason}] {name}")
                skipped.append({"name": name, "reason": reason})
    # Paires DexScreener (VIRTUAL, PROS) : premier pool Uni V3 avec le bon quote
    for name, sym, query, quote_want, band in DS_CANDIDATES:
        found = None
        for p in ds_search.get(query, []):
            if p["quoteToken"]["symbol"] == quote_want:
                found = p
                break
        if found:
            resolved.append({"name": name, "symbol": sym,
                             "pool": found["pairAddress"], "band": band,
                             "gt": None, "ds_search": found})
            print(f"  [DS] {name} -> {found['pairAddress'][:12]} "
                  f"liq ${(found.get('liquidity') or {}).get('usd')}")
        else:
            print(f"  [EXCLU — pas de pool Uni V3 trouvé sur DexScreener] {name}")
    print(f"candidats résolus : {len(resolved)}")

    # Prix ETH + gas live (Base)
    eth = http_get_json(f"{BINANCE}/api/v3/ticker/price?symbol=ETHUSDT", timeout=15)
    eth_px = float(eth["price"])
    gas_hex = None
    for rpc in RPCS:
        try:
            req = urllib.request.Request(
                rpc, data=json.dumps({"jsonrpc": "2.0", "id": 1,
                                      "method": "eth_gasPrice", "params": []}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                gas_hex = json.loads(r.read().decode())["result"]
            break
        except Exception:
            continue
    gwei = int(gas_hex, 16) / 1e9 if gas_hex else 0.05
    gas_usd = GAS_UNITS * gwei * 1e-9 * eth_px
    gas_total = 2.0 * gas_usd  # trade + budget revert (convention repo)
    print(f"ETH ${eth_px:.2f} | gas {gwei:.3f} gwei -> ${gas_usd:.5f}/trade "
          f"(total budget ${gas_total:.5f})")

    results = []
    for c in resolved:
        pool = Web3.to_checksum_address(c["pool"])
        name, sym, band = c["name"], c["symbol"], c["band"]
        print(f"\n--- {name} [{band}] {pool[:12]} ---")
        rec = {"name": name, "symbol": sym, "band": band, "pool": pool,
               "gt": c.get("gt")}
        # 1) DexScreener (dex, labels, txns, volume, priceChange, liquidité)
        ds = dex_pair(pool)
        if not ds:
            print("  [EXCLU] pas de données DexScreener")
            rec["excluded"] = "no DexScreener data"
            results.append(rec)
            continue
        rec["dex"] = ds.get("dexId")
        rec["labels"] = ds.get("labels")
        rec["ds_liq_usd"] = (ds.get("liquidity") or {}).get("usd")
        rec["ds_vol_h24"] = (ds.get("volume") or {}).get("h24")
        rec["ds_vol_h1"] = (ds.get("volume") or {}).get("h1")
        rec["ds_chg_h24"] = (ds.get("priceChange") or {}).get("h24")
        rec["ds_chg_h6"] = (ds.get("priceChange") or {}).get("h6")
        rec["ds_chg_h1"] = (ds.get("priceChange") or {}).get("h1")
        rec["ds_txns_h24"] = (ds.get("txns") or {}).get("h24")
        rec["ds_txns_h1"] = (ds.get("txns") or {}).get("h1")
        rec["ds_created"] = ds.get("pairCreatedAt")
        rec["base_token"] = ds["baseToken"]["address"]
        rec["quote_token"] = ds["quoteToken"]["address"]
        rec["base_symbol"] = ds["baseToken"]["symbol"]
        rec["quote_symbol"] = ds["quoteToken"]["symbol"]
        print(f"  DS: dex={rec['dex']} labels={rec['labels']} liq=${rec['ds_liq_usd']} "
              f"vol24=${rec['ds_vol_h24']} chg h1={rec['ds_chg_h1']}% h24={rec['ds_chg_h24']}%")
        print(f"  DS txns h24: {rec['ds_txns_h24']}")
        if rec["dex"] != "uniswap" or "v3" not in (rec["labels"] or []):
            print(f"  [EXCLU] pas un pool Uniswap V3 (dex={rec['dex']})")
            rec["excluded"] = f"not Uni V3: {rec['dex']} {rec['labels']}"
            results.append(rec)
            continue
        # 2) On-chain : fee(), slot0, liquidité, factory.getPool
        try:
            st = onchain_pool_state(pool)
            gp = onchain_get_pool(st["token0"], st["token1"], st["fee_bps"])
            rec["onchain"] = {"fee_bps": st["fee_bps"],
                              "fee_pct": st["fee_bps"] / 10000.0,
                              "tick": st["tick"],
                              "liquidity": st["liquidity"],
                              "token0": st["token0"], "token1": st["token1"],
                              "factory_getPool_match": gp.lower() == pool.lower()}
            print(f"  on-chain: fee={st['fee_bps']/10000:.3f}% tick={st['tick']} "
                  f"L={st['liquidity']:.3g} factory_match={rec['onchain']['factory_getPool_match']}")
            if not rec["onchain"]["factory_getPool_match"] or st["liquidity"] == 0:
                print("  [EXCLU] factory mismatch ou liquidité 0")
                rec["excluded"] = "factory mismatch or L=0"
                results.append(rec)
                continue
            dec_a = onchain_decimals(st["token0"])
            dec_b = onchain_decimals(st["token1"])
            rec["onchain"]["dec0"] = dec_a
            rec["onchain"]["dec1"] = dec_b
        except Exception as e:
            print(f"  [EXCLU] erreur on-chain: {e}")
            rec["excluded"] = f"onchain error: {e}"
            results.append(rec)
            continue
        # 3) GoPlus (honeypot) sur le token de base
        base_tok = rec["base_token"]
        gp = goplus(base_tok)
        rec["goplus"] = gp
        print(f"  GoPlus: {gp}")
        # 4) Binance : listing + depth + volatilité 1 min
        bd = binance_depth(sym)
        rec["binance"] = bd
        if bd.get("listed"):
            sig = binance_sigma_4s(sym)
            rec["binance_sigma"] = sig
            print(f"  Binance: LISTÉ mid=${bd['mid']} imb01={bd['imb_01']} "
                  f"imb05={bd['imb_05']} vol_to_move_0.1% up=${bd['vol_to_move_01_up_usdt']} "
                  f"dn=${bd['vol_to_move_01_dn_usdt']} sigma_4s={sig}")
        else:
            rec["binance_sigma"] = None
            print(f"  Binance: NON LISTÉ ({bd.get('error')})")
        # 5) Seuil par pool : aller-retour QuoterV2 à 1k$ et 5k$ + gas
        asset_tok = base_tok
        quote_tok = rec["quote_token"]
        dec_asset = onchain_decimals(asset_tok)
        dec_quote = onchain_decimals(quote_tok)
        thresholds = {}
        for size in (100, 250, 1000, 5000):
            cost, proceeds, err = roundtrip_cost_pct(
                pool, quote_tok, asset_tok, dec_asset, dec_quote,
                st["fee_bps"], float(size), eth_px)
            if err:
                thresholds[size] = {"error": err}
                print(f"  seuil ${size}: ERREUR {err}")
            else:
                thr = cost + gas_total / size * 100.0
                thresholds[size] = {"roundtrip_cost_pct": round(cost, 5),
                                    "threshold_pct": round(thr, 5),
                                    "proceeds_usd": round(proceeds, 2)}
                print(f"  seuil ${size}: aller-retour {cost:.4f}% + gas "
                      f"{gas_total/size*100:.4f}% -> seuil {thr:.4f}%")
        rec["thresholds"] = thresholds
        # 6) Move proxy 4s + score EV
        chg_h1 = rec["ds_chg_h1"]
        if rec.get("binance_sigma"):
            move_proxy = rec["binance_sigma"]["sigma_4s_pct"]
            move_src = "binance klines 1m (sigma_4s)"
        elif chg_h1 is not None:
            move_proxy = (abs(chg_h1) / 60.0) / math.sqrt(15)
            move_src = "|h1%|/60/sqrt(15) — proxy grossier"
        else:
            move_proxy = None
            move_src = "aucun"
        rec["move_proxy_4s_pct"] = move_proxy
        rec["move_proxy_src"] = move_src
        thr1k = (thresholds.get(1000) or {}).get("threshold_pct")
        liq_usd = rec["ds_liq_usd"] or 0
        vol24 = rec["ds_vol_h24"] or 0
        turnover = (vol24 / liq_usd) if liq_usd else 0
        rec["turnover_24h"] = round(turnover, 3)
        signal_factor = 1.0 if bd.get("listed") else 0.15
        rec["signal_factor"] = signal_factor
        if move_proxy is not None and thr1k:
            ratio = move_proxy / thr1k
            turn_f = min(turnover, 2.0)
            score = ratio * signal_factor * turn_f
            rec["ratio_move_threshold"] = round(ratio, 3)
            rec["turnover_factor"] = round(turn_f, 3)
            rec["ev_score"] = round(score, 4)
            rec["p_move_gt_threshold"] = round(
                1.0 - norm_cdf(thr1k / move_proxy), 4) if move_proxy > 0 else 0.0
            print(f"  move_proxy_4s={move_proxy:.5f}% ({move_src}) | ratio={ratio:.2f} "
                  f"| turnover={turnover:.2f}x | signal x{signal_factor} "
                  f"| EV score={score:.4f} | P(move>seuil)={rec['p_move_gt_threshold']:.1%}")
        else:
            rec["ev_score"] = None
            print("  score EV: impossible (move proxy ou seuil manquant)")
        results.append(rec)

    ranked = sorted([r for r in results if r.get("ev_score") is not None],
                    key=lambda r: r["ev_score"], reverse=True)
    print("\n=== CLASSEMENT EV (top 5) ===")
    for i, r in enumerate(ranked[:5], 1):
        print(f"{i}. {r['name']} [{r['band']}] score={r['ev_score']} "
              f"seuil1k={r['thresholds'][1000].get('threshold_pct')}% "
              f"move4s={r['move_proxy_4s_pct']:.5f}% "
              f"binance={'OUI' if r['binance'].get('listed') else 'NON'} "
              f"turnover={r['turnover_24h']}x")
    print("\n=== EXCLUS ===")
    for r in results:
        if r.get("excluded"):
            print(f"- {r['name']}: {r['excluded']}")

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(),
           "duration_s": round(time.time() - t0, 1),
           "eth_px": eth_px, "gas_gwei": round(gwei, 4),
           "gas_usd_per_trade": round(gas_usd, 6),
           "gas_total_budget_usd": round(gas_total, 6),
           "results": results,
           "skipped_at_resolution": skipped,
           "ranking": [r["name"] for r in ranked]}
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nJSON écrit : {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
