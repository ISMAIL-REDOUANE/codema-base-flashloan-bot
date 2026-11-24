# Grosses pools — Mesure LIVE des spreads cross-DEX (Polygon, v4.1)

**Date :** 2026-11-24 — **Priorité Ismail** : les grosses pools auraient
moins de concurrence sur Polygon. On MESURE, on ne promet rien.
**Script :** `big_pools.py` (lecture seule — aucun broadcast, aucune clé)
→ résultats bruts `big_pools_samples.jsonl`, `big_pools_measurement_*.json`.

## Verdict (final, 6 échantillons au total)

**MONITOR-ONLY.** Sur **6 échantillons** (3 avec un bug qui excluait les
venues Algebra + 3 corrigés avec toutes les venues), **toutes les
mesures sont négatives** : le meilleur spread observé est **−0,014 %**
(USDC.e/DAI, 1 000 $) et le meilleur net est **−0,02 $** partout
(= −2 × gas, le loan optimal tombe à ~0). Aucun spread ≥ +0,1 %
(net ≥ 3 $ sur loan 5 000 $) n'apparaît, et aucun net > 0 $ non plus
(règle v4.1). Les venues sont alignées à ~0,03–0,05 % près — comme sur
le fork — et les frais + impact des deux jambes effacent tout écart.
**La correction du bug Algebra n'a rien changé au verdict** : les
venues Algebra sont bien les meilleures sur WMATIC/WETH et USDC.e/DAI,
mais leurs spreads restent négatifs.

⚠️ **Biais connu des échantillons 1–3** : la version de `big_pools.py`
utilisée alors excluait silencieusement les venues **Algebra**
(QuickSwap V3) et les V2 sans router connu (bug `TOKENS[adresse]`
+ dépaquetage 3-tuple — corrigé depuis). Ces 3 échantillons sont
conservés dans `big_pools_samples_superseded_pre-algebra-fix.jsonl`
et dans les fichiers `big_pools_measurement_2026-11-24T2252/2256/2259.json` ;
ils ne comptent pas dans le verdict final, mais ils montrent déjà la
même chose (tous spreads négatifs).

## Méthode

- Paires majors, liquidité ≥ 500 000 $ quelque part (pas de plafond) :
  WMATIC/USDC.e, WMATIC/USDT, WETH/USDC.e, USDC.e/USDT, WMATIC/WETH,
  USDC.e/DAI, WMATIC/USDC (natif).
- Venues découvertes live via **DexScreener** (top 6 par paire, Polygon,
  liquidité ≥ 10 000 $), classées on-chain (V2 / Uni V3 / Algebra) ;
  repli sur liste statique vérifiée si DexScreener est injoignable.
  **Balancer exclu** (pairAddress composite non-adresse + protocole
  mort, BIP-928).
- Quotes on-chain des deux sens par taille (1 000 $, 5 000 $, 20 000 $) :
  QuoterV2 (Uni V3), getAmountsOut (V2), réserves virtuelles (Algebra).
  Tailles en $ converties via prix de référence CoinGecko + prix propre
  de chaque venue — chaque venue reçoit le même montant en $.
- Spread = meilleur prix de VENTE / meilleur prix d'ACHAT − 1.
- Net via `polygon_guard` (règle v4.1 : net > 0 $ après flash 0 %,
  frais de swap, gas + budget revert = 2 × gas) avec les réserves des
  meilleures venues (réelles V2, virtuelles V3, quote côté en $).
  Gas live ~275–284 gwei pendant les mesures (~0,005 $/trade, 0,01 $
  budgété avec revert).
- Règle d'évaluation : le tier devient EXÉCUTABLE seulement si des
  spreads ≥ ~0,1 % apparaissent avec une fréquence mesurable ; sinon
  il reste MONITOR-ONLY.

## Échantillons 1–3 (supplantés — Algebra exclues, voir biais ci-dessus)

Blocs 97 903 489 / 97 903 581 / 97 903 714 — gas 274,6 / 281,9 / 283,8 gwei.
Spreads % (négatif = acheter coûte plus cher que vendre ne rapporte) :

| Paire | 1 000 $ | 5 000 $ | 20 000 $ |
|---|---|---|---|
| WMATIC/USDC.e | −1,34 % | −4,24 % | −14,02 % |
| WMATIC/USDT | −0,13 % | −0,25 % | −0,69 % |
| WETH/USDC.e | −0,51 % | −1,65 % | −4,70 % |
| USDC.e/USDT | **−0,02 %** | −0,02 % | −0,03 % |
| WMATIC/WETH | −0,57 % / −0,47 % | −2,37 % / −1,79 % | −12,25 % / −6,50 % |
| USDC.e/DAI | −0,02 % | −0,03 % | −0,05 % |
| WMATIC/USDC | −0,46 % | −1,92 % | −7,63 % |

Net : **−0,02 $ partout** (SKIP, loan optimal ~0). Tranches :
>0$ : 0 | ≥0,50$ : 0 | ≥3$ : 0 | ≤0$ : 63/63 mesures.

Lecture : le spread négatif croît avec la taille (impact AMM) — à
20 000 $, il atteint −14 % sur WMATIC/USDC.e car le loan tape des
pools dont les réserves virtuelles actives sont petites (la liquidité
« 530 k $ » DexScreener n'est pas la liquidité active au tick courant).
Les paires stable-stable (USDC.e/USDT, USDC.e/DAI) sont les plus
serrées (−0,02 %) mais ne laissent aucune marge après frais (0,05 %
V3 + 0,3 % V2 par jambe).

## Échantillons corrigés (Algebra incluses) — 23:04, 23:11 et 23:18 UTC

Blocs 97 903 998 / 97 904 286 / 97 904 555 — gas 283,0 / 280,7 / ~281 gwei.
6 venues cotées par paire en moyenne (Uni V3, QS V2, Sushi V2,
Algebra, + V2 forks : dooar, apeswap, jetswap, gravityfinance).
Spreads % (les trois échantillons, quasi identiques — stabilité ±0,16 pp max) :

| Paire | 1 000 $ | 5 000 $ | 20 000 $ |
|---|---|---|---|
| WMATIC/USDC.e | −1,34 % | −4,24 % | −14,02 % |
| WMATIC/USDT | −0,13 % | −0,25 % | −0,69 % / −0,71 % |
| WETH/USDC.e | −0,60 % / −0,61 % | −1,65 % | −4,70 % |
| USDC.e/USDT | −0,02 % | −0,03 % | −0,06 % |
| WMATIC/WETH | −0,47 % | −1,79 % | −6,51 % |
| USDC.e/DAI | **−0,01 %** | −0,03 % | −0,05 % |
| WMATIC/USDC | −0,46 % / −0,47 % | −1,93 % / −1,95 % | −7,72 % / −7,87 % |

Net : **−0,02 $ sur les 63 mesures** (SKIP, loan optimal ~0). Tranches :
>0$ : **0 / 63** | ≥0,50$ : 0 / 63 | ≥3$ : 0 / 63 | ≤0$ : 63 / 63.
Fait notable : meilleur achat et meilleure vente sont souvent la
**même venue** (ex. QuickSwap V2 des deux côtés sur WMATIC/USDC.e,
Uni V3 des deux côtés sur WMATIC/USDT) — aucune autre venue ne bat
son prix dans un sens ou dans l'autre : le marché est aligné, le
spread négatif n'est que frais + impact.

## Conditions de passage en exécutable (non remplies)

1. Des spreads ≥ ~0,1 % (net > 0 $ à la règle v4.1, idéalement
   net ≥ 3 $ sur loan 5 000 $) apparaissent sur **plusieurs
   échantillons** ;
2. Preuve sur **fork Polygon** d'un WIN avec le contrat existant
   (chemin cross-DEX déjà prouvé pour WMATIC/USDC.e) ;
3. Mêmes guards que le bot principal (kill switch, float ledger,
   max 10 % de liquidité, simulation avant broadcast).

## Limites

- Les quotes sont instantanées (échantillons toutes les 5 min) : un
  écart qui apparaît et disparaît entre deux échantillons n'est pas vu.
- Les réserves virtuelles V3/Algebra approximent la liquidité active
  au tick courant ; un trade réel traverserait des ticks et paierait
  plus d'impact que la quote QuoterV2 ne le montre parfois.
- Prix de référence CoinGecko (MATIC, WETH, stables) : une erreur de
  prix fausse la taille en $ des quotes, pas le spread (les deux sens
  utilisent la même référence).
