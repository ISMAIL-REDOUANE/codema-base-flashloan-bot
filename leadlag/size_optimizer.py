#!/usr/bin/env python3
"""size_optimizer.py — OPTIMISATION DES TAILLES $1 -> $1000 sur les 3
meilleures routes du scan cross-venue (Base, bloc du scan 62 077 712).

Pour chaque route : cycle atomique complet simulé à chaque taille
(emprunt flash Morpho 0% -> achat jambe 1 -> vente jambe 2 ->
remboursement), avec les quotes d'exécution (modèle analytique mono-tick,
validé à 0,0% contre v3_quote_python et à -0,0001% contre le quoter
Aerodrome sur la jambe de vente — voir route_verify.py), et le profit
APRÈS TOUS les coûts (fees des deux tiers réels + impact des deux jambes
+ gas $0,0044). AUCUN seuil fixe supposé, AUCUN profit garanti.

Sélection des routes : meilleur net VÉRIFIÉ à $100 du scan, paires
même-pool EXCLUES (un aller-retour dans la même pool n'est pas de
l'arbitrage — c'est la perte minimale possible).
Garde TVL : TVL >= 10x la taille sur chaque jambe, sinon la taille est
marquée NON VÉRIFIÉE (modèle mono-tick fragile sur liquidité ~1 tick).
Garde quoter : re-vérifiée au quoter on-chain à la taille optimale
(là où un quoter adresse la pool).

TOUT EST SYNTHÉTIQUE (quotes, jamais exécuté, jamais un profit).
Lecture seule on-chain ; AUCUN broadcast, AUCUN wallet, AUCUNE clé.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadlag'))

import cross_venue as cv  # noqa: E402
import route_verify as rv  # noqa: E402

BASE_DIR = Path(str(Path(__file__).resolve().parents[1] / 'leadlag'))
RESULTS_JSON = BASE_DIR / "cross_venue_results.json"
OUT_JSON = BASE_DIR / "size_optimizer_results.json"
SCAN_BLOCK = 62077712
SIZES = [1, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000]
TARGET_GROUPS = ["WETH/cbBTC", "WETH/USDC", "cbBTC/USDC"]


def select_best_pairs():
    """Meilleure paire vérifiée par groupe (hors même-pool), depuis le scan."""
    data = json.loads(RESULTS_JSON.read_text())
    routes = {}
    for g in data["groups"]:
        sym = g["token_symbol"]
        qaddr = g["quote_addr"].lower()
        quote = ("cbBTC" if qaddr == rv.CBBTC.lower() else
                 "USDC" if qaddr == cv.USDC.lower() else "?")
        gname = f"{sym}/{quote}"
        if gname not in TARGET_GROUPS:
            continue
        best = None
        for tp in g.get("tier_pairs", []):
            # net VÉRIFIÉ (quoter on-chain) à $100 ; même-pool exclue
            if not tp.get("verified"):
                continue
            if tp.get("size_usd") != 100:
                continue
            if tp["buy_pair"].lower() == tp["sell_pair"].lower():
                continue  # même pool : pas de l'arbitrage
            if best is None or tp["net_usd"] > best["net_usd"]:
                best = tp
        if best is None:
            continue
        pools = {p["pair_address"].lower(): p for p in g["pools"]}
        routes[gname] = {
            "token_addr": g["token_addr"], "quote_addr": g["quote_addr"],
            "usd_price_quote": g["usd_price_quote"],
            "buy_pool": best["buy_pair"], "sell_pool": best["sell_pair"],
            "buy_venue": best["buy_venue"], "sell_venue": best["sell_venue"],
            "buy_fee_bps": best["buy_fee_bps"], "sell_fee_bps": best["sell_fee_bps"],
            "scan_net_100": best["net_usd"],
            "scan_threshold_pct": best["threshold_pct"],
            "tvl_buy_usd": pools[best["buy_pair"].lower()].get("liq_usd_ds"),
            "tvl_sell_usd": pools[best["sell_pair"].lower()].get("liq_usd_ds"),
            "buy_pool_type": pools[best["buy_pair"].lower()].get("pool_type"),
            "sell_pool_type": pools[best["sell_pair"].lower()].get("pool_type"),
        }
    return routes


def main():
    cv.init_selectors()
    routes = select_best_pairs()
    print("ROUTES SÉLECTIONNÉES (meilleur net vérifié à $100, hors même-pool) :")
    for gname, r in routes.items():
        print(f"  {gname}: {r['buy_venue']} {r['buy_pool'][:12]}.. "
              f"(fee {r['buy_fee_bps']}, TVL ${r['tvl_buy_usd']:,.0f}) -> "
              f"{r['sell_venue']} {r['sell_pool'][:12]}.. "
              f"(fee {r['sell_fee_bps']}, TVL ${r['tvl_sell_usd']:,.0f}) | "
              f"scan net $100 = {r['scan_net_100']:+.4f} $ | "
              f"threshold {r['scan_threshold_pct']:.4f}% | "
              f"types {r['buy_pool_type']}/{r['sell_pool_type']}")
    out = {"scan_block": SCAN_BLOCK, "synthetic": True, "routes": {}}
    # --- gas complet mesuré UNE fois (audit #12) : même tx, même coût
    # pour toutes les tailles (les unités ne dépendent pas du montant).
    eth_usd = 1643.55  # mid WETH/USDC on-chain au bloc du scan
    gas = rv.measure_full_gas(SCAN_BLOCK, eth_usd)
    gas_prudent = rv.measure_full_gas(SCAN_BLOCK, eth_usd,
                                      gas_units=rv.GAS_UNITS_PRUDENT)
    print(f"GAS COMPLET bloc {SCAN_BLOCK} : {gas['total_usd']:.4f} $ "
          f"(L2 {gas['l2_fee_usd']:.4f} $ + L1 {gas['l1_fee_usd']:.4f} $ "
          f"= {gas['l1_share_pct']:.1f}% L1, baseFee {gas['base_fee_gwei']:.4f} gwei, "
          f"{gas['gas_units']} unités) | prudent {gas_prudent['total_usd']:.4f} $ "
          f"({gas_prudent['gas_units']} unités) | ancien figé {rv.GAS_LEGACY_USD} $")
    out["gas_full"] = gas
    out["gas_prudent"] = gas_prudent
    for gname, r in routes.items():
        if r["buy_pool_type"] != "cl" or r["sell_pool_type"] != "cl":
            print(f"  !! {gname} : jambe non-CL ({r['buy_pool_type']}/{r['sell_pool_type']}) "
                  f"— modèle V2 non implémenté dans route_verify, route ignorée")
            out["routes"][gname] = {"skipped": "non-CL leg", **r}
            continue
        bs = rv.read_pool_state(r["buy_pool"], SCAN_BLOCK)
        ss = rv.read_pool_state(r["sell_pool"], SCAN_BLOCK)
        states = (bs, ss)
        print(f"\n{gname} — fees on-chain : achat {bs['fee_bps']} "
              f"(scan {r['buy_fee_bps']}), vente {ss['fee_bps']} (scan {r['sell_fee_bps']})")
        rows = []
        for size in SIZES:
            res = rv.verify_cycle(r["buy_pool"], r["sell_pool"],
                                  r["token_addr"], r["quote_addr"],
                                  float(size), r["usd_price_quote"], SCAN_BLOCK,
                                  tvl_buy_usd=r["tvl_buy_usd"],
                                  tvl_sell_usd=r["tvl_sell_usd"],
                                  states=states, quoter_guard=False,
                                  gas_usd=gas["total_usd"])
            tvl_ok = res["tvl_ok"]["buy"] and res["tvl_ok"]["sell"]
            rows.append({
                "size_usd": size, "net_usd": res["net_direct_usd"],
                "net_decomposed_usd": res["net_usd"],
                "gross_usd": res["gross_usd"],
                "fee_buy_usd": res["fee_buy_usd"], "impact_buy_usd": res["impact_buy_usd"],
                "fee_sell_usd": res["fee_sell_usd"], "impact_sell_usd": res["impact_sell_usd"],
                "gas_usd": res["gas_usd"], "threshold_pct": res["threshold_pct"],
                "mid_gap_pct": res["mid_gap_pct"],
                "crossed_tick_buy": res["crossed_tick_buy"],
                "crossed_tick_sell": res["crossed_tick_sell"],
                "tvl_ok_10x": tvl_ok,
            })
            print(f"  ${size:>5}: net {res['net_direct_usd']:+8.4f} $ | brut {res['gross_usd']:+7.4f} | "
                  f"fees {res['fee_buy_usd'] + res['fee_sell_usd']:7.4f} | "
                  f"impact {res['impact_buy_usd'] + res['impact_sell_usd']:7.4f} | "
                  f"gas {res['gas_usd']:.4f} | thr {res['threshold_pct']:.4f}% | "
                  f"TVL10x={'OK' if tvl_ok else 'NON'} | tickX={res['crossed_tick_buy'] or res['crossed_tick_sell']}")
        best_row = max(rows, key=lambda x: x["net_usd"])
        # garde quoter à la taille optimale ET à $100 (référence — à $1 la
        # quote est limitée par la quantification : 1 unité brute = 0,06 %).
        # Chaque jambe au montant et au sens réels, tolérance 0,5 bp (audit #2).
        def _quoter_at(size):
            rr = rv.verify_cycle(r["buy_pool"], r["sell_pool"],
                                 r["token_addr"], r["quote_addr"],
                                 float(size), r["usd_price_quote"],
                                 SCAN_BLOCK, tvl_buy_usd=r["tvl_buy_usd"],
                                 tvl_sell_usd=r["tvl_sell_usd"],
                                 states=states, quoter_guard=True,
                                 gas_usd=gas["total_usd"])
            return rr["route_status"], rr["quoter_guards"], rr["net_direct_usd"]
        status_opt, qg_opt, _ = _quoter_at(best_row["size_usd"])
        status_100, qg_100, net_100 = _quoter_at(100)
        out["routes"][gname] = {**r, "grid": rows,
                                "optimal_size_usd": best_row["size_usd"],
                                "optimal_net_usd": best_row["net_usd"],
                                "route_status": status_opt,
                                "quoter_guard_at_optimal": qg_opt,
                                "route_status_100": status_100,
                                "quoter_guard_at_100": qg_100,
                                "net_100_usd": net_100}
        def _fmt(qg):
            return " ; ".join(
                f"{leg}={g['status']} (diff "
                f"{'n/a' if g['diff_pct'] is None else f'{g['diff_pct']:+.4f}%'}"
                f"{'' if g['quoter'] else ', pas de quoter'})"
                for leg, g in qg.items())
        print(f"  => TAILLE OPTIMALE {gname} : ${best_row['size_usd']} -> "
              f"net {best_row['net_usd']:+.4f} $ | statut {status_opt} | "
              f"quoter: {_fmt(qg_opt)}")
        print(f"     À $100 : net {net_100:+.4f} $ | statut {status_100} | "
              f"quoter: {_fmt(qg_100)}")
    OUT_JSON.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nÉcrit : {OUT_JSON}")


if __name__ == "__main__":
    main()
