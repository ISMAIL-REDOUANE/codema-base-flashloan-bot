#!/usr/bin/env python3
"""
amoy_detector.py — Détecteur paper-trade Polygon Amoy (v4.0).

LECTURE SEULE, testnet Amoy (chaîne 80002) uniquement.
  - Aucun broadcast, aucune transaction signée, aucun wallet,
    aucune clé privée, aucun fonds réel. Ce script ne contient
    AUCUN code de signature : il ne fait que des eth_call / eth_getCode.
  - Il poll les pools DEX des venues déclarées "present" dans
    amoy_config.yaml, calcule le spread cross-venue avec le moteur
    mathématique du bot (math_engine.py), et journalise chaque
    opportunité SIMULÉE dont le profit net est > 0 $ APRÈS TOUS LES
    COÛTS (flash fee 0 %, frais de swap, gas, budget revert) dans
    amoy_opportunities.jsonl — avec un flag `gte_3_usd` (true si le
    net est ≥ 3 $). RÈGLE DU 2026-11-24 (Ismail) : le min profit de
    3 $ est ABANDONNÉ comme seuil de journalisation ; la RÈGLE
    D'ARRÊT reste évaluée sur les opps ≥ 3 $ (voir README.md).
  - Les spreads dont le net est ≤ 0 $ après tous les coûts ne sont
    JAMAIS journalisés un par un : ils sont comptés dans
    daily_summary.json (compteurs par jour).

État vérifié 2026-11-24 : AUCUNE venue n'est déployée sur Amoy
(eth_getCode vide pour les 13 adresses canoniques ; liste officielle
Uniswap sans Amoy ; docs QuickSwap sans Amoy). Le détecteur tourne
donc avec 0 pool — c'est le résultat honnête. Si un DEX apparaît
un jour sur Amoy, on met son adresse en status "present" dans la
config et le détecteur la pollera sans changer le code.

Usage :
  python3 amoy_detector.py --once                 # 1 cycle, puis stop
  python3 amoy_detector.py --loop                 # boucle toutes les 60 s (Ctrl+C pour stop)
  python3 amoy_detector.py --duration-minutes 10  # boucle 10 min puis stop (smoke test)
  python3 amoy_detector.py --discover             # vérifie juste le code des venues, puis stop
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent          # crypto-base-flashloan-bot/
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE.parent))    # polygon/ (polygon_gas : non utilisé ici, RPC Amoy)

from math_engine import Costs, Pool, find_optimal_loan  # noqa: E402

# --- Valeurs par défaut si PyYAML absent (mêmes valeurs que amoy_config.yaml) ---
DEFAULTS = {
    "chain_id": 80002,
    "rpcs": ["https://rpc-amoy.polygon.technology",
             "https://polygon-amoy.drpc.org",
             "https://polygon-amoy-bor-rpc.publicnode.com"],
    "explorer": "https://amoy.polygonscan.com",
    "matic_price_usd_reference": 0.0758,
    "gas_units": 450000,
    "gas_price_max_gwei": 1000.0,
    # RÈGLE DU 2026-11-24 (Ismail) : min profit 3 $ ABANDONNÉ comme seuil
    # de journalisation. On logue tout net > 0 $ après TOUS les coûts
    # (flash 0 %, swap, gas, budget revert = 1 × gas). La RÈGLE D'ARRÊT
    # reste évaluée sur les opps ≥ 3 $ (stop_rule_min_profit_usd).
    "log_threshold_usd": 0.0,
    "revert_budget_gas_multiple": 1.0,
    "stop_rule_min_profit_usd": 3.0,
    "stop_rule_min_opps_per_week": 1,
    "scan_interval_seconds": 60,
    "max_loan_usd": 50000.0,
    "max_pct_liquidity": 0.10,
    "opp_log": "amoy_opportunities.jsonl",
    "summary": "daily_summary.json",
    "detector_log": "amoy_detector.log",
}

# Sélecteurs de fonctions (lecture seule, eth_call) :
SEL_GET_PAIR = "e6a43905"      # getPair(address,address) -> address (V2 factory)
SEL_GET_RESERVES = "0902f1ac"  # getReserves() -> (uint112,uint112,uint32) (V2 pair)
SEL_GET_POOL = "1698ee82"      # getPool(address,address,uint24) -> address (V3 factory)
SEL_SLOT0 = "3850c7bd"         # slot0() -> (sqrtPriceX96,tick,...) (V3 pool)
SEL_LIQUIDITY = "1a686502"     # liquidity() -> uint128 (V3 pool)
SEL_DECIMALS = "313ce567"      # decimals() -> uint8 (ERC20)
SEL_TOKEN0 = "0dfe1681"        # token0() -> address (V2 pair / V3 pool)
SEL_TOKEN1 = "d21220a7"        # token1() -> address


def log_line(msg: str, log_path: Path):
    """Journal texte horodaté (stdout + fichier)."""
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with log_path.open("a") as f:
        f.write(line + "\n")


def load_config() -> dict:
    """Charge amoy_config.yaml (PyYAML si dispo, sinon DEFAULTS)."""
    cfg_path = HERE / "amoy_config.yaml"
    cfg = dict(DEFAULTS)
    venues, watchlist = {}, []
    try:
        import yaml
        raw = yaml.safe_load(cfg_path.read_text())
        ch = raw.get("chain", {})
        cfg["chain_id"] = ch.get("chain_id", 80002)
        cfg["rpcs"] = [ch.get("rpc_url")] + list(ch.get("rpc_fallbacks", []))
        cfg["rpcs"] = [u for u in cfg["rpcs"] if u]
        cfg["explorer"] = ch.get("explorer", cfg["explorer"])
        cfg["matic_price_usd_reference"] = raw.get(
            "matic_price_usd_reference", cfg["matic_price_usd_reference"])
        cfg["gas_units"] = raw.get("gas_units_per_trade", cfg["gas_units"])
        cfg["gas_price_max_gwei"] = raw.get("gas_price_max_gwei",
                                            cfg["gas_price_max_gwei"])
        m = raw.get("math", {})
        cfg["log_threshold_usd"] = m.get("log_threshold_usd",
                                         cfg["log_threshold_usd"])
        cfg["revert_budget_gas_multiple"] = m.get(
            "revert_budget_gas_multiple",
            cfg["revert_budget_gas_multiple"])
        cfg["stop_rule_min_profit_usd"] = m.get(
            "stop_rule_min_profit_usd", cfg["stop_rule_min_profit_usd"])
        cfg["stop_rule_min_opps_per_week"] = m.get(
            "stop_rule_min_opps_per_week",
            cfg["stop_rule_min_opps_per_week"])
        cfg["max_loan_usd"] = m.get("max_loan_usd", cfg["max_loan_usd"])
        cfg["max_pct_liquidity"] = m.get("max_pct_liquidity",
                                         cfg["max_pct_liquidity"])
        cfg["scan_interval_seconds"] = raw.get("scan_interval_seconds",
                                               cfg["scan_interval_seconds"])
        venues = raw.get("venues", {}) or {}
        watchlist = raw.get("watchlist", []) or []
        files = raw.get("files", {}) or {}
        cfg["opp_log"] = files.get("opportunities_log", cfg["opp_log"])
        cfg["summary"] = files.get("daily_summary", cfg["summary"])
        cfg["detector_log"] = files.get("detector_log", cfg["detector_log"])
    except ImportError:
        print("PyYAML absent — utilisation des DEFAULTS (mêmes valeurs).")
    except Exception as e:  # noqa: BLE001
        print(f"Config illisible ({e}) — utilisation des DEFAULTS.")
    cfg["venues"] = venues
    cfg["watchlist"] = watchlist
    return cfg


class AmoyRPC:
    """Client JSON-RPC minimal, lecture seule, avec bascule de RPC."""

    def __init__(self, urls: list[str]):
        self.urls = urls
        self.active: str | None = None
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json",
             "User-Agent": "CODEMA-amoy-detector/4.0"})

    def call(self, method: str, params=None):
        # Ordre d'essai : le dernier RPC qui a répondu en premier
        # (évite de re-frapper le RPC officiel mort à chaque appel :
        # un cycle fait ~14 appels, ça coûtait ~15 s par cycle).
        # 2 tentatives par RPC : drpc/publicnode sont capricieux
        # (réponses chunkées tronquées, 403 Cloudflare intermittents —
        # même flakiness que polygon_gas.py, qui réessaie 3 fois).
        urls = ([self.active] if self.active else []) + \
               [u for u in self.urls if u != self.active]
        last_err = None
        for url in urls:
            for attempt in range(2):
                try:
                    r = self.session.post(
                        url, json={"jsonrpc": "2.0", "id": 1,
                                   "method": method, "params": params or []},
                        timeout=10)
                    r.raise_for_status()
                    data = r.json()
                    if "error" in data:
                        raise RuntimeError(f"RPC error : {data['error']}")
                    self.active = url
                    return data.get("result")
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt == 0:
                        time.sleep(0.5)
        raise RuntimeError(f"aucun RPC Amoy ne répond (dernier : {last_err})")

    def chain_id(self) -> int:
        return int(self.call("eth_chainId"), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber"), 16)

    def gas_price_gwei(self) -> float:
        return int(self.call("eth_gasPrice"), 16) / 1e9

    def get_code(self, address: str) -> str:
        return self.call("eth_getCode", [address, "latest"]) or "0x"

    def eth_call(self, to: str, data: str) -> str:
        return self.call("eth_call", [{"to": to, "data": data}, "latest"]) or "0x"


# ------------------------------------------------------------------ decoding
def _u256(word: str) -> int:
    return int(word, 16)


def _addr(word: str) -> str:
    return "0x" + word[-40:]


def _encode_address(a: str) -> str:
    return a[2:].rjust(64, "0")


def _encode_u24(v: int) -> str:
    return format(v, "064x")


# ------------------------------------------------------------------ venues
def is_valid_address(addr: str) -> bool:
    """0x + 40 caractères hex. Une adresse malformée (ex : 39 car.)
    doit être signalée, jamais envoyée au RPC (elle fait planter
    tout le cycle avec une erreur -32602)."""
    if not isinstance(addr, str) or len(addr) != 42 or not addr.startswith("0x"):
        return False
    try:
        int(addr[2:], 16)
        return True
    except ValueError:
        return False


def discover_venues(rpc: AmoyRPC, venues_cfg: dict,
                    log_path: Path | None = None) -> dict:
    """Vérifie la présence on-chain de chaque venue (eth_getCode).
    Retourne {venue: {status, contracts:{name: bool_present}}}.
    Une adresse invalide est marquée 'invalid' et ignorée (pas de crash)."""
    out = {}
    for name, v in venues_cfg.items():
        contracts = {}
        for key, addr in v.items():
            if key in ("status", "evidence"):
                continue
            if isinstance(addr, str) and addr.startswith("0x"):
                if not is_valid_address(addr):
                    contracts[key] = "invalid"
                    if log_path:
                        log_line(f"venue {name}.{key} : ADRESSE INVALIDE "
                                 f"({addr}, {len(addr)} car.) — ignorée",
                                 log_path)
                    continue
                code = rpc.get_code(addr)
                contracts[key] = len(code) > 4  # "0x" = pas de code
        present = any(c is True for c in contracts.values())
        out[name] = {"declared": v.get("status", "?"),
                     "present_onchain": present,
                     "contracts": contracts,
                     "evidence": v.get("evidence", "")}
    return out


def read_v2_pair(rpc: AmoyRPC, factory: str, token_a: str, token_b: str,
                 fee_bps: int = 30) -> Pool | None:
    """Lit une paire V2 : getPair puis getReserves. None si pas de paire."""
    data = "0x" + SEL_GET_PAIR + _encode_address(token_a) + _encode_address(token_b)
    pair = _addr(rpc.eth_call(factory, data))
    if pair == "0x0000000000000000000000000000000000000000":
        return None
    res = rpc.eth_call(pair, "0x" + SEL_GET_RESERVES)
    if len(res) < 130:
        return None
    r0 = _u256(res[2:66])
    r1 = _u256(res[66:130])
    t0 = _addr(rpc.eth_call(pair, "0x" + SEL_TOKEN0))
    # token0 = le plus petit des deux ; réserve USDC = celle du token stable
    # (on suppose token_b = stablecoin ici, comme sur le mainnet)
    if t0.lower() == token_a.lower():
        reserve_stable, reserve_meme = r0, r1
    else:
        reserve_stable, reserve_meme = r1, r0
    # Échelle : les réserves brutes sont en unités token ; on convertit
    # avec les décimales lues on-chain.
    dec_stable = _u256(rpc.eth_call(token_b, "0x" + SEL_DECIMALS))
    dec_meme = _u256(rpc.eth_call(token_a, "0x" + SEL_DECIMALS))
    reserve_usdc = reserve_stable / (10 ** dec_stable)
    reserve_meme = reserve_meme / (10 ** dec_meme)
    return Pool(name=f"V2 {token_a[:6]}..{token_a[-4:]}/{token_b[:6]}",
                reserve_usdc=reserve_usdc, reserve_meme=reserve_meme,
                fee_bps=fee_bps)


def read_v3_pool(rpc: AmoyRPC, factory: str, token_a: str, token_b: str,
                 fee: int = 3000) -> Pool | None:
    """Lit une pool V3 : getPool puis slot0 + liquidity.
    Approximation DOCUMENTÉE : les réserves "virtuelles" au tick courant
    sont L / sqrtP (token0) et L * sqrtP (token1) — valable pour la
    DÉTECTION de spread ; le sizing exact serait re-vérifié avant toute
    exécution (qui n'a pas lieu ici : détection seulement)."""
    data = ("0x" + SEL_GET_POOL + _encode_address(token_a)
            + _encode_address(token_b) + _encode_u24(fee))
    pool_addr = _addr(rpc.eth_call(factory, data))
    if pool_addr == "0x0000000000000000000000000000000000000000":
        return None
    slot0 = rpc.eth_call(pool_addr, "0x" + SEL_SLOT0)
    if len(slot0) < 66:
        return None
    sqrt_price_x96 = _u256(slot0[2:66])
    liq = _u256(rpc.eth_call(pool_addr, "0x" + SEL_LIQUIDITY))
    if sqrt_price_x96 == 0 or liq == 0:
        return None
    dec_a = _u256(rpc.eth_call(token_a, "0x" + SEL_DECIMALS))
    dec_b = _u256(rpc.eth_call(token_b, "0x" + SEL_DECIMALS))
    sqrt_p = sqrt_price_x96 / (2 ** 96)  # prix token1/token0, brut
    # Ajustement décimales : prix(token1/token0) = sqrtP^2 * 10^(decA-decB)
    price = (sqrt_p ** 2) * (10 ** (dec_a - dec_b))
    # Réserves virtuelles au tick courant (en unités token, puis en $) :
    # token0 = L / sqrtP_adj, token1 = L * sqrtP_adj
    sqrt_p_adj = sqrt_p * (10 ** ((dec_a - dec_b) / 2))
    reserve_a = liq / sqrt_p_adj / (10 ** dec_a)
    reserve_b = liq * sqrt_p_adj / (10 ** dec_b)
    # On suppose token_b = stablecoin (USDC) comme sur le mainnet.
    return Pool(name=f"V3 {token_a[:6]}..{token_a[-4:]}/{token_b[:6]} fee={fee}",
                reserve_usdc=reserve_b, reserve_meme=reserve_a,
                fee_bps=fee // 100)


# ------------------------------------------------------------------ cycle
def load_summary(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_summary(path: Path, summary: dict):
    path.write_text(json.dumps(summary, indent=2))


def run_cycle(rpc: AmoyRPC, cfg: dict, log_path: Path) -> dict:
    """Un cycle de détection. Retourne les compteurs du cycle."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    stats = {"date": now.isoformat(), "cycles": 1, "pairs_checked": 0,
             "spreads_seen": 0, "below_zero_usd": 0, "opps_gt_0_usd": 0,
             "opps_ge_3_usd": 0,
             "max_spread_pct": 0.0, "venues_present": 0, "venues_absent": 0,
             "rpc": rpc.active or "?"}
    try:
        chain = rpc.chain_id()
        block = rpc.block_number()
        gwei = rpc.gas_price_gwei()
    except Exception as e:  # noqa: BLE001
        log_line(f"CYCLE ÉCHEC RPC : {e}", log_path)
        return {**stats, "error": str(e)}
    if chain != cfg["chain_id"]:
        log_line(f"CYCLE ÉCHEC : chainId {chain} != {cfg['chain_id']} attendu",
                 log_path)
        return {**stats, "error": f"mauvaise chaîne {chain}"}
    gas_pol = cfg["gas_units"] * gwei * 1e-9
    gas_usd_ref = gas_pol * cfg["matic_price_usd_reference"]
    log_line(f"cycle bloc={block} gas={gwei:.1f} gwei "
             f"({gas_pol:.5f} POL test / {gas_usd_ref:.5f} $ simulés) "
             f"rpc={rpc.active}", log_path)

    try:
        venues = discover_venues(rpc, cfg["venues"], log_path)
    except Exception as e:  # noqa: BLE001 — un cycle en échec ne tue pas la boucle
        log_line(f"CYCLE ÉCHEC découverte venues : {e}", log_path)
        return {**stats, "error": str(e)}
    for name, v in venues.items():
        if v["present_onchain"]:
            stats["venues_present"] += 1
            log_line(f"venue {name} : PRÉSENTE {v['contracts']}", log_path)
        else:
            stats["venues_absent"] += 1
    log_line(f"venues : {stats['venues_present']} présente(s), "
             f"{stats['venues_absent']} absente(s)", log_path)

    # Paires : seulement si au moins 2 venues présentes ET watchlist non vide.
    watchlist = cfg["watchlist"]
    present = [n for n, v in venues.items() if v["present_onchain"]]
    if len(present) < 2 or not watchlist:
        if not watchlist:
            log_line("watchlist vide (aucun token vérifié) — 0 paire à poller",
                     log_path)
        elif len(present) < 2:
            log_line(f"1 seule venue présente ({present}) — pas d'arbitrage "
                     f"2-DEX possible", log_path)
        return stats

    # RÈGLE DU 2026-11-24 (Ismail) : min profit 3 $ ABANDONNÉ comme seuil
    # de journalisation. On logue toute opp dont le net est > 0 $ APRÈS
    # TOUS LES COÛTS : brut − flash fee (0 %) − frais de swap (déjà dans
    # amm_out) − gas − budget revert (1 × gas, pire cas trade + revert).
    # Le flag gte_3_usd marque les opps ≥ 3 $ (RÈGLE D'ARRÊT).
    # On n'utilise PAS decide() ici : ses seuils (min 3 $ et net > gas×3)
    # sont l'ancienne règle — on calcule le net optimal directement.
    costs = Costs(gas_usd=gas_usd_ref, flash_provider="morpho",
                  min_profit_usd=cfg["log_threshold_usd"],
                  gas_multiple=1.0,
                  gas_price_gwei=gwei,
                  max_gas_price_gwei=cfg["gas_price_max_gwei"])
    revert_budget_usd = gas_usd_ref * cfg["revert_budget_gas_multiple"]
    for item in watchlist:
        token_a, token_b = item["token_a"], item["token_b"]
        pools = []
        for venue_name in present:
            v = cfg["venues"][venue_name]
            try:
                if "v2" in venue_name:
                    p = read_v2_pair(rpc, v["factory"], token_a, token_b)
                else:
                    p = read_v3_pool(rpc, v["factory"], token_a, token_b)
                if p and p.reserve_usdc > 0 and p.reserve_meme > 0:
                    pools.append((venue_name, p))
            except Exception as e:  # noqa: BLE001
                log_line(f"lecture {venue_name} {item.get('label','?')} : {e}",
                         log_path)
        if len(pools) < 2:
            continue
        stats["pairs_checked"] += 1
        for i in range(len(pools)):
            for j in range(len(pools)):
                if i == j:
                    continue
                buy_name, buy = pools[i]
                sell_name, sell = pools[j]
                if not buy.price_usdc_per_meme:
                    continue
                spread = 100.0 * (sell.price_usdc_per_meme
                                  / buy.price_usdc_per_meme - 1)
                opt = find_optimal_loan(buy, sell, costs,
                                        cfg["max_loan_usd"],
                                        cfg["max_pct_liquidity"])
                net_before_revert = opt["net_usd"]
                net_after_all = net_before_revert - revert_budget_usd
                stats["spreads_seen"] += 1
                stats["max_spread_pct"] = max(stats["max_spread_pct"], spread)
                if net_after_all > cfg["log_threshold_usd"]:
                    stats["opps_gt_0_usd"] += 1
                    gte_3 = net_after_all >= cfg["stop_rule_min_profit_usd"]
                    if gte_3:
                        stats["opps_ge_3_usd"] += 1
                    opp = {"timestamp": now.isoformat(), "simulated": True,
                           "chain": "amoy", "chain_id": 80002,
                           "token_a": token_a, "token_b": token_b,
                           "label": item.get("label", ""),
                           "venue_buy": buy_name, "venue_sell": sell_name,
                           "spread_pct": round(spread, 2),
                           "optimal_loan_usd": opt["optimal_loan_usd"],
                           "simulated_net_usd": round(net_after_all, 4),
                           "net_before_revert_budget_usd":
                               round(net_before_revert, 4),
                           "revert_budget_usd": round(revert_budget_usd, 6),
                           "gte_3_usd": gte_3,
                           "simulated_gross_usd": opt["gross_usd"],
                           "gas_pol_test": round(gas_pol, 6),
                           "gas_usd_simulated": round(gas_usd_ref, 6),
                           "gas_price_gwei": round(gwei, 1),
                           "note": "USD simulé : POL test valorisé au prix "
                                   "MATIC mainnet (référence seulement) ; "
                                   "net = brut − flash 0 % − swap − gas − "
                                   "budget revert (1 × gas)"}
                    with (HERE / cfg["opp_log"]).open("a") as f:
                        f.write(json.dumps(opp) + "\n")
                    log_line(f"OPP SIMULÉE net > 0 $ : {opp}", log_path)
                else:
                    stats["below_zero_usd"] += 1
    log_line(f"cycle terminé : {stats['pairs_checked']} paire(s), "
             f"{stats['spreads_seen']} spread(s), "
             f"{stats['opps_gt_0_usd']} opp(s) net > 0 $ "
             f"(dont {stats['opps_ge_3_usd']} ≥ 3 $), "
             f"{stats['below_zero_usd']} net ≤ 0 $ (compteur seulement)",
             log_path)
    return stats


def merge_summary(summary_path: Path, stats: dict):
    """Fusionne les compteurs du cycle dans le résumé journalier."""
    summary = load_summary(summary_path)
    day = stats["date"][:10]
    d = summary.setdefault(day, {"cycles": 0, "pairs_checked": 0,
                                 "spreads_seen": 0, "below_zero_usd": 0,
                                 "opps_gt_0_usd": 0, "opps_ge_3_usd": 0,
                                 "max_spread_pct": 0.0,
                                 "venues_present": 0, "venues_absent": 0,
                                 "errors": 0})
    d["cycles"] += stats.get("cycles", 0)
    d["pairs_checked"] += stats.get("pairs_checked", 0)
    d["spreads_seen"] += stats.get("spreads_seen", 0)
    d["below_zero_usd"] += stats.get("below_zero_usd", 0)
    d["opps_gt_0_usd"] += stats.get("opps_gt_0_usd", 0)
    d["opps_ge_3_usd"] += stats.get("opps_ge_3_usd", 0)
    d["max_spread_pct"] = max(d["max_spread_pct"],
                              stats.get("max_spread_pct", 0.0))
    # Venues : on n'écrase les compteurs QUE si le cycle a vraiment
    # fait la découverte (sinon un cycle en échec RPC les remettrait à 0).
    if "error" not in stats:
        d["venues_present"] = stats.get("venues_present", 0)
        d["venues_absent"] = stats.get("venues_absent", 0)
    if "error" in stats:
        d["errors"] += 1
    summary[day] = d
    save_summary(summary_path, summary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="1 cycle puis stop")
    ap.add_argument("--loop", action="store_true",
                    help="boucle jusqu'à Ctrl+C")
    ap.add_argument("--duration-minutes", type=float, default=0,
                    help="boucle N minutes puis stop (smoke test)")
    ap.add_argument("--discover", action="store_true",
                    help="vérifie juste le code des venues, puis stop")
    args = ap.parse_args()

    cfg = load_config()
    log_path = HERE / cfg["detector_log"]
    rpc = AmoyRPC(cfg["rpcs"])
    log_line("=== AMOY DETECTOR v4.0 — LECTURE SEULE, aucun broadcast ===",
             log_path)
    log_line(f"RPCs : {cfg['rpcs']}", log_path)

    if args.discover:
        try:
            venues = discover_venues(rpc, cfg["venues"], log_path)
            for name, v in venues.items():
                print(f"{name}: déclaré={v['declared']} "
                      f"présent={v['present_onchain']} {v['contracts']}")
        except Exception as e:  # noqa: BLE001
            print(f"DISCOVER ÉCHEC : {e}")
        return

    if args.once:
        try:
            stats = run_cycle(rpc, cfg, log_path)
        except Exception as e:  # noqa: BLE001
            log_line(f"CYCLE ÉCHEC inattendu : {e}", log_path)
            stats = {"date": datetime.now(timezone.utc).isoformat(),
                     "cycles": 1, "error": str(e)}
        merge_summary(HERE / cfg["summary"], stats)
        return

    interval = cfg["scan_interval_seconds"]
    end = None
    if args.duration_minutes > 0:
        end = time.time() + args.duration_minutes * 60
        log_line(f"mode durée : {args.duration_minutes} min "
                 f"(intervalle {interval} s)", log_path)
    elif args.loop:
        log_line(f"mode boucle continue (intervalle {interval} s) — "
                 f"Ctrl+C pour stopper", log_path)
    else:
        print("Préciser --once, --loop ou --duration-minutes N.")
        return
    try:
        while True:
            try:
                stats = run_cycle(rpc, cfg, log_path)
            except Exception as e:  # noqa: BLE001 — un cycle en échec ne tue pas la boucle
                log_line(f"CYCLE ÉCHEC inattendu : {e}", log_path)
                stats = {"date": datetime.now(timezone.utc).isoformat(),
                         "cycles": 1, "error": str(e)}
            merge_summary(HERE / cfg["summary"], stats)
            if end is not None and time.time() >= end:
                log_line("durée écoulée — arrêt propre", log_path)
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        log_line("arrêt par Ctrl+C", log_path)


if __name__ == "__main__":
    main()
