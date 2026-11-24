"""
ev_test.py — Mesure de l'espérance de gain (EV) sur 100 opportunités simulées (v2).

POURQUOI (ADVANCED_RESEARCH.md §4.4) : EV = p_win × gain_moyen − p_perte ×
perte_moyenne − gas_moyen, avec p_win estimé sur des trades SIMULÉS, pas
inventé. Si EV ≤ 0 après 100 simulations, ON NE PASSE PAS EN LIVE — on
change de stratégie. C'est le test go/no-go que base-flash-arb-lab a
appliqué aux majors (et qui a donné no-go : 0/992).

PROTOCOLE (seed fixe = reproductible) :
  - 100 opportunités : spreads tirés 55 % petits (0–3 %), 30 % moyens
    (3–10 %), 10 % grands (10–20 %), 5 % très grands (20–30 %).
  - Liquidités log-uniformes 5k–100k $ (notre cible meme coins sghar).
  - Gas : 90 % normal (0,005–0,05 gwei), 5 % élevé (0,5–2 gwei),
    5 % pic (10–254 gwei — le pic du 29 oct 2026) -> le plafond 2 gwei
    doit les faire SKIPPER.
  - Chaque opportunité passe par decide() (gas unifié, min 3 $, net > gas×3).
  - Un trade EXECUTE paie son gas (déjà déduit du net) ; un SKIP paie 0 $.
  - Métriques : taux d'exécution, EV par opportunité, EV par trade exécuté,
    net total, max drawdown (sur la courbe des nets exécutés cumulés).

HONNÊTETÉ — ce que ce test NE prouve PAS :
  - Tous les trades EXECUTE ont net > 3 $ PAR CONSTRUCTION de decide() :
    le win rate simulé est donc de 100 % et le drawdown ~0. En live, le
    win rate réel sera < 100 % : simulation imparfaite, prix qui bouge
    entre la quote et le bloc, MEV, taxes non vues, revert. Ce test mesure
    l'EV DU MODÈLE (est-ce que les spreads existent en quantité suffisante),
    pas l'EV réel. Le vrai go/no-go exige 100 simulations FORK (preflight
    on-chain) — voir FORK_TEST_RESULTS.md de l'agent fork-test.
  - Les spreads sont tirés d'une distribution SUPPOSÉE (5–20 % sur memes),
    pas mesurée sur des pools réels : si les spreads réels sont plus petits,
    l'EV réel sera plus petit. À re-mesurer sur des données réelles.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from math_engine import Costs, Pool, decide

N_DEFAULT = 100
SEED_DEFAULT = 42
BASE_PRICE = 0.001  # 1 MEME = 0,001 $ (prix de référence arbitraire)


def _sample_spread(rng: random.Random) -> float:
    u = rng.random()
    if u < 0.55:
        return rng.uniform(0.0, 3.0)
    if u < 0.85:
        return rng.uniform(3.0, 10.0)
    if u < 0.95:
        return rng.uniform(10.0, 20.0)
    return rng.uniform(20.0, 30.0)


def _sample_liquidity(rng: random.Random) -> float:
    # Log-uniforme entre 5 000 et 100 000 $
    return math.exp(rng.uniform(math.log(5_000), math.log(100_000)))


def _sample_gas_gwei(rng: random.Random) -> float:
    u = rng.random()
    if u < 0.90:
        return rng.uniform(0.005, 0.05)
    if u < 0.95:
        return rng.uniform(0.5, 2.0)
    return rng.uniform(10.0, 254.0)  # pic type 29 oct 2026


def make_opportunity(rng: random.Random):
    """Une opportunité synthétique : 2 pools V2, spread tiré, liquidités tirées."""
    spread_pct = _sample_spread(rng)
    liq_a, liq_b = _sample_liquidity(rng), _sample_liquidity(rng)
    price_a = BASE_PRICE
    price_b = BASE_PRICE * (1 + spread_pct / 100.0)
    reserve_usdc_a, reserve_usdc_b = liq_a / 2.0, liq_b / 2.0
    pool_a = Pool("A", reserve_usdc_a, reserve_usdc_a / price_a)
    pool_b = Pool("B", reserve_usdc_b, reserve_usdc_b / price_b)
    return pool_a, pool_b, spread_pct


def run_ev(n: int = N_DEFAULT, seed: int = SEED_DEFAULT) -> dict:
    rng = random.Random(seed)
    executed_nets: list[float] = []
    skipped = 0
    gas_cap_skips = 0
    gas_paid_total = 0.0
    spreads_executed: list[float] = []
    rows: list[dict] = []
    for i in range(n):
        pool_a, pool_b, spread = make_opportunity(rng)
        gas_gwei = _sample_gas_gwei(rng)
        costs = Costs(gas_price_gwei=gas_gwei)  # gas_usd calculé par le modèle unifié
        d = decide(pool_a, pool_b, costs)
        if d["action"] == "EXECUTE":
            executed_nets.append(d["expected_net_usd"])
            spreads_executed.append(spread)
            gas_paid_total += d["gas_usd"]
            rows.append({"i": i, "action": "EXECUTE", "spread_pct": round(spread, 2),
                         "loan_usd": d["optimal_loan_usd"],
                         "net_usd": d["expected_net_usd"],
                         "gas_gwei": round(gas_gwei, 4)})
        else:
            skipped += 1
            if gas_gwei > costs.max_gas_price_gwei:
                gas_cap_skips += 1
            rows.append({"i": i, "action": "SKIP", "spread_pct": round(spread, 2),
                         "loan_usd": d["optimal_loan_usd"],
                         "net_usd": d["expected_net_usd"],
                         "gas_gwei": round(gas_gwei, 4),
                         "reasons": d["reasons"]})
    total_net = sum(executed_nets)
    n_exec = len(executed_nets)
    # Max drawdown sur la courbe cumulée des nets exécutés (dans l'ordre tiré).
    peak, max_dd = 0.0, 0.0
    cum = 0.0
    for net in executed_nets:
        cum += net
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "n_opportunities": n, "seed": seed,
        "n_executed": n_exec, "n_skipped": skipped,
        "execution_rate_pct": round(100.0 * n_exec / n, 1) if n else 0.0,
        "gas_cap_skips": gas_cap_skips,
        "total_net_usd": round(total_net, 2),
        "ev_per_opportunity_usd": round(total_net / n, 2) if n else 0.0,
        "ev_per_executed_trade_usd": round(total_net / n_exec, 2) if n_exec else 0.0,
        "avg_net_executed_usd": round(sum(executed_nets) / n_exec, 2) if n_exec else 0.0,
        "min_net_executed_usd": round(min(executed_nets), 2) if n_exec else 0.0,
        "max_net_executed_usd": round(max(executed_nets), 2) if n_exec else 0.0,
        "avg_spread_executed_pct": round(sum(spreads_executed) / len(spreads_executed), 2)
        if spreads_executed else 0.0,
        "total_gas_paid_usd": round(gas_paid_total, 2),
        "max_drawdown_usd": round(max_dd, 2),
        "verdict": ("GO (modèle) — EV > 0 sur 100 simulations, MAIS go/no-go "
                    "réel exige 100 simulations FORK" if total_net > 0 else
                    "NO-GO — EV ≤ 0, ne pas passer en live"),
        "rows": rows,
    }


def write_report(results: dict, path: str = "EV_RESULTS.md") -> None:
    lines = [
        "# EV mesuré — 100 opportunités simulées (v2)",
        "",
        f"Date : 2026-11-24. Seed : {results['seed']} (reproductible : "
        f"`python3 ev_test.py`). Modèle : decide() v2 (gas unifié, min 3 $, "
        f"net > gas × 3, plafond gas 2 gwei).",
        "",
        "| Métrique | Valeur |",
        "|---|---|",
        f"| Opportunités simulées | {results['n_opportunities']} |",
        f"| Trades EXECUTE | {results['n_executed']} ({results['execution_rate_pct']} %) |",
        f"| SKIP | {results['n_skipped']} (dont {results['gas_cap_skips']} par plafond gas) |",
        f"| Net total (100 opportunités) | **{results['total_net_usd']:.2f} $** |",
        f"| **EV par opportunité** | **{results['ev_per_opportunity_usd']:.2f} $** |",
        f"| EV par trade exécuté | {results['ev_per_executed_trade_usd']:.2f} $ |",
        f"| Net moyen / trade exécuté | {results['avg_net_executed_usd']:.2f} $ (min {results['min_net_executed_usd']:.2f} $, max {results['max_net_executed_usd']:.2f} $) |",
        f"| Spread moyen des trades exécutés | {results['avg_spread_executed_pct']:.2f} % |",
        f"| Gas total payé (trades exécutés) | {results['total_gas_paid_usd']:.2f} $ |",
        f"| Max drawdown (courbe cumulée) | {results['max_drawdown_usd']:.2f} $ |",
        "",
        f"**Verdict : {results['verdict']}**",
        "",
        "## Ce que ce test prouve — et ce qu'il ne prouve pas",
        "",
        "- Il prouve que, SI les spreads des memes sont bien distribués comme",
        "  supposé (55 % petits, 30 % moyens, 15 % grands) et SI le gas reste",
        "  sous le plafond, le modèle trouve assez de trades à +3 $ pour que",
        "  l'EV par opportunité soit positive.",
        "- Il ne prouve PAS le win rate réel : tous les EXECUTE ont net > 3 $",
        "  PAR CONSTRUCTION de decide(). En live, une partie revertera ou",
        "  sortira perdante (prix qui bouge, MEV, taxes, frais dynamiques).",
        "  Le vrai go/no-go exige 100 simulations FORK (preflight on-chain).",
        "- Les spreads sont SUPPOSÉS, pas mesurés sur des pools réels.",
        "  Si les spreads réels sont plus petits, l'EV réel sera plus petite.",
        "",
    ]
    Path(path).write_text("\n".join(lines))
    print(f"Rapport écrit : {path}")


if __name__ == "__main__":
    res = run_ev()
    for k in ("n_opportunities", "n_executed", "n_skipped", "execution_rate_pct",
              "gas_cap_skips", "total_net_usd", "ev_per_opportunity_usd",
              "ev_per_executed_trade_usd", "avg_net_executed_usd",
              "max_drawdown_usd", "total_gas_paid_usd", "verdict"):
        print(f"{k}: {res[k]}")
    write_report(res)
    Path("ev_results.json").write_text(json.dumps(res, indent=2))
