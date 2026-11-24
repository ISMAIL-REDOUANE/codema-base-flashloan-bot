"""
polygon_flash.py — Flash loan 0 frais sur Polygon (v4.0) : registre des
providers + enforcement.

Le 0 frais est une exigence DURE d'Ismail (« Non khdem bchi flash loan ola
bchi flash ikon 0$ fees »). Ce module est le garde-fou : en mode 0 frais,
seul Morpho Blue Polygon est autorisé. Aave (0,05 %) est BLOQUÉ, Balancer
et dYdX sont MORTS.

Vérifié on-chain 2026-11-24 (voir POLYGON_FLASH_VERIFICATION.md) :
  - Morpho Polygon 0x1bF0c2541F820E775182832f06c0B7Fc27A25f67 : code présent,
    flashFee structurellement 0 (docs : « flashFee is zero »), soldes
    USDC 113 658 $ / USDT 122 030 $.
  - Aave V3 Pool 0x794a61358D6845594F94dc1DB02A252b5b4814aD :
    FLASHLOAN_PREMIUM_TOTAL() = 5 → 0,05 %.
  - Balancer Vault : code présent mais MORT (BIP-928, wind-down 30 oct 2026).
"""
from __future__ import annotations

MORPHO_POLYGON = "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67"
AAVE_V3_POOL_POLYGON = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
BALANCER_VAULT = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"

# fee_rate : None = pas de flash loan (mort) ; 0.0 = 0 frais vérifié.
PROVIDERS = {
    "morpho": {
        "address": MORPHO_POLYGON,
        "fee_rate": 0.0,
        "status": "verified_zero_fee",
        "note": "Morpho Blue Polygon — flashFee 0 par conception (docs + on-chain).",
    },
    "aave": {
        "address": AAVE_V3_POOL_POLYGON,
        "fee_rate": 0.0005,
        "status": "paid",
        "note": "Aave V3 — 0,05 % (FLASHLOAN_PREMIUM_TOTAL = 5 vérifié). BLOQUÉ en mode 0 frais.",
    },
    "balancer": {
        "address": BALANCER_VAULT,
        "fee_rate": None,
        "status": "dead",
        "note": "Balancer MORT (BIP-928, wind-down 30 oct 2026) — NE PLUS UTILISER.",
    },
    "dydx": {
        "address": None,
        "fee_rate": None,
        "status": "dead",
        "note": "dYdX Solo close-only depuis nov 2021 — NE PLUS UTILISER.",
    },
    "uniswap_v4": {
        "address": "0x67366782805870060151383f4bbff9dab53e5cd6",
        "fee_rate": 0.0,
        "status": "verified_zero_fee_alt",
        "note": "V4 flash accounting (unlock + take/settle, pas de fee protocole) — "
                "vérifié docs + on-chain, non implémenté en v4.0.",
    },
}

ZERO_FEE_ALLOWLIST = ["morpho"]   # seuls ces providers en mode 0 frais


class FlashFeeError(ValueError):
    """Levée quand un provider payant ou mort est demandé en mode 0 frais."""


def check_zero_fee(provider: str) -> dict:
    """Vérifie qu'un provider est autorisé en mode 0 frais.
    Retourne sa fiche ; lève FlashFeeError sinon (payant ou mort)."""
    name = provider.strip().lower()
    info = PROVIDERS.get(name)
    if info is None:
        raise FlashFeeError(f"provider inconnu : {provider!r} "
                            f"(connus : {sorted(PROVIDERS)})")
    if info["status"] == "dead":
        raise FlashFeeError(f"provider MORT : {name} — {info['note']}")
    if name in ZERO_FEE_ALLOWLIST:
        return info
    if info["fee_rate"] == 0.0:
        raise FlashFeeError(
            f"provider 0 frais mais NON IMPLÉMENTÉ en v4.0 : {name} — "
            f"{info['note']} Allowlist mode 0 frais : {ZERO_FEE_ALLOWLIST}.")
    raise FlashFeeError(
        f"provider PAYANT : {name} facture {info['fee_rate'] * 100:.2f} % "
        f"— bloqué en mode 0 frais (Ismail : flash loan 0 $ fees). "
        f"Utiliser 'morpho' (0 %).")
    return info


def flash_fee_usd(provider: str, loan_usd: float) -> float:
    """Fee du flash loan en $ pour un provider et un montant donnés."""
    name = provider.strip().lower()
    info = PROVIDERS.get(name)
    if info is None or info["fee_rate"] is None:
        raise FlashFeeError(f"provider inutilisable : {provider!r}")
    return loan_usd * info["fee_rate"]


if __name__ == "__main__":
    for name in ("morpho", "aave", "balancer", "dydx", "uniswap_v4", "nope"):
        try:
            info = check_zero_fee(name)
            print(f"{name:12} OK  fee={info['fee_rate']}  {info['address']}")
        except FlashFeeError as e:
            print(f"{name:12} BLOQUÉ : {e}")
    print("fee Morpho sur 1 000 $ :", flash_fee_usd("morpho", 1000.0), "$")
    print("fee Aave sur 1 000 $ :", flash_fee_usd("aave", 1000.0), "$")
