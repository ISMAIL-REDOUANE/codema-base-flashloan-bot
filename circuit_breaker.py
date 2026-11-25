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
    seen_tx_hashes: List[str] = field(default_factory=list)  # audit #15 : déduplication
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
                "token_trades_last_hour": self.token_trades_last_hour,
                "seen_tx_hashes": self.seen_tx_hashes[-500:]}
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
        self.seen_tx_hashes = data.get("seen_tx_hashes", [])

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

    def record_receipt(self, status: str, gas_usd: float = 0.0,
                       token_address: str = "", tx_hash: str = "",
                       net_usd: Optional[float] = None) -> str:
        """Enregistrement UNIQUE d'un reçu de transaction (audit #15).
        status : "success" | "revert" | "simulated".
        Un seul appel met à jour ENSEMBLE les compteurs de pertes, le
        nombre de trades, les reverts consécutifs ET la pause — l'ancien
        code avait deux chemins incohérents : record_real_trade comptait
        un trade perdant comme revert SANS déclencher la pause, et
        record_revert ne comptait ni le gas ni le trade. Ici :
        - success : net_usd RÉEL (déjà net du gas) compté dans net_today
          + trades_today ; reverts remis à 0, sauf si net < 0 (perte
          anormale pour un trade atomique -> +1 revert, AVEC pause).
        - revert : perte = -gas_usd (net_usd ignoré si fourni), trades
          +1, reverts +1, pause à 3 d'affilée. Le gas du revert est
          compté comme perte — avant il était perdu (0 $ compté).
        - simulated : rien n'est compté (0 $ réellement perdu).
        Déduplication : un même tx_hash ne compte jamais deux fois
        (retour "duplicate"). Retourne "recorded" | "duplicate" |
        "simulated"."""
        self._reset_if_new_day()
        if status == "simulated":
            return "simulated"
        if status not in ("success", "revert"):
            raise ValueError(f"statut de reçu inconnu : {status}")
        if tx_hash:
            key = tx_hash.lower()
            if key in self.seen_tx_hashes:
                return "duplicate"
            self.seen_tx_hashes.append(key)
            self.seen_tx_hashes = self.seen_tx_hashes[-500:]
        if status == "revert":
            loss = gas_usd if gas_usd > 0 else 0.0
            self.net_today_usd -= loss
            self.trades_today += 1
            self.consecutive_reverts += 1
        else:
            net = 0.0 if net_usd is None else net_usd
            self.net_today_usd += net
            self.trades_today += 1
            if net < 0:
                self.consecutive_reverts += 1
            else:
                self.consecutive_reverts = 0
        if token_address:
            key = token_address.lower()
            self.token_trades_last_hour.setdefault(key, []).append(time.time())
        if self.consecutive_reverts >= self.max_consecutive_reverts:
            self.paused_until = time.time() + self.revert_pause_seconds
        self.save()
        return "recorded"

    def record_real_trade(self, net_usd: float, token_address: str = "",
                          tx_hash: str = "") -> None:
        """Enregistre un trade RÉEL (on-chain / fork). Fine enveloppe de
        record_receipt (audit #15) : le net est déjà net du gas, donc
        gas_usd=0 ici — le net compté est le net réel, la pause se
        déclenche désormais aussi sur 3 trades perdants d'affilée."""
        self.record_receipt("success", gas_usd=0.0,
                            token_address=token_address, tx_hash=tx_hash,
                            net_usd=net_usd)

    def record_revert(self, gas_usd: float = 0.0, token_address: str = "",
                      tx_hash: str = "") -> None:
        """Un revert on-chain : +1 au compteur, pause à 3 d'affilée.
        Fine enveloppe de record_receipt (audit #15) : le gas du revert
        est désormais compté comme perte, et le trade est compté."""
        self.record_receipt("revert", gas_usd=gas_usd,
                            token_address=token_address, tx_hash=tx_hash)

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
