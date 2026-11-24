"""
polygon_ledger.py — Grand livre du float gas Polygon (v4.0).

Réutilise le FloatLedger du bot Base (self_funded.py) avec le float RÉEL
d'Ismail : 17,2743 MATIC ≈ 1,31 $ (screenshot MetaMask 2026-11-24 21:53).
Le gas Polygon coûte ~0,0095 $/trade (279 gwei) : le float couvre ~137
trades au gas mesuré (~68 au pire cas trade + revert) — assez pour
démarrer, la contrainte reste les opportunités, pas le float.
NOTE : le FloatLedger arrondit au centime — le gas 0,0095 $/trade compte
0,01 $ dans le livre (arrondi prudent, jamais sous-estimé).

Règles identiques au mode autofinancé Base (v3.4) :
  - Le gas sort du FLOAT d'Ismail, jamais d'un sponsor (part sponsor 0 %,
    Ismail garde 100 % du profit).
  - can_afford() bloque tout trade dont le PIRE CAS (gas + budget revert)
    dépasse le float restant — jamais de trade à découvert.
  - Kill switch à 0 $ : tous les trades s'arrêtent, il faut recharger.
  - Les profits (USDC) ne rechargent PAS le float (conversion manuelle).

Aucune clé privée, aucune création de wallet : comptabilité seulement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from self_funded import FloatLedger  # noqa: E402

FLOAT_MATIC = 17.2743            # solde réel d'Ismail (MetaMask, 2026-11-24)
MATIC_PRICE_USD = 0.0758        # CoinGecko polygon-ecosystem-token
FLOAT_USD = round(FLOAT_MATIC * MATIC_PRICE_USD, 2)   # 1,31 $
LOW_FLOAT_ALERT_USD = 0.5
MIN_PROFIT_USD = 3.0


def polygon_ledger(state_path: str = "float_state_polygon.json",
                   trades_path: str = "trades_polygon.jsonl") -> FloatLedger:
    """FloatLedger configuré pour Polygon : float 1,31 $, part sponsor 0 %."""
    return FloatLedger(
        payer="ismail",
        float_usd=FLOAT_USD,
        sponsor_share_pct=0.0,
        gas_payer="ismail",
        min_profit_usd=MIN_PROFIT_USD,
        low_float_alert_usd=LOW_FLOAT_ALERT_USD,
        state_path=state_path,
        trades_path=trades_path,
    )


def trades_covered(ledger: FloatLedger, gas_usd_per_trade: float,
                   worst_case_multiple: float = 2.0) -> int:
    """Combien de trades le float restant couvre-t-il, au pire cas
    (gas × 2 = trade + un revert) ?"""
    worst = gas_usd_per_trade * worst_case_multiple
    if worst <= 0:
        return 0
    return int(ledger.float_remaining_usd // worst)


def float_runway(ledger: FloatLedger, gas_usd_per_trade: float,
                 revert_usd_per_trade: float | None = None) -> dict:
    """Autonomie du float : trades couverts, au coût mesuré et au pire cas."""
    revert = gas_usd_per_trade if revert_usd_per_trade is None \
        else revert_usd_per_trade
    return {
        "float_usd": ledger.float_usd,
        "float_matic": FLOAT_MATIC,
        "float_remaining_usd": ledger.float_remaining_usd,
        "ismail_paid_usd": ledger.ismail_paid_usd,
        "profits_usd": ledger.profits_usd,
        "gas_usd_per_trade": gas_usd_per_trade,
        "revert_usd_per_trade": revert,
        "trades_at_measured_gas": int(ledger.float_remaining_usd
                                      // max(gas_usd_per_trade, 1e-9)),
        "trades_worst_case": trades_covered(ledger, gas_usd_per_trade),
        "kill_switch": ledger.tripped,
        "can_trade": ledger.status()["can_trade"],
    }


if __name__ == "__main__":
    led = polygon_ledger(state_path=None, trades_path=None)
    print(led.float_status_line())
    print(f"float : {FLOAT_MATIC} MATIC = {FLOAT_USD} $")
    # Gas mesuré live Polygon : ~279 gwei × 450 000 unités ≈ 0,0095 $
    print(float_runway(led, gas_usd_per_trade=0.00952))
    print("Trade +73,07 $ (gas 0,00952 $) :",
          led.record_trade("MEME-WIN-POLYGON", 73.07, 0.00952, "morpho",
                           simulated=True))
    print("Après :", led.float_status_line())
