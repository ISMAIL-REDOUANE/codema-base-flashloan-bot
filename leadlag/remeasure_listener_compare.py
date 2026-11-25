#!/usr/bin/env python3
"""RE-MESUREMENT — comparaison ANCIENNE vs NOUVELLE logique de vérification
Polygon (audit #10). Lecture seule du JSONL du listener.
- ANCIENNE logique (bug #10) : entrée de vente = prix spot (res_b/res_a),
  net/action via polygon_decide sur réserves approximatives. Un signal
  enregistré => ancien net > 0 $ => action EXECUTE.
- NOUVELLE logique (corrigée) : out_a EXACT -> entrée de vente, retour
  en $ depuis out_b, coûts exacts, verdict dérivé de ce net
  (sig["verification"] : expected_net_usd, action).
Sortie : leadlag/remeasure_listener_compare.json + tableau imprimé.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SIG_PATH = os.path.join(ROOT, "polygon", "remeasurement_signals.jsonl")


def main():
    signals = []
    stats_lines = 0
    with open(SIG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "signal":
                signals.append(rec)
            elif rec.get("type") == "stats":
                stats_lines += 1
    print(f"Signaux (ancien net > 0 $) : {len(signals)} | lignes stats : {stats_lines}")
    rows = []
    flips = 0
    confirmed = 0
    unverified = 0
    for s in signals:
        v = s.get("verification") or {}
        old_net = s.get("net_usd")
        new_net = v.get("expected_net_usd")
        new_action = v.get("action")
        err = v.get("error")
        if err or new_action is None:
            unverified += 1
            status = "NON VÉRIFIÉ (erreur quoter)"
        elif new_action == "EXECUTE":
            confirmed += 1
            status = "CONFIRMÉ (EXECUTE des deux côtés)"
        else:
            flips += 1
            status = "RETOURNÉ (ancien EXECUTE -> nouveau SKIP)"
        rows.append({
            "block": s.get("block"), "pair": s.get("pair"),
            "size_usd": s.get("size_usd"),
            "spread_pct_old": s.get("spread_pct"),
            "old_net_usd": old_net, "old_action": "EXECUTE",
            "new_net_usd": new_net, "new_action": new_action,
            "new_spread_pct": v.get("spread_pct"),
            "verification_error": err,
            "verdict_comparison": status,
        })
        print(f"bloc {s.get('block')} {s.get('pair')} {s.get('size_usd')}$ : "
              f"ancien net {old_net} $ EXECUTE -> nouveau net {new_net} $ "
              f"{new_action or err} | {status}")
    print(f"\n=== COMPARAISON ANCIEN vs NOUVEAU (audit #10) ===")
    print(f"Signaux totaux : {len(signals)}")
    print(f"Confirmés EXECUTE par la nouvelle logique : {confirmed}")
    print(f"Retournés EXECUTE -> SKIP par la nouvelle logique : {flips}")
    print(f"Non vérifiés (erreur quoter) : {unverified}")
    if signals and flips == 0 and confirmed == len(signals):
        print("Le fix #10 ne change AUCUN verdict sur cette fenêtre : "
              "les signaux de l'ancienne logique étaient déjà exacts.")
    out = {"signals_total": len(signals), "confirmed_execute": confirmed,
           "flipped_to_skip": flips, "unverified": unverified, "rows": rows}
    with open(os.path.join(HERE, "remeasure_listener_compare.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("saved leadlag/remeasure_listener_compare.json")


if __name__ == "__main__":
    main()
