#!/usr/bin/env python3
"""debug_curve.py — Isole le revert de la jambe Curve sur le fork.

Déploie CurveFlashArbPolygon sur le fork Anvil (127.0.0.1:8545),
broadcast executeArbitrage(5 000 $, minDy) et imprime le hash de tx
(pour `cast trace`) + le receipt. NE broadcast RIEN sur mainnet.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from curve_route import (CURVE_AM3POOL, MATIC_PRICE_USD, MORPHO_POLYGON,
                         ONCHAIN_MIN_PROFIT_USD, POOL_USDC_USDCE_100,
                         POOL_USDCE_USDT_100, USDC_NATIVE, USDCE, USDT,
                         quote_route_4swap_usdc)

ANVIL_URL = "http://127.0.0.1:8545"
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view"},
]


def main():
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected()
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)
    me = deployer.address
    print("fork block:", w3.eth.block_number, "chain:", w3.eth.chain_id)

    def send_signed(fn, gas=2_000_000):
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me),
                                   "gas": gas,
                                   "maxFeePerGas": w3.eth.gas_price, "maxPriorityFeePerGas": 0,
                                   "chainId": 137, "value": 0})
        signed = deployer.sign_transaction(tx)
        return w3.eth.send_raw_transaction(signed.raw_transaction)

    artifact = json.loads(Path("out/CurveFlashArbPolygon.sol/CurveFlashArbPolygon.json").read_text())
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    txh = send_signed(contract.constructor(
        USDC_NATIVE, USDCE, USDT, POOL_USDC_USDCE_100, POOL_USDCE_USDT_100,
        CURVE_AM3POOL, int(ONCHAIN_MIN_PROFIT_USD * 1e6)), gas=3_000_000)
    rc = w3.eth.wait_for_transaction_receipt(txh)
    print("deploy:", rc["contractAddress"], "status:", rc["status"], "gas:", rc["gasUsed"])
    arb = w3.eth.contract(address=rc["contractAddress"], abi=artifact["abi"])

    q = quote_route_4swap_usdc(5_000.0, w3, gas_price_gwei=w3.eth.gas_price / 1e9)
    print("quote block:", q["block"], "gross:", q["gross_usd"], "net:", q["net_usd"],
          "min_dy:", q["min_dy_usdce"], "leg2:", q["leg2_usdt_to_usdce_curve"])
    txh = send_signed(arb.functions.executeArbitrage(int(5_000 * 1e6), q["min_dy_usdce"]))
    rc = w3.eth.wait_for_transaction_receipt(txh)
    print("executeArbitrage tx:", rc["transactionHash"].hex())
    print("status:", rc["status"], "gasUsed:", rc["gasUsed"], "block:", rc["blockNumber"])
    Path("/tmp/curve_debug_tx.txt").write_text(rc["transactionHash"].hex())


if __name__ == "__main__":
    main()
