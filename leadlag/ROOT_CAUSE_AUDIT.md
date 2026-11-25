# ROOT-CAUSE AUDIT — Pourquoi NOUS trouvons 0 opportunité

**Date :** 2026-11-25, 11:01–11:15 UTC · **Contexte :** run de validation paper-trade
en cours (30 min, ETH/SOSO/AERO/ICNT, Base seulement), snapshot à 11:01–11:06 UTC
(run non terminé : 1 624 enregistrements analysés à 11:06, compteurs finaux
susceptibles de croître — le run se termine ~11:13). **Attention :** les
compteurs OPPORTUNITY sont **par cycle**, pas par mouvement distinct — un
mouvement persistant est compté à chaque cycle où il dépasse le seuil
(19 enregistrements = 13 événements distincts, voir § SOSO).
**Fichiers d'analyse :** `leadlag/audit_checks.py`,
`leadlag/audit_checks2.py` (reproductibles, lecture seule).

**Comment lire ce rapport :** chaque nombre est étiqueté **LIVE** (mesuré sur nos
logs / appels lecture seule) ou **SYNTHÉTIQUE** (recalculé / reconstruit avec le
modèle mono-tick du repo — jamais un trade exécuté, jamais un profit réel).

## Verdict en une phrase

**Le 0 est à ~70 % une absence réelle (le marché est efficient à l'échelle
2–4 s / 0,1 % pour les venues qu'on regarde) et à ~30 % notre propre
cécité — mais la cécité est dans OÙ on regarde (6,6 % du volume top-20)
et QUEL signal on utilise (plafond de prédiction 4–13× sous les seuils),
pas dans la vitesse ni dans la sévérité des seuils.**

---

## Cause n° 1 — LE SIGNAL EST STRUCTURELLEMENT TROP FAIBLE (le modèle ne peut jamais déclencher d'entrée)

**Hypothèse :** la prédiction de mouvement issue de l'imbalance Binance est
plus petite que le seuil minimal de chaque pool — donc le système ne peut
mathématiquement jamais dire ENTRY, quelle que soit l'imbalance observée.

**Preuve (LIVE, nos propres données) :**

| Paire | Corrélation imb→move | Pente (% par unité d'imb) | max \|imb\| observé | Mouvement max PRÉDIT | Seuil min de la pool |
|---|---|---|---|---|---|
| ETH/USDC | 0,115–0,190 | 0,0228–0,0289 | 0,320 | **0,0093 %** | 0,0334 % ($100) / 0,066 % ($1k) |
| AERO/USDC | 0,157–0,196 | 0,0218–0,0326 | 0,572 | **0,0181 %** | 0,1668 % ($25) / 0,2339 % ($100) |

- Mouvement max prédit = pente × max\|imb\| observé sur tout le run
  (`audit_checks.py` §B, recomputé depuis `paper_entries.jsonl`).
- ETH : 0,0093 % prédit vs 0,0334 % de seuil → **3,6× trop petit** (7× au seuil $1k).
- AERO : 0,0181 % prédit vs 0,1668 % de seuil → **9,2× trop petit**.
- Même avec une imbalance PARFAITE (\|imb\| = 1, jamais observée — max réel 0,32
  sur ETH, 0,57 sur AERO), la prédiction serait 0,029 % / 0,033 % — toujours
  sous les seuils.
- Conditionnel (LIVE) : quand \|imb\| > 0,2, le mouvement suivant moyen est
  0,0129 % (ETH, n=18, max 0,0522 %) contre 0,0097 % quand \|imb\| < 0,05 —
  l'imbalance extrême décale la moyenne de +33 % en relatif, mais les
  mouvements restent minuscules en absolu. Le plus gros mouvement suivant
  une imbalance extrême (AERO, 0,1412 %) reste sous le plus petit seuil AERO
  (0,1668 % à $25).
- Base rate (LIVE, `measurements.jsonl`, 12 min) : mouvements Binance 2 s
  > 0,1 % : **0/334 (BTC), 0/335 (ETH)**. Dans le run paper : 1/347 (AERO),
  0/347 (ETH).

**Pourquoi c'est attendu (littérature) :** Cont, Kukanov & Stoikov (2014,
*Journal of Financial Econometrics* 12, 47–88) montrent que l'order-flow
imbalance explique les mouvements **contemporains** (R² ≈ 0,65) mais que le
R² **prédictif** hors-échantillon s'effondre à ≈ **0,0003** — « explaining is
not predicting ». Une réplication sur données Binance live (lobkit) trouve
R² prédictif ≤ **0,7 %** pour le mouvement des 10 s suivantes. Notre
système utilise en plus une imbalance **statique** (photo du carnet, pas le
flux d'événements OFI) à 3 s de résolution — encore plus faible que l'OFI
de la littérature. Nos corrélations mesurées (0,115–0,19, n≈190–347) ont un
intervalle de confiance à 95 % de ±0,14 environ : statistiquement, elles
sont à peine distinguables de zéro.

**Fix ($0 d'abord) :**
1. Remplacer la prédiction linéaire (moyenne conditionnelle) par une règle
   de **queue** : entrer seulement si \|imb\| extrême ET si la distribution
   conditionnelle des mouvements passés dépasse le seuil (ex. P(move > seuil
   \| \|imb\| > 0,8) mesurée sur les données). Coût $0 — mais nos données
   disent que même ce test échouera probablement (max conditionnel 0,1412 %
   < seuil 0,1668 %).
2. Passer à l'OFI **flux** (événements du carnet, pas photo statique) — $0
   en code, mais exige le WebSocket Binance, **bloqué depuis cette VM**
   (451 + handshake timeout ×5) → nécessite un VPS (cause n° 4).
3. Ne PAS « assouplir » le modèle en inventant une pente plus forte : la
   pente est mesurée, pas choisie.

**Ce que ça changerait :** rien de mesurable à court terme. Même un signal
10× meilleur atteindrait à peine le seuil ETH à $100. C'est la cause n° 1
parce qu'elle rend les entrées **structurellement impossibles**, pas parce
que la réparer rapporterait beaucoup — la littérature dit qu'elle ne
rapporterait presque rien.

---

## Cause n° 2 — PAS DE LEADER POUR LES PETITES POOLS (les seuls mouvements > seuil n'avaient aucun signal)

**Hypothèse :** les seuls mouvements qui dépassent un seuil sont sur des
tokens NON listés sur Binance (SOSO, ICNT) — donc sans aucun signal
Binance. Le système ne peut pas les prédire, seulement les constater
après coup.

**Preuve (LIVE) :**
- **19 enregistrements OPPORTUNITY = 13 événements distincts** (groupés par
  écart < 10 s), **tous SOSO/USDC**, tous `binance_signal: false`
  (`paper_entries.jsonl`, snapshot 11:06) — et ils **s'accélèrent** : 4 à
  11:01, 14 à 11:04 (rafale de trades SOSO vers 11:04–11:05 UTC).
  Mouvements réalisés : 0,1003 % à **0,4269 %** ; meilleurs nets
  rétrospectifs (SYNTHÉTIQUE) : **+$0,5686 à $250** (move 0,4269 %),
  +$0,2436 à $250 (0,2967 %) ; **total des 13 événements : $1,5791**
  (somme des premiers enregistrements de chaque événement — la somme
  par cycle, $2,1942, double-compte les mouvements persistants).
  2 des 13 événements sont des mouvements BAISSIERS (−0,1607 %,
  −0,2321 %) — il aurait fallu un SHORT pour les prendre.

**Pourquoi c'est structurel :** le prix d'un AMM est une fonction en
escalier — il ne bouge que quand un trade s'exécute, en un bloc (200 ms
sur Base). On ne peut pas « attraper un mouvement en cours » : soit on le
prédit (il faut un signal en amont), soit on arrive après (trop tard). Pour
SOSO, le mouvement vient d'un trade organique isolé, imprévisible sans
visibilité sur le flux d'ordres — et Base n'a **pas de mempool publique**
(séquenceur privé Coinbase). Il n'existe pas de « Binance de SOSO ».

**Quel leader à la place ? (mesurable à $0) :**
- **La pool principale du token comme leader** : si SOSO a une pool plus
  grosse ailleurs (Aerodrome ? une autre chaîne ?), son prix peut mener la
  pool Uni V3. À vérifier par token (DexScreener, $0) — non fait à ce jour.
- **Le bêta des majors** : si SOSO corrèle avec ETH/BTC, un mouvement ETH
  peut prédire un mouvement SOSO amplifié. Non testé — nos données ont
  ETH et SOSO dans la même fenêtre, la corrélation est calculable à $0.
- **Le flux de la pool elle-même** : volume/txn entrant (DexScreener) —
  mais c'est du passé, pas du futur.

**Ce que ça changerait :** incertain. Si un leader existe (pool Aerodrome
ou bêta majors), les 13 événements SOSO (≈ $1,58 au total en rétrospectif
sur ~25 min de phase live, dont une rafale à 11:04–11:05) deviendraient
théoriquement attrapables — soit **≈ $3,80/heure en papier pendant une
rafale, avant erreurs de prédiction** — mais les rafales sont épisodiques,
et sans leader le gain est **0**. C'est la cause n° 2 parce qu'elle
explique pourquoi les seuls mouvements réels étaient inattrapables — pas
parce que la réparer est garantie.

---

## Cause n° 3 — COUVERTURE : ON REGARDE 6,6 % DU VOLUME (le reste est sur Aerodrome)

**Hypothèse :** notre contrat + quoter ne voient que Uniswap V3 — une
minorité du volume Base. Si des opportunités existent, elles vivent
probablement là où est le volume.

**Preuve (LIVE, GeckoTerminal, 2026-11-25 ~11:10 UTC, top 60 pools Base) :**

| Venue | Page 1 (top 20) — part vol 24h | Pages 2–3 (pools 21–60) — part vol 24h |
|---|---|---|
| Aerodrome Slipstream (toutes générations) | **78,9 %** | **65,4 %** |
| PancakeSwap V3 | 14,2 % | 0,5 % |
| **Uniswap V3 (nous)** | **6,6 %** | **31,9 %** |
| Uniswap V4 | 0,2 % | 1,0 % |

- Page 1 : Aerodrome 74,7 % + Slipstream-3 3,3 % + Slipstream 0,9 % = 78,9 %.
- Nous regardons donc **6,6 % du volume des 20 plus grosses pools** et nous
  manquons **93,4 %**. Sur les pools 21–60, Uni V3 remonte à 31,9 % (les
  petites pools sont plus souvent Uni V3), mais le volume y est bien moindre.
- Le scan expert l'avait déjà trouvé : la plus grosse pool Base est
  WETH/USDC 0,01 % **PancakeSwap V3** (2,95 M$ de réserve, 28 M$/jour).

**Qu'est-ce qu'il faudrait pour citer Aerodrome (vérifié, $0) :**
- Adresses vérifiées on-chain **par nos soins, bloc 62 071 176**
  (`eth_getCode`, LIVE) : CLFactory legacy `0x5e7BB1…` (4 958 o),
  CLFactoryGaugeCaps `0xaDe65c…` (5 235 o), CLFactoryGaugesV3 `0xf8f2eB…`
  (5 235 o), MixedQuoterV3 `0xCd2A7D…` (8 225 o), SwapRouter GaugesV3
  `0x698Cb2…` (9 908 o), FactoryRegistry `0x5C3F18…` (2 649 o).
  Sources : docs.eco.com (Aerodrome Slipstream), builddaily.io,
  substreams.dev (adresses vérifiées on-chain par leurs auteurs).
- La math est la MÊME que Uni V3 (liquidité concentrée : slot0,
  liquidité, sqrtPriceX96) — la pool est un fork V3, clé par `tickSpacing`
  (1/50/100/200/2000) au lieu du fee. Le quoter est MixedQuoterV3 (chemin
  tagué `0x80000 | tickSpacing` pour la génération Gauges V3). Il faut
  résoudre les factories via `FactoryRegistry.poolFactories()` (ne pas
  hardcoder une seule factory — 3 générations coexistent).
- À noter : présence de code vérifiée seulement — les signatures
  `getPool`/`quote` n'ont pas encore été appelées par nos soins.

**Ce que ça changerait :** inconnu, mais c'est le plus grand espace NON
mesuré. Si le lead-lag existe quelque part sur Base, c'est là où 79 % du
volume s'échange. C'est le fix $0 avec le plus grand gain espéré — et c'est
pourquoi c'est le fix n° 1 recommandé (voir verdict), même si la cause
n° 1 explique mieux le 0 actuel.

---

## Cause n° 4 — VITESSE (réelle, mesurée — mais NON déterminante)

**Hypothèse :** notre boucle détection+exécution (~1,9–3,1 s) est plus
lente que la durée de vie des opportunités (lag 2–4 s).

**Preuve (LIVE) — budget de la boucle, mesuré :**

| Étape | Temps mesuré (LIVE) | Source |
|---|---|---|
| Appel depth Binance (limit 1000) | **1 520–2 459 ms** (juste maintenant) ; médiane 946 ms pour aggTrades (12 min) | `audit_checks2.py` §I ; `measurements.jsonl` |
| eth_call Alchemy | **363–1 049 ms** (variable) | §I, juste maintenant |
| RPC public Base | **HTTP 403 ×3 — mort** (était ~15 % d'échecs, maintenant bloqué) | §I, juste maintenant |
| Cycle complet du run | **3,13 s/cycle** (30 cycles / 94 s) | `paper_run1.log` |
| Bloc Base | 200 ms | connu (Denim) |
| Arrivée du signal (REST) | médiane 952 ms, p95 3 060 ms | lead-lag report |

- Notre cycle (3,1 s) est **plus long que la borne basse du lag (2 s)** :
  un mouvement qui naît et meurt en < 3 s peut être invisible.
- MAIS : pour les petites pools, les mouvements **persistent** (0/23
  réversions à +2 cycles) — la vitesse ne les fait pas rater, c'est le
  signal qui manque (cause n° 2). Pour les majors, les mouvements sont
  trop petits de toute façon (cause n° 1).
- WebSocket Binance : **inutilisable depuis cette VM** (api.binance.com
  451 ; stream.binance.com 451 ; data-stream.binance.vision handshake
  timeout ×5). Le passage au WS exige de quitter cette VM.

**Boucles atteignables par option (SYNTHÉTIQUE, estimations) :**

| Option | Boucle estimée | Coût | Ce que ça fixe |
|---|---|---|---|
| Actuelle (VM, REST + Alchemy) | ~1,9–3,1 s | $0 | — |
| VPS Tokyo (~$20/mois, t3.small) | ~0,3–0,5 s | ~$20/mois | WS Binance (~25 ms) ; Alchemy US ~150 ms |
| VPS us-east-1 (~$20/mois) | ~0,3–0,5 s | ~$20/mois | RPC Base ~10–50 ms ; Binance WS ~120–180 ms |
| Nœud propre / coloc | ~0,05–0,2 s | $200–500/mois | tout, sauf le bloc 200 ms |

**Ce que ça changerait :** ≈ 0 entrée supplémentaire par semaine avec le
signal actuel (le plafond de prédiction est 4–13× sous les seuils — même
une détection instantanée ne crée pas d'entrée). La vitesse ne devient
déterminante qu'APRÈS qu'un signal prédictif existe. C'est une cause
réelle mais classée n° 4 : elle explique une petite partie du 0, et la
réparer seule ne change rien de mesurable.

---

## Cause n° 5 — SEUIL TROP STRICT (vrai bug, petit gain)

**Hypothèse :** notre math de seuil (gas ×2, grille de tailles, modèle
mono-tick) bloque des trades qu'une règle plus lâche (mais honnête)
prendrait.

**Preuve — le cas SOSO recomputé à la main (SYNTHÉTIQUE, modèle mono-tick
validé par QuoterV2 à 0,0001 pp près sur les tiers liquides : SOSO $1k
0,3628 % quoter vs 0,3627 % analytique ; ETH 0,0327 % vs 0,0326 % ;
AERO 0,6757 % vs 0,6769 %) :**

Seuil par taille, SOSO/USDC fee 0,01 % (LIVE : mid 0,296333 $, L 5,21e17) :

| Taille | Coût aller-retour | Seuil gas ×2 | Seuil gas ×1 | Part du gas dans le seuil |
|---|---|---|---|---|
| $25 | $0,0094 | **0,0732 %** | 0,0554 % | 49 % |
| $50 | $0,0276 | **0,0730 %** | 0,0641 % | 24 % |
| $100 | $0,0905 | 0,0994 % | 0,0949 % | 9 % |
| $250 | $0,4900 | 0,1996 % | 0,1978 % | 2 % |
| $500 | $1,8569 | 0,3732 % | — | 0 % |
| $1 000 | $7,2030 | 0,7212 % | — | 0 % |

- **BUG RÉEL :** `threshold_for_tier` itère sur `SIZES = [100, 250, …]`
  (`paper_trade.py`, ligne des SIZES) — il ne teste jamais $25/$50.
  Le vrai seuil minimum de SOSO est **0,0730 % à $50**, pas 0,0993 % à
  $100 comme logué. Le système **surestime le seuil SOSO de 36 %**.
- **Gas ×2 :** il compte pour 49 % du seuil à $25, 9 % à $100, ~0 % dès
  $500. Le passer à ×1 ferait gagner 0,0045 pp à $100 — négligeable. Le
  gas n'est PAS le problème (contrairement à l'intuition initiale).
- **Le vrai coût, c'est l'impact :** à $100, l'impact (0,0453 %) vaut
  déjà 4,5× les frais (0,01 % × 2). À $250, l'impact (0,0982 %) double
  le seuil. Le seuil n'est presque jamais le fee — c'est l'impact.
- **Net du mouvement SOSO 0,1741 % par taille (SYNTHÉTIQUE) :**
  $25 → **+$0,025** ; $50 → **+$0,050** ; $100 → **+$0,075** ;
  $250 → −$0,065 ; $500 → −$0,999 ; $1 000 → −$5,49.
  La taille optimale est $100 — et même le meilleur cas vaut **7 cents**.

**Ce que ça changerait :** corriger la grille ($25/$50 inclus) ajouterait
~4–7 opportunités rétrospectives par ~350 cycles (mouvements entre
0,073 % et 0,0993 %), chacune ≤ $0,05 — soit **≈ $0,20–0,35 par run de
30 min, en rétrospectif, avant toute erreur de prédiction**. Fix gratuit
et à faire, mais il ne change pas le verdict. Le modèle mono-tick, lui,
est **validé** (ancres QuoterV2) — pas une cause.

**Flag qualité de données (sans effet sur les décisions) :** les ancres
`q1k` sont absurdes sur les tiers quasi-vides (AERO fee 100 : impact
médian **595 486 %** ; fee 10000 : 79 % ; fee 3000 : 33 %) — le QuoterV2
renvoie n'importe quoi quand L ≈ 0. Les décisions utilisent le modèle
analytique, pas ces ancres — mais elles ne doivent jamais être citées
comme des mesures.

---

## Cause n° 6 — ÉCHANTILLONNAGE 3 s (mineur)

**Hypothèse :** on échantillonne toutes les ~3,1 s — les mouvements nés
et morts dans un cycle sont invisibles.

**Preuve (LIVE) :**
- Petites pools : 23 mouvements > 0,1 % observés (SOSO 15, AERO 2,
  ICNT 6), **0 réversion** au cycle +2 (~6 s). Les mouvements persistent :
  l'échantillonnage à 3 s ne les rate pas, il les voit en rétrospectif.
- Majors : mouvements 2 s > 0,1 % : **0/334 (BTC), 0/335 (ETH)** en
  12 min — il n'y a rien à rater. Les 3 seuls mouvements 2 s > 0,05 %
  (BTC 1, ETH 2) n'ont **pas** réversé à plus de 50 % au bin suivant.
- Le prix AMM bouge par paliers discrets (un trade = un saut, un bloc).
  Un échantillonnage à 500 ms verrait le saut ~2,5 s plus tôt qu'à 3 s —
  mais le saut est déjà arrivé : on ne peut pas entrer « pendant » un
  saut qui tient dans un bloc de 200 ms. Il faut le prédire, pas le
  suivre.

**Ce que ça changerait :** passer à 500 ms / par bloc aiderait les majors
marginalement (un échantillon par mouvement au lieu d'un tous les 1,5
mouvements) — gain ≈ 0 entrée/semaine vu la taille des mouvements.
Le coût : 6× plus d'appels RPC (rate limits Alchemy gratuits à surveiller).

---

## Cause n° 7 — SHORT NON EXÉCUTABLE (écart implémentation, 42 % du signal perdu en réel)

**Hypothèse :** le système prédit des SHORT que le contrat du repo ne
peut pas exécuter.

**Preuve (LIVE) :** directions en phase live : LONG 197, **SHORT 141**,
soit **42 %** des prédictions (`paper_entries.jsonl`). Le contrat
`MorphoFlashLoanArbitrage` n'emprunte que de l'USDC et achète l'asset
(LONG uniquement) ; un SHORT exigerait d'emprunter l'asset (marché
Morpho WETH/cbBTC à vérifier + fonction dédiée — non construite).

**Ce que ça changerait :** en papier, rien (les SHORT étaient tous SKIP
de toute façon). En réel, si un signal apparaissait, **42 % des entrées
seraient inexécutables** sans nouveau code. Fix $0 en code (emprunt
asset via Morpho + vente), à faire avant tout passage en réel — mais
ce n'est pas ce qui cause le 0 actuel.

---

## Cause n° 8 — FENÊTRE TROP COURTE / MARCHÉ CALME (mineur)

**Hypothèse :** nos fenêtres (12 min lead-lag, 30 min paper) sont courtes
et calmes — les opportunités se concentrent dans les sessions volatiles
(news, listings, liquidations).

**Preuve (LIVE + littérature) :**
- Le 2026-11-25 était pourtant une journée **baissière et volatile à
  l'échelle journalière** (BTC −1,3 %, ETH −2,2 %, small caps −5 % à
  −30 %, 368 M$ de liquidations sur 24 h d'après les données du jour) —
  et malgré cela, à l'échelle 2–4 s, le marché était calme : 0 mouvement
  2 s > 0,1 % sur les majors en 12 min, 1/347 en 30 min (AERO).
- La littérature confirme que les écarts CEX-DEX sont minuscules en
  moyenne : corrélation CEX-DEX 0,98–0,99, écart absolu moyen 0,06–0,08 %
  (Divyasshree N., 2025, *Price Discovery Dynamics Between DEX and CEX*,
  Zenodo) — c'est-à-dire **sous notre breakeven** la plupart du temps.
  Les écarts se concentrent lors des chocs — mais ils sont aussi
  arbitrés en millisecondes par ceux qui sont équipés.
- Un run de 7 jours **échantillonnerait** ces sessions volatiles (FOMC,
  listings, liquidations) — la base rate monterait probablement de
  ~0,3 % à quelques % des fenêtres. Mais le plafond de prédiction
  (cause n° 1) et le seuil (cause n° 5) ne bougent pas : même en session
  volatile, il faut un mouvement > seuil **prédit à l'avance**.

**Ce que ça changerait :** un run 7 jours trouverait plausiblement une
poignée d'événements de queue (mouvements > 0,15 % sur majors, plus sur
petites pools) — c'est exactement le protocole GO/STOP déjà défini
(≥5 entrées/sem net > 1 $ ET |r| ≥ 0,3). Il ne « répare » pas le 0, il
le **teste** sur une fenêtre honnête.

---

## Étude de cas : les mouvements SOSO — aurions-nous pu les attraper ?

**Faits (LIVE, snapshot 11:06) :** 13 événements distincts SOSO/USDC en
~25 min de phase live, mouvements réalisés 0,1003 % à **0,4269 %**, tous
persistants ≥ 6 s. Seuil min 0,0993 % à $100 (0,0730 % à $50 avec la
grille corrigée). Total rétrospectif des 13 événements : **$1,5791**
(SYNTHÉTIQUE, mono-tick validé) — meilleur événement : move 0,4269 % →
net **+$0,5686 à $250**. Les événements se concentrent en rafale
(11:04–11:05 UTC : 8 des 13). Exemple détaillé (premier événement) :
mouvement +0,1741 % en un cycle (~3 s), net rétrospectif +$0,0746 à $100.

| Scénario | Aurait-on attrapé le mouvement ? | Preuve |
|---|---|---|
| Avec le signal actuel (imbalance Binance) | **NON** — SOSO n'est pas listé sur Binance, pas de signal du tout | `binance_signal: false` sur les 19 enregistrements / 13 événements |
| Avec un cycle de 500 ms | **NON** — le saut tient dans un bloc (200 ms) ; on le verrait plus tôt, mais toujours après | Prix AMM = paliers discrets ; 0/23 réversions |
| Avec le seuil corrigé ($25–50) | **OUI en rétrospectif** (0,1741 % > 0,0730 %) — mais toujours pas prédictible | § Cause n° 5 |
| Avec un leader Aerodrome / bêta majors | **PEUT-ÊTRE** — non mesuré ; c'est le test à faire | Cause n° 2 |
| Avec un VPS Tokyo | **NON** — la vitesse ne crée pas de signal | Cause n° 4 |

**EV honnête des mouvements SOSO :** 13 événements ≈ **$1,58 au total**
en ~25 min de phase live (dont une rafale), **SI prédiction parfaite et
timing parfait à la taille optimale** — et la prédiction parfaite est
impossible sans signal. Avec un signal réel (corrélation 0,18), l'EV
attendue est proche de **$0**. La rafale montre que les petites pools
bougent par grappes — mais bouger n'est pas être prévisible.

---

## Comment font les vrais searchers (comparaison de pratique, sourcé)

| Ce qu'ils font | Nous | $0 réparable ? | Source |
|---|---|---|---|
| Flux WS privés, ms (pas REST 1–2 s) | REST 1,5–2,5 s | Non — WS bloqué sur cette VM ; VPS ~$20/mois | Lead-lag report (451, timeouts) |
| Colocation / nœud proche du séquenceur | VM New York, RPC partagé | Non — VPS ~$20/mois | Lead-lag report (Tokyo ~20–25 ms) |
| **Surveillent TOUTES les venues** (Aerodrome = 79 % du vol Base) | Uni V3 seulement (6,6 % p.1) | **OUI — $0** (adresses vérifiées § Cause n° 3) | GeckoTerminal live, ce rapport |
| Inventaire des deux côtés (pas de flash pour la jambe CEX) | Flash only, $0 capital CEX | Non — capital requis | CHEAPEST_SOLVER_POLYGON.md |
| Exécuteurs ms (Rust/Go), simulation locale (Revm/Erigon) | Python, cycle 3,1 s, eth_call distant | Partiellement — Rust = travail, pas d'argent | arXiv 2510.14642v1 (fenêtres Atlas ~250 ms) |
| Soumission privée / bundles (Flashbots, Atlas) | Broadcast public (Polygon) / pas de mempool Base | Partiellement — Atlas $0 d'entrée, mais fenêtres 250 ms injouables à 356 ms | arXiv 2510.14642v1 ; SOLVER_ZERO_DOLLAR_POLYGON.md |
| Décident en **~250 ms** (enchères Atlas scellées, une seule chance) | Décision en ~3 s | Non sans infra ms | arXiv 2510.14642v1 |
| Modèles de flux (OFI événementiel), pas photo statique | Imbalance statique à 3 s | **OUI — $0 en code** (mais exige WS) | Cont et al. 2014 ; lobkit |
| Capital gas pour des centaines de tentatives/jour | $1,31 = ~137–296 tentatives | Non — c'est le float d'Ismail | Repo (float $1,31) |

**Et pourtant :** même chez les pros, la marge moyenne est minuscule —
Bitquery : **0,22 $/trade en moyenne sur Polygon, 47,7 % des trades
< 1 cent et nets-négatifs après frais**. « Beaucoup de gens gagnent
avec » est vrai — mais ils gagnent des centimes par trade, des milliers
de fois par jour, avec du capital et de l'infra. Ce n'est pas un jeu
à $0 et 3 s de latence.

---

## Classement final des causes

| # | Cause | Part du 0 (jugement d'expert) | Gain si réparée |
|---|---|---|---|
| 1 | **Signal trop faible** — prédiction max 0,009–0,018 % vs seuils 0,033–0,167 % ; le modèle ne peut jamais déclencher | ~35 % | ≈ 0 entrée/sem (la littérature dit que même l'OFI ne prédit presque rien) |
| 2 | **Pas de leader pour les petites pools** — les seuls mouvements > seuil (SOSO) n'avaient aucun signal | ~20 % | Incertain (0 si pas de leader ; ~$3,80/h papier pendant une rafale si leader trouvé) |
| 3 | **Couverture 6,6 %** — Aerodrome = 79 % du volume top-20, jamais regardé | ~20 % | Inconnu — le plus grand espace non mesuré |
| 4 | **Vitesse** — cycle 3,1 s vs vie 2–4 s ; depth 1,5–2,5 s ; RPC public mort (403) | ~10 % | ≈ 0 avec le signal actuel ; nécessaire après un signal |
| 5 | **Seuil trop strict** — grille $100 min (vrai seuil SOSO 0,073 % pas 0,0993 %) ; gas ×2 | ~5 % | +4–7 opps rétrospectives / 350 cycles, ≤ $0,05 chacune |
| 6 | **Échantillonnage 3 s** — mouvements nés/morts intra-cycle | ~5 % | ≈ 0 (les mouvements persistent ; les sauts sont atomiques) |
| 7 | **SHORT inexécutable** — 42 % des prédictions (141/338) | 0 % du 0 actuel ; 42 % en réel | À corriger avant tout réel |
| 8 | **Fenêtre courte** — 12–30 min, marché calme à l'échelle 2–4 s | ~5 % | Une poignée d'événements de queue sur 7 jours, à tester |

---

## Verdict d'expert

**Le 0 est un artefact de mesure à ~30 % et une absence réelle à ~70 %.**
L'absence est réelle parce que (a) les mouvements à l'échelle 2–4 s sont
de ~0,01–0,03 % quand il en faudrait 0,07–0,17 % au minimum, (b) la
prédiction par imbalance est plafonnée 4–13× sous les seuils, et (c) les
seuls mouvements > seuil (SOSO) sont des sauts atomiques imprévisibles
sans leader. L'artefact est réel parce que (a) on ne regarde que 6,6 %
du volume, (b) on n'a aucun leader pour les petites pools, (c) la grille
de tailles commence à $100, et (d) 42 % du signal (SHORT) est
inexécutable en l'état.

**Le fix le plus important, et le seul à faire en premier :**
**citer Aerodrome Slipstream ($0)** — ajouter le quoter MixedQuoterV3 +
les 3 CLFactories (adresses vérifiées on-chain dans ce rapport) au
système paper-trade, et mesurer les mêmes paires sur Aerodrome vs Uni V3
pendant 7 jours. C'est le seul fix qui ouvre un espace **non mesuré**
(79 % du volume) au lieu d'optimiser un espace déjà mesuré à 0.
Ensuite, dans l'ordre : (2) leader par token pour les petites pools
(Aerodrome comme leader ou bêta majors) ; (3) grille de tailles $25+
et SHORT via Morpho ; (4) vitesse (VPS) **seulement si** le log prouve
que la vitesse est le goulot — aujourd'hui il prouve le contraire.

**Si après 7 jours sur Aerodrome le compte reste à 0 :** abandonner le
lead-lag Binance → Base et pivoter vers les bug bounties / audit contests
(meilleur chemin $0 depuis la mort de la route Curve) — comme déjà
recommandé dans l'expert scan.

---

## Sources

- Nos logs : `leadlag/paper_entries.jsonl` (1 400 enregistrements, snapshot
  11:01–11:05 UTC), `leadlag/paper_run1.log`, `leadlag/measurements.jsonl`
  (1 600 enregistrements, 12 min), `leadlag/expert_scan_results.json`
  (11 candidats).
- Nos scripts : `leadlag/audit_checks.py`, `leadlag/audit_checks2.py`
  (toutes les recomputations de ce rapport).
- GeckoTerminal API (live, 2026-11-25 ~11:10 UTC) : top 60 pools Base,
  part de volume par venue.
- On-chain Base, bloc 62 071 176 (live) : `eth_getCode` des 6 adresses
  Aerodrome (FactoryRegistry + 3 CLFactories + MixedQuoterV3 + SwapRouter).
- Cont, Kukanov & Stoikov (2014), « The Price Impact of Order Book
  Events », *Journal of Financial Econometrics* 12(1), 47–88
  (arXiv:1011.6402) — R² contemporain ≈ 0,65, R² prédictif ≈ 0,0003.
- lobkit (PyPI) — réplication Binance live : R² prédictif ≤ 0,7 % à 10 s.
- Divyasshree N. (2025), « Price Discovery Dynamics Between DEX and CEX »,
  Zenodo — corrélation CEX-DEX 0,98–0,99, écart moyen 0,06–0,08 %.
- Zhao & Zhou (2023), UQAM Chaire Fintech — les prix DEX suivent les CEX
  avec un lag optimal mesurable ; les arbitrageurs maintiennent l'alignement.
- arXiv 2510.14642v1 (Polygon Atlas / FastLane) — fenêtres d'enchères
  ~250 ms, décision en une seule fois, sans visibilité concurrentielle.
- Bitquery (via repo) — marge moyenne Polygon 0,22 $/trade, 47,7 % des
  trades < 1 cent et nets-négatifs.
- Adresses Aerodrome : docs.eco.com (Aerodrome Slipstream), builddaily.io,
  substreams.dev — vérifiées on-chain par nos soins (code présent, § Cause n° 3).
