# Rôles « solver » à 0 $ — Polygon / Ethereum — SOLVER_ZERO_DOLLAR_POLYGON.md

Date : 2026-11-25. Auteur : recherche + vérification docs officielles (lecture seule).
Question d'Ismail : « chof goliya l7wayj li n9dar ndirhom b 0$ bhal solver ».

**Verdict en une phrase : un seul rôle est vraiment faisable à 0 $ pour Ismail —
filler non-exclusif UniswapX sur Base (permissionless, sans bond, sans KYC,
sans inventaire : le reactor donne les tokens d'entrée avant, on swap, on
rend la sortie). FastLane Atlas est à 0 $ pour entrer (bond = gas seulement)
mais pas gagnable avec son infra actuelle (fenêtres de ~250 ms). CoW est
possible à 0 $ de capital via le pool DAO, mais bloqué par KYC/société +
approbation de l'équipe. Tout le reste (1inch, Across, Relay) exige du
capital propre — pas 0 $.**

Contexte Ismail (rappel) : float total 1,31 $ MATIC (~17,27 MATIC), pas de
budget serveur (machine locale / free-tier), MetaMask, Alchemy gratuit
(Base + Sepolia activés, Polygon PAS encore activé sur son app), bot
d'arbitrage flash-loan déjà construit (Morpho 0 %). La question ici n'est
PAS de refaire le bot — c'est : quels AUTRES rôles « solver » sont
faisables à 0 $ ?

---

## 0. Tableau récapitulatif

| Rôle | Bond / stake exigé (source) | Capital / inventaire | KYC / whitelist | Verdict 0 $ |
|---|---|---|---|---|
| **UniswapX filler non-exclusif (Base)** | **Aucun** (docs Uniswap) | **Aucun** (input d'abord via callback) | **Non** (permissionless) | **OUI** |
| **FastLane Atlas solver (Polygon PFL)** | Bond = gas seulement, **aucun minimum dans les docs** (atlETH = POL) | Non si flash loan (`_borrow` escrow) | Non (permissionless) | **CONDITIONNEL** — 0 $ pour entrer, vitesse bloque pour gagner |
| **CoW solver (pool DAO)** | 0 $ si vouched par le pool DAO ; sinon 50 k$ + 500 k COW → 100 k$ + 1 M COW (CIP-44) | Non si Flash-Loan Router (CIP-66) | **OUI** (société + passeports) + approbation équipe | **CONDITIONNEL** — KYC/société + compétition |
| **CoW solver (propre pool)** | 500 000 $ stables + 1 500 000 COW | Non si Flash-Loan Router | Oui | **NON** |
| **1inch Fusion resolver** | ≥ 5 % de toute la Unicorn Power (FAQ) / 10 % (blog) — top 10 max | Oui (inventaire + FeeBank) | Oui (Synaps + TRM Labs) | **NON** |
| **Across relayer** | Aucun bond | **Oui — avance ses fonds** | Non | **NON** (capital) |
| **Relay solver** | Aucun bond | **Oui — remplit avec son capital** | Non (de fait : accès au flux) | **NON** (capital) |
| Chainlink SVR searcher (Atlas, Base/Arb) | 0,1 ETH recommandé (~300 $) | Non si flash loan (contrat solver) | Non | **NON** (bond ~300 $, pas Polygon) |
| Validateur Polygon | Stake POL massif (guides : ~16 000 MATIC historiquement) | Oui | Non | **NON** |
| Bundler ERC-4337 | Aucun | Gas float seulement | Non | **NON en pratique** (~0 flux pour un inconnu) |

---

## 1. FastLane Atlas solver (Polygon) — le plus proche du sujet

### En une phrase
Un solver Atlas répond aux opérations d'utilisateurs (intents / opportunités
MEV) en proposant une solution exécutée atomiquement dans une seule
transaction, et gagne la valeur qu'il capture moins son enchère et son gas.

### Comment il gagne
- Atlas est un framework d'« execution abstraction » : une app collecte une
  opération utilisateur (EIP-712), un bundler la combine avec les opérations
  des solvers en une seule transaction atomique. Les solvers enchérissent ;
  le meilleur gagne et exécute.
  Source : https://docs.atlasevm.com/atlas/getting-started/components/atlas/
- Sur Polygon, l'usage live principal est la vente aux enchères MEV FastLane
  (PFL) : pour chaque transaction publique qui crée une opportunité (OppTx),
  Atlas ouvre une enchère scellée (sealed-bid, premier prix) où les searchers
  soumettent des offres pour faire inclure leur arbitrage juste après l'OppTx.
  Source : https://arxiv.org/html/2510.14642v1 (« The Bidding Games », oct. 2025)
- Le solver gagne = valeur MEV capturée − enchère payée au validateur − gas.

### Exigences exactes (docs officielles FastLane, docs.atlasevm.com)
- **Bond atlETH = escrow de gas seulement, AUCUN minimum dans les docs.**
  « In order to participate in auctions, solvers must acquire and bond enough
  atlETH to cover the gas their operations will consume. »
  Source : https://docs.atlasevm.com/atlas/getting-started/components/atlETH/
  atlETH = wrapped du token natif de la chaîne (POL sur Polygon, ETH sur
  Ethereum). Fonction `depositAndBond(uint256 amountToBond)` ; exemple des
  docs : 1e18 (1 token natif). Récupération en 2 étapes : `unbond` + attente
  (`ESCROW_DURATION` blocs) + `redeem`.
  Source : https://docs.atlasevm.com/atlas/guides/solvers/bond-atleth
- **1 seule enchère par bloc et par compte bondé** (anti double-spend atlETH) :
  pour participer à plusieurs enchères dans le même bloc, il faut autant de
  comptes (EOA) bondés. Source : même guide.
- **Contrat solver obligatoire** : le contrat doit définir `atlasSolverCall`
  et payer son enchère avant la fin de son exécution ; le gas consommé est
  déduit du solde bondé et crédité au bundler. Si l'opération n'est pas
  exécutée : 0 $ facturé. Si elle échoue par faute du solver : gas facturé.
  Source : guide « How to Participate in Auctions »,
  https://docs.atlasevm.com/atlas/guides/solvers/participate-auctions/
- **Communication** : WebSocket vers l'operations-relay
  (`wss://relay-fra.fastlane-labs.xyz/ws/solver` dans l'exemple des docs),
  SDK Go Atlas. Le relay diffuse chaque opération utilisateur ; le solver
  filtre (`isOfInterest`), construit sa solution (`buildSolution`) et la
  renvoie. Source : même guide.
- **Pas de whitelist, pas de KYC** : « Permissionless for users, apps, and
  Solvers » (README Atlas, https://github.com/FastLane-Labs/atlas).

### Les flash loans peuvent-ils remplacer l'inventaire ? OUI (documenté)
- Atlas a un **flash loan natif** : « The `_borrow()` function makes flash
  loans available from the Atlas Escrow balance. The balance must be repaid
  by the end of the Atlas transaction by the solver or the borrower. »
  Source : https://raw.githubusercontent.com/FastLane-Labs/atlas/main/README.md
  Limite : le montant disponible = le solde de l'escrow Atlas (alimenté par
  les enchères et les sponsors) — ce n'est PAS un prêt illimité comme Morpho.
  Un solver peut aussi appeler un flash loan externe (Morpho 0 % sur Polygon,
  déjà vérifié) depuis son contrat solver, puisque tout s'exécute
  atomiquement dans la transaction Atlas.

### Concurrence et réalisme — le vrai mur
- **Fenêtre d'enchère ~250 ms** sur Polygon : « the bundle is submitted to a
  FastLane node, which, in practice, opens an auction window of approximately
  250 ms » ; le searcher doit détecter l'OppTx, estimer la MEV, calculer
  l'enchère optimale et soumettre — le tout en ~250 ms, en sealed-bid
  (sans voir les offres adverses), avec risque de winner's curse
  (surenchère systématique). Source : arXiv 2510.14642v1.
- La recherche académique sur ce jeu utilise des agents à apprentissage par
  renforcement (PPO) optimisés pour l'inférence temps réel — c'est un jeu
  de professionnels, pas un script Python sur RPC public gratuit.
- L'infra actuelle d'Ismail (latence quote ~356 ms, RPC public drpc gratuit)
  est **plus lente que la fenêtre d'enchère elle-même** : il ne peut pas
  gagner ces enchères aujourd'hui, même avec un bond de quelques POL.
- De plus, le flux d'enchères Atlas sur Polygon est le MEV validateur (PFL),
  pas un flux d'intents de swaps grand public : il n'y a pas de « programme
  solver Polygon » documenté avec un relay public et un onboarding simple
  comme celui de Chainlink SVR (voir ci-dessous).

### Cas voisin — Chainlink SVR searcher (Atlas, mais PAS Polygon)
- Atlas est aussi le système d'enchères de Chainlink SVR (liquidations),
  live sur **Base, Arbitrum, BNB Chain, Monad, Arc, Ink, Robinhood Chain**
  — Polygon n'est PAS dans la liste.
  Source : https://docs.chain.link/data-feeds/svr-feeds/searcher-onboarding-atlas
- Bond recommandé par Chainlink : **Base / Arbitrum 0,1 ETH** (~300 $),
  BNB 1 BNB, Arc ~200 USDC, Monad ~10 000 MON. C'est un escrow de gas,
  remboursable — mais 0,1 ETH dépasse le float d'Ismail (1,31 $).
- Les liquidations elles-mêmes peuvent utiliser des flash loans via le
  contrat solver. Le rôle est réel et documenté, mais **bloqué par le bond
  et hors Polygon**.

### Verdict Atlas : CONDITIONNEL
- **0 $ pour entrer** (bond = quelques POL de gas, récupérables ; pas de
  KYC ; pas de whitelist ; flash loans natifs).
- **~0 $ à gagner avec l'infra actuelle** : fenêtres ~250 ms, enchères
  scellées contre des pros, latence actuelle 356 ms. Il faudrait : RPC
  privé/dédié ou node, écoute mempool, exécuteur en ms (Go/Rust), et une
  stratégie d'enchère — exactement l'infra payante déjà identifiée pour
  la compétition (RPC dédié + FastLane). Atlas est donc l'étape 2, pas
  l'étape 1.

---

## 2. UniswapX filler non-exclusif (Base) — LE rôle à 0 $

### En une phrase
Un filler UniswapX exécute les swaps signés par les utilisateurs (intents)
quand l'enchère hollandaise atteint un prix rentable, et garde la différence
entre le prix de l'enchère et son coût d'exécution réel.

### Comment il gagne
- L'utilisateur signe un ordre (intent) : « je donne X, je veux au minimum
  Y ». L'ordre passe par une enchère hollandaise : le prix offert au filler
  commence haut et décroît avec le temps/blocs. Le filler qui exécute
  gagne : (montant d'entrée reçu) − (montant de sortie livré) − gas.
- Les ordres sont publics et gratuits via l'API UniswapX :
  `GET https://api.uniswap.org/v2/orders?orderStatus=open&chainId=8453&limit=50&orderType=Dutch_V3`
  (max 4 requêtes/sec, pas de clé). Vérifié par moi : l'endpoint répond
  sans authentification (`{"orders":[]}` au moment du test — voir §2.4).

### Exigences exactes (docs officielles Uniswap)
- **Aucun bond, aucun stake, aucun KYC, aucune whitelist** pour le filler
  non-exclusif. La doc officielle distingue deux rôles :
  - **Quoter** : permissioned, vetté par Uniswap Labs (c'est lui qui gagne
    l'exclusivité) — PAS accessible à 0 $.
  - **Non-exclusive filler** : « Permissionless, no vetting » ; devient
    éligible (a) après expiration de l'exclusivité (enchère ouverte à tous),
    ou (b) pendant l'exclusivité via « soft exclusivity override » (livrer
    `exclusivityOverrideBps` % de plus que le prix exclusif ; ex. 25 bps =
    0,25 % de plus). « A non-exclusive filler carries no fade risk and is
    never subject to the circuit breaker. »
  Source : https://developers.uniswap.org/docs/liquidity/uniswapx/filling/overview
- **Chaînes DutchV3** : Arbitrum, Arc, Avalanche, **Base**, BNB, Ink, Monad,
  Robinhood Chain, Tempo, Unichain. **Polygon n'est PAS supporté.**
  Base supporte Priority + DutchV3. Adresses Base (doc officielle) :
  DutchV3OrderReactor `0x000000008a8330B5d1F43A62Bf4C673A49f27ba0`,
  OrderQuoter `0xc6ef4C96Ee89e48Eff1C35545DBEED4Ad8dAC9D4`,
  Permit2 `0x000000000022D473030F116dDEE9F6B43aC78BA3`.
  Source : https://developers.uniswap.org/docs/liquidity/uniswapx/deployments
  (Ismail a déjà Alchemy Base activé — pas besoin de Polygon ici.)
- **Exécution** : appeler `execute` / `executeBatch` sur le reactor.
  Fenêtre d'exclusivité ~24 s (2 blocs) sur mainnet ; après, enchère
  ouverte. Le reactor vérifie que les sorties requises arrivent chez
  l'utilisateur dans la même transaction, sinon revert.
  Source : https://developers.uniswap.org/docs/liquidity/uniswapx/filling/dutch-v3-chains/filling-on-dutch-v3-chains
  et https://developers.uniswap.org/docs/liquidity/uniswapx/filling/mainnet/filling-on-mainnet

### Les flash loans / l'inventaire : NON NÉCESSAIRES (c'est le point clé)
- Le filler a deux façons de sourcer la sortie : (1) son inventaire, ou
  (2) **`executeWithCallback` : recevoir les tokens d'entrée D'ABORD,
  exécuter une route pour acquérir la sortie, et la rendre avant la fin
  de la transaction.** Citation doc : « use `executeWithCallback` to receive
  the input tokens first, run a route to acquire the output, and return the
  output before the transaction ends. »
  Source : Filling on Mainnet (lien ci-dessus).
- L'exemple officiel `SwapRouter02Executor` fait exactement cela : il
  remplit l'ordre en swappant sur Uniswap V2/V3 via SwapRouter02.
  Source : https://github.com/Uniswap/UniswapX (README, section Fill Contracts)
  et https://developers.uniswap.org/docs/liquidity/uniswapx/concepts/architecture
- **Conséquence : le filler n'a besoin d'AUCUN inventaire et d'AUCUN flash
  loan.** Le reactor lui avance les tokens d'entrée ; il les swap sur un
  AMM ; il rend la sortie. Si la route ne donne pas assez, la transaction
  revert (le filler perd seulement le gas du revert — ~0,001–0,005 $ sur
  Base). C'est le même pattern « quote → simule → exécute » que son bot
  d'arbitrage actuel, appliqué à des ordres d'utilisateurs au lieu de
  spreads entre pools.
- Un contrat Executor maison peut aussi brancher un flash loan Morpho
  (0 %) si une stratégie en a besoin — mais ce n'est pas requis pour
  remplir.

### Coûts réels à 0 $ (chiffrés)
- Gas par fill sur Base : ~0,005 $ (mesuré par le bot actuel sur Base ;
  gas Base ~0,006 gwei en test, mainnet du même ordre).
- Déploiement du contrat Executor : une fois, quelques cents sur Base.
- Serveur : polling API ≤ 4 req/sec + RPC Alchemy gratuit (déjà actif
  pour Base) + machine locale — 0 $.
- Float nécessaire : gas seulement. S'il bridge ~1,20 $ de MATIC → ETH
  sur Base (Relay : 0 % platform fee + 0,02 $ d'exécution + gas — déjà
  vérifié), cela fait **~240 fills à 0,005 $**. Le float actuel (1,31 $)
  suffit pour démarrer.
- Exemple d'implémentation officielle : `dutchv3_strategy`
  (repo Uniswap `uniswapx-strategy`), et le guide communautaire
  « How to Become a Filler? » (Titania Research) avec template open-source.
  Source : https://titaniaresear.ch/how-to-become-a-filler

### Concurrence et réalisme — honnête
- **L'exclusivité mange le meilleur** : les quoters pros (market makers)
  ont ~24 s d'exclusivité et prennent les ordres rentables en premier. Le
  filler permissionless ne voit que les restes après décroissance du prix —
  c'est là que la marge est la plus fine. Pour gagner, il faut être le
  plus rapide juste après l'expiration, ou battre le prix exclusif de
  `exclusivityOverrideBps`.
- **Flux fin à chaque instant** : test live (2026-11-25 ~06:25 UTC) de
  l'API publique — **0 ordre ouvert** sur Base Dutch_V3 et 0 sur Ethereum
  Dutch_V2 au moment du test. L'API ne retourne que les 50 derniers ordres
  et ils sont consommés en secondes : le flux existe mais il est fin et
  rapide. Un seul snapshot à 0 ne prouve pas l'absence de flux, mais il
  prouve qu'on ne peut pas compter sur un flux épais et lent.
- Titania Research (qui a construit un filler) : « In reality, it is
  challenging to generate significant profits, but it may be worth trying
  to gain an understanding of the market structure. »
- **Gains réalistes pour un solo à 0 $ : 0 à quelques $/semaine au début**,
  avec une courbe d'apprentissage (vitesse d'exécution, sélection des
  ordres, simulation pré-envoi). La valeur immédiate est le système et
  la compétence — pas un revenu.
- Le risque principal est le gas des fills ratés/revertés, pas le capital :
  chaque tentative coûte ~0,005 $, donc 1,31 $ = ~260 tentatives.

### Verdict UniswapX filler : OUI — le seul rôle vraiment à 0 $
- 0 $ de bond, 0 $ d'inventaire, 0 $ de KYC, API gratuite, exemple
  officiel existant, chaîne Base déjà activée chez Ismail, gas à 0,005 $.
- C'est le rôle « bhal solver » le plus proche de ce qu'Ismail veut, et il
  réutilise exactement les briques de son bot actuel (quoter, simulation
  pré-envoi, exécution atomique, garde min-profit).

---

## 3. CoW Protocol solver — possible à 0 $ de capital, bloqué par l'identité

### En une phrase
Un solver CoW propose la meilleure exécution (CoW + AMMs) pour un lot
d'ordres d'utilisateurs toutes les ~30 secondes, et gagne des récompenses
hebdomadaires en COW.

### Comment il gagne
- Batch auction toutes les ~30 s ; les solvers concourent ; la meilleure
  solution (surplus utilisateur maximal) gagne et s'exécute on-chain.
  Récompenses hebdomadaires en COW. Volume 2025 : 87 Md$ (116 % YoY) ;
  30+ équipes de solvers. Source : docs CoW + analyses (earlythunder.com).

### Exigences exactes (docs officielles CoW)
- **Bond — deux voies :**
  - **Pool DAO (vouching)** : le solver est « vouché » par le CoW DAO
    Bonding Pool — **pas de bond propre à déposer**. Conditions : KYC
    (détails d'incorporation de la société + passeports d'1–2 actionnaires
    / développeurs), commencer sur **BNB Chain d'abord**, frais de service
    de **15 % des récompenses COW hebdomadaires** après 6 mois (CIP-48).
    L'équipe garde le droit de refuser. Source :
    https://github.com/cowprotocol/docs/blob/HEAD/docs/cow-protocol/tutorials/solvers/onboard.md
  - **Propre pool réduit (CIP-44)** : **50 000 $ en stables + 500 000 COW**
    au départ, puis **100 000 $ + 1 000 000 COW** sous un an.
  - **Propre pool complet** : **500 000 $ en stables + 1 500 000 COW**.
    Source : https://docs.cow.bleu.builders/cow-protocol/reference/core/auctions/bonding-pools
- **Infra** : solver engine + driver Rust open-source (le driver gère
  l'interface avec l'autopilot, le fetching de liquidité AMM, la
  simulation et la soumission). Serveur à faire tourner 24/7.
  Source : https://docs.cow.bleu.builders/cow-protocol/explanation/architecture/driver
- **Compétition** : 30+ équipes pro ; un moteur solo doit battre leurs
  solutions pour gagner quoi que ce soit. La récompense dépend de la
  qualité du moteur, pas de la participation.

### Les flash loans peuvent-ils remplacer l'inventaire ? OUI (officiel)
- **CIP-66 : Flash-Loan Router intégré et audité**, adresse
  `0x9da8b48441583a2b93e2ef8213aad0ec0b392c69` sur toutes les chaînes EVM :
  « enabling solvers to execute settlements utilising funds from one or
  more flash-loans… allowing them to access temporary liquidity without
  collateral. » Le router appelle `settle` directement ; n'importe quel
  solver de l'AllowList peut l'appeler ; les risques sont à la charge du
  solver. Source : https://forum.cow.fi/t/cip-66-flash-loan-router-integration/2939
  et https://docs.cow.bleu.builders/flash-loan-router/contracts/interfaces/iflash-loan-router
- CoW tourne sur Polygon (le VouchRegister liste Polygon), mais les
  nouveaux solvers du pool DAO commencent sur BNB Chain.

### Verdict CoW : CONDITIONNEL
- **Capital : 0 $ possible** (pool DAO + Flash-Loan Router).
- **Mais :** KYC avec société (Ismail est un individu sans société
  déclarée pour cela), passeports, approbation discrétionnaire de
  l'équipe CoW, démarrage sur BNB Chain (pas Polygon), infra Rust 24/7,
  et concurrence de 30+ équipes pro. Gains réalistes pour un solo :
  ~0 $ tant que le moteur ne gagne pas d'enchères.
- C'est une voie réelle, mais pas une voie « bhal solver à 0 $ »
  immédiate : c'est un projet d'équipe avec une identité juridique.

---

## 4. 1inch Fusion resolver — NON (des millions de $ de stake)

### En une phrase
Un resolver 1inch remplit les ordres Fusion (enchère hollandaise) et
gagne la différence entre le prix de l'ordre et son coût d'exécution.

### Exigences exactes (docs officielles 1inch)
- **Stake 1INCH → Unicorn Power (UP)** : il faut être dans le **top 10**
  des détenteurs d'UP, avec un minimum de **5 % de toute l'UP totale**
  (FAQ officielle) — le blog 1inch dit **10 %** (divergence entre deux
  sources officielles ; dans les deux cas, des millions de $ de 1INCH).
  Maximum 10 resolvers listés. Lock de 1 mois à 2 ans (défaut 2 ans),
  pénalité en cas de unstake anticipé.
  Sources : https://help.1inch.com/en/articles/6800254-1inch-fusion-faq
  et https://1inch.com/blog/post/fusion-mode-swap-resolving
- **Vérification obligatoire** : KYC/KYB par Synaps + screening du wallet
  par TRM Labs. 1inch n'audite pas le code backend du resolver (à écrire
  soi-même ; exemple : https://github.com/1inch/fusion-resolver-example).
- **FeeBank** : dépôt de 1INCH pour couvrir les frais de resolving.
  Le resolver paie aussi le gas de chaque fill.
- Note : une proposition (1IP-89) visant à retirer le seuil d'UP a été
  signalée comme introduite — **non confirmée comme adoptée** au
  2026-11-25. À surveiller, pas à compter dessus.

### Verdict 1inch : NON
5 % de toute l'UP = des millions de dollars, plus KYC, plus 10 places
seulement. Pas 0 $, pas pour un solo.

---

## 5. Across relayer et Relay solver — NON (capital avancé)

### Across relayer
- En une phrase : un relayer Across paie l'utilisateur sur la chaîne de
  destination avec **ses propres fonds**, et Across le rembourse ensuite
  via le HubPool.
- Exigences : bot relayer Node.js (CPU dual-core 2+ GHz, 4 Go RAM
  recommandés), RPCs sur chaque chaîne, et **assez de capital pour
  remplir les transferts** — le montant n'est pas fixé, il est égal à
  la taille des transferts qu'on accepte de remplir. Frais relayer
  typiques : ~0,011 % (ex. 0,107 USDC pour 1 000 USDC ETH→Arbitrum).
  Sources : https://github.com/across-protocol/dev-docs/blob/HEAD/developers/running-a-relayer.md
  et https://skrumble.com/cross-chain-bridges/across-protocol-review/
- **Verdict : NON.** Avec 1,31 $, on ne peut remplir que des transferts
  de ~1 $ — le gas de chaque fill (~0,01 $ sur Polygon) mange la marge.
  Le capital est le produit lui-même.

### Relay solver (relay.link)
- En une phrase : même modèle — le solver remplit l'ordre sur la chaîne
  de destination avec **son propre capital**, le protocole vérifie et le
  rembourse depuis le dépôt escrow de l'utilisateur.
  Source : https://docs.relay.link/references/protocol/overview
  et https://github.com/relayprotocol/relay-docs/blob/HEAD/references/protocol/how-it-works.mdx
- **Verdict : NON.** Capital propre exigé par construction ; de plus la
  distribution des ordres (quoting) est hors protocole — l'accès au flux
  n'est pas un simple endpoint public comme UniswapX.

---

## 6. Aussi considérés et écartés

| Rôle | Pourquoi pas à 0 $ |
|---|---|
| Validateur Polygon | Stake POL massif (guides historiques : ~16 000 MATIC ; en tout cas des milliers de $) + serveur dédié. |
| MEV-Share / Flashbots searcher | Ethereum mainnet uniquement — pas Polygon, pas Base. |
| UniswapX quoter | Permissioned, vetté par Uniswap Labs (c'est le rôle qui gagne l'exclusivité). |
| Bundler ERC-4337 | Permissionless en théorie (aucun bond), mais les wallets envoient les userOps à Pimlico/Alchemy/Biconomy — un bundler inconnu reçoit ~0 flux. (Les tutos Pimlico montrent les utilisateurs soumettant via le bundler Pimlico : https://docs.pimlico.io/guides/tutorials/send-transaction) |
| Searcher FastLane PFL « classique » (spam/PGA) | C'est l'ancien modèle : spammer des transactions pour être premier — remplacé par les enchères Atlas scellées (~250 ms). Sans enchère, pas d'accès prioritaire. |
| deBridge DLN taker / Everclear solver / Squid | Même modèle que Relay/Across : capital propre avancé. |

---

## 7. Verdict classé — quoi faire, dans quel ordre

### Rang 1 — UniswapX filler non-exclusif sur Base : OUI, à 0 $, à construire en premier
C'est le seul rôle où **toutes** les barrières sont à zéro : pas de bond,
pas de KYC, pas d'inventaire, pas de whitelist, API publique gratuite,
exemple officiel existant, chaîne Base déjà activée, gas 0,005 $/fill.
Il réutilise les briques du bot actuel (quoter → simulation pré-envoi →
exécution atomique → garde min-profit), appliquées à des ordres
d'utilisateurs au lieu de spreads entre pools.

**Premières étapes exactes pour Ismail (0 $) :**
1. **Bridge ~1,20 $ de MATIC → ETH sur Base** (Relay : 0 % platform fee
   + 0,02 $ d'exécution + gas — déjà vérifié) pour le gas des fills.
   Garder ~1–2 MATIC pour le gas Polygon. (Alternative 0 $ : tester
   d'abord sur fork Base, sans bridge.)
2. **Récupérer l'exemple officiel** `dutchv3_strategy` (repo Uniswap
   `uniswapx-strategy`) et le guide Titania ; lire le reactor Base
   `0x000000008a8330B5d1F43A62Bf4C673A49f27ba0`.
3. **Poller l'API publique** `api.uniswap.org/v2/orders` (chaîne 8453,
   `Dutch_V3`, ≤ 4 req/sec) et logger les ordres ouverts pendant 24 h
   pour mesurer le flux réel (le test instantané a donné 0 ordre ouvert).
4. **Simuler chaque ordre hors-chaîne** (eth_call) : ne soumettre que si
   (prix Dutch − coût route AMM − gas) > 0 — même garde que le bot actuel.
5. **Déployer l'Executor sur Base** (quelques cents, une fois) puis remplir
   en `executeWithCallback` (input d'abord, swap, sortie rendue).
6. **Règle d'arrêt** : si < 1 fill rentable / semaine pendant 2 semaines,
   arrêter — le flux ne suffit pas pour un solo à 0 $.

### Rang 2 — FastLane Atlas solver (Polygon) : CONDITIONNEL, étape 2
0 $ pour entrer (bond = quelques POL de gas, récupérables ; flash loans
natifs `_borrow()`), mais **pas gagnable sans infra payante** : fenêtres
~250 ms, enchères scellées, pros avec agents RL. À tenter seulement après
avoir (a) un RPC privé/dédié ou un node, (b) une écoute mempool, (c) un
exécuteur en ms. Le jour où il a cette infra, Atlas devient le prolongement
naturel de son bot d'arbitrage (même compétence : détecter → enchérir →
exécuter atomiquement).

### Rang 3 — CoW solver (pool DAO) : CONDITIONNEL, projet long
0 $ de capital possible (pool DAO + Flash-Loan Router CIP-66), mais il faut
une société + passeports + l'approbation de l'équipe CoW + démarrer sur BNB
Chain + un moteur Rust compétitif contre 30+ équipes. À envisager seulement
s'il veut monter une structure et jouer le long terme.

### Rang 4 — Le reste : NON
1inch (millions de $ d'UP), Across/Relay (capital avancé), validateur
(Stake massif), Chainlink SVR (bond 0,1 ETH ~300 $, pas Polygon).

### La phrase à retenir
**« Solver à 0 $ » existe — mais un seul : filler UniswapX sur Base.**
Tout le reste demande soit du capital, soit une identité juridique, soit
une vitesse qu'on n'a pas encore. Et même le filler ne promet pas de
revenu : il promet un système à 0 $ pour apprendre le jeu et attraper
les restes que les pros laissent après l'exclusivité.

---

## Annexe — sources (toutes vérifiées le 2026-11-25)

- FastLane Atlas docs (bond, atlETH, participation) :
  https://docs.atlasevm.com/atlas/getting-started/components/atlETH/
  https://docs.atlasevm.com/atlas/guides/solvers/bond-atleth
  https://docs.atlasevm.com/atlas/guides/solvers/participate-auctions/
  https://docs.atlasevm.com/atlas/getting-started/components/atlas/
- Atlas README (flash loans `_borrow()`, permissionless) :
  https://raw.githubusercontent.com/FastLane-Labs/atlas/main/README.md
- Chainlink SVR Atlas onboarding (bonds 0,1 ETH Base/Arb, chaînes live) :
  https://docs.chain.link/data-feeds/svr-feeds/searcher-onboarding-atlas
- Polygon Atlas / FastLane, fenêtres ~250 ms (arXiv 2510.14642v1) :
  https://arxiv.org/html/2510.14642v1
- FastLane on Polygon (searcher onboarding mentionné) :
  https://medium.com/@fastlanelabs/introducing-fastlane-on-polygon-157c74e34d7
- UniswapX docs (filling, overview, deployments, mainnet) :
  https://developers.uniswap.org/docs/liquidity/uniswapx/filling/overview
  https://developers.uniswap.org/docs/liquidity/uniswapx/filling/dutch-v3-chains/filling-on-dutch-v3-chains
  https://developers.uniswap.org/docs/liquidity/uniswapx/filling/mainnet/filling-on-mainnet
  https://developers.uniswap.org/docs/liquidity/uniswapx/deployments
  https://developers.uniswap.org/docs/liquidity/uniswapx/concepts/architecture
- UniswapX repo (fill contracts, SwapRouter02Executor) :
  https://github.com/Uniswap/UniswapX
- Titania Research, « How to Become a Filler? » :
  https://titaniaresear.ch/how-to-become-a-filler
- CoW bonding pools (CIP-44) :
  https://docs.cow.bleu.builders/cow-protocol/reference/core/auctions/bonding-pools
- CoW solver onboarding (KYC, BNB d'abord, 15 % fee) :
  https://github.com/cowprotocol/docs/blob/HEAD/docs/cow-protocol/tutorials/solvers/onboard.md
- CoW CIP-66 Flash-Loan Router + interface :
  https://forum.cow.fi/t/cip-66-flash-loan-router-integration/2939
  https://docs.cow.bleu.builders/flash-loan-router/contracts/interfaces/iflash-loan-router
- CoW driver (infra solver) :
  https://docs.cow.bleu.builders/cow-protocol/explanation/architecture/driver
- 1inch Fusion FAQ + blog resolver :
  https://help.1inch.com/en/articles/6800254-1inch-fusion-faq
  https://1inch.com/blog/post/fusion-mode-swap-resolving
- Across relayer (exigences serveur, capital avancé) :
  https://github.com/across-protocol/dev-docs/blob/HEAD/developers/running-a-relayer.md
  https://skrumble.com/cross-chain-bridges/across-protocol-review/
- Relay Protocol (solver = capital propre) :
  https://docs.relay.link/references/protocol/overview
  https://github.com/relayprotocol/relay-docs/blob/HEAD/references/protocol/how-it-works.mdx
- Pimlico (concentration du flux bundler) :
  https://docs.pimlico.io/guides/tutorials/send-transaction

**Méthode :** recherche web + docs officielles uniquement. Aucun broadcast,
aucun wallet, aucune clé, aucun fonds, aucune inscription. Aucun fichier
existant modifié. Test live : endpoint UniswapX Orders API interrogé
(2026-11-25 ~06:25 UTC, sans clé) — `{"orders":[]}` sur Base Dutch_V3 et
sur Ethereum Dutch_V2 au moment du test.
