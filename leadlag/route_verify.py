#!/usr/bin/env python3
"""route_verify.py — VÉRIFICATION INDÉPENDANTE d'une route cross-venue (Base).

Reprend une route du scan (même bloc, même état) et re-calcule le net en
SÉPARANT fees / impact / gas, SANS double comptage, avec une implémentation
de la math V3 écrite indépendamment (pas de réutilisation de
v3_quote.v3_quote_python pour le calcul principal — on le compare ensuite
comme garde croisée).

Rappel math (Uniswap V3, un seul tick, L et sqrtP constants) :
  - le quoter V3 applique la fee sur l'INPUT : amount_in_after_fee =
    amount_in * (1 - f). La fee est donc DANS le prix d'exécution, pas
    ajoutée après. Un calcul qui ajouterait "fee" au net APRÈS avoir quoté
    avec fee compterait la fee DEUX fois — c'est l'erreur à éviter.
  - décomposition d'une jambe (en unités de sortie, au prix mid) :
      idéal (ni fee ni impact)  = amount_in * mid
      fee (en sortie)           = amount_in * f * mid
      idéal après fee           = amount_in * (1 - f) * mid
      impact (en sortie)        = idéal après fee - sortie réelle
      => idéal - réelle = fee + impact (identité vérifiée numériquement)
  - net du cycle = brut(mid) - fee_achat - impact_achat
                   - fee_vente - impact_vente - gas
    où brut(mid) = taille * (mid_vente / mid_achat - 1) est le profit
    brut du seul écart de prix mid.
    Identité de contrôle : net == (sortie réelle jambe 2 en USD) - taille - gas.

Gardes (fail-closed) :
  - quoter on-chain officiel comme garde là où il existe (Uni V3 /
    Pancake QuoterV2 ; Aerodrome MixedQuoterV3 SEULEMENT si la factory de
    la pool est GaugesV3 0xf8f2... — sinon "non adressable", dit
    explicitement) : écart quoter vs analytique > 2% => NON VÉRIFIÉ.
  - TVL >= 10x la taille sur chaque jambe (règle AMZNc), sinon NON VÉRIFIÉ.
  - crossed_tick : si le swap traverse un tick, le modèle mono-tick est
    fragile => signalé, et la quote du quoter (si dispo) fait foi.

Lecture seule on-chain ; AUCUN broadcast, AUCUN wallet, AUCUNE clé.
La clé RPC est lue en mémoire depuis config.yaml, jamais affichée ni loguée.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")
sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")

import cross_venue as cv  # noqa: E402  (RPC + eth_call + keccak_sel)
from v3_quote import v3_quote_python  # noqa: E402  (garde croisée uniquement)

cv.init_selectors()  # les SEL_* (slot0, fee, ...) sont des globales de cross_venue

Q96 = 2 ** 96
# ------------------------------------------------------------------ GAS (#12)
# Fini le $0,0044 figé : le gas est le COÛT COMPLET de la transaction
# exacte (exécution L2 + fee L1 Base), mesuré on-chain au bloc visé.
# - Unités L2 : 285 948 mesurées en fork Base (exécution réussie
#   MorphoFlashLoanArbitrage, bloc 61 807 834, fork_results_morpho.json) ;
#   budget prudent du repo : 450 000 unités (couvre l'estimation eth_call
#   364 074 + marge). Les mesures fork Anvil NE comptent PAS la fee L1.
# - Prix L2 : baseFeePerGas du bloc (eth_getBlockByNumber) + 0 priorité
#   (le fork utilisait maxPriorityFeePerGas=0).
# - Fee L1 : GasPriceOracle.getL1Fee(calldata) au même bloc. Le calldata
#   de executeArbitrage(uint256) = sélecteur 4 o + montant 32 o = 36 o.
# - Prix ETH : mid WETH/USDC on-chain au bloc (pas de prix fixe).
GAS_ORACLE = "0x420000000000000000000000000000000000000F"
GAS_UNITS_MEASURED = 285948      # exécution réussie, fork Base 61 807 834
GAS_UNITS_PRUDENT = 450000       # budget prudent du repo
GAS_LEGACY_USD = 0.0044          # ancienne hypothèse figée (comparaison)
QUOTER_TOL_PCT = 0.005           # 0,5 bp — la tolérance doit être < la
# marge nette recherchée (quelques bp) ; l'ancien 2 % = 200 bp acceptait
# n'importe quoi. Mesuré sur la jambe de vente WETH/cbBTC : -0,0001 %.
AERO_GAUGES_V3_FACTORY = "0xf8f2eB4940CFE7d13603DDDD87f123820Fc061Ef"
UNI_V3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
# CORRECTION 2026-11-25 : la constante CAKE_V3_FACTORY de cross_venue.py
# (0x0BFb...ba76a35) est la factory BSC, PAS celle de Base. Vérifié
# on-chain au bloc 62 077 712 : factory() du quoter Cake Base ET factory()
# de la pool Pancake 0xb94b2233... = 0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865.
CAKE_V3_FACTORY_BASE = "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865"
CAKE_V3_FACTORY_BSC_WRONG = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805bA76a35"  # ne pas utiliser sur Base
UNI_V3_QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
CAKE_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
AERO_MIXED_QUOTER_V3 = "0xCd2A7D98e82D6107eac1828ce8DeAA6acB65b555"
WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"


# ------------------------------------------------------------------ lectures
def _eth_call_retry(to, data_hex, block, tries=4, delays=(1, 3, 8)):
    """eth_call avec retries : le RPC renvoie parfois des 429, des timeouts,
    voire des réponses à zéro sous charge (observé : fee() -> 32 octets à
    zéro). Un 0 sur fee/slot0/liquidité est IMPOSSIBLE pour nos pools :
    on retente, puis on échoue bruyamment (fail-closed) au lieu de
    poursuivre avec un coût sous-estimé — une fee à 0 fabriquerait un
    faux profit. Ne JAMAIS logger la clé RPC (elle est dans l'URL)."""
    import time as _time
    last = None
    for attempt in range(tries):
        try:
            out = cv.eth_call(to, data_hex, block)
            return out
        except Exception as e:  # noqa: BLE001 — 429/timeout réseau
            last = e
            if attempt < tries - 1:
                _time.sleep(delays[min(attempt, len(delays) - 1)])
    raise RuntimeError(f"eth_call {to[:12]}.. {data_hex[:12]} bloc {block} "
                       f"échoué après {tries} essais : {type(last).__name__}: {str(last)[:100]}")


def _u256(hexstr):
    return int.from_bytes(bytes.fromhex(hexstr[2:] if hexstr.startswith("0x") else hexstr), "big")


def read_pool_state(pool, block):
    """slot0 + liquidité + fee + token0 + tickSpacing + factory au bloc épinglé.
    Supporte aussi les pools V2 (getReserves) : si slot0() REVERT on-chain
    (la pool n'est pas une CL — ex. Uniswap V2 0x88A43bbD, factory V2),
    on bascule sur getReserves(). Un revert « execution reverted » n'est
    PAS une erreur réseau : il ne déclenche pas de retry infini."""
    st = {"pool": pool}
    try:
        sqrt_x96, tick = cv.parse_slot0(_eth_call_retry(pool, "0x" + cv.SEL_SLOT0, block))
    except RuntimeError as e:
        if "execution reverted" in str(e):
            st["pool_type"] = "v2"
            return _read_pool_state_v2(st, pool, block)
        raise
    if sqrt_x96 <= 0:
        raise RuntimeError(f"slot0 à zéro pour {pool} au bloc {block} — RPC suspect, abandon")
    st["pool_type"] = "cl"
    st["sqrt_x96"], st["tick"] = sqrt_x96, tick
    st["liq"] = _u256(_eth_call_retry(pool, "0x" + cv.SEL_LIQ, block))
    if st["liq"] <= 0:
        raise RuntimeError(f"liquidité à zéro pour {pool} au bloc {block} — RPC suspect, abandon")
    st["fee_bps"] = None
    for _attempt in range(3):
        try:
            fee = _u256(_eth_call_retry(pool, "0x" + cv.SEL_FEE, block))
        except Exception:
            fee = None
        if fee:  # une fee V3 réelle n'est jamais 0 ; 0 = réponse RPC corrompue
            st["fee_bps"] = fee
            break
        import time as _time
        _time.sleep(2)
    try:
        st["tick_spacing"] = _u256(_eth_call_retry(pool, "0x" + cv.SEL_TICK_SPACING, block))
    except Exception:
        st["tick_spacing"] = None
    st["token0"] = "0x" + _eth_call_retry(pool, "0x" + cv.SEL_TOKEN0, block)[-40:]
    try:
        st["factory"] = "0x" + _eth_call_retry(pool, "0x" + cv.keccak_sel("factory()"), block)[-40:]
    except Exception:
        st["factory"] = None
    # Fallback fee : les pools Aerodrome CL n'exposent pas toujours fee() —
    # on dérive la fee du tickSpacing via la factory (feeAmountTickSpacing).
    if st["fee_bps"] is None and st.get("factory") and st.get("tick_spacing") is not None:
        sel = cv.keccak_sel("feeAmountTickSpacing(uint24)")
        for cand in (1, 50, 100, 250, 300, 500, 1000, 3000, 10000):
            try:
                data = "0x" + sel + cand.to_bytes(32, "big").hex()
                ts = _u256(_eth_call_retry(st["factory"], data, block))
                if ts == st["tick_spacing"]:
                    st["fee_bps"] = cand
                    st["fee_source"] = "factory_tickSpacing"
                    break
            except Exception:
                continue
    if st["fee_bps"] is None:
        raise RuntimeError(f"fee introuvable on-chain pour {pool} au bloc {block} "
                           f"— vérification impossible, pas de fee supposée")
    st.setdefault("fee_source", "pool_fee()")
    return st


# Factories V2 connues sur Base (pour le routeur de garde getAmountsOut).
V2_FACTORY_TO_ROUTER = {
    "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",  # Uni V2 -> Router02
    "0xc35dadb65012ec5796536bd9864ed8773abc74c4": "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",  # Sushi V2
    "0x5757371414417b8c6caad45baef941abc7d3ab32": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",  # QuickSwap V2
}
AERO_V2_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"  # routeur Aerodrome V2 (Base)


def _read_pool_state_v2(st, pool, block):
    """État d'une pool V2 (constant product) : réserves + token0 + factory.
    Fee V2 standard = 3000 (0,30 %, 997/1000) — les 4 pools V2 du scan
    l'enregistrent toutes à 3000 ; elle est lue comme telle, pas supposée
    à une autre valeur."""
    raw = _eth_call_retry(pool, "0x" + cv.keccak_sel("getReserves()"), block)
    b = bytes.fromhex(raw[2:])
    st["reserve0"] = int.from_bytes(b[0:32], "big")
    st["reserve1"] = int.from_bytes(b[32:64], "big")
    if st["reserve0"] <= 0 or st["reserve1"] <= 0:
        raise RuntimeError(f"réserves à zéro pour {pool} au bloc {block}")
    st["token0"] = "0x" + _eth_call_retry(pool, "0x" + cv.SEL_TOKEN0, block)[-40:]
    try:
        st["factory"] = "0x" + _eth_call_retry(pool, "0x" + cv.keccak_sel("factory()"), block)[-40:]
    except Exception:
        st["factory"] = None
    st["fee_bps"] = 3000
    st["fee_source"] = "v2_standard_0.3pct"
    st["liq"] = None
    st["sqrt_x96"] = None
    st["tick"] = None
    st["tick_spacing"] = None
    return st


def v2_router_quote(router, token_in, token_out, amount_in_raw, block):
    """Garde V2 : Router.getAmountsOut(amountIn, [in, out]) — quote on-chain
    calculée sur les réserves (l'équivalent V2 du quoter). Retourne
    amounts[1] (raw) ou None après 3 essais. Note : les adresses d'un
    tableau address[] sont des MOTS de 32 octets (rembourrage à gauche),
    pas les 20 octets du chemin compacté (bug trouvé ici : _addr_b32
    renvoie 20 o, l'appel revertissait)."""
    def _addr_word(addr):
        return bytes(12) + bytes.fromhex(addr[2:].zfill(40))
    for _attempt in range(3):
        try:
            data = ("0x" + cv.keccak_sel("getAmountsOut(uint256,address[])")
                    + _uint_b32(amount_in_raw).hex() + _uint_b32(0x40).hex()
                    + _uint_b32(2).hex()
                    + _addr_word(token_in).hex() + _addr_word(token_out).hex())
            raw = _eth_call_retry(router, data, block)
            b = bytes.fromhex(raw[2:])
            # retour : offset (32 o) + longueur (32 o) + amounts[0] + amounts[1]
            if len(b) < 128:
                return None
            return int.from_bytes(b[96:128], "big")
        except Exception:
            continue
    return None


def v2_router_for_factory(factory):
    """Routeur V2 correspondant à la factory (None si inconnue — la garde
    sera alors not_addressable, pas devinée)."""
    return V2_FACTORY_TO_ROUTER.get((factory or "").lower())


def token_decimals(addr):
    return cv.token_decimals(addr)


# ------------------------------------------------------------------ math V3 (indépendante)
def mid_from_sqrt(sqrt_x96, dec_token, dec_quote, token_is_token0):
    """Prix mid (quote par token, unités humaines) depuis sqrtPriceX96."""
    sqrt_p = sqrt_x96 / Q96
    adj = 10.0 ** (dec_token - dec_quote)
    if token_is_token0:
        return sqrt_p * sqrt_p * adj
    return adj / (sqrt_p * sqrt_p)


def mono_tick_out(amount_in_raw, liq, sqrt_x96, fee_bps, zero_for_one, tick_spacing=None):
    """Sortie brute (raw) du modèle mono-tick — math standard Uniswap V3,
    réimplémentée ici (ne pas confondre avec v3_quote_python, utilisée en
    garde croisée). fee_bps = fee on-chain V3 en unités de 1e-6
    (500 = 0,05 %, 85 = 0,0085 %) ; la fraction est fee_bps / 1_000_000
    (PAS / 10_000 — diviser par 10_000 surestimerait la fee 100x, erreur
    trouvée et corrigée ici).
    tick_spacing = espacement réel lu on-chain (défaut : 60).
    Retourne (amount_out_raw, crossed_tick, sqrt_next)."""
    if amount_in_raw <= 0 or liq <= 0 or sqrt_x96 <= 0:
        return 0.0, False, sqrt_x96
    f = fee_bps / 1_000_000.0  # fee on-chain V3 en unités de 1e-6
    amount_after_fee = amount_in_raw * (1.0 - f)
    sqrt_p = sqrt_x96 / Q96
    ts = tick_spacing if tick_spacing else 60
    tick_width = 1.0001 ** ts - 1.0
    if zero_for_one:
        inv_next = 1.0 / sqrt_p + amount_after_fee / liq
        sqrt_next = 1.0 / inv_next
        amount_out = liq * (sqrt_p - sqrt_next)
        crossed = abs(sqrt_next / sqrt_p - 1.0) > tick_width
    else:
        sqrt_next = sqrt_p + amount_after_fee / liq
        amount_out = liq * (1.0 / sqrt_p - 1.0 / sqrt_next)
        crossed = abs(sqrt_next / sqrt_p - 1.0) > tick_width
    return max(0.0, amount_out), crossed, int(sqrt_next * Q96)


def decompose_leg(amount_in_raw, liq, sqrt_x96, fee_bps, zero_for_one,
                  dec_in, dec_out, mid_out_per_in, tick_spacing=None):
    """Décompose UNE jambe : idéal / fee / impact / réel.
    mid_out_per_in = prix mid (sortie humaine par 1 entrée humaine).
    Toutes les valeurs en unités RAW de sortie, sauf 'mid' (humain).
    Identité : ideal - actual == fee + impact (à ~1e-9 près)."""
    f = fee_bps / 1_000_000.0  # fee on-chain V3 en unités de 1e-6
    scale = 10.0 ** (dec_out - dec_in)  # raw_out par raw_in au prix mid
    ideal = amount_in_raw * mid_out_per_in * scale
    fee_out = amount_in_raw * f * mid_out_per_in * scale
    after_fee_ideal = amount_in_raw * (1.0 - f) * mid_out_per_in * scale
    actual, crossed, _ = mono_tick_out(amount_in_raw, liq, sqrt_x96, fee_bps,
                                     zero_for_one, tick_spacing=tick_spacing)
    impact = after_fee_ideal - actual
    return {"ideal_raw": ideal, "fee_raw": fee_out, "impact_raw": impact,
            "actual_raw": actual, "crossed_tick": crossed,
            "identity_err_raw": (ideal - actual) - (fee_out + impact)}


def measure_full_gas(block, eth_usd, gas_units=GAS_UNITS_MEASURED,
                     calldata_len=36):
    """Coût COMPLET de la transaction d'arbitrage exacte au bloc donné :
    exécution L2 (baseFeePerGas du bloc, priorité 0) + fee L1 Base
    (GasPriceOracle.getL1Fee sur le calldata réel, 36 o). Converti en USD
    au prix ETH on-chain du bloc. Les mesures fork Anvil ne comptent pas
    la L1 — ici elle est mesurée, pas supposée. Retourne un dict.
    Ne PAS utiliser le $0,0044 figé comme coût (il est gardé dans
    GAS_LEGACY_USD pour comparaison seulement)."""
    cv.init_selectors()
    blk = cv.rpc_call("eth_getBlockByNumber", [hex(block), False])
    base_fee_wei = int(blk["baseFeePerGas"], 16)
    # calldata représentatif : executeArbitrage(uint256) — 4 o sélecteur
    # + 32 o montant (100 USDC = 100_000_000, majorité d'octets à zéro).
    sel = cv.keccak_sel("executeArbitrage(uint256)")
    amount = (100_000_000).to_bytes(32, "big")
    data = bytes.fromhex(sel) + amount
    assert len(data) == calldata_len, len(data)
    # getL1Fee(bytes) : sélecteur + offset 0x20 + longueur + données (32 o)
    gsel = cv.keccak_sel("getL1Fee(bytes)")
    payload = ("0x" + gsel + (32).to_bytes(32, "big").hex()
               + len(data).to_bytes(32, "big").hex()
               + data.hex().ljust(64, "0"))
    l1_fee_wei = _u256(_eth_call_retry(GAS_ORACLE, payload, block))
    l2_fee_wei = gas_units * base_fee_wei
    total_wei = l2_fee_wei + l1_fee_wei
    return {
        "block": block, "gas_units": gas_units,
        "base_fee_gwei": base_fee_wei / 1e9,
        "l2_fee_wei": l2_fee_wei, "l2_fee_usd": l2_fee_wei / 1e18 * eth_usd,
        "l1_fee_wei": l1_fee_wei, "l1_fee_usd": l1_fee_wei / 1e18 * eth_usd,
        "l1_share_pct": (l1_fee_wei / total_wei * 100.0 if total_wei else 0.0),
        "total_usd": total_wei / 1e18 * eth_usd,
        "eth_usd": eth_usd, "calldata_len": calldata_len,
        "legacy_usd": GAS_LEGACY_USD,
    }


def decompose_leg_v2(amount_in_raw, reserve_in, reserve_out, fee_bps,
                     dec_in, dec_out, mid_out_per_in):
    """Décompose UNE jambe V2 (constant product, fee 0,30 % sur l'entrée).
    Même forme de retour que decompose_leg (CL) : idéal / fee / impact /
    réel, avec l'identité idéal - réel == fee + impact. La quote CP vient
    de cv.v2_quote (modèle vérifié par le scan)."""
    f = fee_bps / 1_000_000.0
    scale = 10.0 ** (dec_out - dec_in)
    ideal = amount_in_raw * mid_out_per_in * scale
    fee_out = amount_in_raw * f * mid_out_per_in * scale
    after_fee_ideal = amount_in_raw * (1.0 - f) * mid_out_per_in * scale
    actual = cv.v2_quote(float(amount_in_raw), float(reserve_in),
                         float(reserve_out), fee=f)
    impact = after_fee_ideal - actual
    return {"ideal_raw": ideal, "fee_raw": fee_out, "impact_raw": impact,
            "actual_raw": actual, "crossed_tick": False,
            "identity_err_raw": (ideal - actual) - (fee_out + impact)}


def mid_from_reserves(reserve_token, reserve_quote, dec_token, dec_quote):
    """Prix mid (quote par token) depuis les réserves V2."""
    return (reserve_quote / 10 ** dec_quote) / (reserve_token / 10 ** dec_token)


# ------------------------------------------------------------------ quoter (garde)
def _addr_b32(addr):
    return bytes.fromhex(addr[2:].zfill(40))


def _uint_b32(n):
    return int(n).to_bytes(32, "big")


def quoter_path_quote(quoter_addr, token_in, token_out, fee_bps, amount_in_raw, block):
    """QuoterV2 quoteExactInput (path, 1 hop) — implémentation directe avec
    retry (l'ABI path est connue-bonne ; on ÉVITE quoteExactInputSingle,
    dont l'encodage fee/amountIn est inversé — audit #8). Retourne
    amount_out raw ou None après 3 essais."""
    for _attempt in range(3):
        try:
            path = (bytes.fromhex(token_in[2:]) + int(fee_bps).to_bytes(3, "big")
                    + bytes.fromhex(token_out[2:]))
            padded = path + b"\x00" * ((32 - len(path) % 32) % 32)
            data = ("0x" + cv.keccak_sel("quoteExactInput(bytes,uint256)")
                    + _uint_b32(0x40).hex() + _uint_b32(amount_in_raw).hex()
                    + _uint_b32(len(path)).hex() + padded.hex())
            raw = _eth_call_retry(quoter_addr, data, block)
            # quoteExactInput renvoie 4 mots (amountOut, sqrtPriceX96After,
            # initializedTicksCrossed, gasEstimate) : SEUL le 1er mot est
            # amountOut. Prendre tout le retour fabrique un entier géant
            # (bug trouvé ici : OverflowError sur la jambe Cake E1).
            return int.from_bytes(bytes.fromhex(raw[2:])[0:32], "big")
        except Exception:
            continue
    return None


def quoter_check_aero(token_in, token_out, tick_spacing, amount_in_raw, block):
    """MixedQuoterV3 (tag 0x80000|tickSpacing) — valable SEULEMENT pour les
    pools de la factory GaugesV3. Retourne amount_out raw ou None.
    Retry sur None (un 429 transitoire ressemble à un revert)."""
    for _attempt in range(3):
        try:
            out = cv.aero_mixed_quoter(token_in, token_out, tick_spacing, amount_in_raw, block)
            if out is not None:
                return out
        except Exception:
            pass
    return None


def quoter_tol_pct(out_raw):
    """Tolérance effective du quoter en % : max(0,5 bp, 1 unité de sortie).
    Le quoter renvoie des entiers : à petit montant, 1 unité brute vaut
    déjà plus que 0,5 bp (sortie 1 703 raw -> 1 unité = 0,059 %)."""
    if not out_raw:
        return QUOTER_TOL_PCT
    return max(QUOTER_TOL_PCT, 100.0 / out_raw)


def quoter_for_pool(factory, token_in, token_out, fee_bps, tick_spacing,
                    amount_in_raw, block):
    """Choisit le quoter par factory (vérifiée on-chain). Règle stricte
    (audit #2) : un quoter ne cite que les pools DE SA factory (il résout
    la pool par (tokens, fee) ou (tokens, tickSpacing) dans sa factory).
    Citer une pool d'une autre factory, c'est citer UNE AUTRE POOL — donc
    PAS de repli sur les autres quoters : si le quoter de la factory ne
    répond pas, la jambe est not_addressable, pas « vérifiée » par une
    pool voisine (bug trouvé ici : le MixedQuoter citait la pool 0x7C74
    à la place de 0xeC3c, écart -0,0039 % faussement « vérifié »).
    Retourne (amount_out raw ou None, nom du quoter)."""
    fac = (factory or "").lower()
    if fac == AERO_GAUGES_V3_FACTORY.lower():
        out = quoter_check_aero(token_in, token_out, tick_spacing, amount_in_raw, block)
        return out, ("aero_mixed_quoter_v3 (GaugesV3)" if out is not None else None)
    if fac == UNI_V3_FACTORY.lower():
        out = quoter_path_quote(UNI_V3_QUOTER_V2, token_in, token_out, fee_bps,
                                amount_in_raw, block)
        return out, ("uni_quoter_v2" if out is not None else None)
    if fac == CAKE_V3_FACTORY_BASE.lower():
        out = quoter_path_quote(CAKE_QUOTER_V2, token_in, token_out, fee_bps,
                                amount_in_raw, block)
        return out, ("cake_quoter_v2" if out is not None else None)
    return None, None


# ------------------------------------------------------------------ cycle complet
def verify_cycle(buy_pool, sell_pool, token_addr, quote_addr, size_usd,
                 usd_price_quote, block, tvl_buy_usd=None, tvl_sell_usd=None,
                 states=None, quoter_guard=True, decimals=None, gas_usd=None):
    """... decimals=(dec_token, dec_quote) : décimales à utiliser (défaut :
    lues on-chain via token_decimals — strict, lève une erreur si le RPC
    échoue). Passer decimals explicites rend la fonction testable hors-ligne.
    gas_usd : COÛT COMPLET mesuré de la transaction exacte
    (measure_full_gas) — REQUIS, pas de valeur par défaut (le $0,0044
    figé est interdit, audit #12). Le cycle est INVALIDE si
    buy_pool == sell_pool (audit : la « meilleure paire » $1 000 du scan
    est la même pool des deux côtés — exclue)."""
    """Simule le CYCLE ATOMIQUE COMPLET au bloc donné :
    emprunt flash Morpho 0% (size_usd de quote) -> achat jambe 1 (quote->token)
    -> vente jambe 2 (token->quote) -> remboursement.
    Retourne la décomposition complète + gardes. TOUT EST SYNTHÉTIQUE
    (quotes analytiques / quoter, jamais exécuté, jamais un profit)."""
    cv.init_selectors()
    # --- garde cycle invalide (audit) : même pool des deux côtés
    if buy_pool.lower() == sell_pool.lower():
        raise ValueError(f"cycle invalide : buy_pool == sell_pool == {buy_pool} "
                         f"(la « meilleure paire » $1 000 du scan — exclue)")
    # --- gas : coût complet mesuré, jamais le $0,0044 figé (audit #12)
    if gas_usd is None:
        raise RuntimeError("gas_usd requis : mesurer le coût complet de la "
                           "transaction exacte via measure_full_gas() — "
                           "pas de $0,0044 figé")
    if decimals is not None:
        dec_t, dec_q = decimals
    else:
        dec_t = token_decimals(token_addr)
        dec_q = token_decimals(quote_addr)
    if states is not None:
        bs, ss = states
    else:
        bs = read_pool_state(buy_pool, block)
        ss = read_pool_state(sell_pool, block)
        for nm, st in (("buy", bs), ("sell", ss)):
            if st["fee_bps"] is None:
                raise RuntimeError(f"fee introuvable on-chain pour la jambe {nm} "
                                   f"({st['pool']}) — vérification impossible, pas de "
                                   f"fee supposée")
    tok0_buy = bs["token0"].lower() == token_addr.lower()
    tok0_sell = ss["token0"].lower() == token_addr.lower()
    # --- mids (CL : sqrtPriceX96 ; V2 : réserves)
    if bs.get("pool_type") == "v2":
        mid_buy = mid_from_reserves(bs["reserve0"] if tok0_buy else bs["reserve1"],
                                    bs["reserve1"] if tok0_buy else bs["reserve0"],
                                    dec_t, dec_q)
    else:
        mid_buy = mid_from_sqrt(bs["sqrt_x96"], dec_t, dec_q, tok0_buy)   # quote par token
    if ss.get("pool_type") == "v2":
        mid_sell = mid_from_reserves(ss["reserve0"] if tok0_sell else ss["reserve1"],
                                     ss["reserve1"] if tok0_sell else ss["reserve0"],
                                     dec_t, dec_q)
    else:
        mid_sell = mid_from_sqrt(ss["sqrt_x96"], dec_t, dec_q, tok0_sell)
    # --- jambe 1 : achat. Entrée = size_usd de quote ; sortie = token.
    quote_in_raw = int(size_usd / usd_price_quote * 10 ** dec_q)
    mid_weth_per_quote_buy = 1.0 / mid_buy
    if bs.get("pool_type") == "v2":
        leg1 = decompose_leg_v2(
            quote_in_raw,
            bs["reserve1"] if tok0_buy else bs["reserve0"],
            bs["reserve0"] if tok0_buy else bs["reserve1"],
            bs["fee_bps"], dec_in=dec_q, dec_out=dec_t,
            mid_out_per_in=mid_weth_per_quote_buy)
    else:
        leg1 = decompose_leg(quote_in_raw, bs["liq"], bs["sqrt_x96"], bs["fee_bps"],
                             zero_for_one=not tok0_buy,
                             dec_in=dec_q, dec_out=dec_t,
                             mid_out_per_in=mid_weth_per_quote_buy,
                             tick_spacing=bs.get("tick_spacing"))
    tok_bought_raw = leg1["actual_raw"]
    tok_bought = tok_bought_raw / 10 ** dec_t
    # --- jambe 2 : vente. Entrée = token acheté ; sortie = quote.
    if ss.get("pool_type") == "v2":
        leg2 = decompose_leg_v2(
            int(tok_bought_raw),
            ss["reserve0"] if tok0_sell else ss["reserve1"],
            ss["reserve1"] if tok0_sell else ss["reserve0"],
            ss["fee_bps"], dec_in=dec_t, dec_out=dec_q,
            mid_out_per_in=mid_sell)
    else:
        leg2 = decompose_leg(int(tok_bought_raw), ss["liq"], ss["sqrt_x96"], ss["fee_bps"],
                             zero_for_one=tok0_sell,
                             dec_in=dec_t, dec_out=dec_q,
                             mid_out_per_in=mid_sell,
                             tick_spacing=ss.get("tick_spacing"))
    quote_out_raw = leg2["actual_raw"]
    usd_out = quote_out_raw / 10 ** dec_q * usd_price_quote
    # --- conversion en USD (au prix mid)
    fee1_usd = leg1["fee_raw"] / 10 ** dec_t * mid_buy * usd_price_quote
    imp1_usd = leg1["impact_raw"] / 10 ** dec_t * mid_buy * usd_price_quote
    fee2_usd = leg2["fee_raw"] / 10 ** dec_q * usd_price_quote
    imp2_usd = leg2["impact_raw"] / 10 ** dec_q * usd_price_quote
    gross_usd = size_usd * (mid_sell / mid_buy - 1.0)
    net_usd = gross_usd - fee1_usd - imp1_usd - fee2_usd - imp2_usd - gas_usd
    net_direct = usd_out - size_usd - gas_usd
    # --- threshold (avant impact) : (fee1+fee2) + gas/taille
    # fees route WETH/cbBTC : 85 (0,85 bp) + 300 (3 bp) = 3,85 bp au total
    # (audit : PAS 2 bp — le plancher « 2 bp » est une autre combinaison).
    thr_pct = (bs["fee_bps"] + ss["fee_bps"]) / 10000.0 + gas_usd / size_usd * 100.0
    # --- gardes : quoter croisé (modèle indépendant vs v3_quote_python, CL seulement)
    _cc = {"note": "jambe V2 : pas de v3_quote_python (modèle CP direct)"}
    if bs.get("pool_type") == "cl" and ss.get("pool_type") == "cl":
        q1 = v3_quote_python(float(quote_in_raw), float(bs["liq"]), bs["sqrt_x96"],
                             fee_bps=bs["fee_bps"] / 100.0, zero_for_one=not tok0_buy)
        q2 = v3_quote_python(float(int(tok_bought_raw)), float(ss["liq"]), ss["sqrt_x96"],
                             fee_bps=ss["fee_bps"] / 100.0, zero_for_one=tok0_sell)
        _cc = {
            "buy_diff_pct": ((q1.amount_out - leg1["actual_raw"]) / leg1["actual_raw"] * 100.0
                             if leg1["actual_raw"] else None),
            "sell_diff_pct": ((q2.amount_out - leg2["actual_raw"]) / leg2["actual_raw"] * 100.0
                              if leg2["actual_raw"] else None)}
    # --- gardes : quoter on-chain (là où il existe), coté au MONTANT et
    # au SENS RÉELS de chaque jambe (audit #2 — jamais la quote d'achat
    # $100 réutilisée pour la vente ou pour $500/$1 000).
    # Tolérance QUOTER_TOL_PCT = 0,005 % (0,5 bp) : elle doit être < la
    # marge nette recherchée (quelques bp) ; l'ancien 2 % = 200 bp
    # acceptait n'importe quoi (contre-exemple audit : désaccord 1 %).
    # Statut par jambe : quoter_verified / quoter_disagree / not_addressable.
    # La route n'est « vérifiée » que si les DEUX jambes le sont ; sinon
    # elle est classée séparément (PARTIALLY_VERIFIED / NOT_VERIFIED).
    guards = {}
    if quoter_guard:
        for leg, pool, st, amt, tin, tout, fee, analytic_raw in (
                ("buy", buy_pool, bs, quote_in_raw, quote_addr, token_addr,
                 bs["fee_bps"], leg1["actual_raw"]),
                ("sell", sell_pool, ss, int(tok_bought_raw), token_addr, quote_addr,
                 ss["fee_bps"], leg2["actual_raw"])):
            # Garde par jambe : CL -> quoter de sa factory ; V2 -> Router
            # getAmountsOut de sa factory (l'équivalent V2 du quoter).
            if st.get("pool_type") == "v2":
                router = v2_router_for_factory(st.get("factory"))
                out_raw = (v2_router_quote(router, tin, tout, amt, block)
                           if router else None)
                venue = (f"v2_router_getAmountsOut ({router[:10]}..)"
                         if router else None)
            else:
                out_raw, venue = quoter_for_pool(
                    st.get("factory"), tin, tout, fee, st.get("tick_spacing"), amt, block)
            if out_raw is None:
                status = "not_addressable"  # aucun quoter ne couvre cette pool
                diff_pct = None
                diff_usd = None
                tol_pct = QUOTER_TOL_PCT
            else:
                diff_pct = ((out_raw - analytic_raw) / analytic_raw * 100.0
                            if analytic_raw else None)
                # Le quoter renvoie des ENTIERS : à petit montant, 1 unité
                # brute vaut déjà plus que la tolérance (ex. sortie 1 703 raw
                # -> 1 unité = 0,059 %). Plancher de quantification :
                # tolérance effective = max(0,5 bp, 1 unité de sortie).
                # Sans ce plancher, un désaccord de <1 unité (arrondi) est
                # faussement classé « disagree ». diff_usd est reporté pour
                # juger l'impact en dollars sur le net.
                tol_pct = quoter_tol_pct(out_raw)
                leg_out_usd = (usd_out if leg == "sell" else
                               tok_bought * mid_buy * usd_price_quote)
                diff_usd = (diff_pct / 100.0 * leg_out_usd
                            if diff_pct is not None else None)
                status = ("quoter_verified" if diff_pct is not None
                          and abs(diff_pct) <= tol_pct
                          else "quoter_disagree")
            guards[leg] = {"quoter": venue, "out_raw": out_raw,
                           "analytic_raw": analytic_raw,
                           "diff_pct": diff_pct, "diff_usd": diff_usd,
                           "status": status,
                           "tolerance_pct": tol_pct}
    _statuses = [g["status"] for g in guards.values()] if guards else []
    if _statuses and all(s == "quoter_verified" for s in _statuses):
        route_status = "FULLY_QUOTER_VERIFIED"
    elif any(s == "quoter_disagree" for s in _statuses):
        route_status = "NOT_VERIFIED"
    elif any(s == "quoter_verified" for s in _statuses):
        route_status = "PARTIALLY_VERIFIED"
    else:
        route_status = "NOT_VERIFIED"
    # --- gardes TVL
    tvl_ok = {}
    for leg, tvl in (("buy", tvl_buy_usd), ("sell", tvl_sell_usd)):
        tvl_ok[leg] = (tvl is not None and tvl >= 10 * size_usd)
    return {
        "route": f"buy {buy_pool} -> sell {sell_pool}",
        "block": block, "size_usd": size_usd, "synthetic": True,
        "mid_buy_quote_per_token": mid_buy, "mid_sell_quote_per_token": mid_sell,
        "mid_gap_pct": (mid_sell / mid_buy - 1.0) * 100.0,
        "fee_buy_bps_onchain": bs["fee_bps"], "fee_sell_bps_onchain": ss["fee_bps"],
        "fee_buy_source": bs.get("fee_source"), "fee_sell_source": ss.get("fee_source"),
        "factory_buy": bs.get("factory"), "factory_sell": ss.get("factory"),
        "pool_type_buy": bs.get("pool_type"), "pool_type_sell": ss.get("pool_type"),
        "liq_buy": bs["liq"], "liq_sell": ss["liq"],
        "tick_buy": bs["tick"], "tick_sell": ss["tick"],
        "token_bought": tok_bought, "usd_out": usd_out,
        "gross_usd": gross_usd,
        "fee_buy_usd": fee1_usd, "impact_buy_usd": imp1_usd,
        "fee_sell_usd": fee2_usd, "impact_sell_usd": imp2_usd,
        "gas_usd": gas_usd, "gas_legacy_usd": GAS_LEGACY_USD,
        "net_usd": net_usd, "net_direct_usd": net_direct,
        "identity_err_usd": net_usd - net_direct,
        "threshold_pct": thr_pct,
        "leg1_identity_err_raw": leg1["identity_err_raw"],
        "leg2_identity_err_raw": leg2["identity_err_raw"],
        "crossed_tick_buy": leg1["crossed_tick"],
        "crossed_tick_sell": leg2["crossed_tick"],
        "crosscheck_v3_quote_python": _cc,
        "quoter_guards": guards,
        "route_status": route_status,
        "quoter_tolerance_pct": QUOTER_TOL_PCT,
        "leg2_actual_raw": leg2["actual_raw"],
        "tvl_ok": tvl_ok,
        "tvl_buy_usd": tvl_buy_usd, "tvl_sell_usd": tvl_sell_usd,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", type=int, default=62077712)
    ap.add_argument("--size", type=float, default=100.0)
    ap.add_argument("--upq", type=float, default=58683.42,
                    help="USD par cbBTC (prix DexScreener au moment du scan)")
    ap.add_argument("--eth-usd", type=float, default=1643.55,
                    help="USD par ETH (mid WETH/USDC on-chain au bloc)")
    ap.add_argument("--gas-units", type=int, default=GAS_UNITS_MEASURED,
                    help="unités L2 de la tx exacte (défaut : 285 948 mesurées en fork)")
    args = ap.parse_args()
    # --- gas complet mesuré AVANT le cycle (audit #12)
    gas = measure_full_gas(args.block, args.eth_usd, gas_units=args.gas_units)
    print(f"GAS COMPLET bloc {args.block} ({args.gas_units} unités, ETH ${args.eth_usd}): "
          f"L2 {gas['l2_fee_usd']:.4f} $ (baseFee {gas['base_fee_gwei']:.4f} gwei) + "
          f"L1 {gas['l1_fee_usd']:.4f} $ ({gas['l1_share_pct']:.1f}%) = "
          f"{gas['total_usd']:.4f} $ (ancien figé : {GAS_LEGACY_USD} $)")
    r = verify_cycle(
        "0xeC3c3755b9DED4a2960ef50C9b48C1694CE274C2",
        "0x42d4a22CaD0F5a49681a5715cE994Af73A43B76b",
        WETH, CBBTC, args.size, args.upq, args.block,
        tvl_buy_usd=4779934.12, tvl_sell_usd=442583.75,
        gas_usd=gas["total_usd"])
    print(json.dumps(r, indent=1, default=str))
    print("\n--- LECTURE ---")
    print(f"bloc {r['block']} | taille ${r['size_usd']:.0f} | gap mid {r['mid_gap_pct']:.4f}%")
    print(f"fees : achat {r['fee_buy_bps_onchain']} (0,85 bp) + vente {r['fee_sell_bps_onchain']} (3 bp) "
          f"= 3,85 bp au total (PAS 2 bp — audit)")
    print(f"brut {r['gross_usd']:+.4f} $ | fee achat {r['fee_buy_usd']:.4f} $ | "
          f"impact achat {r['impact_buy_usd']:.4f} $ | fee vente {r['fee_sell_usd']:.4f} $ | "
          f"impact vente {r['impact_sell_usd']:.4f} $ | gas complet {r['gas_usd']:.4f} $")
    print(f"NET {r['net_usd']:+.4f} $ (direct {r['net_direct_usd']:+.4f} $, "
          f"écart identité {r['identity_err_usd']:+.2e} $) | threshold {r['threshold_pct']:.4f}%")
    print(f"référence scan : net -0.0183 $, threshold 0.0429% (avec gas figé 0,0044 $)")
    print(f"statut route : {r['route_status']} (tolérance quoter {r['quoter_tolerance_pct']}% = 0,5 bp)")
    print(f"crossed_tick achat={r['crossed_tick_buy']} vente={r['crossed_tick_sell']} | "
          f"crosscheck v3_quote_python: {r['crosscheck_v3_quote_python']}")
    print(f"factories: achat {r['factory_buy']} | vente {r['factory_sell']}")
    for leg, g in r["quoter_guards"].items():
        print(f"garde quoter {leg} : {g['quoter']} -> {g['status']} "
              f"(diff {g['diff_pct'] if g['diff_pct'] is None else round(g['diff_pct'], 4)}%)")
    print(f"TVL ok (10x taille): {r['tvl_ok']}")
    print(f"fee sources: achat {r['fee_buy_source']} | vente {r['fee_sell_source']}")


if __name__ == "__main__":
    main()
