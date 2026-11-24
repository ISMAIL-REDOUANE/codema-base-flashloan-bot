# EV mesuré — 100 opportunités simulées (v2)

Date : 2026-11-24. Seed : 42 (reproductible : `python3 ev_test.py`). Modèle : decide() v2 (gas unifié, min 3 $, net > gas × 3, plafond gas 2 gwei).

| Métrique | Valeur |
|---|---|
| Opportunités simulées | 100 |
| Trades EXECUTE | 33 (33.0 %) |
| SKIP | 67 (dont 4 par plafond gas) |
| Net total (100 opportunités) | **1117.60 $** |
| **EV par opportunité** | **11.18 $** |
| EV par trade exécuté | 33.87 $ |
| Net moyen / trade exécuté | 33.87 $ (min 3.17 $, max 311.39 $) |
| Spread moyen des trades exécutés | 13.09 % |
| Gas total payé (trades exécutés) | 4.52 $ |
| Max drawdown (courbe cumulée) | 0.00 $ |

**Verdict : GO (modèle) — EV > 0 sur 100 simulations, MAIS go/no-go réel exige 100 simulations FORK**

## Ce que ce test prouve — et ce qu'il ne prouve pas

- Il prouve que, SI les spreads des memes sont bien distribués comme
  supposé (55 % petits, 30 % moyens, 15 % grands) et SI le gas reste
  sous le plafond, le modèle trouve assez de trades à +3 $ pour que
  l'EV par opportunité soit positive.
- Il ne prouve PAS le win rate réel : tous les EXECUTE ont net > 3 $
  PAR CONSTRUCTION de decide(). En live, une partie revertera ou
  sortira perdante (prix qui bouge, MEV, taxes, frais dynamiques).
  Le vrai go/no-go exige 100 simulations FORK (preflight on-chain).
- Les spreads sont SUPPOSÉS, pas mesurés sur des pools réels.
  Si les spreads réels sont plus petits, l'EV réel sera plus petite.
