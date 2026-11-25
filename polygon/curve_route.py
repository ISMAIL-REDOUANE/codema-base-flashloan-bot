"""
curve_route.py — Route 4-jambes CORRIGÉE (v4.5, lecture seule + math pure).

CORRECTION vs LOW_FEE_PROFIT_POLYGON.md (vérifiée on-chain bloc 97 921 969) :
la jambe Curve NE rend PAS de l'USDC natif. underlying_coins(1) du am3pool
= 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174 = USDC.e (bridgé), PAS l'USDC
natif (0x3c49…). Les amTokens Aave v2 de Polygon wrappent l'USDC.e.
Donc exchange_underlying(2, 1) rend de l'USDC.e, et une 4e jambe
(USDC.e -> USDC natif, V3 0,01 %) est OBLIGATOIRE avant de rembourser
Morpho. La route correcte est donc 4 swaps :

    USDC (Morpho) --V3 100--> USDC.e --V3 100--> USDT
    --Curve (2,1)--> USDC.e --V3 100--> USDC (natif) --repay-->

Ce module NE BROADCAST RIEN. Il ne fait que :
  1. coter la route corrigée en lecture seule (eth_call, même bloc) ;
  2. calculer le net (pur) et le minDy (pur) pour le contrat
     CurveFlashArbPolygon.sol.

Quotes live vérifiées (bloc 97 922 005, 4 swaps) :
  1 000 $ -> brut +1,04 $ / net +1,01 $ (gas 2x)
  5 000 $ -> brut +5,11 $ / net +5,08 $
  20 000 $ -> brut +19,24 $ / net +19,20 $
"""
from __future__ import annotations

from typing import Dict, Optional

# ---------------------------------------------------------------- adresses
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"   # USDC natif
USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"          # USDC.e (bridgé)
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
CURVE_AM3POOL = "0x445FE580eF8d70FF569aB36e80c647af338db351"
MORPHO_POLYGON = "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"

# V3 USDC/USDC.e 0,01 % (token0 = USDC.e, token1 = USDC).
POOL_USDC_USDCE_100 = "0xD36ec33c8bed5a9F7B6630855f1533455b98a418"
# V3 USDC.e/USDT 0,01 % (token0 = USDC.e, token1 = USDT).
POOL_USDCE_USDT_100 = "0xDaC8A8E6DBf8c690ec6815e0fF03491B2770255D"

# Gas mesuré sur Polygon (pro-scan / realtime, nov 2026) et prix MATIC.
GAS_PRICE_GWEI = 280.0
MATIC_PRICE_USD = 0.0758
# Route 4 swaps : 3 swaps V3 + 1 Curve + flash loan + repay.
# Estimation prudente avant mesure fork (le trade 2-jambes est à ~450 000).
GAS_UNITS_4SWAP = 750_000
# minProfit on-chain (contrat) : 0,01 $.
ONCHAIN_MIN_PROFIT_USD = 0.01
# Marge de slippage pour minDy (jambe Curve) : quote x (1 - 0,05 %).
MINDY_SLIPPAGE = 0.0005


def gas_budget_4swap_usd(gas_price_gwei: float = GAS_PRICE_GWEI,
                         matic_price_usd: float = MATIC_PRICE_USD,
                         gas_units: int = GAS_UNITS_4SWAP) -> float:
    """Budget gas total (trade + budget revert = 2x gas), en $."""
    trade = gas_units * gas_price_gwei * 1e-9 * matic_price_usd
    return 2.0 * trade


def route_net_from_legs(loan_usd: float, leg0_usd: float, leg1_usd: float,
                        leg2_usd: float, leg3_usd: float,
                        gas_budget_usd: float) -> Dict:
    """Net de la route corrigée à partir des 4 sorties de jambes (pur).

    leg0 : USDC -> USDC.e (V3) ; leg1 : USDC.e -> USDT (V3) ;
    leg2 : USDT -> USDC.e (Curve) ; leg3 : USDC.e -> USDC (V3).
    """
    gross = leg3_usd - loan_usd
    net = gross - gas_budget_usd
    return {
        "loan_usd": loan_usd,
        "leg0_usdc_to_usdce": leg0_usd,
        "leg1_usdce_to_usdt": leg1_usd,
        "leg2_usdt_to_usdce_curve": leg2_usd,
        "leg3_usdce_to_usdc": leg3_usd,
        "gross_usd": round(gross, 4),
        "gas_budget_usd": round(gas_budget_usd, 4),
        "net_usd": round(net, 4),
        "verdict": "WIN" if net > 0 else "SKIP",
    }


def min_dy_for_quote(leg2_quote_usd: float,
                     slippage: float = MINDY_SLIPPAGE) -> int:
    """minDy (USDC.e, 6 décimales) pour la jambe Curve : quote x (1 - slip)."""
    return int(leg2_quote_usd * (1.0 - slippage) * 1e6)


# ---------------------------------------------------------------- garde Aave
# Leçon du fork test 2026-11-25 : la quote dit WIN mais la jambe Curve
# REVERT avec Aave v2 VL_RESERVE_FROZEN ('3') — les réserves DAI / USDC.e /
# USDT d'Aave v2 Polygon sont GELÉES (gouvernance : v2 dépréciée au profit
# de v3). exchange_underlying dépose l'underlying dans Aave v2, donc tout
# deposit revert. Le garde off-chain DOIT vérifier ce flag avant de
# broadcaster — une quote ne le voit pas (get_dy_underlying est une vue).
AAVE_V2_LENDING_POOL = "0x8dFf5E27EA6b7AC08EbFdf9eB090F32ee9a30fcf"
AAVE_V2_UNDERLYINGS = (  # DAI, USDC.e, USDT (ordre du am3pool)
    "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063",
    USDCE,
    USDT,
)
# Erreur Aave v2 (Errors.sol officiel) : VL_RESERVE_FROZEN = '3'.
AAVE_VL_RESERVE_FROZEN = "3"


def check_aave_frozen(w3, block: Optional[int] = None) -> Dict:
    """Lit les flags gelés des 3 réserves Aave v2 (on-chain, lecture seule).

    Retourne {'frozen': {token: bool}, 'any_frozen': bool}.
    Bit 57 de la configuration = isFrozen (cf. ReserveConfigurationMap).
    """
    from web3 import Web3

    blk = block if block is not None else w3.eth.block_number
    abi = [{"name": "getReserveData",
            "outputs": [{"components": [
                {"name": "configuration", "type": "uint256"},
                {"name": "liquidityIndex", "type": "uint128"},
                {"name": "variableBorrowIndex", "type": "uint128"},
                {"name": "currentLiquidityRate", "type": "uint128"},
                {"name": "currentVariableBorrowRate", "type": "uint128"},
                {"name": "currentStableBorrowRate", "type": "uint128"},
                {"name": "lastUpdateTimestamp", "type": "uint40"},
                {"name": "aTokenAddress", "type": "address"},
                {"name": "stableDebtTokenAddress", "type": "address"},
                {"name": "variableDebtTokenAddress", "type": "address"},
                {"name": "interestRateStrategyAddress", "type": "address"},
                {"name": "id", "type": "uint8"}], "name": "data", "type": "tuple"}],
            "inputs": [{"type": "address", "name": "asset"}],
            "stateMutability": "view", "type": "function"}]
    lp = w3.eth.contract(address=Web3.to_checksum_address(AAVE_V2_LENDING_POOL),
                         abi=abi)
    frozen = {}
    for tok in AAVE_V2_UNDERLYINGS:
        cfg = lp.functions.getReserveData(
            Web3.to_checksum_address(tok)).call(block_identifier=blk)[0]
        frozen[tok] = bool((cfg >> 57) & 1)
    return {"frozen": frozen, "any_frozen": any(frozen.values()),
            "block": blk}


def route_guard_decision(net_usd: float, aave_frozen: bool,
                         min_profit_usd: float = ONCHAIN_MIN_PROFIT_USD) -> Dict:
    """Décision off-chain de la route Curve (pur) : EXECUTE ssi
    net > 0 ET Aave v2 non gelé. Un net positif ne suffit PAS si la
    jambe Curve ne peut pas s'exécuter (revert garanti = gas perdu)."""
    if aave_frozen:
        return {"action": "SKIP", "reason": "aave_v2_frozen",
                "net_usd": net_usd,
                "detail": "Aave v2 gelé : exchange_underlying revert "
                          "(VL_RESERVE_FROZEN '3'). Ne pas broadcaster."}
    if net_usd <= 0:
        return {"action": "SKIP", "reason": "net_negatif", "net_usd": net_usd,
                "detail": "net <= 0 $ après gas."}
    if net_usd <= min_profit_usd:
        return {"action": "SKIP", "reason": "net_sous_minprofit",
                "net_usd": net_usd,
                "detail": "net <= minProfit on-chain (0,01 $)."}
    return {"action": "EXECUTE", "reason": "ok", "net_usd": net_usd,
            "detail": "net > 0 et Aave v2 non gelé."}


def quote_route_4swap_usdc(amount_usd: float, w3, block: Optional[int] = None,
                           gas_price_gwei: float = GAS_PRICE_GWEI) -> Dict:
    """Cote la route corrigée 4 swaps en lecture seule (eth_call), TOUTES
    les jambes au MEME bloc. Necessite web3. Ne broadcast rien."""
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
    l3 = qv3(USDCE, USDC_NATIVE, l2, 100)
    out = route_net_from_legs(amount_usd, l0 / 1e6, l1 / 1e6, l2 / 1e6,
                              l3 / 1e6, gas_budget_4swap_usd(gas_price_gwei))
    out["block"] = blk
    out["min_dy_usdce"] = min_dy_for_quote(l2 / 1e6)
    return out


if __name__ == "__main__":
    # Chiffres enregistrés (bloc 97 922 005, quotes live) — reprint only.
    for loan, l0, l1, l2, l3 in (
        (1_000.0, 999.89, 1001.03, 1001.14, 1001.04),
        (5_000.0, 4999.45, 5005.12, 5005.62, 5005.11),
        (20_000.0, 19997.49, 20019.82, 20021.57, 20019.24),
    ):
        print(route_net_from_legs(loan, l0, l1, l2, l3,
                                  gas_budget_4swap_usd()))
