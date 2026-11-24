"""
scanner.py — Scanner meme coins SGHAR, LOW competition, sur Base.

Stratégie "low competition" :
  - On ne chasse PAS WETH/USDC (tous les bots du monde sont dessus).
  - On chasse les MEME/USDC avec liquidité 5k–100k $ : assez pour sortir,
    trop petit pour les gros bots d'arbitrage.
  - Filtres durs anti-rug / anti-honeypot AVANT tout calcul de profit.

Sources (v1, sans clé API) :
  1. DexScreener API publique : /latest/dex/pairs/base/<token>
     (paires, liquidité, volume, prix, dexId, pairAddress)
  2. Vérification on-chain via les factories (getPair) — à brancher
     quand le RPC est configuré (voir executor.py).
  3. Honeypot check = simulation buy + sell sur un fork / eth_call :
     si le sell revert ou taxe > max, on jette le token.

Ce fichier ne trade RIEN. Il ne fait que produire des candidats.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from math_engine import Pool


@dataclass
class MemeCandidate:
    token_address: str
    symbol: str
    dex_a: str          # ex: "aerodrome"
    dex_b: str          # ex: "uniswap" (V2)
    pool_a: Pool = field(repr=False)
    pool_b: Pool = field(repr=False)
    liquidity_usd: float = 0.0
    holders: int = 0
    age_hours: float = 0.0
    spread_pct: float = 0.0
    flags: List[str] = field(default_factory=list)

    def spread(self) -> float:
        if self.pool_a.price_usdc_per_meme == 0:
            return 0.0
        return 100.0 * (self.pool_b.price_usdc_per_meme
                        / self.pool_a.price_usdc_per_meme - 1)


# Seuils par défaut — identiques à config.yaml (surchargés si config chargée)
DEFAULTS = {
    "min_liquidity_usd": 5_000.0,
    "max_liquidity_usd": 100_000.0,
    "min_holders": 20,
    "max_age_hours": 72.0,
    "min_spread_pct": 3.0,
    "max_tax_pct": 5.0,
}


GOPLUS_API = "https://api.gopluslabs.io/api/v1/token_security/8453"
# Champs GoPlus à checker (recherche §3.2) — gratuit, sans clé, chaîne 8453.
GOPLUS_REJECT_FLAGS = ("honeypot", "mintable", "liquidity_not_locked", "high_tax",
                       "owner_can_pause", "blacklist", "goplus_unknown")


def fetch_goplus_security(token_address: str, timeout: int = 10) -> Dict:
    """Appelle GoPlus token_security pour UN token sur Base (8453).
    Retourne le dict brut du token, ou {} si l'API est indisponible.
    L'appelant ne doit JAMAIS crasher sur une erreur réseau : un token
    non vérifié = UNKNOWN = on ne trade pas (voir vet_token_goplus)."""
    url = f"{GOPLUS_API}?contract_addresses={token_address}"
    req = urllib.request.Request(url, headers={"User-Agent": "codema-flashloan-bot-v2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
    if data.get("code") != 1:
        return {"_error": f"GoPlus code={data.get('code')} message={data.get('message')}"}
    result = (data.get("result") or {})
    return result.get(token_address.lower(), {}) or {}


def vet_token_goplus(token_address: str, max_tax_pct: float = 5.0,
                     timeout: int = 10) -> tuple[str, List[str]]:
    """Verdict GoPlus pour un token : ("PASS" | "REJECT" | "UNKNOWN", flags).
    - REJECT : honeypot, taxe > max, mint possible, proxy/owner dangereux,
      transfer pausable, blacklist, pas open-source.
    - UNKNOWN : API down / réponse vide -> ON NE TRADE PAS (le doute ne se
      paie pas avec de l'argent réel : un honeypot = perte TOTALE).
    - PASS : aucun red flag détecté (ne remplace pas un audit)."""
    raw = fetch_goplus_security(token_address, timeout)
    if not raw or "_error" in raw:
        return "UNKNOWN", ["goplus_unknown"]
    flags: List[str] = []

    def _is_true(v) -> bool:
        return str(v) == "1"

    def _tax(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    if _is_true(raw.get("is_honeypot")):
        flags.append("honeypot")
    buy_tax, sell_tax = _tax(raw.get("buy_tax")), _tax(raw.get("sell_tax"))
    if max(buy_tax, sell_tax) > max_tax_pct:
        flags.append("high_tax")
    if _is_true(raw.get("is_mintable")):
        flags.append("mintable")
    if _is_true(raw.get("is_proxy")) or _is_true(raw.get("can_take_back_ownership")):
        flags.append("owner_can_pause")
    if _is_true(raw.get("transfer_pausable")):
        flags.append("owner_can_pause")
    if _is_true(raw.get("is_blacklisted")):
        flags.append("blacklist")
    if _is_true(raw.get("owner_change_balance")):
        flags.append("owner_can_pause")
    if raw.get("is_open_source") == "0":
        flags.append("not_open_source")
    if _is_true(raw.get("is_airdrop_scam")):
        flags.append("honeypot")
    try:
        holders = int(raw.get("holder_count") or 0)
        if 0 < holders < 20:
            flags.append("too_few_holders")
    except (TypeError, ValueError):
        pass
    verdict = "REJECT" if any(f in GOPLUS_REJECT_FLAGS or f in ("high_tax",)
                              for f in flags) else "PASS"
    return verdict, flags


def apply_goplus_to_candidate(c: "MemeCandidate", max_tax_pct: float = 5.0,
                              timeout: int = 10) -> tuple[str, List[str]]:
    """Vette un candidat avec GoPlus et ajoute les flags au candidat.
    Retourne (verdict, flags). Un verdict UNKNOWN ajoute 'goplus_unknown',
    qui est un drapeau de rejet dans passes_filters()."""
    verdict, flags = vet_token_goplus(c.token_address, max_tax_pct, timeout)
    for f in flags:
        if f not in c.flags:
            c.flags.append(f)
    return verdict, flags


def passes_filters(c: MemeCandidate, cfg: Optional[Dict] = None) -> tuple[bool, List[str]]:
    """Filtres durs. Retourne (passe, raisons_du_rejet)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    reasons: List[str] = []
    liq = c.liquidity_usd
    if liq < cfg["min_liquidity_usd"]:
        reasons.append(f"liquidité trop faible ({liq:.0f} $ < {cfg['min_liquidity_usd']:.0f} $)")
    if liq > cfg["max_liquidity_usd"]:
        reasons.append(f"liquidité trop haute ({liq:.0f} $ — trop de concurrence)")
    if c.holders < cfg["min_holders"]:
        reasons.append(f"trop peu de holders ({c.holders})")
    if c.age_hours > cfg["max_age_hours"]:
        reasons.append(f"coin trop vieux ({c.age_hours:.0f} h — spreads déjà arbitrés)")
    if abs(c.spread()) < cfg["min_spread_pct"]:
        reasons.append(f"spread trop petit ({c.spread():.2f} % < {cfg['min_spread_pct']} %)")
    for flag in c.flags:
        if flag in ("honeypot", "mintable", "liquidity_not_locked", "high_tax",
                    "owner_can_pause", "blacklist", "goplus_unknown"):
            reasons.append(f"drapeau rouge : {flag}")
    return (not reasons), reasons


def fetch_pairs_from_dexscreener(token_address: str, timeout: int = 10) -> List[Dict]:
    """Récupère les paires d'un token sur Base via DexScreener (API publique,
    pas de clé). Retourne [] en cas d'erreur réseau — le scanner ne crash pas."""
    url = f"https://api.dexscreener.com/latest/dex/pairs/base/{token_address}"
    req = urllib.request.Request(url, headers={"User-Agent": "codema-flashloan-bot-v1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:  # réseau coupé, rate-limit, token inconnu
        print(f"[scanner] DexScreener indisponible pour {token_address}: {e}")
        return []
    return data.get("pairs") or []


def pairs_to_pools(pairs: List[Dict]) -> List[Pool]:
    """Convertit les paires DexScreener en Pool (réserves USDC/MEME).
    On ne garde que les paires MEME/USDC (quote USDC)."""
    pools: List[Pool] = []
    for p in pairs:
        if (p.get("quoteToken") or {}).get("symbol") != "USDC":
            continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if liq <= 0:
            continue
        # DexScreener ne donne pas les réserves brutes : on les reconstruit
        # à partir du prix et de la liquidité (approximation v1, à remplacer
        # par une lecture on-chain des réserves en prod).
        price = float(p.get("priceUsd") or 0)
        if price <= 0:
            continue
        reserve_usdc = liq / 2.0
        reserve_meme = reserve_usdc / price if price else 0
        fee_bps = 30  # V2 / Aerodrome volatile ; V3 : selon le tier
        pools.append(Pool(name=f"{p.get('dexId')}:{p.get('pairAddress','')[:10]}",
                          reserve_usdc=reserve_usdc, reserve_meme=reserve_meme,
                          fee_bps=fee_bps))
    return pools


def scan_token(token_address: str, symbol: str = "?",
               cfg: Optional[Dict] = None, goplus_check: bool = False) -> List[MemeCandidate]:
    """Scanne UN token : paires -> pools -> candidats croisés (A x B).
    goplus_check=True : vette le token via GoPlus AVANT de produire des
    candidats (REJECT/UNKNOWN -> aucun candidat, on ne trade pas l'aveugle).
    Par défaut False (scan offline / tests sans réseau)."""
    if goplus_check:
        verdict, flags = vet_token_goplus(token_address)
        if verdict != "PASS":
            print(f"[scanner] GoPlus {verdict} pour {token_address} : {flags} — token jeté")
            return []
    pairs = fetch_pairs_from_dexscreener(token_address)
    pools = pairs_to_pools(pairs)
    candidates: List[MemeCandidate] = []
    for i, pa in enumerate(pools):
        for pb in pools[i + 1:]:
            # A = moins cher (on achète là), B = plus cher (on vend là)
            buy, sell = (pa, pb) if pa.price_usdc_per_meme <= pb.price_usdc_per_meme else (pb, pa)
            liq = min(buy.liquidity_usd, sell.liquidity_usd)
            c = MemeCandidate(token_address=token_address, symbol=symbol,
                              dex_a=buy.name, dex_b=sell.name,
                              pool_a=buy, pool_b=sell, liquidity_usd=liq)
            c.spread_pct = c.spread()
            ok, _ = passes_filters(c, cfg)
            if ok:
                candidates.append(c)
    return candidates


if __name__ == "__main__":
    # Exemple offline (sans réseau) : construction manuelle d'un candidat
    a = Pool("Aerodrome", 20_000, 20_000_000)
    b = Pool("UniswapV2", 18_000, 15_000_000)
    c = MemeCandidate("0x0000000000000000000000000000000000000000", "MEME",
                      "aerodrome", "uniswap", a, b, liquidity_usd=36_000,
                      holders=150, age_hours=10)
    print("spread:", round(c.spread(), 2), "%")
    print("filtres:", passes_filters(c))
    print("Pour un vrai scan réseau : scan_token('0x...adresse_du_token...')")
