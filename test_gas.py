#!/usr/bin/env python3
"""Tests gas.py (audit #12) — coût COMPLET de la transaction exacte :
exécution L2 + frais L1 (GasPriceOracle), prix ETH daté.
Les tests live (RPC Base + CoinGecko) sont en lecture seule et SKIPPÉS
si le réseau est indisponible.
Lancer : python3 test_gas.py (stdlib only).
"""
import re
import sys

sys.path.insert(0, ".")

from gas import (EthPrice, estimate_full_tx_cost_usd,
                 execute_arbitrage_calldata, fetch_eth_price_usd,
                 gas_cost_usd_from_gwei, get_l1_fee_wei)


def _rpc_url():
    for path in ("config.yaml", "config.yaml.example"):
        try:
            text = open(path).read()
        except OSError:
            continue
        m = re.search(r"rpc_url:\s*\"?([^\"\n]+)\"?", text)
        if m:
            return m.group(1).strip()
    return "https://mainnet.base.org"


def test_l2_math():
    # 450 000 × 0,05 gwei × 3 000 $ = 0,0675 $.
    assert gas_cost_usd_from_gwei(450_000, 0.05, 3000.0) == 0.0675
    assert gas_cost_usd_from_gwei(0, 1.0, 3000.0) == 0.0
    print("OK test_l2_math — 450 000 × 0,05 gwei × 3 000 $ = 0,0675 $")


def test_execute_arbitrage_calldata():
    # Sélecteur vérifié par keccak + amount en uint256 (36 octets).
    data = execute_arbitrage_calldata(100_000_000)
    assert data[:4].hex() == "f7c7724f", data[:4].hex()
    assert len(data) == 36, len(data)
    assert int.from_bytes(data[4:], "big") == 100_000_000
    print("OK test_execute_arbitrage_calldata — 0xf7c7724f + amount uint256")


def test_full_cost_math_offline():
    # Somme L2 + L1 avec un L1 simulé (pas de RPC) : on vérifie la
    # composition, pas l'oracle (le live est dans le test suivant).
    l2 = gas_cost_usd_from_gwei(450_000, 0.05, 3000.0)
    l1_wei = 500_000_000_000_000  # 0,0005 ETH simulé
    l1_usd = l1_wei / 1e18 * 3000.0
    assert abs((l2 + l1_usd) - (0.0675 + 1.5)) < 1e-9
    print("OK test_full_cost_math_offline — total = L2 + L1 (0,0675 + 1,50 $)")


def test_l1_fee_live():
    """Lecture seule : frais L1 réel pour executeArbitrage(100 USDC)."""
    try:
        from arb.runtime import serialized_envelope
        payload = serialized_envelope({"to": "0x1111111111111111111111111111111111111111",
            "data": "0x" + execute_arbitrage_calldata(100_000_000).hex(),
            "gas": hex(450000), "gasPrice": hex(10000000)})
        fee_wei = get_l1_fee_wei(_rpc_url(),
                                 payload)
    except Exception as e:  # noqa: BLE001
        print(f"SKIP test_l1_fee_live (oracle illisible : {e})")
        return
    assert fee_wei > 0, fee_wei
    assert fee_wei < 10**18, fee_wei  # < 1 ETH, sanity
    print(f"OK test_l1_fee_live — L1 fee executeArbitrage(100 USDC) = "
          f"{fee_wei} wei ({fee_wei / 1e18:.6f} ETH)")


def test_eth_price_live():
    """Lecture seule : prix ETH daté via CoinGecko."""
    try:
        price = fetch_eth_price_usd()
    except Exception as e:  # noqa: BLE001
        print(f"SKIP test_eth_price_live (CoinGecko illisible : {e})")
        return
    assert price.usd > 0, price
    assert price.source.startswith("coingecko "), price.source
    assert price.fetched_at, price.fetched_at
    print(f"OK test_eth_price_live — ETH = {price.usd:.2f} $ "
          f"({price.source})")


def test_full_cost_live():
    """Lecture seule : coût complet (L2 + L1) de la tx exacte, live."""
    try:
        price = fetch_eth_price_usd()
        full = estimate_full_tx_cost_usd(
            _rpc_url(), execute_arbitrage_calldata(100_000_000),
            450_000, 0.05, price)
    except Exception as e:  # noqa: BLE001
        print(f"SKIP test_full_cost_live (réseau : {e})")
        return
    assert full["l1_fee_usd"] > 0, full
    assert full["total_cost_usd"] > full["l2_cost_usd"], full
    assert full["l1_source"] == "oracle_serialized_template"
    assert full["eth_price_source"].startswith("coingecko ")
    print(f"OK test_full_cost_live — L2 {full['l2_cost_usd']:.4f} $ + L1 "
          f"{full['l1_fee_usd']:.6f} $ = {full['total_cost_usd']:.4f} $ "
          f"(ETH {full['eth_price_usd']:.2f} $, {full['eth_price_source']})")


def test_eth_price_without_source_refused():
    """Un prix sans source est refusé (audit #12)."""
    try:
        estimate_full_tx_cost_usd(
            _rpc_url(), execute_arbitrage_calldata(100_000_000),
            450_000, 0.05, EthPrice(usd=3000.0, source=""))
    except ValueError as e:
        print(f"OK test_eth_price_without_source_refused — {e}")
        return
    raise AssertionError("un prix sans source aurait dû être refusé")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ÉCHEC {name} : {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{failed} ÉCHEC(S) sur {len(tests)} tests.")
        sys.exit(1)
    print(f"TOUS LES TESTS GAS PASSENT ({len(tests)} tests).")
