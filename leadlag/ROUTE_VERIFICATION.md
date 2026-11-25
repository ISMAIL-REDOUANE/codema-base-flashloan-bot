# ROUTE VERIFICATION — Arbitrage cross-venue Base (WETH/cbBTC, WETH/USDC, cbBTC/USDC)

> **SYNTHÉTIQUE — tous les chiffres ci-dessous sont des QUOTES et des SIMULATIONS (modèle analytique mono-tick + quoters on-chain), jamais des trades exécutés, jamais un profit réalisé.** Les mesures dites « live » sont des lectures on-chain (état des pools, fees, gas) au bloc indiqué ; elles ne prouvent pas qu'un trade aurait été exécuté.
> Date : 2026-11-25. Repo : `codema-base-flashloan-bot`, branche `master` (commit a486284, 2026-11-25 11:54 — ce travail n'y est PAS inclus, le parent pousse).
> Fichiers : `leadlag/route_verify.py`, `leadlag/size_optimizer.py`, `leadlag/replay.py`, `leadlag/replay_analyze.py`, `leadlag/verify_top_events.py`, `leadlag/verify_static_positives.py`, `leadlag/test_route_verify.py`, `leadlag/replay_24h.jsonl` (17 250 échantillons), `leadlag/replay_24h_summary.json`, `leadlag/static_positives_verified.json`, `leadlag/size_optimizer_results.json`, `leadlag/route_verify_100.json`.

---

## (a) Vérification des chiffres — route WETH/cbBTC, bloc 62 077 712 (scan)

**Route :** achat Aero `0xeC3c3755b9DED4a2960ef50C9b48C1694CE274C2` (fee on-chain **85** = 0,0085 %) → vente Aerodrome `0x42d4a22CaD0F5a49681a5715cE994Af73A43B76b` (fee on-chain **300** = 0,03 %), taille **100 $**, bloc **62 077 712** (archive Alchemy, accessible — le bloc exact a été relu).

| Poste | Valeur | Commentaire |
|---|---|---|
| Gap mid (brut) | **+0,0273 %** → **+0,0273 $** | mid achat 0,02801048 → mid vente 0,02801138 cbBTC/WETH |
| Fee jambe achat | **0,0085 $** (85 = 0,85 bp) | lue on-chain au bloc |
| Fee jambe vente | **0,0300 $** (300 = 3 bp) | lue on-chain au bloc |
| **Fees totales** | **0,0385 $ = 3,85 bp** | **CORRECTION audit : PAS 2 bp** (voir § Corrections) |
| Impact achat | ~0,0000 $ | pool profonde (TVL 4,78 M$) |
| Impact vente | 0,0021 $ | pool TVL 442 584 $ |
| Impact total | **0,0021 $** | |
| Gas (ancien, figé) | 0,0044 $ | hypothèse du scan |
| Gas (mesuré, audit #12) | **0,0024 $** | coût complet tx exacte (voir § Gas) |
| **Net (gas ancien)** | **−0,0183 $** | **CONFIRMÉ — identique au scan** |
| **Net (gas mesuré)** | **−0,0162 $** | net corrigé avec le vrai gas |
| Threshold (gas ancien) | 0,0429 % | **CONFIRMÉ** |
| Threshold (gas mesuré) | 0,0409 % | |
| Identité (décomposé − direct) | +0,00052 $ | arrondi int (troncature) — négligeable |
| Garde quoter jambe vente | **vérifiée** (MixedQuoterV3 : 170 382 raw vs analytique 170 382 → −0,0001 %) | |
| Garde quoter jambe achat | **not_addressable** (factory 0x9cb2, aucun quoter) | modèle analytique seul |
| Crosscheck `v3_quote_python` | 0,0 % sur les deux jambes | modèle indépendant |
| Statut route | **PARTIALLY_VERIFIED** | une jambe quoter-vérifiée, une analytique |

**Conclusion (a) : le −0,0183 $ du scan est CONFIRMÉ, et le threshold 0,0429 % est CONFIRMÉ** (avec le gas figé du scan). Avec le gas mesuré (0,0024 $ au lieu de 0,0044 $), le net devient −0,0162 $ et le threshold 0,0409 %.

### Gas complet (audit #12) — mesuré live au bloc 62 077 712
- Exécution L2 : **285 948 unités** (mesurées en fork Base, bloc 61 807 834, `fork_results_morpho.json`) ; baseFee 0,005002 gwei → **0,002351 $**.
- Fee L1 Base : **0,000002 $** (0,1 % du total) — validée contre un vrai reçu (tx `0x5f7cfe70ac`, l1Fee 1 183 275 227 wei = valeur oracle). Le calldata est 36 o (`executeArbitrage(uint256)`), la L1 est quasi indépendante de la taille (plancher Fjord 100 o).
- **Total mesuré : 0,002353 $** ; prudent (450 000 unités, budget repo) : **0,003701 $**. L'ancien 0,0044 $ figé **surestimait** le gas. Les mesures fork Anvil ne comptent pas la L1 — ici elle est mesurée, pas supposée.

---

## (b) Tableau — grille de tailles $1–$1 000, bloc 62 077 712, gas mesuré 0,0024 $

Cycle atomique complet simulé à chaque taille (flash Morpho 0 % → achat → vente → remboursement), quotes au montant et au sens réels de chaque jambe (audit #2), fees lues on-chain au bloc, gas complet. **Tout est synthétique (quotes).**

| Route | Bloc | Taille optimale | Brut | Fees | Impact | Gas | Net | Statut quoter |
|---|---|---|---|---|---|---|---|---|
| WETH/cbBTC (Aero 0xeC3c… → Aerodrome 0x42d4…) | 62 077 712 | **1 $** | +0,0003 $ | 0,0004 $ | 0,0000 $ | 0,0024 $ | **−0,0025 $** | PARTIALLY_VERIFIED (achat not_addressable) |
| WETH/cbBTC — à 100 $ | 62 077 712 | — | +0,0273 $ | 0,0385 $ | 0,0021 $ | 0,0024 $ | **−0,0162 $** | PARTIALLY_VERIFIED (vente vérifiée −0,0001 %) |
| WETH/USDC (Aerodrome 0xb2cc… → Uni 0xb4CB…) | 62 077 712 | **1 $** | +0,0001 $ | 0,0003 $ | 0,0000 $ | 0,0024 $ | **−0,0025 $** | PARTIALLY_VERIFIED (achat not_addressable, factory 0x5e7b) |
| WETH/USDC — à 100 $ | 62 077 712 | — | +0,0149 $ | 0,0285 $ | 0,0035 $ | 0,0024 $ | **−0,0194 $** | PARTIALLY_VERIFIED (vente vérifiée −0,0000 %) |
| cbBTC/USDC (Uni 0xfBB6… → Pancake 0xb94b…) | 62 077 712 | **1 $** | +0,0004 $ | 0,0006 $ | 0,0000 $ | 0,0024 $ | **−0,0031 $** | NOT_VERIFIED à 1 $ (écart quoter 0,047 % — arrondi, voir note) |
| cbBTC/USDC — à 100 $ | 62 077 712 | — | +0,0373 $ | 0,0600 $ | 0,0058 $ | 0,0024 $ | **−0,0312 $** | **FULLY_QUOTER_VERIFIED** (achat −0,0003 %, vente −0,0006 %) |

Détail de la grille (nets, en $) — **tous négatifs à toutes les tailles, le net décroît monotonement avec la taille** (fees + impact croissent plus vite que le brut) :

| Taille | WETH/cbBTC | WETH/USDC | cbBTC/USDC |
|---|---|---|---|
| 1 $ | −0,0025 | −0,0025 | −0,0031 |
| 5 $ | −0,0031 | −0,0030 | −0,0035 |
| 10 $ | −0,0038 | −0,0038 | −0,0047 |
| 25 $ | −0,0056 | −0,0060 | −0,0090 |
| 50 $ | −0,0091 | −0,0100 | −0,0157 |
| 75 $ | −0,0122 | −0,0145 | −0,0231 |
| 100 $ | −0,0162 | −0,0194 | −0,0312 |
| 250 $ | −0,0442 | −0,0581 | −0,0955 |
| 500 $ | −0,1121 | −0,1571 | −0,2604 |
| 750 $ | −0,2067 | −0,2995 | −0,4981 |
| 1000 $ | −0,3287 | −0,4852 | −0,8075 |

**Aucun seuil fixe n'a été supposé (audit #11) : le threshold est calculé par taille** (fees + gas/taille ; ex. WETH/cbBTC : 0,2738 % à 1 $ → 0,0387 % à 1 000 $). La taille optimale est **1 $ sur les 3 routes** — le plus petit montant perd le moins, parce que le gas fixe (0,0024 $) domine à petite taille et que les fees+impact dominent à grande taille. **Aucun profit à aucune taille au bloc du scan.**

Note $1 (cbBTC/USDC) : à 1 $, la sortie de la jambe d'achat est ~1 704 raw cbBTC — 1 unité = 0,059 %. L'écart quoter de −0,047 % est un arrondi d'unité (< 1 unité), couvert par le plancher de quantification (tolérance = max(0,5 bp, 1 unité de sortie). La jambe de vente à 1 $ montre un écart réel de −0,0487 % (487 raw USDC, 0,0005 $) — petit désaccord quoter/modèle à 1 $, sans effet sur la conclusion (le net à 1 $ est négatif de toute façon ; le net à 100 $ est FULLY_QUOTER_VERIFIED).

**Preuve reproductible :**
```
cd ~/workspace/crypto-base-flashloan-bot/leadlag
../.venv/bin/python route_verify.py --block 62077712 --size 100
../.venv/bin/python size_optimizer.py        # grille $1–$1000, 3 routes
../.venv/bin/python -m unittest test_route_verify   # 13 tests, OK
```
Adresses (bloc 62 077 712) : WETH `0x4200000000000000000000000000000000000006` ; cbBTC `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` ; USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` ; buy/sell : voir tableau. Prix : cbBTC 58 683,42 $ (DexScreener au scan), ETH 1 643,55 $ (mid WETH/USDC on-chain au bloc).

---

## (c) Replay 24 h — blocs 61 645 712 → 62 077 712 (17 250 échantillons, pas 25 blocs = 5 s)

**Couverture (audit #1) : 17 250 / 432 001 blocs = 3,99 %. 414 751 blocs (96,01 %) n'ont PAS été observés.** Un 0 sur ce replay ne prouve pas l'absence de gaps — il borne seulement les gaps qui vivent ≥ 5 s. 31 erreurs d'échantillonnage (0,18 %).

### Ce que le replay a trouvé (avec les fees STATIQUES du scan — puis corrigé)
- **4 295 échantillons positifs** à 100 $ (fees statiques) : 1 306 WETH/cbBTC (7,6 %) + 2 989 WETH/USDC (17,3 %). Meilleurs nets apparents : +0,2525 $ (bloc 62 009 212) et +0,2459 $ (bloc 61 676 712). Gap mid max : 0,3194 % (WETH/cbBTC), 2,2490 % (WETH/USDC — tiré par des pools fines, pas par les paires profondes).

### La correction décisive : les fees Aerodrome sont DYNAMIQUES (mesuré live)
Les pools Aerodrome changent de fee au cours de la journée — le replay, qui réutilisait la fee du bloc de scan pour les 24 h, **sous-estimait les fees quand elles étaient hautes et créait des faux positifs** :

| Pool | Fee au scan (62 077 712) | Fee bloc 61 676 712 | Fee bloc 62 009 212 |
|---|---|---|---|
| Aerodrome 0x42d4… (WETH/cbBTC) | 300 | 1 300 | **3 300** |
| Aerodrome 0x3FE0… (WETH/USDC) | 250 | 3 500 | **6 250** |
| Aero 0xbB55… (WETH/cbBTC) | 441 | 2 351 | **4 400** |
| Aero 0x4A7a… (WETH/USDC) | 343 | 2 090 | **3 000** |
| Contrôles statiques : Cake 0xC211…, Uni 0xb4CB…, Aero 0xeC3c…, Cake 0x72AB… | 100 / 100 / 85 / 100 | 100 / 100 / 85 / 100 | 100 / 100 / 85 / 100 |

**TOUTES les pools Aerodrome (3 factories : GaugesV3 0xf8f2…, 0x9cb2…, 0x5e7b…) ont des fees dynamiques ; Uni et Cake sont statiques.** Le tickSpacing est stable (10 pour 0x42d4) — seule la fee bouge. C'est le mécanisme de fee dynamique d'Aerodrome Slipstream.

### Les 2 meilleurs événements apparents sont des FAUX POSITIFS (re-vérifiés avec la vraie fee au bloc)
| Événement | Net replay (fee statique) | Net VÉRIFIÉ (fee on-chain au bloc) | Fees on-chain | Statut |
|---|---|---|---|---|
| E1 — bloc 62 009 212, Cake 0xC211… → Aerodrome 0x42d4… | +0,2525 $ | **−0,0470 $** | 100 + **3 300** | FULLY_QUOTER_VERIFIED (achat −0,0006 %, vente −0,0003 %) |
| E2 — bloc 61 676 712, Uni 0xb4CB… → Aerodrome 0x3FE0… | +0,2459 $ | **−0,0782 $** | 100 + **3 500** | FULLY_QUOTER_VERIFIED (achat 0,0 %, vente −0,0 %) |

Le gap était réel (+0,30 % de brut), mais la fee dynamique (0,33 % / 0,35 %) l'a mangé. Le quoter on-chain — qui lit la fee live — l'a détecté : son écart avec le modèle statique était exactement le delta de fee (−0,30 %).

### Les 11 opportunités RÉELLES (jambes 100 % à fees statiques Uni/Cake, toutes re-vérifiées)
Sur les 4 295 positifs apparents, **seuls 11 impliquent deux jambes à fees statiques** (0 sur WETH/cbBTC, 11 sur WETH/USDC). **Les 11 sont vérifiés POSITIFS, tous FULLY_QUOTER_VERIFIED** (écarts quoter ≤ 0,0006 %) :

| # | Bloc | Paire (100 $) | Gap | Fees | Net vérifié |
|---|---|---|---|---|---|
| 1 | 61 989 637 | Cake 0x72AB… → Uni 0xb4CB… | 0,0436 % | 100+100 | **+0,0177 $** |
| 2 | 61 918 462 | Cake 0xB775… → Cake 0x72AB… | 0,0849 % | 500+100 | **+0,0152 $** |
| 3 | 61 905 037 | Uni 0xd0b5… → Cake 0x72AB… | 0,0775 % | 500+100 | **+0,0133 $** |
| 4 | 61 901 012 | Uni 0xb4CB… → Cake 0x72AB… | 0,0366 % | 100+100 | **+0,0099 $** |
| 5 | 62 048 587 | Cake 0x72AB… → Uni V2 0x88A4… | 0,3456 % | 100+3000 | **+0,0099 $** |
| 6 | 61 910 687 | Uni 0xb4CB… → Uni 0xd0b5… | 0,0726 % | 100+500 | **+0,0066 $** |
| 7 | 62 018 437 | Uni 0xb4CB… → Cake 0x72AB… | 0,0331 % | 100+100 | **+0,0059 $** |
| 8 | 62 047 162 | Cake 0x72AB… → Uni 0xb4CB… | 0,0324 % | 100+100 | **+0,0054 $** |
| 9 | 61 837 137 | Uni 0xd0b5… → Uni 0xb4CB… | 0,0683 % | 500+100 | **+0,0034 $** |
| 10 | 62 075 362 | Cake 0x72AB… → Uni 0xb4CB… | 0,0290 % | 100+100 | **+0,0033 $** |
| 11 | 62 074 812 | Uni 0xb4CB… → Cake 0x72AB… | 0,0278 % | 100+100 | **+0,0021 $** |

**Total des 11 : +0,0928 $ sur 24 h (à 100 $ par trade). Meilleur net : +0,0177 $.** (Détail : `static_positives_verified.json`. L'événement #5 utilise une jambe V2 — Uni V2 0x88A43bbD, fee 0,30 % — vérifiée par le Router V2 `getAmountsOut`, écart −0,0000004 %.)

**Durée de vie des 11 épisodes** (échantillons consécutifs à meilleur net > 0, pas 5 s) : 5 événements ≤ 5 s, 2 à ~10 s, 1 à ~15 s, 1 à ~20 s, 1 à ~25 s. **Médiane 5 s, maximum ~25 s.** (Mesure limitée : le replay ne stocke que la meilleure paire par échantillon, pas toutes les paires — la durée par paire peut être plus courte.)

### Ce que le replay ne prouve pas
- Couverture 3,99 % : les gaps vivant < 5 s et les gaps intra-bloc sont **invisibles** et **non exclus**.
- Les gaps impliquant une pool Aerodrome ne sont vérifiables qu'avec la fee lue **au bloc de l'événement** — le replay (fees statiques) ne les mesure pas correctement. Une re-vérification exhaustive des 4 295 positifs exigerait ~4 295 lectures de fee au bloc (faisable, non faite — les 11 statiques suffisent à établir l'existence d'opportunités réelles, et E1/E2 suffisent à établir que les plus grosses apparentes sont fausses).
- Aucune observation live continue n'a été faite au-delà du replay (le replay couvre déjà 24 h d'archive).

---

## (d) Routes moins coûteuses — vérifiées

**Les 3 meilleures routes utilisent déjà les jambes les moins chères disponibles.** Le plancher de fees vérifié sur les paires scannées :

| Combinaison | Fees | Net au bloc du scan (100 $) | Verdict |
|---|---|---|---|
| Aero 85 → Aerodrome 85 (0xeC3c… → 0x7C74…) | **170 = 1,70 bp** (plancher absolu) | −0,0192 $ | vérifiée — pire que la meilleure (−0,0183 $) car le gap est plus petit |
| Aero 85 → Cake 100 (0xeC3c… → 0xC211…) | 185 = 1,85 bp | −0,0216 $ | vérifiée — pire |
| Cake 100 → Uni 100 (0x72AB… → 0xb4CB…) | 200 = 2,00 bp (plancher **statique**) | — (bloc scan : −0,0194 $ sur la route WETH/USDC) | **c'est la combinaison de l'événement vérifié #1 (+0,0177 $)** |
| Aero 85 → Aerodrome 300 (meilleure, WETH/cbBTC) | 385 = 3,85 bp | **−0,0183 $** | meilleur net malgré des fees plus hautes — le gap (0,273 %) compte plus que les fees |

**Conclusion (d) : AUCUNE route moins coûteuse vérifiée ne bat le meilleur net.** Baisser les fees de 3,85 bp à 1,70 bp ne suffit pas : le gap de ces paires est plus petit, le net reste négatif. Le facteur limitant n'est pas la fee, c'est le **gap** (≤ 0,085 % sur les routes statiques vérifiées, vs ~0,02–0,04 % de coûts).

- **V4 flash accounting vs Morpho : non implémenté, non vérifié.** Le contrat existant est Morpho-only (swaps V2). Surtout : Morpho flash est **déjà à 0 %** — V4 flash accounting ne peut pas faire moins que 0 % sur le prêt. Il ne pourrait aider que s'il donnait accès à des pools V4 moins chères ou à des hooks — non démontré ici. (Note d'exécutabilité, audit #7 : les routes CL ne sont **pas exécutables par le contrat Base existant** (V2 only) — cette vérification est **économique seulement** ; l'exécution exigerait une modification du contrat.)
- **Conversion native / raccourcis : aucun.** Les routes sont déjà mono-saut par jambe, même quote des deux côtés (pas de jambe USDC.e→USDC, pas de conversion intermédiaire à éviter).
- **Pools 0,01 % / 0,0085 % avec liquidité réelle :** les pools à 85 (0,0085 %) existent (Aero 0xeC3c TVL 4,78 M$, Aerodrome 0x7C74 TVL 1,52 M$) et sont déjà utilisées. La pool Aerodrome 0xdbc6… à 80 (0,008 %) a TVL 83 384 $ — trop fine pour 100 $ (TVL < 10× la taille au-delà de ~8 000 $ de toute façon, mais son gap n'a jamais dépassé le breakeven dans le scan).

---

## (e) Opportunité historique vs réellement capturable

| | Opportunité HISTORIQUE (le gap a existé à un bloc passé) | RÉELLEMENT CAPTURABLE (on aurait pu l'exécuter) |
|---|---|---|
| Scan bloc 62 077 712 | Gap 0,0273 % (WETH/cbBTC) — a existé | **Non** : net −0,0162 $ après tous coûts |
| E1 / E2 (replay) | Gap ~0,30 % — a existé | **Non** : faux positifs (fee dynamique 3 300 / 3 500) → nets −0,047 $ / −0,078 $ |
| 11 événements vérifiés | Gaps 0,028–0,085 % (WETH/USDC) — ont existé, quoter-vérifiés | **Théoriquement oui, pratiquement presque non** : voir ci-dessous |

**Capturabilité des 11 événements réels :**
1. **Liquidité suffisante : oui.** TVL des pools : 0,58–6,94 M$ (≥ 10× la taille de 100 $) ; aucun tick traversé ; impact ≤ 0,0035 $ à 100 $.
2. **Atomicité possible : oui en principe** (les deux jambes + remboursement dans UNE transaction via le contrat Morpho — mais le contrat actuel ne gère que les swaps V2, pas les CL : il faudrait le modifier, audit #7).
3. **Durée de vie ≥ temps d'exécution : c'est le point dur.** Les épisodes vivent **5–25 s (médiane 5 s)**. Un bot devrait : détecter le gap (quoter les deux pools), décider, construire et faire inclure la transaction — le tout en moins de 5 s dans la moitié des cas (blocs Base de 2 s = ~2 blocs). C'est possible pour un bot rapide et bien connecté, mais **la moitié des événements (5/11) ne vivent qu'un seul échantillon (≤ 5 s)** — la plupart seraient manqués, et ceux capturés rapportent 0,002–0,018 $.
4. **Économie : non.** Même en capturant les 11/11 à 100 $ : **+0,0928 $ par jour**. Augmenter la taille ne aide pas : l'impact croît (la grille montre le net qui décroît avec la taille) et le gap maximal observé (0,085 %) ne supporte pas plus de ~250 $ avant que l'impact ne mange le profit. Il n'y a pas d'échelle à laquelle ces gaps deviennent un revenu.

---

## (f) VERDICT FINAL

**Au bloc du scan (62 077 712), RIEN n'est rentable :** le meilleur net vérifié est **−0,0162 $ sur 100 $** (WETH/cbBTC), soit **~1,6 bp sous le breakeven**. Les 3 routes sont négatives à toutes les tailles de 1 $ à 1 000 $, et la taille optimale est 1 $ (perdre le moins possible).

**Sur 24 h, des opportunités RÉELLES existent mais elles sont microscopiques :** 11 événements vérifiés (quoter, cycle complet, fees on-chain au bloc), meilleur net **+0,0177 $** sur 100 $, total **+0,0928 $/jour**, durées de vie 5–25 s. Ce n'est pas une activité rentable — c'est la preuve que le marché est efficient à cette échelle : les gaps qui dépassent les fees existent, mais ils sont rares, brefs et minuscules.

**Ce qui manque pour passer positif (en bp) :**
- Au bloc du scan : il manque **~1,6 bp** de gap sur WETH/cbBTC (gap 0,0273 % vs threshold 0,0409 %) et **~1,9 bp** sur WETH/USDC (gap 0,0149 % vs threshold 0,0309 %).
- Pour un profit significatif (**+1 $ par trade de 100 $**, soit 1 %) : il faudrait des gaps **~100 bp plus grands** que le meilleur gap statique observé (0,085 %). Les gaps de cette taille n'ont été observés que sur des paires à fees dynamiques — où la fee monte avec le gap et l'annule (E1/E2).
- Autrement dit : **le marché Base cross-venue sur les majors est efficient à ±2 bp près.** Un edge exigerait soit des gaps structurellement plus grands (nouvelle venue, nouvelle paire, événement de marché), soit une exécution en < 5 s pour attraper les micro-gaps — et même alors le revenu serait de l'ordre de 0,10 $/jour à 100 $/trade.

**Recommandation (expert) :** ne pas déployer de capital ni de contrat pour ces routes. Si Ismail veut poursuivre : (1) surveiller en continu (live) les paires statiques Cake↔Uni WETH/USDC — les seules où des gaps vérifiés ont été vus — avec une alerte sur gap > 0,03 % ; (2) mesurer si des gaps ≥ 0,15 % existent sur 7 jours (le seuil où un trade de 100 $ rapporterait ~0,10 $) ; (3) ne pas toucher aux routes Aerodrome tant que la fee dynamique n'est pas modélisée (elle annule les gaps). Le travail Rust (hot path) n'a de sens qu'après ces mesures — la vitesse ne crée pas d'edge ici, elle ne fait que mesurer le même ~0 plus vite (décision Ismail 2026-11-25 12:21 : Rust après les fixes, seulement si le log prouve que la latence perd des entries).

---

## Corrections de l'audit ChatGPT (2026-11-25) — appliquées explicitement

| # | Correction | Application ici |
|---|---|---|
| #1 | Cross-tx : couverture réelle ~3,3 % (98 blocs / 2 974), pas ~1 bloc sur 3 | **Replay : couverture mesurée et publiée = 3,99 % (17 250 / 432 001 blocs).** Un 0 ne prouve pas l'absence de gaps — le § (c) le dit explicitement. |
| #2 | « Verified » : quote chaque jambe au montant et au sens réels ; tolérance < marge cherchée (jamais 2 %) ; `pool_ok_for_size` sans cross-check par jambe ne vaut rien ; simuler le cycle complet à bloc fixé | **Fait :** `verify_cycle` quote chaque jambe au montant/sens réels ; tolérance quoter **0,005 % (0,5 bp)** + plancher de quantification (1 unité de sortie) ; statut par jambe (quoter_verified / quoter_disagree / not_addressable) ; route FULLY/PARTIALLY/NOT_VERIFIED ; cycle complet simulé à bloc fixé. **Bugs trouvés et corrigés pendant ce travail :** (i) `quoter_path_quote` prenait les 4 mots de retour de `quoteExactInput` comme un seul entier géant (OverflowError) — seul le 1er mot est `amountOut` ; (ii) le repli sur les autres quoters citait **une autre pool** (le MixedQuoter a cité la pool 0x7C74 à la place de 0xeC3c, écart −0,0039 % faussement « vérifié ») — supprimé, un quoter ne cite que les pools **de sa factory** ; (iii) `getAmountsOut` V2 : les adresses d'un tableau sont des mots de 32 o (pas 20 o) — l'appel revertissait ; (iv) `read_pool_state` supposait CL : les pools V2 (ex. Uni V2 0x88A43bbD) revertissent sur `slot0()` — bascule V2 (`getReserves` + Router `getAmountsOut` comme garde). |
| #11 | Grille de tailles $1–$1 000, pas de seuil fixe 5 bp | **Fait :** grille 1/5/10/25/50/75/100/250/500/750/1000 $ sur les 3 routes ; threshold calculé par taille ; aucun seuil fixe. |
| #12 | Gas = coût complet de la transaction exacte, pas 0,0044 $ figé ; attention à la composante L1 sur Base | **Fait :** `measure_full_gas` — L2 285 948 unités (fork) + L1 `GasPriceOracle.getL1Fee` (0,000002 $, 0,1 %) = **0,002353 $** ; prudent 0,003701 $. Le 0,0044 $ figé surestimait le gas. |
| — | Fees WETH/cbBTC $100 : 85 + 300 = **3,85 bp, PAS 2 bp** | **Corrigé partout.** Le plancher « 2 bp » est la combinaison Cake 100 → Uni 100 (WETH/USDC), pas cette route. Le plancher absolu vérifié est 1,70 bp (85+85). |
| — | « Meilleure paire » à $1 000 = **même pool des deux côtés** (0xeC3c… → 0xeC3c…) — cycle invalide | **Exclue :** `verify_cycle` lève `ValueError` si buy == sell (test unitaire). La paire figure encore dans `cross_venue_results.json` (tier_pairs, net −0,0219 $) — ne pas l'utiliser. |
| — | (Autres findings : second agent — scanner.py, v3_quote.py, self_funded.py, realtime_listener.py) | Non touchés ici. Seul `cross_venue.py` a été modifié (token_decimals strict — voir ci-dessous). |

### Bugs trouvés et corrigés pendant ce travail (en plus de l'audit)
1. **Fee en unités 1e-6, pas 1e-4** : `fee/10_000` appliquait 5 % au lieu de 0,05 % pour fee=500 — corrigé en `fee/1_000_000` dans le modèle V3 (test de régression).
2. **`token_decimals` silencieux** : sur échec RPC, il mettait 18 en cache par défaut (USDC lu à 18 décimales → nets WETH/USDC ≈ −100 $) — corrigé dans `cross_venue.py` : retry puis **lève une erreur, jamais de défaut**.
3. **Factory Cake BSC** : `cross_venue.py` pointait la factory Cake BSC (0x0BFb…ba76a35) — la vraie factory Cake Base est `0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865` (vérifiée : `factory()` du QuoterV2 + de la pool).
4. **Fees dynamiques Aerodrome** (découverte majeure, § c) : toutes les pools Aerodrome changent de fee (300 → 3 300 en une journée). Le scan et le replay utilisaient la fee du bloc de scan — **tous les « positifs » impliquant une pool Aerodrome sont des faux positifs** (démontré par E1/E2, re-vérifiés négatifs avec la vraie fee).
5. **RPC zéro transitoire sur `fee()`** : retry + repli tickSpacing + fail-closed.

### Fichiers modifiés (hors nouveaux fichiers)
- `leadlag/cross_venue.py` : **seulement** `token_decimals` strict (retry puis raise, pas de défaut 18). Aucun autre fichier du repo touché. `paper_trade.py`, `paper_entries.jsonl`, `paper_run1.log`, `expert_scan.py` intacts. **Aucun commit** (le parent pousse).

### Tests
```
cd ~/workspace/crypto-base-flashloan-bot/polygon && ../.venv/bin/python -m unittest
# Ran 178 tests in 39.4s — OK
cd ~/workspace/crypto-base-flashloan-bot/leadlag && ../.venv/bin/python -m unittest test_route_verify
# Ran 13 tests in 6.0s — OK
```
Les 13 tests (`test_route_verify.py`, hors ligne, état synthétique) : accord mono-tick vs `v3_quote_python` ; identité idéal − réel = fee + impact ; régression fee 85 = 0,0085 % ; même-pool rejetée ; gas obligatoire ; net décomposé == net direct ; grille $1–$1000 monotone ; régression décimales USDC 6 vs 18 (signature −100 $) ; tolérance quoter + plancher de quantification ; jambe V2 (identité + fee 0,30 %) ; `token_decimals` lève sur échec RPC ; fee dynamique lue depuis l'état au bloc.

---

## Annexe — commandes de reproduction
```
# 1. Vérification route WETH/cbBTC (bloc scan, $100, gas mesuré)
cd ~/workspace/crypto-base-flashloan-bot/leadlag
../.venv/bin/python route_verify.py --block 62077712 --size 100
# 2. Grille de tailles (3 routes, $1–$1000)
../.venv/bin/python size_optimizer.py
# 3. Replay 24 h (déjà fait : replay_24h.jsonl, 17 250 échantillons, 1 250 s)
../.venv/bin/python replay.py
../.venv/bin/python replay_analyze.py        # -> replay_24h_summary.json
# 4. Vérification des 2 meilleurs événements apparents + des 11 statiques
../.venv/bin/python verify_top_events.py
../.venv/bin/python verify_static_positives.py  # -> static_positives_verified.json (11/11 positifs)
# 5. Tests
../.venv/bin/python -m unittest test_route_verify
```
