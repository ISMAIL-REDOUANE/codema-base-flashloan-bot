"""
v3_quote.py — Cotation Uniswap V3 réelle (v2, amélioration n°1 de ADVANCED_RESEARCH.md).

LE PROBLÈME v1 : math_engine.py ne connaît que la formule V2 (x*y=k).
Or la moitié du marché Base est en liquidité concentrée (Uniswap V3,
Aerodrome Slipstream) : un swap V3 ne se calcule PAS avec la formule V2 —
il traverse des ticks, et la sortie dépend de la liquidité L et du prix
√P à chaque tick. Coter un pool V3 avec la formule V2 = trader à l'aveugle.

DEUX VOIES (dans cet ordre de préférence) :
  1. ON-CHAIN (exacte) : QuoterV2.quoteExactInput via eth_call sur le
     RPC Base — c'est le prix que le router obtiendrait vraiment, frais et
     ticks inclus. Adresse vérifiée (RESEARCH.md, docs Uniswap officiels) :
     0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a
     Sélecteur vérifié (keccak + test live 2026-11-24) :
     quoteExactInput = 0xcdca1753 — 100 USDC -> 0,0595 WETH (fee 500).
     quoteExactInputSingle (0xf7729d43) REVERT sur Base (vérifié : formes
     tuple + args, fees 500/3000, pools existants) — NE PAS L'UTILISER.
  2. PYTHON (approximation, un seul tick) : formule V3 à liquidité
     concentrée dans le tick courant — L et √P constants. Valable tant que
     le swap ne traverse pas de tick initialisé ; sinon on le signale
     (crossed_tick=True) et on recommande le quoter on-chain. À n'utiliser
     que quand le RPC est indisponible, et TOUJOURS marquée "estimate".

NON FAIT / HONNÊTETÉ :
  - Aerodrome Slipstream a son propre quoter (frais dynamiques) — NON
    implémenté ici : le quoter V3 Uniswap ne s'applique pas à Slipstream.
    Coter Slipstream avec ce module serait faux. À ajouter en v3.
  - Uniswap V4 (singleton, flash accounting) — NON implémenté, v3+.
  - Aucune quote n'est inventée : si l'on-chain échoue ET qu'on n'a pas
    L/√P réels, la fonction retourne status="unavailable", jamais un faux prix.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
# Sélecteurs keccak vérifiés (web3) le 2026-11-24 :
#   quoteExactInput(bytes,uint256) = 0xcdca1753  -> FONCTIONNE sur Base (vérifié live)
#   quoteExactInputSingle(...)    = 0xf7729d43  -> REVERT sur Base (vérifié live :
#     formes tuple + args séparés, fees 500 et 3000, pools existants confirmés
#     via factory.getPool — revert sans data à chaque fois). NE PAS UTILISER
#     quoteExactInputSingle sur Base tant que ce comportement n'est pas expliqué ;
#     on passe par quoteExactInput avec un path à 1 hop (même prix, même quoter).
SELECTOR_QUOTE_INPUT = bytes.fromhex("cdca1753")
SELECTOR_QUOTE_SINGLE = bytes.fromhex("f7729d43")  # documenté, inutilisable sur Base
Q96 = 2 ** 96


@dataclass
class V3Quote:
    amount_in: float          # montant d'entrée (en unités du token, ex. USDC 6 décimales -> en $ si USDC)
    amount_out: float         # montant de sortie estimé / quoté
    source: str               # "quoter_v2_onchain" | "v3_python_single_tick" | "unavailable"
    fee_bps: int = 0
    crossed_tick: bool = False  # True = le swap traverserait un tick -> l'estimation Python est fragile
    sqrt_price_x96_after: Optional[int] = None
    gas_estimate: Optional[int] = None
    error: Optional[str] = None


# ------------------------------------------------------------------ encodage ABI
def _addr_b32(address: str) -> bytes:
    return bytes.fromhex(address[2:].lower().rjust(64, "0"))


def _uint_b32(value: int) -> bytes:
    return int(value).to_bytes(32, "big")


def encode_quote_single(token_in: str, token_out: str, fee_bps: int,
                        amount_in: int, sqrt_price_limit_x96: int = 0) -> bytes:
    """Calldata de quoteExactInputSingle(address,address,uint24,uint256,uint160).
    CONSERVÉ POUR DOCUMENTATION : cette fonction REVERT sur Base (vérifié
    2026-11-24). Ne pas l'utiliser pour coter — utiliser encode_quote_path()."""
    return (SELECTOR_QUOTE_SINGLE + _addr_b32(token_in) + _addr_b32(token_out)
            + _uint_b32(fee_bps) + _uint_b32(amount_in)
            + _uint_b32(sqrt_price_limit_x96))


def encode_quote_path(token_in: str, fee_bps: int, token_out: str,
                      amount_in: int) -> bytes:
    """Calldata de quoteExactInput(bytes path, uint256 amountIn) — 1 hop.
    path = tokenIn (20 o) + fee (3 o, uint24) + tokenOut (20 o) = 43 octets.
    C'est LA voie qui fonctionne sur Base (vérifié live : 100 USDC -> WETH)."""
    path = bytes.fromhex(token_in[2:]) + int(fee_bps).to_bytes(3, "big") \
        + bytes.fromhex(token_out[2:])
    padded = path + b"\x00" * ((32 - len(path) % 32) % 32)
    return (SELECTOR_QUOTE_INPUT
            + _uint_b32(0x40)               # offset vers path
            + _uint_b32(amount_in)
            + _uint_b32(len(path))
            + padded)


def _rpc_eth_call(rpc_url: str, to: str, data: bytes, timeout: int = 15) -> bytes:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to, "data": "0x" + data.hex()}, "latest"],
    }).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "codema-flashloan-bot-v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"eth_call error: {out['error']}")
    return bytes.fromhex(out["result"][2:])


def quote_v3_onchain(token_in: str, token_out: str, fee_bps: int,
                     amount_in_wei: int, rpc_url: str,
                     timeout: int = 15) -> V3Quote:
    """Quote EXACTE via QuoterV2 on-chain (eth_call = 0 gas, lecture seule),
    par quoteExactInput avec un path à 1 hop (la voie qui FONCTIONNE sur Base).
    amount_in_wei : montant brut (ex. USDC : 6 décimales, 1 USDC = 1_000_000).
    Retourne amount_out brut dans les mêmes unités que le token de sortie.
    En cas d'échec RPC : status unavailable, JAMAIS de prix inventé."""
    try:
        data = encode_quote_path(token_in, fee_bps, token_out, amount_in_wei)
        raw = _rpc_eth_call(rpc_url, QUOTER_V2, data, timeout=timeout)
        # Retour quoteExactInput : (amountOut, sqrtPriceX96After[], ticksCrossed[], gasEstimate)
        amount_out = int.from_bytes(raw[0:32], "big")
        gas_est = int.from_bytes(raw[96:128], "big")
        sqrt_after = None
        ticks = 0
        try:
            off1 = int.from_bytes(raw[32:64], "big")
            sqrt_after = int.from_bytes(raw[off1 + 32:off1 + 64], "big")
            off2 = int.from_bytes(raw[64:96], "big")
            ticks = int.from_bytes(raw[off2 + 32:off2 + 64], "big")
        except Exception:
            pass
        return V3Quote(amount_in=amount_in_wei, amount_out=amount_out,
                       source="quoter_v2_onchain", fee_bps=fee_bps,
                       crossed_tick=ticks > 0, sqrt_price_x96_after=sqrt_after,
                       gas_estimate=gas_est)
    except Exception as e:
        return V3Quote(amount_in=amount_in_wei, amount_out=0.0,
                       source="unavailable", fee_bps=fee_bps,
                       error=f"quoter on-chain indisponible : {type(e).__name__}: {e}")


# Largeur d'un tick Uniswap V3 selon le tier de frais (en bps -> tick spacing) :
# 0,01 % (1 bp) -> 1 tick (0,01 %), 0,05 % (5 bp) -> 10 (0,1 %),
# 0,3 % (30 bp) -> 60 (0,6 %), 1 % (100 bp) -> 200 (2 %).
# Un mouvement de prix supérieur à la largeur d'un tick traverse
# (probablement) un tick initialisé : l'estimation mono-tick devient fragile.
_TICK_SPACING_BPS = {1: 1, 5: 10, 30: 60, 100: 200}


def _tick_width(fee_bps: int) -> float:
    spacing = _TICK_SPACING_BPS.get(fee_bps, 60)
    return 1.0001 ** spacing - 1.0
def v3_quote_python(amount_in: float, liquidity: float, sqrt_price_x96: int,
                    fee_bps: int = 30, zero_for_one: bool = True) -> V3Quote:
    """Approximation V3 à liquidité concentrée, DANS UN SEUL TICK.
    Math standard Uniswap V3 (voir docs Uniswap / ADVANCED_RESEARCH.md §4.1) :
      sqrtP = sqrtPriceX96 / 2**96   (prix = sqrtP², token1 par token0)
      - token0 -> token1 : 1/sqrtP_next = 1/sqrtP + amount0*(1-f)/L
                           amount1_out  = L * (sqrtP - sqrtP_next)
      - token1 -> token0 : sqrtP_next  = sqrtP + amount1*(1-f)/L
                           amount0_out  = L * (1/sqrtP - 1/sqrtP_next)
    Limites (à lire) : L et le tick sont supposés constants pendant le swap.
    Si le montant est grand devant L, le swap traverserait des ticks et
    cette formule SUR-ESTIME la sortie -> crossed_tick=True, à vérifier
    avec le quoter on-chain avant toute décision d'argent réel."""
    if amount_in <= 0 or liquidity <= 0 or sqrt_price_x96 <= 0:
        return V3Quote(amount_in=amount_in, amount_out=0.0,
                       source="v3_python_single_tick", fee_bps=fee_bps,
                       error="entrées invalides (montant / liquidité / prix)")
    amount_in_after_fee = amount_in * (1.0 - fee_bps / 10_000.0)
    sqrt_p = sqrt_price_x96 / Q96
    tick_width = _tick_width(fee_bps)
    if zero_for_one:
        inv_next = 1.0 / sqrt_p + amount_in_after_fee / liquidity
        sqrt_next = 1.0 / inv_next
        amount_out = liquidity * (sqrt_p - sqrt_next)
        # Mouvement de prix > largeur d'un tick -> franchissement probable.
        crossed = abs(sqrt_next / sqrt_p - 1.0) > tick_width
    else:
        sqrt_next = sqrt_p + amount_in_after_fee / liquidity
        amount_out = liquidity * (1.0 / sqrt_p - 1.0 / sqrt_next)
        crossed = abs(sqrt_next / sqrt_p - 1.0) > tick_width
    return V3Quote(amount_in=amount_in, amount_out=max(0.0, amount_out),
                   source="v3_python_single_tick", fee_bps=fee_bps,
                   crossed_tick=crossed,
                   sqrt_price_x96_after=int(sqrt_next * Q96))


def quote_v3_best(token_in: str, token_out: str, fee_bps: int,
                  amount_in_wei: int, rpc_url: Optional[str] = None,
                  liquidity: Optional[float] = None,
                  sqrt_price_x96: Optional[int] = None,
                  zero_for_one: bool = True) -> V3Quote:
    """Meilleure quote disponible, dans l'ordre :
    1) quoter on-chain si rpc_url donné, 2) formule Python si L et √P fournis,
    3) unavailable (jamais de prix inventé)."""
    if rpc_url:
        q = quote_v3_onchain(token_in, token_out, fee_bps, amount_in_wei, rpc_url)
        if q.source == "quoter_v2_onchain":
            return q
    if liquidity is not None and sqrt_price_x96 is not None:
        # amount_in_wei -> unités "token" : on suppose ici des tokens à
        # 18 décimales pour la formule Python ; pour USDC (6 déc.),
        # passer amount_in en unités réelles via l'appelant.
        return v3_quote_python(float(amount_in_wei), liquidity, sqrt_price_x96,
                               fee_bps, zero_for_one)
    return V3Quote(amount_in=amount_in_wei, amount_out=0.0, source="unavailable",
                   fee_bps=fee_bps,
                   error="ni RPC (quoter on-chain) ni (liquidité + √P) fournis")


if __name__ == "__main__":
    # Démo Python (sans RPC) : pool WETH/USDC fictif, L = 1 000 000, prix 3 000 $.
    # sqrtP = sqrt(3000) ≈ 54,77 -> sqrtPriceX96 = 54,77 * 2**96.
    import math as _math
    sqrt_x96 = int(_math.sqrt(3000) * Q96)
    q = v3_quote_python(100.0, 1_000_000.0, sqrt_x96, fee_bps=30, zero_for_one=False)
    print("V3 Python : 100 USDC ->", round(q.amount_out, 6), "WETH",
          "| source:", q.source, "| crossed_tick:", q.crossed_tick)
    # Démo on-chain réelle (lecture seule, 0 gas) : 100 USDC -> WETH, fee 0,05 %.
    # Vérifié live 2026-11-24 : ~0,0595 WETH (WETH ~1 680 $).
    q2 = quote_v3_onchain("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                          "0x4200000000000000000000000000000000000006",
                          500, 100_000_000, "https://mainnet.base.org")
    print("V3 on-chain :", q2.source, "->", q2.amount_out, "wei WETH",
          "| gas estimé:", q2.gas_estimate, "| erreur:", q2.error)
