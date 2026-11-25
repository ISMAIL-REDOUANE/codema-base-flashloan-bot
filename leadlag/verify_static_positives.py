#!/usr/bin/env python3
"""verify_static_positives.py — Vérifie les 11 échantillons positifs du
replay dont les DEUX jambes sont à fees STATIQUES (Uni/Cake), avec
route_verify (fees on-chain au bloc, cycle complet, gardes quoter).
Les autres positifs impliquent une pool Aerodrome à fee DYNAMIQUE et sont
des faux positifs (fee du scan réutilisée) — démontré par E1/E2.
"""
import sys, json
sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")
sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")
import route_verify as rv

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

d = json.load(open("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag/cross_venue_results.json"))
addr_of = {}
tvl_of = {}
for g in d["groups"]:
    for p in g["pools"]:
        addr_of[p["pair_address"].lower()[:10]] = p["pair_address"]
        tvl_of[p["pair_address"].lower()[:10]] = p.get("liq_usd_ds")
venue_of = {}
for g in d["groups"]:
    for p in g["pools"]:
        venue_of[p["pair_address"].lower()[:10]] = p["venue"]
STATIC = {"uniswap", "pancakeswap"}

recs = [json.loads(l) for l in open("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag/replay_24h.jsonl")]
events = []
for r in recs:
    b = r["groups"]["WETH/USDC"]["best"]["100"]
    if not b.get("net_usd") or b["net_usd"] <= 0:
        continue
    pair = b["pair"]
    buy10 = pair.split("->")[0].split(":")[1][:10].lower()
    sell10 = pair.split("->")[1].split(":")[1][:10].lower()
    if venue_of.get(buy10) in STATIC and venue_of.get(sell10) in STATIC:
        events.append((r["block"], b["net_usd"], buy10, sell10, pair))
events.sort(key=lambda x: -x[1])
print(f"{len(events)} événements statiques à vérifier")
results = []
for block, replay_net, buy10, sell10, pair in events:
    buy, sell = addr_of[buy10], addr_of[sell10]
    try:
        gas = rv.measure_full_gas(block, 1643.55)
        r = rv.verify_cycle(buy, sell, WETH, USDC, 100.0, 1.0, block,
                            tvl_buy_usd=tvl_of[buy10], tvl_sell_usd=tvl_of[sell10],
                            gas_usd=gas["total_usd"])
    except Exception as e:  # noqa: BLE001 — on enregistre, on ne plante pas
        print(f"bloc {block} replay {replay_net:+.4f} $ -> ERREUR : {type(e).__name__}: {str(e)[:120]} | {pair}")
        results.append({"block": block, "replay_net_usd": replay_net,
                        "verified_net_usd": None, "error": f"{type(e).__name__}: {str(e)[:120]}",
                        "pair": pair})
        continue
    ok = r["route_status"] == "FULLY_QUOTER_VERIFIED"
    print(f"bloc {block} replay {replay_net:+.4f} $ -> VÉRIFIÉ {r['net_direct_usd']:+.4f} $ "
          f"| gap {r['mid_gap_pct']:.4f}% | fees {r['fee_buy_bps_onchain']}+{r['fee_sell_bps_onchain']} | "
          f"statut {r['route_status']} | {pair}")
    results.append({"block": block, "replay_net_usd": replay_net,
                    "verified_net_usd": r["net_direct_usd"],
                    "pair": pair, "gap_pct": r["mid_gap_pct"],
                    "fees_bps": [r["fee_buy_bps_onchain"], r["fee_sell_bps_onchain"]],
                    "route_status": r["route_status"],
                    "quoter": {k: (v["status"], v["diff_pct"]) for k, v in r["quoter_guards"].items()}})
json.dump(results, open("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag/static_positives_verified.json", "w"), indent=1, default=str)
n_pos = sum(1 for x in results if x["verified_net_usd"] > 0)
print(f"\nVÉRIFIÉS POSITIFS : {n_pos}/{len(results)} | meilleur net vérifié : "
      f"{max((x['verified_net_usd'] for x in results), default=None)} $")
