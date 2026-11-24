"""
executor.py — Exécuteur avec RÈGLE GAS : simuler AVANT de broadcaster.

Le point que Ismail a exigé, en clair :
  - Si le trade serait PERDANT, on fait REVERT... mais un revert on-chain
    coûte du gas quand même. Donc on NE BROADCASTE PAS les trades perdants.
  - On simule off-chain (eth_call / fork local, sans envoyer de tx) :
    simulation = 0 gas, 0 $.
  - On broadcast SEULEMENT si la simulation dit : net > min_profit
    ET net > gas x 3.
  - Le revert dans le contrat Solidity n'est que le filet de sécurité
    (si le prix a bougé entre la simulation et l'inclusion dans le bloc).
    Objectif : 0 revert on-chain.

Modes :
  dry_run (défaut) : simulation seulement, AUCUN broadcast, AUCUNE clé.
  live            : NON implémenté en v2 — à activer seulement après audit
                    + fork tests + clé dans un coffre, jamais en dur.

v2 — PREFLIGHT EVM RÉEL (preflight.py, amélioration n°3) :
  run(opportunities, rpc_url="https://mainnet.base.org") ajoute, pour chaque
  candidat EXECUTE par le calcul, une simulation on-chain via getAmountsOut
  des vrais routers : si le preflight dit LOSE / STALE / UNAVAILABLE, le
  candidat est rétrogradé en SKIP (0 gas). Le calcul mathématique ne suffit
  pas : il ne voit ni les taxes, ni les hooks, ni les frais dynamiques.
  Sans rpc_url, on reste sur la simulation mathématique seule (documenté).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from math_engine import Costs, Pool, decide
from preflight import is_fresh, preflight_roundtrip
from scanner import MemeCandidate

# v3.3 — Morpho Blue 0 % préféré, Aave 0,05 % en repli (morpho_flash.py).
# Balancer MORT (BIP-928, wind-down 30 oct 2026) : ne plus l'utiliser.
from morpho_flash import (MORPHO_FLASH_FEE, costs_for_provider,
                          fetch_morpho_balances, select_provider)

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
ROUTER_BY_DEX = {
    "aerodrome": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
    "uniswap": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
    "uniswapv2": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
    "sushi": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891",
    "sushiswap": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891",
}


def _router_for(dex_name: str) -> Optional[str]:
    key = (dex_name or "").lower().split(":")[0]
    return ROUTER_BY_DEX.get(key)


def simulate_evm(candidate: MemeCandidate, loan_usd: float, rpc_url: str,
                 costs: Optional[Costs] = None, timeout: int = 15):
    """Preflight EVM d'un candidat : quote on-chain du round-trip complet.
    Retourne None si on ne peut pas quoter (DEX inconnu / token inconnu) :
    l'appelant doit alors traiter ça comme un SKIP, pas comme un feu vert."""
    costs = costs or Costs()
    router_buy = _router_for(candidate.dex_a)
    router_sell = _router_for(candidate.dex_b)
    if not router_buy or not router_sell:
        return None
    loan_raw = int(loan_usd * 1e6)  # USDC : 6 décimales
    # Aerodrome n'a PAS getAmountsOut V2 (fork §7.1) : cotation Route-based.
    from preflight import AERODROME_ROUTER
    return preflight_roundtrip(
        rpc_url, loan_raw, USDC, candidate.token_address, USDC,
        router_buy, router_sell,
        flash_fee_rate=costs.flash_fee_rate,
        gas_units=450_000, gas_price_gwei=costs.gas_price_gwei or 0.05,
        eth_price_usd=3000.0, min_profit_usd=costs.min_profit_usd,
        gas_multiple=costs.gas_multiple, loan_usd=loan_usd,
        token_out_decimals=6,
        router_buy_is_aero=(router_buy.lower() == AERODROME_ROUTER.lower()),
        router_sell_is_aero=(router_sell.lower() == AERODROME_ROUTER.lower()),
        timeout=timeout)


@dataclass
class SimulationResult:
    action: str            # "EXECUTE" | "SKIP"
    token: str
    symbol: str
    loan_usd: float
    expected_net_usd: float
    gas_usd: float
    gas_paid_usd: float    # 0.0 si SKIP (rien broadcasté), gas réel si EXECUTE
    reasons: List[str] = field(default_factory=list)
    spread_pct: float = 0.0
    provider: str = "aave"  # v3.3 : "morpho" (0 %) ou "aave" (0,05 %)
    provider_reason: str = ""


def simulate(candidate: MemeCandidate, costs: Optional[Costs] = None,
             max_loan_usd: float = 50_000.0,
             max_pct_liquidity: float = 0.10,
             vault_balances: Optional[Dict] = None) -> SimulationResult:
    """Simulation off-chain PURE (que du calcul, aucun appel réseau en v1).
    En prod : remplacer par un eth_call sur un fork (Anvil/Tenderly) qui
    exécute executeOperation() à blanc — même logique, même verdict.
    v3.3 — CHOIX DU PROVIDER : on décide d'abord avec Aave (0,05 %) pour
    obtenir la taille candidate, puis select_provider() choisit Morpho
    (0 %) si le loan tient dans 50 % du solde Morpho ; si oui, on
    RE-décide avec le taux 0 % (l'optimal bouge très légèrement).
    vault_balances=None -> soldes MESURÉS bloc 61 806 974 (datés, dit
    clairement dans morpho_flash.py) ; avec un RPC, passer les soldes
    live lus par fetch_morpho_balances()."""
    costs = costs or Costs()
    # 1) taille candidate avec le taux du caller (défaut Aave 0,05 %).
    d0 = decide(candidate.pool_a, candidate.pool_b, costs,
                max_loan_usd, max_pct_liquidity)
    # 2) choix du provider pour cette taille, puis RE-décision avec le
    #    taux du provider choisi (0 % Balancer ou 0,05 % Aave) — l'optimal
    #    bouge légèrement avec le taux, donc on ne réutilise jamais d0
    #    tel quel quand le provider change.
    sel = select_provider(d0["optimal_loan_usd"], "USDC", vault_balances)
    costs = costs_for_provider(sel.provider, costs)
    d = decide(candidate.pool_a, candidate.pool_b, costs,
               max_loan_usd, max_pct_liquidity)
    return SimulationResult(
        action=d["action"], token=candidate.token_address,
        symbol=candidate.symbol, loan_usd=d["optimal_loan_usd"],
        expected_net_usd=d["expected_net_usd"], gas_usd=d["gas_usd"],
        # <-- LA RÈGLE GAS : SKIP = 0 gas payé. EXECUTE en dry_run = 0 aussi
        # (on ne broadcast rien en dry_run).
        gas_paid_usd=0.0, reasons=d["reasons"], spread_pct=d["spread_pct"],
        provider=sel.provider, provider_reason=sel.reason)


def run(opportunities: List[MemeCandidate], costs: Optional[Costs] = None,
        mode: str = "dry_run", rpc_url: Optional[str] = None,
        breaker=None, sponsor=None, zero_cost=None, funding=None,
        **kw) -> List[SimulationResult]:
    """Boucle principale v2 : simuler chaque opportunité, ne rien envoyer.
    - rpc_url donné : chaque EXECUTE mathématique passe en plus par le
      preflight EVM ; LOSE/STALE/UNAVAILABLE -> SKIP (0 gas).
    - breaker donné (CircuitBreaker) : refuse les trades si les limites
      sont atteintes (perte jour / kill switch / pause reverts).
    - sponsor donné (SponsorLedger, v3.1) : chaque EXECUTE passe par le
      deal sponsor — check_trade() bloque le trade (raison STOP explicite)
      si la part sponsor dépasserait le plafond journalier ou si le kill
      switch / prefund épuisé ; sinon le trade est enregistré (partage
      25 % / 75 %, gas déduit du prefund) dans trades.jsonl. Chaque SKIP
      logue 0 $ / 0 $ pour le sponsor et Ismail (rien à partager).
    - zero_cost donné (ZeroCostGuard, v3.2) : chaque EXECUTE passe par
      check_zero_cost() AVANT tout enregistrement — provider interdit
      (Aave 0,05 %), gas à la charge d'Ismail, prefund sponsor insuffisant,
      crédits CDP non approuvés ou la moindre charge à Ismail -> SKIP avec
      la raison explicite "ZERO_COST: ...". Autorisé -> la ligne
      trades.jsonl porte ismail_paid_usd (toujours 0,00 $) ; sans sponsor,
      c'est le garde lui-même qui écrit la ligne.
    - funding donné (FloatLedger, v3.4, SELF-FUNDED, mode par défaut) :
      pas de deal sponsor — Ismail garde 100 % du net, le gas sort de
      son float (20 $). Le garde $0 bascule en mode "self_funded" (gas
      Ismail autorisé si le float couvre le pire cas gas + budget revert,
      net >= 3 $ après gas). L'enregistrement se fait dans le FloatLedger
      (une seule ligne par trade, funding_mode "self_funded", gas SIMULÉ
      déduit du float en dry-run). Sans garde, le float reste le
      garde-fou (can_afford) avant tout enregistrement.
    - Sans rpc_url ni breaker : simulation mathématique seule (v1).
    v3.3 : avec rpc_url, on lit AUSSI les soldes live de Morpho
    (fetch_morpho_balances) pour le choix du provider ; sans rpc_url,
    ce sont les soldes mesurés bloc 61 806 974 qui servent (datés)."""
    if mode != "dry_run":
        raise ValueError("mode live NON autorisé en v2 — rester en dry_run")
    costs = costs or Costs()
    vault_balances = kw.pop("vault_balances", None)
    if rpc_url and vault_balances is None:
        vault_balances = fetch_morpho_balances(rpc_url)
        if vault_balances is None:
            print("[v3.3] soldes Morpho illisibles (RPC) -> soldes mesurés "
                  "bloc 61 806 974 utilisés pour le choix du provider")
    results: List[SimulationResult] = []
    for opp in opportunities:
        r = simulate(opp, costs, vault_balances=vault_balances, **kw)
        if r.action == "EXECUTE" and breaker is not None:
            ok, reason = breaker.can_trade(opp.token_address)
            if not ok:
                r.action, r.reasons = "SKIP", [f"circuit breaker : {reason}"]
                r.gas_paid_usd = 0.0
        if r.action == "EXECUTE" and rpc_url:
            # v3.3 : le preflight doit utiliser le taux du PROVIDER CHOISI
            # (0 % Morpho), pas le taux Aave par défaut — sinon le net
            # on-chain serait sous-estimé de la prime Aave.
            costs_pf = costs_for_provider(r.provider, costs)
            pf = simulate_evm(opp, r.loan_usd, rpc_url, costs_pf)
            if pf is None:
                r.action = "SKIP"
                r.reasons = ["preflight impossible (DEX/token non quotable) -> SKIP"]
            elif pf.status != "WIN":
                r.action = "SKIP"
                r.reasons = [f"preflight EVM {pf.status} : net on-chain "
                             f"{pf.net_usd:.2f} $ — " + "; ".join(pf.reasons)]
                if pf.error:
                    r.reasons.append(pf.error)
            else:
                # Fraîcheur : la quote doit dater de <= 2 blocs (Denim 200 ms).
                from preflight import get_block_number
                now_block = get_block_number(rpc_url)
                if not is_fresh(pf.block_number, now_block):
                    r.action = "SKIP"
                    r.reasons = [f"quote trop vieille (bloc {pf.block_number}, "
                                 f"actuel {now_block}) — plus de 2 blocs, on rejette"]
                else:
                    r.expected_net_usd = pf.net_usd  # le net on-chain fait foi
                    r.gas_usd = pf.gas_cost_usd
        # v3.1 — SPONSOR : un EXECUTE ne part que si le deal sponsor l'autorise.
        # Bloqué (plafond / kill switch / prefund) -> SKIP avec raison STOP
        # explicite, 0 $ pour tout le monde. Autorisé -> on passe au garde
        # $0 AVANT d'enregistrer quoi que ce soit (v3.2).
        # v3.4 — SELF-FUNDED : quand `funding` est donné, il n'y a PAS de
        # deal sponsor — Ismail garde 100 % du net, et le float est le
        # garde-fou gas (pas de check sponsor, pas de plafond sponsor).
        sponsor_share, ismail_share = 0.0, 0.0
        sponsor_ok = True
        if funding is not None:
            if r.action == "EXECUTE":
                sponsor_share, ismail_share = 0.0, r.expected_net_usd
        elif sponsor is not None and r.action == "EXECUTE":
            ok, reason, sponsor_share, ismail_share = sponsor.check_trade(
                r.expected_net_usd)
            if not ok:
                sponsor_ok = False
                r.action, r.reasons = "SKIP", [f"sponsor STOP : {reason}"]
                sponsor_share, ismail_share = sponsor.split_profit(0.0)
        elif sponsor is not None:
            sponsor_share, ismail_share = sponsor.split_profit(0.0)
        # v3.2 — ZERO-COST : le dernier garde avant exécution. Bloqué ->
        # SKIP "ZERO_COST: ..." et RIEN n'est enregistré nulle part.
        # Autorisé -> enregistrement (sponsor, ou le garde seul s'il n'y a
        # pas de sponsor), avec ismail_paid_usd dans la ligne trades.jsonl.
        # v3.4 — SELF-FUNDED : le garde bascule en mode "self_funded"
        # (gas Ismail depuis le float, net >= 3 $ après gas) et
        # l'enregistrement se fait dans le FloatLedger (une seule ligne
        # par trade, funding_mode "self_funded", gas SIMULÉ déduit du
        # float en dry-run — gas_paid_usd vaut 0,00 $ sans broadcast).
        if zero_cost is not None and r.action == "EXECUTE":
            from zero_cost import trade_from_result
            if funding is not None:
                if getattr(zero_cost, "mode", "zero_cost") != "self_funded":
                    zero_cost.mode = "self_funded"
                trade = trade_from_result(
                    r, gas_payer="ismail",
                    float_remaining_usd=funding.float_remaining_usd)
            else:
                prefund = sponsor.prefund_remaining() if sponsor is not None else None
                trade = trade_from_result(r, gas_payer=zero_cost.gas_payer,
                                          prefund_remaining_usd=prefund)
            ok, reason = zero_cost.check_zero_cost(trade)
            if not ok:
                r.action = "SKIP"
                r.reasons = [reason]
                sponsor_share, ismail_share = 0.0, 0.0
            elif funding is not None:
                funding.record_trade(r.symbol, r.expected_net_usd,
                                     r.gas_usd, r.provider,
                                     simulated=(mode == "dry_run"))
            elif sponsor is not None:
                sponsor.record_trade(r.symbol, r.expected_net_usd,
                                     r.gas_paid_usd, r.provider,
                                     simulated=(mode == "dry_run"),
                                     extra={"ismail_paid_usd": zero_cost.ismail_paid_usd,
                                            "zero_cost": True})
            else:
                zero_cost.append_ledger(r.symbol, r.expected_net_usd,
                                        r.gas_paid_usd, r.provider,
                                        simulated=(mode == "dry_run"))
        elif funding is not None and r.action == "EXECUTE":
            # Cas sans garde $0 : le float reste le garde-fou (pire cas
            # gas + budget revert) avant tout enregistrement.
            ok_f, reason_f = funding.can_afford(r.gas_usd)
            if not ok_f:
                r.action = "SKIP"
                r.reasons = [reason_f]
                sponsor_share, ismail_share = 0.0, 0.0
            else:
                funding.record_trade(r.symbol, r.expected_net_usd,
                                     r.gas_usd, r.provider,
                                     simulated=(mode == "dry_run"))
        elif sponsor is not None and r.action == "EXECUTE" and sponsor_ok:
            sponsor.record_trade(r.symbol, r.expected_net_usd,
                                 r.gas_paid_usd, r.provider,
                                 simulated=(mode == "dry_run"))
        results.append(r)
        if r.action == "EXECUTE":
            print(f"[dry-run] WOULD-EXECUTE {r.symbol} spread {r.spread_pct:.1f}% "
                  f"loan {r.loan_usd:.0f} $ net attendu +{r.expected_net_usd:.2f} $ "
                  f"[provider {r.provider}] "
                  f"(gas payé en dry-run : 0 $ — aucun broadcast) "
                  f"[sponsor {sponsor_share:.2f} $ / Ismail {ismail_share:.2f} $]")
        else:
            print(f"[dry-run] SKIP {r.symbol} spread {r.spread_pct:.1f}% "
                  f"net {r.expected_net_usd:.2f} $ [provider {r.provider}] "
                  f"— raisons : {'; '.join(r.reasons)} "
                  f"— gas payé : 0 $ "
                  f"[sponsor {sponsor_share:.2f} $ / Ismail {ismail_share:.2f} $]")
    return results


if __name__ == "__main__":
    from scanner import MemeCandidate
    costs = Costs()  # v2 : gas unifié (0,0675 $), min profit 3 $
    # 1) Gagnant : spread 20 %, petites pools
    win = MemeCandidate("0xAAA", "MEME-WIN", "aerodrome", "uniswap",
                        Pool("Aero", 20_000, 20_000_000),
                        Pool("UniV2", 18_000, 15_000_000),
                        liquidity_usd=36_000, holders=150, age_hours=10)
    # 2) Perdant : spread 2 % seulement
    lose = MemeCandidate("0xBBB", "MEME-LOSE", "aerodrome", "uniswap",
                         Pool("Aero", 50_000, 50_000_000),
                         Pool("UniV2", 50_000, 49_000_000),
                         liquidity_usd=100_000, holders=200, age_hours=5)
    run([win, lose], costs)
