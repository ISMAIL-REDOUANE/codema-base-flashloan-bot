"""
self_funded.py — Mode GAS AUTOFINANCÉ (v3.4, décision d'Ismail 2026-11-24) :
Ismail finance le gas lui-même (~20 $ d'ETH, float sur Base) et garde
100 % du profit (part sponsor 0 %).

Ce qui change par rapport au mode $0 TOTAL (v3.2) :
  - La contrainte 0 $ TOTAL est LEVÉE pour le GAS SEULEMENT. Le flash
    loan reste 0 % (Morpho Blue uniquement, Aave 0,05 % toujours BLOQUÉ)
    et l'audit payant reste le seul coût sans solution.
  - Le gas sort du FLOAT d'Ismail (20 $), jamais d'un sponsor (il n'y
    en a plus : section `sponsorship:` INACTIVE en config.yaml).
  - Ismail garde 100 % du net : split (0,00 $ sponsor / net Ismail).
  - Le wallet d'Ismail n'est PAS créé ici et AUCUNE clé privée n'est
    demandée, lue ou stockée : l'adresse PUBLIQUE viendra d'Ismail plus
    tard. Ce module ne fait que de la COMPTABILITÉ (simulation).

Le FloatLedger, en clair :
  - float_usd : ce qu'Ismail a mis (20,00 $ par défaut).
  - ismail_paid_usd : le gas DÉPENSÉ (cumulé, arrondi au centime).
  - profits_usd : les profits NETS cumulés des trades EXECUTE.
  - float_remaining_usd = float_usd - ismail_paid_usd. Les profits ne
    rechargent PAS le float : le profit arrive en USDC, le gas se paie
    en ETH — la conversion est une action manuelle d'Ismail, pas du bot.
  - can_afford(gas) : le trade n'est autorisé que si le float couvre
    le PIRE CAS = gas du trade + budget revert (un revert coûte environ
    le même gas que le trade, donc par défaut : 2 × gas). Sous ce seuil,
    le trade est BLOQUÉ avec une raison explicite — jamais de trade qui
    dépasserait le float.
  - Kill switch : quand le float atteint 0,00 $, TOUS les trades
    s'arrêtent (tripped=True, raison claire) — il faut recharger le
    float (top_up) ou arrêter. Le bot ne trade jamais à découvert.
  - Chaque trade EXECUTE est enregistré dans trades.jsonl avec
    funding_mode "self_funded", ismail_paid_usd (cumulé), le float
    restant, et le partage 100/0 — la preuve, trade par trade, que
    le gas vient du float et que le profit est 100 % à Ismail.

Gas mesuré (fork Base, 2026-11-24) : trade gagnant 0,0042–0,0052 $,
revert 0,0040–0,0046 $ (à 0,0049 gwei). Modèle Costs : 0,0675 $/trade
(450 000 unités × 0,05 gwei × 3 000 $). Plafond 2 gwei : 2,70 $/trade.
À 20 $ : ~4 000 trades au gas mesuré, ~296 au gas modèle, 7 au plafond.
Le float n'est donc pas la contrainte : ce sont les opportunités.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

DEFAULT_FLOAT_USD = 20.0
DEFAULT_SPONSOR_SHARE_PCT = 0.0
DEFAULT_MIN_PROFIT_USD = 3.0
DEFAULT_LOW_FLOAT_ALERT_USD = 5.0


def _round2(x: float) -> float:
    """Arrondi au centime, avec -0.0 ramené à 0.0."""
    v = round(float(x) + 1e-9, 2)
    return 0.0 if v == 0 else v


@dataclass
class FloatLedger:
    """Grand livre du float gas d'Ismail : comptabilité + garde-fous."""
    payer: str = "ismail"
    float_usd: float = DEFAULT_FLOAT_USD
    sponsor_share_pct: float = DEFAULT_SPONSOR_SHARE_PCT  # 0 = Ismail 100 %
    gas_payer: str = "ismail"
    min_profit_usd: float = DEFAULT_MIN_PROFIT_USD
    low_float_alert_usd: float = DEFAULT_LOW_FLOAT_ALERT_USD
    state_path: Optional[str] = None       # float_state.json (persisté)
    trades_path: Optional[str] = None      # trades.jsonl (append-only)

    # --- état (persisté) ---
    day: str = field(default_factory=lambda: date.today().isoformat())
    ismail_paid_usd: float = 0.0           # gas dépensé (cumulé)
    profits_usd: float = 0.0               # profits NETS cumulés (EXECUTE)
    trades_executed: int = 0
    trades_blocked: int = 0
    tripped: bool = False                   # kill switch float à 0 ?
    trip_reason: str = ""

    def __post_init__(self):
        if self.state_path:
            self.load()

    # ------------------------------------------------------------------ persistance
    def save(self):
        if not self.state_path:
            return
        data = {"day": self.day, "payer": self.payer,
                "float_usd": self.float_usd,
                "ismail_paid_usd": _round2(self.ismail_paid_usd),
                "profits_usd": _round2(self.profits_usd),
                "trades_executed": self.trades_executed,
                "trades_blocked": self.trades_blocked,
                "tripped": self.tripped, "trip_reason": self.trip_reason,
                "sponsor_share_pct": self.sponsor_share_pct,
                "min_profit_usd": self.min_profit_usd}
        Path(self.state_path).write_text(json.dumps(data, indent=2))

    def load(self):
        try:
            data = json.loads(Path(self.state_path).read_text())
        except Exception:
            return
        self.day = data.get("day", self.day)
        self.ismail_paid_usd = data.get("ismail_paid_usd", 0.0)
        self.profits_usd = data.get("profits_usd", 0.0)
        self.trades_executed = data.get("trades_executed", 0)
        self.trades_blocked = data.get("trades_blocked", 0)
        self.tripped = data.get("tripped", False)
        self.trip_reason = data.get("trip_reason", "")
        self.float_usd = data.get("float_usd", self.float_usd)
        self.sponsor_share_pct = data.get("sponsor_share_pct",
                                          self.sponsor_share_pct)

    # ------------------------------------------------------------------ float
    @property
    def float_remaining_usd(self) -> float:
        """Ce qui reste du float après le gas dépensé. Les profits ne le
        rechargent PAS (USDC ≠ ETH gas — conversion manuelle d'Ismail)."""
        return _round2(self.float_usd - self.ismail_paid_usd)

    def float_low(self) -> bool:
        """True quand le float restant est sous le seuil d'alerte (< 5 $)."""
        return self.float_remaining_usd < self.low_float_alert_usd

    def float_alert(self) -> Optional[str]:
        if self.float_low():
            return (f"ALERTE float bas : il reste {self.float_remaining_usd:.2f} $ "
                    f"(seuil {self.low_float_alert_usd:.2f} $) — recharger le "
                    f"float ou le bot s'arrêtera à 0 $")
        return None

    def worst_case_cost(self, gas_usd: float,
                        revert_budget_usd: Optional[float] = None) -> float:
        """Pire cas pour UN trade : gas du trade + budget revert (un revert
        coûte environ le même gas que le trade, donc par défaut : 2 × gas)."""
        gas = _round2(gas_usd)
        revert = gas if revert_budget_usd is None else _round2(revert_budget_usd)
        return _round2(gas + revert)

    # ------------------------------------------------------------------ partage
    def split_profit(self, net_usd: float) -> Tuple[float, float]:
        """(part sponsor, part Ismail). sponsor_share_pct = 0 -> Ismail 100 %.
        net <= 0 -> (0, 0) : pas de profit, pas de partage."""
        if net_usd is None or net_usd <= 0:
            return (0.0, 0.0)
        sponsor = _round2(net_usd * self.sponsor_share_pct / 100.0)
        ismail = _round2(net_usd - sponsor)
        return (sponsor, ismail)

    # ------------------------------------------------------------------ décisions
    def can_afford(self, gas_usd: float,
                   revert_budget_usd: Optional[float] = None) -> Tuple[bool, str]:
        """Le float couvre-t-il le PIRE CAS (gas + budget revert) ?
        Non -> trade BLOQUÉ avec raison explicite, jamais de trade à découvert."""
        if self.tripped:
            self.trades_blocked += 1
            return False, f"SELF_FUNDED: kill switch — {self.trip_reason}"
        worst = self.worst_case_cost(gas_usd, revert_budget_usd)
        remaining = self.float_remaining_usd
        if remaining <= 0:
            self._trip(f"float épuisé ({remaining:.2f} $ restants) — recharger "
                       f"{self.float_usd:.2f} $ ou arrêter")
            self.trades_blocked += 1
            return False, f"SELF_FUNDED: kill switch — {self.trip_reason}"
        if worst > remaining:
            self.trades_blocked += 1
            return False, (f"SELF_FUNDED: pire cas {worst:.2f} $ (gas "
                           f"{_round2(gas_usd):.2f} $ + budget revert) > float "
                           f"restant {remaining:.2f} $ — trade bloqué, Ismail "
                           f"ne trade pas à découvert")
        return True, "OK"

    def _trip(self, reason: str):
        self.tripped = True
        self.trip_reason = reason
        self.save()

    def charge_gas(self, gas_usd: float) -> bool:
        """Déduit le gas du float. Retourne False et DÉCLENCHE le kill
        switch si le float tombe à 0 (ou moins) : on arrête tout."""
        gas = _round2(gas_usd)
        if gas <= 0:
            return True
        self.ismail_paid_usd = _round2(self.ismail_paid_usd + gas)
        self.save()
        if self.float_remaining_usd <= 0:
            self._trip(f"float épuisé après {gas:.2f} $ de gas "
                       f"(dépensé total {self.ismail_paid_usd:.2f} $) — "
                       f"recharger {self.float_usd:.2f} $ ou arrêter")
            return False
        return True

    # ------------------------------------------------------------------ enregistrement
    def record_trade(self, symbol: str, net_usd: float, gas_usd: float = 0.0,
                     provider: str = "", action: str = "EXECUTE",
                     simulated: bool = False,
                     extra: Optional[Dict] = None) -> Dict:
        """Enregistre un trade EXÉCUTÉ : gas déduit du float (pire cas
        vérifié avant), profit ajouté aux profits, partage 100/0.
        `gas_usd` = gas SIMULÉ en dry-run (r.gas_usd, pas gas_paid_usd
        qui vaut 0,00 $ sans broadcast) — la comptabilité dry-run
        reflète ce que le live coûterait. Retourne l'entrée (avec
        'blocked' si le float ne couvre pas le pire cas — dans ce cas
        RIEN n'est déduit ni enregistré, le trade ne doit pas avoir lieu).
        Les SKIP ne passent pas ici : 0 $ / 0 $, rien à enregistrer."""
        sponsor, ismail = self.split_profit(net_usd)
        ok, reason = self.can_afford(gas_usd)
        if not ok:
            return {"symbol": symbol, "action": action, "blocked": True,
                    "reason": reason, "net_usd": _round2(net_usd),
                    "sponsor_share_usd": sponsor, "ismail_share_usd": ismail,
                    "gas_usd": _round2(gas_usd), "provider": provider,
                    "funding_mode": "self_funded",
                    "ismail_paid_usd": _round2(self.ismail_paid_usd),
                    "float_remaining_usd": self.float_remaining_usd,
                    "profits_usd": _round2(self.profits_usd)}
        self.charge_gas(gas_usd)
        if net_usd > 0:
            self.profits_usd = _round2(self.profits_usd + net_usd)
        self.trades_executed += 1
        entry = {"date": self.day, "symbol": symbol, "action": action,
                 "net_usd": _round2(net_usd), "sponsor_share_usd": sponsor,
                 "ismail_share_usd": ismail, "gas_usd": _round2(gas_usd),
                 "provider": provider, "blocked": False,
                 "simulated": simulated,  # True en dry-run : 0 $ réel, jamais dû
                 "funding_mode": "self_funded",
                 "ismail_paid_usd": _round2(self.ismail_paid_usd),
                 "float_remaining_usd": self.float_remaining_usd,
                 "profits_usd": _round2(self.profits_usd)}
        if extra:
            entry.update(extra)
        if self.trades_path:
            with open(self.trades_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        self.save()
        return entry

    def top_up(self, amount_usd: float) -> float:
        """Recharge du float (Ismail remet de l'ETH). Remet le kill
        switch à zéro si le float redevient positif. Retourne le reste."""
        self.float_usd = _round2(self.float_usd + amount_usd)
        if self.float_remaining_usd > 0 and self.tripped:
            self.tripped = False
            self.trip_reason = ""
        self.save()
        return self.float_remaining_usd

    def float_status_line(self) -> str:
        """La ligne affichée par dry_run.py — une seule source de vérité."""
        return (f"FINANCEMENT : Ismail — float {self.float_usd:.2f} $ / "
                f"dépensé {self.ismail_paid_usd:.2f} $ / "
                f"restant {self.float_remaining_usd:.2f} $ / "
                f"profit {self.profits_usd:.2f} $")

    def status(self) -> Dict:
        # Lecture seule : aucun effet de bord (pas de trip, pas de compteur).
        remaining = self.float_remaining_usd
        if self.tripped:
            ok, reason = False, f"kill switch — {self.trip_reason}"
        elif remaining <= 0:
            ok, reason = False, "float épuisé — recharger ou arrêter"
        else:
            ok, reason = True, "OK"
        return {"payer": self.payer, "funding_mode": "self_funded",
                "float_usd": self.float_usd,
                "float_remaining_usd": remaining,
                "ismail_paid_usd": _round2(self.ismail_paid_usd),
                "profits_usd": _round2(self.profits_usd),
                "sponsor_share_pct": self.sponsor_share_pct,
                "min_profit_usd": self.min_profit_usd,
                "trades_executed": self.trades_executed,
                "trades_blocked": self.trades_blocked,
                "low_float_alert": self.float_alert(),
                "kill_switch": self.tripped, "trip_reason": self.trip_reason,
                "can_trade": ok, "reason": reason}


def load_from_config(path: str = "config.yaml") -> "FloatLedger":
    """Lit la section `funding:` de config.yaml (parseur simple, sans
    dépendance YAML — comme sponsor.load_from_config)."""
    text = Path(path).read_text()
    m = re.search(r"^funding:\n((?:[ \t]+\S.*\n?)+)", text, re.M)
    params: Dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s+([a-z_]+):\s*(.*?)\s*(?:#.*)?$", line)
            if mm:
                params[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")

    def _f(key, default):
        try:
            return float(params.get(key, default))
        except ValueError:
            return default

    return FloatLedger(
        payer=params.get("payer", "ismail"),
        float_usd=_f("float_usd", DEFAULT_FLOAT_USD),
        sponsor_share_pct=_f("sponsor_share_pct", DEFAULT_SPONSOR_SHARE_PCT),
        gas_payer=params.get("gas_payer", "ismail"),
        min_profit_usd=_f("min_profit_usd", DEFAULT_MIN_PROFIT_USD),
        low_float_alert_usd=_f("low_float_alert_usd", DEFAULT_LOW_FLOAT_ALERT_USD),
        state_path=params.get("state_file", "float_state.json") or None,
        trades_path=params.get("trades_file", "trades.jsonl") or None,
    )


if __name__ == "__main__":
    f = FloatLedger()
    print("Statut :", f.status())
    print(f.float_status_line())
    for net in (100.0, 73.07, 0.0):
        print(f"net {net:.2f} $ -> sponsor {f.split_profit(net)[0]:.2f} $ / "
              f"Ismail {f.split_profit(net)[1]:.2f} $")
    print("Trade 73,07 $ (gas 0,0066 $) :",
          f.record_trade("MEME-WIN", 73.07, 0.0066, "morpho"))
    print("Après :", f.float_status_line())
    print("Pire cas gas 0,07 $ :", f.worst_case_cost(0.07), "$")
    print("can_afford(0,07 $) :", f.can_afford(0.07))
