# EXPERT SCAN — Meilleurs candidats lead-lag Binance → Base (Uniswap V3)

**Date :** 2026-11-25 ~10:45 UTC · **Contexte :** ETH 1 646,93 $, gas Base 0,006 gwei
(0,00445 $/trade — le gas est négligeable, le coût est fees + impact).
**Fichiers :** `leadlag/expert_scan.py` (le scan, reproductible),
`leadlag/expert_scan_results.json` (toutes les mesures, horodatées).

## Verdict en une phrase

**Aucun candidat ne passe : la meilleure probabilité mesurée qu'un mouvement
de 4 s dépasse le seuil de sa pool est de 0,09 % (WETH/USDC) — les 10 autres
sont à 0,0 %.** Le classement ci-dessous est donc un classement des
« moins mauvais », pas des gagnants. Et la thèse « les petites pools bougent
plus » est à moitié vraie : elles bougent plus, mais leur impact prix est
10 à 1 000× supérieur au mouvement — l'edge se fait manger par le trade
lui-même.

## 1. Classement EV (top 5)

Score EV = (move_proxy_4s / seuil_1k) × facteur_signal × facteur_turnover.
`move_proxy_4s` = sigma_4s Binance (listés) ou |h1%|/60/√15 (non listés,
proxy grossier déclaré). `facteur_signal` : 1,0 si listé Binance, 0,15 sinon.
`facteur_turnover` : min(vol24/liquidité, 2).

| # | Pool (Uni V3) | Bande | TVL | Vol 24h | Fee | Seuil $100 / $1k / $5k | Move 4s (proxy) | Binance | P(move > seuil) | Score |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **WETH/USDC** `0xb4cb8009` | major | 577 k$ | 13,6 M$ | 0,01 % | 0,061 % / **0,066 %** / 0,246 % | 0,0213 % | OUI | **0,09 %** | **0,643** |
| 2 | **cbBTC/USDC** `0xfbb6eed8` | major | 6,09 M$ | 13,2 M$ | 0,05 % | 0,110 % / **0,108 %** / 0,137 % | 0,0179 % | OUI | 0,0 % | **0,330** |
| 3 | **VIRTUAL/WETH** `0x9c087Eb7` | small | 271 k$ | 288 k$ | 0,05 % | 0,134 % / **0,353 %** / 1,452 % | 0,0326 % | OUI | 0,0 % | **0,098** |
| 4 | **AERO/USDC** `0xE5B5f522` | mid | 129 k$ | 126 k$ | 0,05 % | 0,234 % / **1,336 %** / 5,925 % | 0,0368 % | OUI | 0,0 % | **0,027** |
| 5 | **SOL/USDC** `0x1cCA8388` | mid | 65 k$ | 27 k$ | 0,30 % | 0,740 % / **1,856 %** / 49,28 % | 0,0245 % | OUI | 0,0 % | **0,005** |

## 2. Tableau complet (11 candidats mesurés)

| Pool | Bande | TVL | Vol 24h | Δh1 / Δh24 | Fee | Seuil $1k | Move 4s | Binance | Imbalance 0,1 % | Score | Raison du rang |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WETH/USDC `0xb4cb80` | major | 577 k$ | 13,6 M$ | +0,52 % / −2,17 % | 0,01 % | 0,066 % | 0,0213 % | OUI | +0,14 | 0,643 | Seuil le plus bas de tout le scan (fees 0,01 % + impact faible) ; seule P > 0 |
| cbBTC/USDC `0xfbb6ee` | major | 6,09 M$ | 13,2 M$ | +0,21 % / −1,21 % | 0,05 % | 0,108 % | 0,0179 % | OUI | −0,45 | 0,330 | 2e seuil le plus bas ; mais sigma BTC encore plus petit que son seuil |
| VIRTUAL/WETH `0x9c087E` | small | 271 k$ | 288 k$ | +0,21 % / −2,33 % | 0,05 % | 0,353 % | 0,0326 % | OUI | **+0,58** | 0,098 | Seul petit candidat listé Binance ; sigma le plus haut (0,033 %) et imbalance achat fort — mais seuil 11× le move |
| AERO/USDC `0xE5B5f5` | mid | 129 k$ | 126 k$ | −0,09 % / −5,15 % | 0,05 % | 1,336 % | 0,0368 % | OUI | +0,35 | 0,027 | Sigma le plus haut du scan (0,037 %) mais impact 1,34 % à 1 k$ : pool trop fine |
| SOL/USDC `0x1cCA83` | mid | 65 k$ | 27 k$ | +0,03 % / −4,20 % | 0,30 % | 1,856 % | 0,0245 % | OUI | +0,01 | 0,005 | Fee 0,30 % + impact : seuil 49 % à 5 k$ — inexécutable à taille normale |
| VVV/USDC `0x67A110` | small | 1,07 M$ | 1,36 M$ | +2,00 % / −0,25 % | 0,30 % | 0,658 % | 0,0086 % | NON | — | 0,0025 | Pas de signal Binance (non listé) + fee 0,30 % : pas un candidat lead-lag |
| xdp/USDC `0x2dF380` | mid | 692 k$ | 3,25 M$ | +0,32 % / −6,24 % | 0,01 % | 0,492 % | 0,0014 % | NON | — | 0,0008 | Fee 0,01 % mais impact 0,49 % à 1 k$ (liquidité mal concentrée) ; pas de signal |
| ELSA/USDC `0xdc8F36` | small | 20 k$ | 17 k$ | −1,03 % / −28,9 % | 1,00 % | 8,142 % | 0,0044 % | NON | — | 0,0001 | −29 % en 24 h (bouge le plus) mais fee 1 % + impact 8 % à 1 k$ : le move est 1 800× sous le seuil |
| PLAY/USDC `0xE6dcff` | small | 2 k$ | 86 $ | −0,91 % / −10,7 % | 0,30 % | 75,78 % | 0,0039 % | NON | — | 0,0000 | Pool morte (2 k$ TVL, 86 $/jour) : un trade de 100 $ coûte 23,6 % |
| CTR/USDC `0xc01A30` | small | 345 $ | 21 $ | −0,87 % / −5,72 % | 1,00 % | 91,95 % | 0,0037 % | NON | — | 0,0000 | Pool morte (345 $ TVL) : un trade de 100 $ coûte 29 % |
| PROS/USDC `0x3f4E90` | mid | 205 $ | 2,5 k$ | +1,38 % / +11,8 % | 0,30 % | 91,93 % | 0,0059 % | NON* | — | 0,0000 | Pool V3 morte (205 $) ; le +11,8 % vit sur Aerodrome, pas ici ; *Binance : carnet vide (déférencé/illiquide) |

**Non résolus (exclus avant mesure) :** HYPE/WETH, VELVET/USDC, KNTQ/USDC —
aucun pool Uni V3 trouvé (leurs top pools sont Aerodrome, voir §4).

Toutes les pools mesurées : vérifiées on-chain (factory.getPool = adresse,
fee() lu on-chain, liquidité non nulle), GoPlus `is_honeypot = 0` partout,
mix txns DexScreener avec sells partout (aucun buys-only).

## 3. La méthode choisie — et pourquoi (jugement d'expert)

**Choix 1 — Le seuil se mesure, il ne se suppose pas.** Chaque pool a son
seuil mesuré par aller-retour EXACT via QuoterV2 on-chain (buy puis sell à
l'état actuel, $100/$250/$1k/$5k) + gas live. Résultat : le seuil n'est
presque jamais le fee — c'est l'impact. Exemples : xdp fee 0,01 % mais seuil
0,49 % à 1 k$ (impact 0,47 %) ; AERO fee 0,05 % mais seuil 1,34 % à 1 k$ ;
SOL fee 0,30 % mais seuil 49 % à 5 k$. Quiconque classe par fee seulement
se trompe d'un facteur 10 à 100.

**Choix 2 — Le move se mesure sur le leader, pas sur le DEX.** Pour les
tokens listés Binance : sigma_4s = écart-type des rendements 1 min
(120 bougies) / √15 — la volatilité du leader sur la fenêtre du trade.
Pour les non listés : |Δh1|/60/√15, proxy grossier déclaré (il sous-estime
probablement les vrais mouvements 4 s — mais même en le multipliant par 10,
aucun non listé ne passe son seuil).

**Choix 3 — Le score EV pénalise l'absence de signal.** Un token non listé
Binance n'a PAS de signal order book : il ne peut pas être un candidat
lead-lag, seulement un pari momentum. Facteur 0,15 (pas 0, pour ne pas
cacher les gros mouvements : ELSA −29 % reste visible dans le tableau).

**Choix 4 — Le turnover comme second critère.** vol24/liquidité : une pool
qui tourne 23× par jour (WETH) offre des fenêtres ; une pool qui tourne
0,04× (PLAY) n'offre rien — le prix y est stale mais intraidable.

## 4. Les deux découvertes qui changent la suite

### Découverte A — Les top pools de Base ne sont PAS Uniswap V3
Sur les 80 top pools GeckoTerminal (pages 1–4), les plus grosses sont
**Aerodrome Slipstream** (AERO, SOL, HYPE, VELVET, KNTQ, CTR), **PancakeSwap
V3** (WETH/USDC 0,01 % la plus grosse : 2,95 M$ de réserve, 28 M$/jour ;
ELSA, PLAY) et **Uniswap V4** (VVV). Le contrat du repo ne connaît que
Uniswap V3 : il ne voit qu'une minorité du volume Base. **Conséquence :**
même un scan parfait en V3 rate les vraies grosses pools. La prochaine étape
experte logique est de MESURER les pools Aerodrome Slipstream (même math
de liquidité concentrée, autre factory/quoter) — sans prétendre qu'elles
seront rentables : leur impact à taille réelle reste à mesurer.

### Découverte B — Les petites pools sont PIRES pour le lead-lag, pas meilleures
La thèse d'Ismail (« les gros mouvements sont dans les petites pools ») est
vraie pour le mouvement brut (ELSA −29 %, PLAY −10,7 %, CTR −5,7 % en 24 h)
mais fausse pour le trade : le seuil explose avec la finesse de la pool.
À 1 000 $ : WETH 0,066 % → VIRTUAL 0,353 % → AERO 1,336 % → SOL 1,856 % →
ELSA 8,14 % → PLAY 75,8 % → CTR 92 %. Même à 100 $ : PLAY 23,6 %, CTR 29 %,
PROS 19,3 %. **Le mouvement doit être 10 à 1 000× plus gros que sur les
majors pour simplement couvrir les coûts — et il ne l'est que 2 à 10× plus.**
C'est la réfutation chiffrée de la thèse, pas une opinion.

## 5. Alternatives rejetées (et pourquoi)

- **Tokens « c » (actions tokenisées : NVDAc, MSTRc, TSLAc, METAc, GOOGLc…) :**
  plus gros volumes et mouvements du jour (−5 % à −12 %), mais PAS listés
  Binance — leur leader est l'action NASDAQ elle-même, pas Binance. Piste
  séparée (leader = cours de l'action, données gratuites Yahoo/Stooq ; le
  token trade 24/7, l'action 9h30–16h ET — le gap d'ouverture est le
  signal), hors scope de ce scan Binance → Base. À explorer si le lead-lag
  Binance est abandonné.
- **Pools Aerodrome / PancakeSwap V3 / V4 :** hors scope du contrat repo
  (V3 Uni seulement). Rejetées pour CE scan, pas pour toujours — voir §4A.
- **PEPE sur Base :** volume 366 $/jour, pool morte — exclu.
- **Majors seules :** déjà prouvées 0 opportunité (0/992 quotes, 61 065
  quotes temps réel, 12 min lead-lag) — gardées comme contrôle, pas comme
  réponse. Ironie du scan : elles restent les « meilleures » parce que leur
  seuil est le plus bas.
- **Momentum brut sans signal Binance :** ce n'est plus du lead-lag, c'est
  du trading directionnel sur des micro-caps — autre jeu, autre risque
  (exit fin, honeypot, impact). Non recommandé ici.

## 6. Caveats honnêtes

- **Volatilité ≠ edge prévisible.** sigma_4s est une volatilité
  INCONDITIONNELLE. Le signal order book (imbalance) est CONDITIONNEL :
  quand l'imbalance est extrême, le mouvement suivant peut dépasser sigma
  de plusieurs fois. Ce scan ne peut pas l'exclure — c'est exactement ce
  que la validation paper-trade mesure (corrélation imbalance → move).
- **Proxy grossier pour les non listés.** |Δh1|/60/√15 sous-estime
  probablement les vrais mouvements 4 s. Même ×10, aucun ne passe.
- **Fenêtre courte, marché baissier.** Mesures du 2026-11-25 ~10:45 UTC,
  marché en baisse (BTC −1,3 %, ETH −2,2 %, small caps −5 % à −30 %).
  Les sigmas sont ceux d'une journée agitée — en journée calme ils sont
  plus petits, pas plus grands.
- **QuoterV2 = état actuel.** Le coût aller-retour est mesuré à l'instant T ;
  la liquidité par tick bouge. Les seuils sont des ordres de grandeur
  stables sur la journée, pas des constantes.
- **VIRTUAL est en WETH, pas en USDC.** Son seuil est calculé en WETH
  (converti en $ au prix ETH du moment) — comparable, mais la jambe de
  sortie est WETH, pas USDC.

## 7. Recommandation d'expert

**Paper-trader 3 candidats, 7 jours, 24/7 — puis STOP si le verdict est 0 :**

| # | Candidat | Pourquoi lui (et pas un autre) | Taille paper |
|---|---|---|---|
| 1 | **WETH/USDC 0,01 %** `0xb4cb8009` | Seuil le plus bas (0,066 % à 1 k$, 0,035 % à 250 $) ; seule P(move > seuil) > 0 (0,09 %) ; turnover 23,6× | 250 $–1 000 $ |
| 2 | **cbBTC/USDC 0,05 %** `0xfbb6eed8` | 2e seuil le plus bas (0,108 %) ; pool la plus profonde (6,1 M$) — impact stable | 1 000 $ |
| 3 | **VIRTUAL/WETH** `0x9c087Eb7` | Seul petit candidat listé Binance ; sigma le plus haut (0,033 %) ; imbalance achat +0,58 mesuré ; le test décisif de la thèse « small pools » | 100 $–250 $ |

**Protocole :** le système paper-trade existant (order book Binance →
mouvement prédit → entrée si net prévu > 0, seuil par pool). Durée 7 jours.
**GO :** ≥5 entrées/semaine avec net prévu > 1 $ ET corrélation
imbalance → move |r| ≥ 0,3. **STOP (l'un ou l'autre suffit) :**
0 entrée en 7 jours, ou |r| < 0,1, ou meilleur net prévu < 0,5 $.
Si STOP : **abandonner le lead-lag Binance → Uni V3 Base** et, dans l'ordre :
(1) mesurer les pools Aerodrome Slipstream (la vraie liquidité Base) ;
(2) sinon pivoter vers les bug bounties / audit contests — le meilleur
chemin 0 $ depuis la mort de la route Curve.

**Ce que je NE recommande pas :** entrer en réel sur aucun de ces 3
candidats aujourd'hui (P ≤ 0,09 % = pas d'edge mesurable), ni augmenter
la taille pour « compenser » (l'impact grandit avec la taille — voir
SOL : 49 % à 5 k$), ni paper-trader les 8 autres (seuils 0,49 % à 92 %,
aucun signal Binance pour 6 d'entre eux).

## 8. Sources & reproductibilité

- GeckoTerminal top pools Base, pages 1–4, 2026-11-25 ~10:43 UTC (80 pools).
- DexScreener paires (dex, labels, txns, volume, priceChange, liquidité),
  2026-11-25 ~10:43–10:45 UTC.
- On-chain Base (RPC public mainnet.base.org, fallback Alchemy en mémoire,
  jamais logué) : `factory.getPool`, `fee()`, `slot0()`, `liquidity()`,
  `decimals()` ; QuoterV2 `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a`
  (quoteExactInput, path 1 hop).
- Binance (data-api.binance.vision) : `/api/v3/depth` (limit 1000),
  `/api/v3/klines` 1m × 120, `/api/v3/ticker/price` ETHUSDT.
- GoPlus `token_security/8453` (honeypot/taxes, best-effort).
- Reproduction : `cd ~/workspace/crypto-base-flashloan-bot &&
  .venv/bin/python leadlag/expert_scan.py` (~3 min, lecture seule).
