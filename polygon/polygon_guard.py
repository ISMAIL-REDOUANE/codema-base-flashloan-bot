"""
polygon_guard.py — Garde off-chain Polygon v4.1 (règle net > 0 $).

CHANGEMENT DE RÈGLE (Ismail, 2026-11-24) : le min profit de 3 $ est
ABANDONNÉ sur Polygon. Nouvelle règle : on entre dans N'IMPORTE QUEL
trade dont le profit net simulé est > 0 $ APRÈS TOUS LES COÛTS :
  - flash fee (0 % Morpho),
  - frais de swap des pools (déjà dans les quotes / amm_out),
  - gas du trade,
  - budget revert (pire cas : gas + gas de revert).

Concrètement, le garde réutilise decide() de math_engine.py (fichier
Base, NON MODIFIÉ) avec des coûts adaptés :
  - gas_usd = gas du trade + budget revert = 2 × gas (REVERT_BUDGET_MULTIPLE = 1),
  - min_profit_usd = 0.0,
  - gas_multiple = 0.0 (la marge de sécurité « net > gas × 3 » est
    REMPLACÉE par le budget revert compté dans gas_usd — sinon on
    compterait le gas deux fois).
Avec ces paramètres, decide() dit EXECUTE exactement quand
net = brut - flash_fee - gas - budget_revert > 0.

Plancher anti-poussière ON-CHAIN : le contrat MorphoFlashLoanArbitragePolygon
est déployé avec minProfit = 0,01 $ (ONCHAIN_MIN_PROFIT_USD). Le garde
off-chain fait le vrai calcul économique ; le require on-chain n'est que
le filet de sécurité atomique (un trade à profit < 0,01 $ revert — il ne
peut pas finir perdant ou nul à cause d'un mouvement de prix entre la
simulation et l'inclusion).

Le bot Base garde min 3 $ (sauf instruction contraire) : ce module est
Polygon uniquement. Aucune clé privée, simulation seulement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from math_engine import Costs, Pool, decide, gas_cost_usd  # noqa: E402

# Budget revert = 1 × gas du trade (pire cas : trade + un revert).
# Mesuré sur le fork Polygon : revert 0,0024 $ vs trade 0,0028 $ — le
# modèle prudent (450 000 unités × 279 gwei = 0,0095 $) couvre ~4× le
# revert mesuré. Coût total budgété = 2 × gas.
REVERT_BUDGET_MULTIPLE = 1.0
# Plancher anti-poussière on-chain (USDC, 6 décimales : 0,01 $ = 10 000).
ONCHAIN_MIN_PROFIT_USD = 0.01
GAS_UNITS = 450_000
GAS_PRICE_MAX_GWEI = 1000.0
MATIC_PRICE_USD = 0.0758


def polygon_costs(gas_price_gwei: float,
                  matic_price_usd: float = MATIC_PRICE_USD,
                  gas_units: int = GAS_UNITS) -> Costs:
    """Costs Polygon v4.1 : gas total = trade + budget revert, min 0 $.

    gas_usd = 2 × (units × gwei × prix MATIC) : le trade ET son revert
    éventuel sont budgétés AVANT de décider. min_profit = 0, gas_multiple
    = 0 : decide() dit alors EXECUTE exactement quand net > 0 $.
    """
    trade_gas = gas_cost_usd(gas_units, gas_price_gwei, matic_price_usd)
    total_gas = trade_gas * (1.0 + REVERT_BUDGET_MULTIPLE)
    return Costs(gas_usd=total_gas,
                 flash_provider="morpho",
                 min_profit_usd=0.0,
                 gas_multiple=0.0,
                 gas_price_gwei=gas_price_gwei,
                 max_gas_price_gwei=GAS_PRICE_MAX_GWEI)


def polygon_decide(pool_buy: Pool, pool_sell: Pool,
                   gas_price_gwei: float,
                   matic_price_usd: float = MATIC_PRICE_USD,
                   gas_units: int = GAS_UNITS,
                   max_loan_usd: float = 50_000.0,
                   max_pct_liquidity: float = 0.10) -> dict:
    """Décision Polygon v4.1 : EXECUTE ssi net > 0 $ après TOUS les coûts.

    Retourne le dict de decide() + le champ ``rule`` qui explicite la
    règle appliquée et le détail des coûts (gas trade, budget revert).
    """
    costs = polygon_costs(gas_price_gwei, matic_price_usd, gas_units)
    d = decide(pool_buy, pool_sell, costs, max_loan_usd, max_pct_liquidity)
    trade_gas = gas_cost_usd(gas_units, gas_price_gwei, matic_price_usd)
    d["rule"] = ("net > 0 $ apres gas + budget revert "
                 "(v4.1, min profit 3 $ abandonne)")
    d["gas_trade_usd"] = round(trade_gas, 6)
    d["revert_budget_usd"] = round(trade_gas * REVERT_BUDGET_MULTIPLE, 6)
    d["total_cost_usd"] = round(costs.gas_usd, 6)
    d["onchain_min_profit_usd"] = ONCHAIN_MIN_PROFIT_USD
    return d


def tranche(net_usd: float) -> str:
    """Tranche d'une opportunité, pour mesurer l'effet du changement de
    règle : > 0 $, >= 0,50 $, >= 3 $ (ancienne barre)."""
    if net_usd >= 3.0:
        return ">=3$"
    if net_usd >= 0.50:
        return ">=0.50$"
    if net_usd > 0:
        return ">0$"
    return "<=0$"


def tranche_counts(nets: list) -> dict:
    """Compte les opportunités par tranche, en CUMULÉ (chaque tranche
    inclut les supérieures) : ">0$" = tous les nets > 0 ; ">=0.50$" =
    ceux >= 0,50 $ ; ">=3$" = ceux >= 3 $ (ancienne barre) ; "<=0$" =
    les non rentables. Sert à mesurer l'effet du changement de règle."""
    return {
        ">0$": sum(1 for n in nets if n > 0),
        ">=0.50$": sum(1 for n in nets if n >= 0.50),
        ">=3$": sum(1 for n in nets if n >= 3.0),
        "<=0$": sum(1 for n in nets if n <= 0),
    }


if __name__ == "__main__":
    # Démo : spread 10 % → EXECUTE ; spread ~1,7 % → petit net > 0 → EXECUTE ;
    # spread 0 → SKIP. Barème v4.1.
    buy = Pool("QuickSwap", 8_800.0, 115_000.0)
    for name, sell in (
        ("spread 10 %", Pool("Uni V3", 9_700.0, 115_000.0)),
        ("spread ~1,7 %", Pool("Uni V3", 8_950.0, 115_000.0)),
        ("spread 0 %", Pool("Uni V3", 8_800.0, 115_000.0)),
    ):
        d = polygon_decide(buy, sell, 279.0)
        print(f"{name:14} -> {d['action']:7} net={d['expected_net_usd']:.2f} $ "
              f"loan={d['optimal_loan_usd']:.2f} $ "
              f"(gas trade {d['gas_trade_usd']:.5f} $ + revert "
              f"{d['revert_budget_usd']:.5f} $) tranche={tranche(d['expected_net_usd'])}")
