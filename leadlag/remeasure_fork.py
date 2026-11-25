#!/usr/bin/env python3
"""RE-MESUREMENT — fork preflight sur les majors (et, si le scan en trouve,
sur les candidats V2). SYNTHÉTIQUE (fork Anvil, jamais mainnet).
Lecture seule RPC (clé lue dans config.yaml, jamais affichée ni loggée).
Usage :
  python3 remeasure_fork.py                # majors WETH/USDC 100 $ au bloc courant
  python3 remeasure_fork.py --candidates   # + candidats V2 du scan (si présents)
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import fork_preflight as fp  # noqa: E402

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
UNI_V2 = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
BASESWAP_V2 = "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86"
# Routers V2 VÉRIFIÉS dans le repo (audit #7 : seuls v2 et v3-uni ont un
# adaptateur ; les autres dex ne sont pas forkables par fork_preflight.py).
V2_ROUTERS = {
    "uniswap": UNI_V2,
    "baseswap": BASESWAP_V2,
}


def rpc_url():
    cfg = open(os.path.join(ROOT, "config.yaml")).read()
    return re.search(r'rpc_url:\s*[\"\']?([^\"\'\s]+)', cfg).group(1)


def main():
    url = rpc_url()
    out = {"method": "fork_preflight (Anvil, SYNTHETIQUE)", "runs": []}
    # 1) Majors WETH/USDC, 100 $, bloc courant
    print("=== FORK MAJORS WETH/USDC 100 $ (bloc courant) ===")
    try:
        res = fp.run_fork_preflight(url, None, usdc=USDC, meme=WETH,
                                    router_buy=UNI_V2, router_sell=BASESWAP_V2,
                                    min_profit_raw=0, amount_raw=100_000_000)
        res["label"] = "majors WETH/USDC 100$ UniV2->BaseSwapV2"
        out["runs"].append(res)
        print(json.dumps(res, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        out["runs"].append({"label": "majors WETH/USDC 100$", "error": f"{type(e).__name__}: {e}"})
        print("ERREUR majors:", e)
    # 2) Candidats V2 du scan (si --candidates et fichier présent)
    if "--candidates" in sys.argv:
        path = os.path.join(HERE, "remeasure_scan_results.json")
        if not os.path.exists(path):
            print("Pas de résultats de scan — skip candidats.")
        else:
            data = json.load(open(path))
            n = 0
            for r in data["results"]:
                for c in r["candidates_new_code"]:
                    da = (c["dex_a"] or "").split(":")[0].lower()
                    db = (c["dex_b"] or "").split(":")[0].lower()
                    if da in V2_ROUTERS and db in V2_ROUTERS and da != db:
                        print(f"=== FORK candidat {r['token'][:14]} {da}->{db} "
                              f"spread {c['spread_pct']}% ===")
                        try:
                            res = fp.run_fork_preflight(
                                url, None, usdc=USDC, meme=r["token"],
                                router_buy=V2_ROUTERS[da], router_sell=V2_ROUTERS[db],
                                min_profit_raw=0, amount_raw=100_000_000)
                            res["label"] = f"candidat {r['token']} {da}->{db}"
                            out["runs"].append(res)
                            print(json.dumps(res, indent=2, default=str))
                            n += 1
                        except Exception as e:  # noqa: BLE001
                            out["runs"].append({"label": f"candidat {r['token']} {da}->{db}",
                                               "error": f"{type(e).__name__}: {e}"})
                            print("ERREUR candidat:", e)
                    else:
                        out["runs"].append({
                            "label": f"candidat {r['token']} {c['dex_a']}->{c['dex_b']}",
                            "skipped": "jambes non-V2 (contrat V2-only, audit #7) — "
                                       "fork_preflight V2 inapplicable, vérification par quoter exact requise",
                            "spread_pct": c["spread_pct"]})
            print(f"Candidats forkés (V2/V2): {n}")
    with open(os.path.join(HERE, "remeasure_fork_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("saved leadlag/remeasure_fork_results.json")


if __name__ == "__main__":
    main()
