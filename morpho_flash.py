"""
morpho_flash.py — Flash loan à 0 frais via Morpho Blue (Base, v3.3).

POURQUOI MORPHO (vérifié 2026-11-24, voir RESEARCH.md § Morpho Blue) :
  - Morpho Blue est déployé sur Base à l'adresse canonique (même
    singleton que sur toutes les chaînes) :
    0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
    (code présent, 15 623 octets, bloc 61 806 974).
  - La prime de flash loan est ZÉRO PAR CONCEPTION (pas un paramètre
    de gouvernance) : docs Morpho officielles —
    "flashFee is zero", "maxFlashLoan is the token's balance of this
    contract", "receiver of assets is the caller". Il n'existe AUCUNE
    fonction flashFee sur le contrat : un eth_call du sélecteur
    ERC-3156 flashFee(address,uint256) = 0xd9d98ce4 REVERT
    (execution reverted, vérifié bloc 61 806 974). Le fee 0 ne peut
    donc pas être "monté" un jour — contrairement à Balancer, où
    c'était un paramètre de gouvernance.
  - Aave V3, lui, facture 0,05 % (vérifié on-chain, FORK_TEST_RESULTS.md).
    Sur un loan de 8 847,98 $ : Aave = 4,42 $, Morpho = 0 $.

POURQUOI PLUS BALANCER (BIP-928, 30 oct 2026 — voir BALANCER_RESEARCH.md) :
  Balancer a été liquidé (wind-down) : pools en retraits seuls, bug
  bounty terminé, Balancer Labs dissoute. Le Vault 0xBA12...F2C8 ne
  doit PLUS être utilisé comme provider de flash loan. balancer_flash.py
  est conservé pour référence, marqué DÉPRÉCIÉ. Morpho le remplace :
  même fee 0 %, mais liquidité ~3 500× plus grande.

CONTRAINTE N°1 — LIQUIDITÉ MORPHO SUR BASE (énorme) :
  Soldes de Morpho mesurés bloc 61 806 974 (2026-11-24) :
    USDC : 328 711 525,75 $  |  WETH : 88 713,53 (~148,9 M$ au prix pool)
  maxFlashLoan = le solde ENTIER du contrat (tous marchés confondus +
  collatéral déposé + dons). Le plafond 50 % (MAX_PCT_MORPHO_BALANCE)
  donne ~164 M$ USDC utilisables : en pratique, ce n'est plus le
  provider qui limite le loan, mais le moteur (max 10 % de la plus
  petite réserve, max 50 000 $ — voir math_engine.py). La règle 50 %
  est conservée par prudence : le solde est partagé avec tous les
  marchés Morpho, il peut baisser entre la lecture et le bloc.

CONTRAINTE N°2 — LES MEME COINS NE SONT PAS CHEZ MORPHO :
  Morpho détient les tokens des marchés de prêt (majors : WETH, USDC,
  DAI, cbETH...). Un meme coin n'y est (presque) jamais.
  Le design est donc : on emprunte WETH ou USDC (0 frais), on swap
  sur Uniswap / BaseSwap contre le MEME, on revend, on rembourse.
  Le flash loan ne sert qu'à financer l'arbitrage, pas à emprunter
  le meme coin lui-même.

FONCTIONNEMENT (Morpho Blue, différent d'Aave et de Balancer) :
  1. Le bot appelle morpho.flashLoan(token, assets, data).
     Le RECEIVER est l'appelant lui-même (msg.sender) — pas de
     paramètre recipient. Un seul token par appel.
  2. Morpho transfère les tokens à l'appelant, puis appelle
     onMorphoFlashLoan(assets, data) sur l'appelant. Signature
     VÉRIFIÉE contre le repo officiel morpho-org/morpho-blue
     (src/Morpho.sol + src/interfaces/IMorphoCallbacks.sol) et la
     doc officielle : `onMorphoFlashLoan(uint256 assets, bytes
     calldata data)` — sélecteur 0x31f57072 (vérifié par keccak).
  3. Dans le callback : swaps, vérification profit >= minProfit,
     approve(Morpho, assets) — Morpho tire ensuite le remboursement
     via transferFrom(msg.sender, address(this), assets). Fee = 0,
     donc on rembourse EXACTEMENT `assets`.
  4. Le callback DOIT vérifier msg.sender == morpho (sinon n'importe
     qui peut appeler onMorphoFlashLoan et vider le contrat).
  5. `data` doit être NON VIDE : on y encode le montant attendu
     (abi.encode(amount)) pour que le callback vérifie assets, et
     pour garantir le déclenchement du callback.

SÉCURITÉ :
  - Aucune clé privée ici, aucune transaction envoyée par ce module :
    il ENCODE l'appel et SÉLECTIONNE le provider. L'envoi reste
    interdit en dry_run (voir executor.py).
  - Le fee 0 % est structurel (pas de getter, pas de gouvernance
    qui puisse le monter) — mais le bot vérifie quand même que le
    contrat n'a pas de flashFee (verify_no_flash_fee_getter) et que
    le solde couvre le loan avant de compter sur 0 %.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- constantes
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
# Adresse canonique Morpho Blue, identique sur toutes les chaînes.
# Vérifiée 2026-11-24 : code présent (15 623 octets, bloc 61 806 974),
# docs Morpho officielles, docs.eco.com, agent.zbang.net, darknavy.org
# (rapport d'exploit Base : Morpho.flashLoan(USDC, 97_000e6, data)).
MORPHO_FLASH_FEE = 0.0              # 0 % — par conception, pas de getter
AAVE_FLASH_FEE = 0.0005             # 0,05 % — pour comparaison (voir math_engine)
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Soldes de Morpho sur Base, mesurés on-chain bloc 61 806 974 (2026-11-24).
# Ce sont des données DATÉES : elles servent de repli quand le RPC n'est
# pas disponible. Avec un RPC, fetch_morpho_balances() les remplace par
# les soldes live. Ne jamais trader sur ces chiffres sans les re-vérifier.
MEASURED_BLOCK = 61_806_974
MEASURED_MORPHO_BALANCES_USD: Dict[str, float] = {
    "USDC": 328_711_525.75,
    "WETH": 148_900_000.0,   # 88 713,53 WETH × ~1 678 $ (prix pool Uni V2)
}
MEASURED_MORPHO_WETH = 88_713.53

MAX_PCT_MORPHO_BALANCE = 0.50      # jamais plus de 50 % du solde Morpho
# Alias (même règle que chez Balancer) pour le code qui parle de "vault".
MAX_PCT_VAULT_BALANCE = MAX_PCT_MORPHO_BALANCE
PUBLIC_BASE_RPC = "https://mainnet.base.org"

# Sélecteurs vérifiés par keccak le 2026-11-24 (ne pas deviner) :
# flashLoan(address,uint256,bytes) = 0xe0232b42
# onMorphoFlashLoan(uint256,bytes) = 0x31f57072
# flashFee(address,uint256) [ERC-3156] = 0xd9d98ce4 — ABSENT de Morpho
#   (l'eth_call revert : "execution reverted", bloc 61 806 974).
FLASH_LOAN_SELECTOR = "0xe0232b42"
ON_MORPHO_FLASH_LOAN_SELECTOR = "0x31f57072"
FLASH_FEE_SELECTOR = "0xd9d98ce4"


# ------------------------------------------------------------------- helpers
def is_valid_address(addr: str) -> bool:
    """0x + 40 caractères hexadécimaux (checksum non exigé ici)."""
    if not isinstance(addr, str) or not addr.startswith("0x"):
        return False
    h = addr[2:]
    return len(h) == 40 and all(c in "0123456789abcdefABCDEF" for c in h)


def provider_fee_rate(provider: str) -> float:
    """Taux de flash loan par provider. 'morpho' = 0, 'aave' = 0,05 %."""
    if provider == "morpho":
        return MORPHO_FLASH_FEE
    if provider == "aave":
        return AAVE_FLASH_FEE
    raise ValueError(f"provider inconnu : {provider!r} (morpho | aave)")


def costs_for_provider(provider: str, base_costs=None):
    """Copie un Costs (math_engine) avec le taux du provider choisi.
    Le défaut reste Aave (0,05 %) : on ne change le taux que quand on
    choisit explicitement Morpho — les tests v1/v2 ne bougent pas."""
    from math_engine import Costs
    c = base_costs or Costs()
    return Costs(gas_usd=c.gas_usd, flash_fee_rate=provider_fee_rate(provider),
                 flash_provider=provider, min_profit_usd=c.min_profit_usd,
                 gas_multiple=c.gas_multiple, gas_price_gwei=c.gas_price_gwei,
                 max_gas_price_gwei=c.max_gas_price_gwei)


@dataclass
class ProviderChoice:
    provider: str                  # "morpho" | "aave"
    reason: str
    usable_usd: float              # plafond utilisable chez ce provider ($)
    fee_rate: float
    balances_source: str           # "rpc_live" | "measured_block_61806974" | "n/a"


def select_provider(loan_usd: float, token_symbol: str = "USDC",
                    morpho_balances_usd: Optional[Dict[str, float]] = None,
                    max_pct_morpho: float = MAX_PCT_MORPHO_BALANCE) -> ProviderChoice:
    """Choisit le provider de flash loan pour un loan donné.
    Morpho (0 %) est préféré QUAND :
      - le token emprunté est WETH ou USDC (ce que Morpho détient),
      - le loan <= max_pct_morpho × solde Morpho pour ce token.
    Sinon Aave (0,05 %, liquidité 13,6 M$ USDC) en repli.
    morpho_balances_usd = None -> on utilise les soldes MESURÉS bloc
    61 806 974, en le disant clairement (source = measured, pas live)."""
    token = (token_symbol or "USDC").upper()
    if token not in ("USDC", "WETH"):
        return ProviderChoice(
            provider="aave", fee_rate=AAVE_FLASH_FEE,
            reason=f"token {token} absent de Morpho "
                   f"(que des majors) — repli Aave",
            usable_usd=float("inf"), balances_source="n/a")
    if morpho_balances_usd is None:
        balances = MEASURED_MORPHO_BALANCES_USD
        source = f"measured_block_{MEASURED_BLOCK} (stale — re-vérifier avec RPC)"
    else:
        balances = morpho_balances_usd
        source = "rpc_live"
    held = balances.get(token, 0.0)
    usable = held * max_pct_morpho
    if loan_usd <= usable:
        return ProviderChoice(
            provider="morpho", fee_rate=MORPHO_FLASH_FEE,
            reason=f"Morpho 0 % : loan {loan_usd:.2f} $ <= "
                   f"{max_pct_morpho:.0%} du solde Morpho {token} "
                   f"({held:,.2f} $ -> utilisable {usable:,.2f} $)",
            usable_usd=usable, balances_source=source)
    return ProviderChoice(
        provider="aave", fee_rate=AAVE_FLASH_FEE,
        reason=f"loan {loan_usd:.2f} $ > {max_pct_morpho:.0%} du solde "
               f"Morpho {token} ({held:,.2f} $ -> utilisable {usable:,.2f} $) "
               f"— repli Aave (0,05 %, liquidité 13,6 M$)",
        usable_usd=float("inf"), balances_source=source)


# ------------------------------------------------------- lectures on-chain
def _eth_call(rpc_url: str, to: str, data: str, timeout: int = 10):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "codema-flashloan-bot-v3.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"eth_call erreur : {out['error']}")
    return out["result"]


def verify_no_flash_fee_getter(rpc_url: str = PUBLIC_BASE_RPC,
                               timeout: int = 10) -> Tuple[bool, str]:
    """Vérifie que Morpho n'a PAS de fonction flashFee (ERC-3156).
    Morpho Blue n'implémente pas flashFee : l'appel doit REVERT
    ("execution reverted"). Retourne (True, source) si le revert est
    confirmé (= fee 0 par conception), (False, détail) sinon.
    En cas d'échec réseau : (False, raison) — on ne suppose rien."""
    # flashFee(address,uint256) = 0xd9d98ce4, token = USDC, amount = 0.
    data = FLASH_FEE_SELECTOR + USDC[2:].lower().rjust(64, "0") + "00" * 32
    try:
        _eth_call(rpc_url, MORPHO, data, timeout)
        return False, ("rpc_live : flashFee a répondu sans revert — "
                       "Morpho aurait un fee ?! Vérifier avant tout live")
    except RuntimeError as e:
        if "execution reverted" in str(e) or "revert" in str(e).lower():
            return True, "rpc_live : flashFee revert confirmé (pas de getter)"
        return False, f"rpc_live : eth_call inattendue : {e}"
    except Exception as e:
        return False, f"réseau indisponible : {type(e).__name__} — non vérifié"


def fetch_flash_loan_fee_pct(rpc_url: str = PUBLIC_BASE_RPC,
                             timeout: int = 10) -> Tuple[float, str]:
    """Le fee Morpho est 0 par conception (docs officielles + absence
    de getter flashFee, vérifiée par verify_no_flash_fee_getter).
    Retourne (0.0, source) — jamais un 0 % inventé silencieusement :
    la source dit si l'absence de getter a été confirmée live."""
    ok, src = verify_no_flash_fee_getter(rpc_url, timeout)
    if ok:
        return 0.0, src
    return MORPHO_FLASH_FEE, f"non confirmé live ({src}) — fee 0 par doc, à re-vérifier"


def fetch_morpho_balances(rpc_url: str = PUBLIC_BASE_RPC,
                          eth_price_usd: float = 1678.0,
                          timeout: int = 10) -> Optional[Dict[str, float]]:
    """Soldes live de Morpho (balanceOf) pour WETH et USDC, en $.
    maxFlashLoan = le solde entier du contrat (docs Morpho).
    Retourne None si le RPC est indisponible (l'appelant utilise alors
    les soldes mesurés — en le disant)."""
    try:
        morpho_pad = MORPHO[2:].lower().rjust(64, "0")
        data = "0x70a08231" + morpho_pad  # balanceOf(address)
        out = {}
        for symbol, token, dec in (("WETH", WETH, 18), ("USDC", USDC, 6)):
            raw = _eth_call(rpc_url, token, data, timeout)
            val = int(raw, 16) / 10 ** dec
            out[symbol] = val * eth_price_usd if symbol == "WETH" else val
        return out
    except Exception:
        return None


# Alias (même lecture, nom historique côté executor).
fetch_vault_balances = fetch_morpho_balances


# ------------------------------------------------- encodage de l'appel flash
def _abi_encode_address(addr: str) -> bytes:
    return bytes.fromhex(addr[2:].lower().rjust(64, "0"))


def _abi_encode_uint(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def encode_flash_loan_call(token: str, amount: int,
                           user_data: bytes = b"") -> str:
    """Encode morpho.flashLoan(token, assets, data) en calldata hex
    (stdlib only, pas d'eth_abi). Testé par round-trip dans
    test_morpho.py. NE BROADCAST RIEN : c'est de l'encodage pur.
    Note : le receiver est l'appelant (msg.sender) — pas de paramètre
    recipient, contrairement à Balancer/Aave. `user_data` doit être
    NON VIDE en pratique : le contrat y encode le montant attendu
    pour que le callback le vérifie."""
    if not is_valid_address(token):
        raise ValueError(f"token invalide : {token}")
    if amount <= 0:
        raise ValueError(f"amount invalide : {amount} (doit être > 0)")
    ud = bytes(user_data)
    head = b"".join([_abi_encode_address(token),
                     _abi_encode_uint(amount),
                     _abi_encode_uint(96)])  # offset data
    tail_data = _abi_encode_uint(len(ud)) + ud + b"\x00" * ((32 - len(ud) % 32) % 32)
    return FLASH_LOAN_SELECTOR + (head + tail_data).hex()


def encode_flash_loan_data(amount: int) -> bytes:
    """Données du callback : le montant attendu, encodé ABI (uint256).
    Le contrat le décode dans onMorphoFlashLoan et exige decoded == assets."""
    return _abi_encode_uint(amount)


def decode_flash_loan_call(calldata: str) -> Dict:
    """Décode un calldata flashLoan (pour les tests / l'audit de l'encodage)."""
    raw = bytes.fromhex(calldata[2:] if calldata.startswith("0x") else calldata)
    assert raw[:4].hex() == FLASH_LOAN_SELECTOR[2:], "sélecteur != flashLoan"
    body = raw[4:]
    token = "0x" + body[12:32].hex()
    amount = int.from_bytes(body[32:64], "big")
    off_d = int.from_bytes(body[64:96], "big")
    n_d = int.from_bytes(body[off_d:off_d + 32], "big")
    user_data = body[off_d + 32:off_d + 32 + n_d]
    return {"token": token, "amount": amount, "user_data": user_data}


def on_morpho_flash_loan_check(sender: str, assets: int,
                               expected_assets: Optional[int] = None,
                               user_data: bytes = b"") -> Tuple[bool, List[str]]:
    """Vérifications que le callback Solidity DOIT faire (logique pure,
    testable ici sans déployer) :
      1. msg.sender == Morpho (sinon n'importe qui peut appeler le callback).
      2. assets > 0 (Morpho revert elle-même si assets == 0).
      3. Si data non vide : le montant décodé == assets (sinon le
         callback a été appelé avec d'autres paramètres que l'emprunt).
      4. À rembourser = assets exactement (fee = 0 par conception).
    Retourne (ok, raisons)."""
    reasons: List[str] = []
    if sender.lower() != MORPHO.lower():
        reasons.append(f"appelant {sender} != Morpho {MORPHO} — REJETER")
    if assets <= 0:
        reasons.append(f"assets = {assets} (attendu > 0)")
    if expected_assets is not None and assets != expected_assets:
        reasons.append(f"assets {assets} != montant attendu {expected_assets}")
    if user_data:
        try:
            decoded = int.from_bytes(user_data[:32], "big")
            if decoded != assets:
                reasons.append(f"data décodée {decoded} != assets {assets}")
        except Exception as e:
            reasons.append(f"data illisible : {e}")
    return (not reasons), reasons


def repayment_amount(assets: int) -> int:
    """Ce qu'il faut rembourser à Morpho : exactement `assets` (fee 0)."""
    return assets


if __name__ == "__main__":
    print("Morpho Blue Base :", MORPHO)
    fee, src = fetch_flash_loan_fee_pct()
    print(f"Flash fee : {fee*100:.2f} % (source {src})")
    ok, src2 = verify_no_flash_fee_getter()
    print(f"Pas de getter flashFee : {ok} ({src2})")
    bal = fetch_morpho_balances()
    print("Soldes Morpho live :", bal)
    for loan in (790.16, 8_847.98, 30_000.0, 60_000.0, 1_000_000.0):
        sel = select_provider(loan, "USDC")
        print(f"  loan {loan:>12,.2f} $ -> {sel.provider} ({sel.reason})")
    sel = select_provider(790.16, "MEMECOIN")
    print(f"  loan MEME -> {sel.provider} ({sel.reason})")
    cd = encode_flash_loan_call(USDC, 790_160_000, encode_flash_loan_data(790_160_000))
    print("Calldata flashLoan (USDC 790.16) :", cd[:80] + "...")
    print("Round-trip :", decode_flash_loan_call(cd))
    print("Callback check :",
          on_morpho_flash_loan_check(MORPHO, 790_160_000, 790_160_000,
                                     encode_flash_loan_data(790_160_000)))
