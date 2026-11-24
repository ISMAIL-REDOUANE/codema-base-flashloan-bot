"""
circuit_breaker.py — Garde-fous financiers (v2, amélioration n°6 de ADVANCED_RESEARCH.md).

Ce que v1 n'avait PAS : aucune limite de perte. Un bug, un pic de gas ou
une série de honeypots pouvait faire tourner le bot en boucle et vider le
compte en gas. La recherche est claire : les bots qui survivent (27,8 %)
sont ceux qui S'ARRÊTENT quand ils perdent.

Règles (config.yaml, section `limits:`) :
  - Perte max par jour : 20 $ par défaut. Dépassée -> stop jusqu'à demain.
  - Perte max par trade : gas + 0 $ en théorie (atomicité du flash loan) ;
    si un trade perd PLUS que le gas, c'est un bug -> stop immédiat.
  - Max trades par jour : 50 (évite le spam qui tue les bots, cf. recherche §3.1).
  - 3 reverts d'affilée -> pause 1 h (quelque chose a changé on-chain).
  - Kill switch : `kill_switch: true` dans config.yaml (ou breaker.kill())
    -> le bot refuse TOUT trade, même gagnant, jusqu'à remise à zéro manuelle.
  - 1 token = max 2 trades par heure (évite de se faire piéger par un token
    qui se fait dumper — recherche §3.4).

État persisté dans un JSON (circuit_state.json) : le compteur survit à un
redémarrage du bot. Un trade n'est JAMAIS compté comme gagné/perdu sur une
estimation : seuls les nets RÉELS (on-chain / fork) alimentent le breaker.
En dry-run, les nets simulés sont journalisés mais ne déclenchent pas le
breaker (ils ne coûtent rien) — c'est documenté dans record_simulated().
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_DAILY_LOSS_LIMIT_USD = 20.0
DEFAULT_MAX_TRADES_PER_DAY = 50
DEFAULT_MAX_CONSECUTIVE_REVERTS = 3
DEFAULT_REVERT_PAUSE_SECONDS = 3600   # 1 h
DEFAULT_MAX_TRADES_PER_TOKEN_PER_HOUR = 2


@dataclass
class CircuitBreaker:
    daily_loss_limit_usd: float = DEFAULT_DAILY_LOSS_LIMIT_USD
    max_trades_per_day: int = DEFAULT_MAX_TRADES_PER_DAY
    max_consecutive_reverts: int = DEFAULT_MAX_CONSECUTIVE_REVERTS
    revert_pause_seconds: int = DEFAULT_REVERT_PAUSE_SECONDS
    max_trades_per_token_per_hour: int = DEFAULT_MAX_TRADES_PER_TOKEN_PER_HOUR
    kill_switch: bool = False
    state_path: Optional[str] = None

    # --- état (persisté) ---
    day: str = field(default_factory=lambda: date.today().isoformat())
    net_today_usd: float = 0.0
    trades_today: int = 0
    consecutive_reverts: int = 0
    paused_until: float = 0.0
    token_trades_last_hour: Dict[str, List[float]] = field(default_factory=dict)
    simulated_only_note: str = ""

    def __post_init__(self):
        if self.state_path:
            self.load()

    # ------------------------------------------------------------------ persistance
    def _reset_if_new_day(self):
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.net_today_usd = 0.0
            self.trades_today = 0
            self.consecutive_reverts = 0

    def save(self):
        if not self.state_path:
            return
        data = {"day": self.day, "net_today_usd": self.net_today_usd,
                "trades_today": self.trades_today,
                "consecutive_reverts": self.consecutive_reverts,
                "paused_until": self.paused_until,
                "kill_switch": self.kill_switch,
                "token_trades_last_hour": self.token_trades_last_hour}
        Path(self.state_path).write_text(json.dumps(data, indent=2))

    def load(self):
        try:
            data = json.loads(Path(self.state_path).read_text())
        except Exception:
            return
        self.day = data.get("day", self.day)
        self.net_today_usd = data.get("net_today_usd", 0.0)
        self.trades_today = data.get("trades_today", 0)
        self.consecutive_reverts = data.get("consecutive_reverts", 0)
        self.paused_until = data.get("paused_until", 0.0)
        self.kill_switch = data.get("kill_switch", False)
        self.token_trades_last_hour = data.get("token_trades_last_hour", {})

    # ------------------------------------------------------------------ décisions
    def can_trade(self, token_address: str = "") -> tuple[bool, str]:
        """Le bot a-t-il le droit d'envoyer un trade maintenant ?"""
        self._reset_if_new_day()
        if self.kill_switch:
            return False, "KILL SWITCH activé — aucun trade (remise à zéro manuelle requise)"
        now = time.time()
        if now < self.paused_until:
            mins = int((self.paused_until - now) / 60) + 1
            return False, f"pause après reverts — reprise dans ~{mins} min"
        if self.net_today_usd <= -self.daily_loss_limit_usd:
            return False, (f"limite de perte journalière atteinte "
                           f"({self.net_today_usd:.2f} $ <= -{self.daily_loss_limit_usd:.2f} $) — stop pour aujourd'hui")
        if self.trades_today >= self.max_trades_per_day:
            return False, f"max trades/jour atteint ({self.max_trades_per_day})"
        if token_address:
            recent = [t for t in self.token_trades_last_hour.get(token_address.lower(), [])
                      if now - t < 3600]
            if len(recent) >= self.max_trades_per_token_per_hour:
                return False, (f"déjà {len(recent)} trades sur ce token dans l'heure "
                               f"(max {self.max_trades_per_token_per_hour})")
        return True, "OK"

    def record_real_trade(self, net_usd: float, token_address: str = "") -> None:
        """Enregistre un trade RÉEL (on-chain / fork). Seul le réel compte :
        un net simulé ne déclenche jamais le breaker (il n'a rien coûté)."""
        self._reset_if_new_day()
        self.net_today_usd += net_usd
        self.trades_today += 1
        if net_usd < 0:
            # Perte plus grande que le gas seul = anomalie -> on compte
            # comme un revert (le contrat atomique ne devrait pas perdre plus).
            self.consecutive_reverts += 1
        else:
            self.consecutive_reverts = 0
        if token_address:
            key = token_address.lower()
            self.token_trades_last_hour.setdefault(key, []).append(time.time())
        self.save()

    def record_revert(self) -> None:
        """Un revert on-chain : +1 au compteur. À 3 d'affilée -> pause 1 h."""
        self._reset_if_new_day()
        self.consecutive_reverts += 1
        if self.consecutive_reverts >= self.max_consecutive_reverts:
            self.paused_until = time.time() + self.revert_pause_seconds
        self.save()

    def record_simulated(self, net_usd: float) -> str:
        """Journalise un net SIMULÉ (dry-run) : informatif seulement, le
        breaker ne s'enclenche PAS sur des simulations (0 $ réellement perdu)."""
        return (f"[simulé, ne déclenche pas le breaker] net {net_usd:.2f} $ "
                f"(réel aujourd'hui : {self.net_today_usd:.2f} $)")

    def kill(self) -> None:
        self.kill_switch = True
        self.save()

    def reset_kill_switch(self) -> None:
        self.kill_switch = False
        self.save()

    def status(self) -> Dict:
        self._reset_if_new_day()
        ok, reason = self.can_trade()
        return {"day": self.day, "net_today_usd": round(self.net_today_usd, 2),
                "trades_today": self.trades_today,
                "consecutive_reverts": self.consecutive_reverts,
                "paused": time.time() < self.paused_until,
                "kill_switch": self.kill_switch,
                "can_trade": ok, "reason": reason}


if __name__ == "__main__":
    b = CircuitBreaker()
    print("Au départ :", b.status())
    b.record_real_trade(71.55, "0xAAA")
    b.record_real_trade(-0.07, "0xAAA")
    print("Après 2 trades réels :", b.status())
    for _ in range(3):
        b.record_revert()
    print("Après 3 reverts :", b.status())
    b.kill()
    print("Après kill switch :", b.status())
