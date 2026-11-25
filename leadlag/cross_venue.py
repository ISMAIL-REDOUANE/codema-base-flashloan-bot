"""cross_venue.py — SAME-PAIR, CROSS-VENUE price gaps on Base (read-only).

QUESTION (Ismail, 2026-11-25, spotted on DexScreener): the SAME coin, the
SAME pool name, but TWO pools with a BIG price difference — why did WE
never find this gap?

HYPOTHESIS TO TEST: our scanners only ever quoted ONE pool per pair, on
Uniswap V3 only. We NEVER compared the same (token, quote) pair across
venues at the same block. This script does exactly that.

METHOD (all read-only, $0, no broadcast/wallet/keys/funds):
  1. Top ~15 tokens by 24h volume on Base (GeckoTerminal top pools).
  2. For each token, ALL its Base pairs via DexScreener
     (/latest/dex/tokens/{address}) — grouped by the UNORDERED pair
     (token contract address, quote token address). Same NAME/symbol is
     NOT enough: copycat tokens share names with different addresses.
  3. Same-block on-chain quotes: for every pool in a multi-venue group,
     read slot0 + liquidity + fee at ONE block (eth_call, block pinned),
     then compute execution prices with the analytic mono-tick V3 model
     (validated vs QuoterV2 to 0.0001 pp on liquid tiers — see
     leadlag/ROOT_CAUSE_AUDIT.md § cause 5). Cross-check Uni V3 pools
     with QuoterV2 quoteExactInput at the same block; try Pancake
     QuoterV2 (quoteExactInputSingle) and Aerodrome MixedQuoterV3
     (tagged path 0x80000|tickSpacing) where they work — fall back to
     analytic and SAY so.
  4. Net per ordered pair (buy cheap pool -> sell expensive pool) at
     $100/$500/$1,000 after ALL costs (buy fee+impact, sell fee+impact,
     gas $0.0044/trade, flash 0% Morpho). Entry rule (Ismail): net > $0.
  5. Classification of every big gap: REAL vs ARTIFACT (stale pool,
     different quote token, copycat token, honeypot, fee-tier only).

LABELS (per skill label_synthetic_results): every quote is a QUOTE
(never a win/profit/executed trade); every reconstructed net is
SYNTHETIC; live-measured numbers (on-chain reads, DexScreener data)
are labelled LIVE.

RPC: Alchemy URL loaded from config.yaml IN MEMORY ONLY — never
printed, logged, or written to any file. Public mainnet.base.org is
DEAD (RemoteDisconnected, verified 2026-11-25).
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/crypto-base-flashloan-bot")
from v3_quote import v3_quote_python  # noqa: E402  (analytic mono-tick model)

BASE_DIR = Path("/home/hatch/workspace/crypto-base-flashloan-bot/leadlag")
OUT_JSON = BASE_DIR / "cross_venue_results.json"

GT = "https://api.geckoterminal.com/api/v2/networks/base/pools"
DS = "https://api.dexscreener.com/latest/dex"
GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/8453"

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
STABLES = {USDC.lower(), "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"}  # USDC native + bridged

# Verified on-chain (eth_getCode, block 62,072,884) — sizes match audit:
UNI_V3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
UNI_V3_QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
AERO_CLFACTORY_LEGACY = "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"
AERO_CLFACTORY_GAUGE_CAPS = "0xaDe65c38CD4849aDBA595a4323a8C7DdfE89716a"
AERO_CLFACTORY_GAUGES_V3 = "0xf8f2eB4940CFE7d13603DDDD87f123820Fc061Ef"
AERO_MIXED_QUOTER_V3 = "0xCd2A7D98e82D6107eac1828ce8DeAA6acB65b555"
AERO_FACTORY_REGISTRY = "0x5C3F18F06CC09CA1910767A34a20F771039E37C0"
CAKE_V3_FACTORY = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
CAKE_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

GAS_USD_PER_TRADE = 0.0044   # measured Base gas (expert scan, 0.006 gwei)
SIZES_USD = [100, 500, 1000]
N_TOKENS = 15

# ------------------------------------------------------------------ helpers
def http_get_json(url, timeout=20, headers=None):
    h = {"User-Agent": "codema-cross-venue-scan/1.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _load_rpc():
    txt = Path("/home/hatch/workspace/crypto-base-flashloan-bot/config.yaml").read_text()
    m = re.search(r'rpc_url:\s*"([^"]+)"', txt)
    if not m:
        raise RuntimeError("no Alchemy rpc_url in config.yaml")
    return m.group(1)


RPC = _load_rpc()


def rpc_call(method, params, timeout=20):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                          "params": params}).encode()
    req = urllib.request.Request(RPC, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if "error" in out:
        raise RuntimeError(str(out["error"]))
    return out["result"]


def eth_call(to, data_hex, block="latest", timeout=20):
    return rpc_call("eth_call", [{"to": to, "data": data_hex},
                                 hex(block) if isinstance(block, int) else block],
                    timeout=timeout)


def eth_get_code(addr):
    return rpc_call("eth_getCode", [addr, "latest"])


def keccak_sel(sig):
    from web3 import Web3
    return Web3.keccak(text=sig)[:4].hex()


def _addr_b32(a):
    return bytes.fromhex(a[2:].lower().rjust(64, "0"))


def _uint_b32(v):
    return int(v).to_bytes(32, "big")


# Selectors (computed, not hardcoded magic)
SEL_SLOT0 = None
SEL_LIQ = None
SEL_FEE = None
SEL_TICK_SPACING = None
SEL_TOKEN0 = None
SEL_TOKEN1 = None
SEL_DECIMALS = None
SEL_GLOBAL_STATE = None


def init_selectors():
    global SEL_SLOT0, SEL_LIQ, SEL_FEE, SEL_TICK_SPACING, SEL_TOKEN0, SEL_TOKEN1, SEL_DECIMALS, SEL_GLOBAL_STATE
    SEL_SLOT0 = keccak_sel("slot0()")
    SEL_LIQ = keccak_sel("liquidity()")
    SEL_FEE = keccak_sel("fee()")
    SEL_TICK_SPACING = keccak_sel("tickSpacing()")
    SEL_TOKEN0 = keccak_sel("token0()")
    SEL_TOKEN1 = keccak_sel("token1()")
    SEL_DECIMALS = keccak_sel("decimals()")
    SEL_GLOBAL_STATE = keccak_sel("globalState()")


def parse_slot0(raw):
    b = bytes.fromhex(raw[2:])
    sqrt_x96 = int.from_bytes(b[0:32], "big")
    tick_raw = int.from_bytes(b[32:64], "big")
    tick = tick_raw - (1 << 256) if tick_raw >= (1 << 255) else tick_raw
    return sqrt_x96, tick


def pool_state(pool, block):
    """slot0 + liquidity + fee + token0/token1 + tickSpacing at a pinned block.
    Returns dict or {'error': ...}. fee() may revert on some pools (then None)."""
    out = {"pool": pool}
    try:
        out["sqrt_x96"], out["tick"] = parse_slot0(eth_call(pool, "0x" + SEL_SLOT0, block))
    except Exception as e:
        out["error"] = f"slot0: {type(e).__name__}: {str(e)[:100]}"
        return out
    try:
        out["liq"] = int.from_bytes(bytes.fromhex(eth_call(pool, "0x" + SEL_LIQ, block)[2:]), "big")
    except Exception as e:
        out["error"] = f"liquidity: {type(e).__name__}: {str(e)[:100]}"
        return out
    try:
        out["fee_bps"] = int.from_bytes(bytes.fromhex(eth_call(pool, "0x" + SEL_FEE, block)[2:]), "big")
    except Exception:
        out["fee_bps"] = None
    try:
        out["tick_spacing"] = int.from_bytes(bytes.fromhex(eth_call(pool, "0x" + SEL_TICK_SPACING, block)[2:]), "big")
    except Exception:
        out["tick_spacing"] = None
    try:
        out["token0"] = "0x" + eth_call(pool, "0x" + SEL_TOKEN0, block)[-40:]
        out["token1"] = "0x" + eth_call(pool, "0x" + SEL_TOKEN1, block)[-40:]
    except Exception:
        out["token0"] = out["token1"] = None
    return out


def algebra_state(pool, block):
    """Algebra CLAMM globalState() -> {'sqrt_x96','tick','fee_bps'} or None.
    QuickSwap V4, Hydrex and other Algebra forks expose the price here
    (slot0() does not exist on them). Same sqrtPriceX96 format as Uni V3."""
    try:
        raw = eth_call(pool, "0x" + SEL_GLOBAL_STATE, block)
        b = bytes.fromhex(raw[2:])
        if len(b) < 96:
            return None
        sqrt_x96 = int.from_bytes(b[0:32], "big")
        tick_raw = int.from_bytes(b[32:64], "big")
        tick = tick_raw - (1 << 256) if tick_raw >= (1 << 255) else tick_raw
        fee_bps = int.from_bytes(b[64:96], "big")
        if sqrt_x96 == 0:
            return None
        return {"sqrt_x96": sqrt_x96, "tick": tick, "fee_bps": fee_bps}
    except Exception:
        return None


_DECIMALS_CACHE = {}


def token_decimals(addr):
    """Décimales d'un token, lues on-chain (decimals()).
    CORRECTION 2026-11-25 (route verification) : l'ancienne version
    retombait SILENCIEUSEMENT sur 18 en cas d'échec RPC et METTAIT EN
    CACHE ce 18 — un decimals() USDC raté (429) faisait croire que USDC
    a 18 décimales, ce qui faussait TOUT le calcul (impact ~100% du
    montant, net ~ -$100 sur WETH/USDC et cbBTC/USDC). Désormais :
    retries, puis échec BRUYANT (jamais de valeur par défaut)."""
    import time as _time
    a = addr.lower()
    if a in _DECIMALS_CACHE:
        return _DECIMALS_CACHE[a]
    last = None
    for attempt in range(3):
        try:
            d = int.from_bytes(bytes.fromhex(eth_call(addr, "0x" + SEL_DECIMALS, "latest")[2:]), "big")
            if 0 <= d <= 18:
                _DECIMALS_CACHE[a] = d
                return d
            last = RuntimeError(f"decimals() = {d} hors plage pour {addr}")
        except Exception as e:  # noqa: BLE001 — 429/timeout réseau
            last = e
        _time.sleep(1 + attempt)
    raise RuntimeError(f"token_decimals({addr}) impossible après 3 essais "
                       f"(pas de valeur par défaut) : {type(last).__name__}: {str(last)[:100]}")


def price_from_sqrt(sqrt_x96, dec_token, dec_quote, token_is_token0):
    """Quote-token per 1 token, from sqrtPriceX96.
    token_is_token0: the traded token is token0 of the pool."""
    sqrt_p = sqrt_x96 / 2 ** 96
    adj = 10.0 ** (dec_token - dec_quote)
    if token_is_token0:
        return sqrt_p * sqrt_p * adj
    return adj / (sqrt_p * sqrt_p)


def analytic_quote_raw(amount_in_raw, liq, sqrt_x96, fee_bps, token_is_token0, dec_token, dec_quote, direction):
    """Mono-tick analytic quote, raw amounts in/out (same math as
    v3_quote.v3_quote_python). Works for ANY quote token.
    NOTE on units: fee_bps here is the ON-CHAIN fee (hundredths of a bip:
    500 = 0.05%, 3000 = 0.3%). v3_quote_python expects TRUE basis points
    (10000 = 100%), so we divide by 100 before calling it. (Passing 500
    straight through would apply a 5% fee — a real bug caught in testing.)"""
    if direction == "buy":
        quote_is_token0 = not token_is_token0
        q = v3_quote_python(float(amount_in_raw), float(liq), sqrt_x96,
                            fee_bps=fee_bps / 100.0, zero_for_one=quote_is_token0)
        return q.amount_out / 10 ** dec_token, q.crossed_tick, q.source
    else:
        q = v3_quote_python(float(amount_in_raw), float(liq), sqrt_x96,
                            fee_bps=fee_bps / 100.0, zero_for_one=token_is_token0)
        return q.amount_out / 10 ** dec_quote, q.crossed_tick, q.source

# ------------------------------------------------------------------ venue quoters (cross-checks)
def _first_word(raw_hex):
    """First 32-byte word of an eth_call return value (hex string)."""
    b = bytes.fromhex(raw_hex[2:])
    return int.from_bytes(b[0:32], "big")


def uni_quoter_quote(token_in, token_out, fee_bps, amount_in_raw, block):
    """Uni V3 QuoterV2 quoteExactInput (path, 1 hop) — known-good on Base.
    Returns amount_out raw or None."""
    try:
        path = bytes.fromhex(token_in[2:]) + int(fee_bps).to_bytes(3, "big") + bytes.fromhex(token_out[2:])
        padded = path + b"\x00" * ((32 - len(path) % 32) % 32)
        data = ("0x" + keccak_sel("quoteExactInput(bytes,uint256)")
                + _uint_b32(0x40).hex() + _uint_b32(amount_in_raw).hex()
                + _uint_b32(len(path)).hex() + padded.hex())
        raw = eth_call(UNI_V3_QUOTER_V2, data, block)
        return _first_word(raw)
    except Exception:
        return None


def cake_quoter_quote(token_in, token_out, fee_bps, amount_in_raw, block):
    """PancakeSwap V3 QuoterV2 — try quoteExactInputSingle first, then
    quoteExactInput (path). Returns (amount_out raw, method) or (None, None)."""
    try:
        data = ("0x" + keccak_sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)")
                + _addr_b32(token_in).hex() + _addr_b32(token_out).hex()
                + _uint_b32(fee_bps).hex() + _uint_b32(amount_in_raw).hex()
                + _uint_b32(0).hex())
        raw = eth_call(CAKE_QUOTER_V2, data, block)
        return _first_word(raw), "cake_quoter_v2_single"
    except Exception:
        pass
    try:
        path = bytes.fromhex(token_in[2:]) + int(fee_bps).to_bytes(3, "big") + bytes.fromhex(token_out[2:])
        padded = path + b"\x00" * ((32 - len(path) % 32) % 32)
        data = ("0x" + keccak_sel("quoteExactInput(bytes,uint256)")
                + _uint_b32(0x40).hex() + _uint_b32(amount_in_raw).hex()
                + _uint_b32(len(path)).hex() + padded.hex())
        raw = eth_call(CAKE_QUOTER_V2, data, block)
        return _first_word(raw), "cake_quoter_v2_path"
    except Exception:
        return None, None


def aero_mixed_quoter(token_in, token_out, tick_spacing, amount_in_raw, block):
    """Aerodrome MixedQuoterV3 quoteExactInput with tagged path
    (hop = 0x80000 | tickSpacing for the Gauges V3 factory).
    Returns amount_out raw or None."""
    try:
        hop = 0x80000 | int(tick_spacing)
        path = bytes.fromhex(token_in[2:]) + int(hop).to_bytes(3, "big") + bytes.fromhex(token_out[2:])
        padded = path + b"\x00" * ((32 - len(path) % 32) % 32)
        data = ("0x" + keccak_sel("quoteExactInput(bytes,uint256)")
                + _uint_b32(0x40).hex() + _uint_b32(amount_in_raw).hex()
                + _uint_b32(len(path)).hex() + padded.hex())
        raw = eth_call(AERO_MIXED_QUOTER_V3, data, block)
        return _first_word(raw)
    except Exception:
        return None


# ------------------------------------------------------------------ discovery
def top_tokens(n=N_TOKENS):
    """Top n tokens by 24h volume on Base, from GeckoTerminal top pools."""
    vols = {}  # addr -> {symbol, max_vol24, name}
    for page in (1, 2):
        data = http_get_json(f"{GT}?page={page}")
        for pool in data.get("data", []):
            attr = pool["attributes"]
            vol24 = float(attr.get("volume_usd", {}).get("h24", 0) or 0)
            # pool name: "SYM1 / SYM2 0.01%" -> symbols per side
            name = attr.get("name", "") or ""
            parts = [s.strip() for s in name.split("/")]
            syms = []
            for part in parts:
                m = re.match(r"^([A-Za-z0-9$._-]+)", part.strip())
                syms.append(m.group(1) if m else "?")
            rel = pool.get("relationships", {})
            sides = []
            for i, side in enumerate(("base_token", "quote_token")):
                tid = rel.get(side, {}).get("data", {}).get("id", "")
                if not tid.startswith("base_0x"):
                    continue
                sides.append((tid[5:], syms[i] if i < len(syms) else "?"))
            for addr, sym in sides:
                if addr.lower() in STABLES or addr.lower() == WETH.lower():
                    continue
                cur = vols.get(addr.lower())
                if cur is None or vol24 > cur["max_vol24"]:
                    vols[addr.lower()] = {"address": addr, "symbol": sym,
                                          "max_vol24": vol24}
        time.sleep(0.5)
    ranked = sorted(vols.values(), key=lambda x: -x["max_vol24"])[:n]
    return ranked


def token_pairs(addr):
    """ALL DexScreener pairs for a token (all chains) — filter Base here."""
    data = http_get_json(f"{DS}/tokens/{addr}")
    return [p for p in data.get("pairs", []) if p.get("chainId") == "base"]


def search_symbol(symbol):
    """DexScreener search by symbol — surfaces copycats (same symbol,
    different contract address)."""
    try:
        data = http_get_json(f"{DS}/search?q={symbol}")
    except Exception:
        return []
    out = {}
    for p in data.get("pairs", []):
        if p.get("chainId") != "base":
            continue
        bt = p.get("baseToken", {})
        if bt.get("symbol", "").upper() == symbol.upper():
            out[bt.get("address", "").lower()] = bt.get("symbol")
    return out


def goplus_check(addresses):
    """GoPlus honeypot/tax flags (best-effort; returns {} if unreachable)."""
    try:
        qs = ",".join(addresses)
        data = http_get_json(f"{GOPLUS}?contract_addresses={qs}", timeout=25)
        return data.get("result", {}) or {}
    except Exception as e:
        return {"_error": str(e)[:120]}


# ------------------------------------------------------------------ net math
def roundtrip_net(buy_pool, sell_pool, size_usd, dec_token, dec_quote, usd_price_quote, block):
    """Buy $size_usd of token in buy_pool (quote->token), sell the token
    received in sell_pool (token->quote). SYNTHETIC net (analytic / getAmountOut
    quotes, never executed). Returns dict or None if a leg is invalid."""
    tok_out, m1 = buy_tokens(buy_pool, size_usd, usd_price_quote, dec_token, dec_quote, block)
    if not tok_out:
        return None
    usd_out, m2 = sell_tokens(sell_pool, tok_out, usd_price_quote, dec_token, dec_quote, block)
    if usd_out is None:
        return None
    net = usd_out - size_usd - GAS_USD_PER_TRADE
    return {"size_usd": size_usd, "token_bought": tok_out, "usd_out": usd_out,
            "net_usd": net, "gas_usd": GAS_USD_PER_TRADE,
            "buy_fee_bps": buy_pool.get("fee_bps"), "sell_fee_bps": sell_pool.get("fee_bps"),
            "methods": f"{m1}->{m2}"}


def classify_gap(group, gap_pct, best_net_by_size, pools_meta):
    """REAL vs ARTIFACT with a reason. group = list of pool dicts."""
    reasons = []
    # stale / thin?
    live = [p for p in pools_meta if (p.get("txns_h24") or 0) > 0 and (p.get("liq_usd") or 0) >= 1000]
    if len(live) < 2:
        reasons.append("stale/thin: fewer than 2 pools with txns_h24>0 and TVL>=$1k")
    # any size with net > 0?
    real_sizes = [s for s, n in best_net_by_size.items() if n is not None and n > 0]
    if not real_sizes:
        reasons.append("net<=0 at every size ($100/$500/$1k) after all costs")
    if reasons:
        return "ARTIFACT", "; ".join(reasons)
    return "REAL", f"net>0 at sizes {real_sizes}"

# ------------------------------------------------------------------ V2 fallback
def v2_reserves(pool, block):
    try:
        raw = eth_call(pool, "0x" + keccak_sel("getReserves()"), block)
        b = bytes.fromhex(raw[2:])
        return int.from_bytes(b[0:32], "big"), int.from_bytes(b[32:64], "big")
    except Exception:
        return None


def v2_quote(amount_in_raw, reserve_in, reserve_out, fee=0.003):
    """x*y=k exact-input quote (single hop, fee on input)."""
    if reserve_in <= 0 or reserve_out <= 0 or amount_in_raw <= 0:
        return 0.0
    a = amount_in_raw * (1.0 - fee)
    return a * reserve_out / (reserve_in + a)




def buy_tokens(pool_rec, size_usd, usd_price_quote, dec_token, dec_quote, block):
    """Buy $size_usd of token in pool_rec. Returns (token_amount_human, method)
    or (None, method). V2: x*y=k formula on reserves (standard V2 pairs only).
    CL: analytic mono-tick (fee + impact)."""
    oc = pool_rec.get("onchain", {})
    quote_raw = int(size_usd / usd_price_quote * 10 ** dec_quote)
    if quote_raw <= 0:
        return None, "zero_input"
    if oc.get("v2"):
        r_in = oc["reserve1"] if pool_rec["token_is_token0"] else oc["reserve0"]
        r_out = oc["reserve0"] if pool_rec["token_is_token0"] else oc["reserve1"]
        out_raw = v2_quote(quote_raw, r_in, r_out, fee=0.003)
        return (out_raw / 10 ** dec_token, "v2_cp") if out_raw > 0 else (None, "v2_cp")
    if oc.get("liq") is None or pool_rec.get("fee_bps") is None:
        return None, "unavailable"
    tok, _crossed, _ = analytic_quote_raw(quote_raw, oc["liq"], oc["sqrt_x96"],
                                          pool_rec["fee_bps"],
                                          pool_rec["token_is_token0"],
                                          dec_token, dec_quote, "buy")
    return (tok if tok and tok > 0 else None), "cl_analytic"


def sell_tokens(pool_rec, token_amount_human, usd_price_quote, dec_token, dec_quote, block):
    """Sell token_amount_human of token in pool_rec. Returns (usd_received, method)
    or (None, method)."""
    oc = pool_rec.get("onchain", {})
    token_raw = int(token_amount_human * 10 ** dec_token)
    if token_raw <= 0:
        return None, "zero_input"
    if oc.get("v2"):
        r_in = oc["reserve0"] if pool_rec["token_is_token0"] else oc["reserve1"]
        r_out = oc["reserve1"] if pool_rec["token_is_token0"] else oc["reserve0"]
        out_raw = v2_quote(token_raw, r_in, r_out, fee=0.003)
        if out_raw <= 0:
            return None, "v2_cp"
        return (out_raw / 10 ** dec_quote) * usd_price_quote, "v2_cp"
    if oc.get("liq") is None or pool_rec.get("fee_bps") is None:
        return None, "unavailable"
    quote_human, _crossed, _ = analytic_quote_raw(token_raw, oc["liq"], oc["sqrt_x96"],
                                                  pool_rec["fee_bps"],
                                                  pool_rec["token_is_token0"],
                                                  dec_token, dec_quote, "sell")
    if not quote_human or quote_human <= 0:
        return None, "cl_analytic"
    return quote_human * usd_price_quote, "cl_analytic"


# ------------------------------------------------------------------ main
def main():
    import datetime
    init_selectors()
    t0 = time.time()
    print("=== CROSS-VENUE SAME-PAIR SCAN (Base, read-only) ===", flush=True)
    block = int(rpc_call("eth_blockNumber", []), 16)
    print(f"quote block (pinned for all on-chain reads): {block}", flush=True)

    # 1. top tokens
    tokens = top_tokens(N_TOKENS)
    print(f"top {len(tokens)} tokens by 24h volume (GeckoTerminal): "
          + ", ".join(f"{t['symbol']}(${t['max_vol24']/1e6:.1f}M)" for t in tokens), flush=True)
    # explicit extra checks: WETH and cbBTC quoted in USDC (biggest pairs)
    tokens.append({"address": WETH, "symbol": "WETH", "max_vol24": 0, "explicit": True})
    tokens.append({"address": CBBTC, "symbol": "cbBTC", "max_vol24": 0, "explicit": True})

    # 2. all pairs per token + grouping
    groups = {}   # (token_addr_lower, quote_addr_lower) unordered -> group dict
    copycats = {}
    for tok in tokens:
        addr = tok["address"]
        sym = tok["symbol"]
        try:
            pairs = token_pairs(addr)
        except Exception as e:
            print(f"  {sym}: DexScreener error {e}", flush=True)
            continue
        # copycat search (same symbol, different contract)
        try:
            found = search_symbol(sym)
            others = [a for a in found if a != addr.lower()]
            if others:
                copycats[sym] = {"real": addr, "copycats": others}
        except Exception:
            pass
        for p in pairs:
            bt, qt = p.get("baseToken", {}), p.get("quoteToken", {})
            ba, qa = bt.get("address", "").lower(), qt.get("address", "").lower()
            if not ba or not qa:
                continue
            key = tuple(sorted((ba, qa)))
            g = groups.setdefault(key, {"token_a": ba, "token_b": qa, "pools": []})
            liq = p.get("liquidity", {}) or {}
            vol = p.get("volume", {}) or {}
            tx = p.get("txns", {}) or {}
            h24 = tx.get("h24", {}) or {}
            g["pools"].append({
                "venue": p.get("dexId"), "pair_address": p.get("pairAddress"),
                "base_symbol": bt.get("symbol"), "quote_symbol": qt.get("symbol"),
                "base_addr": ba, "quote_addr": qa,
                "price_usd_ds": float(p.get("priceUsd") or 0),
                "price_native_ds": p.get("priceNative"),
                "liq_usd": float(liq.get("usd") or 0),
                "vol_h24_usd": float(vol.get("h24") or 0),
                "txns_h24": int(h24.get("buys", 0) or 0) + int(h24.get("sells", 0) or 0),
                "buys_h24": int(h24.get("buys", 0) or 0),
                "sells_h24": int(h24.get("sells", 0) or 0),
                "pair_created_at": p.get("pairCreatedAt"),
                "labels": p.get("labels", []),
                "url": p.get("url"),
            })
        time.sleep(0.2)
    print(f"token groups found: {len(groups)}", flush=True)

    # keep groups with >=2 pools on DIFFERENT venues (the cross-venue question),
    # plus same-venue multi-tier groups (fee-tier-only classification)
    multi = []
    for key, g in groups.items():
        venues = {p["venue"] for p in g["pools"]}
        if len(g["pools"]) >= 2 and (len(venues) >= 2 or len(g["pools"]) >= 2):
            # identify the traded token: the non-stable side if present
            a, b = key
            token_addr = a if a not in STABLES and b in STABLES else (
                b if b not in STABLES and a in STABLES else a)
            quote_addr = b if token_addr == a else a
            g["token_addr"] = token_addr
            g["quote_addr"] = quote_addr
            g["cross_venue"] = len(venues) >= 2
            multi.append(g)
    print(f"multi-pool groups (>=2 pools): {len(multi)} "
          f"({sum(1 for g in multi if g['cross_venue'])} cross-venue)", flush=True)

    # 3. same-block on-chain state for every pool in multi groups
    dec_token = {}
    jobs = []
    for g in multi:
        for p in g["pools"]:
            jobs.append((g, p))

    def fetch_state(job):
        g, p = job
        st = pool_state(p["pair_address"], block)
        return g, p, st

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_state, jobs))

    # attach state + compute mid + execution prices.
    # Pool-type detection order matters: (1) slot0 -> Uni V3 / Pancake /
    # Aerodrome Slipstream CL; (2) globalState -> Algebra CLAMM (QuickSwap V4,
    # Hydrex — they ALSO expose a getReserves-like view, so V2 must be tried
    # LAST or they get misread as V2 pairs); (3) getReserves -> standard V2.
    for g, p, st in results:
        dec = token_decimals(g["token_addr"])
        dec_token[g["token_addr"]] = dec
        qdec = token_decimals(g["quote_addr"])
        st2 = None
        pool_type = None
        if "sqrt_x96" in st:
            st2 = st
            pool_type = "cl"
        else:
            alg = algebra_state(p["pair_address"], block)
            if alg:
                try:
                    liq = int.from_bytes(bytes.fromhex(eth_call(p["pair_address"], "0x" + SEL_LIQ, block)[2:]), "big")
                except Exception:
                    liq = None
                try:
                    t0a = "0x" + eth_call(p["pair_address"], "0x" + SEL_TOKEN0, block)[-40:]
                    t1a = "0x" + eth_call(p["pair_address"], "0x" + SEL_TOKEN1, block)[-40:]
                except Exception:
                    t0a = t1a = None
                st2 = {"algebra": True, "sqrt_x96": alg["sqrt_x96"], "tick": alg["tick"],
                       "fee_bps": alg["fee_bps"], "liq": liq, "token0": t0a, "token1": t1a}
                pool_type = "cl"
            else:
                res = v2_reserves(p["pair_address"], block)
                if res:
                    try:
                        t0a = "0x" + eth_call(p["pair_address"], "0x" + SEL_TOKEN0, block)[-40:]
                        t1a = "0x" + eth_call(p["pair_address"], "0x" + SEL_TOKEN1, block)[-40:]
                    except Exception:
                        t0a = t1a = None
                    st2 = {"v2": True, "reserve0": res[0], "reserve1": res[1],
                           "token0": t0a, "token1": t1a}
                    pool_type = "v2"
                else:
                    continue
        p["onchain"] = st2
        p["pool_type"] = pool_type
        if pool_type == "v2":
            t0a, t1a = st2.get("token0"), st2.get("token1")
            if t0a and t0a.lower() == g["token_addr"].lower():
                p["token_is_token0"] = True
                p["mid_price"] = (st2["reserve1"] / 10 ** qdec) / (st2["reserve0"] / 10 ** dec)
            elif t1a and t1a.lower() == g["token_addr"].lower():
                p["token_is_token0"] = False
                p["mid_price"] = (st2["reserve0"] / 10 ** qdec) / (st2["reserve1"] / 10 ** dec)
            else:
                p["mid_price"] = None
                p["token_is_token0"] = None
            p["mid_method"] = "v2_cp_ratio"
            p["fee_bps"] = 3000  # V2 volatile assumption (0.3%, on-chain units) — labelled in report
            p["fee_assumed"] = True
        else:
            tok0 = (st2.get("token0") or "").lower()
            p["token_is_token0"] = (tok0 == g["token_addr"].lower())
            p["mid_price"] = price_from_sqrt(st2["sqrt_x96"], dec, qdec,
                                             p["token_is_token0"])
            p["mid_method"] = "algebra_globalState" if st2.get("algebra") else "cl_sqrt"
            p["fee_bps"] = st2.get("fee_bps")
            p["fee_assumed"] = False

    # USD price of the quote token per group (DexScreener price + on-chain mid)
    for g in multi:
        quote_usd = None
        for p in g["pools"]:
            mid = p.get("mid_price")
            ds = p.get("price_usd_ds")
            if not mid or not ds:
                continue
            if (p.get("base_addr") or "").lower() == g["token_addr"].lower():
                quote_usd = ds / mid  # DS price is the token's USD price
            elif (p.get("base_addr") or "").lower() == g["quote_addr"].lower():
                quote_usd = ds  # DS price is the quote's USD price
            if quote_usd:
                break
        g["usd_price_quote"] = quote_usd
        if quote_usd and (g["quote_addr"].lower() in {s.lower() for s in STABLES}):
            g["usd_price_quote_sanity"] = abs(quote_usd - 1.0)
        # V2 sanity: a genuine V2 pair's CP mid must agree with the CL pools'
        # median mid in the same group. A >5% deviation means the pool is
        # misread (stable invariant or CLAMM that slipped through) — exclude
        # it from net math (its CP "price" is not tradeable at that level).
        cl_mids = [p["mid_price"] for p in g["pools"]
                   if p.get("pool_type") == "cl" and p.get("mid_price")]
        if cl_mids:
            cl_mids.sort()
            med = cl_mids[len(cl_mids) // 2]
            for p in g["pools"]:
                if p.get("pool_type") == "v2" and p.get("mid_price"):
                    dev = abs(p["mid_price"] / med - 1.0)
                    p["v2_mid_dev_vs_cl_pct"] = round(dev * 100, 3)
                    if dev > 0.05:
                        p["v2_mid_excluded"] = True
        # execution prices per size, via buy_tokens (V2 getAmountOut / CL analytic)
        dec = dec_token.get(g["token_addr"], 18)
        qdec = token_decimals(g["quote_addr"])
        for p in g["pools"]:
            p["exec_buy"] = {}
            if p.get("mid_price") is None or not quote_usd:
                for size in SIZES_USD:
                    p["exec_buy"][size] = None
                continue
            for size in SIZES_USD:
                tok, _m = buy_tokens(p, size, quote_usd, dec, qdec, block)
                p["exec_buy"][size] = (size / tok) if tok and tok > 0 else None

    # quoter cross-checks (Uni V3 / Pancake / Aerodrome) at the same block
    for g, p, st in results:
        p["quoter_check"] = None
        oc = p.get("onchain", {})
        if oc.get("v2") or "error" in oc:
            continue
        venue = (p["venue"] or "").lower()
        fee = p.get("fee_bps")
        if fee is None:
            continue
        tok = g["token_addr"]
        quo = g["quote_addr"]
        dec = dec_token.get(tok, 18)
        qdec = token_decimals(quo)
        upq = g.get("usd_price_quote") or 1.0
        # buy $100 of token with quote token — raw amounts
        amt_in_raw = int(100 / upq * 10 ** qdec)
        out_raw = None
        method = None
        if venue == "uniswap":
            out_raw = uni_quoter_quote(quo, tok, fee, amt_in_raw, block)
            method = "uni_quoter_v2"
        elif venue == "pancakeswap":
            out_raw, method = cake_quoter_quote(quo, tok, fee, amt_in_raw, block)
        elif venue in ("aerodrome", "aero"):
            ts = oc.get("tick_spacing")
            if ts is not None:
                out_raw = aero_mixed_quoter(quo, tok, ts, amt_in_raw, block)
                method = "aero_mixed_quoter_v3"
        if out_raw:
            tok_out = out_raw / 10 ** dec
            px = 100.0 / tok_out if tok_out > 0 else None
            ana = p["exec_buy"].get(100)
            p["quoter_check"] = {"method": method, "exec_px_100": px,
                                 "analytic_px_100": ana,
                                 "diff_pct": ((px - ana) / ana * 100.0
                                            if px and ana else None)}
        else:
            p["quoter_check"] = {"method": method or "n/a", "exec_px_100": None,
                                 "note": "quoter call failed/reverted — analytic only"}

    # 4. nets + classification per group
    out_groups = []
    for g in multi:
        pools = [p for p in g["pools"] if p.get("mid_price")]
        if len(pools) < 2:
            continue
        mids = [p["mid_price"] for p in pools]
        mid_gap = (max(mids) - min(mids)) / min(mids) * 100.0
        # DexScreener gap (what Ismail saw)
        ds_prices = [p["price_usd_ds"] for p in pools if p.get("price_usd_ds")]
        ds_gap = ((max(ds_prices) - min(ds_prices)) / min(ds_prices) * 100.0
                  if len(ds_prices) >= 2 and min(ds_prices) > 0 else None)
        dec = dec_token.get(g["token_addr"], 18)
        qdec = token_decimals(g["quote_addr"])
        upq = g.get("usd_price_quote")
        best_net = {}
        best_pair = {}
        tier_pairs = []  # MULTI-TIER: every ordered pool pair, net by size
        for size in SIZES_USD:
            best = None
            best_desc = None
            for buy in pools:
                for sell in pools:
                    if buy is sell:
                        continue
                    if upq is None:
                        continue
                    if buy.get("v2_mid_excluded") or sell.get("v2_mid_excluded"):
                        continue  # misread V2 mid — not tradeable at CP price
                    r = roundtrip_net(buy, sell, size, dec, qdec, upq, block)
                    if r is None:
                        continue
                    # threshold for this tier pair at this size, before impact:
                    # (buy fee + sell fee) + gas/size, in %. Fees are on-chain
                    # units (500 = 0.05%), so /10000 gives percent.
                    thr = (((buy.get("fee_bps") or 0) + (sell.get("fee_bps") or 0)) / 10000.0
                           + GAS_USD_PER_TRADE / size * 100.0)
                    tier_pairs.append({
                        "size_usd": size,
                        "buy_venue": buy["venue"], "buy_fee_bps": buy.get("fee_bps"),
                        "buy_pair": buy["pair_address"],
                        "sell_venue": sell["venue"], "sell_fee_bps": sell.get("fee_bps"),
                        "sell_pair": sell["pair_address"],
                        "threshold_pct": round(thr, 4),
                        "net_usd": round(r["net_usd"], 4),
                        "methods": r.get("methods"),
                    })
                    if best is None or r["net_usd"] > best:
                        best = r["net_usd"]
                        best_desc = f"buy {buy['venue']}:{buy['pair_address'][:10]}.. -> sell {sell['venue']}:{sell['pair_address'][:10]}.."
            best_net[size] = best
            best_pair[size] = best_desc
        cls, reason = classify_gap(g, mid_gap, best_net, pools)
        out_groups.append({
            "token_addr": g["token_addr"], "quote_addr": g["quote_addr"],
            "token_symbol": next((p["base_symbol"] for p in pools
                                  if (p.get("base_addr") or "").lower() == g["token_addr"].lower()), None)
                or next((p["quote_symbol"] for p in pools
                         if (p.get("quote_addr") or "").lower() == g["token_addr"].lower()), "?"),
            "cross_venue": g["cross_venue"],
            "usd_price_quote": g.get("usd_price_quote"),
            "usd_price_quote_sanity": g.get("usd_price_quote_sanity"),
            "mid_gap_pct_live": round(mid_gap, 4),
            "ds_gap_pct": round(ds_gap, 4) if ds_gap is not None else None,
            "best_net_usd": {str(s): (round(best_net[s], 4) if best_net[s] is not None else None)
                             for s in SIZES_USD},
            "best_pair": best_pair,
            "tier_pairs": tier_pairs,
            "classification": cls, "reason": reason,
            "pools": [{
                "venue": p["venue"], "pair_address": p["pair_address"],
                "pool_type": p.get("pool_type"),
                "fee_bps": p.get("fee_bps"), "fee_assumed": p.get("fee_assumed", False),
                "mid_method": p.get("mid_method"),
                "stable_pool_suspected": p.get("stable_pool_suspected"),
                "v2_mid_dev_vs_cl_pct": p.get("v2_mid_dev_vs_cl_pct"),
                "v2_mid_excluded": p.get("v2_mid_excluded", False),
                "liq_usd_ds": p.get("liq_usd"), "vol_h24_usd": p.get("vol_h24_usd"),
                "txns_h24": p.get("txns_h24"), "buys_h24": p.get("buys_h24"),
                "sells_h24": p.get("sells_h24"),
                "price_usd_ds": p.get("price_usd_ds"),
                "mid_price_live": p.get("mid_price"),
                "exec_buy_usd_per_token": {str(s): p.get("exec_buy", {}).get(s)
                                           for s in SIZES_USD},
                "quoter_check": p.get("quoter_check"),
                "onchain_liq": p.get("onchain", {}).get("liq"),
                "onchain_tick": p.get("onchain", {}).get("tick"),
            } for p in pools],
        })
    out_groups.sort(key=lambda x: -(x["best_net_usd"].get("100") or -1e9))

    # 5. GoPlus on the tokens (best-effort)
    token_addrs = list({g["token_addr"] for g in out_groups})
    goplus = goplus_check(token_addrs) if token_addrs else {}

    result = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "block": block,
        "gas_usd_per_trade": GAS_USD_PER_TRADE,
        "sizes_usd": SIZES_USD,
        "tokens_scanned": [{"symbol": t["symbol"], "address": t["address"],
                            "max_vol24_usd": t["max_vol24"]} for t in tokens],
        "copycats": copycats,
        "groups": out_groups,
        "real_gaps": [g for g in out_groups if g["classification"] == "REAL"],
        "goplus": goplus,
        "duration_s": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(result, indent=1))
    print(f"\nDONE in {result['duration_s']}s — {len(out_groups)} groups, "
          f"{len(result['real_gaps'])} REAL gaps -> {OUT_JSON}", flush=True)
    for g in out_groups:
        print(f"  {g['token_symbol']:8s} cross={g['cross_venue']} mid_gap={g['mid_gap_pct_live']:.3f}% "
              f"ds_gap={g['ds_gap_pct']} net100={g['best_net_usd'].get('100')} "
              f"net500={g['best_net_usd'].get('500')} net1000={g['best_net_usd'].get('1000')} "
              f"-> {g['classification']} ({g['reason']})", flush=True)
    return result


if __name__ == "__main__":
    main()
