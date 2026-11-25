"""
route.py — Route typée + capacités d'exécution des contrats (audit #7).

LE PROBLÈME (audit #7) : le scanner (cross_venue.py) remonte des routes
CL (Uniswap V3, Aerodrome Slipstream) alors que le contrat principal Base
(FlashLoanArbitrage / MorphoFlashLoanArbitrage) ne sait exécuter que des
jambes V2 (swapExactTokensForTokens). L'exécuteur prétendait EXECUTE sur
des routes qu'aucun contrat ne peut exécuter.

LA CORRECTION :
  - Une route est un objet typé : token emprunté, token intermédiaire,
    jambes (kind, pool, router, fee, sens). Le kind dit QUEL adaptateur
    il faut — et s'il existe.
  - route_executable_by_contract() dit si la route est exécutable par les
    contrats disponibles, avec la raison explicite sinon. L'exécuteur
    (executor.simulate) refuse (SKIP) toute route non exécutable — il ne
    prétend plus qu'une route CL est exécutable tant que l'adaptateur
    n'existe pas.
  - Adaptateurs EXISTANTS (compilés, prouvés sur fork) :
      "v2"     : FlashLoanArbitrage / MorphoFlashLoanArbitrage
                 (swapExactTokensForTokens — Uni V2 / Sushi V2 / BaseSwap V2)
      "v3-uni" : MorphoFlashLoanArbitrageV3 (SwapRouter02 exactInputSingle —
                 Uniswap V3 uniquement ; contrat écrit audit #7, prouvé sur
                 fork, NON déployé mainnet, NON audité)
  - Kinds SANS adaptateur (route refusée, raison explicite) :
      "aero-classic"    : Aerodrome Classic — le router n'a PAS l'interface
                          V2 (vérifié sur le bytecode) ; la cotation
                          Route-based existe (preflight), pas l'exécution.
      "aero-slipstream" : Slipstream CL — quoter dédié non implémenté,
                          adaptateur absent.
      "v4"              : Uniswap V4 — adaptateur absent.
  - Prêt cbBTC (audit #7) : le token emprunté fait partie de la route.
    Morpho ne détient que les tokens de ses marchés ; un prêt dans un
    token dont les soldes ne sont pas vérifiés (ni live ni mesurés) est
    refusé explicitement par l'exécuteur — jamais supposé disponible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"

# Kinds de jambes connus.
LEG_KIND_V2 = "v2"                    # Uni V2 / Sushi V2 / BaseSwap V2
LEG_KIND_AERO_CLASSIC = "aero-classic"  # Aerodrome Classic (Route-based)
LEG_KIND_V3_UNI = "v3-uni"            # Uniswap V3 (exactInputSingle)
LEG_KIND_AERO_SLIPSTREAM = "aero-slipstream"  # Aerodrome Slipstream (CL)
LEG_KIND_V4 = "v4"                    # Uniswap V4

# Nom de DEX (tel qu'il apparaît dans MemeCandidate.dex_a/dex_b) -> kind.
DEX_KIND = {
    "uniswap": LEG_KIND_V2, "uniswapv2": LEG_KIND_V2,
    "sushi": LEG_KIND_V2, "sushiswap": LEG_KIND_V2,
    "baseswap": LEG_KIND_V2,
    "aerodrome": LEG_KIND_AERO_CLASSIC, "aero": LEG_KIND_AERO_CLASSIC,
    "slipstream": LEG_KIND_AERO_SLIPSTREAM,
    "aerodrome-slipstream": LEG_KIND_AERO_SLIPSTREAM,
    "uniswapv3": LEG_KIND_V3_UNI, "uniswap-v3": LEG_KIND_V3_UNI,
    "v3": LEG_KIND_V3_UNI,
    "uniswapv4": LEG_KIND_V4, "v4": LEG_KIND_V4,
}

# Kind -> adaptateur (contrat) qui l'exécute. Absent = AUCUN adaptateur.
ADAPTER_FOR_KIND = {
    LEG_KIND_V2: ("v2", "FlashLoanArbitrage / MorphoFlashLoanArbitrage "
                        "(swapExactTokensForTokens)"),
    LEG_KIND_V3_UNI: ("v3-uni", "MorphoFlashLoanArbitrageV3 "
                                "(SwapRouter02 exactInputSingle) — prouvé sur "
                                "fork, NON déployé mainnet, NON audité"),
}

# Raison explicite par kind sans adaptateur.
NO_ADAPTER_REASON = {
    LEG_KIND_AERO_CLASSIC: ("jambe Aerodrome Classic : le router Aerodrome "
                            "n'a PAS l'interface V2 (vérifié sur le bytecode) "
                            "— cotation Route-based possible, exécution "
                            "impossible sans adaptateur (absent)"),
    LEG_KIND_AERO_SLIPSTREAM: ("jambe Slipstream : aucun adaptateur "
                               "(quoter + router dédiés non implémentés)"),
    LEG_KIND_V4: ("jambe Uniswap V4 : aucun adaptateur"),
}


@dataclass
class Leg:
    """Une jambe d'arbitrage : un swap dans UNE pool, dans UN sens."""
    kind: str                      # "v2" | "aero-classic" | "v3-uni" | ...
    dex_name: str = ""             # nom brut (ex. "aerodrome")
    pool_address: Optional[str] = None
    router_address: Optional[str] = None
    fee_bps: int = 30


@dataclass
class Route:
    """Une route d'arbitrage complète et typée (audit #7)."""
    loan_token: str                # adresse du token emprunté en flash loan
    loan_token_symbol: str = "USDC"
    mid_token: str = ""            # adresse du token intermédiaire (MEME)
    mid_token_symbol: str = ""
    legs: List[Leg] = field(default_factory=list)  # [achat, vente]
    provider: str = "morpho"

    def kinds(self) -> List[str]:
        return [leg.kind for leg in self.legs]


def kind_for_dex(dex_name: str) -> str:
    """Kind d'un nom de DEX (insensible à la casse, préfixe avant ':')."""
    key = (dex_name or "").lower().split(":")[0].strip()
    return DEX_KIND.get(key, "unknown")


def route_executable_by_contract(route: Route,
                                 adapters: Tuple[str, ...] = ("v2",)
                                 ) -> Tuple[bool, str]:
    """La route est-elle exécutable par les contrats disponibles ?
    adapters = kinds autorisés (défaut ("v2",) = les contrats V2 seuls ;
    passer ("v2", "v3-uni") quand l'adaptateur V3 est déployé et câblé).
    Retourne (True, "") ou (False, raison explicite — jamais un silence)."""
    if not route.legs:
        return False, "route sans jambes — rien à exécuter"
    if len(route.legs) != 2:
        return False, (f"route à {len(route.legs)} jambes — le contrat "
                       "n'exécute que des allers-retours à 2 jambes")
    if len(set(route.kinds())) != 1:
        return False, "legacy contracts require homogeneous legs; use AtomicArbitrage for a mixed route"
    for i, leg in enumerate(route.legs):
        if leg.kind == "unknown":
            return False, (f"jambe {i + 1} ({leg.dex_name or '?'}) : kind "
                           "inconnu — DEX non reconnue, exécution refusée")
        if leg.kind not in ADAPTER_FOR_KIND:
            return False, (f"jambe {i + 1} ({leg.dex_name or leg.kind}) : "
                           + NO_ADAPTER_REASON.get(
                               leg.kind, f"kind {leg.kind} : aucun adaptateur"))
        adapter_kind, _desc = ADAPTER_FOR_KIND[leg.kind]
        if adapter_kind not in adapters:
            return False, (f"jambe {i + 1} ({leg.dex_name or leg.kind}) : "
                           f"adaptateur '{adapter_kind}' non autorisé "
                           f"(adapters={list(adapters)}) — le contrat "
                           "correspondant n'est pas déployé/câblé")
    return True, ""


def build_route_from_candidate(candidate, loan_token: str = USDC,
                               loan_token_symbol: str = "USDC",
                               provider: str = "morpho") -> Route:
    """Construit la Route typée d'un MemeCandidate (dex_a/dex_b -> kinds).
    Ne prétend rien sur l'exécutabilité : c'est route_executable_by_contract
    qui tranche."""
    return Route(
        loan_token=loan_token,
        loan_token_symbol=loan_token_symbol,
        mid_token=candidate.token_address,
        mid_token_symbol=candidate.symbol,
        legs=[
            Leg(kind=kind_for_dex(candidate.dex_a), dex_name=candidate.dex_a,
                fee_bps=candidate.pool_a.fee_bps),
            Leg(kind=kind_for_dex(candidate.dex_b), dex_name=candidate.dex_b,
                fee_bps=candidate.pool_b.fee_bps),
        ],
        provider=provider,
    )


if __name__ == "__main__":
    # Démo : V2+V2 exécutable ; Aerodrome+V2 refusée ; V3 refusée par défaut.
    from scanner import MemeCandidate
    from math_engine import Pool
    v2 = build_route_from_candidate(MemeCandidate(
        "0xAAA", "MEME", "uniswap", "sushi",
        Pool("U", 20_000, 20_000_000), Pool("S", 18_000, 15_000_000)))
    print("V2+V2 :", route_executable_by_contract(v2))
    aero = build_route_from_candidate(MemeCandidate(
        "0xAAA", "MEME", "aerodrome", "uniswap",
        Pool("A", 20_000, 20_000_000), Pool("U", 18_000, 15_000_000)))
    print("Aero+V2 :", route_executable_by_contract(aero))
    v3 = build_route_from_candidate(MemeCandidate(
        "0xAAA", "MEME", "uniswapv3", "uniswapv3",
        Pool("V3a", 20_000, 20_000_000), Pool("V3b", 18_000, 15_000_000)))
    print("V3+V3 (défaut) :", route_executable_by_contract(v3))
    print("V3+V3 (adapters v2+v3-uni) :",
          route_executable_by_contract(v3, adapters=("v2", "v3-uni")))
