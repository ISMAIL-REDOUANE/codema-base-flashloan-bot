"""dry_run.py — Démonstration : 1 trade gagnant WOULD-EXECUTE, 1 trade
perdant SKIPPED avec 0 gas. Génère simulation_log.txt.
Lancer : python3 dry_run.py
v3.1 — SPONSOR : chaque trade logue le partage sponsor 25 % / Ismail 75 %,
et le dry-run écrit trades.jsonl (simulé, 0 $ réel).
v3.2 — ZERO-COST : chaque EXECUTE passe par le garde $0 (Morpho 0 %
seulement, gas sponsor, Ismail 0,00 $) — voir zero_cost.py.
v3.4 — SELF-FUNDED (défaut, décision d'Ismail 2026-11-24) : Ismail
finance le gas lui-même (float 20 $) et garde 100 % du profit. Le
dry-run utilise le FloatLedger (self_funded.py) + le garde $0 en mode
"self_funded" ; le sponsor n'est plus utilisé (section INACTIVE).
Le gas DÉDUIT du float en dry-run est le gas SIMULÉ (r.gas_usd, pas
gas_paid_usd qui vaut 0,00 $ sans broadcast)."""
from executor import run
from math_engine import Costs, Pool
from scanner import MemeCandidate
from self_funded import load_from_config as load_funding
from zero_cost import load_from_config as load_zero_cost

if __name__ == "__main__":
    costs = Costs()  # v2 : gas unifié (0,0675 $), min profit 3 $ (Ismail)
    # --- v3.4 : mode autofinancé par défaut (config.yaml `funding:`) ---
    try:
        funding = load_funding("config.yaml")
    except Exception as e:
        print(f"[funding] config illisible ({e}) — float par défaut 20 $")
        from self_funded import FloatLedger
        funding = FloatLedger()
    # Dry-run propre : pas d'état persisté d'un run précédent.
    funding.state_path = None
    funding.trades_path = "trades.jsonl"
    sponsor = None  # v3.4 : plus de sponsor (section INACTIVE en config)
    try:
        zero_cost = load_zero_cost("config.yaml")
    except Exception as e:
        print(f"[zero-cost] config illisible ({e}) — garde par défaut (Morpho)")
        from zero_cost import ZeroCostGuard
        zero_cost = ZeroCostGuard()
    zero_cost.trades_path = "trades.jsonl"
    # Le garde lit le mode depuis config.yaml (`funding.payer == "ismail"`
    # -> "self_funded") ; on le force ici pour être explicite.
    zero_cost.mode = "self_funded"
    win = MemeCandidate("0xAAA", "MEME-WIN", "aerodrome", "uniswap",
                        Pool("Aero", 20_000, 20_000_000),
                        Pool("UniV2", 18_000, 15_000_000),
                        liquidity_usd=36_000, holders=150, age_hours=10)
    lose = MemeCandidate("0xBBB", "MEME-LOSE", "aerodrome", "uniswap",
                         Pool("Aero", 50_000, 50_000_000),
                         Pool("UniV2", 50_000, 49_000_000),
                         liquidity_usd=100_000, holders=200, age_hours=5)
    results = run([win, lose], costs, funding=funding, zero_cost=zero_cost)
    total_gas = sum(r.gas_paid_usd for r in results)
    total_net = sum(r.expected_net_usd for r in results if r.action == "EXECUTE")
    sp, ism = funding.split_profit(total_net)
    print(f"\nTOTAL gas payé en dry-run : {total_gas:.2f} $ "
          f"(le trade perdant a été SKIPPÉ avant broadcast, 0 gas)")
    print(f"TOTAL net exécuté : +{total_net:.2f} $ -> "
          f"sponsor {sp:.2f} $ / Ismail {ism:.2f} $ "
          f"(gas simulé déduit du float : {funding.ismail_paid_usd:.2f} $)")
    print(funding.float_status_line())
    print(f"ZERO-COST : mode {zero_cost.mode} — "
          f"{zero_cost.trades_checked} trade(s) vérifié(s), "
          f"{zero_cost.trades_blocked} bloqué(s)")
    with open("simulation_log.txt", "w") as f:
        for r in results:
            sp_r, ism_r = funding.split_profit(
                r.expected_net_usd if r.action == "EXECUTE" else 0.0)
            f.write(f"{r.action} {r.symbol} spread={r.spread_pct:.2f}% "
                    f"loan={r.loan_usd:.2f}$ net={r.expected_net_usd:.2f}$ "
                    f"gas_paid={r.gas_paid_usd:.2f}$ reasons={r.reasons} "
                    f"sponsor={sp_r:.2f}$ ismail={ism_r:.2f}$\n")
        f.write(f"TOTAL gas payé : {total_gas:.2f}$\n")
        f.write(f"TOTAL net : {total_net:.2f}$ sponsor={sp:.2f}$ ismail={ism:.2f}$\n")
        f.write(funding.float_status_line() + "\n")
    print("Log écrit dans simulation_log.txt (+ trades.jsonl pour le float)")
