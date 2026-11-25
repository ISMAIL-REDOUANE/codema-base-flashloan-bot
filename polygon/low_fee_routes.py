"""
low_fee_routes.py — Routes a tres petits frais sur Polygon (v4.5, analyse seule).

Question d'Ismail (2026-11-25) : « 9leb kifach nwliw t7na 3ndna profit
wkha howa ri f 0.05 o 0.02 » — comment profiter meme avec des spreads
de 0,02 % - 0,05 % ?

Ce module NE BROADCAST RIEN. Il ne fait que :
  1. coter la route 4-jambes USDC -> USDC.e -> USDT -> USDC (Curve) en
     lecture seule (eth_call au meme bloc) ;
  2. calculer la table de breakeven pour chaque paire de venues avec la
     math de polygon_guard.py (reutilisee, pas dupliquee) ;
  3. evaluer l'alternative market-making (LP) : APR de frais vs IL + gas.

FAITS MESURES (voir LOW_FEE_PROFIT_POLYGON.md pour les sources) :
  - Uniswap V3 0,01 % : tier reel, pools USDC.e/USDT TVL 832 k$.
  - Algebra (QuickSwap V3) : frais dynamique, plancher 0,001 % sur les
    stables en marche calme (lu on-chain via globalState : fee_raw=10).
  - Curve am3pool : frais 0,001 % (fee() = 100000 en precision 1e10),
    mais il trade des amTokens en USDC NATIF (pas USDC.e) et a un volume
    ~0 -> son prix est STALE (1,0001) alors que l'USDT vaut ~0,9988 $.
  - Aucun pool V4 a 0 frais avec de la liquidite reelle sur Polygon
    (Bunni TVL 5 $, FeeFree ~14 k$ total, Angstrom Ethereum only,
    0 evenement Initialize en 10 000 blocs).
  - V4 Quoter 0x31AB... inutilisable (pas de quoteExactInputSingle).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from math_engine import Pool, evaluate_sizes  # noqa: E402
from polygon_guard import polygon_costs, polygon_decide  # noqa: E402

# ---------------------------------------------------------------- adresses
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"   # USDC natif
USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"          # USDC.e (bridged)
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
CURVE_AM3POOL = "0x445FE580eF8d70FF569aB36e80c647af338db351"
MORPHO_POLYGON = "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"

# Frais mesures (bps ; 1 bp = 0,01 %). Sources dans le rapport.
FEE_V3_001 = 1        # Uniswap V3 tier 0,01 % (et V4 1 bp, meme chose)
FEE_V3_005 = 5        # Uniswap V3 tier 0,05 %
FEE_V3_030 = 30       # Uniswap V3 tier 0,30 %
FEE_V2 = 30           # QuickSwap/Sushi V2 : 0,30 %
FEE_ALGEBRA_STABLE = 0   # Algebra stables : 0,001 % = 0,1 bp -> NON
                         # representable en bps entiers (Pool.fee_bps: int).
                         # On met 0 ici et on corrige de +0,1 bp par jambe
                         # dans breakeven_table() (voir UNMODELED_FEE_BPS).
FEE_CURVE_AM3 = 0        # idem : 0,001 % = 0,1 bp, corrige de la meme facon.

# Correction a ajouter au breakeven (bps) pour les jambes a 0,001 %.
UNMODELED_FEE_BPS = 0.1

# Gas mesure sur Polygon (pro-scan / realtime, nov 2026) et prix MATIC.
GAS_PRICE_GWEI = 282.0
MATIC_PRICE_USD = 0.0758
# Route 4-jambes : 3 swaps + flash loan + repay -> ~650 000 unites estimees
# (a mesurer sur fork ; le trade 2-jambes standard est a 450 000).
GAS_UNITS_4LEG = 650_000


def gas_budget_4leg_usd(gas_price_gwei: float = GAS_PRICE_GWEI,
                        matic_price_usd: float = MATIC_PRICE_USD) -> float:
    """Budget total (trade + revert) pour la route 4-jambes, en $."""
    costs = polygon_costs(gas_price_gwei, matic_price_usd,
                          gas_units=GAS_UNITS_4LEG)
    return costs.gas_usd


# ---------------------------------------------------------------- route Curve
def route_4leg_from_quotes(amount_usd: float, leg0_usd: float,
                           leg1_usd: float, leg2_usd: float,
                           gas_budget_usd: float) -> Dict:
    """Resultat de la route 4-jambes a partir de quotes deja mesurees
    (meme bloc) : USDC -> USDC.e (V3 0,01 %) -> USDT (V3 0,01 %)
    -> USDC (Curve am3pool). Fonction pure, sans RPC (utilisee par les
    tests avec les chiffres enregistres)."""
    gross = leg2_usd - amount_usd
    net = gross - gas_budget_usd
    return {
        "loan_usd": amount_usd,
        "leg0_usdc_to_usdce": round(leg0_usd, 2),
        "leg1_usdce_to_usdt": round(leg1_usd, 2),
        "leg2_usdt_to_usdc_curve": round(leg2_usd, 2),
        "gross_usd": round(gross, 4),
        "gas_budget_usd": round(gas_budget_usd, 4),
        "net_usd": round(net, 4),
        "verdict": "WIN" if net > 0 else "LOSS",
    }


def quote_route_4leg_usdc(amount_usd: float, w3, block: Optional[int] = None,
                          gas_price_gwei: float = GAS_PRICE_GWEI) -> Dict:
    """Cote la route 4-jambes en lecture seule (eth_call), TOUTES les
    jambes au MEME bloc. Necessite web3. Ne broadcast rien.
    Retourne le meme dict que route_4leg_from_quotes()."""
    from web3 import Web3

    blk = block if block is not None else w3.eth.block_number
    qabi = [{"name": "quoteExactInputSingle",
             "outputs": [{"type": "uint256"}, {"type": "uint160"},
                         {"type": "uint32"}, {"type": "uint256"}],
             "inputs": [{"type": "tuple", "components": [
                 {"type": "address", "name": "tokenIn"},
                 {"type": "address", "name": "tokenOut"},
                 {"type": "uint256", "name": "amountIn"},
                 {"type": "uint24", "name": "fee"},
                 {"type": "uint160", "name": "sqrtPriceLimitX96"}]}],
             "stateMutability": "nonpayable", "type": "function"}]
    cabi = [{"name": "get_dy_underlying", "outputs": [{"type": "uint256"}],
             "inputs": [{"type": "int128", "name": "i"},
                        {"type": "int128", "name": "j"},
                        {"type": "uint256", "name": "dx"}],
             "stateMutability": "view", "type": "function"}]
    q = w3.eth.contract(address=Web3.to_checksum_address(QUOTER_V2), abi=qabi)
    c = w3.eth.contract(address=Web3.to_checksum_address(CURVE_AM3POOL),
                        abi=cabi)

    def qv3(a_in, a_out, amt, fee):
        return q.functions.quoteExactInputSingle(
            (Web3.to_checksum_address(a_in), Web3.to_checksum_address(a_out),
             amt, fee, 0)).call(block_identifier=blk)[0]

    amt = int(amount_usd * 1e6)
    l0 = qv3(USDC_NATIVE, USDCE, amt, 100)
    l1 = qv3(USDCE, USDT, l0, 100)
    l2 = c.functions.get_dy_underlying(2, 1, l1).call(block_identifier=blk)
    budget = gas_budget_4leg_usd(gas_price_gwei)
    out = route_4leg_from_quotes(amount_usd, l0 / 1e6, l1 / 1e6, l2 / 1e6,
                                 budget)
    out["block"] = blk
    return out


# ---------------------------------------------------------------- breakeven
# Paires de venues (jambe A + jambe B), frais en bps entiers. Les jambes a
# 0,001 % (Algebra stables, Curve) sont a fee_bps=0 avec la correction
# UNMODELED_FEE_BPS appliquee dans la table (voir ci-dessous).
VENUE_PAIRS = [
    ("V3 0,01 % + V3 0,01 %", FEE_V3_001, FEE_V3_001, 0.0),
    ("V3 0,01 % + Algebra 0,001 %", FEE_V3_001, FEE_ALGEBRA_STABLE,
     UNMODELED_FEE_BPS),
    ("V3 0,01 % + Curve 0,001 %", FEE_V3_001, FEE_CURVE_AM3,
     UNMODELED_FEE_BPS),
    ("V3 0,01 % + V3 0,05 %", FEE_V3_001, FEE_V3_005, 0.0),
    ("V3 0,05 % + V3 0,05 %", FEE_V3_005, FEE_V3_005, 0.0),
    ("V3 0,05 % + Algebra volatile ~0,087 %", FEE_V3_005, 9, 0.0),
    ("V3 0,05 % + V2 0,30 %", FEE_V3_005, FEE_V2, 0.0),
    ("V3 0,30 % + V2 0,30 %", FEE_V3_030, FEE_V2, 0.0),
]

# Profondeur des pools synthetiques : 5 Md$ par cote, soit un impact prix
# ~0 aux tailles etudiees (<= 20 k$). C'est le bon modele ICI, et non
# la TVL reelle (832 k$) : les pools V3 sont a liquidite CONCENTREE
# autour du tick courant, pas constant-product sur toute la courbe.
# Preuve live : QuoterV2 donne le MEME taux a 1 k$ et a 5 k$ sur
# USDC.e/USDT 0,01 % (impact < 0,01 %), et le pro-scan mesure des
# round-trips reels a -0,02 $ / -0,15 $, pas les -100 $ qu'un modele
# constant-product avec 416 k$ de reserves predirait. Pour les pools
# volatiles minces (ex. WMATIC/USDC.e 0,05 %, TVL 136 k$), l'impact
# reel a 5-20 k$ s'ajoute : le garde le gere via son loan optimal.
POOL_RESERVE_USD = 5_000_000_000.0


def _synthetic_pools(spread_pct: float, fee_buy_bps: int,
                     fee_sell_bps: int,
                     reserve_usd: float = POOL_RESERVE_USD):
    """Deux pools constant-product avec un ecart de prix = spread_pct.
    La pool 'buy' est la moins chere (on y achete), la 'sell' la plus
    chere (on y revend)."""
    buy = Pool("buy", reserve_usd, reserve_usd, fee_bps=fee_buy_bps)
    sell = Pool("sell", reserve_usd, reserve_usd / (1.0 + spread_pct / 100.0),
                fee_bps=fee_sell_bps)
    return buy, sell


def breakeven_table(spreads_pct: List[float] = (0.02, 0.05, 0.10),
                    sizes_usd: List[float] = (1_000.0, 5_000.0, 20_000.0),
                    gas_price_gwei: float = GAS_PRICE_GWEI) -> List[Dict]:
    """Table de breakeven avec la math de polygon_guard (decide() +
    evaluate_sizes()). Pour chaque paire de venues et chaque spread :
    breakeven analytique (frais A + frais B, + correction 0,1 bp par
    jambe a 0,001 %), net du garde a chaque taille (frais non modelises
    deduits), et decision optimale du garde."""
    costs = polygon_costs(gas_price_gwei)
    rows = []
    for name, fee_a, fee_b, unmodeled_bps in VENUE_PAIRS:
        total_fee_bps = fee_a + fee_b + unmodeled_bps
        for spread in spreads_pct:
            buy, sell = _synthetic_pools(spread, fee_a, fee_b)
            dec = polygon_decide(buy, sell, gas_price_gwei)
            nets = {}
            for row in evaluate_sizes(list(sizes_usd), buy, sell, costs):
                # Deduit les frais non modelises (0,001 % par jambe).
                corr = row["loan_usd"] * unmodeled_bps / 10_000.0
                nets[int(row["loan_usd"])] = round(row["net_usd"] - corr, 2)
            rows.append({
                "pair": name,
                "fees_bps": round(total_fee_bps, 1),
                "breakeven_spread_pct": round(total_fee_bps / 100.0, 3),
                "spread_pct": spread,
                "optimal_loan_usd": dec["optimal_loan_usd"],
                "optimal_net_usd": round(
                    dec["expected_net_usd"]
                    - dec["optimal_loan_usd"] * unmodeled_bps / 10_000.0, 2),
                "guard_action": dec["action"],
                "net_by_size_usd": nets,
            })
    return rows


# ---------------------------------------------------------------- market-making
def impermanent_loss_pct(price_ratio: float) -> float:
    """IL d'une position full-range quand le prix bouge d'un facteur
    price_ratio (ex. 1,10 = +10 %). Formule standard :
    IL = 2*sqrt(r)/(1+r) - 1 (negatif ou nul)."""
    import math
    return 2.0 * math.sqrt(price_ratio) / (1.0 + price_ratio) - 1.0


def lp_evaluation(volume24h_usd: float, fee_bps: float, tvl_usd: float,
                  position_usd: float) -> Dict:
    """APR de frais + revenus hebdo d'une position LP, a partir du volume
    24 h, du frais et de la TVL mesures. Hypothese : la position reste
    dans le range 100 % du temps (borne superieure, range concentre
    actif) ; un range large et passif gagne moins."""
    daily_fees = volume24h_usd * fee_bps / 10_000.0
    apr = daily_fees * 365.0 / tvl_usd if tvl_usd else 0.0
    share = position_usd / tvl_usd if tvl_usd else 0.0
    weekly = daily_fees * 7.0 * share
    return {
        "daily_fees_usd": round(daily_fees, 2),
        "fee_apr_pct": round(apr * 100.0, 2),
        "position_usd": position_usd,
        "weekly_fees_usd": round(weekly, 2),
        "yearly_fees_usd": round(weekly * 52.0, 2),
    }


# Pools LP mesures le 2026-11-25 (DefiLlama yields + DexScreener).
LP_POOLS = [
    # (nom, volume24h, frais bps, TVL, source)
    ("USDC.e/USDT V3 0,01 %", 644_001.0, 1, 830_874.0,
     "DefiLlama yields 2026-11-25 (apyBase 2,12 %)"),
    ("USDC natif/USDT V3 0,01 %", 1_627_546.0, 1, 536_117.0,
     "DefiLlama yields 2026-11-25 (apyBase 8,31 %)"),
    ("WMATIC/USDC.e V3 0,05 %", 35_849.0, 5, 136_185.0,
     "DefiLlama yields 2026-11-25 (apyBase 3,60 %)"),
    ("WMATIC/USDC natif V3 0,05 %", 287_306.0, 5, 173_397.0,
     "DefiLlama yields 2026-11-25 (apyBase 22,68 %)"),
    ("WMATIC/USDC.e V3 0,01 %", 3.61, 1, 292.0,
     "DexScreener 2026-11-25 : pool morte (vol 3,61 $/j)"),
]


if __name__ == "__main__":
    print("=== BREAKEVEN (garde Polygon, gas 282 gwei, budget 2x gas "
          f"= {polygon_costs(GAS_PRICE_GWEI).gas_usd:.4f} $) ===")
    for r in breakeven_table():
        print(f"{r['pair']:38s} frais {r['fees_bps']:>5} bps | "
              f"breakeven {r['breakeven_spread_pct']:.3f} % | "
              f"spread {r['spread_pct']:.2f} % | optimal "
              f"${r['optimal_loan_usd']:.0f} -> net "
              f"{r['optimal_net_usd']:+.2f} $ ({r['guard_action']}) | "
              f"net 1k/5k/20k $ : {r['net_by_size_usd']}")
    print()
    print("=== MARKET-MAKING (LP, position 1 000 $) ===")
    for name, vol, fee, tvl, src in LP_POOLS:
        ev = lp_evaluation(vol, fee, tvl, 1_000.0)
        print(f"{name:32s} APR {ev['fee_apr_pct']:>6} % | "
              f"+{ev['weekly_fees_usd']:.2f} $/sem | "
              f"+{ev['yearly_fees_usd']:.2f} $/an  [{src}]")
    print()
    print("=== IMPERMANENT LOSS (full-range, position 1 000 $) ===")
    for move in (1.05, 1.10, 1.20, 0.95, 0.90, 0.80):
        il = impermanent_loss_pct(move)
        print(f"prix x{move:.2f} : IL {il*100:+.3f} % = {il*1000:+.2f} $")
    print()
    print("=== ROUTE 4-JAMBES (chiffres enregistres, bloc 97921113) ===")
    print(route_4leg_from_quotes(5_000.0, 4_999.45, 5_005.16, 5_005.66,
                                 gas_budget_4leg_usd()))
