#!/usr/bin/env python3
"""
triangle_detector.py — Détecteur d'arbitrage TRIANGULAIRE sur Polygon (v4.1).

PRIORITÉ d'Ismail : les triples de GROSSES pools (profondeur réelle).
Prior honnête (deep research du projet) : le triangle est le plus souvent
« textbook-only » — les spreads sur 3 paires d'une même venue sont
arbitrés en millisecondes et survivent rarement aux frais. On MESURE.

Cycles évalués (les deux sens) :
  WMATIC -> USDC.e -> USDT -> WMATIC
  WMATIC -> USDC.e -> WETH  -> WMATIC
  WMATIC -> USDT   -> WETH  -> WMATIC
(chaque cycle est aussi évalué dans le sens inverse.)

Méthode par cycle et par taille (1 000 $, 5 000 $, 20 000 $) :
  - chaque jambe est cotée on-chain sur la MEILLEURE venue de la paire
    (QuoterV2 pour Uni V3, getAmountsOut pour V2, réserves virtuelles
    pour Algebra) — le montant d'entrée de chaque jambe est la sortie
    réelle de la jambe précédente (pas une taille fixe) ;
  - frais de swap comptés sur CHAQUE jambe (dans les quotes) ;
  - net = (montant final - montant initial) en $ - gas - budget revert
    (gas budgété 600 000 unités — 3 swaps + flash loan ; flash fee 0 %
    Morpho). Règle v4.1 : opportunité ssi net > 0 $ ; tranches
    >0$ / ≥0,50$ / ≥3$ rapportées.

MODE MONITOR-ONLY (par défaut et pour l'instant le seul) :
  ce script est LECTURE SEULE — il ne contient AUCUN code de broadcast,
  aucune clé, aucun contrat. Il scanne les cycles et LOGUE toute
  opportunité à net > 0 $. Il ne peut pas exécuter, par construction.
  Il ne deviendrait exécutable que si un triangle franchit net > 0 $
  de façon répétée ET qu'une preuve fork (WIN) existe — avec les mêmes
  guards que le bot principal (kill switch, float ledger, max 10 %).

Usage :
  python3 triangle_detector.py [--samples N] [--interval S]
  Sortie : triangle_measurement_<ts>.json + triangle_samples.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import big_pools as bp  # noqa: E402
from polygon_gas import read_gas_price_gwei  # noqa: E402
from polygon_guard import tranche  # noqa: E402

TRIANGLE_GAS_UNITS = 600_000  # 3 swaps + flash loan + callback (estimation)
START_SIZES_USD = [1_000.0, 5_000.0, 20_000.0]

# Triples de grosses pools (ordre = sens direct ; l'inverse est évalué aussi).
TRIPLES = [
    ("WMATIC", "USDC.e", "USDT"),
    ("WMATIC", "USDC.e", "WETH"),
    ("WMATIC", "USDT", "WETH"),
]

MODE = "MONITOR-ONLY"  # jamais d'exécution — lecture seule par construction


def triangle_net_usd(start_usd: float, final_usd: float,
                     gas_usd: float, revert_budget_usd: float = None) -> dict:
    """Math pure du cycle : net après TOUS les coûts (règle v4.1)."""
    if revert_budget_usd is None:
        revert_budget_usd = gas_usd  # pire cas : gas + gas de revert
    gross = final_usd - start_usd
    total_cost = gas_usd + revert_budget_usd
    net = gross - total_cost
    return {"gross_usd": round(gross, 4), "gas_usd": round(gas_usd, 6),
            "revert_budget_usd": round(revert_budget_usd, 6),
            "total_cost_usd": round(total_cost, 6),
            "net_usd": round(net, 4), "action": "LOG" if net > 0 else "SKIP",
            "tranche": tranche(net)}


def classify_venues(w3, pair):
    """Venues classées on-chain pour une paire (mise en cache par l'appelant)."""
    venues = bp.discover_venues(pair)
    if not venues:
        venues = [{"dex": d, "pair": p, "liq_usd": None}
                  for d, p in bp.STATIC_VENUES.get(pair, [])]
    out = []
    for v in venues:
        kind = bp.classify_pool(w3, v["pair"])
        if kind == "unknown":
            continue
        router = None
        if kind == "v2":
            router = (bp.QUICKSWAP_V2_ROUTER if v["dex"] == "quickswap"
                      else bp.SUSHI_V2_ROUTER if v["dex"] == "sushiswap"
                      else None)
        out.append({**v, "kind": kind, "router": router})
    return out


def best_leg(w3, venues, token_in, token_out, amount_in_raw):
    """Meilleure venue pour une jambe : quote on-chain, max output.
    token_in / token_out = SYMBOLES (ex. 'WMATIC') — les adresses sont
    résolues ici (venue_reserves attend des symboles)."""
    addr_in = bp.TOKENS[token_in][0]
    addr_out = bp.TOKENS[token_out][0]
    best = None
    for v in venues:
        try:
            reserves = None
            if v["kind"] in ("v2", "algebra") and v["router"] is None:
                r_in, r_out, fee = bp.venue_reserves(
                    w3, v["kind"], v["pair"], token_in, token_out)
                reserves = (r_in, r_out, fee)
            out_raw, method = bp.quote_venue(
                w3, v["kind"], v["pair"], addr_in, addr_out,
                amount_in_raw, v["router"], reserves)
            if best is None or out_raw > best[0]:
                best = (out_raw, v, method)
        except Exception as e:  # noqa: BLE001 — une venue en panne ne tue pas le cycle
            v.setdefault("errors", []).append(str(e)[:100])
            continue
    return best


def evaluate_cycle(w3, tokens, start_usd, gas_gwei, matic_price,
                   prices_usd, venue_cache):
    """Évalue un cycle A -> B -> C -> A (montants réels, jambe par jambe)."""
    a, b, c = tokens
    dec = {t: bp.TOKENS[t][1] for t in tokens}
    amt_in = int((start_usd / prices_usd[a]) * 10**dec[a])
    legs = []
    cur_tok, cur_amt = a, amt_in
    for nxt in (b, c, a):
        pair = (cur_tok, nxt)
        if pair not in venue_cache:
            venue_cache[pair] = classify_venues(w3, pair)
        venues = venue_cache[pair]
        if not venues:
            return {"cycle": " -> ".join(tokens + (a,)), "start_usd": start_usd,
                    "error": f"aucune venue pour {cur_tok}/{nxt}"}
        best = best_leg(w3, venues, cur_tok, nxt, cur_amt)
        if best is None:
            return {"cycle": " -> ".join(tokens + (a,)), "start_usd": start_usd,
                    "error": f"aucune quote pour {cur_tok}->{nxt}"}
        out_raw, venue, method = best
        legs.append({"from": cur_tok, "to": nxt,
                     "amount_in": cur_amt / 10**dec[cur_tok],
                     "amount_out": out_raw / 10**dec[nxt],
                     "dex": venue["dex"], "kind": venue["kind"],
                     "method": method})
        cur_tok, cur_amt = nxt, out_raw
    final_usd = cur_amt / 10**dec[a] * prices_usd[a]
    gas_usd = TRIANGLE_GAS_UNITS * gas_gwei * 1e-9 * matic_price
    net = triangle_net_usd(start_usd, final_usd, gas_usd)
    return {"cycle": " -> ".join(tokens + (a,)), "start_usd": start_usd,
            "final_usd": round(final_usd, 4), "legs": legs,
            "gas_gwei": round(gas_gwei, 2), "net": net}


def measure_all():
    w3 = bp.connect()
    gas_gwei = read_gas_price_gwei()
    prices_usd = bp.reference_prices_usd()
    matic_price = prices_usd["WMATIC"]
    venue_cache = {}
    ts = datetime.now(timezone.utc)
    sample = {"date": ts.isoformat(), "chain": "polygon", "chain_id": 137,
              "block": w3.eth.block_number, "mode": MODE,
              "gas_price_gwei": round(gas_gwei, 2),
              "triangle_gas_units": TRIANGLE_GAS_UNITS,
              "reference_prices_usd": prices_usd,
              "cycles": []}
    for triple in TRIPLES:
        for direction in (triple, (triple[0], triple[2], triple[1])):
            for size in START_SIZES_USD:
                try:
                    res = evaluate_cycle(w3, direction, size, gas_gwei,
                                         matic_price, prices_usd, venue_cache)
                except Exception as e:  # noqa: BLE001
                    res = {"cycle": " -> ".join(direction + (direction[0],)),
                           "start_usd": size, "error": str(e)[:200]}
                sample["cycles"].append(res)
                if "net" in res:
                    print(f"  {res['cycle']} ${size:,.0f} : "
                          f"net {res['net']['net_usd']:+.4f}$ "
                          f"({res['net']['tranche']}, {res['net']['action']})")
                else:
                    print(f"  {res['cycle']} ${size:,.0f} : "
                          f"ERREUR {res.get('error', '?')[:100]}")
    return sample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--out", type=str, default="triangle_samples.jsonl")
    args = ap.parse_args()
    assert MODE == "MONITOR-ONLY", "ce script ne doit jamais exécuter"
    for i in range(args.samples):
        print(f"=== Triangle échantillon {i + 1}/{args.samples} "
              f"({datetime.now(timezone.utc).isoformat()}) — {MODE} ===")
        sample = measure_all()
        with open(args.out, "a") as f:
            f.write(json.dumps(sample) + "\n")
        fname = ("triangle_measurement_"
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M')}.json")
        Path(fname).write_text(json.dumps(sample, indent=2))
        print(f"Échantillon sauvé : {fname} (+ {args.out})")
        if i + 1 < args.samples:
            print(f"Attente {args.interval}s…")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
