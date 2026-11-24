"""
polygon_gas.py — Gas Polygon (v4.0) : lecture du gas price live + coût en
MATIC et en $.

Polygon n'est PAS Base : le gas price live est ~279 gwei (bloc 97 901 602),
et le MATIC vaut ~0,0758 $ — un trade à 450 000 unités coûte donc
0,12555 MATIC ≈ 0,0095 $, soit ~2× PLUS cher qu'un trade Base mesuré
(0,0042–0,0052 $ à 0,005 gwei). Le gas Polygon reste minuscule en valeur
absolue, mais il n'est pas « quasi gratuit » en $ : le float 1,31 $ couvre
~137 trades au gas mesuré (~68 au pire cas trade + revert). Le plafond
est en gwei (1 000) ET en $ (le guard net > gas × 3 de decide() s'applique
toujours). Aucune clé, aucun secret : RPC public drpc.org.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

RPC_URL = "https://polygon.drpc.org"
RPC_FALLBACKS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://rpc.ankr.com/polygon",
]
MATIC_PRICE_USD = 0.0758        # CoinGecko polygon-ecosystem-token 2026-11-24
DEFAULT_GAS_UNITS = 450_000     # même hypothèse que le bot Base
GAS_PRICE_MAX_GWEI = 1000.0     # au-dessus : on ne broadcast RIEN
GAS_PRICE_LIVE_GWEI = 279.0     # mesuré 2026-11-24 (bloc 97 901 602)

_UA = {"Content-Type": "application/json",
       "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


@dataclass
class PolygonGasReading:
    gas_price_gwei: float
    gas_cost_matic: float   # pour DEFAULT_GAS_UNITS
    gas_cost_usd: float
    over_cap: bool
    source: str = RPC_URL


def _rpc(url: str, method: str, params=None):
    """Appel JSON-RPC via `requests` (urllib échoue sur les réponses
    chunkées de drpc : IncompleteRead puis 308 fantôme — vérifié
    2026-11-24 sur eth_getCode ; requests gère le chunked proprement)."""
    import requests as _rq

    body = {"jsonrpc": "2.0", "id": 1, "method": method,
            "params": params or []}
    last_err = None
    for _ in range(3):  # drpc est parfois capricieux
        try:
            r = _rq.post(url, json=body, headers=_UA, timeout=10)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"RPC error : {data['error']}")
            res = data.get("result")
            if not isinstance(res, str) or not res.startswith("0x"):
                raise RuntimeError(f"réponse inattendue : {str(data)[:120]}")
            return res
        except Exception as e:  # noqa: BLE001 — on réessaie
            last_err = e
    raise RuntimeError(f"{url} : {last_err}")


def read_gas_price_gwei(rpc_url: str = RPC_URL) -> float:
    """Gas price live en gwei (eth_gasPrice). Essaie les fallbacks."""
    last_err = None
    for url in [rpc_url] + RPC_FALLBACKS:
        try:
            res = _rpc(url, "eth_gasPrice")
            return int(res, 16) / 1e9
        except Exception as e:  # noqa: BLE001 — on essaie le RPC suivant
            last_err = e
    raise RuntimeError(f"aucun RPC Polygon ne répond (dernier : {last_err})")


def gas_cost_matic(gas_units: int, gas_price_gwei: float) -> float:
    """Coût gas en MATIC : units × gwei × 1e-9."""
    return gas_units * gas_price_gwei * 1e-9


def gas_cost_usd(gas_units: int, gas_price_gwei: float,
                 matic_price_usd: float = MATIC_PRICE_USD) -> float:
    """Coût gas en $ : units × gwei × 1e-9 × prix MATIC."""
    return gas_cost_matic(gas_units, gas_price_gwei) * matic_price_usd


def read_gas(rpc_url: str = RPC_URL,
             gas_units: int = DEFAULT_GAS_UNITS,
             matic_price_usd: float = MATIC_PRICE_USD) -> PolygonGasReading:
    """Lecture complète : prix live + coût du trade type + plafond."""
    gwei = read_gas_price_gwei(rpc_url)
    matic = gas_cost_matic(gas_units, gwei)
    return PolygonGasReading(
        gas_price_gwei=gwei,
        gas_cost_matic=matic,
        gas_cost_usd=matic * matic_price_usd,
        over_cap=gwei > GAS_PRICE_MAX_GWEI,
        source=rpc_url,
    )


if __name__ == "__main__":
    r = read_gas()
    print(f"gas price : {r.gas_price_gwei:.1f} gwei (plafond {GAS_PRICE_MAX_GWEI:.0f})")
    print(f"trade {DEFAULT_GAS_UNITS} unités : {r.gas_cost_matic:.6f} MATIC "
          f"= {r.gas_cost_usd:.6f} $")
    print(f"float 1,31 $ = {1.31 / max(r.gas_cost_usd, 1e-9):,.0f} trades "
          f"(pire cas ×2 : {1.31 / max(2 * r.gas_cost_usd, 1e-9):,.0f})")
    print("over_cap :", r.over_cap)
