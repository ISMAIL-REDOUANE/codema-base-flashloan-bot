#!/usr/bin/env python3
"""verify_top_events.py — Vérification INDÉPENDANTE (route_verify.py) des
2 meilleurs événements du replay 24 h, avec gardes quoter par jambe.
Adresses copiées du JSON du scan (jamais tapées de mémoire)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")
sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")
import route_verify as rv

WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

EVENTS = [
    # (label, buy, sell, token, quote, upq, block, replay_net)
    ("E1 WETH/cbBTC",
     "0xC211e1f853A898Bd1302385CCdE55f33a8C4B3f3",
     "0x42d4a22CaD0F5a49681a5715cE994Af73A43B76b",
     WETH, CBBTC, 58683.42, 62009212, +0.2525),
    ("E2 WETH/USDC",
     "0xb4CB800910B228ED3d0834cF79D697127BBB00e5",
     "0x3FE04A59Ebd38cF06080a6F60a98D124eb59392A",
     WETH, USDC, 1.0, 61676712, +0.2459),
]

for label, buy, sell, tok, quo, upq, block, replay_net in EVENTS:
    gas = rv.measure_full_gas(block, 1643.55)
    r = rv.verify_cycle(buy, sell, tok, quo, 100.0, upq, block,
                        gas_usd=gas["total_usd"])
    print(f"{label} bloc {block} (replay net {replay_net:+.4f} $)")
    print(f"  gap {r['mid_gap_pct']:.4f}% | brut {r['gross_usd']:+.4f} $ | "
          f"fees {r['fee_buy_usd'] + r['fee_sell_usd']:.4f} $ | "
          f"impact {r['impact_buy_usd'] + r['impact_sell_usd']:.4f} $ | "
          f"gas {r['gas_usd']:.4f} $")
    print(f"  NET direct {r['net_direct_usd']:+.4f} $ (décomposé {r['net_usd']:+.4f} $) | "
          f"statut {r['route_status']}")
    for leg, g in r["quoter_guards"].items():
        print(f"    {leg}: {g['quoter']} -> {g['status']} "
              f"(diff {g['diff_pct'] if g['diff_pct'] is None else round(g['diff_pct'], 4)}%, "
              f"tol {g['tolerance_pct']:.4f}%)")
    print(f"  fees on-chain: {r['fee_buy_bps_onchain']} + {r['fee_sell_bps_onchain']} | "
          f"TVL ok: {r['tvl_ok']} | crossed: {r['crossed_tick_buy']}/{r['crossed_tick_sell']} | "
          f"identité: {r['identity_err_usd']:+.2e} $")
