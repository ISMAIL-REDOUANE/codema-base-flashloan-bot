"""
⛔⛔⛔ DÉPRÉCIÉ — v3.3 (2026-11-24) : BALANCER EST MORT ⛔⛔⛔
Balancer a été liquidé (wind-down BIP-928, 30 oct 2026) : pools en
retraits seuls, bug bounty terminé, Balancer Labs dissoute. Le Vault
0xBA12...F2C8 ne doit PLUS être utilisé comme provider de flash loan.
Ce fichier est CONSERVÉ POUR RÉFÉRENCE (historique + tests) — ne pas
l'utiliser pour de nouveaux trades. Le remplaçant est morpho_flash.py
(Morpho Blue, même fee 0 % mais par conception, liquidité ~3 500×
plus grande). L'executor ne sélectionne plus Balancer.

balancer_flash.py — Flash loan à 0 frais via Balancer V2 Vault (Base, v3).

POURQUOI BALANCER (vérifié 2026-11-24, voir BALANCER_RESEARCH.md) :
  - Le Vault Balancer V2 est déployé sur Base à la MÊME adresse que sur
    toutes les chaînes : 0xBA12222222228d8Ba445958a75a0704d566BF2C8
    (code présent, 24 512 octets, bloc 61 794 215).
  - La prime de flash loan est lue on-chain :
    Vault.getProtocolFeesCollector() = 0xce88686553686DA562CE7Cea497CE749DA109f9F
    ProtocolFeesCollector.getFlashLoanFeePercentage() = 0  =>  0,00 %.
    La doc Balancer dit la même chose : "Currently there are 0 fees for
    flash loans" — mais c'est un paramètre de gouvernance, il PEUT changer.
    Le bot doit donc le RELIRE on-chain avant de compter sur 0 %.
  - Aave V3, lui, facture 0,05 % (vérifié on-chain, FORK_TEST_RESULTS.md).
    Sur un loan de 8 847,98 $ : Aave = 4,42 $, Balancer = 0 $.

CONTRAINTE N°1 — LIQUIDITÉ DU VAULT SUR BASE (petite !) :
  Soldes du Vault mesurés bloc 61 794 215 (2026-11-24) :
    WETH : 23,27  (~39 047 $)  |  USDC : 53 208,01 $
  Total ~92 255 $. Le flash loan ne peut pas dépasser ce que le Vault
  détient. Nos loans (optimal ~790 $, fork 8 848 $) passent largement,
  mais un loan > ~26 600 $ USDC (50 % du solde, marge de sécurité)
  bascule sur Aave, qui détient 13,6 M$ USDC (aToken).
  Règle : on n'emprunte jamais plus de 50 % du solde du Vault
  (MAX_PCT_VAULT_BALANCE) — le solde est partagé avec tous les autres
  utilisateurs du Vault, il peut baisser entre la lecture et le bloc.

CONTRAINTE N°2 — LES MEME COINS NE SONT PAS DANS LE VAULT :
  Le Vault ne détient que les tokens des pools Balancer (majors :
  WETH, USDC, DAI, BAL...). Un meme coin n'y est (presque) jamais.
  Le design est donc : on emprunte WETH ou USDC (0 frais), on swap
  sur Uniswap / Aerodrome contre le MEME, on revend, on rembourse.
  Le flash loan ne sert qu'à financer l'arbitrage, pas à emprunter
  le meme coin lui-même.

FONCTIONNEMENT (Balancer V2, différent d'Aave) :
  1. Le bot appelle vault.flashLoan(recipient, tokens[], amounts[], userData).
  2. Le Vault transfère les tokens, puis appelle
     receiveFlashLoan(tokens[], amounts[], feeAmounts[], userData)
     sur le contrat destinataire. feeAmounts = 0 aujourd'hui.
  3. Dans le callback : swaps, vérification profit >= minProfit,
     remboursement (le Vault vérifie que son solde a augmenté d'au
     moins feeAmount — 0 aujourd'hui).
  4. Le callback DOIT vérifier msg.sender == vault (sinon n'importe
     qui peut appeler receiveFlashLoan et vider le contrat).
  5. Pas de mode "simple" à 1 token comme Aave flashLoanSimple :
     Balancer prend toujours des tableaux (même pour 1 seul token).

SÉCURITÉ :
  - Aucune clé privée ici, aucune transaction envoyée par ce module :
    il ENCODE l'appel et SÉLECTIONNE le provider. L'envoi reste
    interdit en dry_run (voir executor.py).
  - Le fee 0 % est relu on-chain (fetch_flash_loan_fee_pct) : si
    la gouvernance le monte un jour, le bot retombe sur le calcul
    avec le vrai taux au lieu de supposer 0 %.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- constantes
BALANCER_VAULT = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
# Adresse vérifiée on-chain : Vault.getProtocolFeesCollector() (bloc 61 794 215).
# ATTENTION : Basescan étiquette un AUTRE contrat "ProtocolFeesCollector"
# (0xCcb400111263f59Da19d9DD3977BC07e548431Af, fee 1 %) — ce N'EST PAS
# celui du Vault. Ne jamais utiliser l'adresse 0xCcb4... : le Vault pointe
# vers 0xce88..., dont getFlashLoanFeePercentage() = 0.
BALANCER_FEES_COLLECTOR = "0xce88686553686DA562CE7Cea497CE749DA109f9F"
BALANCER_FLASH_FEE = 0.0            # 0 % — lu on-chain 2026-11-24, à relire en prod
AAVE_FLASH_FEE = 0.0005             # 0,05 % — pour comparaison (voir math_engine)
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Soldes du Vault sur Base, mesurés on-chain bloc 61 794 215 (2026-11-24).
# Ce sont des données DATÉES : elles servent de repli quand le RPC n'est
# pas disponible. Avec un RPC, fetch_vault_balances() les remplace par
# les soldes live. Ne jamais trader sur ces chiffres sans les re-vérifier.
MEASURED_BLOCK = 61_794_215
MEASURED_VAULT_BALANCES_USD: Dict[str, float] = {
    "USDC": 53_208.01,
    "WETH": 39_047.06,   # 23,27 WETH × 1 678 $ (prix Uni V2, bloc 61 791 654)
}
MEASURED_VAULT_WETH = 23.27

MAX_PCT_VAULT_BALANCE = 0.50       # jamais plus de 50 % du solde du Vault
PUBLIC_BASE_RPC = "https://mainnet.base.org"

# Sélecteurs vérifiés (keccak des signatures canoniques) :
# flashLoan(address,address[],uint256[],bytes) = 0x5c38449e
# receiveFlashLoan(address[],uint256[],uint256[],bytes) = 0xf04f2707
FLASH_LOAN_SELECTOR = "0x5c38449e"
RECEIVE_FLASH_LOAN_SELECTOR = "0xf04f2707"

# Balancer V3 : NON déployé sur Base (vérifié 2026-11-24 : aucun code à
# l'adresse vanity 0xbA13333333333333333333333333333333333333, bloc 61 794 292).
# V3 est fee-free by design, mais sans Vault V3 sur Base, c'est hors sujet.
BALANCER_V3_VAULT = ""


# ------------------------------------------------------------------- helpers
def is_valid_address(addr: str) -> bool:
    """0x + 40 caractères hexadécimaux (checksum non exigé ici)."""
    if not isinstance(addr, str) or not addr.startswith("0x"):
        return False
    h = addr[2:]
    return len(h) == 40 and all(c in "0123456789abcdefABCDEF" for c in h)


def provider_fee_rate(provider: str) -> float:
    """Taux de flash loan par provider. 'balancer' = 0, 'aave' = 0,05 %."""
    if provider == "balancer":
        return BALANCER_FLASH_FEE
    if provider == "aave":
        return AAVE_FLASH_FEE
    raise ValueError(f"provider inconnu : {provider!r} (balancer | aave)")


def costs_for_provider(provider: str, base_costs=None):
    """Copie un Costs (math_engine) avec le taux du provider choisi.
    Le défaut reste Aave (0,05 %) : on ne change le taux que quand on
    choisit explicitement Balancer — les tests v1/v2 ne bougent pas."""
    from math_engine import Costs
    c = base_costs or Costs()
    return Costs(gas_usd=c.gas_usd, flash_fee_rate=provider_fee_rate(provider),
                 flash_provider=provider, min_profit_usd=c.min_profit_usd,
                 gas_multiple=c.gas_multiple, gas_price_gwei=c.gas_price_gwei,
                 max_gas_price_gwei=c.max_gas_price_gwei)


@dataclass
class ProviderChoice:
    provider: str                  # "balancer" | "aave"
    reason: str
    usable_usd: float              # plafond utilisable chez ce provider ($)
    fee_rate: float
    balances_source: str           # "rpc_live" | "measured_block_61794215" | "n/a"


def select_provider(loan_usd: float, token_symbol: str = "USDC",
                    vault_balances_usd: Optional[Dict[str, float]] = None,
                    max_pct_vault: float = MAX_PCT_VAULT_BALANCE) -> ProviderChoice:
    """Choisit le provider de flash loan pour un loan donné.
    Balancer (0 %) est préféré QUAND :
      - le token emprunté est WETH ou USDC (ce que le Vault détient),
      - le loan <= max_pct_vault × solde du Vault pour ce token.
    Sinon Aave (0,05 %, liquidité 13,6 M$ USDC) en repli.
    vault_balances_usd = None -> on utilise les soldes MESURÉS bloc
    61 794 215, en le disant clairement (source = measured, pas live)."""
    token = (token_symbol or "USDC").upper()
    if token not in ("USDC", "WETH"):
        return ProviderChoice(
            provider="aave", fee_rate=AAVE_FLASH_FEE,
            reason=f"token {token} absent du Vault Balancer "
                   f"(que des majors) — repli Aave",
            usable_usd=float("inf"), balances_source="n/a")
    if vault_balances_usd is None:
        balances = MEASURED_VAULT_BALANCES_USD
        source = f"measured_block_{MEASURED_BLOCK} (stale — re-vérifier avec RPC)"
    else:
        balances = vault_balances_usd
        source = "rpc_live"
    held = balances.get(token, 0.0)
    usable = held * max_pct_vault
    if loan_usd <= usable:
        return ProviderChoice(
            provider="balancer", fee_rate=BALANCER_FLASH_FEE,
            reason=f"Balancer 0 % : loan {loan_usd:.2f} $ <= "
                   f"{max_pct_vault:.0%} du solde Vault {token} "
                   f"({held:,.2f} $ -> utilisable {usable:,.2f} $)",
            usable_usd=usable, balances_source=source)
    return ProviderChoice(
        provider="aave", fee_rate=AAVE_FLASH_FEE,
        reason=f"loan {loan_usd:.2f} $ > {max_pct_vault:.0%} du solde "
               f"Vault {token} ({held:,.2f} $ -> utilisable {usable:,.2f} $) "
               f"— repli Aave (0,05 %, liquidité 13,6 M$)",
        usable_usd=float("inf"), balances_source=source)


# ------------------------------------------------------- lectures on-chain
def _eth_call(rpc_url: str, to: str, data: str, timeout: int = 10):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "codema-flashloan-bot-v3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode())
    if "error" in out:
        raise RuntimeError(f"eth_call erreur : {out['error']}")
    return out["result"]


def fetch_flash_loan_fee_pct(rpc_url: str = PUBLIC_BASE_RPC,
                             timeout: int = 10) -> Tuple[float, str]:
    """Relit on-chain getFlashLoanFeePercentage() (1e18 = 100 %).
    Retourne (taux, source). En cas d'échec réseau : on retourne le taux
    MESURÉ (0 %) en le disant — jamais un 0 % inventé silencieusement."""
    # getFlashLoanFeePercentage() = keccak("getFlashLoanFeePercentage()")[:4]
    # = 0xd877845c — VÉRIFIÉ par keccak le 2026-11-24 (ne pas deviner).
    data = "0xd877845c"
    try:
        raw = _eth_call(rpc_url, BALANCER_FEES_COLLECTOR, data, timeout)
        val = int(raw, 16) / 1e18
        return val, "rpc_live"
    except Exception as e:
        return BALANCER_FLASH_FEE, f"fallback_measured_0%: {type(e).__name__}"


def fetch_vault_balances(rpc_url: str = PUBLIC_BASE_RPC,
                         eth_price_usd: float = 1678.0,
                         timeout: int = 10) -> Optional[Dict[str, float]]:
    """Soldes live du Vault (balanceOf) pour WETH et USDC, en $.
    Retourne None si le RPC est indisponible (l'appelant utilise alors
    les soldes mesurés — en le disant)."""
    try:
        vault_pad = BALANCER_VAULT[2:].lower().rjust(64, "0")
        data = "0x70a08231" + vault_pad  # balanceOf(address)
        out = {}
        for symbol, token, dec in (("WETH", WETH, 18), ("USDC", USDC, 6)):
            raw = _eth_call(rpc_url, token, data, timeout)
            val = int(raw, 16) / 10 ** dec
            out[symbol] = val * eth_price_usd if symbol == "WETH" else val
        return out
    except Exception:
        return None


# ------------------------------------------------- encodage de l'appel flash
def _abi_encode_address(addr: str) -> bytes:
    return bytes.fromhex(addr[2:].lower().rjust(64, "0"))


def _abi_encode_uint(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def encode_flash_loan_call(recipient: str, tokens: List[str],
                           amounts: List[int],
                           user_data: bytes = b"") -> str:
    """Encode vault.flashLoan(recipient, tokens[], amounts[], userData)
    en calldata hex (stdlib only, pas d'eth_abi). Testé par round-trip
    dans test_balancer.py. NE BROADCAST RIEN : c'est de l'encodage pur."""
    if not is_valid_address(recipient):
        raise ValueError(f"recipient invalide : {recipient}")
    if len(tokens) != len(amounts) or not tokens:
        raise ValueError("tokens et amounts doivent avoir la même taille non vide")
    for t in tokens:
        if not is_valid_address(t):
            raise ValueError(f"token invalide : {t}")
    head = b"".join([_abi_encode_address(recipient),
                     _abi_encode_uint(128),   # offset tokens[]
                     _abi_encode_uint(128 + 32 + 32 * len(tokens)),  # amounts[]
                     _abi_encode_uint(128 + 32 + 32 * len(tokens)
                                      + 32 + 32 * len(amounts))])     # userData
    tail_tokens = _abi_encode_uint(len(tokens)) + b"".join(
        _abi_encode_address(t) for t in tokens)
    tail_amounts = _abi_encode_uint(len(amounts)) + b"".join(
        _abi_encode_uint(a) for a in amounts)
    ud = bytes(user_data)
    tail_data = _abi_encode_uint(len(ud)) + ud + b"\x00" * ((32 - len(ud) % 32) % 32)
    return FLASH_LOAN_SELECTOR + (head + tail_tokens + tail_amounts + tail_data).hex()


def decode_flash_loan_call(calldata: str) -> Dict:
    """Décode un calldata flashLoan (pour les tests / l'audit de l'encodage)."""
    raw = bytes.fromhex(calldata[2:] if calldata.startswith("0x") else calldata)
    assert raw[:4].hex() == FLASH_LOAN_SELECTOR[2:], "sélecteur != flashLoan"
    body = raw[4:]
    recipient = "0x" + body[12:32].hex()  # 1er param : address sur 32 octets
    off_t = int.from_bytes(body[32:64], "big")
    off_a = int.from_bytes(body[64:96], "big")
    off_d = int.from_bytes(body[96:128], "big")
    n_t = int.from_bytes(body[off_t:off_t + 32], "big")
    tokens = ["0x" + body[off_t + 32 + 32 * i + 12:off_t + 64 + 32 * i].hex()
              for i in range(n_t)]
    n_a = int.from_bytes(body[off_a:off_a + 32], "big")
    amounts = [int.from_bytes(body[off_a + 32 + 32 * i:off_a + 64 + 32 * i], "big")
               for i in range(n_a)]
    n_d = int.from_bytes(body[off_d:off_d + 32], "big")
    user_data = body[off_d + 32:off_d + 32 + n_d]
    return {"recipient": recipient, "tokens": tokens, "amounts": amounts,
            "user_data": user_data}


def receive_flash_loan_check(sender: str, tokens: List[str],
                             amounts: List[int],
                             fee_amounts: List[int]) -> Tuple[bool, List[str]]:
    """Vérifications que le callback Solidity DOIT faire (logique pure,
    testable ici sans déployer) :
      1. msg.sender == Vault (sinon n'importe qui peut appeler le callback).
      2. feeAmounts == 0 pour Balancer (si la gouvernance monte le fee,
         le contrat doit le voir et exiger le remboursement exact).
      3. À rembourser = amounts[i] + feeAmounts[i] (jamais moins).
    Retourne (ok, raisons)."""
    reasons: List[str] = []
    if sender.lower() != BALANCER_VAULT.lower():
        reasons.append(f"appelant {sender} != Vault {BALANCER_VAULT} — REJETER")
    if len(tokens) != len(amounts) or len(tokens) != len(fee_amounts):
        reasons.append("tailles tokens/amounts/feeAmounts incohérentes")
    for i, f in enumerate(fee_amounts):
        if f != 0:
            reasons.append(f"feeAmount[{i}] = {f} (attendu 0 — la gouvernance "
                           f"a monté le fee, rembourser amount + fee)")
    return (not reasons), reasons


def repayment_amounts(amounts: List[int], fee_amounts: List[int]) -> List[int]:
    """Ce qu'il faut rembourser au Vault : amount + fee (0 aujourd'hui)."""
    return [a + f for a, f in zip(amounts, fee_amounts)]


if __name__ == "__main__":
    print("Vault Balancer Base :", BALANCER_VAULT)
    print("Collector           :", BALANCER_FEES_COLLECTOR)
    fee, src = fetch_flash_loan_fee_pct()
    print(f"Flash fee lu on-chain : {fee*100:.2f} % (source {src})")
    bal = fetch_vault_balances()
    print("Soldes Vault live :", bal)
    for loan in (790.16, 8_847.98, 30_000.0, 60_000.0):
        sel = select_provider(loan, "USDC")
        print(f"  loan {loan:>10,.2f} $ -> {sel.provider} ({sel.reason})")
    sel = select_provider(790.16, "MEMECOIN")
    print(f"  loan MEME -> {sel.provider} ({sel.reason})")
    cd = encode_flash_loan_call("0x" + "11" * 20, [USDC], [790_160_000])
    print("Calldata flashLoan (USDC 790.16) :", cd[:80] + "...")
    print("Round-trip :", decode_flash_loan_call(cd))
