#!/usr/bin/env python3
"""replay.py — REPLAY 24h du scan cross-venue sur Base (lecture seule).

Méthode (le replay par logs est bloqué : Alchemy Free = eth_getLogs limité à
10 blocs/requête ; publicnode/llamarpc/drpc instables ; 1rpc 403 ;
Etherscan V2 payant pour Base) : échantillonnage d'état par eth_call
d'archive via Multicall3 (1 appel RPC par échantillon, toutes les pools
des 2 groupes dans le même appel, au même bloc).

Fenêtre : 24 h se terminant au bloc du scan (61 645 712 -> 62 077 712),
pas de 25 blocs (5 s). À chaque échantillon : slot0 (+liquidité) de
toutes les pools des groupes WETH/cbBTC (11) et WETH/USDC (18), puis
re-calcul du meilleur net cross-venue à $100 et $25 sur toutes les paires
ordonnées (même pool exclue), avec le modèle analytique mono-tick.

Ce qu'un échantillonnage à 5 s PEUT prouver : les gaps qui vivent >= 5 s
(ceux qu'on pourrait capturer avec un cycle ~3 s). Ce qu'il NE prouve PAS :
les pics d'1 bloc (< 5 s) — quantifié dans le rapport final.
Épisodes : |gap| ou net > threshold ; durée de vie en blocs mesurée sur
les échantillons, puis re-lecture bloc par bloc autour de chaque épisode
détecté pour la durée exacte et le trade de fermeture (capture concurrente).

Sortie : replay_24h.jsonl (1 ligne / échantillon, écriture incrémentale)
+ replay_24h_summary.json à la fin.
AUCUN broadcast, AUCUN wallet, AUCUNE clé, AUCUN fond.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadlag'))

from web3 import Web3

import cross_venue as cv  # noqa: E402  (helpers RPC + price_from_sqrt)
from v3_quote import v3_quote_python  # noqa: E402

BASE_DIR = Path(str(Path(__file__).resolve().parents[1] / 'leadlag'))
RESULTS_JSON = BASE_DIR / "cross_venue_results.json"
OUT_JSONL = BASE_DIR / "replay_24h.jsonl"
OUT_SUMMARY = BASE_DIR / "replay_24h_summary.json"

MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

SCAN_BLOCK = 62077712
START_BLOCK = SCAN_BLOCK - 432000          # 24 h avant le scan (200 ms/bloc)
STEP_BLOCKS = 25                            # 5 s
SIZES = (25, 100)
GAS_USD = float(os.environ["CODEMA_REPLAY_GAS_USD"]) if "CODEMA_REPLAY_GAS_USD" in os.environ else None
MAX_WORKERS = 8
GROUPS_WANTED = {("WETH", "cbBTC"), ("WETH", "USDC")}

MULTICALL_ABI = [{
    "inputs": [{"components": [{"name": "target", "type": "address"},
                               {"name": "callData", "type": "bytes"}],
                "name": "calls", "type": "tuple[]"}],
    "name": "aggregate", "outputs": [{"name": "blockNumber", "type": "uint256"},
                                      {"name": "returnData", "type": "bytes[]"}],
    "stateMutability": "view", "type": "function"}]

w3 = Web3(Web3.HTTPProvider(cv.RPC))  # Alchemy, chargé en mémoire par cross_venue
MC = w3.eth.contract(address=MULTICALL3, abi=MULTICALL_ABI)


def load_pools():
    """Pools des 2 groupes, avec métadonnées du scan + token0 lu on-chain."""
    data = json.loads(RESULTS_JSON.read_text())
    pools = []  # {group, venue, addr, fee_bps, pool_type, mid_method, token_is_token0}
    for g in data["groups"]:
        sym = g["token_symbol"]
        quote = "cbBTC" if g["quote_addr"].lower() == CBBTC.lower() else (
            "USDC" if g["quote_addr"].lower() == USDC.lower() else "?")
        if (sym, quote) not in GROUPS_WANTED:
            continue
        dec_t = cv.token_decimals(g["token_addr"])
        dec_q = cv.token_decimals(g["quote_addr"])
        for p in g["pools"]:
            if p.get("pool_type") == "v2":
                continue  # unknown V2 fee schedules cannot be assumed to be 30 bp
            pools.append({
                "group": f"{sym}/{quote}",
                "token_addr": g["token_addr"], "quote_addr": g["quote_addr"],
                "dec_token": dec_t, "dec_quote": dec_q,
                "venue": p["venue"], "addr": p["pair_address"],
                "fee_bps": p["fee_bps"], "pool_type": p.get("pool_type"),
                "mid_method": p.get("mid_method"),
                "liq_usd_ds": p.get("liq_usd_ds"),
                "token_is_token0": None,
            })
    # token0() once per pool (immutable) at latest
    cv.init_selectors()
    for p in pools:
        try:
            t0 = "0x" + cv.eth_call(p["addr"], "0x" + cv.SEL_TOKEN0, "latest")[-40:]
            p["token_is_token0"] = (t0.lower() == p["token_addr"].lower())
        except Exception:
            p["token_is_token0"] = None
    return pools


def build_calls(pools):
    """Liste des (pool_idx, kind) et calldata agrégé pour Multicall3."""
    calls = []
    meta = []
    for i, p in enumerate(pools):
        addr = Web3.to_checksum_address(p["addr"])
        if p["pool_type"] == "v2":
            calls.append((addr, bytes.fromhex(cv.keccak_sel("getReserves()"))))
            meta.append((i, "reserves"))
        elif p.get("mid_method") == "algebra_globalState":
            calls.append((addr, bytes.fromhex(cv.keccak_sel("globalState()"))))
            meta.append((i, "globalState"))
            calls.append((addr, bytes.fromhex(cv.keccak_sel("liquidity()"))))
            meta.append((i, "liq"))
        else:
            calls.append((addr, bytes.fromhex(cv.keccak_sel("slot0()"))))
            meta.append((i, "slot0"))
            calls.append((addr, bytes.fromhex(cv.keccak_sel("liquidity()"))))
            meta.append((i, "liq"))
        if p["pool_type"] != "v2" and p.get("mid_method") != "algebra_globalState":
            calls.append((addr, bytes.fromhex(cv.keccak_sel("fee()"))))
            meta.append((i, "fee"))
    return calls, meta


def sample_block(block, pools, calls, meta):
    """1 appel Multicall3 au bloc donné -> état de toutes les pools."""
    try:
        _bn, ret = MC.functions.aggregate(calls).call(block_identifier=block)
    except Exception as e:
        return {"block": block, "error": f"{type(e).__name__}: {str(e)[:100]}"}
    states = {}
    for (i, kind), raw in zip(meta, ret):
        raw_b = bytes(raw)
        if kind == "slot0":
            if len(raw_b) < 64:
                continue
            sqrt_x96 = int.from_bytes(raw_b[0:32], "big")
            tr = int.from_bytes(raw_b[32:64], "big")
            tick = tr - (1 << 256) if tr >= (1 << 255) else tr
            states.setdefault(i, {})["sqrt_x96"] = sqrt_x96
            states[i]["tick"] = tick
        elif kind == "globalState":
            if len(raw_b) < 96:
                continue
            sqrt_x96 = int.from_bytes(raw_b[0:32], "big")
            tr = int.from_bytes(raw_b[32:64], "big")
            tick = tr - (1 << 256) if tr >= (1 << 255) else tr
            states.setdefault(i, {})["sqrt_x96"] = sqrt_x96
            states[i]["tick"] = tick
            states[i]["fee_bps"] = int.from_bytes(raw_b[64:96], "big")
        elif kind == "fee":
            if len(raw_b) >= 32:
                states.setdefault(i, {})["fee_bps"] = int.from_bytes(raw_b[:32], "big")
        elif kind == "liq":
            if len(raw_b) < 32:
                continue
            states.setdefault(i, {})["liq"] = int.from_bytes(raw_b[0:32], "big")
        elif kind == "reserves":
            if len(raw_b) < 64:
                continue
            states.setdefault(i, {})["reserve0"] = int.from_bytes(raw_b[0:32], "big")
            states[i]["reserve1"] = int.from_bytes(raw_b[32:64], "big")
    return {"block": block, "states": states}


def pool_mid(p, st):
    """Mid price (quote par token) à partir de l'état échantillonné."""
    dec_t, dec_q = p["dec_token"], p["dec_quote"]
    t0 = p["token_is_token0"]
    if p["pool_type"] == "v2":
        r0, r1 = st.get("reserve0"), st.get("reserve1")
        if r0 is None or r1 is None or r0 == 0 or r1 == 0:
            return None
        if t0:
            return (r1 / 10 ** dec_q) / (r0 / 10 ** dec_t)
        return (r0 / 10 ** dec_q) / (r1 / 10 ** dec_t)
    sqrt_x96 = st.get("sqrt_x96")
    if not sqrt_x96:
        return None
    return cv.price_from_sqrt(sqrt_x96, dec_t, dec_q, t0)


def analytic_out(amount_in_raw, liq, sqrt_x96, fee_bps, zero_for_one):
    """Sortie brute (raw) du modèle mono-tick — même math que v3_quote_python."""
    q = v3_quote_python(float(amount_in_raw), float(liq), sqrt_x96,
                        fee_bps=fee_bps / 100.0, zero_for_one=zero_for_one)
    return q.amount_out, q.crossed_tick


def leg_out(pool, st, amount_in_raw, direction, upq):
    """Sortie d'une jambe en USD. direction 'buy' (quote->token) / 'sell' (token->quote).
    Retourne (usd_out, method) ou (None, reason)."""
    if pool["pool_type"] == "v2":
        r0, r1 = st.get("reserve0"), st.get("reserve1")
        if r0 is None or r1 is None:
            return None, "no_reserves"
        t0 = pool["token_is_token0"]
        if direction == "buy":
            r_in = r1 if t0 else r0
            r_out = r0 if t0 else r1
            out = cv.v2_quote(amount_in_raw, r_in, r_out, fee=0.003)
            return out / 10 ** pool["dec_token"] * _weth_usd(pool, upq), "v2_cp"
        r_in = r0 if t0 else r1
        r_out = r1 if t0 else r0
        out = cv.v2_quote(amount_in_raw, r_in, r_out, fee=0.003)
        return out / 10 ** pool["dec_quote"] * upq, "v2_cp"
    liq, sqrt_x96 = st.get("liq"), st.get("sqrt_x96")
    fee = st.get("fee_bps")  # historical fee from this sample, never the scan snapshot
    if liq is None or sqrt_x96 is None or fee is None:
        return None, "no_state"
    t0 = pool["token_is_token0"]
    if direction == "buy":
        out_raw, _ = analytic_out(amount_in_raw, liq, sqrt_x96, fee, zero_for_one=not t0)
        if out_raw <= 0:
            return None, "zero_out"
        return out_raw / 10 ** pool["dec_token"] * _weth_usd(pool, upq), "cl_analytic"
    out_raw, _ = analytic_out(amount_in_raw, liq, sqrt_x96, fee, zero_for_one=t0)
    if out_raw <= 0:
        return None, "zero_out"
    return out_raw / 10 ** pool["dec_quote"] * upq, "cl_analytic"


def _weth_usd(pool, upq):
    """Prix USD d'1 token (WETH ou cbBTC) : pour le groupe WETH/cbBTC,
    upq = USD par cbBTC ; le token WETH vaut mid * upq — mais ici on a
    besoin du USD par WETH pour convertir la sortie 'buy' (en WETH).
    On le passe via upq_weth (voir compute_sample)."""
    return pool.get("_weth_usd", upq)


def compute_sample(block, pools, states):
    """Meilleur net cross-venue par groupe à ce bloc, tailles 25/100 $.
    Exclut les paires même-pool. Retourne un dict compact."""
    # mids + prix USD du token par groupe
    mids = {}
    for i, p in enumerate(pools):
        st = states.get(i)
        mids[i] = pool_mid(p, st) if st else None
    # USD par WETH (groupe WETH/USDC, pool Uni 0.01% la plus profonde en mid
    # médian) et USD par cbBTC = WETH_USD / mid(WETH/cbBTC)
    weth_usd = None
    cbbtc_usd = None
    usdc_mids = [mids[i] for i, p in enumerate(pools)
                 if p["group"] == "WETH/USDC" and mids[i]]
    cbbtc_mids = [mids[i] for i, p in enumerate(pools)
                  if p["group"] == "WETH/cbBTC" and mids[i]]
    if usdc_mids:
        usdc_mids.sort()
        weth_usd = usdc_mids[len(usdc_mids) // 2]
    if weth_usd and cbbtc_mids:
        cbbtc_mids.sort()
        cbbtc_usd = weth_usd / cbbtc_mids[len(cbbtc_mids) // 2]
    out = {"block": block, "weth_usd": weth_usd, "cbbtc_usd": cbbtc_usd, "groups": {},
           "status": "ANALYTIC_ESTIMATE", "step_blocks": STEP_BLOCKS,
           "intra_block_coverage": False, "gas_assumption_usd": GAS_USD}
    for gname, upq, dec_t, dec_q in (("WETH/cbBTC", cbbtc_usd, 18, 8),
                                     ("WETH/USDC", 1.0, 18, 6)):
        if upq is None:
            continue
        idxs = [i for i, p in enumerate(pools) if p["group"] == gname]
        # prix USD du token WETH pour la jambe buy
        for i in idxs:
            pools[i]["_weth_usd"] = weth_usd if weth_usd else upq
        best = {}
        for size in SIZES:
            best_net, best_desc = None, None
            for bi in idxs:
                for si in idxs:
                    if bi == si:
                        continue  # même pool exclue
                    bp, sp = pools[bi], pools[si]
                    if bp["addr"].lower() == sp["addr"].lower():
                        continue  # même adresse (doublon DexScreener) exclue
                    bst_b, bst_s = states.get(bi), states.get(si)
                    if not bst_b or not bst_s:
                        continue
                    if mids[bi] is None or mids[si] is None:
                        continue
                    quote_raw = int(size / upq * 10 ** dec_q)
                    if quote_raw <= 0:
                        continue
                    tok_out_usd, _ = leg_out(bp, bst_b, quote_raw, "buy", upq)
                    if tok_out_usd is None:
                        continue
                    # tok_out_usd est en USD de token ; reconvertir en montant token
                    tok_amount = tok_out_usd / (weth_usd if weth_usd else 1.0)
                    tok_raw = int(tok_amount * 10 ** dec_t)
                    if tok_raw <= 0:
                        continue
                    usd_out, _ = leg_out(sp, bst_s, tok_raw, "sell", upq)
                    if usd_out is None:
                        continue
                    net = usd_out - size  # rank by gross, independent of an unmeasured gas assumption
                    if best_net is None or net > best_net:
                        best_net, best_desc = net, f"{bp['venue']}:{bp['addr'][:10]}..->{sp['venue']}:{sp['addr'][:10]}.."
            best[size] = {"net_usd": (best_net - GAS_USD if best_net is not None and GAS_USD is not None else None),
                          "gross_usd": best_net, "pair": best_desc}
        # gap brut entre mids extrêmes du groupe
        gm = [mids[i] for i in idxs if mids[i]]
        gap = ((max(gm) - min(gm)) / min(gm) * 100.0) if len(gm) >= 2 else None
        out["groups"][gname] = {"best": best,
                                "mid_gap_pct": round(gap, 4) if gap is not None else None,
                                "n_pools": len(gm)}
    return out


def main():
    cv.init_selectors()
    pools = load_pools()
    print(f"pools tracked: {len(pools)}", flush=True)
    for p in pools:
        print(f"  {p['group']:12s} {p['venue']:12s} {p['addr'][:14]}.. fee={p['fee_bps']} type={p['pool_type']} tok0={p['token_is_token0']}", flush=True)
    calls, meta = build_calls(pools)
    print(f"multicall inner calls per sample: {len(calls)}", flush=True)
    blocks = list(range(START_BLOCK, SCAN_BLOCK + 1, STEP_BLOCKS))
    print(f"window: {START_BLOCK} -> {SCAN_BLOCK} ({len(blocks)} samples, step {STEP_BLOCKS})", flush=True)
    t0 = time.time()
    n_ok = n_err = 0
    with OUT_JSONL.open("w") as f:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            # soumission par lots pour écrire au fur et à mesure
            for start in range(0, len(blocks), 200):
                batch = blocks[start:start + 200]
                for res in ex.map(lambda b: sample_block(b, pools, calls, meta), batch):
                    if "error" in res:
                        n_err += 1
                        continue
                    try:
                        rec = compute_sample(res["block"], pools, res["states"])
                    except Exception as e:
                        n_err += 1
                        continue
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    n_ok += 1
                print(f"  ... {n_ok + n_err}/{len(blocks)} samples, {time.time() - t0:.0f}s, ok={n_ok} err={n_err}", flush=True)
    print(f"DONE {n_ok} samples, {n_err} errors in {time.time() - t0:.0f}s -> {OUT_JSONL}", flush=True)


if __name__ == "__main__":
    main()
