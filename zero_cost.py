"""
zero_cost.py — Mode $0 TOTAL (Ismail, 2026-11-24) : Ismail paie 0 $, pas
même 1 $. Chaque coût a une solution $0, sinon le trade est BLOQUÉ.

v3.4 — INTERRUPTEUR DE MODE (décision d'Ismail 2026-11-24) : Ismail
finance le gas LUI-MÊME (~20 $ float). La contrainte $0 TOTAL est donc
LEVÉE pour le GAS SEULEMENT. Le garde a maintenant deux modes :
  - "zero_cost" (ancien comportement, sponsor) : Ismail paie 0,00 $,
    gas sponsor ou crédits CDP, kill switch à la moindre charge.
  - "self_funded" (NOUVEAU défaut, lu depuis la section `funding:` de
    config.yaml) : le gas sort du FLOAT d'Ismail (self_funded.py) —
    le garde vérifie que le float couvre le PIRE CAS (gas + budget
    revert) et que le net simulé reste >= 3 $ APRÈS gas + prime.
    Le flash loan reste Morpho 0 % SEULEMENT dans les deux modes :
    Aave (0,05 %) est BLOQUÉ partout, et Balancer est MORT (BIP-928).
  Le mode par défaut du BOT est désormais "self_funded" (config.yaml
  `funding.payer == "ismail"`). Le mode "zero_cost" reste disponible
  (construire le garde avec mode="zero_cost") pour les tests et le
  cas sponsor.

La règle, en clair (mode zero_cost) :
  - Ismail ne paie JAMAIS rien : ni gas, ni prime de flash loan, ni RPC,
    ni infra, ni rien d'autre. `ismail_paid_usd` doit rester 0,00 $ dans
    TOUS les scénarios — c'est une contrainte DURE (config.yaml,
    `ismail_pays_usd_max: 0.0`), pas un objectif.
  - Flash loan : Morpho Blue 0 % SEULEMENT. Aave (0,05 %) est BLOQUÉ en mode
    $0 : sa prime mangerait du profit qui appartient à Ismail / au
    sponsor. Un trade qui retomberait sur Aave (loan trop gros pour
    Morpho) est SKIPPÉ avec la raison explicite "ZERO_COST".
    (v3.3 : Balancer MORT — BIP-928, wind-down 30 oct 2026 — remplacé
    par Morpho, même fee 0 % mais par conception, pas par gouvernance.)
  - Gas : payé par le prefund SPONSOR (20 $), jamais par Ismail. Repli
    prévu : crédits Paymaster Coinbase (CDP) 1 000 $ — EN ATTENTE
    (demande envoyée 21 nov 18:52, aucune réponse au 24 nov 19:53) :
    tant que ce n'est pas approuvé, "cdp-credits" est BLOQUÉ aussi.
  - RPC : Alchemy free tier (Base-Bot, déjà dans config.yaml).
  - Infra : 0 $ (VM Muse, cron, GitHub, Foundry, Anvil).
  - Kill switch : si UNE SEULE charge à Ismail est détectée (même 0,01 $),
    le garde se déclenche et BLOQUE TOUS les trades suivants — on
    n'attend pas de comprendre pourquoi, on arrête d'abord.

Ce que ce module NE fait PAS : il ne rend pas un revert on-chain
gratuit. Un revert broadcasté coûte son gas (mesuré en fork :
0,0046 $) — ce gas sort du prefund sponsor (mode $0) ou du float
d'Ismail (mode self_funded), et le circuit breaker arrête le bot
après 3 reverts. Le $0 d'Ismail (mode $0) tient parce que (1) les
perdants sont SKIPPÉS avant broadcast (0 gas), (2) le gas des
gagnants ET des reverts vient du prefund sponsor.
Voir ZERO_COST_PRIVATE.md §3.2 : le $0 garanti sur un revert on-chain
est IMPOSSIBLE sur Base aujourd'hui — le résiduel est plafonné et payé
par le sponsor (mode $0) ou par le float (mode self_funded), jamais
par surprise.

Audit : UN SEUL coût sans solution $0 aujourd'hui — l'audit professionnel
payant. Le live reste BLOQUÉ tant qu'il n'est pas financé (sponsor ou
profits futurs). En attendant : Slither/Aderyn (gratuits) + revue
manuelle, et le bot reste en simulation (dry_run).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

from math_engine import FLASH_FEE_BY_PROVIDER

# Frais de flash loan par provider (source unique : math_engine.py).
# Morpho 0 % par conception (vérifié 2026-11-24) ; Aave 0,05 %.
ALLOWED_PROVIDERS_DEFAULT = ("morpho",)

# Statut connu de la demande de crédits CDP au 2026-11-24 19:53 :
# demande envoyée 21 nov 18:52, aucune réponse d'approbation/refus.
CDP_CREDITS_APPROVED = False


def _round_usd(x: float) -> float:
    """Arrondi au micro-dollar (6 décimales) — précision comptable interne
    (audit #9). Un gas de 0,0044 $ survit : 100 charges = 0,44 $, pas 0 $.
    L'arrondi au centime n'a lieu qu'à l'AFFICHAGE (format :.2f) ou pour
    les partages de paiement (en cents)."""
    v = round(float(x) + 1e-12, 6)
    return 0.0 if v == 0 else v


def _round2(x: float) -> float:
    """Arrondi au centime — AFFICHAGE UNIQUEMENT. Ne JAMAIS l'utiliser
    pour accumuler des coûts (audit #9)."""
    v = round(float(x) + 1e-9, 2)
    return 0.0 if v == 0 else v


@dataclass
class ZeroCostGuard:
    """Garde $0 : chaque trade EXECUTE doit passer par check_zero_cost().
    Le moindre dollar facturé à Ismail déclenche le kill switch (mode
    "zero_cost"). En mode "self_funded" (v3.4, défaut du bot), le gas
    sort du float d'Ismail : le garde vérifie que le float couvre le
    pire cas (gas + budget revert) et que le net reste >= 3 $ APRÈS
    gas + prime — le flash loan reste Morpho 0 % seulement."""
    enabled: bool = True
    mode: str = "zero_cost"         # "zero_cost" (sponsor) | "self_funded" (float Ismail)
    ismail_pays_usd_max: float = 0.0   # contrainte DURE (mode zero_cost)
    allowed_flash_providers: Tuple[str, ...] = ALLOWED_PROVIDERS_DEFAULT
    rpc: str = "alchemy-free"
    gas_payer: str = "sponsor"          # "sponsor" | "cdp-credits" | "ismail" (self_funded)
    cdp_credits_approved: bool = CDP_CREDITS_APPROVED
    infra_cost_usd: float = 0.0
    trades_path: Optional[str] = None   # trades.jsonl (ledger)

    # --- état ---
    ismail_paid_usd: float = 0.0       # DOIT rester 0,00 $ — toujours
    tripped: bool = False               # kill switch déclenché ?
    trip_reason: str = ""
    trades_checked: int = 0
    trades_blocked: int = 0

    # ------------------------------------------------------------------ kill switch
    def charge_ismail(self, amount_usd: float, why: str = "") -> bool:
        """Enregistre une charge à Ismail. Retourne False et DÉCLENCHE le
        kill switch dès que amount > 0 (même 0,01 $) : on arrête tout
        avant de comprendre. amount == 0 : rien ne se passe (cas normal)."""
        amount = _round_usd(amount_usd)
        if amount <= 0:
            return True
        self.ismail_paid_usd = _round_usd(self.ismail_paid_usd + amount)
        self.tripped = True
        self.trip_reason = (f"CHARGE ISMAIL DÉTECTÉE : {amount:.2f} $ "
                            f"({why or 'raison inconnue'}) — kill switch, "
                            f"tous les trades bloqués")
        return False

    # ------------------------------------------------------------------ décisions
    def check_zero_cost(self, trade: Dict) -> Tuple[bool, str]:
        """Décide si UN trade peut être exécuté.
        Mode "zero_cost" (sponsor) : Ismail paie 0,00 $ — gas sponsor/CDP,
        kill switch à la moindre charge.
        Mode "self_funded" (v3.4) : gas payé par Ismail depuis son float —
        le float doit couvrir le pire cas (gas + budget revert) et le net
        doit rester >= min_profit $ APRÈS gas + prime. Morpho 0 % seulement
        dans les deux modes.
        trade : dict avec provider, flash_fee_rate (ou flash_fee_usd),
        gas_usd, gas_payer, ismail_cost_usd, prefund_remaining_usd
        (mode $0) / float_remaining_usd + min_profit_usd +
        revert_budget_usd (mode self_funded).
        Retourne (autorisé, raison). BLOQUÉ = SKIP avec raison explicite
        "ZERO_COST: ..." ou "SELF_FUNDED: ..." — jamais un trade silencieux."""
        self.trades_checked += 1
        if not self.enabled:
            return True, "mode $0 désactivé — garde inactive"
        if self.tripped:
            self.trades_blocked += 1
            return False, f"ZERO_COST: kill switch — {self.trip_reason}"
        provider = (trade.get("provider") or "").lower()
        # Prime du trade (calculée si absente du dict : loan × taux).
        flash_fee_usd = _round_usd(trade.get("flash_fee_usd",
                                          trade.get("loan_usd", 0.0)
                                          * trade.get("flash_fee_rate", 0.0)))
        net_usd = trade.get("expected_net_usd", 0.0)
        if provider not in self.allowed_flash_providers:
            fee_rate = trade.get("flash_fee_rate")
            if fee_rate is None:
                fee_rate = FLASH_FEE_BY_PROVIDER.get(provider, 0.0)
            self.trades_blocked += 1
            return False, (f"ZERO_COST: provider '{provider}' interdit en mode "
                           f"$0 (prime {fee_rate:.2%} — seule Morpho 0 % est "
                           f"autorisée) — Ismail paierait "
                           f"{flash_fee_usd:.2f} $ "
                           f"de prime")
        # Prime > 0 même chez un provider "autorisé" : bloqué, sauf si la
        # prime est entièrement couverte par le profit du trade lui-même
        # (elle sort alors du profit, pas de la poche d'Ismail).
        if flash_fee_usd > 0 and flash_fee_usd > max(net_usd, 0.0):
            self.trades_blocked += 1
            return False, (f"ZERO_COST: prime flash {flash_fee_usd:.2f} $ non "
                           f"couverte par le profit net {net_usd:.2f} $ — "
                           f"Ismail paierait la différence")
        # v3.4 — MODE SELF_FUNDED : le gas sort du float d'Ismail. La
        # contrainte $0 est levée pour le gas SEULEMENT : le garde vérifie
        # que le float couvre le PIRE CAS (gas + budget revert, par défaut
        # 2 × gas) et que le net simulé reste >= 3 $ APRÈS gas + prime
        # (le net de decide() est déjà net de gas et de prime).
        if (self.mode or "zero_cost").lower() == "self_funded":
            return self._check_self_funded(trade, net_usd)
        # Gas : qui paie ? Jamais Ismail. Sponsor = prefund ; CDP = crédits
        # (bloqués tant que la demande n'est pas approuvée).
        gas_usd = _round_usd(trade.get("gas_usd", 0.0))
        gas_payer = (trade.get("gas_payer") or self.gas_payer).lower()
        if gas_payer == "ismail":
            self.trades_blocked += 1
            return False, (f"ZERO_COST: gas {gas_usd:.2f} $ à la charge "
                           f"d'Ismail — interdit (max 0,00 $)")
        if gas_payer == "cdp-credits" and not self.cdp_credits_approved:
            self.trades_blocked += 1
            return False, ("ZERO_COST: crédits CDP non approuvés (demande du "
                           "21 nov, aucune réponse au 24 nov) — gas "
                           f"{gas_usd:.2f} $ sans payeur $0, trade bloqué")
        if gas_payer == "sponsor":
            prefund = trade.get("prefund_remaining_usd")
            if prefund is not None and gas_usd > prefund:
                self.trades_blocked += 1
                return False, (f"ZERO_COST: gas {gas_usd:.2f} $ > prefund "
                               f"sponsor restant {prefund:.2f} $ — Ismail "
                               f"ne paiera pas la différence, trade bloqué")
        elif gas_payer not in ("sponsor", "cdp-credits"):
            self.trades_blocked += 1
            return False, f"ZERO_COST: payeur de gas inconnu '{gas_payer}'"
        # Toute autre ligne de coût à la charge d'Ismail.
        ismail_cost = _round_usd(trade.get("ismail_cost_usd", 0.0))
        if ismail_cost > self.ismail_pays_usd_max:
            self.trades_blocked += 1
            return False, (f"ZERO_COST: Ismail paierait {ismail_cost:.2f} $ "
                           f"(max {self.ismail_pays_usd_max:.2f} $) — trade bloqué")
        return True, "OK $0 — Ismail paie 0,00 $"

    def _check_self_funded(self, trade: Dict, net_usd: float) -> Tuple[bool, str]:
        """Branche v3.4 : gas payé par Ismail depuis son float. Le trade
        n'est autorisé que si (1) le payeur est bien Ismail, (2) le float
        couvre le pire cas (gas + budget revert), (3) le net simulé reste
        >= min_profit $ APRÈS gas + prime. Le flash loan reste Morpho 0 %
        (vérifié par l'appelant, avant cette branche)."""
        gas_usd = _round_usd(trade.get("gas_usd", 0.0))
        gas_payer = (trade.get("gas_payer") or self.gas_payer).lower()
        if gas_payer != "ismail":
            self.trades_blocked += 1
            return False, (f"SELF_FUNDED: gas payé par '{gas_payer}' — en "
                           f"mode autofinancé le gas sort du float d'Ismail, "
                           f"pas d'un sponsor/CDP")
        float_remaining = trade.get("float_remaining_usd")
        if float_remaining is None:
            self.trades_blocked += 1
            return False, ("SELF_FUNDED: float restant inconnu — impossible "
                           "de vérifier que le gas est couvert, trade bloqué")
        revert_budget = trade.get("revert_budget_usd")
        if revert_budget is None:
            revert_budget = gas_usd  # un revert coûte ~ le même gas que le trade
        worst = _round_usd(gas_usd + _round_usd(revert_budget))
        if worst > _round_usd(float_remaining):
            self.trades_blocked += 1
            return False, (f"SELF_FUNDED: pire cas {worst:.2f} $ (gas "
                           f"{gas_usd:.2f} $ + budget revert "
                           f"{_round_usd(revert_budget):.2f} $) > float restant "
                           f"{_round_usd(float_remaining):.2f} $ — trade bloqué, "
                           f"Ismail ne trade pas à découvert")
        min_profit = trade.get("min_profit_usd", 3.0)
        if net_usd <= min_profit:
            self.trades_blocked += 1
            return False, (f"SELF_FUNDED: net {net_usd:.2f} $ <= min "
                           f"{min_profit:.2f} $ APRÈS gas + prime — trade bloqué")
        # Coût hors-gas à la charge d'Ismail : toujours interdit (le float
        # ne couvre QUE le gas, pas d'autres frais surprises).
        ismail_cost = _round_usd(trade.get("ismail_cost_usd", 0.0))
        if ismail_cost > 0:
            self.trades_blocked += 1
            return False, (f"SELF_FUNDED: coût hors-gas {ismail_cost:.2f} $ à "
                           f"la charge d'Ismail — le float ne couvre que le gas")
        return True, (f"OK self-funded — gas {gas_usd:.2f} $ sur le float "
                      f"d'Ismail (restant {_round_usd(float_remaining):.2f} $), "
                      f"net {net_usd:.2f} $ après gas, Ismail garde 100 %")

    # ------------------------------------------------------------------ ledger
    def append_ledger(self, symbol: str, net_usd: float, gas_usd: float = 0.0,
                      provider: str = "", simulated: bool = True) -> Dict:
        """Écrit une ligne dans trades.jsonl avec ismail_paid_usd (toujours
        0,00 $ en mode $0) — la preuve, trade par trade, qu'Ismail n'a
        rien payé. Utilisé quand aucun sponsor n'est branché (sinon c'est
        sponsor.record_trade qui écrit la ligne, avec extra)."""
        entry = {"date": date.today().isoformat(), "symbol": symbol,
                 "action": "EXECUTE", "net_usd": _round_usd(net_usd),
                 "gas_usd": _round_usd(gas_usd), "provider": provider,
                 "blocked": False, "simulated": simulated,
                 "zero_cost": True, "ismail_paid_usd": _round_usd(self.ismail_paid_usd)}
        if self.trades_path:
            with open(self.trades_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def status(self) -> Dict:
        return {"enabled": self.enabled,
                "mode": self.mode,
                "ismail_pays_usd_max": self.ismail_pays_usd_max,
                "ismail_paid_usd": _round_usd(self.ismail_paid_usd),
                "allowed_flash_providers": list(self.allowed_flash_providers),
                "rpc": self.rpc, "gas_payer": self.gas_payer,
                "cdp_credits_approved": self.cdp_credits_approved,
                "infra_cost_usd": self.infra_cost_usd,
                "tripped": self.tripped, "trip_reason": self.trip_reason,
                "trades_checked": self.trades_checked,
                "trades_blocked": self.trades_blocked}


def trade_from_result(result, gas_payer: str = "sponsor",
                      prefund_remaining_usd: Optional[float] = None,
                      cdp_credits_approved: bool = CDP_CREDITS_APPROVED,
                      float_remaining_usd: Optional[float] = None,
                      min_profit_usd: float = 3.0,
                      revert_budget_usd: Optional[float] = None) -> Dict:
    """Construit le dict trade attendu par check_zero_cost() depuis un
    SimulationResult de l'executor (provider, loan, net, gas).
    v3.4 : float_remaining_usd (mode self_funded) + min_profit_usd +
    revert_budget_usd (défaut = gas_usd) pour la branche autofinancée."""
    fee_rate = FLASH_FEE_BY_PROVIDER.get((result.provider or "").lower(), 0.0)
    return {"provider": result.provider,
            "flash_fee_rate": fee_rate,
            "flash_fee_usd": _round_usd(result.loan_usd * fee_rate),
            "loan_usd": result.loan_usd,
            "expected_net_usd": result.expected_net_usd,
            "gas_usd": result.gas_usd,
            "gas_payer": gas_payer,
            "prefund_remaining_usd": prefund_remaining_usd,
            "float_remaining_usd": float_remaining_usd,
            "min_profit_usd": min_profit_usd,
            "revert_budget_usd": revert_budget_usd,
            "ismail_cost_usd": 0.0,
            "cdp_credits_approved": cdp_credits_approved}


def load_from_config(path: Optional[str] = None) -> "ZeroCostGuard":
    """Lit la section de config.yaml (audit #13 : chemin par
    argument, sinon variable d'environnement CODEMA_CONFIG,
    sinon "config.yaml")."""
    path = path or os.environ.get("CODEMA_CONFIG") or "config.yaml"
    """Lit la section `zero_cost:` de config.yaml (parseur simple, sans
    dépendance YAML — comme sponsor.load_from_config).
    v3.4 : lit AUSSI la section `funding:` — si `funding.payer ==
    "ismail"`, le mode du garde devient "self_funded" (le BOT est en
    autofinancé par défaut). La section `zero_cost:` elle-même reste
    inchangée (gas_payer "sponsor" = mode $0 historique)."""
    text = Path(path).read_text()
    m = re.search(r"^zero_cost:\n((?:[ \t]+\S.*\n?)+)", text, re.M)
    params: Dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s+([a-z_]+):\s*(.*?)\s*(?:#.*)?$", line)
            if mm:
                params[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    # v3.4 : section `funding:` — décide du mode par défaut du garde.
    fm = re.search(r"^funding:\n((?:[ \t]+\S.*\n?)+)", text, re.M)
    funding_payer = ""
    if fm:
        for line in fm.group(1).splitlines():
            mm = re.match(r"\s+payer:\s*(.*?)\s*(?:#.*)?$", line)
            if mm:
                funding_payer = mm.group(1).strip().strip('"').strip("'")
    mode = "self_funded" if funding_payer.lower() == "ismail" else "zero_cost"
    def _f(key, default):
        try:
            return float(params.get(key, default))
        except ValueError:
            return default
    def _b(key, default):
        return params.get(key, str(default)).lower() in ("true", "yes", "1")
    providers = re.findall(r'"([^"]+)"', params.get("allowed_flash_providers", ""))
    if not providers:
        providers = [p.strip() for p in
                     params.get("allowed_flash_providers", "morpho")
                     .strip("[]").split(",") if p.strip()]
    return ZeroCostGuard(
        enabled=_b("enabled", True),
        mode=mode,
        ismail_pays_usd_max=_f("ismail_pays_usd_max", 0.0),
        allowed_flash_providers=tuple(p.lower() for p in providers) or ("morpho",),
        rpc=params.get("rpc", "alchemy-free"),
        gas_payer=params.get("gas_payer", "sponsor"),
        cdp_credits_approved=_b("cdp_credits_approved", CDP_CREDITS_APPROVED),
        infra_cost_usd=_f("infra_cost_usd", 0.0),
        trades_path=params.get("trades_file", "trades.jsonl") or None,
    )


if __name__ == "__main__":
    g = load_from_config("config.yaml")
    print("Statut :", g.status())
    ok, why = g.check_zero_cost({"provider": "morpho", "flash_fee_rate": 0.0,
                                 "loan_usd": 790.16, "expected_net_usd": 73.07,
                                 "gas_usd": 0.0066, "gas_payer": "sponsor",
                                 "prefund_remaining_usd": 20.0,
                                 "ismail_cost_usd": 0.0})
    print("Morpho 790 $ :", ok, "—", why)
    ok, why = g.check_zero_cost({"provider": "aave", "flash_fee_rate": 0.0005,
                                 "loan_usd": 790.16, "expected_net_usd": 72.68,
                                 "gas_usd": 0.0066, "gas_payer": "sponsor",
                                 "prefund_remaining_usd": 20.0,
                                 "ismail_cost_usd": 0.0})
    print("Aave 790 $ :", ok, "—", why)
    print("Ismail payé :", g.ismail_paid_usd, "$")
