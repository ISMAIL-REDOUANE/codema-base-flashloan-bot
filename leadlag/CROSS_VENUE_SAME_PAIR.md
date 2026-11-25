# Cross-venue same-pair — scan Base (Uni + Aerodrome + Pancake + TOUT)

**Date :** 2026-11-25, scan same-block à **11:30:32 UTC, bloc 62 077 712** · cross-tx 11:35–11:45 UTC, blocs 62 080 784 → 62 083 757
**Fichiers :** `cross_venue.py` · `cross_venue_results.json` (corrigé, original brut : `cross_venue_results_raw.json`) · `cross_venue_verify.py` (post-traitement de vérification) · `cross_venue_crosstx.py` · `cross_venue_crosstx.json`
**Lecture seule.** Aucun broadcast, aucun wallet, aucun fonds. Tous les « net » ci-dessous sont des **nets synthétiques** (quotes analytiques / quoter on-chain, jamais exécutés, jamais des profits). Les prix, gaps et volumes sont des **mesures live**.

---

## 1. Verdict en une phrase

**0 écart RÉEL vérifié.** Sur 29 groupes (même token, même quote, ≥ 2 pools), 127 pools comparées au même bloc, **aucune paire ne donne un net > 0 $** après tous les coûts, à aucune taille ($100 / $500 / $1 000). Le meilleur net vérifié est **−0,0183 $** (WETH/cbBTC, 100 $). Le seul net analytique positif (+2,085 $ sur AMZNc) est un **artefact démonté** (voir §5.1).

C'est la confirmation chiffrée du diagnostic d'Ismail (11:40) : **« kynin foras wlkin kykono 9al mn fees »** — les écarts existent, mais ils sont plus petits que les frais. Le plus grand écart liquide mesuré est 0,27 % (WETH/cbBTC) ; le meilleur écart *exécutable* par paire est ~0,027 % contre un breakeven de 0,043 % → net −0,02 $.

---

## 2. Réponse directe : pourquoi on ne l'avait jamais trouvé — et pourquoi DexScreener montre des gros écarts

**Pourquoi on ne l'avait jamais trouvé : on ne l'avait jamais cherché.** Tous nos scanners précédents cotaient UNE seule pool par paire, sur Uniswap V3 uniquement — soit 6,6 % du volume top-20 de Base. Aerodrome Slipstream = 78,9 %, PancakeSwap V3 = 14,2 %. On ne comparait jamais la même paire à travers plusieurs venues au même bloc. C'est dit plainement : ce n'était pas un bug de détection, c'était une absence de couverture. Ce scan corrige ça : 12 venues, 115 pools CL + 12 pools V2, quotes au même bloc.

**Pourquoi DexScreener montre un gros écart pour le même nom — les 5 causes, avec des exemples concrets de CE scan :**

| Cause | Exemple mesuré | Ce que ça vaut vraiment |
|---|---|---|
| **(a) Pool morte / vide (prix fossile)** | SPCXc : une pool Uni à **TVL 0,31 $, mid 2,9e-37, prix DS 6,45e-27** → écart brut **4,28e37 %**. WETH/xStock : pool aero TVL 0,37 $, mid 3,4e48 → écart brut **1,57e28 %**. | Rien. Le prix d'une pool sans liquidité est du bruit. Les 3–4 pools liquides du même groupe sont d'accord à 0,08 % près. |
| **(b) Pool stale / fine (V2 non repricée)** | AERO/USDC.e : pool Equalizer V2 à **0,9027 contre 0,9996** sur les pools CL → écart brut 10,8 %. | Artefact. La V2 est exclue (écart > 5 % vs médiane CL) ; l'écart liquide réel est **0,0057 %**. |
| **(c) Quote token différent (pas la même paire)** | WETH apparaît en 5 groupes différents : /USDC, /cbBTC, et 3 fois /xStock (MSTRc, AMZNc…). Deux « WETH » à des prix différents = deux paires différentes. | Ne pas comparer. Le scan ne compare que même adresse token + même quote. |
| **(d) Token copycat (même nom, autre adresse)** | **7 symboles avec des copycats** : NVDAc (2), PROS (2), MSTRc (2), SPCXc (2), ANTc (**6**), ELSA (2), AERO (1 — un faux AERO `0x940181a9…`). | Le « même nom » sur DexScreener peut être un autre contrat. Le scan groupe par adresse contrat, jamais par nom. |
| **(e) Différence de fee tier uniquement** | WETH/USDC : pool Aerodrome **2 % de fee à 1 663,89 $** contre 1 643–1 644 $ ailleurs → écart 1,28 %. | L'écart existe mais la fee le mange : net −0,02 $ au mieux. Voir §6. |

**Et le cas qui ressemble le plus à ce qu'Ismail a vu :** AMZNc, écart brut 2,88 % entre 5 pools — dont une à **252,33 $** contre 245,26–247,66 $ pour les autres. Cette pool (Aerodrome `0x22Cf9B71…`) a une **TVL de 1,38 $** et détient **0,05 $ d'USDC + 0,0053 AMZNc** (vérifié live on-chain). Son prix est « vrai » mais inexécutable : on ne peut pas vendre 100 $ dans une pool qui contient 1,38 $. Le net analytique +2,085 $ est un artefact du modèle (voir §5.1). **C'est très probablement ce type d'écart qu'Ismail a vu sur DexScreener : un gros chiffre porté par une micro-pool.**

---

## 3. Méthode (ce qui a été mesuré, et comment c'est vérifié)

- **Sélection :** top 17 tokens Base par volume 24 h (GeckoTerminal) + WETH/cbBTC ajoutés. 133 groupes (token, quote) trouvés, 39 multi-pools, **29 groupes retenus** (≥ 2 pools avec un prix on-chain lisible).
- **Same-block :** toutes les lectures on-chain au **bloc 62 077 712** (slot0 / globalState / réserves). 127 pools après déduplication.
- **Types de pools détectés dans l'ordre :** (1) `slot0()` → Uni V3 / Pancake / Aerodrome Slipstream CL ; (2) `globalState()` → Algebra CLAMM (QuickSwap V4, Hydrex — elles exposent aussi une vue `getReserves`, donc la V2 doit être testée EN DERNIER sinon elles sont mal classées) ; (3) `getReserves()` → V2 standard.
- **Quotes :** prix d'exécution (pas mid) aux tailles 100 $ / 500 $ / 1 000 $. CL : modèle analytique mono-tick (fee réelle du tier + impact). V2 : formule x·y=k sur les réserves.
- **Net :** buy-leg (fee + impact) + sell-leg (fee + impact) + gas **0,0044 $** + flash Morpho **0 %**. Règle d'Ismail : net > 0 $.
- **Vérification (post-traitement, `cross_venue_verify.py`) — un net ne compte comme RÉEL que si, pour LES DEUX jambes :** TVL ≥ 10× la taille du trade ; pool non exclue (V2 dont le mid dévie > 5 % de la médiane CL) ; et pour les jambes Uni/Pancake, le **quoter on-chain officiel doit confirmer** la quote analytique à ±2 %. Le quoter Aerodrome n'est PAS utilisé pour valider (voir ci-dessous).
- **Validation du modèle :** les quoters Uni V3 et Pancake V3 confirment le modèle analytique à **~1e-6 %** sur les pools liquides (ex. Uni WETH/USDC 0,05 % : quoter vs analytique = 0,0000009 %). Le modèle est bon ; ce qui casse, c'est la liquidité réelle des micro-pools.
- **Limite connue du quoter Aerodrome :** le MixedQuoterV3 adresse (factory, tickSpacing), pas une pool. Deux pools du même couple + même tickSpacing retournent des valeurs **identiques au chiffre près** (AMZNc : 246,35677136344947 pour deux pools différentes). Les checks Aerodrome ne sont valables que pour les pools de la factory GaugesV3 (`0xf8f2…`) ; les pools « aero » viennent d'une 4ᵉ factory (`0x9cb2…`, non auditée) que le quoter ne peut pas adresser. Le legacy QuoterV2 (`0x254c…`) revert sur ces pools.
- **Bugs trouvés et corrigés pendant le scan (honnêteté méthodologique) :**
  1. Adresses `0x0x…` (préfixe double) dans la sélection GeckoTerminal → top-15 vide au 1er run.
  2. Décimales du quote codées en dur à 6 → prix faux ×100 sur les quotes WETH/cbBTC.
  3. Parsing du 1er mot de retour quoter (`raw[2:32]` = 15 octets au lieu de 32) → tous les cross-checks quoter « échouaient ».
  4. Pools CLAMM (QuickSwap V4, Hydrex) mal classées V2 via `getReserves` → prix faux (ex. 977 $ au lieu de 1 647 $) ; corrigé par la détection `globalState()` en priorité.
  5. **Bug d'unité de fee** : `v3_quote_python` attend des basis points vrais (10000 = 100 %) alors que la fee on-chain est en centièmes de bip (500 = 0,05 %). Passer 500 tel quel appliquait 5 % de fee. Corrigé (÷100). Les nets du 1er run (buggé) étaient donc surévalués en coûts — le verdict 0 n'en est que plus solide.
  6. Doublons : la même pool apparaissait 2× par groupe (listée sous les deux tokens) → 21 lignes dédupliquées.
  7. Les pools V2 n'ont PAS de `getAmountOut` (c'est le router qui l'a) — la V2 se quote par les réserves uniquement.

---

## 4. Table des écarts (bloc 62 077 712, mesures live ; nets = quotes synthétiques)

`mid_gap` = écart brut entre les mids extrêmes (toutes pools). `liq_gap` = écart entre pools liquides seulement (TVL ≥ 100 $, ≥ 1 txn/24 h, V2 exclues si déviantes). `net` = meilleur net analytique ; `ver100` = meilleur net VÉRIFIÉ à 100 $ (règles §3).

| Token | Quote | Pools | Écart brut | Écart liquide | Net 100 $ | Net 500 $ | Net 1 000 $ | Vérifié 100 $ | Classe |
|---|---|---|---|---|---|---|---|---|---|
| WETH | cbBTC | 11 | 0,273 % | 0,273 % | −0,0183 $ | −0,085 $ | −0,176 $ | −0,0183 $ | ARTIFACT |
| WETH | USDC | 18 | 1,281 % | 1,281 % | −0,0215 $ | −0,125 $ | −0,289 $ | −0,0215 $ | ARTIFACT |
| cbBTC | USDC | 9 | 0,267 % | 0,267 % | −0,0332 $ | −0,199 $ | −0,425 $ | −0,0332 $ | ARTIFACT |
| MSTRc | USDC | 4 | 1,853 % | 0,178 % | −0,0703 $ | −1,95 $ | −7,92 $ | −0,0703 $ | ARTIFACT |
| AERO | USDC.e | 4 | 10,795 % | 0,006 % | −0,0892 $ | −0,439 $ | −0,900 $ | −0,0892 $ | ARTIFACT |
| METAc | USDC | 4 | 0,113 % | 0,113 % | −0,111 $ | −1,49 $ | −5,33 $ | −0,111 $ | ARTIFACT |
| AMZNc | USDC | 5 | 2,881 % | 0,978 % | **+2,085 $** | −3,17 $ | −12,10 $ | −0,170 $ | ARTIFACT (voir §5.1) |
| NVDAc | USDC | 7 | 5,316 % | 2,475 % | −0,204 $ | −1,44 $ | −3,97 $ | −0,204 $ | ARTIFACT |
| GOOGLc | USDC | 7 | 0,793 % | 0,793 % | −0,253 $ | −2,53 $ | −7,42 $ | −0,253 $ | ARTIFACT |
| WETH | NVDAc | 3 | 0,035 % | 0,035 % | −0,262 $ | −2,01 $ | −4,91 $ | −0,262 $ | ARTIFACT |
| TSLAc | USDC | 2 | 0,002 % | 0,002 % | −0,313 $ | −5,77 $ | −21,90 $ | −0,313 $ | ARTIFACT |
| MSTRc | cbBTC | 2 | 0,272 % | 0,272 % | −0,384 $ | −7,76 $ | −29,78 $ | −0,384 $ | ARTIFACT |
| ANTc | USDC | 3 | 0,451 % | 0,451 % | −0,681 $ | −4,86 $ | −13,38 $ | −0,681 $ | ARTIFACT |
| ELSA | USDC | 4 | 6,469 % | 6,418 % | −0,739 $ | −10,69 $ | −38,36 $ | −0,739 $ | ARTIFACT |
| VIRTUAL | cbBTC | 1* | 0,000 % | — | −0,973 $ | −12,08 $ | −41,67 $ | −0,973 $ | ARTIFACT (1 seule pool) |
| SPCXc | USDC | 6 | 4,28e37 % | 0,081 % | −1,047 $ | −14,63 $ | −47,80 $ | −1,047 $ | ARTIFACT (pool morte) |
| AERO | USDC | 3 | 0,206 % | 0,206 % | −1,058 $ | −5,32 $ | −10,77 $ | −1,058 $ | ARTIFACT |
| MUc | USDC | 4 | 5,771 % | 5,771 % | −1,707 $ | −22,10 $ | −76,13 $ | −1,707 $ | ARTIFACT |
| SNDKc | USDC | 4 | 4,320 % | 0,474 % | −1,939 $ | −33,74 $ | −121,38 $ | −1,939 $ | ARTIFACT |
| AERO | cbBTC | 2 | 0,091 % | 0,091 % | −3,020 $ | −59,74 $ | −210,37 $ | −3,020 $ | ARTIFACT |
| WETH | AMZNc | 2 | 0,066 % | 0,066 % | −7,131 $ | −138,48 $ | −433,71 $ | −7,131 $ | ARTIFACT |
| AERO | WETH | 4 | 0,393 % | 0,393 % | −12,32 $ | −201,31 $ | −572,79 $ | −12,32 $ | ARTIFACT |
| PROS | USDC | 6 | 2,717 % | 1,811 % | −5,446 $ | −116,74 $ | −378,52 $ | aucun | ARTIFACT |
| AMZNc | USDC.e | 2 | 0,576 % | — | −25,32 $ | −315,76 $ | −774,39 $ | aucun | ARTIFACT |
| WETH | TSLAc | 2 | 0,587 % | — | −49,34 $ | −415,09 $ | −907,25 $ | aucun | ARTIFACT |
| AERO | SPCXc | 2 | 0,328 % | — | −57,89 $ | −436,48 $ | −932,17 $ | aucun | ARTIFACT |
| WETH | MSTRc | 2 | 0,043 % | — | −71,28 $ | −462,56 $ | −961,09 $ | aucun | ARTIFACT |
| AMDc | USDC | 2 | 7,843 % | — | −99,69 $ | −499,69 $ | −999,69 $ | aucun | ARTIFACT |
| WETH | GOOGLc | 2 | 1,57e28 % | — | — | — | — | aucun | ARTIFACT (pool morte) |

\* VIRTUAL : 2 lignes identiques dédupliquées → 1 pool unique, aucune comparaison possible. « Aucun » = aucune paire ne passe les règles de vérification (TVL < 10× la taille, typiquement).

**Lecture :** les écarts liquides sur les majors sont de 0,03–0,27 % ; sur les xStocks (NVDAc, ELSA, MUc) de 2,5–6,4 % — mais les nets restent négatifs partout, et de plus en plus négatifs quand la taille augmente (l'impact mange l'écart : AMZNc +2,09 $ à 100 $ → −12,10 $ à 1 000 $ ; ELSA −0,74 $ → −38,36 $).

---

## 5. Top 3 écarts — il n'y a pas de top 3 RÉEL

### 5.1 AMZNc/USDC — le faux positif (+2,085 $ analytique → −0,170 $ vérifié) — CAS D'ÉCOLE

- **La paire :** acheter sur Aero `0x532e0F46…` (fee 158 = 0,0158 %, TVL 1 437 824 $, vol 13,6 M$/j, 9 705 txns, mid 245,26 $) → vendre sur Aerodrome `0x22Cf9B71…` (fee 100 = 0,01 %, **TVL 1,38 $**, vol 9,97 $/j, 11 txns, mid 252,33 $). Net analytique +2,085 $ à 100 $.
- **Pourquoi c'est faux :** la pool de vente détient **0,05 $ d'USDC + 0,0053 AMZNc** (lu live on-chain, bloc 62 079 692). Sa liquidité est concentrée sur ~1 tick : le modèle mono-tick suppose que cette liquidité persiste sur tout le tick, alors qu'elle s'épuise après une fraction de tick. Le quoter on-chain (MixedQuoterV3, factory GaugesV3, tickSpacing 1) retourne **~0 AMZNc pour 100 $** — la pool ne peut pas exécuter le trade. Le net réel est ≈ −100 $ (on ne peut même pas vendre), pas +2,09 $.
- **Meilleure paire VÉRIFIÉE du groupe :** Aero `0x532e…` → Uni `0x7F030e…` (fee 10000 = 1 %, TVL 14 781 $) : net **−0,170 $** à 100 $. Les 3 pools liquides (245,26 / 245,30 / 247,66 $) sont d'accord à 0,98 % près — sous le breakeven.
- **Leçon :** un écart affiché par DexScreener porté par une micro-pool n'est pas un trade. Règle ajoutée : TVL ≥ 10× la taille sur chaque jambe, sinon le net ne compte pas.

### 5.2 WETH/cbBTC — le plus proche du breakeven (−0,0183 $ à 100 $)

- 11 pools, écart liquide 0,273 %. Meilleure paire vérifiée : **Aero `0xeC3c3755…` (fee 85 = 0,0085 %, TVL 4,78 M$) → Aerodrome `0x42d4a22C…` (fee 300 = 0,03 %, TVL 442 k$)**, threshold 0,0429 %, net **−0,0183 $** à 100 $ (−0,085 $ à 500 $, −0,176 $ à 1 000 $).
- L'écart entre ces deux mids n'est que ~0,027 % — sous le threshold de 0,043 %. Les quoters Uni/Pancake confirment le modèle à ~1e-6 % sur ce groupe. C'est le groupe à surveiller : il ne manque que ~0,02 % d'écart (ou ~2 bp de fees en moins) pour passer positif.

### 5.3 WETH/USDC — le plus liquide, le plus serré (−0,0215 $ à 100 $)

- 18 pools, écart liquide 1,281 % — mais tiré par la pool Aerodrome **2 % de fee à 1 663,89 $** (TVL 60 743 $, 73 txns). Le cœur liquide (Uni 0,01 % / 0,05 %, Pancake 0,01 %, Aero 0,0085 %) est à 1 642,86–1 644,13 $ (0,08 %).
- Meilleure paire vérifiée : **Aerodrome `0xb2cc224c…` (fee 185) → Uni `0xb4CB8009…` (fee 100 = 0,01 %)**, threshold 0,0329 %, net **−0,0215 $** à 100 $. La pool à 2 % n'est pas arbitrable : sa fee (2 %) dépasse son écart (1,28 %).

---

## 6. MULTI-TIER (instruction Ismail 11:19) — 0,05 % vs 0,01 % vs 0,3 %, entre venues ET dans la même venue

**519 paires de tiers vérifiées à 100 $, toutes négatives.** Meilleur net : −0,0183 $ (WETH/cbBTC). Le threshold par paire de tiers = (fee achat + fee vente) + gas/taille, en % (avant impact ; l'impact est dans le net).

### 6.1 Cross-venue — top 10 paires de tiers vérifiées à 100 $ (toutes WETH/cbBTC ou WETH/USDC)

| Achat | Vente | Threshold | Net 100 $ |
|---|---|---|---|
| Aero 0,0085 % | Aerodrome 0,03 % | 0,0429 % | **−0,0183 $** |
| Aero 0,0085 % | Aerodrome 0,0085 % | 0,0214 % | −0,0192 $ |
| Aerodrome 0,0185 % | Uni 0,01 % | 0,0329 % | −0,0215 $ |
| Aero 0,0085 % | Pancake 0,01 % | 0,0229 % | −0,0216 $ |
| Pancake 0,01 % | Aerodrome 0,03 % | 0,0444 % | −0,0218 $ |
| Aero 0,0085 % | Aero 0,0085 % | 0,0214 % | −0,0219 $ |
| Aerodrome 0,0085 % | Aerodrome 0,03 % | 0,0429 % | −0,0219 $ |
| Aerodrome 0,0185 % | Pancake 0,01 % | 0,0329 % | −0,0221 $ |
| Pancake 0,01 % | Aerodrome 0,0085 % | 0,0229 % | −0,0227 $ |
| Aerodrome 0,0085 % | Aerodrome 0,0085 % | 0,0214 % | −0,0228 $ |

**Lecture :** les thresholds les plus bas du marché sont ~0,021 % (deux jambes à ~0,01 %). Même à ce threshold, le meilleur net est −0,019 $ : l'écart de prix entre les deux pools (~0,02 %) ne couvre pas le threshold + l'impact. **Baisser les fees est le seul levier $0 qui reste** (deep search fees 11:44 : router les deux jambes en 0,01 % → breakeven ~2 bp à 1 000 $ ; mais les pools 0,01 % sont fines et l'impact reste à mesurer en live — ce scan le mesure : il mange les ~2 bp restants).

### 6.2 Même venue — les tiers d'Uni V3 WETH/USDC se parlent-ils ? Non.

| Achat (Uni) | Vente (Uni) | Threshold | Net 100 $ |
|---|---|---|---|
| 0,05 % | 0,01 % | 0,0644 % | −0,0372 $ |
| 0,01 % | 0,05 % | 0,0644 % | −0,0937 $ |
| 0,3 % | 0,01 % | 0,3144 % | −0,2579 $ |
| 0,3 % | 0,05 % | 0,3544 % | −0,3257 $ |
| 0,01 % | 0,3 % | 0,3144 % | −0,3722 $ |

Les trois tiers Uni (0,01 / 0,05 / 0,3 %) sont d'accord à ~0,03 % près (mids 1 643,33 / 1 643,80 / 1 642,86 $). Aucun écart intra-venue. La pool 0,3 % est la plus éloignée du marché (−0,03 %) mais son threshold (0,31 %) est 10× l'écart.

### 6.3 Thresholds par tier (rappel, avant impact)

| Paire de tiers | Threshold à 100 $ | à 500 $ | à 1 000 $ |
|---|---|---|---|
| 0,01 % + 0,01 % | 0,0244 % | 0,0209 % | 0,0204 % |
| 0,0085 % + 0,03 % | 0,0429 % | 0,0394 % | 0,0389 % |
| 0,05 % + 0,01 % | 0,0644 % | 0,0609 % | 0,0604 % |
| 0,05 % + 0,05 % | 0,1044 % | 0,1009 % | 0,1004 % |
| 0,3 % + 0,01 % | 0,3144 % | 0,3109 % | 0,3104 % |
| 1 % + 0,01 % | 1,0144 % | 1,0109 % | 1,0104 % |

Le gas (0,0044 $) ne pèse que 0,0044 % à 100 $ et 0,0004 % à 1 000 $ : **le gas n'est pas le problème, les fees le sont** — et à 1 000 $, c'est l'impact qui domine (nets 5–10× pires qu'à 100 $).

---

## 7. CROSS-TX (instruction Ismail 11:19) — le même couple de pools sur des blocs consécutifs

**Question :** après un gros trade dans la pool A (bloc N), la pool B n'a pas encore repricé — quel écart apparaît, et combien de blocs survit-il ?
**Méthode :** 2 couples suivis en live, 10 min, 1 lecture par bloc (échantillonnage réel ~6 s ≈ 1 bloc sur 3, latence RPC — les durées en blocs sont donc des bornes basses arrondies ; un pic d'1 bloc peut être manqué, c'est dit).

| Couple | Blocs | |Écart| médian | p95 | Max | Blocs > threshold | Épisodes | Gros trades en A |
|---|---|---|---|---|---|---|---|
| WETH/cbBTC : Uni 0,05 % `0x7AeA…` vs Aero 0,0085 % `0xeC3c…` (thr 0,0589 %) | 62 080 784 → 62 083 757 (98 échantillons) | 0,0267 % | 0,0424 % | **0,0477 %** | **0** | **0** | **0** |
| WETH/USDC : Uni 0,3 % `0x6c56…` vs Aero 0,0343 % `0x4A7a…` (thr 0,3347 %) | 62 080 784 → 62 083 757 (98 échantillons) | 0,0695 % | 0,1247 % | **0,1610 %** | **0** | **0** | **0** |

**Résultat : en 10 minutes, l'écart n'a JAMAIS dépassé le breakeven, sur aucun des deux couples. 0 épisode, 0 bloc au-dessus du threshold, 0 gros trade d'1 bloc en A.** Les plus gros écarts observés (0,0477 % et 0,1610 %) restent sous leurs thresholds (0,0589 % et 0,3347 %). Il n'y a donc pas d'épisode à mesurer en durée de vie : **l'écart ne naît même pas** — ce n'est pas qu'il meurt en 1 bloc, c'est qu'il n'atteint jamais le niveau où il paierait. (Fenêtre de 10 min seulement ; un run de 7 j pourrait voir des pics — voir §9.)

---

## 8. Copycats & GoPlus

- **Copycats (même symbole, autre adresse contrat) :** NVDAc ×2, PROS ×2, MSTRc ×2, SPCXc ×2, ANTc **×6**, ELSA ×2, AERO ×1 (faux AERO `0x940181a9…`). Adresses complètes dans `cross_venue_results.json` (`copycats`). Le scan groupe par adresse contrat : ces tokens ne sont jamais mélangés aux vrais.
- **GoPlus :** couverture partielle — 1 seul token a retourné des données (buy_tax 0, cannot_sell_all 0 sur le token vérifié). Les autres requêtes n'ont pas abouti. **Aucun flag honeypot détecté sur le token vérifié ; les autres tokens ne sont pas couverts — à ne pas prendre comme un feu vert.**

---

## 9. Recommandation d'expert — cross-venue vs lead-lag, et quoi paper-trader ensuite

### Cross-venue ou lead-lag ?

**Cross-venue, clairement — mais pas pour trader maintenant, pour surveiller.**
- Lead-lag (validation terminée 11:13) : **0 ENTRY en 567 cycles**, signal 7–10× trop faible, corrélation ~0,1. Le signal n'existe pas sur les majors.
- Cross-venue : les écarts **existent et sont mesurables en continu** (0,027 % sur le meilleur couple, 0,27 % d'écart brut max). Le problème n'est plus « trouver un signal » mais « l'écart est ~2 bp trop petit » — un problème de fees et d'impact, pas de détection. C'est le seul jeu où le gap est quantifié et traquable.
- Le diagnostic d'Ismail est confirmé dans les deux jeux : l'argent est dans les fees, pas dans la vitesse. La deep search fees (11:44) conclut pareil : aucun mécanisme $0 « ne pas payer » n'existe ; le seul levier est de router les deux jambes en pools 0,01 % (breakeven ~2 bp à 1 000 $).

### Quoi paper-trader ensuite (7 jours, $0, lecture seule)

1. **Paire 1 : WETH/cbBTC — Uni 0,05 % `0x7AeA2E8A…` vs Aero 0,0085 % `0xeC3c3755…`.** Paires 2 : WETH/USDC — Uni 0,01 % `0xb4CB8009…` vs Pancake 0,01 % `0x72AB388E…` (les deux jambes à 0,01 %, threshold ~0,024 %).
2. **Grille de tailles : 25 $ / 50 $ / 100 $** (le $25 n'a pas été testé — le threshold y est plus favorable en % de gas, mais l'impact relatif est plus fort ; c'est la question ouverte).
3. **Loguer chaque écart > 2 bp** avec son net vérifié (règles §3 : TVL ≥ 10× taille, quoter Uni/Pancake ±2 %), 24/7, avec le quoter on-chain comme garde (pas le modèle analytique seul — l'affaire AMZNc).
4. **À corriger avant :** le quoter Aerodrome (tag factory — adresser la bonne pool par factory, sinon le check est invalide) et le garde-fou « TVL ≥ 10× taille + range » dans le modèle (fail-closed si la liquidité est sur ~1 tick).

### Critères GO / STOP (décidés d'avance, pas après coup)

- **GO** (passer à l'étape suivante : fork-test + audit) si en 7 jours : **≥ 5 nets vérifiés > 0 $** (tailles 25–100 $) OU un meilleur net vérifié **> +0,50 $**.
- **STOP** (abandonner le cross-venue flash-loan, pivot bug bounties) si en 7 jours : **0 net vérifié > 0 $** OU meilleur net vérifié **< −0,01 $** OU les écarts > threshold n'apparaissent qu'en dessous de 25 $ (inexploitables).
- **Si STOP :** le meilleur chemin $0 reste les **bug bounties / audit contests** (conclusion de l'étude experts + deep search fees).

### Ce que ce scan ne prouve pas

- Une fenêtre de 10 min (cross-tx) et un instantané (scan) : un pic d'1 bloc peut avoir été manqué (échantillonnage ~1 bloc sur 3). Le run 7 j / 24 h tranchera.
- 17 tokens seulement (top volume) : les micro-caps hors top-17 ne sont pas couvertes — ELSA (dans le top-15) montre que les gaps y sont plus gros (6,4 %) mais les nets pires (−0,74 $ à 100 $).
- Aucun trade réel n'a été exécuté : tous les nets sont synthétiques. Le premier trade réel reste bloqué sur : signal vérifié + audit + signature d'Ismail.

---

## 10. Limites & fichiers

- **Limites :** modèle analytique mono-tick (surestime les pools à liquidité ~1 tick — garde TVL ajouté, mais pas de simulation multi-tick complète) ; quoter Aerodrome non fiable par pool (tag factory) ; GoPlus partiel (1 token) ; échantillonnage cross-tx ~1 bloc sur 3 ; 17 tokens ; instantané + 10 min, pas 7 jours.
- **Fichiers (tous dans `~/workspace/crypto-base-flashloan-bot/leadlag/`) :**
  - `cross_venue.py` — le scan (same-block, 12 venues, CL + Algebra + V2, quoters Uni/Pancake/Aero)
  - `cross_venue_results.json` — résultats corrigés (29 groupes, 519 paires de tiers vérifiées à 100 $)
  - `cross_venue_results_raw.json` — résultats bruts avant vérification (le +2,085 $ AMZNc y figure encore comme REAL — ne pas l'utiliser)
  - `cross_venue_verify.py` — post-traitement : dédup, écart liquide, règles de vérification TVL/quoter, reclassification
  - `cross_venue_crosstx.py` + `cross_venue_crosstx.json` — observation 10 min, 2 couples, 98 échantillons
  - `CROSS_VENUE_SAME_PAIR.md` — ce rapport
