# Analyse complète — Flash mint / own-pair / route Curve — 2026-11-25

Auteur : Muse (profil trader). Question d'Ismail : « dir full analyse ogoliya kifach ndir nkhdmha ana ».
Statut : simulation fork flash self-fee EN COURS (agent) — ses chiffres viendront compléter §3.

## 0. Verdict en une phrase

1. **Route Curve 4-jambes : PREMIER signal live positif du projet** — net **+$5,63 à 5 k$**
   (vérifié par moi en direct, blocs 97 921 306–308, 2026-11-25 ~06:16 UTC). C'est une
   **fenêtre** (USDT décoté + pool Curve mort), pas un edge permanent.
2. **Flash mint / own-pair : mécanique réelle, mais théorème des deux moitiés** —
   own both pairs = ~0 $ ; own one pair = moitié du profit ; ça ne crée pas de profit,
   ça protège le LVR et récupère les frais. Et ça coûte du capital seed.
3. **À 0,02 % / 0,05 % : les frais PERMETTENT le profit** (breakeven 0,011 % avec une
   jambe à 0,001 %), **mais le marché ne donne pas le spread en 2 jambes** (tout
   négatif) — sauf la route Curve (§1), qui contourne le problème par un prix stale.

## 1. La route Curve — le signal (vérifié live par moi)

**Route :** emprunt USDC natif chez Morpho → USDC.e (Uni V3 0,01 %) → USDT
(Uni V3 0,01 %) → USDC (Curve am3pool `exchange_underlying`).

**Mesures live (moi, `eth_call`, toutes les jambes au même bloc) :**

| Bloc | Loan | USDC→USDC.e | USDC.e→USDT | USDT→USDC (Curve) | Brut | Net (gas budgété 0,028 $) |
|---|---|---|---|---|---|---|
| 97 921 306 | 1 000 $ | 999,89 | 1 001,04 | 1 001,14 | +1,14 $ | **+1,12 $** |
| 97 921 307 | 5 000 $ | 4 999,45 | 5 005,16 | 5 005,66 | +5,66 $ | **+5,63 $** |
| 97 921 308 | 20 000 $ | 19 997,48 | 20 019,98 | 20 021,73 | +21,73 $ | **+21,70 $** |

Route inverse perd à toutes les tailles (−1,57 $ à 1 k$). Stable ~10 min
(mêmes chiffres à ±0,01 $ sur 3 blocs espacés).

**Pourquoi elle existe :** l'USDT vaut ~0,9988 $ globalement (CoinGecko 0,99917 $,
3commas 0,998991 $, 25 nov 2026) ; Uni V3 et Algebra suivent ce prix
(1 USDC.e = 1,0011 USDT) ; **le pool Curve am3pool est STALE à 1,0001**
(volume 24 h nul, personne ne trade, son prix n'a jamais suivi la décote).
Écart brut ~0,11 % > frais totaux de la route (0,01 % + 0,01 % + 0,001 % = 0,021 %).

**Plafond de loan (vérifié par moi, bloc 97 921 315) :** Morpho détient
75 540,27 $ d'USDC natif → règle 50 % ≈ **37 770 $ max**. Morpho USDT :
122 029,66 $. (Le marché USDC.e ne détient que 504,21 $ — d'où l'emprunt en USDC natif.)

**Limites — à lire avant tout enthousiasme :**
1. **Quotes seulement, jamais exécuté.** Le contrat actuel n'a PAS de jambe Curve :
   il faut une nouvelle fonction (Morpho USDC → 2 swaps V3 → Curve → repay),
   puis un test fork avant tout mainnet.
2. **Gas 4-jambes ESTIMÉ ~650 000 unités (~0,014 $/trade, 0,028 $ budgété 2×)
   — à mesurer sur fork.** Le trade 2-jambes standard est à ~450 000 unités.
3. **Fenêtre, pas edge :** elle meurt si l'USDT revient à 1,0000 $, si quelqu'un
   trade le pool Curve (il se reprice instantanément), ou si le prix Uni bouge.
   Protections existantes : re-simulation pré-envoi (`revert_protection.py`) +
   `minProfit` on-chain 0,01 $ — si l'edge a disparu au bloc d'exécution, le trade
   est droppé (0 $ gas) ou revert (~0,0024 $ mesuré).
4. Profit petit en absolu (+5,63 $ à 5 k$) : il faut répéter la route tant que la
   fenêtre dure — chaque répétition = un nouveau trade + gas + risque de revert.

## 2. Flash mint / flash swap — les mécanismes

| Mécanisme | Fee | Qui reçoit le fee | Statut |
|---|---|---|---|
| Morpho flash loan | **0 %** | — | Vérifié Base + Polygon + Sepolia |
| WETH flash mint (WETH10) | **0** (by design) | — | À vérifier sur Polygon (agent en cours) |
| Uniswap V2 flash swap | 0,30 % du montant | Réserves du pair → LPs | Vérifié (QuickSwap/Sushi V2 existent) |
| Uniswap V3 flash | = pool fee (0,01–1 %) | LPs in-range | Principe vérifié, confirmation on-chain en cours |

**« Posséder un pair » = fournir de la liquidité** (recevoir des LP tokens) :
les frais de chaque swap sur ce pair reviennent aux LPs au prorata. Le flash
swap emprunté depuis son propre pair coûte donc 0 % effectif (le fee revient
à soi-même comme LP). Le flash mint ne change pas l'économie : l'emprunt est
déjà à 0 % via Morpho — il change seulement *d'où* on emprunte.

## 3. Own-pair : le théorème des deux moitiés

Un spread entre 2 pairs = moitié venant du pair A + moitié venant du pair B.
- **Moitié du pair que TU POSSÈDES = 0 $** : tu déplaces l'argent de ta poche LP
  vers ta poche trader (même poche). Le profit trader est exactement compensé
  par la perte LP (LVR).
- **Moitié du pair que tu NE POSSÈDES PAS = profit réel** : il vient des LPs
  des autres.

**Exemple — spread 1 % (A à 1,00 / B à 1,01, fair 1,005), leg 5 000 $ :**

| Qui possède les pairs | Trader | LP | Frais | **Net total** |
|---|---|---|---|---|
| Own nothing (bot classique) | +50 $ | 0 | −30 $ (0,3 % × 2) − gas | **+19,98 $** |
| Own BOTH pairs | +50 $ | −50 $ | 0 $ (reviennent) − gas | **−0,02 $** |
| Own ONE pair | +50 $ | −25 $ | −15 $ (jambe externe) − gas | **+9,98 $** |

Avec des tiers à 0,01 % (frais 0,50 $/jambe) : own one = **+24,48 $** à 1 % ;
**+0,73 $** à 0,05 % ; **−0,02 $** à 0,02 %. Own nothing = +1,48 $ à 0,05 %.

**Capital — la contrainte décisive :** la taille du leg est plafonnée par la
profondeur du PLUS PETIT des deux pools (règle : leg ≤ ~2 % du pool pour garder
l'impact ≤ ~2 %). Donc le capital seed plafonne directement la taille du trade.

| Seed (TVL pool propre) | Leg max sensé | Net @ 1 % (own one, 0,01 %) | Net @ 0,05 % |
|---|---|---|---|
| 1 000 $ | ~20 $ | +0,09 $ | −0,01 $ |
| 10 000 $ | ~200 $ | +0,97 $ | +0,02 $ |
| 100 000 $ | ~2 000 $ | +9,79 $ | +0,29 $ |
| (leg 5 000 $, pool externe profond) | 5 000 $ | +24,48 $ | +0,73 $ |

**Ce que own-pair achète vraiment :** (a) récupération des frais de ses propres
pools ; (b) protection du LVR — sans self-arb, les searchers externes prennent
la valeur du flow sur ton pool (tu ne gardes que leurs frais). **Ce qu'il ne
fait pas :** créer du profit. Le profit vient du flow externe, qui revient
déjà au LP automatiquement. Un pool avec ta liquidité seule (0 traders) =
0 price moves = 0 spread = rien à arbitrer.

## 4. Breakeven à 0,02 % / 0,05 % (vérifié on-chain)

| Paire de venues | Frais totaux | Breakeven | Net @ 0,02 % (5 k$) | Net @ 0,05 % (5 k$) |
|---|---|---|---|---|
| V3 0,01 % + V3 0,01 % | 0,020 % | 0,020 % | −0,03 $ | **+1,47 $** |
| V3 0,01 % + Algebra/Curve 0,001 % | 0,011 % | **0,011 %** | **+0,42 $** | **+1,92 $** |
| V3 0,05 % + V3 0,05 % | 0,100 % | 0,100 % | −4,03 $ | −2,53 $ |
| V3 0,05 % + V2 0,30 % | 0,350 % | 0,350 % | −16,53 $ | −15,03 $ |

Venues vérifiées : Algebra stables **0,001 %** (`globalState` fee_raw=10) ;
Curve am3pool **0,001 %** (`fee()`=100000/1e10) mais USDC natif via amTokens,
pas USDC.e ; V3/V4 tiers 0,01 % existent (USDC.e/USDT TVL 832 k$) ;
**aucun pool V4 0-fee avec liquidité réelle** (Bunni v2 TVL 5 $ sur Polygon,
FeeFree ~14 k$ total, Angstrom Ethereum-only, 0 `Initialize` en 10 000 blocs).
Algebra volatiles 0,0868–0,0878 % (pire que V3 0,05 %).

**Market-making (alternative) :** stable-stable LP = seul vrai revenu à ces
spreads : USDC.e/USDT V3 0,01 % **+0,41–0,54 $/sem par 1 000 $** (2,12 % APR),
USDC natif/USDT **+1,60–2,13 $/sem** (8,31 % APR), IL ~0. WMATIC/USDC.e :
frais +0,69–0,92 $/sem mais IL ±10 % = −1,13 $ efface 1,2–1,6 semaine —
net ≤ 0 la plupart des semaines en passif. Le LP gagne des centimes par
semaine par millier de dollars, pas des dollars par trade.

**Conclusion §4 :** la math des frais permet le profit à 0,02 % ; le marché
ne donne pas le spread en 2 jambes (meilleur spread mesuré −0,014 % sur
117 mesures + 61 065 quotes temps réel). La route Curve est l'exception —
parce que son spread brut est 0,11 %, pas 0,05 %.

## 5. Kifach nkhdmha ana — guide pas-à-pas pour Ismail

### Voie A — Route Curve (PAS de capital seed : le flash loan couvre le loan)

| # | Étape | Qui | Statut |
|---|---|---|---|
| A1 | Ajouter la jambe Curve au contrat (`exchange_underlying`) + test fork avec les quotes réelles | Muse | **À faire** (prochaine étape) |
| A2 | Surveiller la fenêtre : décote USDT + prix Curve + balance Morpho USDC (listener à adapter : alerte si net 5 k$ < 0) | Muse | À faire |
| A3 | Financer le gas : tes 1,31 $ MATIC = **~46 trades** à 0,028 $ budgété. Ne rien envoyer d'autre. Ne jamais envoyer le max (garde ~1–2 MATIC pour le gas Polygon) | Ismail | Prêt (balance actuelle) |
| A4 | Audit du contrat avant tout mainnet (payant, milliers $) — **bloquant** | Ismail/Muse | Bloqué |
| A5 | Approbation d'Ismail par batch avant chaque exécution (jamais sans feu vert ; un stop = arrêt immédiat) | Ismail | Règle permanente |
| A6 | Exécution sur signal live vérifié (re-simulation pré-envoi + minProfit 0,01 $ on-chain) ; profits USDC → wallet ; log dans `trades.jsonl` | Muse | Après A1+A4+A5 |
| A7 | Arrêt dès que la fenêtre se ferme (USDT repeg / trade Curve / net < 0) | Muse | Automatique (garde) |

### Voie B — Own-pair (capital seed nécessaire)

| # | Étape | Qui | Statut |
|---|---|---|---|
| B1 | Choisir le pair : WMATIC/USDC.e ; venue externe : Uni V3 tier 0,01 % (vérifié existant) | Ismail + Muse | À décider |
| B2 | Fournir la liquidité : QuickSwap V2 « Add Liquidity » 50/50, ou Uni V3 mint position (range à choisir). **Tu signes dans ton MetaMask.** Capital selon §3 : 1 k$ = cents/trade, 10 k$ = ~1 $/trade à 1 %, 100 k$ = ~10 $/trade | Ismail | Bloqué : capital (tu as 1,31 $) |
| B3 | Contrat d'arbitrage route own-pair + test fork + audit | Muse/Ismail | Bloqué (audit) |
| B4 | Bot : listener temps réel + route own-pair (déjà prêt pour Polygon, à adapter) | Muse | À faire après B3 |
| B5 | Collecter les frais LP : « Collect » sur QuickSwap/Uni (tu signes) ou en retirant la liquidité | Ismail | Après B2 |
| B6 | Risques : IL, autres searchers qui arbitrent TON pool, smart contract, vitesse (pas de mempool privé) | — | Permanent |

### Ce qui est bloqué maintenant (les deux voies)
- **Audit** (payant, milliers $) — obligatoire avant mainnet, aucune solution 0 $.
- **Wallet mainnet financé** — gas seulement (1,31 $ dispo, ~46 trades Voie A / ~137 trades 2-jambes).
- **Spread réel** — route Curve = 1re fenêtre mesurée ; 2-jambes = 0.
- **Vitesse** — pas de mempool privé ni RPC dédié ; pour la fenêtre Curve ça compte
  moins (elle dure ~10 min, pas des secondes) — pour les spreads normaux, c'est décisif.

### Si tu veux lancer le code toi-même
Le code est sur ton GitHub privé (`ISMAIL-REDOUANE/codema-base-flashloan-bot`,
branche `master`). Besoin : Python + `web3` (le `.venv` du repo), un RPC Polygon,
ton wallet. Le bot ne broadcast rien sans que tu signes/finances.

## 6. Prochaines étapes — décisions d'Ismail

1. **Voie A : lancer la jambe Curve + test fork ?** (coût 0 $, étape A1 — je peux
   la lancer maintenant sur ton ordre)
2. **Voie B : capital seed pour own-pair ?** (combien, et quel pair — voir §3)
3. **Audit :** le lancer maintenant ou attendre le premier signal exécuté en fork ?
4. **Simulation fork flash self-fee** (hold vs self-arb vs external-arb vs
   own-one-pair) : chiffres à venir — ils confirmeront ou corrigeront §3.

## Annexe — fichiers et reproductibilité
- `polygon/LOW_FEE_PROFIT_POLYGON.md` — rapport complet low-fee (venues, breakevens, route Curve, MM).
- `polygon/low_fee_routes.py` — quoter 4-jambes lecture seule + `breakeven_table()` + `lp_evaluation()`.
- `polygon/test_low_fee.py` — 20/20 verts ; suites existantes re-vérifiées : test_polygon 25/25, pro_scan+realtime+revert 64/64.
- `polygon/FLASH_SELF_FEE_POLYGON.md` (agent en cours) — mécanismes flash + simulation fork.
- Adresses : Morpho Polygon `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` ;
  Curve am3pool `0x445FE580eF8d70FF569aB36e80c647af338db351` ;
  V3 USDC.e/USDT 0,01 % `0xDaC8A8E6DBf8c690ec6815e0fF03491B2770255D` ;
  V3 USDC/USDC.e 0,01 % `0xD36ec33c8bed5a9F7B6630855f1533455b98a418`.
- **Aucun broadcast, aucun wallet, aucune clé, aucun fonds réel dans ce document.**
