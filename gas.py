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

# ------------------------------------------------------------------ frais L1 (audit #12)
# Base est un L2 OP Stack : chaque transaction paie EN PLUS du gas L2
# le coût de publication de ses données sur L1 (data fee), calculé par
# le précompilé GasPriceOracle (adresse fixe sur tous les OP Stack).
GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000F"
# Sélecteurs vérifiés par keccak le 2026-11-25 :
SELECTOR_GET_L1_FEE = bytes.fromhex("49948e0e")  # getL1Fee(bytes)
SELECTOR_EXECUTE_ARBITRAGE = bytes.fromhex("f7c7724f")  # executeArbitrage(uint256)
COINGECKO_SIMPLE_PRICE = ("https://api.coingecko.com/api/v3/simple/price"
                          "?ids=ethereum&vs_currencies=usd")


@dataclass
class EthPrice:
    """Prix ETH avec sa provenance DATÉE (audit #12) : un prix sans
    source ni date est un chiffre inventé — il ne doit jamais entrer
    dans un calcul de coût."""
    usd: float
    source: str                    # ex. "coingecko 2026-11-25T12:00:00Z"
    fetched_at: str = ""           # ISO 8601 UTC


@dataclass
class GasReading:
    """Une mesure de gas, avec sa source — jamais un chiffre inventé sans le dire."""
    gas_price_gwei: float
    gas_units: int
    eth_price_usd: float
    source: str                    # "rpc_live" | "config_default" | "fallback"
    block_number: Optional[int] = None
    l1_fee_usd: float = 0.0        # audit #12 : frais L1 (0 si non mesuré)
    l1_source: str = ""            # "oracle_live" | "" (non mesuré)

    @property
    def gas_cost_usd(self) -> float:
        return gas_cost_usd_from_gwei(self.gas_units, self.gas_price_gwei,
                                      self.eth_price_usd)

    @property
    def total_cost_usd(self) -> float:
        """Coût COMPLET de la transaction : exécution L2 + frais L1."""
        return self.gas_cost_usd + self.l1_fee_usd

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


def execute_arbitrage_calldata(amount_raw: int) -> bytes:
    """Calldata de executeArbitrage(amount) du contrat Morpho/V3
    (sélecteur 0xf7c7724f vérifié par keccak). Sert à mesurer le frais
    L1 de CETTE transaction exacte (sa taille = ses données publiées)."""
    return SELECTOR_EXECUTE_ARBITRAGE + int(amount_raw).to_bytes(32, "big")


def get_l1_fee_wei(rpc_url: str, tx_data: bytes,
                   block="latest", timeout: int = 10) -> int:
    """L1 fee for a SERIALIZED TRANSACTION, not its calldata alone."""
    if len(tx_data) < 70:
        raise ValueError("getL1Fee requires a complete serialized transaction")
    block_param = hex(block) if isinstance(block, int) else block
    calldata = SELECTOR_GET_L1_FEE + (32).to_bytes(32, "big") \
        + len(tx_data).to_bytes(32, "big") + tx_data
    # Padding à 32 octets (ABI bytes dynamique).
    if len(tx_data) % 32:
        calldata += b"\x00" * (32 - len(tx_data) % 32)
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": GAS_PRICE_ORACLE,
                                      "data": "0x" + calldata.hex()},
                                     block_param]}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "codema-flashloan-bot-v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"GasPriceOracle error: {out['error']}")
    return int(out["result"], 16)


def fetch_eth_price_usd(timeout: int = 10) -> EthPrice:
    """Prix ETH/USD via CoinGecko (public, sans clé), avec l'heure de
    récupération. Lève une exception si l'API ne répond pas — l'appelant
    doit alors utiliser un prix daté explicite, pas un défaut silencieux."""
    from datetime import datetime, timezone
    req = urllib.request.Request(COINGECKO_SIMPLE_PRICE,
                                 headers={"User-Agent": "codema-flashloan-bot-v2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    price = float(data["ethereum"]["usd"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return EthPrice(usd=price, source=f"coingecko {now}", fetched_at=now)


def estimate_full_tx_cost_usd(rpc_url: str, tx_data: bytes,
                              gas_units: int, gas_price_gwei: float,
                              eth_price: EthPrice,
                              block="latest", timeout: int = 10) -> dict:
    """Coût COMPLET de la transaction exacte (audit #12) :
    exécution L2 (units × gwei × prix ETH) + frais L1 (oracle, sur les
    données EXACTES de la tx). Le prix ETH doit être daté (EthPrice) :
    un prix sans source est refusé. Retourne le détail avec sources."""
    if not eth_price.source:
        raise ValueError("prix ETH sans source — refusé (audit #12)")
    l2_usd = gas_cost_usd_from_gwei(gas_units, gas_price_gwei, eth_price.usd)
    # Legacy callers supply calldata. Include the entire transaction envelope.
    # This remains a template estimate; bot.py prices the actual guarded plan.
    from arb.runtime import serialized_envelope
    envelope = serialized_envelope({"to": "0xFfFfFfFFfFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        "data": "0x" + tx_data.hex(), "gas": hex(gas_units),
        "gasPrice": hex(int(gas_price_gwei * 1e9))})
    l1_wei = get_l1_fee_wei(rpc_url, envelope, block, timeout)
    l1_usd = l1_wei / 1e18 * eth_price.usd
    return {"l2_cost_usd": l2_usd, "l1_fee_usd": l1_usd,
            "total_cost_usd": l2_usd + l1_usd,
            "l1_fee_wei": l1_wei, "gas_units": gas_units,
            "gas_price_gwei": gas_price_gwei,
            "eth_price_usd": eth_price.usd,
            "eth_price_source": eth_price.source,
            "l1_source": "oracle_serialized_template", "envelope_bytes": len(envelope)}


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
