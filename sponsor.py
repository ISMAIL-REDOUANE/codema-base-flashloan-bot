"""
sponsor.py — Modèle sponsor (Ismail, 2026-11-24) : le sponsor préfinance
le gas, il prend 25 % du profit net.

Le deal, en clair :
  - Le sponsor met ~20 $ d'ETH (prefund) dans un wallet dédié : ça ne sert
    QU'À payer le gas des trades. À ~0,008 $ de gas par trade (mesuré live),
    20 $ = ~2 500 trades.
  - Sur chaque trade GAGNANT (net > 0), le profit net est partagé :
    sponsor 25 %, Ismail 75 %. Sur un trade perdant ou SKIP : 0 $ / 0 $,
    personne ne touche rien — la perte, c'est le gas, payé sur le prefund.
  - Plafond journalier sponsor : 20 $/jour. Au-delà, le bot S'ARRÊTE
    (raison claire, pas de trade silencieux) — le sponsor ne paie jamais
    plus que le plafond convenu.
  - Alerte prefund bas : quand il reste < 5 $ de prefund, alerte (il faut
    recharger ou le bot s'arrêtera à 0 $).
  - Kill switch : le sponsor (ou Ismail) peut couper TOUT trade.
  - Ismail peut aussi s'auto-financer : sponsor_share_pct = 0 -> 100 % pour
    lui, le prefund reste le sien (voir config.yaml, section sponsorship:).

v3.4 — AUTOFINANCÉ (décision d'Ismail 2026-11-24) : le deal sponsor est
INACTIF (config.yaml `sponsorship.enabled: false`, part 0 %). Ismail
finance le gas lui-même (voir self_funded.py) et garde 100 % :
  - split_profit(100.0) avec share 0 % -> (0,00 $ sponsor / 100,00 $ Ismail).
  - Un ledger DÉSACTIVÉ (enabled=False) se comporte comme un auto-financé :
    split_profit retourne (0, net) — Ismail 100 %, jamais (0, 0) par erreur.
  - Chaque entrée de ledger porte désormais "funding_mode" ("sponsor" ou
    "self_funded") pour qu'on sache toujours qui a payé le gas.

Règles d'argent (arrondis au centime, le sponsor est arrondi, Ismail
prend le reste : 73,07 $ -> sponsor 18,27 $ / Ismail 54,80 $) :
  - split_profit(net) : net <= 0 -> (0,00 $, 0,00 $) — pas de profit, pas
    de partage. Sinon sponsor = round(net * 25 %, 2), Ismail = net - sponsor.
  - Le gas de chaque trade exécuté est DÉDUIT du prefund (prefund_remaining).
  - Le plafond journalier porte sur ce qui est VERSÉ au sponsor dans la
    journée (la somme des parts sponsor), pas sur le gas.
  - Un trade dont la part sponsor dépasserait le plafond est BLOQUÉ avant
    exécution (raison STOP explicite) — on ne trade jamais au-delà du deal.

État persisté : trades.jsonl (un JSON par trade exécuté) + sponsor_state.json
(soldes du jour, gas cumulé). En dry-run, tout est simulé : 0 $ réel, mais
les parts et le prefund sont calculés exactement comme en live pour que le
sponsor voie les chiffres avant de mettre 1 $.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

DEFAULT_PREFUND_USD = 20.0
DEFAULT_SPONSOR_SHARE_PCT = 25.0
DEFAULT_DAILY_CAP_USD = 20.0
DEFAULT_LOW_PREFUND_ALERT_USD = 5.0


def _round_usd(x: float) -> float:
    """Arrondi au micro-dollar (6 décimales) — précision comptable interne
    (audit #9). Un gas de 0,0044 $ survit : 100 charges = 0,44 $, pas 0 $.
    L'arrondi au centime n'a lieu qu'à l'AFFICHAGE (format :.2f) ou pour
    les partages de paiement (split_profit, en cents)."""
    v = round(float(x) + 1e-12, 6)
    return 0.0 if v == 0 else v


def _round2(x: float) -> float:
    """Arrondi au centime — AFFICHAGE et partages de paiement UNIQUEMENT.
    Ne JAMAIS l'utiliser pour accumuler des coûts (audit #9)."""
    v = round(float(x) + 1e-9, 2)
    return 0.0 if v == 0 else v


@dataclass
class SponsorLedger:
    """Grand livre du sponsor : partage, prefund, plafond journalier."""
    enabled: bool = True
    prefund_usd: float = DEFAULT_PREFUND_USD
    sponsor_share_pct: float = DEFAULT_SPONSOR_SHARE_PCT
    sponsor_wallet: str = ""          # à remplir par Ismail / le sponsor
    daily_cap_usd: float = DEFAULT_DAILY_CAP_USD
    kill_switch: bool = False
    low_prefund_alert_usd: float = DEFAULT_LOW_PREFUND_ALERT_USD
    funding_mode: str = "sponsor"   # v3.4 : "sponsor" | "self_funded" (tag des entrées)
    state_path: Optional[str] = None       # sponsor_state.json (persisté)
    trades_path: Optional[str] = None      # trades.jsonl (append-only)

    # --- état (persisté) ---
    day: str = field(default_factory=lambda: date.today().isoformat())
    sponsor_paid_today_usd: float = 0.0
    gas_spent_total_usd: float = 0.0        # cumulé, déduit du prefund
    trades_today: int = 0

    def __post_init__(self):
        if self.state_path:
            self.load()

    # ------------------------------------------------------------------ persistance
    def _reset_if_new_day(self):
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.sponsor_paid_today_usd = 0.0
            self.trades_today = 0

    def save(self):
        if not self.state_path:
            return
        data = {"day": self.day, "sponsor_paid_today_usd": self.sponsor_paid_today_usd,
                "gas_spent_total_usd": self.gas_spent_total_usd,
                "trades_today": self.trades_today,
                "kill_switch": self.kill_switch,
                "prefund_usd": self.prefund_usd,
                "sponsor_share_pct": self.sponsor_share_pct,
                "sponsor_wallet": self.sponsor_wallet,
                "daily_cap_usd": self.daily_cap_usd}
        Path(self.state_path).write_text(json.dumps(data, indent=2))

    def load(self):
        try:
            data = json.loads(Path(self.state_path).read_text())
        except Exception:
            return
        self.day = data.get("day", self.day)
        self.sponsor_paid_today_usd = data.get("sponsor_paid_today_usd", 0.0)
        self.gas_spent_total_usd = data.get("gas_spent_total_usd", 0.0)
        self.trades_today = data.get("trades_today", 0)
        self.kill_switch = data.get("kill_switch", False)
        self.prefund_usd = data.get("prefund_usd", self.prefund_usd)
        self.sponsor_share_pct = data.get("sponsor_share_pct", self.sponsor_share_pct)
        self.sponsor_wallet = data.get("sponsor_wallet", self.sponsor_wallet)
        self.daily_cap_usd = data.get("daily_cap_usd", self.daily_cap_usd)

    # ------------------------------------------------------------------ partage
    def split_profit(self, net_usd: float) -> Tuple[float, float]:
        """(part sponsor, part Ismail) sur un profit NET.
        net <= 0 -> (0, 0) : pas de profit, pas de partage.
        v3.4 : ledger DÉSACTIVÉ (pas de sponsor) -> Ismail garde 100 %
        (0, net) — cohérent avec can_trade() qui dit déjà "Ismail
        auto-financé, 100 % pour lui". Jamais (0, 0) par erreur."""
        if net_usd is None or net_usd <= 0:
            return (0.0, 0.0)
        if not self.enabled:
            return (0.0, _round2(net_usd))
        sponsor = _round2(net_usd * self.sponsor_share_pct / 100.0)
        ismail = _round2(net_usd - sponsor)
        return (sponsor, ismail)

    def prefund_remaining(self) -> float:
        """Ce qui reste du prefund après le gas dépensé (jamais négatif affiché)."""
        return _round_usd(self.prefund_usd - self.gas_spent_total_usd)

    def prefund_low(self) -> bool:
        """True quand le prefund restant est sous le seuil d'alerte (< 5 $)."""
        return self.prefund_remaining() < self.low_prefund_alert_usd

    def prefund_alert(self) -> Optional[str]:
        if self.prefund_low():
            return (f"ALERTE prefund bas : il reste {self.prefund_remaining():.2f} $ "
                    f"(seuil {self.low_prefund_alert_usd:.2f} $) — recharger ou le "
                    f"bot s'arrêtera à 0 $")
        return None

    # ------------------------------------------------------------------ décisions
    def can_trade(self) -> Tuple[bool, str]:
        """Le bot a-t-il le droit de trader sous le deal sponsor ?"""
        self._reset_if_new_day()
        if self.kill_switch:
            return False, "KILL SWITCH sponsor activé — aucun trade"
        if not self.enabled:
            return True, "sponsor désactivé (Ismail auto-financé, 100 % pour lui)"
        if self.prefund_remaining() <= 0:
            return False, (f"prefund épuisé ({self.prefund_remaining():.2f} $ restants) "
                           f"— recharger {self.prefund_usd:.2f} $ ou arrêter")
        if self.sponsor_paid_today_usd >= self.daily_cap_usd:
            return False, (f"plafond sponsor journalier atteint "
                           f"({self.sponsor_paid_today_usd:.2f} $ / {self.daily_cap_usd:.2f} $) "
                           f"— STOP pour aujourd'hui")
        return True, "OK"

    def check_trade(self, net_usd: float) -> Tuple[bool, str, float, float]:
        """Vérifie UN trade avant exécution : (autorisé, raison, part sponsor,
        part Ismail). Bloque si la part sponsor du trade dépasserait le
        plafond journalier — raison STOP explicite, jamais silencieuse."""
        sponsor, ismail = self.split_profit(net_usd)
        ok, reason = self.can_trade()
        if not ok:
            return False, reason, sponsor, ismail
        if self.enabled and self.sponsor_paid_today_usd + sponsor > self.daily_cap_usd:
            return False, (f"STOP plafond sponsor : ce trade verserait {sponsor:.2f} $ "
                           f"au sponsor, total jour {self.sponsor_paid_today_usd + sponsor:.2f} $ "
                           f"> plafond {self.daily_cap_usd:.2f} $ — trade bloqué"),
            sponsor, ismail
        return True, "OK", sponsor, ismail

    # ------------------------------------------------------------------ enregistrement
    def record_trade(self, symbol: str, net_usd: float, gas_usd: float = 0.0,
                     provider: str = "", action: str = "EXECUTE",
                     simulated: bool = False,
                     extra: Optional[Dict] = None) -> Dict:
        """Enregistre un trade EXÉCUTÉ : partage + gas déduit du prefund +
        part sponsor du jour. Retourne l'entrée (avec 'blocked' si le trade
        a été refusé par le plafond — dans ce cas RIEN n'est enregistré ni
        déduit, le trade ne doit pas avoir lieu).
        Les SKIP ne passent pas ici : 0 $ / 0 $ pour tout le monde, rien à
        enregistrer (voir executor.py qui les logue en console).
        v3.2 ZERO-COST : le gas est DÉDUIT DU PREFUND SPONSOR UNIQUEMENT,
        jamais d'Ismail — chaque entrée porte donc 'ismail_paid_usd: 0.0'
        (sauf extra explicite, qui déclencherait le kill switch $0).
        `extra` : champs additionnels fusionnés dans l'entrée (ex.
        ismail_paid_usd / zero_cost depuis zero_cost.py)."""
        self._reset_if_new_day()
        sponsor, ismail = self.split_profit(net_usd)
        ok, reason, _, _ = self.check_trade(net_usd)
        if not ok:
            return {"symbol": symbol, "action": action, "blocked": True,
                    "reason": reason, "net_usd": _round_usd(net_usd),
                    "sponsor_share_usd": sponsor, "ismail_share_usd": ismail,
                    "gas_usd": _round_usd(gas_usd), "provider": provider,
                    "funding_mode": self.funding_mode,
                    "ismail_paid_usd": 0.0,
                    "prefund_remaining_usd": self.prefund_remaining(),
                    "sponsor_paid_today_usd": _round_usd(self.sponsor_paid_today_usd)}
        self.gas_spent_total_usd = _round_usd(self.gas_spent_total_usd + gas_usd)
        self.sponsor_paid_today_usd = _round_usd(self.sponsor_paid_today_usd + sponsor)
        self.trades_today += 1
        entry = {"date": self.day, "symbol": symbol, "action": action,
                 "net_usd": _round_usd(net_usd), "sponsor_share_usd": sponsor,
                 "ismail_share_usd": ismail, "gas_usd": _round_usd(gas_usd),
                 "provider": provider, "blocked": False,
                 "simulated": simulated,  # True en dry-run : 0 $ réel, jamais dû
                 "funding_mode": self.funding_mode,  # v3.4 : qui paie le gas
                 "ismail_paid_usd": 0.0,  # v3.2 : le gas vient du prefund sponsor, jamais d'Ismail
                 "prefund_remaining_usd": self.prefund_remaining(),
                 "sponsor_paid_today_usd": _round_usd(self.sponsor_paid_today_usd)}
        if extra:
            entry.update(extra)
        if self.trades_path:
            with open(self.trades_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        self.save()
        return entry

    def top_up(self, amount_usd: float) -> float:
        """Recharge du prefund (le sponsor remet de l'ETH). Retourne le reste."""
        self.prefund_usd = _round_usd(self.prefund_usd + amount_usd)
        self.save()
        return self.prefund_remaining()

    def status(self) -> Dict:
        self._reset_if_new_day()
        ok, reason = self.can_trade()
        return {"enabled": self.enabled, "day": self.day,
                "funding_mode": self.funding_mode,
                "prefund_usd": self.prefund_usd,
                "prefund_remaining_usd": self.prefund_remaining(),
                "gas_spent_total_usd": _round_usd(self.gas_spent_total_usd),
                "sponsor_share_pct": self.sponsor_share_pct,
                "sponsor_wallet": self.sponsor_wallet or "(à remplir)",
                "sponsor_paid_today_usd": _round_usd(self.sponsor_paid_today_usd),
                "daily_cap_usd": self.daily_cap_usd,
                "trades_today": self.trades_today,
                "low_prefund_alert": self.prefund_alert(),
                "kill_switch": self.kill_switch,
                "can_trade": ok, "reason": reason}


def load_from_config(path: Optional[str] = None) -> "SponsorLedger":
    """Lit la section de config.yaml (audit #13 : chemin par
    argument, sinon variable d'environnement CODEMA_CONFIG,
    sinon "config.yaml")."""
    path = path or os.environ.get("CODEMA_CONFIG") or "config.yaml"
    """Lit la section `sponsorship:` de config.yaml (parseur simple, sans
    dépendance YAML — le fichier n'utilise que `clé: valeur` plat)."""
    text = Path(path).read_text()
    m = re.search(r"^sponsorship:\n((?:[ \t]+\S.*\n?)+)", text, re.M)
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
    def _b(key, default):
        return params.get(key, str(default)).lower() in ("true", "yes", "1")
    _enabled = _b("enabled", True)
    return SponsorLedger(
        enabled=_enabled,
        prefund_usd=_f("prefund_usd", DEFAULT_PREFUND_USD),
        sponsor_share_pct=_f("sponsor_share_pct", DEFAULT_SPONSOR_SHARE_PCT),
        sponsor_wallet=params.get("sponsor_wallet", ""),
        daily_cap_usd=_f("daily_cap_usd", DEFAULT_DAILY_CAP_USD),
        kill_switch=_b("kill_switch", False),
        low_prefund_alert_usd=_f("low_prefund_alert_usd", DEFAULT_LOW_PREFUND_ALERT_USD),
        # v3.4 : section inactive (sponsorship.enabled: false) = mode autofinancé.
        funding_mode="self_funded" if not _enabled else "sponsor",
        state_path=params.get("state_file", "sponsor_state.json") or None,
        trades_path=params.get("trades_file", "trades.jsonl") or None,
    )


if __name__ == "__main__":
    s = SponsorLedger()
    print("Statut :", s.status())
    for net in (100.0, 73.07, 0.0):
        print(f"net {net:.2f} $ -> sponsor {s.split_profit(net)[0]:.2f} $ / "
              f"Ismail {s.split_profit(net)[1]:.2f} $")
    print("Trade 73,07 $ :", s.record_trade("MEME-WIN", 73.07, 0.0066, "balancer"))
    print("Après :", s.status())
