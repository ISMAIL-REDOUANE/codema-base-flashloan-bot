# Recherche avancée — Bot Flash Loan Base / meme coins sghar (v2)

**Date de vérification : 2026-11-24. Recherche seulement — aucun fond réel, aucune clé privée, aucun déploiement.**
**Règle d'Ismail : min profit 3 $ (config.yaml déjà à jour). Objectif : gagner, ou au minimum ne pas perdre.**

> Lecture en 30 secondes : l'arbitrage 2-DEX classique sur les grosses paires (WETH/USDC)
> est **saturé en 2026** — une étude Base indépendante a trouvé **0 opportunité rentable
> sur 992 quotes** après frais. La seule place où il reste un edge, c'est exactement
> celle que vise ce bot : **petits meme coins, faible liquidité (5k–100k $), spreads
> de 5–20 %, avec des filtres anti-rug très stricts et une simulation avant chaque
> broadcast**. Mais même là, la latence et les bots MEV décident de presque tout.
> Le bot v1 a raison sur le sizing et sur le gas (0 $ sur les perdants). Il lui manque :
> les vraies quotes V3/V4, le flux Flashblocks/Denim, la protection MEV, et les
> garde-fous (circuit breaker, perte max / jour).

---

## 0. Changement majeur que v1 ne connaît pas : Base Denim (5 nov 2026)

C'est la découverte la plus importante de cette recherche, elle change la latence :

- **Denim est live sur Base mainnet depuis le 5 novembre 2026 : blocs canoniques
  toutes les 200 ms (5 blocs/seconde), Flashblocks retiré.**
  Source : https://tatum.io/blog/best-base-rpc-providers-2026
  et https://chainstack.com/learn/compare/best-base-rpc-providers-for-ai-agents-2026/
- Avant Denim : bloc 2 s découpé en 10 Flashblocks de 200 ms, ordre verrouillé
  par Flashblock. Après Denim : bloc canonique 200 ms directement.
  Source : https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120
  et https://chainstack.com/what-are-flashblocks/
- Conséquence : **la fenêtre pour capter un arbitrage est ~200 ms, pas 2 s.**
  Un bot Python qui poll toutes les 20 s (comme `bot/searcher.py` dans les repos
  classiques) arrive **100× trop tard**. Il faut un WebSocket `pendingLogs` /
  `eth_subscribe` + une recherche de cycle en quelques millisecondes, ou accepter
  de ne capter que les spreads qui durent plusieurs blocs (gros spreads de meme
  coins illiquides — justement notre cible, pas les paires liquides).
- Le flux public Flashblocks (`wss://mainnet.flashblocks.base.org/ws`) cité dans
  les mesures d'octobre 2026 est **à re-vérifier après Denim** avant de s'appuyer
  dessus. Ne pas coder en dur une URL pré-Denim.

---

## 1. GitHub — repos classés (vérifiés 2026-11-24)

### 1.1 À COPIER / S'INSPIRER

| # | Repo | Stars (vérifiés) | Stratégie | Verdict |
|---|---|---|---|---|
| 1 | [starky2000/base-flash-arb-lab](https://github.com/starky2000/base-flash-arb-lab) | 3 (15 oct 2026, 7 commits) | Cross-DEX flash USDC→WETH→USDC, Uniswap V3 + PancakeSwap V3 + Uniswap V4 sur Base ; `arbcheck` = vérificateur de quotes par quoter réel ; fork replay Foundry ; liquidations Aave ; UniswapX | **COPIER LA MÉTHODE, PAS L'ESPOIR.** C'est le repo le plus utile : il prouve par la mesure que les majors ne paient pas, et il donne le pattern à suivre : adapter par venue, quote exacte du quoter, refus de chiffrer un net si le gas n'est pas prix, `scan → replay fork → preflight eth_call → 1 seul live send` avec réserves de perte ($2/jour, $20 total). 88 tests Python + `forge test`. Licence AGPL-3.0. |
| 2 | [akari-sora/aave-oracle-lag-arb](https://github.com/akari-sora/aave-oracle-lag-arb) | 40 (30 oct 2026, 15 commits) | Oracle-lag : emprunter WETH à Aave au prix oracle Chainlink, vendre sur DEX quand le DEX est 10–30 % au-dessus, racheter après convergence. Contrat `OracleLagArb` (flash swap Uniswap V3), bot TypeScript multi-chaînes (dont Base), deleverage auto si health factor baisse | **INSPIRER, NE PAS COPIER AVEUGLEMENT.** Bonne idée à ajouter en v3 comme 2e stratégie (elle ne dépend pas d'un spread entre 2 DEX, mais d'un écart oracle vs DEX — c'est arrivé le 29 oct 2026, crise Binance). Mais ce n'est PAS un arbitrage sans risque : c'est un short ETH à levier, liquidable si ETH monte. Le README le dit lui-même. |
| 3 | [manuelinfosec/flash-arb-bot](https://github.com/manuelinfosec/flash-arb-bot) | 75 (créé 31 juil 2022, 7 commits) | Aave V3 flash loan, Uniswap V3 ↔ SushiSwap, scanner Node.js off-chain qui n'appelle `startArbitrage` que si le profit estimé après frais/gas est positif | **INSPIRER (architecture).** Le pattern scanner off-chain + exécution on-chain est le bon, et c'est celui de notre v1. **Dépassé :** Arbitrum seulement (pas Base), adresses 2022, pas de V4, pas de Flashblocks/Denim, pas de filtre honeypot. Ne pas copier les adresses. |
| 4 | Flashbots `simple-arbitrage` (cité dans [Alpha Book — On-Chain Market Making](https://book.longcipher.com/en/blog/dex-market-making-lvr/)) | non vérifié dans cette passe (ne pas citer de nombre d'étoiles) | Baseline MEV Flashbots : watch mempool locale, arbitrage instantané DEX↔DEX et DEX↔CEX | **INSPIRER (baseline).** C'est la référence historique pour la structure searcher. Mais c'est du Ethereum L1 / mempool public — sur Base (mempool privé du séquenceur, ordre par priority fee) il faut l'adapter, pas le transplanter. |
| 5 | [freefilm010/aiqtp-omni-nexus — `gasless-bot`](https://github.com/freefilm010/aiqtp-omni-nexus/blob/HEAD/gasless-bot/README.md) | repo global, pas de stars vérifiées ici | ERC-4337 + paymaster Pimlico (gas sponsorisé), flash loan Aave V3, arbitrage Uniswap V3 ↔ SushiSwap + liquidations Aave (bonus 5–10 %) | **INSPIRER (idée gasless + liquidations).** L'idée « le paymaster paie le gas » est intéressante, mais : Arbitrum seulement, confiance dans un paymaster tiers, et une liquidation ratée coûte quand même du temps/latence. À étudier en v3, jamais en v1. |

### 1.2 À ÉVITER

| Repo | Pourquoi éviter |
|---|---|
| [cjthoma1/flash-loan-bot](https://github.com/cjthoma1/flash-loan-bot) — 74 stars | **Aave V2.** V2 est dépassé ; notre contrat est en V3 (`flashLoanSimple`, fee 0,05 %). Copier V2 = mauvaises interfaces, mauvais frais. |
| `sOLarFLaMEPyL/Arbitrage_Mev_BOT` — 613 stars, 403 forks | **SCAM / honeypot, À NE JAMAIS UTILISER.** Analyse : https://www.derp.ca/research/arbitrage-mev-bot-honeypot-scam/ — un import caché (`FlashLoan-v2/Balancer-v3`, faux compte qui imite Balancer Labs) donne à un tiers le retrait total des ETH/tokens déposés. Leçon : **613 stars ne veulent rien dire.** Ne jamais déployer un contrat dont on n'a pas lu chaque import, ne jamais envoyer d'ETH à un contrat « prêt à l'emploi » trouvé sur GitHub/YouTube. |
| Tout repo « MEV bot prêt, dépose 0,5–1 ETH, clique Launch() » (YouTube/GitHub/Telegram) | Même piège que ci-dessus, quasi systématiquement. Aucun vrai bot rentable ne se distribue comme ça. |
| `amm-arbitrageur` (1 988 stars, dernier commit déc 2022, cité dans https://web3feeds.sifted.network/top100/amm) | Historique / pédagogique seulement. Pré-Base, pré-V4, pré-Flashblocks. |
| `AAVE-FLASHLOAN` (67 stars, mai 2025, cité dans https://web3feeds.sifted.network/top100/amm) | Non audité dans cette passe, pas de preuve de mesure live. Ne pas copier sans lecture complète. |

**Règle GitHub retenue :** on ne copie que (a) la méthode de mesure
(`arbcheck` : quote du quoter réel, pas de prix inventé), (b) le pipeline
`scan → fork replay → preflight → 1 send`, (c) les garde-fous (contrat en
pause par défaut, owner/operator séparés, adresses épinglées, pas d'appels
arbitraires). On ne copie jamais un contrat non lu ligne par ligne.

---

## 2. Stratégies — ce qui marche encore en 2026, ce qui est saturé

Classement honnête, de la plus réaliste pour ce bot à la plus saturée.

### 2.1 Encore jouable (notre terrain)

**1. Cross-DEX sur meme coins illiquides (notre v1) — LA SEULE stratégie
de base encore ouverte à un petit bot.**
Pourquoi : sur WETH/USDC, les spreads sont de quelques bp et les bots
pros les ferment en millisecondes (voir §5 : 0/992 positifs). Sur un meme
coin à 5k–100k $ de liquidité, un gros achat/vente décale le prix de 5–20 %
entre Aerodrome et Uniswap V2, et le spread **dure plusieurs blocs** parce
que peu de bots surveillent ce token. C'est exactement le filtre
`scanner.min_liquidity_usd 5 000–100 000` + `max_age_hours 72` de v1.
Limite : le spread est gros en % mais petit en $ (optimal ~$790 dans notre
démo → +$71). Il faut beaucoup d'opportunités, pas une grosse.

**2. Liquidations Aave V3 sur Base — 2e stratégie la plus réaliste, à
ajouter en v2/v3.**
Bonus : 5 % sur WETH/USDC, 6 % cbBTC/wstETH, 7,5–10 % sur les collatéraux
risqués. Source : https://blog.solvinc.io/posts/aave-liquidation-sniper-python-scanner/
— sur 24 h calmes, 54 liquidations Base, ~$92k de dette remboursée,
~$7 400 de bonus captés en un jour, le plus gros liquidateur en a fait 19.
Le capital n'est pas le problème (flash loan). Le problème, c'est de
**savoir quels wallets vont basculer avant les autres bots** : surveiller
les health factors 1,00–1,05 en continu, avec un scanner Python en lecture
seule. Attention au piège : l'étude `base-flash-arb-lab` n'a trouvé **aucune**
position sous HF 1 sur ses 40 comptes échantillonnés à un instant T — les
liquidations arrivent par vagues (jours de crash), pas en continu. Et depuis
2026, 97 % du bonus Morpho Blue sur Base passe par des enchères Chainlink SVR
(Atlas) où les gagnants reversent 80–95 % du bonus — le « open race » ne
laisse que les miettes. Source :
https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120
Verdict : à construire comme **scanner passif** (coût ~0), pas comme
stratégie principale.

**3. Oracle-lag (Aave oracle vs DEX) — opportuniste, rare, mais gros.**
Voir repo §1.1 n°2. Se produit lors d'événements (panne d'exchange, hack,
29 oct 2026 : ETH 10–30 % au-dessus de l'oracle). À garder comme alerte,
pas comme revenu régulier. Risque : position short à levier, liquidation
possible.

### 2.2 Saturé / mort pour un petit bot

**4. Cross-DEX 2-DEX sur paires liquides (WETH/USDC, WETH/cbETH, USDC/DAI)
— SATURÉ.** Preuve : `base-flash-arb-lab`, 992 combinaisons de quotes,
7 blocs historiques, tailles 200–20 000 USDC, **0 positive après frais**,
meilleur cas −0,1347 USDC (−0,2503 après gas).
Source : https://github.com/starky2000/base-flash-arb-lab
Les spreads sont plus petits que les frais pour les traverser. Un flash
loan enlève le besoin de capital, pas le besoin de battre la concurrence.

**5. Triangulaire / multi-hop sur majors — SATURÉ, sauf via V4.**
Formule : cycle rentable ssi `∏ taux > 1 + frais totaux + gas/taille`.
Plus de hops = plus d'inefficacité potentielle, mais aussi plus de frais
et de slippage par hop. La bonne implémentation est un graphe + Bellman-Ford
(cycle de poids négatif sur `w = −ln(taux)`) — voir
https://book.longcipher.com/en/mev/strategies/atomic-arb/ et
https://github.com/maxkru92/everything-claude-trading/blob/HEAD/skills/crypto/cross-chain-arbitrage/SKILL.md
Sur les majors, les cycles sont fermés en ms par les pros. Sur les memes,
le triangulaire (MEME→WETH→USDC→MEME) peut exister, mais il faut le
**quoter exactement** (pas de prix mid approximatif).

**6. JIT liquidity (just-in-time) — NE MARCHE PAS avec un flash loan.**
Un flash loan doit être remboursé dans la même transaction ; le JIT
classique a besoin d'inventaire réel entre les transactions. Uniswap V4
(flash accounting, EIP-1153) ne change pas ça. Source : README
`base-flash-arb-lab` (conclusion n°2). À ne pas essayer.

**7. Sniping de lancement (acheter au bloc 0) — TRÈS RISQUÉ, déconseillé
comme stratégie principale.**
Un sniper achète quelques secondes après le lancement. Problèmes documentés :
rug (liquidité retirée après les achats), honeypot (achat OK, vente
impossible), taxe de vente, mint/freeze encore actifs, holders concentrés
(90 wallets = 90 % de l'offre dans un cas flaggé par Bubblemaps, token
MYSTERY, −75 % ensuite). Sources :
https://dev.moby.win/agents/strategies/memecoin-sniper-agent/ et
https://coinstats.app/news/1c3fe1285529eb0730ecd38e9d201d99cfd171d2525c7948bfd8174f5d900b1e_Bubblemaps-Flags-90Wallet-Sniping-Cluster-at-MYSTERY-Token-Launch/
et https://true402.dev/guides/base-sniper-bot-stack
La leçon : **le vetting est là où l'argent fuit** — un token invendable
ne coûte pas un mauvais trade, il coûte **toute la position**. Notre v1
a raison d'exiger un âge minimum + des checks, pas d'acheter au bloc 0.
Si on fait du « nouveau » un jour, ce sera : trouver → **vetter** → suivre
le smart money, jamais acheter sans vetting.

**8. UniswapX / ordres Dutch — 0 rentable re-quoté au bloc de fill**
(25 ordres testés dans `base-flash-arb-lab`). À ignorer.

### 2.3 Nouveau en 2026 à surveiller (v3+)

- **Uniswap V4 sur Base** : singleton + flash accounting (multi-hop moins
  cher en gas) + hooks (frais dynamiques, ordres limites on-chain). Et
  depuis le 22 oct 2026, des **Aggregator Hooks** qui routent un pool V4
  vers des venues externes (rival pools). Source :
  https://substreams.dev/packages/uniswap-v4-base/latest et
  https://book.longcipher.com/en/blog/dex-market-making-lvr/
  Conséquence double : (a) notre quoter V2-only rate les routes V4
  (à ajouter), (b) les hooks agrégateurs **réduisent** les spreads
  cross-DEX — la fenêtre se referme encore.
- **Aero (ex-Aerodrome, fusion avec Velodrome nov 2025, Dromos Labs)** :
  DEX dominant sur Base (~$500–600M TVL), Slipstream = concentrated
  liquidity à frais dynamiques. Notre v1 ne connaît que le router
  Classic (`0xcF77…`) ; Slipstream a un autre router/quoter et des frais
  qui changent par événement. Il faut le quoter, sinon on rate la moitié
  du marché — et on se fait piéger par des frais dynamiques mal modélisés.
  Source : https://claudeskills.info/skills/austintgriffith/ethskills/building-blocks/

---

## 3. Comment NE PAS perdre — les défenses, par ordre d'importance

### 3.1 MEV / frontrunning / sandwich sur Base

- **Base n'a pas de mempool public comme Ethereum L1.** Le séquenceur a
  une mempool privée et ordonne par **priority fee dans chaque bloc de
  200 ms** (post-Denim). Le sandwich classique (voir ta transaction
  publique, acheter avant, vendre après) est donc beaucoup plus dur —
  mais pas impossible : un acteur qui voit ton ordre (builder, RPC)
  peut toujours te devancer. Source :
  https://mevdao.org/blog/mev-on-layer-2-how-arbitrum-base-and-optimism-order-transactions
- **Flashbots Protect (`rpc.flashbots.net`) est un RPC Ethereum L1,
  pas Base.** Ne pas le brancher tel quel sur Base en espérant une
  protection. Sur Base, la protection = (a) ne pas broadcaster une
  transaction dont le profit dépend d'un état public fragile, (b) atomicité
  du flash loan (tout ou rien dans une tx), (c) `minOutput` strict par
  jambe + deadline courte, (d) priority fee juste assez haute pour être
  inclus dans le prochain bloc, pas plus. Sources :
  https://graph.org/What-Is-Flashbots-and-How-Does-Protect-Stop-Frontrunning-11-06
  et https://mevdao.org/blog/flashbots-protect-vs-mev-blocker-which-private-rpc-should-you-use
  (attention : ces deux pages parlent d'Ethereum L1 ; la confusion
  Protect = protection sur Base est un piège classique).
- **Le vrai risque MEV pour nous, c'est la course à la latence, pas le
  sandwich.** Mesure Flashbots, oct 2026 : un bot qui réagit au flux
  public en **5–8 ms** (recherche de cycle ~2 ms, signature 0,7 ms,
  broadcast 1,3 ms) capte les opportunités ; « presque tout l'argent est
  décidé avant qu'un flashblock soit publié ». Un bot Python qui poll
  toutes les secondes arrive après la bataille. Source :
  https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120
- **Spam = la façon dont la plupart des bots perdent.** Étude 2025–2026
  (Base, juin 2025–fév 2026) : la recherche probabiliste (on envoie des
  tentatives répétées qui découvrent l'opportunité on-chain) ne fait que
  23 % de l'activité d'arbitrage mais **95 % du spam** et 20 % du gas
  de Base. Le taux de succès off-chain (découverte hors-chaîne) est de
  42,5 %, le meilleur des architectures. Source :
  https://token-research.com/research/tr-2624
  Autre étude (1,4 milliard de tx invariantes) : sur Base, **>90 % des
  bots d'arbitrage spéculatifs exécutent moins de 10 % de leurs tx avec
  succès** ; une fois les frais des tx ratées comptés, la part des bots
  profitables tombe de **82,1 % à 27,8 %**, et le profit agrégé des bots
  spéculatifs sur Base est **négatif : −28,07 ETH**. Source :
  https://token-research.com/research/tr-2539
  **Traduction : notre règle « simuler d'abord, ne broadcaster que les
  gagnants » est exactement ce qui sépare les 27,8 % qui survivent des
  autres. Il faut la garder et la durcir, jamais l'assouplir.**

### 3.2 Honeypot / rug / taxe — le filtre qui vaut plus que le sizing

Chiffre : sur 30 jours à nov 2026, **75–76 % des tokens scannés avaient
au moins un red flag** (honeypot, taxe, mint, owner, liquidité non
verrouillée, holders concentrés). Source : https://coinvote.cc/token-scanner?chain=base&address=0x1fa7a36f39b094321c265b3c8a995836008fdb0d&from=coin
Règles (GoPlus, `api.gopluslabs.io`, chaîne Base = 8453, gratuit sans clé
pour la base) — champs à checker : `is_honeypot`, `buy_tax`, `sell_tax`,
`is_open_source`, `is_proxy`, `can_take_back_ownership`,
`owner_change_balance`, `is_mintable`, `transfer_pausable`,
`is_blacklisted`, `holder_count`, liquidité verrouillée. Endpoints :
`https://api.gopluslabs.io/api/v1/token_security/8453?contract_addresses=0x…`
et DexScreener `https://api.dexscreener.com/latest/dex/tokens/{adresse}`
(300 req/min, sans clé). Sources :
https://ottermind.ai/skills/crypto-token-analyzer et
https://docs.spliceloom.com/data-providers
Seuils v1 (déjà bons, à durcir) :
- honeypot = **refus immédiat** (simulation buy + sell obligatoire) ;
- sell tax > 5 % (v1) → en pratique > 15 % = refus certain, 5–15 % = refus
  pour un arbitrage (la taxe mange le spread) ;
- mint encore possible / owner non renoncé / proxy upgradeable / transfer
  pausable / blacklist = refus ;
- liquidité verrouillée/brûlée < 90 % = refus, < 50 % = danger extrême ;
- top 10 holders ≥ 30 % (hors pools/burn) = refus — quelques vendeurs
  peuvent crasher le prix.

### 3.3 Simulation avant broadcast — la règle gas, version avancée

- **Sur Base, un revert on-chain coûte du gas** (même si le gas est
  bon marché : voir §4). La parade n'est pas le revert, c'est de ne pas
  envoyer : `eth_call` / `eth_estimateGas` + fork Anvil + Tenderly
  Simulation, **avec un plafond de fraîcheur** (candidat vieux de >2
  blocs = rejeté — c'est la règle de `base-flash-arb-lab` : preflight
  avec freshness cap, gas-price cap, cost cap, vérification du solde
  opérateur). Notre `executor.py` fait la simulation mathématique ;
  il lui manque la **simulation EVM réelle** (fork) avant broadcast.
- **Le gas n'est pas gratuit même quand il est petit : il se paie en
  série.** Un bot qui envoie 350 tentatives ratées pour 1 succès (chiffre
  cité pour Base dans https://coincub.com/blog/mev-invisible-tax/) paie
  350× le gas pour 1 profit. D'où : **1 seul candidat → 1 seule tx**,
  jamais de boucle « réessayer jusqu'à ce que ça passe ».

### 3.4 Garde-fous financiers (manquants en v1 — prioritaires)

- **Circuit breaker** : stop si perte nette du jour > X $ (ex. 20 $) ou
  si 3 reverts d'affilée → pause 1 h, alerte.
- **Perte max par trade = gas + 0** (atomicité : un arbitrage flash loan
  ne peut pas perdre plus que le gas, sauf bug de contrat — d'où l'audit).
  **Perte max par jour, par semaine** : à fixer dans `config.yaml`
  (pas de champ aujourd'hui).
- **Plafond de taille** : déjà 10 % de la plus petite réserve + $50k max
  (v1) — garder, et ajouter un plafond par token (pas 2 trades sur le
  même meme coin dans la même heure : évite de se faire piéger par un
  token qui se fait dumper).
- **Kill switch** : contrat en pause par défaut, `setPaused(true)` à
  distance, owner/operator séparés (pattern de `base-flash-arb-lab`).

---

## 4. Math avancée — sizing, Kelly, et le seuil de 3 $

### 4.1 Taille optimale : V2 (v1, correct) vs V3/V4 (manquant)

- **V2 (`x·y=k`)** : `out = y·in·(1−f) / (x + in·(1−f))`. Le prix moyen
  ≈ spot × (1 + in/x), le spot final ≈ spot × (1 + in/x)². C'est ce que
  fait `math_engine.py`, et c'est correct pour Aerodrome Classic /
  Uniswap V2 / Sushi V2. Source : https://orcacrypto.io/learn/advanced/amm-math/
- **V3 (concentrated liquidity)** : la liquidité `L = √(x·y)`, prix en
  `√P` ; réserves réelles `x = L·(1/√P − 1/√Pb)`, `y = L·(√P − √Pa)`.
  Un swap traverse des ticks ; la sortie ne se calcule **pas** avec la
  formule V2 — il faut le **QuoterV2** (`quoteExactInputSingle`) ou une
  simulation tick par tick. **Notre v1 n'a pas de quoter V3 : il rate
  (ou approxime mal) tous les pools V3/V4/Slipstream.** C'est l'amélioration
  n°1 (§6).
- **Règle de coût (Alpha Book)** : pour 2 pools de 5 000 WETH, le spread
  brut nécessaire monte avec la taille : 5 000 $ → +0,67 % suffit ;
  60 000 $ → +1,40 % ; 300 000 $ → +4,61 %. Source :
  https://book.longcipher.com/en/mev/strategies/atomic-arb/
  Traduction : **le spread nécessaire n'est pas fixe, il grandit avec la
  taille — c'est pour ça que le calcul doit chercher l'optimum, pas une
  taille fixe.** Notre `find_optimal_loan` (grille + raffinement) fait
  déjà ça pour V2 ; il faut la même chose avec des quotes V3 exactes.

### 4.2 Kelly — ce que v1 fait bien, et sa limite

- Formule binaire : `f* = p − q/b`, avec `b = gain moyen / perte moyenne`,
  `p` = proba de gain. Forme continue : `f* = μ/σ²`. Source :
  https://www.marketmaker.cc/blog/kelly-criterion-strategy-sizing/
- **Kelly plein est trop agressif** : il maximise la croissance mais avec
  une volatilité monstrueuse. La pratique : **Kelly quart (0,25×) ou
  moitié (0,5×)** — le quart capture ~75 % de la croissance pour moitié
  moins de volatilité. Notre `kelly_cap = 0,25` est donc le bon choix.
  Source : https://www.marketmaker.cc/blog/kelly-criterion-strategy-sizing/
  et https://affpapa.org/en/nevibecode/skills/kelly-criterion
- **Limite critique pour ce bot : Kelly exige ≥50 trades pour un calcul,
  100+ pour un demi-Kelly, et 0,10× pour une stratégie neuve de <30 trades.**
  Source : https://affpapa.org/en/nevibecode/skills/kelly-criterion
  **On n'a pas encore 50 trades réels. Donc le Kelly de v1 ne doit pas
  utiliser un `p` inventé (60 %) : il doit rester à 0,10× (nouvelle
  stratégie) tant qu'on n'a pas 50 trades simulés/fork, et utiliser la
  borne inférieure de Wilson pour `p` (ne pas gonfler le win rate avec
  un petit échantillon chanceux).**
- **Kelly ne s'applique pas au montant du flash loan** (remboursé
  atomiquement) : il s'applique au **capital propre à risque** = gas
  cumulé + risque de bug. C'est déjà la bonne interprétation dans
  `math_engine.kelly_size`, à garder.

### 4.3 Le seuil min profit 3 $ — verdict chiffré

Ismail a confirmé **min 3 $** (2026-11-24). Est-ce réaliste ?

**Oui, mais seulement si le gas est mesuré en direct, pas en dur.**

- Gas réel Base en 2026 : une tx simple ~$0,001–0,002 (Ethereum.org,
  snapshot 1–6 oct 2026) ; un swap ~$0,05–0,15 ; un arbitrage flash
  (~450k gas) à 0,05 gwei et ETH $3 000 = **~$0,07**. Sources :
  https://www.fogment.com/crypto-gas-fees-explained/ et
  https://www.nifmacademy.com/blog/post/322/crypto-trading
- **Problème dans v1 : `config.yaml` dit `gas_price_gwei: 0.05` et
  `gas_units: 450 000` (→ ~$0,07), mais `math_engine.Costs` a un défaut
  `gas_usd = 1,20 $` et un plancher de 0,10 $. Les deux ne se parlent pas.
  Avec un gas réel de $0,07, un seuil de 3 $ = **~43× le gas** — très
  conservateur, on rate des trades à +$1–2 qui seraient rentables.
  Avec un gas de $1,20 (hypothèse v1), 3 $ = 2,5× le gas — trop juste
  par rapport à la règle `net > gas × 3` (il faudrait 3,60 $).
  **Correction : unifier le gas (une seule source, calculée en direct
  depuis le RPC), et garder `net > gas × 3` comme règle, avec `min 3 $`
  comme plancher absolu.**
- **Mais le gas explose parfois :** le 29 oct 2026, le prix médian payé
  a atteint **254,75 gwei** (contre 0,054 gwei le 2 nov) — un swap à
  $70 au lieu de $0,015. Source :
  https://www.sonicwallet.com/learn/crypto/gas-fees-explained
  **Donc un seuil fixe de 3 $ est dangereux sans plafond de gas :**
  si le gas monte à $5, un trade à +$3 net « calculé » devient perdant.
  Il faut : `gas_price` lu en direct + `gas_price_max_gwei` (ex. 2 gwei :
  au-dessus, on ne broadcast rien) + re-simulation juste avant l'envoi.
- **Conclusion seuil : 3 $ est réaliste et sain pour des meme coins
  (spreads 5–20 %, nets de $10–70 dans nos scénarios), à condition de
  (a) mesurer le gas en direct, (b) garder `net > gas × 3`, (c) ajouter
  un plafond de gas. Sur les majors, 3 $ ne suffit pas : les spreads y
  sont < 0,1 %, donc presque aucun trade ne passe le seuil — c'est
  normal, ce n'est pas là qu'on gagne.**

### 4.4 Espérance de gain (EV) — la formule à ajouter

`EV = p_win × gain_moyen − p_perte × perte_moyenne − gas_moyen`
avec `p_win` estimé sur les **trades simulés/fork**, pas inventé.
Si EV ≤ 0 après 100 simulations, **on ne passe pas en live** — on
change de stratégie (autre DEX, autre tranche de liquidité, liquidation).
C'est le test go/no-go que `base-flash-arb-lab` a appliqué (et qui a
donné no-go sur les majors).

---

## 5. Chiffres réalistes 2026 — à quoi s'attendre vraiment

| Chiffre | Valeur sourcée | Source |
|---|---|---|
| Spreads cross-DEX, paires liquides Base | Quelques bp (4–40 bp entre pools V3) | https://github.com/starky2000/base-flash-arb-lab (quotes réelles : −4,4 bp à −175 bp vs meilleur) |
| Opportunités rentables, majors, 992 quotes | **0** | https://github.com/starky2000/base-flash-arb-lab |
| Spreads meme coins illiquides (5k–100k $) | 5–20 % (hypothèse de travail v1, à mesurer : c'est le spread qui rend le trade possible, pas une garantie) | Démo v1 : spread 20 % → net +$71,55 à $790 ; spread 2 % → SKIP |
| Gas Base, conditions normales | Swap $0,05–0,15 ; arbitrage ~450k gas ≈ $0,01–0,10 | https://www.fogment.com/crypto-gas-fees-explained/ ; https://www.nifmacademy.com/blog/post/322/crypto-trading |
| Gas Base, pic (29 oct 2026) | Prix médian 254,75 gwei ; swap ~$70 | https://www.sonicwallet.com/learn/crypto/gas-fees-explained |
| Taux de succès, bots d'arbitrage spéculatifs Base | >90 % des bots réussissent <10 % de leurs tx | https://token-research.com/research/tr-2539 |
| Bots profitables Base, après frais des tx ratées | **27,8 %** (contre 82,1 % avant de compter les ratées) ; profit agrégé **−28,07 ETH** | https://token-research.com/research/tr-2539 |
| Taux de succès, découverte off-chain | **42,5 %**, le meilleur des architectures | https://token-research.com/research/tr-2624 |
| Spam, recherche probabiliste | 23 % de l'activité, **95 % du spam**, 20 % du gas Base | https://token-research.com/research/tr-2624 |
| Liquidations Aave Base, 24 h calmes | 54 events, ~$7 400 de bonus, top liquidateur 19 trades | https://blog.solvinc.io/posts/aave-liquidation-sniper-python-scanner/ |
| Liquidations Morpho Blue Base, 30 jours | $620k de bonus, dont 97 % via enchères SVR (80–95 % reversés) | https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120 |
| Tokens scannés avec ≥1 red flag (30 j) | **75–76 %** | https://coinvote.cc/token-scanner?chain=base&address=0x1fa7a36f39b094321c265b3c8a995836008fdb0d&from=coin |
| Latence de réaction nécessaire | **5–8 ms** (log → tx signée) pour les paires liquides | https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120 |
| Blocs Base post-Denim | **200 ms** (5 blocs/s) | https://tatum.io/blog/best-base-rpc-providers-2026 |

**Pourquoi la plupart des bots perdent (synthèse) :**
1. Ils chassent les majors saturées (spreads < frais).
2. Ils spamment des tentatives on-chain (95 % du spam, gas cumulé > profits).
3. Ils utilisent des prix mid approximatifs au lieu des quotes exactes
   du quoter (le trade « rentable » sur papier revert ou sort perdant).
4. Ils ignorent les frais dynamiques (Slipstream), les taxes de token,
   et les honeypots (perte totale de la position, pas juste du gas).
5. Ils n'ont pas de plafond de gas : un pic de gas transforme un gain
   en perte.
6. Ils copient des contrats GitHub non lus (honeypot de 613 stars).

---

## 6. Top 10 améliorations pour v2 — classées par impact

| # | Amélioration | Impact | Fichier(s) à changer |
|---|---|---|---|
| 1 | **Quoter V3/V4 réel** : remplacer l'approximation V2 par `QuoterV2.quoteExactInputSingle` (Uniswap V3) + quoter Aerodrome Slipstream + Uniswap V4. Sans ça, tous les pools concentrés sont mal prix. | ★★★★★ Profit — sinon on trade à l'aveugle sur la moitié du marché | `math_engine.py` (nouveau module `quoter.py`), `config.yaml` (adresses V4/Slipstream), `RESEARCH.md` |
| 2 | **Gas en direct + plafond** : lire `eth_gasPrice` / `eth_feeHistory` à chaque décision, unifier le gas (supprimer le défaut `1,20 $` incohérent), ajouter `gas_price_max_gwei` (ex. 2) au-dessus duquel on ne broadcast rien. Garder `net > gas × 3` + `min 3 $`. | ★★★★★ Ne pas perdre — un pic de gas est la perte la plus bête | `math_engine.py` (`gas_cost_usd`, `Costs`), `executor.py`, `config.yaml` |
| 3 | **Simulation EVM réelle avant broadcast** : fork Anvil + `eth_call`/`eth_estimateGas` sur le vrai contrat, fraîcheur ≤ 2 blocs, comme `base-flash-arb-lab` (preflight). La simulation mathématique ne suffit pas : elle ne voit pas les taxes, les hooks, les frais dynamiques. | ★★★★★ Ne pas perdre — c'est le filtre qui attrape les honeypots et les taxes | `executor.py` (nouveau `preflight.py`), `contracts/FlashLoanArbitrage.sol` (déjà le filet `require`) |
| 4 | **Filtre GoPlus complet + simulation buy/sell** : brancher l'API GoPlus (`is_honeypot`, taxes, mint, proxy, pause, blacklist, lock) + DexScreener, avec refus dur sur chaque red flag (§3.2). Aujourd'hui `scanner.py` annonce le filtre sans l'appeler en direct. | ★★★★★ Ne pas perdre — un honeypot = perte totale, pas juste du gas | `scanner.py`, `config.yaml` (`scanner.*`) |
| 5 | **Flux temps réel post-Denim** : WebSocket `eth_subscribe` / `pendingLogs` sur les pools suivis, au lieu de poller. Mesurer la latence réelle (objectif : décision < 200 ms, sinon on ne chasse que les spreads qui durent plusieurs blocs). | ★★★★☆ Profit — sans ça on arrive après les pros | Nouveau `streamer.py`, `executor.py` |
| 6 | **Circuit breaker + limites journalières** : perte max/jour (ex. 20 $), 3 reverts d'affilée → pause 1 h, kill switch, contrat en pause par défaut, owner/operator séparés. | ★★★★☆ Ne pas perdre — empêche une boucle de pertes | `executor.py`, `config.yaml` (nouvelle section `limits:`), `contracts/FlashLoanArbitrage.sol` |
| 7 | **Kelly honnête** : passer à 0,10× tant que < 30 trades, borne inférieure de Wilson pour `p`, interdiction d'inventer `p = 60 %`. Ne calculer Kelly qu'après 50 trades simulés/fork. | ★★★★☆ Ne pas perdre — évite de sur-miser sur un edge imaginaire | `math_engine.py` (`kelly_fraction`, `kelly_size`) |
| 8 | **Scanner de liquidations Aave (passif, coût ~0)** : surveiller HF 1,00–1,05 sur Base, alerter, ne pas exécuter tant que le scanner d'arbitrage n'est pas rentable. 2e source de revenu, gratuite à observer. | ★★★☆☆ Profit — diversifie, sans capital | Nouveau `liquidation_scanner.py`, `config.yaml` |
| 9 | **Graphe multi-DEX + Bellman-Ford** : modéliser tous les pools suivis comme un graphe (sommets = tokens, arêtes = pools avec taux net de frais), détecter les cycles négatifs, au lieu de tester des paires 2 à 2. Inclure V4 et Slipstream. | ★★★☆☆ Profit — trouve les triangulaires que le 2-DEX rate | Nouveau `graph.py`, `math_engine.py` |
| 10 | **Journal + EV mesuré (go/no-go)** : logger chaque opportunité (spread, taille, net simulé, net réel, gas, raison du SKIP), calculer EV après 100 simulations fork, et **ne passer en live que si EV > 0**. Sans ce journal, on ne sait pas si on gagne ou si on a eu de la chance. | ★★★☆☆ Ne pas perdre — c'est le test qui a donné no-go sur les majors, il faut l'appliquer aux memes | Nouveau `journal.py` / `trades.jsonl`, `README.md` |

---

## 7. Top 10 pièges à éviter (avec sources)

| # | Piège | Conséquence | Source |
|---|---|---|---|
| 1 | Copier un « MEV bot prêt » GitHub/YouTube (613 stars) sans lire les imports | **Perte totale** : un tiers retire tous les fonds (import caché imitant Balancer) | https://www.derp.ca/research/arbitrage-mev-bot-honeypot-scam/ |
| 2 | Chasser WETH/USDC et les majors | 0/992 rentable après frais — on paie du gas pour rien | https://github.com/starky2000/base-flash-arb-lab |
| 3 | Spammer des tentatives on-chain (recherche probabiliste) | 95 % du spam, profit agrégé **−28,07 ETH** sur Base, seuls 27,8 % des bots restent profitables | https://token-research.com/research/tr-2539 ; https://token-research.com/research/tr-2624 |
| 4 | Utiliser un prix mid au lieu de la quote exacte du quoter | Le trade « rentable » revert ou sort perdant (frais, ticks, slippage) | https://github.com/starky2000/base-flash-arb-lab ; https://book.longcipher.com/en/mev/strategies/atomic-arb/ |
| 5 | Ignorer les frais dynamiques Slipstream / hooks V4 | Quote fausse, profit surestimé | https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120 |
| 6 | Acheter un meme coin sans vetting (bloc 0, sans GoPlus) | Honeypot / rug = **perte de toute la position**, pas juste du gas ; 75–76 % des tokens ont un red flag | https://dev.moby.win/agents/strategies/memecoin-sniper-agent/ ; https://coinvote.cc/token-scanner?chain=base&address=0x1fa7a36f39b094321c265b3c8a995836008fdb0d&from=coin |
| 7 | Seuil de profit fixe sans plafond de gas | Un pic (254 gwei le 29 oct 2026, swap $70) transforme un gain en perte | https://www.sonicwallet.com/learn/crypto/gas-fees-explained |
| 8 | Croire que Flashbots Protect protège sur Base | Protect est un RPC **Ethereum L1** ; sur Base, la protection = atomicité + minOutput + simulation, pas un RPC magique | https://graph.org/What-Is-Flashbots-and-How-Does-Protect-Stop-Frontrunning-11-06 ; https://mevdao.org/blog/mev-on-layer-2-how-arbitrum-base-and-optimism-order-transactions |
| 9 | Kelly plein ou `p` inventé (60 %) avec < 50 trades | Sur-mise, drawdown qui casse le compte ; il faut 0,10× et la borne de Wilson | https://affpapa.org/en/nevibecode/skills/kelly-criterion |
| 10 | Utiliser le flux Flashblocks pré-Denim sans re-vérifier | URL/ordre obsolètes depuis le 5 nov 2026 (blocs 200 ms, Flashblocks retiré) | https://tatum.io/blog/best-base-rpc-providers-2026 ; https://chainstack.com/learn/compare/best-base-rpc-providers-for-ai-agents-2026/ |

---

## 8. Outils — ce qu'il faut utiliser (vérifiés 2026-11-24)

| Besoin | Outil recommandé | Notes / limites |
|---|---|---|
| RPC Base, latence | **Chainstack** (P50 22 ms, P95 35 ms, 7 j au 18 nov 2026) ou **QuickNode** (P99 49 ms, meilleur en DE/JP) ; **dRPC** meilleure dispo (98,49 %) ; Alchemy plus lent sur Base dans cette fenêtre (P95 85 ms) mais plus gros free tier (30M CU/mois) | Benchmark : https://chainstack.com/reports/uncategorized/base-rpc-provider-benchmark-latency-uptime-november-2026/ — **attention : mesures pré-Denim pour partie, à re-mesurer après Denim.** Tous < 99 % de dispo sur la fenêtre : prévoir **2 RPC en fallback**. Vue d'ensemble : https://tatum.io/blog/best-base-rpc-providers-2026 |
| RPC gratuit (tests) | `https://mainnet.base.org` | OK pour tests/fork, pas pour la latence live |
| Découverte meme coins | **DexScreener API** (sans clé, 300 req/min) : `/latest/dex/tokens/{addr}`, `/token-pairs/v1/{chain}/{addr}`, boosts | https://ottermind.ai/skills/crypto-token-analyzer ; https://docs.spliceloom.com/data-providers |
| Sécurité token | **GoPlus** (`api.gopluslabs.io`, Base = 8453, gratuit sans clé en base) | Champs §3.2 ; ne remplace pas un audit |
| Simulation | **Anvil fork** (Foundry) + `eth_call` / `eth_estimateGas` ; **Tenderly** Simulation en complément | Fork = preuve réelle, pas un calcul |
| Contrats / build | **Foundry** (`forge build`, `forge test`) | Déjà la stack de `base-flash-arb-lab` (88 tests Python + forge) |
| Flux temps réel | WebSocket RPC (`eth_subscribe`) + flux preconf Base (à re-vérifier post-Denim) | Le polling est trop lent (voir §0) |
| Liquidations | Scanner Aave HF en lecture seule ; **ApexLiqRadar** (payant, données live HF) en option | https://blog.solvinc.io/posts/aave-liquidation-sniper-python-scanner/ ; https://apexliqradar.com/?proof=76bc3df087 |
| Graph / math | Bellman-Ford sur graphe de pools (voir §2.2 n°5) | https://book.longcipher.com/en/mev/strategies/atomic-arb/ |

---

## 9. Verdict honnête — ce qu'il est réaliste de gagner, et ce qui fait perdre

**Ce qui est réaliste :**
- Sur les **majors**, le revenu attendu d'un bot 2-DEX est **~0 $** (mesuré :
  0/992). Il ne faut pas y aller.
- Sur les **meme coins illiquides (5k–100k $)**, des trades à **+$10 à +$70
  nets** existent en simulation (notre démo : +$71,55 à $790, spread 20 %).
  Mais ils sont **petits, rares, et disputés** : il faut en capter beaucoup,
  avec un taux de succès élevé, pour que ça fasse un revenu. Un objectif
  honnête en phase de test : **mesurer d'abord** (100 simulations fork),
  puis seulement parler de $/jour. Personne ne peut promettre un $/jour
  avant cette mesure — et tout repo qui le promet ment.
- La **liquidation Aave** est le meilleur complément : bonus 5–10 %,
  mais par vagues, et de plus en plus captée par des enchères (SVR).

**Ce qui fait perdre (dans l'ordre) :**
1. Trader les majors saturées.
2. Spammer (gas cumulé des ratées > profits).
3. Ne pas simuler en EVM réelle (honeypot, taxe, frais dynamiques).
4. Ne pas plafonner le gas.
5. Copier un contrat non lu.
6. Sur-miser avec Kelly plein ou un `p` inventé.

**La règle qui résume tout :** un bot qui **ne broadcast que ce qu'il a
simulé gagnant, avec un gas mesuré en direct, sur des tokens vettés, et
qui s'arrête quand il perd**, peut survivre. Un bot qui broadcast pour
« tenter » perd — c'est mesuré : seuls 27,8 % survivent, et leur profit
agrégé est négatif.

**Prochaine étape recommandée :** appliquer les améliorations n°1–4 et
n°6 (§6), puis lancer **100 simulations fork** sur des meme coins réels
(5k–100k $) et calculer l'EV. Si EV > 0 → on prépare le live avec un
budget gas réservé ($2/jour max, comme `base-flash-arb-lab`). Si EV ≤ 0 →
on ne passe pas en live, on pivote vers les liquidations.

---

## Sources — toutes vérifiées le 2026-11-24

- https://github.com/starky2000/base-flash-arb-lab
- https://github.com/akari-sora/aave-oracle-lag-arb
- https://github.com/manuelinfosec/flash-arb-bot
- https://github.com/cjthoma1/flash-loan-bot
- https://github.com/freefilm010/aiqtp-omni-nexus/blob/HEAD/gasless-bot/README.md
- https://www.derp.ca/research/arbitrage-mev-bot-honeypot-scam/
- https://web3feeds.sifted.network/top100/amm
- https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120
- https://token-research.com/research/tr-2624
- https://token-research.com/research/tr-2539
- https://coincub.com/blog/mev-invisible-tax/
- https://book.longcipher.com/en/mev/strategies/atomic-arb/
- https://book.longcipher.com/en/blog/dex-market-making-lvr/
- https://hackernoon.com/the-math-behind-automated-market-makers
- https://orcacrypto.io/learn/advanced/amm-math/
- https://github.com/maxkru92/everything-claude-trading/blob/HEAD/skills/crypto/cross-chain-arbitrage/SKILL.md
- https://graph.org/What-Is-Flashbots-and-How-Does-Protect-Stop-Frontrunning-11-06
- https://blog.web3wagmi.com/flashbots-guide
- https://www.spark.money/glossary/flashbots
- https://mevdao.org/blog/flashbots-protect-vs-mev-blocker-which-private-rpc-should-you-use
- https://mevdao.org/blog/mev-on-layer-2-how-arbitrum-base-and-optimism-order-transactions
- https://arxiv.org/html/2610.03922v1
- https://chainstack.com/what-are-flashblocks/
- https://coinvote.cc/token-scanner?chain=base&address=0x1fa7a36f39b094321c265b3c8a995836008fdb0d&from=coin
- https://ottermind.ai/skills/crypto-token-analyzer
- https://docs.spliceloom.com/data-providers
- https://www.marketmaker.cc/blog/kelly-criterion-strategy-sizing/
- https://affpapa.org/en/nevibecode/skills/kelly-criterion
- https://www.techardentlabs.com/insights/position-sizing-kelly-criterion-and-fixed-fractional-explained
- https://www.mql5.com/en/articles/24147
- https://www.fogment.com/crypto-gas-fees-explained/
- https://www.nifmacademy.com/blog/post/322/crypto-trading
- https://www.sonicwallet.com/learn/crypto/gas-fees-explained
- https://growyourethereum.com/data/ethereum-gas-price-history
- https://blog.solvinc.io/posts/aave-liquidation-sniper-python-scanner/
- https://claudeers.com/aave-oracle-lag-arb
- https://apexliqradar.com/?proof=76bc3df087
- https://dev.moby.win/agents/strategies/memecoin-sniper-agent/
- https://coinstats.app/news/1c3fe1285529eb0730ecd38e9d201d99cfd171d2525c7948bfd8174f5d900b1e_Bubblemaps-Flags-90Wallet-Sniping-Cluster-at-MYSTERY-Token-Launch/
- https://coinmarketcap.com/academy/article/how-to-build-a-fourmeme-token-sniper-with-coinmarketcap-api
- https://www.axxel.ai/crypto-sniper-bot
- https://true402.dev/guides/base-sniper-bot-stack
- https://chainstack.com/reports/uncategorized/base-rpc-provider-benchmark-latency-uptime-november-2026/
- https://tatum.io/blog/best-base-rpc-providers-2026
- https://chainstack.com/learn/compare/best-base-rpc-providers-for-ai-agents-2026/
- https://substreams.dev/packages/uniswap-v4-base/latest
- https://claudeskills.info/skills/austintgriffith/ethskills/building-blocks/
- https://docs.circuit.org/agent-developers/sdk-reference/liquidity
