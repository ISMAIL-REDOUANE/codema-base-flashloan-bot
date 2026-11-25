"""
scanner.py — Scanner meme coins SGHAR, LOW competition, sur Base.

Stratégie "low competition" :
  - On ne chasse PAS WETH/USDC (tous les bots du monde sont dessus).
  - On chasse les MEME/USDC avec liquidité 5k–100k $ : assez pour sortir,
    trop petit pour les gros bots d'arbitrage.
  - Filtres durs anti-rug / anti-honeypot AVANT tout calcul de profit.

Sources (v2, sans clé API) :
  1. DexScreener API publique : /token-pairs/v1/base/<tokenAddress>
     (paires d'UN token — l'ancien endpoint /latest/dex/pairs/base/<token>
     attendait une adresse de PAIRE, pas de token : corrigé audit #4)
  2. Vérification on-chain via les factories (getPair) — à brancher
     quand le RPC est configuré (voir executor.py).
  3. Honeypot check = simulation buy + sell sur un fork / eth_call :
     si le sell revert ou taxe > max, on jette le token.
  4. Holders : GoPlus holder_count (vérifié) ; « inconnu » n'est JAMAIS
     traité comme 0 — un candidat sans holders vérifiés est rejeté
     avec la raison explicite (audit #3). Âge : pairCreatedAt DexScreener.

Ce fichier ne trade RIEN. Il ne fait que produire des candidats.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from math_engine import Pool

# USDC natif Base — la sélection de la quote NE repose PLUS sur le
# symbole seul (audit #4) : on compare l'ADRESSE du quoteToken.
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


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
    # Audit #3 : « inconnu » != 0. holders_known=False => le candidat
    # est rejeté par passes_filters() avec une raison explicite, jamais
    # avec holders=0 silencieux. Même logique pour l'âge.
    holders_known: bool = False
    holders_source: str = ""       # ex. "goplus"
    age_hours: float = 0.0
    age_known: bool = False
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
# Audit #5 : "not_open_source" et "too_few_holders" manquaient de la
# liste de rejet (le flag était posé mais jamais bloquant) ; "tax_unknown"
# y entre aussi (taxe absente != taxe 0).
GOPLUS_REJECT_FLAGS = ("honeypot", "mintable", "liquidity_not_locked", "high_tax",
                       "owner_can_pause", "blacklist", "goplus_unknown",
                       "not_open_source", "too_few_holders", "tax_unknown")


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


def vet_token_goplus_detailed(token_address: str, max_tax_pct: float = 5.0,
                              timeout: int = 10) -> Tuple[str, List[str], Dict]:
    """Verdict GoPlus pour un token : ("PASS" | "REJECT" | "UNKNOWN", flags, info).
    - REJECT : honeypot, taxe > max, mint possible, proxy/owner dangereux,
      transfer pausable, blacklist, pas open-source, trop peu de holders.
    - UNKNOWN : API down / réponse vide / taxe absente -> ON NE TRADE PAS.
    - PASS : aucun red flag détecté (ne remplace pas un audit).
    Audit #5 — UNITÉS : GoPlus renvoie les taxes en DÉCIMAL 0–1
    (0.50 = 50 %). On normalise en % (×100) AVANT de comparer à
    max_tax_pct (5.0 = 5 %). Une taxe ABSENTE (champ vide/absent) vaut
    None -> flag "tax_unknown" -> UNKNOWN, jamais 0 % silencieux.
    info = {"holder_count": int|None, "buy_tax_pct": float|None,
            "sell_tax_pct": float|None}."""
    raw = fetch_goplus_security(token_address, timeout)
    if not raw or "_error" in raw:
        return "UNKNOWN", ["goplus_unknown"], {"holder_count": None,
                                               "buy_tax_pct": None,
                                               "sell_tax_pct": None}
    flags: List[str] = []

    def _is_true(v) -> bool:
        return str(v) == "1"

    def _tax_pct(v) -> Optional[float]:
        """Taxe GoPlus (décimal 0–1) -> % . None si absente/illisible."""
        if v is None or v == "":
            return None
        try:
            return float(v) * 100.0
        except (TypeError, ValueError):
            return None

    if _is_true(raw.get("is_honeypot")):
        flags.append("honeypot")
    buy_tax = _tax_pct(raw.get("buy_tax"))
    sell_tax = _tax_pct(raw.get("sell_tax"))
    if buy_tax is None or sell_tax is None:
        flags.append("tax_unknown")
    elif max(buy_tax, sell_tax) > max_tax_pct:
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
    holder_count: Optional[int] = None
    try:
        holder_count = int(raw.get("holder_count") or 0) or None
    except (TypeError, ValueError):
        holder_count = None
    if holder_count is not None and 0 < holder_count < 20:
        flags.append("too_few_holders")
    # Ordre des verdicts : un red flag dur (honeypot, taxe, ...) = REJECT ;
    # une taxe ABSENTE (donnée manquante, pas un 0) = UNKNOWN — dans les
    # deux cas on ne trade pas, mais la raison est explicite. tax_unknown
    # reste dans GOPLUS_REJECT_FLAGS pour que passes_filters() le rejette
    # aussi quand le flag arrive par un autre chemin.
    hard_reject = [f for f in flags
                   if f in GOPLUS_REJECT_FLAGS and f != "tax_unknown"]
    if hard_reject:
        verdict = "REJECT"
    elif "tax_unknown" in flags:
        verdict = "UNKNOWN"
    else:
        verdict = "PASS"
    return verdict, flags, {"holder_count": holder_count,
                            "buy_tax_pct": buy_tax, "sell_tax_pct": sell_tax}


def vet_token_goplus(token_address: str, max_tax_pct: float = 5.0,
                     timeout: int = 10) -> tuple[str, List[str]]:
    """Verdict GoPlus pour un token : ("PASS" | "REJECT" | "UNKNOWN", flags).
    Enveloppe de vet_token_goplus_detailed (compatibilité historique)."""
    verdict, flags, _info = vet_token_goplus_detailed(token_address, max_tax_pct,
                                                      timeout)
    return verdict, flags


def apply_goplus_to_candidate(c: "MemeCandidate", max_tax_pct: float = 5.0,
                              timeout: int = 10) -> tuple[str, List[str]]:
    """Vette un candidat avec GoPlus et ajoute les flags au candidat.
    Audit #3 : TRANSFÈRE le holder_count vérifié vers le candidat
    (c.holders, c.holders_known=True, c.holders_source="goplus").
    Si holder_count est absent, holders_known reste False (jamais 0
    silencieux) et le candidat sera rejeté explicitement par
    passes_filters(). Retourne (verdict, flags). Un verdict UNKNOWN
    ajoute 'goplus_unknown', qui est un drapeau de rejet dans
    passes_filters()."""
    verdict, flags, info = vet_token_goplus_detailed(c.token_address, max_tax_pct,
                                                     timeout)
    for f in flags:
        if f not in c.flags:
            c.flags.append(f)
    if info.get("holder_count") is not None:
        c.holders = info["holder_count"]
        c.holders_known = True
        c.holders_source = "goplus"
    return verdict, flags


def passes_filters(c: MemeCandidate, cfg: Optional[Dict] = None) -> tuple[bool, List[str]]:
    """Filtres durs. Retourne (passe, raisons_du_rejet).
    Audit #3 : un holders/âge INCONNU est rejeté avec une raison
    explicite (« inconnus »), jamais traité comme 0. Audit #5 :
    "not_open_source", "too_few_holders" et "tax_unknown" sont
    désormais des drapeaux de rejet (ils ne l'étaient pas)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    reasons: List[str] = []
    liq = c.liquidity_usd
    if liq < cfg["min_liquidity_usd"]:
        reasons.append(f"liquidité trop faible ({liq:.0f} $ < {cfg['min_liquidity_usd']:.0f} $)")
    if liq > cfg["max_liquidity_usd"]:
        reasons.append(f"liquidité trop haute ({liq:.0f} $ — trop de concurrence)")
    if not c.holders_known:
        reasons.append("holders inconnus (aucune source vérifiée — rejet explicite, pas 0)")
    elif c.holders < cfg["min_holders"]:
        reasons.append(f"trop peu de holders ({c.holders})")
    if not c.age_known:
        reasons.append("âge inconnu (pairCreatedAt indisponible — rejet explicite, pas 0)")
    elif c.age_hours > cfg["max_age_hours"]:
        reasons.append(f"coin trop vieux ({c.age_hours:.0f} h — spreads déjà arbitrés)")
    if abs(c.spread()) < cfg["min_spread_pct"]:
        reasons.append(f"spread trop petit ({c.spread():.2f} % < {cfg['min_spread_pct']} %)")
    for flag in c.flags:
        if flag in ("honeypot", "mintable", "liquidity_not_locked", "high_tax",
                    "owner_can_pause", "blacklist", "goplus_unknown",
                    "not_open_source", "too_few_holders", "tax_unknown"):
            reasons.append(f"drapeau rouge : {flag}")
    return (not reasons), reasons


def fetch_pairs_from_dexscreener(token_address: str, timeout: int = 10) -> List[Dict]:
    """Récupère les paires d'un token sur Base via DexScreener (API publique,
    pas de clé). Audit #4 : l'ancien endpoint /latest/dex/pairs/base/<token>
    attend une adresse de PAIRE — on utilise /token-pairs/v1/base/<tokenAddress>
    (docs DexScreener). Réponse : {"schemaVersion": ..., "pairs": [...]}
    (même schéma de paire que l'ancien endpoint). Retourne [] en cas
    d'erreur réseau — le scanner ne crash pas."""
    url = f"https://api.dexscreener.com/token-pairs/v1/base/{token_address}"
    req = urllib.request.Request(url, headers={"User-Agent": "codema-flashloan-bot-v1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:  # réseau coupé, rate-limit, token inconnu
        print(f"[scanner] DexScreener indisponible pour {token_address}: {e}")
        return []
    # RE-MESUREMENT 2026-11-25 : l'endpoint /token-pairs/v1 renvoie en
    # LIVE un TABLEAU JSON nu ([{paire}, ...]), PAS {"pairs": [...]}
    # (la docstring du fix #4 supposait le schéma de l'ancien endpoint —
    # le test mocké passait, le live crashait avec AttributeError).
    # On accepte les deux formes.
    if isinstance(data, list):
        return data
    return data.get("pairs") or []


def pairs_age_hours(pairs: List[Dict]) -> Optional[float]:
    """Âge (heures) de la paire la plus RÉCENTE — un meme coin se juge
    sur sa paire la plus jeune. pairCreatedAt est en millisecondes
    epoch. None si aucune paire ne donne de date (âge INCONNU, jamais 0)."""
    stamps = [p.get("pairCreatedAt") for p in pairs if p.get("pairCreatedAt")]
    if not stamps:
        return None
    newest = max(stamps)  # la plus récente = la plus jeune
    return (time.time() * 1000 - newest) / 3_600_000.0


def _is_usdc_quote(p: Dict) -> bool:
    """La paire est-elle cotée en USDC ? Audit #4 : on compare l'ADRESSE
    du quoteToken à USDC_BASE. Repli symbole uniquement si l'adresse est
    absente de la réponse (DexScreener la fournit normalement)."""
    quote = p.get("quoteToken") or {}
    addr = (quote.get("address") or "").lower()
    if addr:
        return addr == USDC_BASE.lower()
    return (quote.get("symbol") or "").upper() == "USDC"


def pairs_to_pools(pairs: List[Dict]) -> List[Pool]:
    """Convertit les paires DexScreener en Pool (réserves USDC/MEME).
    On ne garde que les paires MEME/USDC (quote USDC vérifiée par adresse)."""
    pools: List[Pool] = []
    for p in pairs:
        if not _is_usdc_quote(p):
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
    candidats (REJECT/UNKNOWN -> aucun candidat, on ne trade pas l'aveugle)
    ET transfère le holder_count vérifié aux candidats (audit #3 — un
    seul appel GoPlus par token, pas un par paire).
    goplus_check=False (scan offline / tests sans réseau) : les holders
    restent INCONNUS et passes_filters() rejette les candidats avec la
    raison explicite « holders inconnus » — le scanner ne renvoie plus
    0 candidat silencieusement : il dit POURQUOI.
    Âge : pairCreatedAt DexScreener (paire la plus récente) ; inconnu ->
    rejet explicite (audit #3). Par défaut False (scan offline / tests sans réseau)."""
    goplus_info: Optional[Dict] = None
    goplus_flags: List[str] = []
    if goplus_check:
        verdict, flags, goplus_info = vet_token_goplus_detailed(token_address)
        goplus_flags = flags
        if verdict != "PASS":
            print(f"[scanner] GoPlus {verdict} pour {token_address} : {flags} — token jeté")
            return []
    pairs = fetch_pairs_from_dexscreener(token_address)
    pools = pairs_to_pools(pairs)
    age_h = pairs_age_hours(pairs)
    candidates: List[MemeCandidate] = []
    rejected: List[str] = []
    for i, pa in enumerate(pools):
        for pb in pools[i + 1:]:
            # A = moins cher (on achète là), B = plus cher (on vend là)
            buy, sell = (pa, pb) if pa.price_usdc_per_meme <= pb.price_usdc_per_meme else (pb, pa)
            liq = min(buy.liquidity_usd, sell.liquidity_usd)
            c = MemeCandidate(token_address=token_address, symbol=symbol,
                              dex_a=buy.name, dex_b=sell.name,
                              pool_a=buy, pool_b=sell, liquidity_usd=liq)
            c.spread_pct = c.spread()
            if age_h is not None:
                c.age_hours = age_h
                c.age_known = True
            if goplus_info is not None and goplus_info.get("holder_count") is not None:
                c.holders = goplus_info["holder_count"]
                c.holders_known = True
                c.holders_source = "goplus"
            for f in goplus_flags:
                if f not in c.flags:
                    c.flags.append(f)
            ok, why = passes_filters(c, cfg)
            if ok:
                candidates.append(c)
            else:
                rejected.append("; ".join(why))
    if not candidates and rejected:
        # On ne renvoie pas 0 silencieusement : la raison est affichée.
        print(f"[scanner] {token_address} : 0 candidat — raison la plus fréquente : "
              f"{max(set(rejected), key=rejected.count)}")
    return candidates


if __name__ == "__main__":
    # Exemple offline (sans réseau) : construction manuelle d'un candidat
    a = Pool("Aerodrome", 20_000, 20_000_000)
    b = Pool("UniswapV2", 18_000, 15_000_000)
    c = MemeCandidate("0x0000000000000000000000000000000000000000", "MEME",
                      "aerodrome", "uniswap", a, b, liquidity_usd=36_000,
                      holders=150, holders_known=True, holders_source="demo",
                      age_hours=10, age_known=True)
    print("spread:", round(c.spread(), 2), "%")
    print("filtres:", passes_filters(c))
    print("Pour un vrai scan réseau : scan_token('0x...adresse_du_token...')")
