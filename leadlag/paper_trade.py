"""paper_trade.py — Système paper-trade LEAD-LAG par ORDER BOOKS (Base seulement).

PAPER MODE UNIQUEMENT — lecture seule, aucune exécution, aucun broadcast,
aucun wallet, aucune clé, aucun fond réel. Logue des ENTREES / SKIP papier.

MÉTHODE (raffinement d'Ismail 2026-11-25 10:17) : on NE compare PAS les prix
Binance vs Base. On compare les ORDER BOOKS :
  - Binance A un order book : /api/v3/depth (data-api.binance.vision —
    api.binance.com = HTTP 451 depuis cette VM). Signal = imbalance
    bid/ask (profondeur bid vs ask dans X % du mid, X = 0,1 % et 0,5 %)
    + impact prix visible (volume pour déplacer le prix de 0,1 %).
  - Base N'A PAS d'order book : Uniswap V3 est un AMM. Équivalent côté
    Base = la liquidité par tick du pool (sqrtPriceX96 + L) — le
    "virtual order book" de l'AMM. On calcule l'impact prix d'un trade
    de taille S sur le pool (formule V3 mono-tick + quote on-chain
    QuoterV2 à 1 000 $ comme ancrage exact).
  - Modèle : imbalance Binance -> mouvement de prix PRÉDIT (régression
    imbalance -> move sur 2-4 s, CALIBRÉE pendant la phase A du run).
    Si la corrélation mesurée est ~0, le signal est du bruit : le
    système bloque les entrées (predicted_move = 0) et le dit.
  - Entrée (règle d'Ismail, inchangée) : net PRÉDIT > 0 $ après TOUS
    les coûts (frais swap du tier réel, gas Base live x2 = trade +
    budget revert, flash 0 % Morpho) -> ENTRY papier, sinon SKIP.
    Une prédiction n'est pas une certitude : chaque entrée logue la
    confiance (corrélation mesurée) et la pente du modèle.
  - THRESHOLD PAR POOL (raffinement Ismail 2026-11-25 10:22) : le seuil
    est INDIVIDUEL par pool — breakeven = fee du tier réel (lu on-chain)
    + impact prix à la taille + gas + budget revert. Une pool à 0,01 %
    a un threshold ~0,02 %, une pool à 0,3 % ~0,6 % : la même prédiction
    peut être ENTRY sur l'une et SKIP sur l'autre. Le threshold par pool
    (threshold_pct / threshold_usd) est logué dans CHAQUE évaluation,
    et la décision est prise PAR POOL (tier_decisions).

DÉROULEMENT : phase A (calibration, défaut 10 min) = collecte seule,
aucune décision ; phase B (défaut 20 min) = décisions papier avec le
modèle calibré. Durée totale défaut 30 min.

PAIRES (redirection Ismail 2026-11-25 10:36, POOLS SGHAR) : ETH/USDC
(contrôle major, Binance ETHUSDT) + 3 petites pools V3 Base vérifiées
on-chain (TVL 94-130 k$, volume 24h réel, sells présents) : SOSO/USDC
(fee 100, Binance NON listé), AERO/USDC (fee 500, Binance AEROUSDT
listé), ICNT/USDC (fee 500, Binance NON listé). Pour les paires NON
listées : PAS de signal Binance — on mesure leurs mouvements DEX bruts
et on logue OPPORTUNITY (rétrospectif : le mouvement réalisé a dépassé
le seuil min de la pool) ou MEASURE. Pour les paires listées : signal
imbalance Binance comme avant (ENTRY/SKIP par prédiction).

Sortie : leadlag/paper_entries.jsonl — un objet JSON par évaluation
(par paire, par cycle) + enregistrements "calibration" et "summary".
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")

from v3_quote import quote_v3_onchain, v3_quote_python  # noqa: E402

BASE_DIR = Path("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")
OUT = BASE_DIR / "paper_entries.jsonl"
BASE_RPC = "https://mainnet.base.org"
BINANCE = "https://data-api.binance.vision"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH_BASE = "0x4200000000000000000000000000000000000006"
CBBTC_BASE = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
LINK_BASE = "0x88Fb150BDc53A65fe94Dea0c9BA0a6dAf8C6e196"  # vérifié DexScreener
GAS_UNITS = 450_000
GAS_USD_FALLBACK = 0.005  # mesuré repo sur Base
MAX_LOAN_USD = 50_000.0   # cap repo (Morpho Base USDC ~328 M$ : non contraignant)
CYCLE_S = 3.0  # cycle réel ~3 s : depth Binance ~2 s + RPC ~0,4-0,7 s/appel.
# Horizons de calibration = +3 s / +6 s (la DEX suit en ~2-4 s : un cycle
# de 3 s échantillonne encore le lag, résolution déclarée dans le rapport).
DEPTH_LIMIT = 1000

# Paires Base (sélection SMALL POOLS 2026-11-25, redirection Ismail 10:36 :
# « rah kynin mouvement kbar » — les gros mouvements sont dans les petites
# pools). Vérifiées on-chain (bloc 62 063 525) + DexScreener + Binance :
#  - SOSO/USDC fee 100 (pool 0x29183f918920a2aef0115a9c7374945589968aea,
#    L=5,21e17) : TVL 94 k$, vol24 638 k$, buys 3240 / sells 3790.
#    Binance SOSOUSDT : NON LISTÉ -> pas de signal order book (mesure brute).
#  - AERO/USDC fee 500 (pool 0xe5b5f522e98b5a2baae212d4da66b865b781db97,
#    L=2,56e17) : TVL 129 k$, vol24 127 k$, buys 2523 / sells 2385.
#    Binance AEROUSDT : LISTÉ -> signal imbalance comme avant.
#  - ICNT/USDC fee 500 (pool 0x9331f571f79d1e186a095c93756b5680a43932ac,
#    L=3,79e17) : TVL 130 k$, vol24 291 k$, buys 3014 / sells 3337.
#    Binance ICNTUSDT : NON LISTÉ -> mesure brute.
#  - ETH/USDC (contrôle, major) : gardé pour comparer gros vs petits
#    mouvements dans la même fenêtre. Binance ETHUSDT listé.
# Backup (non retenu, threshold ~0,6 % intéressant) : NVDAc/USDC fee 3000
# (pool 0x60661b315553eb81872deea9a66d567cf0ccd33b, L=3,17e14, TVL 70 k$,
# vol24 202 k$, buys 851 / sells 1098, Binance NON listé).
# bin_sym = None -> paire SANS signal Binance (mesure des mouvements bruts).
PAIRS = [
    {"name": "ETH/USDC", "bin_sym": "ETHUSDT", "asset": WETH_BASE, "dec": 18,
     "tiers": (100, 500, 3000, 10000)},
    {"name": "SOSO/USDC", "bin_sym": None,
     "asset": "0x624e2e7fDc8903165F64891672267AB0FCB98831", "dec": 18,
     "tiers": (100, 500, 3000, 10000)},
    {"name": "AERO/USDC", "bin_sym": "AEROUSDT",
     "asset": "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "dec": 18,
     "tiers": (100, 500, 3000, 10000)},
    {"name": "ICNT/USDC", "bin_sym": None,
     "asset": "0xE0Cd4cAcDdcBF4f36e845407CE53E87717b6601d", "dec": 18,
     "tiers": (100, 500, 3000, 10000)},
]
PRIMARY_TIER = {"ETH/USDC": 100, "SOSO/USDC": 100, "AERO/USDC": 500,
                "ICNT/USDC": 500}

def _load_alchemy_rpc():
    """URL Alchemy lue dans config.yaml EN MÉMOIRE seulement — jamais
    affichée ni loguée (clé = credential). Sert de RPC de secours quand
    le RPC public Base rate-limite (403) ou coupe (taux d'échec ~15 %)."""
    try:
        import re
        txt = Path("/home/hatch/workspace/crypto-base-flashloan-bot/config.yaml").read_text()
        m = re.search(r'rpc_url:\s*"([^"]+)"', txt)
        return m.group(1) if m else None
    except Exception:
        return None


ALCHEMY_RPC = _load_alchemy_rpc()
# Alchemy est le RPC PRIMAIRE (mesuré 2026-11-25 : ~400 ms vs ~700 ms pour
# le RPC public, et pas de 403) ; le RPC public est le secours.
PRIMARY_RPC = ALCHEMY_RPC or BASE_RPC
RPCS = [PRIMARY_RPC] + ([BASE_RPC] if BASE_RPC != PRIMARY_RPC else [])

_lock = threading.Lock()
_stop_at = 0.0


def log(rec: dict) -> None:
    rec["t_ms"] = int(time.time() * 1000)
    with _lock:
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")


# ------------------------------------------------------------------ HTTP / RPC
def http_get_json(url: str, timeout: int = 12):
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "leadlag-paper-trade"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, (time.monotonic() - t0) * 1000.0


def rpc_call(rpc_url: str, method: str, params, timeout: int = 12):
    """Appel JSON-RPC avec retry + bascule : essaie l'URL donnée, puis
    chaque RPC de secours (Alchemy), 2 tours avec backoff. Ne lève
    qu'après épuisement. Ne logue JAMAIS l'URL (clé Alchemy dedans)."""
    last_err = None
    urls = [rpc_url] + [u for u in RPCS if u != rpc_url]
    for attempt in range(2):
        for url in urls:
            try:
                payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                      "params": params}).encode()
                req = urllib.request.Request(url, data=payload,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    out = json.loads(r.read().decode())
                if "error" in out:
                    raise RuntimeError(str(out["error"]))
                return out["result"]
            except Exception as e:
                last_err = e
        time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"rpc {method} échec après retries: {last_err}")


def rpc_eth_call(to: str, data_hex: str, timeout: int = 12) -> bytes:
    res = rpc_call(PRIMARY_RPC, "eth_call",
                   [{"to": to, "data": data_hex}, "latest"], timeout=timeout)
    return bytes.fromhex(res[2:])


def decode_slot0(raw: bytes):
    """Décode slot0() : (sqrtPriceX96, tick)."""
    sqrt_x96 = int.from_bytes(raw[0:32], "big")
    tick_raw = int.from_bytes(raw[32:64], "big")
    tick = tick_raw - (1 << 256) if tick_raw >= (1 << 255) else tick_raw
    return sqrt_x96, tick


def quote_with_fallback(token_in: str, token_out: str, fee_bps: int,
                        amount_in_wei: int):
    """Quote QuoterV2 : RPC primaire (Alchemy) d'abord, public en secours."""
    q = quote_v3_onchain(token_in, token_out, fee_bps, amount_in_wei,
                         PRIMARY_RPC, timeout=12)
    if q.source == "quoter_v2_onchain":
        return q
    return quote_v3_onchain(token_in, token_out, fee_bps, amount_in_wei,
                            BASE_RPC, timeout=12)


# ------------------------------------------------------------------ Binance depth
def binance_depth(sym: str):
    """Order book Binance (top 1000 niveaux). Retourne les agrégats du signal."""
    d, rtt = http_get_json(f"{BINANCE}/api/v3/depth?symbol={sym}&limit={DEPTH_LIMIT}")
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0

    def band_stats(band_pct: float):
        lo, hi = mid * (1 - band_pct / 100.0), mid * (1 + band_pct / 100.0)
        bid_d = sum(p * q for p, q in bids if p >= lo)
        ask_d = sum(p * q for p, q in asks if p <= hi)
        tot = bid_d + ask_d
        imb = (bid_d - ask_d) / tot if tot > 0 else 0.0
        return bid_d, ask_d, imb

    # Volume (USDT) à consommer pour déplacer le prix de 0,1 % :
    # asks sous mid*1,001 (hausse) / bids au-dessus de mid*0,999 (baisse).
    vol_up = sum(p * q for p, q in asks if p < mid * 1.001)
    vol_dn = sum(p * q for p, q in bids if p > mid * 0.999)
    # Largeur couverte par les 1000 niveaux (honnêteté : bandes partielles ?)
    cov_bid = (mid - bids[-1][0]) / mid * 100.0
    cov_ask = (asks[-1][0] - mid) / mid * 100.0
    b01, a01, i01 = band_stats(0.1)
    b05, a05, i05 = band_stats(0.5)
    return {
        "mid": mid, "best_bid": best_bid, "best_ask": best_ask,
        "spread_bps": (best_ask - best_bid) / mid * 10_000.0,
        "imb_01": i01, "bid_d_01": b01, "ask_d_01": a01,
        "imb_05": i05, "bid_d_05": b05, "ask_d_05": a05,
        "vol_to_move_01_up_usdt": vol_up, "vol_to_move_01_dn_usdt": vol_dn,
        "covered_bid_pct": cov_bid, "covered_ask_pct": cov_ask,
        "rtt_ms": round(rtt, 1),
    }


# ------------------------------------------------------------------ Base V3 state
def _addr_b32(a: str) -> bytes:
    return bytes.fromhex(a[2:].lower().rjust(64, "0"))


def pool_state(pool: str):
    """slot0 + liquidité d'un pool V3 (eth_call bruts, pas de web3)."""
    # slot0() = 0x3850c7bd ; liquidity() = 0x1a686502
    raw = rpc_eth_call(pool, "0x3850c7bd")
    sqrt_x96 = int.from_bytes(raw[0:32], "big")
    tick_raw = int.from_bytes(raw[32:64], "big")
    tick = tick_raw - (1 << 256) if tick_raw >= (1 << 255) else tick_raw
    raw_l = rpc_eth_call(pool, "0x1a686502")
    liq = int.from_bytes(raw_l[0:32], "big")
    return sqrt_x96, tick, liq


def get_pool(token_a: str, token_b: str, fee: int):
    """factory.getPool — vérifie l'existence du pool (0x0 = inexistant)."""
    sel = bytes.fromhex("1698ee82")
    data = "0x" + (sel + _addr_b32(token_a) + _addr_b32(token_b)
                   + int(fee).to_bytes(32, "big")).hex()
    raw = rpc_eth_call(FACTORY, data)
    return "0x" + raw[12:32].hex()


def tier_to_bps(fee_tier: int) -> int:
    """Tier Uniswap (100 = 0,01 %) -> vrais basis points pour v3_quote_python
    (qui attend 1 = 0,01 %, cf. _TICK_SPACING_BPS {1,5,30,100}).
    NE JAMAIS passer le tier brut (100) : il serait lu comme 1 % de frais.
    quote_v3_onchain, lui, attend le tier brut (uint24 du pool)."""
    return max(1, fee_tier // 100)


def price_from_sqrt(sqrt_x96: int, asset_dec: int, asset_is_token0: bool) -> float:
    """Prix humain USDC par asset, depuis sqrtPriceX96 (ajusté décimales)."""
    sqrt_p = sqrt_x96 / 2 ** 96
    adj = 10.0 ** (asset_dec - 6)
    if asset_is_token0:
        return sqrt_p * sqrt_p * adj
    return adj / (sqrt_p * sqrt_p)


def shifted_sqrt(sqrt_x96: int, move_pct: float, asset_is_token0: bool) -> int:
    """sqrtPriceX96 après un mouvement de prix de move_pct % (asset vs USDC)."""
    f = math.sqrt(1.0 + move_pct / 100.0)
    if asset_is_token0:
        return int(sqrt_x96 * f)
    return int(sqrt_x96 / f)


# ------------------------------------------------------------------ stats (corrélation / pente)
def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return 0.0, 0.0
    corr = sxy / math.sqrt(sxx * syy)
    slope = sxy / sxx  # move_pct par unité d'imbalance
    return corr, slope


def abs_pct(vals, q):
    """Percentile q (0-100) des |valeurs| ; None si liste vide."""
    if not vals:
        return None
    a = sorted(abs(v) for v in vals)
    i = min(len(a) - 1, max(0, int(math.ceil(q / 100.0 * len(a))) - 1))
    return a[i]


# ------------------------------------------------------------------ net analytique
def net_at_size(size_usd: float, sqrt_x96: int, liq: int, fee_bps: int,
                asset_dec: int, asset_is_token0: bool, move_pct: float,
                gas_total_usd: float):
    """Net PRÉDIT d'un trade lead-lag de taille size_usd (PAPER).
    Achat USDC->asset maintenant (formule V3 mono-tick), vente asset->USDC
    après le mouvement prédit (même L, sqrtP décalé — approximation
    déclarée). Frais du tier déjà dans la formule (1-f). Flash 0 % Morpho.
    Retourne (net, proceeds, impact_buy_pct) ou None si taille invalide."""
    try:
        amount_in_raw = size_usd * 1e6  # USDC 6 décimales
        buy = v3_quote_python(amount_in_raw, float(liq), sqrt_x96,
                              fee_bps=tier_to_bps(fee_bps),
                              zero_for_one=not asset_is_token0)
        if buy.amount_out <= 0:
            return None
        # Prix d'exécution achat vs mid (impact) :
        mid = price_from_sqrt(sqrt_x96, asset_dec, asset_is_token0)
        exec_px = size_usd / (buy.amount_out / 10 ** asset_dec)
        impact = (exec_px - mid) / mid * 100.0 if mid > 0 else 0.0
        if abs(impact) > 1.0:
            return None  # modèle mono-tick non fiable au-delà de 1 % d'impact
        sqrt_fut = shifted_sqrt(sqrt_x96, move_pct, asset_is_token0)
        sell = v3_quote_python(buy.amount_out, float(liq), sqrt_fut,
                               fee_bps=tier_to_bps(fee_bps),
                               zero_for_one=asset_is_token0)
        proceeds = sell.amount_out / 1e6
        net = proceeds - size_usd - gas_total_usd
        return net, proceeds, impact
    except Exception:
        return None


SIZES = [100, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000]


def best_net(sqrt_x96: int, liq: int, fee_bps: int, asset_dec: int,
             asset_is_token0: bool, move_pct: float, gas_total_usd: float):
    """Taille optimale (grille) + meilleur net prédit. None si rien de valide."""
    best = None
    for s in SIZES:
        if s > MAX_LOAN_USD:
            continue
        r = net_at_size(float(s), sqrt_x96, liq, fee_bps, asset_dec,
                        asset_is_token0, move_pct, gas_total_usd)
        if r is None:
            continue
        net, proceeds, impact = r
        if best is None or net > best["net_usd"]:
            best = {"size_usd": float(s), "net_usd": net,
                    "proceeds_usd": proceeds, "impact_buy_pct": impact}
    return best


def roundtrip_cost_usd(size_usd: float, sqrt_x96: int, liq: int, fee_bps: int,
                       asset_dec: int, asset_is_token0: bool):
    """Coût aller-retour à mouvement NUL (frais + impact, en $) pour UNE pool :
    achat USDC->asset puis revente immédiate au même sqrtP (même L, même
    tier). Retourne (cost_usd, impact_buy_pct) ou None si taille invalide
    (impact > 1 % : modèle mono-tick non fiable)."""
    try:
        buy = v3_quote_python(size_usd * 1e6, float(liq), sqrt_x96,
                              fee_bps=tier_to_bps(fee_bps),
                              zero_for_one=not asset_is_token0)
        if buy.amount_out <= 0:
            return None
        mid = price_from_sqrt(sqrt_x96, asset_dec, asset_is_token0)
        exec_px = size_usd / (buy.amount_out / 10 ** asset_dec)
        impact = (exec_px - mid) / mid * 100.0 if mid > 0 else 0.0
        if abs(impact) > 1.0:
            return None
        sell = v3_quote_python(buy.amount_out, float(liq), sqrt_x96,
                               fee_bps=tier_to_bps(fee_bps),
                               zero_for_one=asset_is_token0)
        proceeds = sell.amount_out / 1e6
        return size_usd - proceeds, impact
    except Exception:
        return None


def threshold_for_tier(sqrt_x96: int, liq: int, fee_bps: int, asset_dec: int,
                       asset_is_token0: bool, gas_total_usd: float):
    """THRESHOLD PAR POOL (raffinement Ismail 2026-11-25 10:22) : mouvement
    minimal (%) qui couvre frais + impact + gas + budget revert POUR
    CETTE POOL précise. = min sur les tailles du coût aller-retour à
    mouvement nul + gas, exprimé en % de la taille. Exemples attendus :
    pool 0,01 % -> ~0,02 % ; pool 0,3 % -> ~0,6 %. La même prédiction
    de mouvement peut donc être ENTRY sur l'une et SKIP sur l'autre.
    Retourne dict ou None (pool inutilisable)."""
    best = None
    for s in SIZES:
        if s > MAX_LOAN_USD:
            continue
        r = roundtrip_cost_usd(float(s), sqrt_x96, liq, fee_bps, asset_dec,
                               asset_is_token0)
        if r is None:
            continue
        cost_usd, impact = r
        total = cost_usd + gas_total_usd
        pct = total / s * 100.0
        if best is None or pct < best["threshold_pct"]:
            best = {"threshold_pct": pct, "threshold_usd": total,
                    "best_size_usd": float(s), "roundtrip_cost_usd": cost_usd,
                    "impact_buy_pct": impact, "fee_bps": fee_bps}
    return best


# ------------------------------------------------------------------ run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-minutes", type=float, default=30.0)
    ap.add_argument("--calibration-minutes", type=float, default=10.0)
    ap.add_argument("--pairs", default="ETH,SOSO,AERO,ICNT")
    args = ap.parse_args()
    global _stop_at
    duration_s = args.duration_minutes * 60.0
    calib_s = args.calibration_minutes * 60.0
    want = {p.strip().upper() for p in args.pairs.split(",")}
    pairs = [p for p in PAIRS if p["name"].split("/")[0] in want]
    t_start = time.time()
    _stop_at = t_start + duration_s
    print(f"paper-trade lead-lag order books: {args.duration_minutes:.0f} min "
          f"(calibration {args.calibration_minutes:.0f} min) -> {OUT}", flush=True)
    print(f"paires: {[p['name'] for p in pairs]} | BASE seulement, PAPER", flush=True)

    # --- vérification des pools + choix du tier primaire (prix exact à 1 000 $)
    pool_addr = {}
    asset_is_t0 = {}
    for p in pairs:
        a, b = p["asset"], USDC_BASE
        asset_is_t0[p["name"]] = a.lower() < b.lower()
        live = {}
        for fee in p["tiers"]:
            try:
                addr = get_pool(a, b, fee)
            except Exception as e:
                print(f"  {p['name']} fee {fee}: getPool erreur {e}", flush=True)
                continue
            if addr != "0x0000000000000000000000000000000000000000":
                live[fee] = addr
        pool_addr[p["name"]] = live
        print(f"  {p['name']} pools live: " +
              ", ".join(f"{f}bps={a[:10]}.." for f, a in live.items()), flush=True)
        prim = PRIMARY_TIER[p["name"]]
        if prim not in live:
            # repli : tier live au plus bas frais
            prim = min(live) if live else None
            print(f"  {p['name']} primaire {PRIMARY_TIER[p['name']]} absent -> {prim}",
                  flush=True)
        p["primary_fee"] = prim
        p["primary_pool"] = live.get(prim)

    # --- état par tier (slot0 + liquidité) pour les THRESHOLDS PAR POOL.
    # Lu une fois au démarrage (retry + fallback RPC), puis rafraîchi en
    # rotation pendant le run (1 tier non-primaire par cycle, ~16 s chacun ;
    # le tier primaire est relu à chaque cycle).
    tier_state = {}
    for p in pairs:
        tier_state[p["name"]] = {}
        for fee, addr in pool_addr[p["name"]].items():
            try:
                s0, tk, lq = pool_state(addr)
                tier_state[p["name"]][fee] = {"pool": addr, "sqrt_x96": s0,
                                              "tick": tk, "liq": lq,
                                              "updated_t": time.time()}
            except Exception as e:
                print(f"  {p['name']} fee {fee}: état initial indisponible ({e})",
                      flush=True)
        print(f"  {p['name']} tiers avec état: " +
              ", ".join(f"{f}bps L={st['liq']:.3g}"
                        for f, st in tier_state[p["name"]].items()), flush=True)
    refresh_queue = [(p["name"], fee) for p in pairs
                     for fee in tier_state[p["name"]]
                     if fee != p.get("primary_fee")]
    refresh_ptr = [0]

    # Le temps de vérification des pools (~15 s de RPC) ne doit pas manger
    # la calibration : le chronomètre (t_start + _stop_at) démarre ICI,
    # après la vérification — sinon une calibration courte (ex. 30 s) se
    # termine avec 1 seul échantillon.
    t_start = time.time()
    _stop_at = t_start + duration_s

    # --- état : échantillons récents par paire (pour moves réalisés +2s/+4s)
    recent = {p["name"]: deque(maxlen=40) for p in pairs}  # ~80 s d'historique
    # historique DEX (mid pool) par paire — pour TOUTES les paires : sert
    # (a) la mesure des mouvements bruts des paires SANS signal Binance,
    # (b) la distribution des mouvements DEX (analyseur) et le check survie.
    dex_recent = {p["name"]: deque(maxlen=40) for p in pairs}
    calib = {p["name"]: {"imb01": [], "mv_next": [], "mv_next2": [],
                         "imb05": [], "mv_next_b": [], "mv_next2_b": [],
                         "dt_next": [], "dt_next2": [],
                         "dex_mv_next": [], "dex_mv_next2": [],
                         "dex_dt_next": [], "dex_dt_next2": []} for p in pairs}
    model = {p["name"]: None for p in pairs}  # (band, corr, slope)
    phase = "calibration"
    gas_usd = GAS_USD_FALLBACK
    gas_known = False
    n_cycles = 0
    n_eval = 0
    n_entry = 0
    n_opp = [0]  # opportunités rétrospectives (paires sans signal Binance)

    def fetch_all():
        """Un cycle : Binance depth x3 + gas + état Base, en parallèle."""
        jobs = {}

        def run(fn, key):
            try:
                jobs[key] = ("ok", fn())
            except Exception as e:
                jobs[key] = ("err", f"{type(e).__name__}: {str(e)[:80]}")

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = []
            for p in pairs:
                # pas de job Binance pour les paires non listées (bin_sym=None)
                if p.get("bin_sym"):
                    futs.append(ex.submit(run, lambda p=p: binance_depth(p["bin_sym"]),
                                          ("bin", p["name"])))
            futs.append(ex.submit(run, lambda: rpc_call(PRIMARY_RPC, "eth_gasPrice", []),
                                  ("gas",)))
            # refresh tournant : 1 tier non-primaire par cycle
            if refresh_queue:
                rp, rf = refresh_queue[refresh_ptr[0] % len(refresh_queue)]
                refresh_ptr[0] += 1
                futs.append(ex.submit(
                    run, lambda rp=rp, rf=rf: (rp, rf, pool_state(
                        tier_state[rp][rf]["pool"])), ("refresh",)))
            for p in pairs:
                if p.get("primary_pool"):
                    # slot0 et liquidité en parallèle (pas séquentiel)
                    futs.append(ex.submit(
                        run, lambda p=p: rpc_eth_call(p["primary_pool"], "0x3850c7bd"),
                        ("slot0", p["name"])))
                    futs.append(ex.submit(
                        run, lambda p=p: rpc_eth_call(p["primary_pool"], "0x1a686502"),
                        ("liq", p["name"])))
                    # quotes 1 000 $ par tier : ancrage de validation, 1 cycle sur 15
                    # seulement (sinon 11 appels/cycle pour rien — le sizing
                    # analytique utilise L/sqrtP).
                    if n_cycles % 15 == 0:
                        for fee, addr in pool_addr[p["name"]].items():
                            futs.append(ex.submit(
                                run, lambda p=p, fee=fee: quote_with_fallback(
                                    USDC_BASE, p["asset"], fee, 1_000_000_000),
                                ("q1k", p["name"], fee)))
            for f in futs:
                f.result()
        return jobs

    while time.time() < _stop_at:
        t_cycle = time.time()
        if phase == "calibration" and (t_cycle - t_start) >= calib_s:
            # --- fin de calibration : corrélation imbalance -> move
            for p in pairs:
                c = calib[p["name"]]
                if not p.get("bin_sym"):
                    # PAIRE SANS SIGNAL BINANCE : pas de modèle imbalance.
                    # La calibration = distribution des mouvements DEX bruts
                    # (le test de la thèse « les petites pools bougent plus »).
                    model[p["name"]] = None
                    mv1, mv2 = c["dex_mv_next"], c["dex_mv_next2"]
                    log({"kind": "calibration", "pair": p["name"],
                         "binance_signal": False,
                         "n_samples": len(mv1),
                         "dex_mv_next_median_abs_pct": (
                             round(median([abs(v) for v in mv1]), 5) if mv1 else None),
                         "dex_mv_next_p95_abs_pct": (
                             round(abs_pct(mv1, 95), 5) if mv1 else None),
                         "dex_mv_next_max_abs_pct": (
                             round(max(abs(v) for v in mv1), 5) if mv1 else None),
                         "dex_mv_next2_median_abs_pct": (
                             round(median([abs(v) for v in mv2]), 5) if mv2 else None),
                         "dex_mv_next2_p95_abs_pct": (
                             round(abs_pct(mv2, 95), 5) if mv2 else None),
                         "dex_mv_next2_max_abs_pct": (
                             round(max(abs(v) for v in mv2), 5) if mv2 else None),
                         "median_dt_next_s": round(median(c["dex_dt_next"]), 2)
                         if c["dex_dt_next"] else None,
                         "median_dt_next2_s": round(median(c["dex_dt_next2"]), 2)
                         if c["dex_dt_next2"] else None})
                    print(f"  [calib] {p['name']}: NO BINANCE SIGNAL | "
                          f"n={len(mv1)} DEX moves: médiane |mv| "
                          f"{median([abs(v) for v in mv1]) if mv1 else 0:.4f}% "
                          f"p95 {abs_pct(mv1, 95) if mv1 else 0:.4f}% "
                          f"max {max(abs(v) for v in mv1) if mv1 else 0:.4f}% "
                          f"(+1 cycle)", flush=True)
                    continue
                corr01_n, sl01_n = pearson(c["imb01"], c["mv_next"])
                corr01_n2, sl01_n2 = pearson(c["imb01"], c["mv_next2"])
                corr05_n, sl05_n = pearson(c["imb05"], c["mv_next_b"])
                corr05_n2, sl05_n2 = pearson(c["imb05"], c["mv_next2_b"])
                cands = [("imb01@next", corr01_n, sl01_n),
                         ("imb01@next2", corr01_n2, sl01_n2),
                         ("imb05@next", corr05_n, sl05_n),
                         ("imb05@next2", corr05_n2, sl05_n2)]
                best_band, best_corr, best_slope = max(cands, key=lambda t: abs(t[1]))
                model[p["name"]] = {"band": best_band, "corr": best_corr,
                                    "slope": best_slope, "n": len(c["imb01"]),
                                    "all": {k: round(v, 4) for k, v, _ in
                                            [(c[0], c[1], c[2]) for c in cands]}}
                log({"kind": "calibration", "pair": p["name"],
                     "n_samples": len(c["imb01"]),
                     "corr_imb01_mv_next": round(corr01_n, 4),
                     "slope_imb01_mv_next": round(sl01_n, 6),
                     "corr_imb01_mv_next2": round(corr01_n2, 4),
                     "slope_imb01_mv_next2": round(sl01_n2, 6),
                     "corr_imb05_mv_next": round(corr05_n, 4),
                     "slope_imb05_mv_next": round(sl05_n, 6),
                     "corr_imb05_mv_next2": round(corr05_n2, 4),
                     "slope_imb05_mv_next2": round(sl05_n2, 6),
                     "median_dt_next_s": round(median(c["dt_next"]), 2)
                     if c["dt_next"] else None,
                     "median_dt_next2_s": round(median(c["dt_next2"]), 2)
                     if c["dt_next2"] else None,
                     "chosen_band": best_band, "chosen_corr": round(best_corr, 4),
                     "chosen_slope": round(best_slope, 6)})
                print(f"  [calib] {p['name']}: n={len(c['imb01'])} "
                      f"corr imb01->next={corr01_n:.3f} next2={corr01_n2:.3f} | "
                      f"imb05->next={corr05_n:.3f} next2={corr05_n2:.3f} | "
                      f"dt_next médian={median(c['dt_next']) if c['dt_next'] else 0:.1f}s | "
                      f"choisi {best_band} corr={best_corr:.3f} slope={best_slope:.4f}",
                      flush=True)
            phase = "live"
            print("  >>> phase LIVE (entrées papier activées)", flush=True)
        jobs = fetch_all()
        n_cycles += 1

        # gas live
        g = jobs.get(("gas",))
        if g and g[0] == "ok":
            try:
                gwei = int(g[1], 16) / 1e9
                eth_px = None
                b = jobs.get(("bin", "ETH/USDC"))
                if b and b[0] == "ok":
                    eth_px = b[1]["mid"]
                if eth_px:
                    gas_usd = GAS_UNITS * gwei * 1e-9 * eth_px
                    gas_known = True
            except Exception:
                pass
        gas_total = 2.0 * gas_usd  # trade + budget revert

        for p in pairs:
            name = p["name"]
            has_bin = p.get("bin_sym") is not None
            b = jobs.get(("bin", name)) if has_bin else None
            s0j = jobs.get(("slot0", name))
            lqj = jobs.get(("liq", name))
            if has_bin and (not b or b[0] != "ok"):
                log({"kind": "eval", "pair": name, "phase": phase,
                     "decision": "ERROR",
                     "error": b[1] if b else "binance?",
                     "gas_total_usd": round(gas_total, 6)})
                continue
            bd = b[1] if b else None
            # --- échantillon pour la calibration (Binance seul : survit aux
            # pannes du pool — sinon une panne RPC tue toute la calibration)
            if bd is not None:
                samp = {"t": t_cycle, "mid": bd["mid"],
                        "imb01": bd["imb_01"], "imb05": bd["imb_05"]}
                rq = recent[name]
                rq.append(samp)
                # résoudre : mouvement jusqu'à l'échantillon SUIVANT (+1 cycle)
                # et celui d'APRÈS (+2 cycles) — fenêtres ADAPTATIVES au cycle
                # réel (~3-4 s, pas 2 s) : des fenêtres fixes en secondes
                # rateraient des échantillons quand un cycle dépasse 4 s.
                # Le dt réel est enregistré (médiane = horizon effectif).
                if len(rq) >= 2:
                    prev = rq[-2]
                    if "mv_next" not in prev:
                        prev["mv_next"] = (bd["mid"] - prev["mid"]) / prev["mid"] * 100.0
                        prev["dt_next"] = t_cycle - prev["t"]
                        c = calib[name]
                        c["imb01"].append(prev["imb01"]); c["mv_next"].append(prev["mv_next"])
                        c["imb05"].append(prev["imb05"]); c["mv_next_b"].append(prev["mv_next"])
                        c["dt_next"].append(prev["dt_next"])
                if len(rq) >= 3:
                    prev2 = rq[-3]
                    if "mv_next2" not in prev2:
                        prev2["mv_next2"] = (bd["mid"] - prev2["mid"]) / prev2["mid"] * 100.0
                        prev2["dt_next2"] = t_cycle - prev2["t"]
                        c = calib[name]
                        c["mv_next2"].append(prev2["mv_next2"])
                        c["mv_next2_b"].append(prev2["mv_next2"])
                        c["dt_next2"].append(prev2["dt_next2"])
            n_eval += 1
            if not s0j or s0j[0] != "ok" or not lqj or lqj[0] != "ok":
                err_rec = {"kind": "eval", "pair": name, "phase": phase,
                           "decision": "ERROR",
                           "error": (s0j[1] if s0j and s0j[0] != "ok" else None) or
                                    (lqj[1] if lqj and lqj[0] != "ok" else "slot0/liq?"),
                           "gas_total_usd": round(gas_total, 6)}
                if bd is not None:
                    err_rec.update({"bin_mid": round(bd["mid"], 6),
                                    "imb_01": round(bd["imb_01"], 4),
                                    "imb_05": round(bd["imb_05"], 4)})
                log(err_rec)
                continue
            sqrt_x96, tick = decode_slot0(s0j[1])
            liq = int.from_bytes(lqj[1][0:32], "big")
            is_t0 = asset_is_t0[name]
            # rafraîchir l'état du tier primaire + appliquer le refresh tournant
            if p["primary_fee"] in tier_state[name]:
                tier_state[name][p["primary_fee"]] = {
                    "pool": p["primary_pool"], "sqrt_x96": sqrt_x96,
                    "tick": tick, "liq": liq, "updated_t": t_cycle}
            rf = jobs.get(("refresh",))
            if rf and rf[0] == "ok":
                rp_name, rf_fee, rf_state = rf[1]
                if rp_name in tier_state and rf_fee in tier_state[rp_name]:
                    tier_state[rp_name][rf_fee] = {
                        "pool": tier_state[rp_name][rf_fee]["pool"],
                        "sqrt_x96": rf_state[0], "tick": rf_state[1],
                        "liq": rf_state[2], "updated_t": t_cycle}
            mid_dex = price_from_sqrt(sqrt_x96, p["dec"], is_t0)
            # --- historique DEX : mouvements réalisés (toutes paires).
            # Résout les moves +1/+2 cycles des échantillons précédents
            # (fenêtres adaptatives, dt réel enregistré). Sert la calibration
            # des paires SANS signal Binance + la distribution des mouvements.
            dq = dex_recent[name]
            dq.append({"t": t_cycle, "mid": mid_dex})
            c = calib[name]
            if len(dq) >= 2:
                prev = dq[-2]
                if "mv_next" not in prev:
                    prev["mv_next"] = (mid_dex - prev["mid"]) / prev["mid"] * 100.0
                    prev["dt_next"] = t_cycle - prev["t"]
                    c["dex_mv_next"].append(prev["mv_next"])
                    c["dex_dt_next"].append(prev["dt_next"])
            if len(dq) >= 3:
                prev2 = dq[-3]
                if "mv_next2" not in prev2:
                    prev2["mv_next2"] = (mid_dex - prev2["mid"]) / prev2["mid"] * 100.0
                    prev2["dt_next2"] = t_cycle - prev2["t"]
                    c["dex_mv_next2"].append(prev2["mv_next2"])
                    c["dex_dt_next2"].append(prev2["dt_next2"])
            # mouvements DEX réalisés du cycle courant (décision des paires
            # sans signal Binance + distribution par pool)
            dex_mv_1c = ((mid_dex - dq[-2]["mid"]) / dq[-2]["mid"] * 100.0
                         if len(dq) >= 2 else None)
            dex_mv_2c = ((mid_dex - dq[-3]["mid"]) / dq[-3]["mid"] * 100.0
                         if len(dq) >= 3 else None)
            # quotes 1 000 $ par tier (ancrage exact on-chain)
            q1k = {}
            for fee in pool_addr[name]:
                q = jobs.get(("q1k", name, fee))
                if q and q[0] == "ok" and q[1].source == "quoter_v2_onchain":
                    out = q[1].amount_out / 10 ** p["dec"]
                    px = 1000.0 / out if out > 0 else None
                    q1k[fee] = {"exec_px": px,
                                "impact_pct": ((px - mid_dex) / mid_dex * 100.0
                                              if px and mid_dex else None)}
            rec = {"kind": "eval", "pair": name, "phase": phase,
                   "binance_signal": has_bin,
                   "dex_mid": round(mid_dex, 6), "dex_tick": tick,
                   "dex_liq": liq, "dex_fee_bps": p["primary_fee"],
                   "dex_mv_1c_pct": (round(dex_mv_1c, 5)
                                     if dex_mv_1c is not None else None),
                   "dex_mv_2c_pct": (round(dex_mv_2c, 5)
                                     if dex_mv_2c is not None else None),
                   "q1k": {str(f): {k: (round(v, 6) if isinstance(v, float) else v)
                                    for k, v in v.items()} for f, v in q1k.items()},
                   "gas_total_usd": round(gas_total, 6),
                   "gas_known": gas_known}
            if bd is not None:
                rec.update({
                    "bin_mid": round(bd["mid"], 6),
                    "bin_spread_bps": round(bd["spread_bps"], 3),
                    "imb_01": round(bd["imb_01"], 4),
                    "imb_05": round(bd["imb_05"], 4),
                    "bid_d_01_usdt": round(bd["bid_d_01"], 1),
                    "ask_d_01_usdt": round(bd["ask_d_01"], 1),
                    "bid_d_05_usdt": round(bd["bid_d_05"], 1),
                    "ask_d_05_usdt": round(bd["ask_d_05"], 1),
                    "vol_to_move_01_up_usdt": round(bd["vol_to_move_01_up_usdt"], 1),
                    "vol_to_move_01_dn_usdt": round(bd["vol_to_move_01_dn_usdt"], 1),
                    "covered_bid_pct": round(bd["covered_bid_pct"], 3),
                    "covered_ask_pct": round(bd["covered_ask_pct"], 3)})
            # --- THRESHOLDS PAR POOL (raffinement Ismail 10:22) : breakeven
            # individuel de chaque tier (fee réelle + impact + gas + revert).
            # Logué dans CHAQUE évaluation, calibration comprise.
            thresholds = {}
            for fee, st in tier_state[name].items():
                if st["liq"] <= 0:
                    continue
                th = threshold_for_tier(st["sqrt_x96"], st["liq"], fee,
                                        p["dec"], is_t0, gas_total)
                if th:
                    thresholds[fee] = th
            rec["thresholds"] = {str(f): {
                "threshold_pct": round(th["threshold_pct"], 4),
                "threshold_usd": round(th["threshold_usd"], 4),
                "best_size_usd": th["best_size_usd"],
                "roundtrip_cost_usd": round(th["roundtrip_cost_usd"], 4),
                "impact_buy_pct": round(th["impact_buy_pct"], 4),
                "fee_bps": th["fee_bps"],
                "liq": tier_state[name][f]["liq"],
            } for f, th in thresholds.items()}

            if phase == "calibration":
                if has_bin:
                    rec["decision"] = "NO_DECISION"
                    rec["decision_reason"] = "calibration en cours"
                else:
                    rec["decision"] = "MEASURE"
                    rec["decision_reason"] = ("no Binance signal — mesure des "
                                              "mouvements DEX bruts (calibration)")
                log(rec)
                continue

            if not has_bin:
                # --- PAIRE SANS SIGNAL BINANCE : mesure brute + opportunité
                # RÉTROSPECTIVE. Le mouvement DEX réalisé a-t-il dépassé le
                # seuil min de la pool ? Ce n'est PAS une prédiction : le
                # mouvement a déjà eu lieu. Ça mesure si les petites pools
                # bougent assez (la thèse d'Ismail), pas si on pouvait entrer.
                # Le net rétrospectif = net d'un trade qui aurait pris le
                # mouvement dans le bon sens (calculé sur |mouvement|).
                cands_mv = [v for v in (dex_mv_1c, dex_mv_2c) if v is not None]
                mv = max(cands_mv, key=abs) if cands_mv else None
                min_th = None
                min_fee = None
                for fee, th in thresholds.items():
                    if min_th is None or th["threshold_pct"] < min_th:
                        min_th = th["threshold_pct"]
                        min_fee = fee
                rec["min_threshold_pct"] = (round(min_th, 4)
                                            if min_th is not None else None)
                rec["min_threshold_fee_bps"] = min_fee
                rec["realized_move_pct"] = (round(mv, 5)
                                            if mv is not None else None)
                if mv is None or min_th is None:
                    rec["decision"] = "MEASURE"
                    rec["decision_reason"] = "pas assez d'historique DEX"
                    log(rec)
                    continue
                st = tier_state[name][min_fee]
                bn = best_net(st["sqrt_x96"], st["liq"], min_fee, p["dec"],
                              is_t0, abs(mv), gas_total)
                if bn:
                    rec["retrospective_net_usd"] = round(bn["net_usd"], 4)
                    rec["retrospective_size_usd"] = bn["size_usd"]
                    rec["retrospective_direction"] = ("LONG" if mv > 0
                                                      else "SHORT")
                if abs(mv) > min_th:
                    rec["decision"] = "OPPORTUNITY"
                    rec["decision_reason"] = ("mouvement DEX réalisé > seuil min "
                                              "(rétrospectif — mouvement déjà "
                                              "eu lieu, pas une prédiction)")
                    n_opp[0] += 1
                else:
                    rec["decision"] = "MEASURE"
                    rec["decision_reason"] = "mouvement DEX réalisé <= seuil min"
                log(rec)
                continue

            # --- phase LIVE : prédiction + net prévu
            m = model[name]
            if m is None or abs(m["corr"]) < 0.10:
                rec["decision"] = "SKIP"
                rec["decision_reason"] = "no_signal: |corr| < 0,10 (signal = bruit)"
                rec["model_corr"] = round(m["corr"], 4) if m else None
                rec["model_band"] = m["band"] if m else None
                log(rec)
                continue
            band = m["band"]
            imb = bd["imb_01"] if "imb01" in band else bd["imb_05"]
            pred_move_pct = m["slope"] * imb  # % prédit sur 2-4 s
            direction = "LONG" if pred_move_pct > 0 else ("SHORT" if pred_move_pct < 0
                                                         else "FLAT")
            rec["model_band"] = band
            rec["model_corr"] = round(m["corr"], 4)
            rec["model_slope"] = round(m["slope"], 6)
            rec["model_n"] = m["n"]
            rec["imb_used"] = round(imb, 4)
            rec["pred_move_pct"] = round(pred_move_pct, 5)
            rec["direction"] = direction
            if direction == "FLAT":
                rec["decision"] = "SKIP"
                rec["decision_reason"] = "mouvement prédit = 0"
                log(rec)
                continue
            # --- décision PAR POOL : la même prédiction de mouvement peut
            # être ENTRY sur une pool (threshold bas) et SKIP sur une autre
            # (threshold haut) — c'est exactement ce qu'Ismail veut mesurer.
            tier_decisions = {}
            best_overall = None
            for fee, th in thresholds.items():
                st = tier_state[name][fee]
                bn = best_net(st["sqrt_x96"], st["liq"], fee, p["dec"], is_t0,
                              pred_move_pct, gas_total)
                d = "ENTRY" if (bn and bn["net_usd"] > 0) else "SKIP"
                tier_decisions[fee] = {
                    "decision": d,
                    "pred_net_usd": round(bn["net_usd"], 4) if bn else None,
                    "opt_size_usd": bn["size_usd"] if bn else None,
                    "threshold_pct": round(th["threshold_pct"], 4),
                    "threshold_usd": round(th["threshold_usd"], 4),
                }
                if bn and (best_overall is None
                           or bn["net_usd"] > best_overall["net_usd"]):
                    best_overall = {**bn, "fee_bps": fee}
            rec["tier_decisions"] = {str(f): v
                                     for f, v in tier_decisions.items()}
            if best_overall is None:
                rec["decision"] = "SKIP"
                rec["decision_reason"] = ("sizing impossible sur tous les tiers "
                                          "(impact > 1 % ou L=0)")
                log(rec)
                continue
            rec["best_tier_fee_bps"] = best_overall["fee_bps"]
            rec["opt_size_usd"] = best_overall["size_usd"]
            rec["pred_net_usd"] = round(best_overall["net_usd"], 4)
            rec["pred_proceeds_usd"] = round(best_overall["proceeds_usd"], 2)
            rec["impact_buy_pct"] = round(best_overall["impact_buy_pct"], 4)
            if direction == "SHORT":
                rec["note_short"] = ("SHORT papier : nécessite un flash-borrow "
                                     "de l'asset (non construit dans le contrat repo)")
            if best_overall["net_usd"] > 0:
                rec["decision"] = "ENTRY"
                rec["decision_reason"] = ("net prévu > 0 $ après tous coûts "
                                          f"(tier {best_overall['fee_bps']} bps)")
                n_entry += 1
            else:
                rec["decision"] = "SKIP"
                rec["decision_reason"] = "net prévu <= 0 $ sur tous les tiers"
            log(rec)

        dt = CYCLE_S - (time.time() - t_cycle)
        if dt > 0:
            time.sleep(dt)
        if n_cycles % 30 == 0:
            print(f"  [{time.strftime('%H:%M:%S')}] phase={phase} cycles={n_cycles} "
                  f"evals={n_eval} entries={n_entry} opps={n_opp[0]} "
                  f"gas_total=${gas_total:.5f}",
                  flush=True)

    log({"kind": "summary", "duration_min": args.duration_minutes,
         "calibration_min": args.calibration_minutes, "cycles": n_cycles,
         "evals": n_eval, "entries": n_entry, "opportunities": n_opp[0],
         "phase_end": phase})
    print(f"FIN: cycles={n_cycles} evals={n_eval} entries={n_entry} "
          f"opps={n_opp[0]} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
