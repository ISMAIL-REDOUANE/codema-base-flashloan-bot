"""Phase 1 probe: flash-mint / flash-swap mechanisms on Polygon mainnet (read-only)."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon.drpc.org"))
print("block:", w3.eth.block_number)

AD = {
    "WETH10_eth_addr": "0xbc5cef436eadacadfa8dafb63088f09f21dea7e9",
    "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    "WETH_polygon": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    "QuickSwapV2Factory": "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32",
    "QuickSwapV2Router": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
    "SushiV2Factory": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4",
    "SushiV2Router": "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
    "MorphoPolygon": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67",
    "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
}
for n, a in AD.items():
    a = Web3.to_checksum_address(a)
    print(f"{n}: code={len(w3.eth.get_code(a))} bytes")

SEL_FLASHFEE = Web3.keccak(text="flashFee(address,uint256)")[:4].hex()
SEL_MAXFLASH = Web3.keccak(text="maxFlashLoan(address)")[:4].hex()


def enc_addr(x):
    return "000000000000000000000000" + Web3.to_checksum_address(x)[2:].lower()


for n in ["WMATIC", "WETH_polygon", "WETH10_eth_addr"]:
    a = Web3.to_checksum_address(AD[n])
    data = "0x" + SEL_FLASHFEE + enc_addr(a) + "0" * 60 + "03e8"
    try:
        r = w3.eth.call({"to": a, "data": data})
        print(n, "flashFee(self,1000) ->", int.from_bytes(r, "big"))
    except Exception as e:
        print(n, "flashFee call REVERTS:", str(e)[:100])
    data2 = "0x" + SEL_MAXFLASH + enc_addr(a)
    try:
        r = w3.eth.call({"to": a, "data": data2})
        print(n, "maxFlashLoan(self) ->", int.from_bytes(r, "big"))
    except Exception as e:
        print(n, "maxFlashLoan call REVERTS:", str(e)[:100])

# QuickSwap V2 pair WMATIC/USDC + reserves
sel = Web3.keccak(text="getPair(address,address)")[:4].hex()
data = "0x" + sel + enc_addr(AD["WMATIC"]) + enc_addr(AD["USDC"])
r = w3.eth.call({"to": Web3.to_checksum_address(AD["QuickSwapV2Factory"]), "data": data})
pair = "0x" + r.hex()[-40:]
print("QuickSwap WMATIC/USDC pair:", Web3.to_checksum_address(pair),
      "code:", len(w3.eth.get_code(Web3.to_checksum_address(pair))), "bytes")
r = w3.eth.call({"to": Web3.to_checksum_address(pair), "data": "0x0902f1ac"})
res0 = int.from_bytes(r[0:32], "big")
res1 = int.from_bytes(r[32:64], "big")
print("pair reserves:", res0, res1)
# token0 of the pair
r = w3.eth.call({"to": Web3.to_checksum_address(pair), "data": "0x0dfe1681"})
print("pair token0:", "0x" + r.hex()[-40:])
