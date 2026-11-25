"""
math_engine.py — Moteur mathématique du bot Flash Loan (Base, meme coins sghar).

IDÉE CENTRALE (à retenir) :
  On ne choisit PAS une taille fixe (ex: 10 000 $).
  Le calcul choisit la taille qui maximise le profit NET, pool par pool.
  Pourquoi ? Parce qu'un AMM constant-product (x * y = k) fait bouger le
  prix contre toi quand tu achètes gros : plus tu mets, plus le prix
  d'achat monte et le prix de vente descend. Au-delà d'une taille
  optimale, chaque dollar de plus DÉTRUIT du profit.

Formules (pool V2, x*y=k, fee f sur l'input) :
  out = reserve_out * (amount_in * (1-f)) / (reserve_in + amount_in * (1-f))

  Round-trip USDC -> MEME (pool A, pas cher) -> USDC (pool B, cher) :
    meme  = amm_out(L, x_A, y_A, f_A)
    usdc2 = amm_out(meme, y_B, x_B, f_B)     # sur B, reserve_in = MEME
    brut  = usdc2 - L
    frais_flash = L * 0.0005                  # Aave V3, 0.05 %
    net   = brut - frais_flash - gas_usd
    (les frais DEX sont DÉJÀ dans amm_out, on les reporte sans les
     soustraire une 2e fois — voir dex_fees_usd dans le détail.)

Règle d'exécution (0 gas sur les perdants) :
  EXÉCUTER seulement si  net > min_profit_usd
                     ET  net > gas_usd * gas_multiple
  Sinon SKIP — on ne broadcast RIEN, donc 0 gas payé.
  Le revert on-chain n'est qu'un filet de sécurité, pas la stratégie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Gas UNIFIÉ (v2) : une seule source de vérité, voir gas.py.
# v1 avait gas_usd = 1,20 $ en dur alors que config.yaml disait ~0,07 $.
try:
    from gas import (DEFAULT_GAS_UNITS as _GAS_UNITS,
                     DEFAULT_GAS_PRICE_GWEI as _GAS_GWEI,
                     DEFAULT_ETH_PRICE_USD as _ETH_USD,
                     GAS_PRICE_MAX_GWEI,
                     gas_cost_usd_from_gwei)
except ImportError:  # si gas.py absent (copie isolée du fichier)
    _GAS_UNITS, _GAS_GWEI, _ETH_USD, GAS_PRICE_MAX_GWEI = 450_000, 0.05, 3000.0, 2.0

    def gas_cost_usd_from_gwei(u: int, g: float, e: float) -> float:
        return u * g * 1e-9 * e


# ---------------------------------------------------------------- constants
AAVE_FLASH_FEE = 0.0005          # 0.05 % — lire FLASHLOAN_PREMIUM_TOTAL au runtime en prod
BALANCER_FLASH_FEE = 0.0         # v3 : 0 % — lu on-chain 2026-11-24
#   (Vault.getProtocolFeesCollector().getFlashLoanFeePercentage() = 0,
#   bloc 61 794 215, voir balancer_flash.py / BALANCER_RESEARCH.md).
#   C'est un paramètre de gouvernance : le bot doit le RELIRE, pas le
#   supposer éternellement. Par défaut le provider reste Aave (0,05 %) :
#   on ne passe à 0 % que quand on choisit explicitement Balancer
#   (Costs(flash_provider="balancer") ou balancer_flash.costs_for_provider).
#   ⛔ v3.3 — BALANCER MORT (BIP-928, wind-down 30 oct 2026) : ne plus
#   l'utiliser comme provider. La clé "balancer" est CONSERVÉE ici
#   uniquement pour que les tests historiques passent ; l'executor
#   ne le sélectionne plus (voir morpho_flash.py).
MORPHO_FLASH_FEE = 0.0           # v3.3 : 0 % — PAR CONCEPTION, pas de
#   getter flashFee sur Morpho Blue (vérifié : eth_call revert, bloc
#   61 806 974). Aucune gouvernance ne peut le monter.
FLASH_FEE_BY_PROVIDER = {"aave": AAVE_FLASH_FEE, "balancer": BALANCER_FLASH_FEE,
                         "morpho": MORPHO_FLASH_FEE}
DEFAULT_GAS_UNITS = _GAS_UNITS   # 450 000 — voir gas.py
DEFAULT_GAS_PRICE_GWEI = _GAS_GWEI  # 0.05 — hypothèse config.yaml
DEFAULT_ETH_PRICE_USD = _ETH_USD
DEFAULT_MIN_PROFIT_USD = 3.0     # confirmé par Ismail 2026-11-24 : min 3 $
# Audit #11 — POLITIQUES DE SEUIL (centralisées ici, pas dispersées) :
#   - Base    : min_profit = 3 $ (DEFAULT_MIN_PROFIT_USD, confirmé Ismail)
#               + net > gas × 3 (Costs.gas_multiple).
#   - Polygon : min_profit = 0 $, gas_multiple = 0 (polygon_guard.py :
#               net > 0 $ après gas + budget revert ; le min 3 $ y est
#               ABANDONNÉ par décision d'Ismail 2026-11-24).
# Ce sont deux politiques DISTINCTES et voulues — pas une règle unique.
# Les scanners récents (leadlag/) évaluent net > 0 : c'est la politique
# Polygon, pas celle de Base.
POLICIES = {"base": {"min_profit_usd": 3.0, "gas_multiple": 3.0},
            "polygon": {"min_profit_usd": 0.0, "gas_multiple": 0.0}}


@dataclass
class Pool:
    """Un pool constant-product V2 (Uniswap V2 / Aerodrome volatile / Sushi V2)."""
    name: str
    reserve_usdc: float   # x : réserve en USDC ($, USDC ~ 1 $)
    reserve_meme: float   # y : réserve en tokens MEME
    fee_bps: int = 30     # 30 bps = 0.30 % par swap

    @property
    def price_usdc_per_meme(self) -> float:
        return self.reserve_usdc / self.reserve_meme if self.reserve_meme else 0.0

    @property
    def liquidity_usd(self) -> float:
        # ~2x la réserve USDC (l'autre moitié vaut à peu près pareil en $)
        return 2.0 * self.reserve_usdc


@dataclass
class Costs:
    """Coûts d'un trade. v2 : gas_usd n'est PLUS un défaut inventé (1,20 $ en v1)
    — si on ne le donne pas, il est calculé par le modèle unifié gas.py
    (450 000 × 0,05 gwei × 3 000 $ = 0,0675 $), le même que config.yaml.
    gas_price_gwei sert au PLAFOND : au-dessus de max_gas_price_gwei (2 gwei),
    decide() dit SKIP, on ne broadcast rien.
    v3 : flash_provider = "aave" (défaut, 0,05 %) ou "balancer" (0 %).
    Quand provider = "balancer", flash_fee_rate est forcé à 0,0 — le
    provider gagne sur le taux passé à la main (évite un 0,05 % résiduel).
    v3.3 : flash_provider = "morpho" (0 %, provider préféré — Balancer
    mort, BIP-928). "balancer" conservé pour compat historique seulement."""
    gas_usd: Optional[float] = None
    flash_fee_rate: float = AAVE_FLASH_FEE
    flash_provider: str = "aave"
    min_profit_usd: float = DEFAULT_MIN_PROFIT_USD  # 3 $ — confirmé Ismail
    gas_multiple: float = 3.0    # net doit être > gas * 3
    gas_price_gwei: Optional[float] = None
    max_gas_price_gwei: float = GAS_PRICE_MAX_GWEI  # 2 gwei — au-dessus : stop

    def __post_init__(self):
        if self.flash_provider not in FLASH_FEE_BY_PROVIDER:
            raise ValueError(f"flash_provider inconnu : {self.flash_provider!r} "
                             f"(aave | balancer | morpho)")
        if self.flash_provider in ("balancer", "morpho"):
            self.flash_fee_rate = 0.0
        if self.gas_price_gwei is None:
            self.gas_price_gwei = DEFAULT_GAS_PRICE_GWEI
        if self.gas_usd is None:
            self.gas_usd = gas_cost_usd_from_gwei(
                DEFAULT_GAS_UNITS, self.gas_price_gwei, DEFAULT_ETH_PRICE_USD)


def costs_from_gas_reading(reading, min_profit_usd: float = DEFAULT_MIN_PROFIT_USD,
                           gas_multiple: float = 3.0,
                           max_gas_price_gwei: float = GAS_PRICE_MAX_GWEI,
                           flash_provider: str = "aave") -> Costs:
    """Construit Costs depuis une mesure live (gas.py GasReading) :
    le gas payé dans decide() est alors le gas MESURÉ, pas une hypothèse.
    flash_provider="balancer" met le taux flash à 0 % (v3)."""
    return Costs(gas_usd=reading.gas_cost_usd,
                 flash_provider=flash_provider,
                 min_profit_usd=min_profit_usd, gas_multiple=gas_multiple,
                 gas_price_gwei=reading.gas_price_gwei,
                 max_gas_price_gwei=max_gas_price_gwei)


def gas_cost_usd(gas_units: int = DEFAULT_GAS_UNITS,
                 gas_price_gwei: float = DEFAULT_GAS_PRICE_GWEI,
                 eth_price_usd: float = DEFAULT_ETH_PRICE_USD) -> float:
    """Gas en $ : units * gwei * 1e-9 * prix ETH.
    v2 : AUCUN plancher (v1 forçait 0,10 $ — incohérent avec config.yaml).
    Valeur par défaut unifiée : 450 000 × 0,05 × 3 000 = 0,0675 $."""
    return gas_cost_usd_from_gwei(gas_units, gas_price_gwei, eth_price_usd)


# ---------------------------------------------------------------- AMM
def amm_out(amount_in: float, reserve_in: float, reserve_out: float,
            fee_bps: int = 30) -> float:
    """Sortie d'un swap constant-product, frais DEX déjà déduits.
    Retourne 0 si input/réserve invalide."""
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0.0
    amount_in_after_fee = amount_in * (1.0 - fee_bps / 10_000.0)
    return reserve_out * amount_in_after_fee / (reserve_in + amount_in_after_fee)


def round_trip(loan_usd: float, pool_buy: Pool, pool_sell: Pool,
               flash_fee_rate: float = AAVE_FLASH_FEE) -> Dict[str, float]:
    """Un aller-retour complet. Détail chiffré, sans double comptage."""
    meme_bought = amm_out(loan_usd, pool_buy.reserve_usdc,
                          pool_buy.reserve_meme, pool_buy.fee_bps)
    usdc_back = amm_out(meme_bought, pool_sell.reserve_meme,
                        pool_sell.reserve_usdc, pool_sell.fee_bps)
    gross = usdc_back - loan_usd
    flash_fee = loan_usd * flash_fee_rate
    # Frais DEX payés (information, déjà dans amm_out — NE PAS re-soustraire) :
    dex_fee_buy = loan_usd * pool_buy.fee_bps / 10_000.0
    # valeur en $ du MEME vendu, approximée au prix du pool B :
    dex_fee_sell = meme_bought * pool_sell.price_usdc_per_meme \
        * pool_sell.fee_bps / 10_000.0
    return {
        "loan_usd": loan_usd,
        "meme_bought": meme_bought,
        "usdc_back": usdc_back,
        "gross_usd": gross,
        "flash_fee_usd": flash_fee,
        "dex_fees_usd": dex_fee_buy + dex_fee_sell,
        "price_impact_buy_pct": 100.0 * loan_usd / (pool_buy.reserve_usdc + loan_usd)
        if pool_buy.reserve_usdc else 0.0,
    }


def net_profit(loan_usd: float, pool_buy: Pool, pool_sell: Pool,
               costs: Optional[Costs] = None) -> Dict[str, float]:
    """Profit NET = brut - frais flash - gas. C'est LE chiffre qui décide."""
    costs = costs or Costs()
    r = round_trip(loan_usd, pool_buy, pool_sell, costs.flash_fee_rate)
    net = r["gross_usd"] - r["flash_fee_usd"] - costs.gas_usd
    return {**r, "gas_usd": costs.gas_usd, "net_usd": net,
            "net_pct": 100.0 * net / loan_usd if loan_usd else 0.0}


# ---------------------------------------------------------------- optimal size
def find_optimal_loan(pool_buy: Pool, pool_sell: Pool,
                      costs: Optional[Costs] = None,
                      max_loan_usd: float = 50_000.0,
                      max_pct_liquidity: float = 0.10) -> Dict[str, float]:
    """Taille optimale : recherche en 2 passes (grille log + raffinement).
    Cap dur : jamais plus de max_pct_liquidity de la plus petite réserve
    USDC (sinon le price impact tue le trade), jamais plus que max_loan_usd.
    Retourne la meilleure taille trouvée + son net. Si le meilleur net
    est négatif, la taille optimale est quand même retournée avec
    net < 0 — c'est à decide() de dire SKIP."""
    costs = costs or Costs()
    cap_liq = max_pct_liquidity * min(pool_buy.reserve_usdc, pool_sell.reserve_usdc)
    hi = min(max_loan_usd, cap_liq)
    if hi <= 1:
        return {"optimal_loan_usd": 0.0, "net_usd": -costs.gas_usd,
                "gross_usd": 0.0, "cap_usd": hi, "note": "liquidité trop faible"}

    # Passe 1 : grille géométrique 1 $ -> hi (60 points). Audit #11 :
    # la grille commençait à 10 $ et éliminait les tailles < 10 $ — les
    # petites tailles ($1–$10) sont désormais explorées (le gas, lui,
    # reste compté : une petite taille ne passe que si son net > 0).
    best_loan, best_net, best_detail = 0.0, float("-inf"), {}
    candidates: List[float] = []
    lo = 1.0
    ratio = (hi / lo) ** (1 / 59)
    v = lo
    for _ in range(60):
        candidates.append(min(v, hi))  # jamais au-dessus du plafond (erreur float)
        v *= ratio
    # Passe 2 : raffinement autour du meilleur (+/- 30 %, 40 points)
    for loan in candidates:
        d = net_profit(loan, pool_buy, pool_sell, costs)
        if d["net_usd"] > best_net:
            best_net, best_loan, best_detail = d["net_usd"], loan, d
    if best_loan > 0:
        for f in [0.7 + 0.015 * i for i in range(41)]:  # 0.70 .. 1.30
            loan = best_loan * f
            if loan > hi:
                continue
            d = net_profit(loan, pool_buy, pool_sell, costs)
            if d["net_usd"] > best_net:
                best_net, best_loan, best_detail = d["net_usd"], loan, d
    # Audit #9 — AUCUN arrondi ici : decide() utilise ces valeurs pour
    # trancher ; un net de +0,003 $ arrondi à 0,00 $ serait rejeté à tort
    # (min_profit=0 sur Polygon). L'arrondi n'a lieu qu'à l'affichage
    # (evaluate_sizes, prints). Les valeurs sont en pleine précision float.
    # Le loan est plafonné à hi (la grille peut dépasser hi d'un epsilon
    # float : 50 000,00000000015 $ ne doit jamais sortir d'ici).
    best_loan = min(best_loan, hi)
    return {"optimal_loan_usd": best_loan, "net_usd": best_net,
            "gross_usd": best_detail.get("gross_usd", 0.0),
            "usdc_back": best_detail.get("usdc_back", 0.0),
            "cap_usd": hi,
            "flash_fee_usd": best_detail.get("flash_fee_usd", 0.0),
            "dex_fees_usd": best_detail.get("dex_fees_usd", 0.0),
            "gas_usd": costs.gas_usd}


def evaluate_sizes(sizes_usd: List[float], pool_buy: Pool, pool_sell: Pool,
                   costs: Optional[Costs] = None) -> List[Dict[str, float]]:
    """Même opportunité, plusieurs tailles — la preuve que 10 000 $ peut
    perdre quand 500 $ gagne (price impact)."""
    costs = costs or Costs()
    out = []
    for s in sizes_usd:
        d = net_profit(s, pool_buy, pool_sell, costs)
        out.append({"loan_usd": s, "usdc_back": round(d["usdc_back"], 2),
                    "gross_usd": round(d["gross_usd"], 2),
                    "flash_fee_usd": round(d["flash_fee_usd"], 2),
                    "gas_usd": d["gas_usd"],
                    "net_usd": round(d["net_usd"], 2),
                    "net_pct": round(d["net_pct"], 2),
                    "verdict": "WIN" if d["net_usd"] > 0 else "LOSS"})
    return out


# ---------------------------------------------------------------- Kelly sizing
def kelly_fraction(p_win: float, avg_win: float, avg_loss: float,
                   cap: float = 0.25) -> float:
    """Kelly fractionnaire : f* = (p*(b+1) - 1) / b, b = avg_win/avg_loss.
    On plafonne à `cap` (Kelly quart = 0.25) : Kelly plein est trop
    agressif, surtout sur des meme coins. Retourne 0 si pas d'edge.
    ATTENTION (recherche §4.2) : ne JAMAIS appeler ça avec un p inventé
    (ex. 60 %) — utiliser kelly_fraction_honest() avec le nombre de
    trades réels/simules, sinon on sur-mise sur un edge imaginaire."""
    if avg_loss <= 0 or avg_win <= 0 or not (0 < p_win < 1):
        return 0.0
    b = avg_win / avg_loss
    f_star = (p_win * (b + 1) - 1) / b
    return max(0.0, min(f_star, cap))


def wilson_lower_bound(p_win: float, n_trades: int, z: float = 1.96) -> float:
    """Borne inférieure de Wilson (IC 95 %) pour un win rate observé.
    Avec peu de trades, elle rabat fortement p vers le bas : c'est le
    but — ne pas gonfler le win rate avec un petit échantillon chanceux.
    Ex : 8 gains / 10 trades (p=0,80) -> borne inf ~0,49, pas 0,80."""
    if n_trades <= 0 or not (0 <= p_win <= 1):
        return 0.0
    n = float(n_trades)
    denom = 1.0 + z * z / n
    centre = p_win + z * z / (2 * n)
    spread = z * math.sqrt(p_win * (1 - p_win) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / denom)


def kelly_fraction_honest(p_win: float, avg_win: float, avg_loss: float,
                          n_trades: int = 0) -> float:
    """Kelly HONNÊTE (recherche §4.2) :
    - < 30 trades : cap 0,10× (stratégie neuve — c'est notre cas en v2).
    - 30–49 trades : cap 0,25× (Kelly quart) avec p = borne inf. de Wilson.
    - >= 50 trades : cap 0,25× avec p = borne inf. de Wilson.
    - n_trades = 0 (aucune mesure) : retourne 0 — on ne mise PAS sur un
      edge qu'on n'a pas mesuré. Le sizing du loan reste décidé par
      find_optimal_loan(), pas par Kelly."""
    if n_trades <= 0:
        return 0.0
    cap = 0.10 if n_trades < 30 else 0.25
    p_safe = wilson_lower_bound(p_win, n_trades)
    return kelly_fraction(p_safe, avg_win, avg_loss, cap=cap)


def kelly_size(bankroll_usd: float, p_win: float, avg_win: float,
               avg_loss: float, cap: float = 0.25) -> Dict[str, float]:
    """Taille de capital PROPRE (pas le flash loan) selon Kelly quart.
    Pour un flash loan, le capital à risque n'est pas le montant emprunté
    (remboursé atomiquement) mais le gas + le risque de revert — Kelly
    sert ici à dimensionner le capital propre qu'on accepte de risquer
    par opportunité / par jour, et à plafonner le loan."""
    f = kelly_fraction(p_win, avg_win, avg_loss, cap)
    return {"kelly_fraction": round(f, 4),
            "kelly_full": round(kelly_fraction(p_win, avg_win, avg_loss, cap=1.0), 4),
            "size_usd": round(bankroll_usd * f, 2),
            "bankroll_usd": bankroll_usd}


# ---------------------------------------------------------------- decision
def decide(pool_buy: Pool, pool_sell: Pool, costs: Optional[Costs] = None,
           max_loan_usd: float = 50_000.0,
           max_pct_liquidity: float = 0.10) -> Dict:
    """Décision finale, AVANT tout broadcast.
    EXECUTE seulement si net > min_profit ET net > gas * gas_multiple.
    Sinon SKIP — 0 gas payé, 0 tx envoyée."""
    costs = costs or Costs()
    opt = find_optimal_loan(pool_buy, pool_sell, costs, max_loan_usd, max_pct_liquidity)
    net = opt["net_usd"]
    spread_pct = 100.0 * (pool_sell.price_usdc_per_meme
                          / pool_buy.price_usdc_per_meme - 1) \
        if pool_buy.price_usdc_per_meme else 0.0
    reasons: List[str] = []
    # v2 : PLAFOND DE GAS — si le gas a explosé, on n'envoie rien, même si
    # le net calculé avec un gas normal passerait (le net réel serait négatif).
    if costs.gas_price_gwei is not None \
            and costs.gas_price_gwei > costs.max_gas_price_gwei:
        reasons.append(f"gas trop cher : {costs.gas_price_gwei:.2f} gwei "
                       f"> plafond {costs.max_gas_price_gwei} gwei — aucun broadcast")
    if net <= 0:
        reasons.append(f"net négatif ({net:.2f} $) : le trade perdrait de l'argent")
    if net <= costs.min_profit_usd:
        reasons.append(f"net {net:.2f} $ <= profit minimum {costs.min_profit_usd:.2f} $")
    if net <= costs.gas_usd * costs.gas_multiple:
        reasons.append(f"net {net:.2f} $ <= gas x {costs.gas_multiple} "
                       f"({costs.gas_usd * costs.gas_multiple:.2f} $)")
    action = "EXECUTE" if not reasons else "SKIP"
    return {"action": action, "spread_pct": round(spread_pct, 2),
            "flash_provider": costs.flash_provider,
            "flash_fee_rate": costs.flash_fee_rate,
            "optimal_loan_usd": opt["optimal_loan_usd"],
            "expected_net_usd": net,
            "expected_gross_usd": opt["gross_usd"],
            "gas_usd": costs.gas_usd,
            "gas_paid_if_skipped_usd": 0.0,
            "reasons": reasons,
            "detail": opt}


if __name__ == "__main__":
    # Démo rapide : spread 20 %, petites pools (20k $ / 18k $)
    # Coûts v2 : gas unifié (0,0675 $), min profit 3 $ (Ismail).
    a = Pool("Aerodrome MEME/USDC", 20_000, 20_000_000)
    b = Pool("UniswapV2 MEME/USDC", 18_000, 15_000_000)
    c = Costs()  # gas unifié + min 3 $ par défaut
    print("Gas unifié :", round(c.gas_usd, 4), "$ | min profit :", c.min_profit_usd, "$")
    print("Spread :", round(100 * (b.price_usdc_per_meme / a.price_usdc_per_meme - 1), 1), "%")
    for row in evaluate_sizes([100, 500, 2000, 10000], a, b, c):
        print(row)
    print(decide(a, b, c))
