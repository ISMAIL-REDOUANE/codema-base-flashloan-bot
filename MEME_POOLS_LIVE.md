# Meme pools LIVE sur Base — 2026-11-24 19:50 (Africa/Casablanca, = 19:50 UTC)

**Scan en direct, lecture seule. Aucun trade, aucun fond, aucune clé privée.**

## Verdict en 10 secondes

**Il n'y a AUCUN meme coin petit avec 2 listings DEX sur Base en ce moment.**
Sur 20 candidats vérifiés un par un (liquidité 5 000–100 000 $, créés < 72 h),
**0 ont une 2e paire** — donc **0 spread calculable, 0 arbitrage cross-DEX possible
maintenant**. Ce n'est pas un échec du scan : c'est le marché tel qu'il est à 19:50.

**Réponse directe à la question d'Ismail (« goliya k pool liktkhdem 3lihom nta ») :
on ne travaille sur AUCUN pool pour l'instant, parce qu'il n'y en a aucun qui
remplit les critères. Le travail du bot, c'est de SURVEILLER ces 20 tokens et
d'attraper le moment où une 2e pool apparaît** — un meme naît presque toujours
sur UN SEUL DEX (ici : Uniswap V2 ou V4), et la 2e cotation n'arrive que des
heures/jours plus tard, si le token survit.

## Méthode (reproductible)

1. **GeckoTerminal** `GET /networks/base/new_pools` pages 1–10 → 200 newest pools,
   créés 2026-11-24 17:02 → 19:47 UTC. Filtre : réserve 5 000–100 000 $,
   quote WETH ou USDC, créé < 72 h → **20 candidats**.
2. **DexScreener** `GET /latest/dex/tokens/{token}` pour chacun des 20 → toutes
   les paires Base du token, prix + liquidité + volume 24 h.
3. **GeckoTerminal** `GET /networks/base/tokens/{token}/pools` pour chacun des 20
   (2e source) → confirme 1 seule pool par token dans les 20 cas.
4. **GoPlus** `token_security/8453` sur le top 8 par volume.
5. Contre-vérification : **GeckoTerminal trending pools Base** → que des gros
   tokens anciens (VVV, AERO, SOL, NVDAc…), réserves 200 k$–21 M$, aucun petit meme.
6. Script du scan (relançable) : `meme_scan_live.py` ; données brutes :
   `meme_scan_2026-11-24.json` dans ce dossier.

### Limite de couverture — à lire avant de conclure sur 72 h

La fenêtre 72 h n'est **pas** couverte en entier : GeckoTerminal renvoie une
erreur 401 (rate limit) après ~10 appels rapprochés, donc le scan s'arrête à
la page 10 (pools créés à partir de 17:02 UTC, soit ~2 h 45 de recul). Un
redémarrage du service a aussi effacé les fichiers temporaires du 1er passage ;
les données ont été re-vérifiées en direct (2e passage, mêmes résultats).
**Conclusion honnête : 0 opportunité sur les 200 newest pools ; pour les
72 h complètes, il faudrait un scan paginé lent (1 appel / 3 s) ou une clé
GeckoTerminal.** Le constat structurel reste valable : les nouveaux memes
naissent sur 1 seul DEX.

## Les 20 candidats vérifiés — classés par volume 24 h

Spread = N/A partout : 1 seule paire par token, donc pas de 2e prix à comparer.
Prix en USD (DexScreener), liquidité en USD (DexScreener), volume 24 h en USD.
Âge = heure de création de la pool (UTC, 24 nov 2026).

| # | Token (adresse) | DEX | Liquidité | Vol 24 h | Créée | Spread | Drapeau rouge |
|---|---|---|---|---|---|---|---|
| 1 | **Antropic** `0x39632e…287a96` | Uni V4 | $13 631 | $61 025 | 17:41 | N/A — 1 paire | GoPlus : mintable=1, pausable=1, holders=0 ; copie du nom « Anthropic » |
| 2 | **USOE** `0x2b2ab7…67227` | Uni V4 | **$12,61** ⚠️ | $50 919 | 17:40 | N/A | Liquidité quasi nulle malgré $50k de volume — chiffres incohérents |
| 3 | **VTC6⚡️** `0x29ab93…4f23b` | Uni V4 | $1 896 | $37 484 | 17:41 | N/A | Liquidité très faible vs volume |
| 4 | **AODF** `0x1ba969…10cbd2` | Uni V4 | **$16,31** ⚠️ | $37 477 | 17:40 | N/A | Liquidité quasi nulle malgré $37k de volume |
| 5 | **LUNC** `0x24fecd…31fb9d` | Uni V4 | **$16,41** ⚠️ | $36 454 | 17:40 | N/A | Copie du ticker « LUNA CLASSIC » ; liquidité quasi nulle |
| 6 | **XTruth Oil (XTO)** `0x34b5bb…15a9ae` | Uni V4 | $3 570 | $34 099 | 17:40 | N/A | Cluster 17:40 (voir § cluster) |
| 7 | **AOTF** `0x0cc92f…3c6c5` | Uni V4 | **$12,30** ⚠️ | $32 422 | 17:40 | N/A | Liquidité quasi nulle malgré $32k de volume |
| 8 | **DOTF** `0x160e6a…46e795` | Uni V4 | **$1,44** ⚠️ | $32 253 | 17:40 | N/A | Liquidité quasi nulle ; prix GT ≠ prix DS (×1000) |
| 9 | **AODT🔥** `0x41f21e…ffa2d09` | Uni V4 | $1 874 | $30 750 | 17:40 | N/A | Cluster 17:40 |
| 10 | **URPS** `0x24fdd0…44025d8` | Uni V4 | $1 542 | $30 060 | 17:40 | N/A | Cluster 17:40 ; prix GT ≠ prix DS (×1000) |
| 11 | **NOTF** `0x522b0a…9acb29e` | Uni V4 | $36 577 | $10 115 | 19:30 | N/A | Le plus « propre » en liquidité, mais 1 seule paire |
| 12 | **GONDOLA** `0x1baaeaa…65b72` | Uni V4 | $16 576 | $6 624 | 19:05 | N/A | 1 seule paire |
| 13 | **cCAT** `0x822c2c…faa248` | Uni V2 | $16 381 | $4 862 | 18:03 | N/A | 1 seule paire ; le seul V2 avec volume réel hors cluster |
| 14 | **STELLAR (XLM)** `0xa6cd08…bc4f1` | Uni V2 | $54 980 | $2 384 | 19:31 | N/A | Copie du ticker XLM ; 1 seule paire |
| 15 | **NADF🔥** `0xcee886…17924c3c` | Uni V4 | $67 212 | $2 351 | 17:20 | N/A | Prix $35,32 / FDV $23,4 M — incohérent, à ne pas toucher sans vérif on-chain |
| 16 | **ANTHROPIC** `0x7efb01…c30e3` | Uni V2 | $10 809 | $661 | 19:44 | N/A | 2e token « Anthropic » en 2 h — copie du n°1 ; 1 seule paire |
| 17 | **clankmaxxxing** `0xeb2220…cfa8fd` | Uni V4 | $3 359 | $0,16 | 18:19 | N/A | Volume quasi nul — mort-né |
| 18 | **PR** `0x6afcda…cb07` | Uni V4 | $16 657 | $0,07 | 18:00 | N/A | Volume quasi nul — mort-né |
| 19 | **SCHAT** `0x4861fa…5fee1` | Uni V4 | $10 036 | $0,02 | 18:34 | N/A | Copie « SNAPCHAT » ; volume nul — mort-né |
| 20 | **SANTA** `0xdd46d3…81dba3` | Uni V4 | $8 577 | $0,01 | 18:32 | N/A | Via Bankr ; volume nul — mort-né |

Adresses complètes : `meme_scan_2026-11-24.json` (champ `candidates[].token`
et `ds_pairs[].pair`).

### Ce que les chiffres disent vraiment

- **14/20 pools sont Uniswap V4, 6/20 sont V2.** Les nouveaux memes naissent
  maintenant surtout en V4. Le bot v1/v2 ne sait gérer que V2 (+ quoter V3) :
  sans support V4, il est aveugle sur ~70 % des lancements.
- **Les chiffres de liquidité DexScreener pour les pools V4 sont faux ou
  incomplets** (ex. $1,44 de liquidité avec $32 253 de volume en 24 h —
  impossible en trading réel). Pour les mêmes pools, GeckoTerminal donne une
  réserve 4 à 7 000× plus élevée (ex. DOTF : DS $1,44 vs GT $10 506).
  **Ne jamais décider sur la liquidité DS d'une pool V4 : lire les réserves
  on-chain** (ou, pour V4, la liquidité du PoolManager).
- **Les prix GT et DS divergent de ~×1000 sur plusieurs pools V4**
  (URPS, DOTF, AODF, AODT, XTO). Une seule source de prix pour une V4 =
  dangereux. Le preflight doit croiser 2 sources avant d'exécuter.
- **Cluster de lancement 17:40–17:41** : 10 tokens créés en ~45 secondes
  (Antropic, VTC6, AOTF, USOE, LUNC, URPS, XTO, DOTF, AODF, AODT),
  tous V4, tous $30k–$61k de volume affiché, tous liquidité DS $1–$16.
  Thème « pétrole / réserve US » (USOE, DOTF, XTO, URPS…). Ça ressemble à
  un seul opérateur qui lance des tickers en série, pas à 10 memes organiques.
  Volume élevé + liquidité quasi nulle = chiffres non fiables → **à exclure
  du trading tant que les réserves on-chain ne sont pas vérifiées**.
- **Copies de noms partout** : ANTHROPIC vs Antropic (2 tokens différents),
  STELLAR(XLM), SNAPCHAT, LUNA CLASSIC, Base Santa. Les memes « petits sans
  concurrence » d'aujourd'hui sont majoritairement des copies — la concurrence
  n'est pas sur le prix, elle est sur l'attention, et le risque de rug est élevé.

## GoPlus (top 8 par volume)

- **Antropic** `0x39632e…` : honeypot = 0, buy/sell tax = vide, blacklist = 0,
  open source = 1 — MAIS **mintable = 1, transfer pausable = 1, holders = 0,
  creator = 0,05 %**. Pas un honeypot détecté, mais le créateur peut encore
  minter et mettre le transfert en pause → **risque, pas un feu vert**.
- **Les 7 autres du top 8** (USOE, VTC6, AODF, LUNC, XTO, AOTF, DOTF) :
  **aucune donnée GoPlus** — trop récents / pas indexés. Le filtre GoPlus du
  scanner doit donc traiter « pas de données » comme **UNKNOWN = ne pas trader**,
  jamais comme « OK » (c'est déjà la règle v2, à garder).

## Ce que ça change pour le bot

1. **Aucune paire à surveiller en exécution pour l'instant.** La watchlist
   ci-dessous est une liste d'ATTENTE, pas une liste de trades.
2. **Le scanner doit détecter l'apparition d'une 2e pool** (le vrai signal),
   pas seulement lister les nouveaux tokens. Poll DexScreener
   `/latest/dex/tokens/{token}` pour chaque token de la watchlist, et alerter
   dès que `n_pairs` passe de 1 à 2.
3. **Support V4 obligatoire** avant de trader ces tokens (14/20 en V4).
   Sans V4, le bot ne voit que 6 tokens sur 20.
4. **Vérification des réserves on-chain obligatoire** avant tout `decide()` :
   les chiffres DS/GT pour les V4 ne sont pas fiables (liquidité $1,44 avec
   $32k de volume, prix ×1000 entre sources).
5. **GeckoTerminal rate-limite vite** (401 après ~10 appels rapprochés) :
   le scanner doit mettre en cache et espacer les appels (≥ 3 s), avec
   DexScreener en source principale.

## Watchlist — prochaine étape du scanner

Surveiller ces 20 adresses (fichier JSON joint) ; priorité haute = liquidité
réelle $10k+ ET volume réel : **NOTF, GONDOLA, cCAT, XLM, ANTHROPIC**
(+ Antropic avec prudence GoPlus). Priorité basse / exclure tant que les
réserves on-chain ne sont pas confirmées : tout le cluster 17:40
(USOE, VTC6, AODF, LUNC, XTO, AOTF, DOTF, AODT, URPS) et NADF (prix incohérent).
Relancer ce scan toutes les 2–4 h : une 2e pool apparaît typiquement dans les
24–72 h si le token survit, et c'est là que le spread — donc l'arbitrage —
peut exister.

---
*Sources : api.geckoterminal.com (new_pools p.1–10, token pools, trending pools),
api.dexscreener.com (token-pairs ×20), api.gopluslabs.io (token_security 8453).
Généré 2026-11-24 19:50 Africa/Casablanca. Lecture seule.*
