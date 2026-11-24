"""
websocket_listener.py — Flux temps réel post-Denim (v2, amélioration n°5).

LE PROBLÈME (ADVANCED_RESEARCH.md §0) : Base est passé en blocs de 200 ms
le 5 nov 2026 (Denim, Flashblocks retiré). La fenêtre d'arbitrage est donc
~200 ms, pas 2 s. Un bot qui POLL toutes les secondes (ou toutes les 20 s
comme les repos classiques) arrive 5 à 100× trop tard : les spreads liquides
sont déjà fermés par les bots pros (réaction 5–8 ms, recherche de cycle ~2 ms).

CE QUE FAIT CE MODULE (squelette honnête, pas une promesse) :
  - S'abonne en WebSocket au RPC Base (eth_subscribe : newHeads + logs des
    pools suivis) et appelle un callback à chaque événement, en mesurant la
    latence de réception (objectif : décision < 200 ms, sinon on ne chasse
    que les spreads qui durent plusieurs blocs — les memes illiquides).
  - Fournit aussi un Poller de repli, DOCUMENTÉ COMME TROP LENT post-Denim :
    il ne sert qu'au développement / aux tests, jamais au live sur des
    spreads courts.

CE QU'IL NE FAIT PAS (à ne pas prétendre) :
  - Il ne garantit PAS une exécution en 200 ms : la latence totale
    (réception -> décision -> signature -> broadcast -> inclusion) n'est
    mesurée qu'une fois le bot branché sur un vrai RPC WebSocket rapide.
    Les chiffres seront publiés dans EV_RESULTS.md / FORK_TEST_RESULTS.md,
    pas inventés ici.
  - Le flux public Flashblocks (wss://mainnet.flashblocks.base.org/ws)
    est PRÉ-Denim : NE PAS l'utiliser sans re-vérification (voir recherche §0).
  - Nécessite `websockets` (déjà installé dans .venv) pour le mode live ;
    sans lui, seul le Poller (lent) fonctionne.

Usage : WebSocketListener(rpc_ws_url, pool_addresses, on_event).run()
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class StreamEvent:
    kind: str                 # "new_head" | "log" | "heartbeat"
    block_number: Optional[int] = None
    address: Optional[str] = None
    data: Dict = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)
    latency_ms: float = 0.0   # temps entre l'événement et sa réception (si horodaté)


@dataclass
class ListenerStats:
    events: int = 0
    max_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_block: Optional[int] = None

    def record(self, latency_ms: float, block_number: Optional[int] = None):
        self.events += 1
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.avg_latency_ms += (latency_ms - self.avg_latency_ms) / self.events
        if block_number is not None:
            self.last_block = block_number


class WebSocketListener:
    """Écoute WebSocket (eth_subscribe) — le seul mode viable post-Denim.
    rpc_ws_url : ex. wss://base-mainnet.g.alchemy.com/v2/<key> ou un WSS
    Chainstack/QuickNode. AUCUNE clé en dur ici : à passer en argument.
    pool_addresses : adresses des pools à suivre (logs Swap).
    on_event : callback(event) appelé à chaque événement."""

    def __init__(self, rpc_ws_url: str, pool_addresses: Optional[List[str]] = None,
                 on_event: Optional[Callable] = None):
        self.rpc_ws_url = rpc_ws_url
        self.pool_addresses = [a.lower() for a in (pool_addresses or [])]
        self.on_event = on_event or (lambda e: None)
        self.stats = ListenerStats()
        self._running = False

    async def run(self, max_events: Optional[int] = None):
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError(
                "websockets non installé : `pip install websockets` "
                "(déjà présent dans .venv du projet).") from e
        self._running = True
        async with websockets.connect(self.rpc_ws_url, ping_interval=20) as ws:
            # 1) newHeads — chaque bloc de 200 ms
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe",
                                      "params": ["newHeads"]}))
            # 2) logs des pools suivis (événements Swap)
            if self.pool_addresses:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "eth_subscribe",
                                          "params": ["logs", {"address": self.pool_addresses}]}))
            count = 0
            while self._running:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                msg = json.loads(raw)
                t0 = time.time()
                event = self._parse(msg)
                if event is None:
                    continue
                event.latency_ms = (time.time() - t0) * 1000.0
                self.stats.record(event.latency_ms, event.block_number)
                self.on_event(event)
                count += 1
                if max_events and count >= max_events:
                    break

    def _parse(self, msg: Dict) -> Optional[StreamEvent]:
        params = msg.get("params") or {}
        result = params.get("result") or {}
        if "number" in result:  # newHeads
            return StreamEvent(kind="new_head",
                               block_number=int(result["number"], 16),
                               data={"hash": result.get("hash")})
        if "address" in result:  # log
            return StreamEvent(kind="log",
                               block_number=int(result.get("blockNumber", "0x0"), 16),
                               address=result.get("address"),
                               data={"topics": result.get("topics", []),
                                     "data": result.get("data", "")})
        return None

    def stop(self):
        self._running = False


class PollingFallback:
    """REPLI POLLING — DOCUMENTÉ COMME TROP LENT post-Denim.
    Un poll toutes les N secondes rate les spreads qui durent < N secondes.
    À utiliser uniquement en développement / test, JAMAIS comme stratégie
    live sur des spreads courts. Les memes illiquides (spreads qui durent
    plusieurs blocs) sont la seule cible acceptable en polling."""

    def __init__(self, rpc_url: str, interval_seconds: float = 5.0,
                 on_block: Optional[Callable] = None):
        self.rpc_url = rpc_url
        self.interval_seconds = interval_seconds
        self.on_block = on_block or (lambda b: None)
        self.stats = ListenerStats()

    def _block_number(self) -> Optional[int]:
        payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                              "method": "eth_blockNumber", "params": []}).encode()
        req = urllib.request.Request(self.rpc_url, data=payload,
                                     headers={"Content-Type": "application/json", "User-Agent": "codema-flashloan-bot-v2"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return int(json.loads(resp.read().decode())["result"], 16)
        except Exception:
            return None

    def run_once(self) -> Optional[int]:
        t0 = time.time()
        block = self._block_number()
        if block is not None:
            self.stats.record((time.time() - t0) * 1000.0, block)
            self.on_block(block)
        return block

    def run(self, max_polls: int = 3):
        print(f"[polling] ATTENTION : polling toutes les {self.interval_seconds} s — "
              f"trop lent post-Denim (bloc 200 ms). Développement seulement.")
        for _ in range(max_polls):
            self.run_once()
            time.sleep(self.interval_seconds)


if __name__ == "__main__":
    # Démo sans clé : 3 polls sur le RPC public (lent, dev seulement).
    p = PollingFallback("https://mainnet.base.org", interval_seconds=2.0,
                        on_block=lambda b: print(f"bloc Base : {b}"))
    p.run(max_polls=3)
    print("Stats polling :", p.stats)
    print("Pour le live : WebSocketListener(wss://<rpc-avec-clé>, pools, callback)")
