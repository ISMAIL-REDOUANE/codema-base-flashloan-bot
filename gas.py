"""
gas.py — Modèle de gas UNIFIÉ (v2, correctif finding #4 de ADVANCED_RESEARCH.md).

LE BUG v1 : config.yaml disait gas ~0,07 $ (450 000 units × 0,05 gwei × 3 000 $/ETH)
alors que math_engine.Costs avait un défaut gas_usd = 1,20 $ + un plancher
de 0,10 $. Les deux ne se parlaient pas : avec un gas réel de 0,07 $, le seuil
min 3 $ = ~43× le gas (très conservateur) ; avec 1,20 $, 3 $ = 2,5× le gas,
donc TROP JUSTE par rapport à la règle net > gas × 3 (il faudrait 3,60 $).

LA CORRECTION v2 : UNE SEULE source de vérité.
  - gas_cost_usd() calcule le gas à partir de (units, gwei, prix ETH) — sans plancher.
  - fetch_live_gas_price_gwei() lit eth_gasPrice sur le RPC Base en direct.
  - GAS_PRICE_MAX_GWEI (2 gwei par défaut, config.yaml) : au-dessus, on ne
    broadcast RIEN — un pic de gas (254 gwei le 29 oct 2026 = swap à 70 $)
    transforme un gain en perte, donc le bot s'arrête au lieu de payer.
  - math_engine.Costs utilise ce module : plus aucun défaut incohérent.

Mesure live vérifiée 2026-11-24 sur https://mainnet.base.org :
  eth_gasPrice = 0x5b8d80 = 6 000 000 wei = 0,006 gwei
  → 450 000 units × 0,006 gwei × 3 000 $/ETH ≈ 0,008 $.
Le gas normal sur Base est donc de l'ordre du centime, pas de 1,20 $.
Ce module ne dépend d'AUCUNE librairie externe (urllib stdlib only).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

# ------------------------------------------------------------------ constantes
DEFAULT_GAS_UNITS = 450_000        # flashLoanSimple + 2 swaps, estimation prudente
DEFAULT_GAS_PRICE_GWEI = 0.05      # hypothèse de travail (config.yaml) si RPC indisponible
DEFAULT_ETH_PRICE_USD = 3000.0     # hypothèse config.yaml — remplacer par oracle en prod
GAS_PRICE_MAX_GWEI = 2.0           # PLAFOND : au-dessus, on ne broadcast rien
PUBLIC_BASE_RPC = "https://mainnet.base.org"   # public, sans clé — tests/fork seulement


@dataclass
class GasReading:
    """Une mesure de gas, avec sa source — jamais un chiffre inventé sans le dire."""
    gas_price_gwei: float
    gas_units: int
    eth_price_usd: float
    source: str                    # "rpc_live" | "config_default" | "fallback"
    block_number: Optional[int] = None

    @property
    def gas_cost_usd(self) -> float:
        return gas_cost_usd_from_gwei(self.gas_units, self.gas_price_gwei,
                                      self.eth_price_usd)

    @property
    def over_cap(self) -> bool:
        return self.gas_price_gwei > GAS_PRICE_MAX_GWEI


def gas_cost_usd_from_gwei(gas_units: int, gas_price_gwei: float,
                           eth_price_usd: float) -> float:
    """Gas en $ : units × gwei × 1e-9 × prix ETH. AUCUN plancher inventé :
    si le gas réel est 0,008 $, on dit 0,008 $, pas 0,10 $."""
    if gas_units <= 0 or gas_price_gwei < 0 or eth_price_usd <= 0:
        return 0.0
    return gas_units * gas_price_gwei * 1e-9 * eth_price_usd


def gas_cost_usd(gas_units: int = DEFAULT_GAS_UNITS,
                 gas_price_gwei: float = DEFAULT_GAS_PRICE_GWEI,
                 eth_price_usd: float = DEFAULT_ETH_PRICE_USD) -> float:
    """Coût gas par défaut, UNIFIÉ avec config.yaml :
    450 000 × 0,05 gwei × 3 000 $ = 0,0675 $ (et non 1,20 $ comme en v1)."""
    return gas_cost_usd_from_gwei(gas_units, gas_price_gwei, eth_price_usd)


def fetch_live_gas_price_gwei(rpc_url: str = PUBLIC_BASE_RPC,
                              timeout: int = 10) -> GasReading:
    """Lit eth_gasPrice en direct sur le RPC Base. En cas d'échec réseau,
    retourne le défaut config avec source='fallback' — et le dit clairement,
    pour ne jamais faire croire qu'on a mesuré ce qu'on n'a pas mesuré."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_gasPrice", "params": []}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "codema-flashloan-bot-v2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        gwei = int(data["result"], 16) / 1e9
        return GasReading(gas_price_gwei=gwei, gas_units=DEFAULT_GAS_UNITS,
                          eth_price_usd=DEFAULT_ETH_PRICE_USD, source="rpc_live")
    except Exception as e:
        return GasReading(gas_price_gwei=DEFAULT_GAS_PRICE_GWEI,
                          gas_units=DEFAULT_GAS_UNITS,
                          eth_price_usd=DEFAULT_ETH_PRICE_USD,
                          source=f"fallback: {type(e).__name__}")


def fetch_live_block_number(rpc_url: str = PUBLIC_BASE_RPC,
                            timeout: int = 10) -> Optional[int]:
    """Numéro du dernier bloc — sert au plafond de fraîcheur (preflight)."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_blockNumber", "params": []}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "codema-flashloan-bot-v2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return int(data["result"], 16)
    except Exception:
        return None


def gas_ok(reading: GasReading, max_gwei: float = GAS_PRICE_MAX_GWEI) -> tuple[bool, str]:
    """Plafond de gas : True si on a le droit de broadcaster.
    Retourne (ok, raison). Au-dessus du plafond -> on n'envoie RIEN."""
    if reading.gas_price_gwei > max_gwei:
        return (False, f"gas trop cher : {reading.gas_price_gwei:.3f} gwei "
                       f"> plafond {max_gwei} gwei — aucun broadcast")
    return (True, f"gas OK : {reading.gas_price_gwei:.4f} gwei "
                  f"(coût ~{reading.gas_cost_usd:.4f} $)")


def default_reading() -> GasReading:
    """Lecture par défaut (config) — même valeur que config.yaml, sans RPC."""
    return GasReading(gas_price_gwei=DEFAULT_GAS_PRICE_GWEI,
                      gas_units=DEFAULT_GAS_UNITS,
                      eth_price_usd=DEFAULT_ETH_PRICE_USD,
                      source="config_default")


if __name__ == "__main__":
    print(f"Gas par défaut (config, unifié) : {gas_cost_usd():.4f} $")
    print(f"Gas à 1 gwei : {gas_cost_usd(450_000, 1.0, 3000.0):.2f} $")
    print(f"Gas au pic 254 gwei : {gas_cost_usd(450_000, 254.0, 3000.0):.2f} $")
    live = fetch_live_gas_price_gwei()
    print(f"Gas live Base : {live.gas_price_gwei:.4f} gwei "
          f"-> coût {live.gas_cost_usd:.4f} $ (source: {live.source})")
    print("Plafond OK ?", gas_ok(live))
    print("Plafond à 254 gwei ?", gas_ok(GasReading(254.0, 450_000, 3000.0, "test")))
