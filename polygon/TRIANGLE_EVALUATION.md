# Évaluation — Arbitrage triangulaire sur Polygon (v4.1)

**Date :** 2026-11-24 ~23:00 UTC — **Mode : MONITOR-ONLY**
**Script :** `triangle_detector.py` (lecture seule — aucun code de broadcast,
aucune clé, aucun contrat) → résultats bruts `triangle_samples.jsonl`,
`triangle_measurement_*.json`.

## Verdict

**MONITOR-ONLY — aucun triangle exécutable.** Sur **3 échantillons
(54 évaluations : 3 triples × 2 sens × 3 tailles)**, **0 opportunité
à net > 0 $** : meilleur net **−4,19 $** (WMATIC → WETH → USDT →
WMATIC, 1 000 $, échantillon 3, bloc 97 904 182) ; les meilleurs nets
par échantillon sont stables : −4,72 $ / −4,41 $ / −4,19 $. Le pire
net est **−2 416 $** (WMATIC → WETH → USDC.e → WMATIC, 20 000 $).
Le prior « textbook-only » est confirmé par la mesure : les 3 jambes
paient chacune frais + impact, et l'impact explose avec la taille.

Distribution par tranches (règle v4.1, net après gas + budget revert) :
| Tranche | Évaluations |
|---|---|
| net > 0 $ | **0 / 54** |
| net ≥ 0,50 $ | 0 / 54 |
| net ≥ 3 $ (ancienne barre) | 0 / 54 |
| net ≤ 0 $ | 54 / 54 |

## Méthode

- Triples de **grosses pools** (priorité Ismail) : WMATIC/USDC.e/USDT,
  WMATIC/USDC.e/WETH, WMATIC/USDT/WETH — chaque sens évalué.
- Chaque jambe est cotée on-chain sur la **meilleure venue** de la paire
  (QuoterV2 Uni V3, getAmountsOut V2, réserves virtuelles Algebra) ;
  le montant d'entrée de chaque jambe est la **sortie réelle** de la
  jambe précédente (pas une taille fixe).
- Frais de swap comptés sur **chaque jambe** (dans les quotes).
- Gas budgété **600 000 unités** (3 swaps + flash loan + callback) +
  budget revert = 1 × gas (coût total = 2 × gas). Flash fee **0 %**
  (Morpho). Gas live au moment de l'échantillon 1 : **278,3 gwei**
  → gas 0,0127 $, coût total 0,0254 $/cycle.
- Règle v4.1 : opportunité ssi net > 0 $ après TOUS les coûts.

## Échantillons 1–3 — 2026-11-24 22:57 / 23:01 / 23:09 UTC, blocs 97 903 718 / 97 903 868 / 97 904 182

Gas 278,3 / 279,2 / 269,6 gwei. Nets $ (échantillon 1 / 2 / 3 — valeurs
réelles ; la variation d'un échantillon à l'autre atteint ±2,5 $ à
1 000 $ et ±13 $ à 5 000 $, les prix des venues bougent entre blocs) :

| Cycle | 1 000 $ | 5 000 $ | 20 000 $ |
|---|---|---|---|
| WMATIC → USDC.e → USDT → WMATIC | −8,70 / −7,48 / −6,24 $ | −119,51 / −113,56 / −107,45 $ | −1 537,64 / −1 515,47 / −1 494,92 $ |
| WMATIC → USDT → USDC.e → WMATIC | −6,28 / −7,56 / −8,76 $ | −107,91 / −113,87 / −120,53 $ | −1 498,21 / −1 520,46 / −1 548,39 $ |
| WMATIC → USDC.e → WETH → WMATIC | −12,72 / −12,24 / −11,27 $ | −187,30 / −185,07 / −180,53 $ | −2 403,99 / −2 396,92 / −2 382,60 $ |
| WMATIC → WETH → USDC.e → WMATIC | −10,93 / −11,90 / −13,15 $ | −190,92 / −193,29 / −199,77 $ | −2 416,35 / −2 425,38 / −2 449,42 $ |
| WMATIC → USDT → WETH → WMATIC | −5,28 / −5,61 / −5,54 $ | −90,50 / −92,11 / −90,27 $ | −1 233,89 / −1 241,55 / −1 239,55 $ |
| WMATIC → WETH → USDT → WMATIC | **−4,72 / −4,41 / −4,19 $** | −88,30 / −86,78 / −85,66 $ | −1 296,96 / −1 299,69 / −1 305,69 $ |

Lecture : la perte croît avec la taille (impact AMM) — à 1 000 $ elle
est déjà de 0,5–1,3 % (frais des 3 jambes + impact), à 20 000 $ elle
atteint 6–12 %. Aucun désalignement de prix entre les 3 paires ne
compense ces coûts.

Exemple détaillé (meilleur cycle à 1 000 $, WMATIC → USDC.e → USDT → WMATIC) :
- Jambe 1 : 13 141,64 WMATIC → **991,43 USDC.e** (QuickSwap V2, getAmountsOut)
- Jambe 2 : 991,43 USDC.e → **992,68 USDT** (QuickSwap Algebra, réserves virtuelles)
  — la paire stable-stable GAGNE même 0,13 % ;
- Jambe 3 : 992,68 USDT → **13 027,65 WMATIC** (Uniswap V3, QuoterV2)
- Final : 991,33 $ pour 1 000 $ de départ → brut −8,67 $, gas + revert
  −0,03 $ → **net −8,70 $**. La perte vient des deux jambes WMATIC
  (frais 0,3 % V2 + 0,05 % V3 + impact), pas de la jambe stable.

## Conditions de passage en exécutable (non remplies)

Le détecteur ne deviendrait exécutable que si TOUTES ces conditions
sont réunies — aucune ne l'est aujourd'hui :
1. un triangle franchit **net > 0 $** de façon **répétée** (plusieurs
   échantillons, pas un pic isolé) ;
2. preuve sur **fork Polygon** d'un WIN net > 0 $ avec le contrat
   (chemin triangle à implémenter + audit) ;
3. mêmes guards que le bot principal (kill switch, float ledger,
   max 10 % de liquidité, simulation avant broadcast).

Tant que ce n'est pas le cas, le détecteur reste en monitor-only et le
runner (`python3 triangle_detector.py --samples N --interval 300`)
sert à surveiller l'apparition d'opportunités.

## Limites

- Gas triangle estimé à 600 000 unités (pas mesuré on-chain — aucun
  contrat triangle n'existe) ; le coût réel pourrait être ±20 %.
- Les quotes sont instantanées : un triangle qui apparaît et disparaît
  entre deux échantillons (5 min) n'est pas vu — d'où le re-scan
  toutes les 2–4 h recommandé.
- Aucun vrai token testé : les triples sont des majors, pas des memes.
