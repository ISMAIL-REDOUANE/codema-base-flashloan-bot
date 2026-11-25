"""analyze_paper.py — Analyse du run paper-trade lead-lag order books.

Lit leadlag/paper_entries.jsonl et produit :
  1. Cadence + couverture (cycles, evals, erreurs RPC).
  2. Calibration : corrélation imbalance -> move (+1/+2 cycles), bande choisie.
  3. Thresholds PAR POOL : médiane par tier (la mesure demandée par Ismail).
  4. Phase LIVE : ENTRY/SKIP par paire et PAR TIER (même prédiction =
     ENTRY sur une pool, SKIP sur une autre ?), distribution des nets prédits.
  5. Survie des ENTRY papier : mouvement Binance et DEX réalisé à +1/+2
     cycles ; net réalisé (approx. : pred_net + taille x (move_réalisé DEX
     - move_prédit)/100 — le coût aller-retour est supposé identique,
     il ne dépend que de la taille, pas du mouvement).
  6. Validation hors-échantillon du modèle : corrélation move prédit vs
     move Binance réalisé en phase LIVE.
Sortie : résumé texte + leadlag/paper_analysis.json.
TOUT est PAPER — une ENTRY papier n'est jamais appelée profit ou gain.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

BASE = Path(str(Path(__file__).resolve().parents[1] / 'leadlag'))
IN = BASE / "paper_entries.jsonl"
OUT = BASE / "paper_analysis.json"


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return 0.0, 0.0
    return sxy / math.sqrt(sxx * syy), sxy / sxx


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(q * len(s))))
    return s[i]


def main():
    recs = [json.loads(l) for l in open(IN) if l.strip()]
    evals = [r for r in recs if r.get("kind") == "eval"]
    calibs = [r for r in recs if r.get("kind") == "calibration"]
    summ = [r for r in recs if r.get("kind") == "summary"]
    out = {"n_records": len(recs), "n_evals": len(evals)}

    print("=" * 70)
    print("ANALYSE PAPER-TRADE — lead-lag order books (Base, PAPER)")
    print("=" * 70)
    if summ:
        s = summ[-1]
        print(f"Run : {s.get('duration_min')} min (calibration "
              f"{s.get('calibration_min')} min) | cycles={s.get('cycles')} "
              f"evals={s.get('evals')} entries={s.get('entries')} "
              f"opps={s.get('opportunities', 0)}")
    # paires dynamiques (contrôle ETH en premier, puis petites pools)
    pairs = sorted({r.get("pair") for r in evals if r.get("pair")})
    pairs.sort(key=lambda p: (0 if p == "ETH/USDC" else 1, p))
    out["pairs"] = pairs
    # --- cadence + erreurs
    errs = [r for r in evals if r.get("decision") == "ERROR"]
    print(f"\nÉvaluations : {len(evals)} | ERREUR : {len(errs)} "
          f"({100.0 * len(errs) / max(1, len(evals)):.1f} %)")
    if errs:
        print("  raisons :", Counter(r.get("error", "?")[:60] for r in errs))
    for pair in pairs:
        ts = sorted(r["t_ms"] for r in evals if r.get("pair") == pair)
        dts = [(b - a) / 1000.0 for a, b in zip(ts, ts[1:])]
        if dts:
            print(f"  {pair} : {len(ts)} evals, cadence médiane "
                  f"{median(dts):.1f} s (p90 {pct(dts, 0.9):.1f} s)")
    out["errors"] = len(errs)

    # --- calibration
    print("\n--- CALIBRATION (imbalance Binance -> move, 10 min) ---")
    out["calibration"] = {}
    for c in calibs:
        p = c["pair"]
        if c.get("binance_signal") is False:
            # paire SANS signal Binance : la calibration = distribution
            # des mouvements DEX bruts (test de la thèse « petites pools »).
            out["calibration"][p] = {
                "binance_signal": False, "n": c["n_samples"],
                "dex_mv_next_median_abs_pct": c.get("dex_mv_next_median_abs_pct"),
                "dex_mv_next_p95_abs_pct": c.get("dex_mv_next_p95_abs_pct"),
                "dex_mv_next_max_abs_pct": c.get("dex_mv_next_max_abs_pct"),
                "dex_mv_next2_median_abs_pct": c.get("dex_mv_next2_median_abs_pct"),
                "dex_mv_next2_p95_abs_pct": c.get("dex_mv_next2_p95_abs_pct"),
                "dex_mv_next2_max_abs_pct": c.get("dex_mv_next2_max_abs_pct"),
                "median_dt_next_s": c.get("median_dt_next_s"),
                "median_dt_next2_s": c.get("median_dt_next2_s"),
            }
            print(f"  {p} : NO BINANCE SIGNAL | n={c['n_samples']} | "
                  f"DEX moves +1 cycle : médiane |mv| "
                  f"{c.get('dex_mv_next_median_abs_pct')} % | p95 "
                  f"{c.get('dex_mv_next_p95_abs_pct')} % | max "
                  f"{c.get('dex_mv_next_max_abs_pct')} % | +2 cycles max "
                  f"{c.get('dex_mv_next2_max_abs_pct')} %")
            continue
        out["calibration"][p] = {
            "n": c["n_samples"],
            "corr_imb01_next": c.get("corr_imb01_mv_next"),
            "corr_imb01_next2": c.get("corr_imb01_mv_next2"),
            "corr_imb05_next": c.get("corr_imb05_mv_next"),
            "corr_imb05_next2": c.get("corr_imb05_mv_next2"),
            "chosen_band": c.get("chosen_band"),
            "chosen_corr": c.get("chosen_corr"),
            "chosen_slope": c.get("chosen_slope"),
            "median_dt_next_s": c.get("median_dt_next_s"),
            "median_dt_next2_s": c.get("median_dt_next2_s"),
        }
        print(f"  {p} : n={c['n_samples']} | imb01->next "
              f"{c.get('corr_imb01_mv_next')} next2 {c.get('corr_imb01_mv_next2')} | "
              f"imb05->next {c.get('corr_imb05_mv_next')} next2 "
              f"{c.get('corr_imb05_mv_next2')} | choisi {c.get('chosen_band')} "
              f"corr={c.get('chosen_corr')} slope={c.get('chosen_slope')} | "
              f"dt_next médian {c.get('median_dt_next_s')} s")

    # --- thresholds par pool
    print("\n--- THRESHOLDS PAR POOL (médiane sur tout le run) ---")
    out["thresholds"] = {}
    for pair in pairs:
        ths = defaultdict(list)
        ths_usd = defaultdict(list)
        sizes = defaultdict(list)
        for r in evals:
            if r.get("pair") != pair:
                continue
            for fee, th in (r.get("thresholds") or {}).items():
                ths[fee].append(th["threshold_pct"])
                ths_usd[fee].append(th["threshold_usd"])
                sizes[fee].append(th["best_size_usd"])
        out["thresholds"][pair] = {}
        for fee in sorted(ths, key=lambda f: int(f)):
            out["thresholds"][pair][fee] = {
                "threshold_pct_med": round(median(ths[fee]), 4),
                "threshold_pct_min": round(min(ths[fee]), 4),
                "threshold_pct_max": round(max(ths[fee]), 4),
                "threshold_usd_med": round(median(ths_usd[fee]), 4),
                "best_size_med": median(sizes[fee]),
                "n": len(ths[fee]),
            }
            print(f"  {pair} fee {fee} bps : threshold "
                  f"{median(ths[fee]):.4f} % "
                  f"(min {min(ths[fee]):.4f} / max {max(ths[fee]):.4f}) | "
                  f"${median(ths_usd[fee]):.4f} à taille médiane "
                  f"${median(sizes[fee]):.0f} | n={len(ths[fee])}")

    # --- phase LIVE : décisions
    live = [r for r in evals if r.get("phase") == "live"]
    print(f"\n--- PHASE LIVE : {len(live)} évaluations ---")
    out["live"] = {}
    for pair in pairs:
        lp = [r for r in live if r.get("pair") == pair]
        dec = Counter(r.get("decision") for r in lp)
        reasons = Counter(r.get("decision_reason", "?") for r in lp
                          if r.get("decision") == "SKIP")
        nets = [r["pred_net_usd"] for r in lp if r.get("pred_net_usd") is not None]
        moves = [r["pred_move_pct"] for r in lp if r.get("pred_move_pct") is not None]
        # paires sans signal Binance : nets RÉTROSPECTIFS (mouvement déjà eu lieu)
        retro = [r["retrospective_net_usd"] for r in lp
                 if r.get("retrospective_net_usd") is not None]
        out["live"][pair] = {
            "n": len(lp), "decisions": dict(dec),
            "skip_reasons": dict(reasons),
            "pred_net_best": max(nets) if nets else None,
            "pred_net_med": round(median(nets), 4) if nets else None,
            "pred_move_max_abs": max((abs(m) for m in moves), default=None),
            "pred_move_p95_abs": pct([abs(m) for m in moves], 0.95) if moves else None,
            "retro_net_best": max(retro) if retro else None,
            "retro_net_med": round(median(retro), 4) if retro else None,
            "retro_n": len(retro),
        }
        print(f"  {pair} : {dict(dec)}")
        for k, v in reasons.items():
            print(f"      SKIP — {k} : {v}")
        if nets:
            print(f"      net prédit : meilleur {max(nets):.4f} $ | "
                  f"médian {median(nets):.4f} $ | "
                  f"move prédit max |.| "
                  f"{max((abs(m) for m in moves), default=0):.4f} % "
                  f"(p95 {pct([abs(m) for m in moves], 0.95):.4f} %)")
        if retro:
            print(f"      net RÉTROSPECTIF (mouvement déjà eu lieu, pas une "
                  f"prédiction) : meilleur {max(retro):.4f} $ | "
                  f"médian {median(retro):.4f} $ | n={len(retro)}")

    entries = [r for r in live if r.get("decision") == "ENTRY"]
    print(f"\nENTRIES papier (prédiction Binance) : {len(entries)}")
    out["n_entries"] = len(entries)
    opps = [r for r in live if r.get("decision") == "OPPORTUNITY"]
    print(f"OPPORTUNITÉS rétrospectives (mouvement DEX déjà eu lieu) : {len(opps)}")
    out["n_opportunities"] = len(opps)

    # --- MOUVEMENTS DEX RÉALISÉS : petites pools vs contrôle ETH
    # (le test direct de la thèse d'Ismail : « les petites pools bougent plus »)
    print("\n--- MOUVEMENTS DEX RÉALISÉS PAR POOL (phase LIVE, |move| par cycle) ---")
    out["dex_moves"] = {}
    for pair in pairs:
        lp = [r for r in live if r.get("pair") == pair]
        m1 = [abs(r["dex_mv_1c_pct"]) for r in lp
              if r.get("dex_mv_1c_pct") is not None]
        m2 = [abs(r["dex_mv_2c_pct"]) for r in lp
              if r.get("dex_mv_2c_pct") is not None]
        # % des cycles où le mouvement réalisé a dépassé le seuil min de la pool
        over = 0
        tot = 0
        for r in lp:
            th = r.get("min_threshold_pct")
            if th is None:
                ths = r.get("thresholds") or {}
                if ths:
                    th = min(v["threshold_pct"] for v in ths.values())
            mv = max([abs(v) for v in (r.get("dex_mv_1c_pct"),
                                       r.get("dex_mv_2c_pct"))
                      if v is not None], default=None)
            if th is not None and mv is not None:
                tot += 1
                if mv > th:
                    over += 1
        out["dex_moves"][pair] = {
            "n": len(lp),
            "mv1c_med_abs_pct": round(median(m1), 5) if m1 else None,
            "mv1c_p95_abs_pct": round(pct(m1, 0.95), 5) if m1 else None,
            "mv1c_max_abs_pct": round(max(m1), 5) if m1 else None,
            "mv2c_med_abs_pct": round(median(m2), 5) if m2 else None,
            "mv2c_p95_abs_pct": round(pct(m2, 0.95), 5) if m2 else None,
            "mv2c_max_abs_pct": round(max(m2), 5) if m2 else None,
            "cycles_over_min_threshold": over,
            "cycles_with_threshold": tot,
            "pct_over_min_threshold": (round(100.0 * over / tot, 1)
                                       if tot else None),
        }
        if tot:
            print(f"  {pair} : n={len(lp)} | +1 cycle |mv| médiane "
                  f"{median(m1) if m1 else 0:.5f} % p95 {pct(m1, 0.95) if m1 else 0:.5f} % "
                  f"max {max(m1) if m1 else 0:.5f} % | +2 cycles max "
                  f"{max(m2) if m2 else 0:.5f} % | cycles où |move| > seuil min : "
                  f"{over}/{tot} ({100.0 * over / tot:.1f} %)")
        else:
            print(f"  {pair} : n={len(lp)} | pas de seuil mesuré")

    # --- détail des OPPORTUNITÉS rétrospectives
    print("\n--- OPPORTUNITÉS RÉTROSPECTIVES (détail) ---")
    out["opportunities_detail"] = []
    for o in opps:
        d = {"pair": o["pair"], "t_ms": o["t_ms"],
             "realized_move_pct": o.get("realized_move_pct"),
             "direction": o.get("retrospective_direction"),
             "min_threshold_pct": o.get("min_threshold_pct"),
             "retrospective_net_usd": o.get("retrospective_net_usd"),
             "retrospective_size_usd": o.get("retrospective_size_usd")}
        out["opportunities_detail"].append(d)
        print(f"  {o['pair']} {d['direction']} move réalisé "
              f"{o.get('realized_move_pct', 0):+.4f} % vs seuil min "
              f"{o.get('min_threshold_pct')} % -> net rétrospectif "
              f"{o.get('retrospective_net_usd')} $ @ "
              f"${o.get('retrospective_size_usd')}")
    if not opps:
        print("  (aucune opportunité rétrospective)")

    # --- décisions PAR TIER : même prédiction, ENTRY sur l'une / SKIP sur l'autre ?
    print("\n--- DÉCISIONS PAR TIER (même prédiction, seuils différents) ---")
    out["tier_disagreement"] = {}
    for pair in pairs:
        lp = [r for r in live if r.get("pair") == pair
              and r.get("tier_decisions")]
        per_tier = defaultdict(Counter)
        disagree = 0
        for r in lp:
            ds = {f: v["decision"] for f, v in r["tier_decisions"].items()}
            for f, d in ds.items():
                per_tier[f][d] += 1
            if len(set(ds.values())) > 1:
                disagree += 1
        out["tier_disagreement"][pair] = {
            "n_evals_with_tiers": len(lp),
            "disagree_evals": disagree,
            "per_tier": {f: dict(c) for f, c in per_tier.items()},
        }
        print(f"  {pair} : {len(lp)} evals avec tiers, "
              f"{disagree} où les tiers DÉSACCORDENT (ENTRY sur l'une, SKIP sur l'autre)")
        for f in sorted(per_tier, key=lambda x: int(x)):
            print(f"      tier {f} bps : {dict(per_tier[f])}")

    # --- survie des ENTRY : mouvements réalisés à +1/+2 cycles
    print("\n--- SURVIE DES ENTRY PAPIER (mouvements réalisés) ---")
    by_pair = defaultdict(list)
    for r in evals:
        by_pair[r.get("pair")].append(r)
    for p in by_pair:
        by_pair[p].sort(key=lambda r: r["t_ms"])
    surv = []
    out["entries_detail"] = []
    for e in entries:
        seq = by_pair[e["pair"]]
        idx = next((i for i, r in enumerate(seq) if r["t_ms"] == e["t_ms"]), None)
        if idx is None:
            continue
        size = e.get("opt_size_usd") or 0
        pred_net = e.get("pred_net_usd") or 0
        pred_mv = e.get("pred_move_pct") or 0
        d = {"pair": e["pair"], "t_ms": e["t_ms"],
             "direction": e.get("direction"),
             "pred_move_pct": round(pred_mv, 5), "pred_net_usd": round(pred_net, 4),
             "opt_size_usd": size, "tier": e.get("best_tier_fee_bps"),
             "model_corr": e.get("model_corr")}
        for k, j in (("plus1", idx + 1), ("plus2", idx + 2)):
            if j < len(seq):
                r = seq[j]
                if r.get("bin_mid") and e.get("bin_mid"):
                    d[f"bin_move_{k}_pct"] = round(
                        (r["bin_mid"] - e["bin_mid"]) / e["bin_mid"] * 100, 5)
                if r.get("dex_mid") and e.get("dex_mid"):
                    dex_mv = (r["dex_mid"] - e["dex_mid"]) / e["dex_mid"] * 100
                    d[f"dex_move_{k}_pct"] = round(dex_mv, 5)
                    # net réalisé (approx.) = pred_net + taille x (move DEX
                    # réalisé - move prédit)/100
                    d[f"realized_net_{k}_usd"] = round(
                        pred_net + size * (dex_mv - pred_mv) / 100.0, 4)
        surv.append(d)
        out["entries_detail"].append(d)
    if surv:
        for d in surv:
            print(f"  {d['pair']} {d['direction']} tier {d['tier']} "
                  f"pred {d['pred_move_pct']:+.4f}% net {d['pred_net_usd']:+.4f}$ "
                  f"@ ${d['opt_size_usd']:.0f} | Binance +1 "
                  f"{d.get('bin_move_plus1_pct', '—'):+}% +2 "
                  f"{d.get('bin_move_plus2_pct', '—'):+}% | DEX +1 "
                  f"{d.get('dex_move_plus1_pct', '—'):+}% +2 "
                  f"{d.get('dex_move_plus2_pct', '—'):+}% | net réalisé +2 "
                  f"{d.get('realized_net_plus2_usd', '—')}")
        ok1 = sum(1 for d in surv if (d.get("realized_net_plus1_usd") or -1) > 0)
        ok2 = sum(1 for d in surv if (d.get("realized_net_plus2_usd") or -1) > 0)
        print(f"  -> net réalisé > 0 $ : +1 cycle {ok1}/{len(surv)} | "
              f"+2 cycles {ok2}/{len(surv)}")
        out["survival"] = {"n": len(surv), "plus1_pos": ok1, "plus2_pos": ok2}
    else:
        print("  (aucune ENTRY — rien à tester pour la survie)")
        out["survival"] = {"n": 0}

    # --- validation hors-échantillon du modèle (phase LIVE)
    print("\n--- MODÈLE HORS-ÉCHANTILLON (phase LIVE : prédit vs réalisé) ---")
    out["holdout"] = {}
    for pair in pairs:
        seq = [r for r in live if r.get("pair") == pair
               and r.get("pred_move_pct") is not None]
        xs, y1, y2 = [], [], []
        full = by_pair[pair]
        idx_of = {r["t_ms"]: i for i, r in enumerate(full)}
        for r in seq:
            i = idx_of.get(r["t_ms"])
            if i is None:
                continue
            if i + 1 < len(full) and full[i + 1].get("bin_mid") and r.get("bin_mid"):
                xs.append(r["pred_move_pct"])
                y1.append((full[i + 1]["bin_mid"] - r["bin_mid"]) / r["bin_mid"] * 100)
            if i + 2 < len(full) and full[i + 2].get("bin_mid") and r.get("bin_mid"):
                y2.append((full[i + 2]["bin_mid"] - r["bin_mid"]) / r["bin_mid"] * 100)
        c1, s1 = pearson(xs[:len(y1)], y1)
        c2, s2 = pearson(xs[:len(y2)], y2)
        out["holdout"][pair] = {"n": len(xs), "corr_next": c1, "corr_next2": c2}
        print(f"  {pair} : n={len(xs)} | corr prédit->réalisé Binance : "
              f"+1 cycle {c1} | +2 cycles {c2}")

    json.dump(out, open(OUT, "w"), indent=1)
    print(f"\nAnalyse écrite : {OUT}")


if __name__ == "__main__":
    main()
