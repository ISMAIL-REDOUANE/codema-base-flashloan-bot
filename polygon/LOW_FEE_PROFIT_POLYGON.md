# Profiter à 0,02 % – 0,05 % de spread sur Polygon — LOW_FEE_PROFIT_POLYGON.md

Date : 2026-11-25. Auteur : recherche + vérification on-chain (lecture seule).
Question d'Ismail : « 9leb kifach nwliw t7na 3ndna profit wkha howa ri f 0.05 o 0.02 ».

**Verdict en une phrase : la math des frais PERMET le profit à 0,02 %–0,05 %
(breakeven 0,011 % avec une jambe à 0,001 %), mais le marché n'offre pas
ces spreads sur les venues mesurées (tous négatifs) — SAUF une route
4-jambes via Curve, mesurée positive à +1,11 $ / +5,63 $ / +21,70 $ net
à 1 k$ / 5 k$ / 20 k$, qui exploite un prix STALE (USDT à −0,11 % +
pool Curve à volume zéro). C'est une fenêtre, pas un edge permanent.**

---

## 1. Venues à frais < 0,05 % — table vérifiée

Chaque frais vient d'une lecture on-chain ou d'une doc — aucun frais deviné.

| Venue | Frais | Liquidité / profondeur | Source du frais | Verdict |
|---|---|---|---|---|
| Uniswap V3 tier 0,01 % | **0,01 %** | USDC.e/USDT TVL 832 k$, vol24 689 k$ ; WMATIC/USDC.e 0,01 % TVL **292 $** (morte, vol 3,61 $/j) | Fee tier du pool, vérifié on-chain (pro-scan) + DexScreener | Utilisable sur stables ; morte sur WMATIC |
| Uniswap V4 pools 1 bp | **0,01 %** | WETH/USDC.e 5 bp liq 3,13e14, USDC.e/USDT 1 bp, WMATIC/USDC.e 1 bp (pools standards, **sans hook**) | Pro-scan : pools trouvées on-chain via factory | Mêmes frais que V3, pas d'avantage |
| Uniswap V4 hooks 0 frais | **0 % (théorique)** | **AUCUNE avec liquidité réelle** : Bunni v2 TVL **5 $** sur Polygon ; FeeFree ~14 k$ total toutes chaînes ; Angstrom Ethereum only | DefiLlama (Bunni 5 $, FeeFree ~14 k$) ; 0 événement `Initialize` en 10 000 blocs (publicnode, ~5,5 h) | **N'existe pas en pratique sur Polygon** |
| Algebra (QuickSwap V3) stables | **0,001 %** en calme (fee_raw=10) | USDC.e/USDT liq 74 790 $, vol24 103 488 $ ; USDC.e/DAI liq 45 306 $, vol24 144 407 $ | `globalState()` on-chain bloc ~97 920 760 : fee_raw=10 → 10/100 = 0,1 bp = 0,001 % ; factory `baseFeeConfiguration` : baseFee=100 → 0,01 % pour les NOUVELLES pools ; AMA Algebra : stables « as low as 0,01 % », volatiles jusqu'à 2 % | La jambe la moins chère du marché — mais dynamique (remonte en volatilité) |
| Algebra volatiles | **0,0868–0,0878 %** | WMATIC/USDC.e 0,0868 %, WETH/USDC.e 0,0878 % | `globalState()` on-chain : fee_raw=868 / 878 | Plus cher que V3 0,05 % — inutile pour l'arb |
| Curve am3pool (amDAI/amUSDC/amUSDT) | **0,001 %** | TVL 2 263 625 $, A=2000, balances amDAI 841 221 / amUSDC 782 508 / amUSDT 635 581 ; **volume 24 h nul** (API null, 0 le 24 nov) | `fee()` on-chain = 100000 (précision 1e10) → 0,001 % ; confirmé par `get_dy_underlying` (perte 0,0124 % à 1 k$ < frais 0,04 % standard) | **La jambe clé — mais voir §4** : elle trade de l'USDC NATIF via amTokens, pas USDC.e, et son prix est STALE |
| QuickSwap / Sushi V2 | 0,30 % | — | Standard V2 | Trop cher pour 0,02–0,05 % |

Notes :
- Le Quoter V4 `0x31AB…` est **inutilisable** (pas de `quoteExactInputSingle`) ;
  les quotes V4 passent par les réserves virtuelles (comme Algebra).
- Le router Algebra `exactInputSingle` en `eth_call` revert « STF » : c'est un
  vrai swap (il faut les tokens), pas un quoter — ne pas l'utiliser pour coter.
- Les quotes DAI de la sonde Curve étaient **fausses** (bug de sonde : DAI a
  18 décimales, montants passés en 1e6) — jetées, jamais utilisées. Seules les
  quotes USDC/USDT (6 décimales) sont valides.

## 2. Table de breakeven — math du garde Polygon (`polygon_guard.py`)

Méthode : `polygon_decide()` + `evaluate_sizes()` de `math_engine.py`
(réutilisés, pas dupliqués), flash Morpho 0 %, gas 282 gwei, budget total
2× gas = **0,0192 $** (trade + revert), min profit 0 $. Pools synthétiques
profondes (impact ~0) — c'est le bon modèle ici : les pools V3 sont à
liquidité concentrée, et QuoterV2 donne le **même taux à 1 k$ et à 5 k$**
(impact < 0,01 %) ; un modèle constant-product avec la TVL réelle
prédirait −100 $ là où le pro-scan mesure −0,02 $ / −0,15 $ en réel.
Pour les pools volatiles minces (WMATIC/USDC.e 0,05 %, TVL 136 k$),
l'impact réel à 5–20 k$ s'ajoute — le garde le gère via son loan optimal.

| Paire de venues | Frais totaux | Breakeven | Net à 0,02 % (1k / 5k / 20k $) | Net à 0,05 % (1k / 5k / 20k $) | Net à 0,10 % (1k / 5k / 20k $) |
|---|---|---|---|---|---|
| V3 0,01 % + V3 0,01 % | 0,020 % | 0,020 % | −0,02 / −0,03 / −0,18 $ (SKIP) | **+0,28 / +1,47 / +5,82 $** | +0,78 / +3,97 / +15,82 $ |
| V3 0,01 % + Algebra 0,001 % | 0,011 % | **0,011 %** | **+0,07 / +0,42 / +1,62 $** | +0,37 / +1,92 / +7,62 $ | +0,87 / +4,42 / +17,62 $ |
| V3 0,01 % + Curve 0,001 % | 0,011 % | **0,011 %** | **+0,07 / +0,42 / +1,62 $** | +0,37 / +1,92 / +7,62 $ | +0,87 / +4,42 / +17,62 $ |
| V3 0,01 % + V3 0,05 % | 0,060 % | 0,060 % | −0,42 / −2,03 / −8,18 $ | −0,12 / −0,53 / −2,18 $ | +0,38 / +1,97 / +7,81 $ |
| V3 0,05 % + V3 0,05 % | 0,100 % | 0,100 % | −0,82 / −4,03 / −16,18 $ | −0,52 / −2,53 / −10,18 $ | −0,02 / −0,03 / −0,19 $ (breakeven) |
| V3 0,05 % + Algebra volatile ~0,087 % | 0,140 % | 0,140 % | −1,22 / −6,03 / −24,18 $ | −0,92 / −4,53 / −18,18 $ | −0,42 / −2,03 / −8,20 $ |
| V3 0,05 % + V2 0,30 % | 0,350 % | 0,350 % | −3,32 / −16,53 / −66,16 $ | −3,02 / −15,03 / −60,18 $ | −2,52 / −12,54 / −50,22 $ |
| V3 0,30 % + V2 0,30 % | 0,600 % | 0,600 % | −5,81 / −28,99 / −116,02 $ | −5,51 / −27,50 / −110,06 $ | −5,02 / −25,01 / −100,12 $ |

Lecture :
- **À 0,05 % de spread, SEULES les paires avec une jambe à 0,01 % gagnent** :
  V3 0,01 % + V3 0,01 % (+1,47 $ à 5 k$) et V3 0,01 % + Algebra/Curve
  0,001 % (+1,92 $ à 5 k$). Les paires 0,05 % + 0,05 % perdent (−2,53 $).
- **À 0,02 % de spread, SEULES les paires avec une jambe à 0,001 % gagnent**
  (+0,42 $ à 5 k$), et de justesse : le net est de l'ordre du gas × 20.
  V3 0,01 % + V3 0,01 % est à son breakeven exact (−0,03 $ à 5 k$).
- **Ce qui manque pour le reste : une jambe à 0 frais.** Avec une jambe
  0 % (hook V4 avec liquidité — n'existe pas, §1), le breakeven de
  V3 0,01 % + 0 % tomberait à 0,010 %, et V3 0,05 % + 0 % à 0,050 %.
- **Mais le point décisif : les spreads mesurés sont NÉGATIFS.**
  Pro-scan (117 mesures) : meilleur spread −0,014 % ; realtime (61 065
  quotes, 60 min) : meilleur net −0,02 $. Aucune paire 2-jambes ne
  passe, même à breakeven 0,011 %. La table dit ce qui se passerait SI
  le spread existait — il n'existe pas sur ces venues.

## 3. La route qui existe vraiment : USDC → USDC.e → USDT → USDC (Curve)

### Mesures (toutes les jambes au MÊME bloc, `eth_call`, RPC drpc)

Emprunt **USDC natif** chez Morpho (pas USDC.e — voir ci-dessous) :
USDC → USDC.e (V3 0,01 %) → USDT (V3 0,01 %) → USDC (Curve am3pool).

| Bloc | Loan | L0 USDC→USDC.e | L1 USDC.e→USDT | L2 USDT→USDC (Curve) | Brut | Net (gas 4-jambes 2× ≈ 0,028 $) |
|---|---|---|---|---|---|---|
| 97 920 970 | 1 000 $ | — | 1 001,15 | 1 001,25 | +1,15 $ | +1,12 $ |
| 97 920 970 | 5 000 $ | — | 5 005,72 | 5 006,22 | +5,67 $ | +5,64 $ |
| 97 921 113 | 1 000 $ | 999,89 | 1 001,04 | 1 001,14 | +1,14 $ | **+1,11 $** |
| 97 921 113 | 5 000 $ | 4 999,45 | 5 005,16 | 5 005,66 | +5,66 $ | **+5,63 $** |
| 97 921 113 | 20 000 $ | 19 997,48 | 20 019,98 | 20 021,73 | +21,73 $ | **+21,70 $** |
| 97 921 085 | 1 000 $ | — | 1 001,15 | 1 001,25 | +1,14 $ | +1,12 $ |

Variante emprunt USDC.e (marché Morpho minuscule) : à 252 $ (plafond 50 %
des 504,21 $ détenus), brut +0,29 $, net +0,27 $. La route inverse
(USDC → USDT Curve → USDC.e V3 → USDC) perd à toutes les tailles
(−1,57 $ à 1 k$, −7,92 $ à 5 k$) — un seul sens gagne.

### Pourquoi elle existe

- **L'USDT vaut ~0,9988 $ globalement** (CoinGecko 0,99917 $, 3commas
  0,998991 $, altcoinbuzz 0,9988 $, The Block 0,9989 $ — 25 nov 2026).
  Uni V3 et Algebra suivent ce prix : 1 USDC.e = 1,0011 USDT.
- **Le pool Curve am3pool est STALE à 1,0001** : volume ~0, personne ne
  trade, son prix interne n'a jamais suivi la décote de l'USDT.
  1 USDT = 1,0001 USDC sur Curve contre 0,9988 USDC.e sur Uni.
- L'écart brut est donc ~0,11 % — au-dessus des frais totaux de la
  route (0,01 % + 0,01 % + 0,001 % = 0,021 %) et du gas.
- La route est **stable sur ~10 minutes** (3 blocs : 97 920 835 →
  97 921 113, mêmes chiffres à ±0,01 $) et **l'impact prix est
  négligeable jusqu'à 20 k$** (brut 0,114 % à 1 k$, 0,109 % à 20 k$).

### Limites — à lire avant tout enthousiasme

1. **Quotes seulement, jamais exécuté.** Le contrat actuel n'a PAS de
   jambe Curve (`exchange_underlying`) : il faut une nouvelle fonction
   (emprunt Morpho USDC → 2 swaps V3 → Curve → repay), puis un test
   fork avant tout mainnet. Gas 4-jambes estimé ~650 000 unités
   (~0,014 $ le trade, 0,028 $ budgété 2×) — **à mesurer sur fork**.
2. **Plafond de loan : Morpho détient 75 540 $ d'USDC natif** (bloc
   97 920 970 ; 113 658 $ le 24 nov — ça bouge) → règle 50 % ≈
   **37 770 $ max**. Le marché USDC.e ne détient que 504,21 $.
3. **C'est une fenêtre, pas un edge permanent.** Elle meurt si :
   l'USDT revient à 1,0000 $ (la décote se résorbe en heures-jours),
   quelqu'un trade le pool Curve (il se reprice instantanément),
   ou le prix Uni bouge. La re-simulation pré-envoi
   (`revert_protection.py`) + le `minProfit` on-chain 0,01 $
   protègent : si l'edge a disparu au bloc d'exécution, le trade est
   droppé (0 $ gas) ou revert (~0,0024 $ mesuré).
4. `exchange_underlying` n'a pas été exécuté — c'est la fonction
   standard des pools Curve « aave » et `get_dy_underlying` la
   confirme, mais la preuve d'exécution reste le test fork.
5. Le profit par trade est petit en absolu (+5,63 $ à 5 k$) : il faut
   répéter la route tant que la fenêtre dure — chaque répétition est
   un nouveau trade avec son gas et son risque de revert.

## 4. Alternative market-making : gagner les frais au lieu de les payer

Position LP 1 000 $, chiffres DefiLlama yields + DexScreener, 25 nov 2026.
APR calculée sur volume 24 h (DefiLlama `apyBase` = moyenne 7 j, citée
entre parenthèses). Hypothèse favorable : position dans le range 100 %
du temps (un range large passif gagne moins).

| Pool LP | TVL | Vol 24 h | Frais | APR frais | +/semaine (1 k$) | IL |
|---|---|---|---|---|---|---|
| USDC.e/USDT V3 0,01 % | 830 874 $ | 644 001 $ | 0,01 % | 2,83 % (DefiLlama 2,12 %, 7 j 12,66 %) | **+0,41 à 0,54 $** | ~0 (stable-stable, prix 1,0000–1,0012) |
| USDC natif/USDT V3 0,01 % | 536 117 $ | 1 627 546 $ | 0,01 % | 11,08 % (DefiLlama 8,31 %) | **+1,60 à 2,13 $** | ~0 |
| WMATIC/USDC.e V3 0,05 % | 136 185 $ | 35 849 $ | 0,05 % | 4,80 % (DefiLlama 3,60 %) | +0,69 à 0,92 $ | ±10 % → −1,13 $ ; ±20 % → −4,14 $ |
| WMATIC/USDC natif V3 0,05 % | 173 397 $ | 287 306 $ | 0,05 % | 30,24 % (DefiLlama 22,68 %) | +4,36 à 5,80 $ | ±10 % → −1,13 $ ; ±20 % → −4,14 $ |
| Algebra USDC.e/USDT | 74 790 $ | 103 488 $ | 0,001 % actuel | ~0,5 % (borne basse ; frais moyen 24 h inconnu, dynamique) | ~+0,10 $ | ~0 |
| WMATIC/USDC.e V3 0,01 % | 292 $ | 3,61 $ | 0,01 % | ~0,05 % | ~0,01 $ | — (pool morte) |

IL (full-range, formule 2√r/(1+r)−1, position 1 000 $) : prix ×1,05 → −0,30 $ ;
×1,10 → −1,13 $ ; ×1,20 → −4,14 $ ; ×0,90 → −1,39 $ ; ×0,80 → −6,19 $.
Gas LP : mint/collect/burn ~0,002–0,004 $ chacun à 282 gwei — négligeable
en cadence mensuelle, ~0,01–0,02 $/sem en rebalancing hebdo actif.

**Verdict market-making :**
- **Stable-stable (USDC/USDT 0,01 %) : petit positif réel, +0,41 à
  2,13 $/semaine par 1 000 $**, IL quasi nulle, gas négligeable. Mais :
  capital à risque (pas de flash loan), 1 000 $ immobilisés pour
  ~0,50–2 $/sem, et il faut rester dans le range (si l'USDT dépegs
  plus, les frais s'arrêtent). C'est un revenu, pas un trade.
- **WMATIC/USDC.e 0,05 % : net ≤ 0 la plupart des semaines en passif.**
  Un seul mouvement de ±10 % (−1,13 $) efface 1,2–1,6 semaine de frais
  ; ±20 % (−4,14 $) en efface ~6. La pool WMATIC/USDC natif à 22,68 %
  encaisse mieux (une semaine de frais = 4,36 $), mais reste exposée
  à la même IL — positif seulement avec gestion active du range.
- **Conclusion : le LP stable-stable est la seule alternative qui
  gagne vraiment à 0,02–0,05 % de spread — mais elle gagne des
  centimes par semaine par millier de dollars, pas des dollars par
  trade.** Elle ne remplace pas l'arbitrage ; elle le complète avec
  du capital au repos.

## 5. Verdict final — les routes exactes

### À 0,05 % de spread
- **Théorie : OUI.** V3 0,01 % + V3 0,01 % (breakeven 0,020 %) et
  V3 0,01 % + Algebra/Curve 0,001 % (breakeven 0,011 %) sont
  profitables : +1,47 $ / +1,92 $ net à 5 k$.
- **Pratique : NON, pas aujourd'hui.** Les spreads mesurés sur ces
  venues sont négatifs (meilleur −0,014 %). Il n'y a rien à prendre
  en 2-jambes.
- **Sauf la route Curve 4-jambes (§3)**, qui gagne +5,63 $ net à
  5 k$ — mais son spread brut est 0,11 %, pas 0,05 % : elle ne
  prouve pas le 0,05 %, elle contourne le problème par un prix stale.

### À 0,02 % de spread
- **Théorie : OUI, de justesse.** Seules les paires avec une jambe à
  0,001 % passent (breakeven 0,011 %) : +0,42 $ net à 5 k$,
  +0,07 $ à 1 k$. V3 0,01 % + V3 0,01 % est exactement à son
  breakeven (−0,03 $ à 5 k$).
- **Pratique : NON.** Même remarque : aucun spread de 0,02 % mesuré
  en live. Et à +0,42 $ par trade, une seule variation de prix entre
  la quote et l'inclusion efface le profit — le garde dropprait le
  trade (0 $ gas) plus souvent qu'il ne l'exécuterait.

### Ce qu'il faudrait pour que ça change
1. **Un spread réel ≥ breakeven** sur les venues 0,01 % / 0,001 %
   (0,011–0,020 %) — il n'apparaît pas dans 61 065 quotes + 117
   mesures. Le realtime listener le verrait s'il apparaissait.
2. **Ou une jambe à 0 frais avec liquidité** (hook V4) — n'existe pas
   sur Polygon aujourd'hui (Bunni 5 $, FeeFree ~14 k$, Angstrom
   Ethereum only, 0 nouveau pool V4 en 10 000 blocs).
3. **Ou exploiter la fenêtre Curve (§3)** : c'est la seule route
   positive mesurée. Étapes : (a) fonction Curve dans le contrat,
   (b) test fork avec les quotes réelles, (c) surveillance de la
   décote USDT + du prix Curve, (d) exécution tant que la fenêtre
   dure, arrêt dès qu'elle se ferme. Gain attendu : ~+1,11 $/trade
   à 1 k$, ~+5,63 $ à 5 k$, ~+21,70 $ à 20 k$ — tant que l'USDT
   reste décoté et que personne ne trade le pool Curve.

### Ce qui est FAUX de croire
- « Les tiers 0,01 % suffisent » — non : sans spread mesuré, le
  breakeven bas ne sert à rien. Le problème n'a jamais été le frais,
  c'est l'absence de spread.
- « Curve = frais 0,04 % » — non : l'am3pool est à 0,001 % (lu
  on-chain), mais il trade de l'USDC natif, pas USDC.e — la route
  a besoin d'une jambe USDC↔USDC.e en plus (c'est la jambe L0).
- « La route Curve est un edge durable » — non : c'est une
  décote USDT (~0,11 %) + un pool mort. Elle peut durer des heures
  comme disparaître au prochain bloc.

## Annexe — fichiers et reproductibilité

- `low_fee_routes.py` : quoter 4-jambes (lecture seule, même bloc),
  `breakeven_table()` (math du garde), `lp_evaluation()`,
  `impermanent_loss_pct()`. `python3 low_fee_routes.py` réimprime
  les tables.
- `test_low_fee.py` : 20/20 tests (conversions de frais, breakevens,
  quotes enregistrées blocs 97 920 970 / 97 921 113, LP, IL).
  Suites existantes non touchées et toujours vertes : test_polygon
  25/25, test_pro_scan + test_realtime_listener +
  test_revert_protection 64/64.
- **Aucun fichier existant modifié. Aucun broadcast, aucun wallet,
  aucune clé, aucun fonds réel.**
- Adresses : Morpho Polygon `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` ;
  Curve am3pool `0x445FE580eF8d70FF569aB36e80c647af338db351` ;
  Algebra factory `0x411b0fAcC3489691f28ad58c47006AF5E3Ab3A28` ;
  V3 USDC.e/USDT 0,01 % `0xDaC8A8E6DBf8c690ec6815e0fF03491B2770255D` ;
  V3 USDC natif/USDT 0,01 % `0x31083a78E11B18e450fd139F9ABEa98CD53181B7` ;
  V3 USDC/USDC.e 0,01 % `0xD36ec33c8bed5a9F7B6630855f1533455b98a418`.
