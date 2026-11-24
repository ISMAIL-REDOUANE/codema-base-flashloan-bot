"""
revert_protection.py — Protection revert Polygon v4.2 (HONNÊTE).

VERDICT 2026-11-24 (voir REVERT_PROTECTION_POLYGON.md) : AUCUN service
vérifié ne donne 0 $ sur un revert ON-CHAIN sur Polygon aujourd'hui.
- MEV Blocker /noreverts et Flashbots Protect : Ethereum seulement
  (docs officielles : « All features are supported on Ethereum »).
- FastLane Atlas : « No Free Reverts » (blog officiel) + framework
  solvers, pas une route pour un bot autonome ; relai PFL : très peu
  de validateurs (latence en heures).
- Polygon Private Mempool : existe (gratuit, live 2026-04-02) mais
  AUCUNE simulation / drop de revert documentée ; endpoint non publié
  (accès sur demande). NE PEUT PAS prétendre au 0 $ revert.
- dRPC / Blink / bloXroute : protection MEV (vie privée) seulement.
- Paymaster ERC-4337 : NE PEUT PAS rendre le revert 0 $ (EntryPoint
  facture le gas même en revert — Trail of Bits, docs ERC-4337).
- EIP-3529 : refund SELFDESTRUCT supprimé, max refund gasUsed/5.

Ce module NE prétend PAS au 0 $ revert. Il fait trois choses vérifiées :
  1. Re-simulation au moment de l'envoi : eth_call de la tx contre le
     DERNIER bloc + fenêtre de fraîcheur de la quote. Si la re-sim
     échoue ou si le net tombe <= 0 -> DROP avant envoi (0 $ gas).
     Ça réduit la fenêtre de course ; ça ne supprime pas le risque.
  2. Routage : `public` (défaut) ou `private` (Polygon Private
     Mempool — endpoint TBD, DÉSACTIVÉ par défaut, marqué NON VÉRIFIÉ
     pour le revert ; il protège du frontrunning, pas du revert).
  3. Journal des issues : chaque tentative est enregistrée
     (dropped_presend / sent / executed / reverted_onchain + gas payé).
  4. Politique de repli fail-closed : route protégée injoignable ->
     NE PAS ENVOYER par défaut ; broadcast public seulement si
     allow_public_fallback=True ET net couvrant le budget revert.

Mode dry-run par défaut : rien n'est broadcast (le bot est en
simulation jusqu'à l'audit + décision d'Ismail). Le `send_fn` réel
(broadcast signé) sera branché plus tard ; en attendant, le sender
par défaut est un DryRunSender qui n'envoie rien.

Aucune clé privée, aucun broadcast mainnet dans ce module.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

import requests as _rq

# --- Constantes mesurées (fork Polygon, bloc 97 902 229, 2026-11-24) ---
REVERT_GAS_USD_MEASURED = 0.0024    # revert mesuré sur le fork
REVERT_GAS_USD_PRUDENT = 0.0095     # 450 000 unités × 279 gwei
DEFAULT_MAX_QUOTE_AGE_SECONDS = 30
DEFAULT_PRIVATE_TIMEOUT_SECONDS = 3.0
DEFAULT_LOG_FILE = "revert_protection_log.jsonl"

# La route privée n'est PAS vérifiée pour le revert : l'endpoint est
# inconnu (Polygon ne l'a pas publié — accès sur demande) et AUCUNE
# simulation/drop n'est documentée. Elle reste désactivée tant qu'on
# n'a pas vérifié l'endpoint ET son comportement.
PRIVATE_ROUTE_VERIFIED_FOR_REVERT = False


@dataclass
class SimResult:
    """Résultat d'une simulation (eth_call ou garde off-chain)."""
    success: bool
    net_usd: float = 0.0
    gas_usd: float = 0.0
    block_number: int | None = None
    reason: str = ""


@dataclass
class SendResult:
    """Résultat d'un envoi (réel ou dry-run)."""
    status: str  # "sent" | "executed" | "reverted_onchain" | "dropped_by_relay" | "dry_run" | "failed"
    tx_hash: str | None = None
    gas_paid_usd: float = 0.0
    reason: str = ""


@dataclass
class RouteOutcome:
    """Issue complète d'une tentative de trade, journalisée."""
    decision: str  # "dropped_presend" | "sent" | "dry_run" | "dropped_route_down"
    route: str     # "public" | "private"
    reason: str
    gas_paid_usd: float = 0.0
    tx_hash: str | None = None
    net_usd: float = 0.0
    block_number: int | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class DryRunSender:
    """Sender par défaut : n'envoie RIEN. Le bot est en dry-run jusqu'à
    l'audit + décision d'Ismail. Un vrai sender (broadcast signé) sera
    branché ici plus tard, après audit."""

    def send(self, route: str, raw_tx: str) -> SendResult:
        return SendResult(status="dry_run", tx_hash=None,
                          gas_paid_usd=0.0,
                          reason="dry-run : rien n'est broadcast")


def parse_eth_call_response(data: dict) -> SimResult:
    """Interprète une réponse JSON-RPC eth_call.

    - `result` présent (0x...) -> la call a réussi (pas de revert).
    - `error` présent -> la call a revert (ou autre erreur) : on traite
      toute erreur comme un revert potentiel -> DROP.
    C'est le même principe que la simulation d'un relai no-revert :
    on ne broadcast que ce qui passe la call contre le dernier bloc.
    """
    if isinstance(data, dict) and "result" in data and data["result"]:
        return SimResult(success=True, reason="eth_call ok")
    err = data.get("error", {}) if isinstance(data, dict) else {}
    msg = err.get("message", "eth_call error") if isinstance(err, dict) else str(err)
    return SimResult(success=False, reason=f"eth_call revert/erreur : {msg}")


def eth_call_simulate(rpc_url: str, tx: dict,
                      block: str = "latest",
                      timeout: float = 10.0) -> SimResult:
    """Re-simulation live : eth_call de la tx contre le bloc donné.

    tx : dict JSON-RPC (from, to, data, value, gas). Ne signe rien,
    ne broadcast rien — c'est une lecture. Toute erreur (revert,
    RPC down, timeout) -> success=False -> DROP.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [tx, block]}
    try:
        r = _rq.post(rpc_url, json=body, timeout=timeout)
        r.raise_for_status()
        res = parse_eth_call_response(r.json())
        if res.success:
            try:
                res.block_number = int(_rpc_block_number(rpc_url), 16)
            except Exception:  # noqa: BLE001 — le bloc est informatif
                res.block_number = None
        return res
    except Exception as e:  # noqa: BLE001 — toute erreur = DROP
        return SimResult(success=False, reason=f"eth_call impossible : {e}")


def _rpc_block_number(rpc_url: str, timeout: float = 10.0) -> str:
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber",
            "params": []}
    r = _rq.post(rpc_url, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["result"]


def expected_revert_cost_usd(revert_rate: float,
                             revert_gas_usd: float = REVERT_GAS_USD_PRUDENT) -> float:
    """Coût attendu des reverts résiduels par trade tenté.

    E[revert] = taux_de_course × coût_revert. Ex. 5 % × 0,0095 $ =
    0,000475 $/trade tenté (soit ~0,0475 $ pour 100 trades tentés).
    Ce n'est pas 0 $ — c'est le résidu chiffré, à mesurer en
    paper-trade Amoy (chaque `reverted_onchain` du journal compte).
    """
    if not 0.0 <= revert_rate <= 1.0:
        raise ValueError("revert_rate doit être entre 0 et 1")
    if revert_gas_usd < 0:
        raise ValueError("revert_gas_usd doit être >= 0")
    return revert_rate * revert_gas_usd


class RevertRouter:
    """Routeur d'envoi Polygon v4.2 : re-simulation + routage + journal.

    Paramètres (voir polygon_config.yaml, section revert_protection) :
      route : "public" (défaut) ou "private".
      private_endpoint : URL du Polygon Private Mempool — None par
        défaut (endpoint NON PUBLIÉ, NON VÉRIFIÉ pour le revert).
      private_timeout_seconds : délai max pour joindre la route privée.
      max_quote_age_seconds : quote plus vieille -> DROP (0 $).
      allow_public_fallback : False par défaut (fail-closed) — si la
        route privée est down, NE PAS ENVOYER. True = repli public
        autorisé, seulement si le net couvre le budget revert.
      revert_budget_usd : coût budgété d'un revert (défaut prudent).
      log_file : journal JSONL des issues (None = pas de journal).
      sender : objet avec .send(route, raw_tx) -> SendResult.
        Par défaut DryRunSender (n'envoie rien).
      simulate_fn : callable(tx) -> SimResult. Par défaut, eth_call
        live contre rpc_url. Injecter un faux dans les tests.
      rpc_url : RPC de lecture pour la re-simulation eth_call.
    """

    def __init__(self, route: str = "public",
                 private_endpoint: str | None = None,
                 private_timeout_seconds: float = DEFAULT_PRIVATE_TIMEOUT_SECONDS,
                 max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
                 allow_public_fallback: bool = False,
                 revert_budget_usd: float = REVERT_GAS_USD_PRUDENT,
                 log_file: str | None = DEFAULT_LOG_FILE,
                 sender=None,
                 simulate_fn=None,
                 rpc_url: str = "https://polygon.drpc.org"):
        route = route.strip().lower()
        if route not in ("public", "private"):
            raise ValueError(f"route inconnue : {route!r} (public|private)")
        if route == "private" and not private_endpoint:
            raise ValueError(
                "route 'private' sans private_endpoint : l'endpoint du "
                "Polygon Private Mempool n'est PAS publié (accès sur "
                "demande) — impossible de router en privé sans l'avoir "
                "vérifié. Laisser route='public'.")
        # La route privée ne garantit JAMAIS le 0 $ revert sur Polygon
        # (voir REVERT_PROTECTION_POLYGON.md) — même si elle répond.
        self.private_revert_guarantee = False
        self.route = route
        self.private_endpoint = private_endpoint
        self.private_timeout_seconds = private_timeout_seconds
        self.max_quote_age_seconds = max_quote_age_seconds
        self.allow_public_fallback = allow_public_fallback
        self.revert_budget_usd = revert_budget_usd
        self.log_file = log_file
        self.sender = sender or DryRunSender()
        self.simulate_fn = simulate_fn
        self.rpc_url = rpc_url

    # -- santé de la route privée -------------------------------------
    def private_endpoint_reachable(self) -> bool:
        """Teste la route privée (eth_chainId, timeout court). False si
        pas d'endpoint, timeout, ou erreur. Un endpoint joignable ne
        prouve PAS le 0 $ revert — seulement qu'il répond."""
        if not self.private_endpoint:
            return False
        try:
            body = {"jsonrpc": "2.0", "id": 1,
                    "method": "eth_chainId", "params": []}
            r = _rq.post(self.private_endpoint, json=body,
                         timeout=self.private_timeout_seconds)
            r.raise_for_status()
            return r.json().get("result") == "0x89"  # 137 = Polygon
        except Exception:  # noqa: BLE001 — injoignable = down
            return False

    # -- décision d'envoi ---------------------------------------------
    def route_trade(self, tx: dict, quote_timestamp: float,
                    net_usd: float, raw_tx: str = "",
                    now: float | None = None) -> RouteOutcome:
        """Décide et (en dry-run) route un trade.

        tx : dict JSON-RPC pour la re-simulation eth_call.
        quote_timestamp : horodatage de la quote (secondes epoch).
        net_usd : profit net simulé APRÈS TOUS LES COÛTS (garde
          polygon_guard : net > 0 après gas + budget revert).
        raw_tx : transaction signée (vide en dry-run / tests).
        Retourne un RouteOutcome journalisé. Aucun broadcast réel
        tant que le sender est DryRunSender.
        """
        now = time.time() if now is None else now
        outcome = self._decide(tx, quote_timestamp, net_usd, now)
        if outcome is not None:
            self._record(outcome)
            return outcome

        # Route privée : vérifier qu'elle répond, sinon repli fail-closed.
        route = self.route
        if route == "private" and not self.private_endpoint_reachable():
            if not self.allow_public_fallback:
                outcome = RouteOutcome(
                    decision="dropped_route_down", route="private",
                    reason="route privée injoignable + fail-closed "
                           "(allow_public_fallback=false) — RIEN envoyé, 0 $",
                    gas_paid_usd=0.0, net_usd=net_usd)
                self._record(outcome)
                return outcome
            route = "public"  # repli explicite, net couvre le budget revert

        sent = self.sender.send(route, raw_tx)
        decision = "sent" if sent.status == "sent" else sent.status
        if sent.status == "dry_run":
            decision = "dry_run"
        outcome = RouteOutcome(
            decision=decision, route=route,
            reason=sent.reason or f"envoyé via {route}",
            gas_paid_usd=sent.gas_paid_usd, tx_hash=sent.tx_hash,
            net_usd=net_usd)
        self._record(outcome)
        return outcome

    def _decide(self, tx: dict, quote_timestamp: float,
                net_usd: float, now: float) -> RouteOutcome | None:
        """Filtres pre-send. Retourne un RouteOutcome DROP, ou None si
        le trade passe (on passe à l'envoi). Chaque DROP = 0 $ gas."""
        age = now - quote_timestamp
        if age > self.max_quote_age_seconds:
            return RouteOutcome(
                decision="dropped_presend", route=self.route,
                reason=f"quote trop vieille ({age:.1f}s > "
                       f"{self.max_quote_age_seconds}s) — DROP, 0 $",
                gas_paid_usd=0.0, net_usd=net_usd)
        if net_usd <= 0:
            return RouteOutcome(
                decision="dropped_presend", route=self.route,
                reason=f"net <= 0 $ ({net_usd:.4f} $) après tous coûts "
                       "— DROP, 0 $",
                gas_paid_usd=0.0, net_usd=net_usd)
        sim = self._simulate(tx)
        if not sim.success:
            return RouteOutcome(
                decision="dropped_presend", route=self.route,
                reason=f"re-simulation au dernier bloc : ÉCHEC "
                       f"({sim.reason}) — DROP avant broadcast, 0 $",
                gas_paid_usd=0.0, net_usd=net_usd,
                block_number=sim.block_number)
        return None

    def _simulate(self, tx: dict) -> SimResult:
        if self.simulate_fn is not None:
            return self.simulate_fn(tx)
        return eth_call_simulate(self.rpc_url, tx)

    # -- journal --------------------------------------------------------
    def _record(self, outcome: RouteOutcome) -> None:
        if not self.log_file:
            return
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(outcome.to_dict()) + "\n")
        except Exception:  # noqa: BLE001 — le journal ne doit jamais bloquer
            pass


def router_from_config(cfg: dict, sender=None, simulate_fn=None) -> RevertRouter:
    """Construit le routeur depuis la section revert_protection de
    polygon_config.yaml (dict). Valeurs par défaut = fail-closed."""
    rp = (cfg or {}).get("revert_protection", {}) or {}
    return RevertRouter(
        route=rp.get("route", "public"),
        private_endpoint=rp.get("private_endpoint"),
        private_timeout_seconds=rp.get("private_timeout_seconds",
                                       DEFAULT_PRIVATE_TIMEOUT_SECONDS),
        max_quote_age_seconds=rp.get("max_quote_age_seconds",
                                     DEFAULT_MAX_QUOTE_AGE_SECONDS),
        allow_public_fallback=rp.get("allow_public_fallback", False),
        revert_budget_usd=rp.get("revert_budget_usd",
                                 REVERT_GAS_USD_PRUDENT),
        log_file=rp.get("log_file", DEFAULT_LOG_FILE),
        sender=sender, simulate_fn=simulate_fn,
        rpc_url=(cfg or {}).get("chain", {}).get(
            "rpc_url", "https://polygon.drpc.org"),
    )


if __name__ == "__main__":
    # Démo offline (simulateur factice) : les 3 cas de DROP à 0 $ + 1 envoi dry-run.
    ok = lambda tx: SimResult(success=True, net_usd=0.5, block_number=1)
    bad = lambda tx: SimResult(success=False, reason="revert simulé")
    r = RevertRouter(log_file=None, simulate_fn=ok)
    t = time.time()
    print("trade OK, quote fraîche :",
          r.route_trade({"to": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"},
                        t, 0.5))
    print("trade OK, quote vieille :",
          r.route_trade({"to": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"},
                        t - 120, 0.5))
    print("trade net <= 0 :",
          r.route_trade({"to": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"},
                        t, -0.1))
    r2 = RevertRouter(log_file=None, simulate_fn=bad)
    print("trade qui revert en re-sim :",
          r2.route_trade({"to": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"},
                         t, 0.5))
    print("E[revert] à 5 % de courses :",
          f"{expected_revert_cost_usd(0.05):.6f} $/trade")
