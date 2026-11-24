# Zéro coût, privé, $0 même sur revert — Bot Flash Loan Base

**Date de vérification : 2026-11-24. Recherche seulement — aucun fond réel, aucune clé privée, aucun déploiement.**
**Règles d'Ismail : (1) travailler à 0 $ de poche — un collab/partenaire paie fees + gas ; (2) un trade perdant s'annule ; (3) le trade ne doit pas apparaître dans le mempool (pas de frontrunning) ; (4) PRÉCISION DU 2026-11-24 : même si le trade revert on-chain, on ne paie rien — 0 $ même en cas de revert.**
**État du bot au moment de l'écriture : v3 (Balancer 0 % intégré : `balancer_flash.py`, `BALANCER_FLASH_FEE = 0.0` dans `math_engine.py`), min profit 3 $, gas unifié (`gas.py`), preflight EVM (`preflight.py`, fraîcheur ≤ 2 blocs), circuit breaker (`circuit_breaker.py` : perte max 20 $/jour, 3 reverts d'affilée → pause 1 h).**

> Lecture en 30 secondes — les 5 réponses qui comptent :
> 1. **Le gas est déjà presque gratuit sur Base** (~0,008 $ par arbitrage à 0,006 gwei mesuré live ; 0,0675 $ à l'hypothèse 0,05 gwei). Un trade à +3 $ le paie 375×. Le « 0 $ de poche » n'a donc pas besoin d'un sponsor généreux : il suffit que le profit paie le gas — et c'est déjà le cas.
> 2. **Sur Base il n'y a PAS de mempool public.** Le séquenceur unique de Coinbase voit seul les transactions en attente. Un bot externe ne peut pas te frontrunner — il ne voit ton trade qu'une fois dans un bloc, trop tard. La menace n'est pas le sandwich, c'est la course à la latence (200 ms/bloc post-Denim).
> 3. **Le $0 sur revert on-chain est IMPOSSIBLE à garantir à 100 % sur Base aujourd'hui.** La protection revert de type Flashbots (bundle non inclus = 0 $) est Ethereum L1 uniquement : Base n'a pas de marché de builders, pas d'`eth_sendBundle`, pas de MEV-Share. Une fois qu'une transaction est incluse et revert, le gas est dû — c'est la règle du protocole.
> 4. **Ce qui est atteignable : $0 dans ~99 % des cas + un pire cas résiduel minuscule.** Ne jamais broadcaster un perdant (simulation + preflight ≤ 2 blocs) + revert précoce dans le contrat + plafond gas 2 gwei + circuit breaker. Pire cas mesuré : revert à 54 829 gas = **0,0008 $** en conditions normales, **0,33 $** au plafond de 2 gwei — jamais plus, parce que le plafond bloque les pics.
> 5. **Le « collab qui paie tout gratuitement » n'existe pas sans contrepartie.** Un paymaster est payé par quelqu'un (7–10 % de markup, ou un budget que le sponsor finance) ; un sponsor rationnel ne paie que s'il récupère plus qu'il ne dépense — typiquement un % du profit, prélevé sur le profit, jamais « pour rien ». Le deal réaliste est : **sponsor = Ismail lui-même via un budget gas plafonné, remboursé sur les profits** — ou un partenaire qui prend 20–30 % du profit net en échange du préfinancement du gas. Tout « sponsor gratuit sans rien en retour » est soit une campagne limitée (Base Gasless, jusqu'à 15 000 $ de crédits, pour l'onboarding, pas pour un bot d'arbitrage), soit une arnaque.

---

## 0. Le point dur d'abord : $0 même sur revert — ce qui est vrai, ce qui ne l'est pas

| Affirmation | Vrai ? | Preuve |
|---|---|---|
| Un revert on-chain coûte normalement le gas consommé jusqu'au revert | ✅ Vrai, règle du protocole | Fork test du bot : revert mesuré 54 829 gas = 0,0008 $ ; Titania Research : « even if a transaction reverts, the gas consumed is not refunded » |
| Un flash loan qui revert ne coûte pas de prime de prêt | ✅ Vrai | Le prêt est annulé atomiquement : prime Aave 0,05 % = 0 $ sur revert ; Balancer 0 % de toute façon |
| Un bundle Flashbots qui revert n'est pas inclus et coûte 0 $ | ✅ Vrai — **sur Ethereum L1 seulement** | Docs Flashbots : bundle avec tx qui revert « is not included in the block at all, unless you listed that transaction in `revertingTxHashes` » ; « a bundle that is not included costs nothing » |
| La même protection existe sur Base | ❌ **Faux en nov 2026** | Base n'a pas de marché de builders : séquenceur unique Coinbase ; « Flashbots-style private relays don't exist for Base in 2026 » ; gouvernance Aave/Chainlink SVR : « MEV-Share itself does not operate on these networks, so there is no equivalent private bundle infrastructure » ; « Arbitrum and Base do not natively support Flashbots » |
| Un paymaster ERC-4337 ne paie pas si le tx revert | ❌ **Faux — il paie quand même** | ERC-4337 docs + audits : « Validation succeeds, execution reverts, and the paymaster pays anyway » ; « If the operation fails, the Paymaster still pays the network fees » |
| Annuler un tx en attente (RBF / cancel) est gratuit | ❌ **Faux** | Un cancel = une nouvelle tx (0 ETH vers soi, même nonce, frais +10–20 %) qui doit être minée : 21 000 gas minimum, payés. Et sur Base (bloc 200 ms), la fenêtre pour annuler est de ~200 ms — en pratique le tx est déjà dans un bloc quand tu t'en rends compte |
| Ne jamais envoyer un tx qui va revert coûte 0 $ | ✅ Vrai — **c'est la seule garantie $0 qui existe sur Base** | `eth_call` / simulation off-chain = lecture seule, 0 gas. C'est déjà l'architecture v1/v2 du bot (`preflight.py`) |
| Un revert peut coûter 0 $ « si on a un bon relayer » | ⚠️ Déplacé, pas supprimé | Un relayer qui simule et drop les txs en échec protège *toi*, mais c'est le relayer (ou son sponsor) qui absorbe le risque quand sa simulation se trompe. Le coût ne disparaît pas, il change de poche |

**Conclusion du §0 :** sur Base, il n'existe aujourd'hui **aucun mécanisme protocolaire** qui annule le coût gas d'un revert déjà inclus. La stratégie $0 n'est donc pas « trouver le relai magique », c'est **empêcher le revert d'être inclus** (simulation + fraîcheur + plafond gas + revert précoce) et **plafonner le pire cas à quelques centimes**. Le reste de ce document chiffre chaque couche.

---

## 1. $0 de poche : qui paie le gas et les fees ? (modèle collab)

### 1.1 D'abord la math : le profit paie déjà son propre gas — le sponsor est presque superflu

Chiffres mesurés par le bot lui-même (pas des hypothèses) :

| Cas | Gas | Coût en $ (ETH 3 000 $) | vs profit min 3 $ |
|---|---|---|---|
| Arbitrage normal, gas live mesuré 0,006 gwei, 450 000 units | 450 000 × 0,006 gwei | **0,0081 $** | 3 $ = **370× le gas** |
| Même arbitrage, hypothèse prudente 0,05 gwei | 450 000 × 0,05 gwei | **0,0675 $** | 3 $ = 44× le gas |
| Revert mesuré en fork (54 829 gas, 0,0049 gwei) | 54 829 × 0,0049 gwei | **0,0008 $** | négligeable |
| Pic de gas 254 gwei (29 oct 2026) — **bloqué par le plafond v2 de 2 gwei** | — | **jamais payé** (le bot n'envoie rien au-dessus de 2 gwei) | — |
| Prime flash loan Aave (0,05 % sur 8 847,98 $) | — | 4,42 $ | payée sur le profit, pas de poche |
| Prime flash loan Balancer (v3, 0 %) | — | **0 $** | — |

**Lecture :** à 0,008–0,07 $ par trade gagnant, le gas n'est pas le problème économique du bot — le problème, c'est le **taux de trades gagnants**. Un sponsor qui paierait le gas ne fait économiser que ~0,01 $ par trade ; en échange il exigerait une part du profit qui vaut 100× plus. **Le deal le plus rationnel n'est pas « quelqu'un paie mon gas », c'est « le profit paie le gas, et je garde 100 % du reste ».** Le sponsor n'a de sens que pour le **préfinancement** (avoir des ETH dans le wallet opérateur avant le premier profit) et pour les **reverts** (quelques centimes) — pas comme modèle économique permanent.

Formule de décision à garder dans le bot (déjà implémentée, `math_engine.decide()` + `gas.py`) :
`net = brut − prime_flash − gas ; exécuter seulement si net > 3 $ ET net > gas × 3`.
Avec Balancer (prime 0), le seuil effectif devient `brut > 3 $ + gas`.

### 1.2 Paymasters ERC-4337 — comment ça marche, qui paie, et pourquoi ça ne sponsorise pas un bot d'arbitrage gratuitement

**Mécanisme.** Un UserOperation ERC-4337 est exécutée par un bundler via le contrat EntryPoint. Un paymaster est un contrat qui prépaye le gas à la place de l'utilisateur — soit gratuitement (sponsorship), soit contre paiement en ERC-20. Le sponsor (l'app) dépose des fonds et définit une politique : contrats allowlistés, fonctions allowlistées, plafond par utilisateur et global, cycle de reset (jour/semaine/mois). Quelqu'un paie toujours : le paymaster n'est pas de l'argent gratuit, c'est un compte prépayé avec des règles.
Sources : https://docs.cdp.coinbase.com/paymaster/guides/build-sponsored-transaction-component ; https://www.alchemy.com/docs/wallets/reference/gas-manager-faqs ; https://eco.com/support/en/articles/15254049-best-erc-4337-infrastructure-2026-alchemy-pimlico-biconomy-zerodev

**Fournisseurs vérifiés (nov 2026) et leurs prix réels :**

| Fournisseur | Modèle | Coût du sponsor | Plafonds / limites |
|---|---|---|---|
| **Coinbase Developer Platform (CDP) Paymaster / Base Paymaster** | Sponsorship via dashboard, allowlist contrat + fonction | 7 % de markup (facturé `actualGas × ethPrice × 1,07`) ; **jusqu'à 15 000 $ de crédits gas via la Base Gasless Campaign** | Sponsorship **jusqu'à 10–15k $/mois** sur mainnet (les docs disent 10k $ dans l'ancien tutoriel, 15k $ dans la doc actuelle), illimité en testnet ; limites par utilisateur et globales configurables |
| **Alchemy Gas Manager** | Sponsorship facturé mensuellement | **8 %** des frais de gas couverts (PAYG) ; testnet gratuit illimité | Gas avancé jusqu'à une limite de tier, alertes à 50/75/90/100 % ; on-chain paymaster mainnet réservé aux Enterprise (sauf exceptions) |
| **Pimlico** | Paymaster vérifiant + ERC-20 paymaster | **10 % de surcharge** sur le gas sponsorisé (mainnet) + ~0,0075 $ par UserOperation (0,0105 $ sponsorisée) ; 10M crédits/mois inclus, puis 1 $ / 100k crédits | 5 000 req/min en PAYG ; politiques : allowlist, plafonds par utilisateur, plafond global |
| **Biconomy** | Sponsorship + token paymaster | Markup par UserOp + sponsorship (ordre de 5–10 % selon les comparatifs) | ~25 chaînes, session keys |
| **Circle Paymaster** | USDC comme token de gas | **10 %** pour l'utilisateur final (depuis 1er juil 2025 ; gratuit avant) ; USDC uniquement sur Base | — |

**Pourquoi un paymaster ne sponsorise pas un bot d'arbitrage « gratuitement » :**
1. **La politique est allowlistée par contrat et fonction.** Le sponsor choisit quoi sponsoriser — un bot d'arbitrage qui appelle un contrat de flash loan n'est pas un cas d'usage d'onboarding ; aucun fournisseur ne l'allowliste par défaut. Il faut que *le sponsor* (Ismail ou le partenaire) crée et finance *sa propre* politique.
2. **Le paymaster paie même si l'exécution revert** (§3.3) — c'est un risque de griefing documenté : un attaquant (ou un bot mal réglé) peut vider le dépôt en envoyant des UserOperations qui passent la validation et revertent à l'exécution. D'où des limites strictes par utilisateur/opération, et la nécessité de simuler avant.
3. **Le markup 7–10 % est dérisoire en $ sur Base** (10 % de 0,01 $ = 0,001 $) — mais le vrai coût est le **dépôt prépayé + le risque d'abus**, pas le markup.
4. **Surcharge ERC-4337 : ~42k gas de plus** qu'une tx EOA classique (validation EntryPoint) — sur Base ça reste des centimes, mais ça va dans le mauvais sens pour un bot qui optimise le gas.

**Verdict paymaster :** utile comme **mécanisme technique** si un partenaire veut préfinancer le gas avec des règles (allowlist du contrat `FlashLoanArbitrage`, plafond 20 $/jour = le circuit breaker), inutile comme « argent gratuit ». Le partenaire paie le dépôt ; le bot le rembourse sur les profits (voir §1.5).

### 1.3 Base Transactions (EIP-8430) — le sponsorship natif, mais pas encore live

C'est la nouveauté la plus importante pour le modèle $0 — et la plus mal comprise. Les **Base Transactions** (type `0x79`, EIP-8430) permettent nativement, sans contrat paymaster : batching, **sponsorship par un tiers**, paiement du gas en token, nonces parallèles, délégation type EIP-7702. Le `payer` signe une autorisation séparée ; en mode « open », n'importe quelle clé peut attacher son `payer_auth` et payer à la place de l'expéditeur.
Source : https://docs.base.org/specifications/base-transactions (mise à jour 2026-11-13)

**Deux limites décisives pour nous :**
1. **Pas encore activé.** « Base Transactions activate with the **Everest network upgrade**, and their Base Sepolia and Base Mainnet activation dates are **TBD**. Until Everest activates, this path isn't available. » Everest est la 5e mise à jour de Base (après Denim, 5 nov 2026) — aucune date mainnet publiée au 2026-11-24. **On ne peut pas construire le modèle $0 dessus aujourd'hui.**
2. **Même quand ce sera live, le sponsor paie le gas d'un revert.** La doc est explicite : le paiement du sponsor est en phase 0 et « commits in phase 0 even if a later phase reverts, so the sponsor is reimbursed whatever the outcome » — le sponsor est remboursé en token *si* le sender a prévu un transfert, mais le gas lui-même est dû. Le sponsorship déplace le paiement, il ne l'annule pas.

**Action :** surveiller l'activation d'Everest ; quand ce sera live, c'est le meilleur mécanisme de sponsorship pour le bot (pas de contrat paymaster, pas de bundler, signature native). En attendant : ERC-4337 ou relayer.

### 1.4 Relayers / meta-transactions (ERC-2771) — le tiers soumet, le tiers paie

**Mécanisme.** L'utilisateur signe un message (EIP-712) décrivant l'action ; un relayer l'enveloppe dans une vraie transaction, paie le gas depuis son wallet, et la soumet via un contrat forwarder de confiance qui vérifie la signature — le contrat cible voit l'utilisateur comme expéditeur, pas le relayer. Le relayer ne peut pas modifier une demande signée, mais il peut retarder ou refuser de l'envoyer. Le remboursement, s'il y en a un, est off-chain ou dans une logique de contrat dédiée.
Sources : https://eips.ethereum.org/EIPS/eip-2771 (via https://watswallet.com/blog/gasless-transactions-explained) ; https://docs.settlemint.com/docs/concepts/custody-and-signing/gas-funding

**Pour notre bot :** le relayer est utile si c'est **notre propre relayer** (ou celui du partenaire) : il simule chaque tx avant de la soumettre et **drop celles qui revertent** — c'est le mécanisme « simulation + drop » du §3. Mais :
- Le contrat `FlashLoanArbitrage` doit faire confiance au forwarder (support ERC-2771 à ajouter — le contrat actuel ne l'a pas).
- Si la simulation du relayer se trompe et que le tx revert on-chain, **c'est le relayer qui paie** — le coût est déplacé vers le sponsor, pas annulé. Le sponsor doit l'accepter contractuellement (plafond de pertes).
- Un relayer tiers non fiable peut censurer (ne pas envoyer les bons trades) — il ne peut pas voler les fonds d'un flash loan atomique, mais il peut faire rater des opportunités.

### 1.5 Modèles de collab / profit-share qui existent vraiment

Il n'existe **pas** de « prop firm MEV » publique qui finance des bots d'arbitrage Base. Ce qui existe, ce sont des modèles voisins — voici ce qui est transposable, avec ce que le sponsor exige en échange :

| Modèle | Qui paie quoi | Ce que le sponsor exige | Transposable au bot ? |
|---|---|---|---|
| **Sponsor = Ismail, remboursé sur profits** (recommandé) | Ismail préfinance un wallet gas (ex. 5 $ = ~500 trades) ; le bot rembourse le gas sur chaque profit avant de compter le net | Rien — c'est son propre argent, avec un plafond (circuit breaker 20 $/jour) | ✅ Oui — c'est le modèle le plus simple et il est déjà compatible avec le code actuel |
| **Partenaire backer, % du profit** | Le partenaire préfinance gas + (éventuellement) le wallet opérateur ; il prend **20–30 % du profit net** (après gas et prime flash) | Preuve de rentabilité d'abord (EV > 0 sur 100 simulations fork, `EV_RESULTS.md`), journal de trades vérifiable, kill switch, plafond de pertes, contrat écrit | ✅ Oui — c'est le deal standard « searcher + backer » dans le MEV, même s'il se négocie de gré à gré, pas sur une plateforme |
| **Prop firm classique (Capiffy, Ment Funding, Goat, WenCrypto)** | La firme finance un compte simulé, 75–90 % du profit au trader, après un challenge payant (ex. 89–500 $) | Challenge : objectif de profit 5–10 %, drawdown max 3–10 %, frais d'évaluation non remboursés | ❌ Non — c'est du trading discrétionnaire (forex/futures/crypto spot), pas du MEV ; aucun ne finance un bot d'arbitrage flash loan |
| **Proportion / funded accounts on-chain (Hyperliquid)** | Un backer poste un buffer + prime ; le trader garde 30–90 % du profit, le backer est payé sur le profit | Buffer posté par le backer, compte sur Hyperliquid uniquement | ⚠️ Modèle intéressant comme référence de contrat, mais Hyperliquid ≠ Base/arbitrage flash loan |
| **Base Gasless Campaign (crédits CDP)** | Coinbase offre jusqu'à **15 000 $ de crédits gas** via CDP Paymaster | Candidature, projet d'onboarding utilisateur — pas un bot de trading ; crédits limités dans le temps | ⚠️ À tenter pour les tests, pas comme modèle permanent |
| **MEV-Share / refunds (Flashbots, L1)** | Les searchers enchérissent pour backrunner ton tx ; 90 % du backrun te revient | Ton tx doit créer un backrun rentable — un arbitrage atomique n'en crée pas (il n'y a rien à backrunner après un arbitrage déjà exécuté) | ❌ Non — ne s'applique pas à notre stratégie, et c'est L1 uniquement |
| **« Sponsor gratuit, sans rien en retour » (Telegram/YouTube)** | — | — | 🚨 **Arnaque quasi certaine.** Rappel : le faux « MEV bot » à 613 stars volait tous les fonds via un import caché imitant Balancer (`ADVANCED_RESEARCH.md` §1.2). Aucun sponsor rationnel ne paie sans contrepartie. |

**Structure de deal recommandée (à mettre par écrit avant tout live) :**
- Le sponsor préfinance un montant plafonné (ex. 20 $ de gas = ~2 000 trades à 0,01 $).
- Chaque profit est splitté **après** déduction du gas réel et de la prime flash : ex. sponsor 25 %, Ismail 75 %.
- Plafonds durs : perte max 20 $/jour, 3 reverts → pause 1 h (déjà dans `circuit_breaker.py`), kill switch.
- Le sponsor ne touche jamais aux clés ; il ne voit que le journal (`trades.jsonl` / `EV_RESULTS.md`) et peut couper le financement à tout moment.
- Le bot ne démarre en live que si EV > 0 sur 100 simulations fork — sinon le sponsor paie pour des pertes, et aucun deal ne tient.

### 1.6 Verdict $0 de poche

| Question | Réponse |
|---|---|
| Peut-on trader à 0 $ de poche ? | **Oui, de 3 façons** : (a) le profit paie le gas (déjà vrai dès +3 $) ; (b) un sponsor préfinance le gas et se rembourse sur le profit ; (c) un paymaster CDP/Pimlico avec une politique allowlistée, financée par le sponsor |
| Un étranger paiera-t-il tout ton gas « pour rien » ? | **Non.** Il n'existe aucun mécanisme qui paie le gas de quelqu'un d'autre sans contrepartie, sans limite et sans condition. Les crédits gratuits existants sont plafonnés, temporaires et réservés à l'onboarding |
| Le gas est-il le bon poste à optimiser ? | **Non.** À 0,01 $/trade, même 1 000 trades = 10 $. Le poste qui coûte cher, c'est le **taux de trades perdants** et les **reverts en série** — d'où le §3 |
| Faut-il un sponsor pour démarrer ? | Seulement pour le **préfinancement initial** (quelques $ d'ETH dans le wallet opérateur) et comme filet pour les reverts. Une fois le premier profit encaissé, le bot s'autofinance |

---

## 2. Mempool privé / anti-frontrunning sur Base

### 2.1 Comment le mempool de Base marche vraiment en 2026 (post-Denim)

**Il n'y a pas de mempool public sur Base.** C'est une propriété structurelle de l'OP Stack, pas un réglage :
- « Unlike Ethereum, OP Stack chains do not have a public mempool » et « the OP Stack mempool is currently only visible to the Sequencer » (documents de procédure cités dans la plainte US contre Coinbase, 2026).
- « On Base there is no public mempool to snipe — a single Coinbase-operated sequencer decides ordering, and the only way to see what it is about to do is to follow the blocks it produces » (Chainstack, nov 2026).
- « Base runs a single sequencer with no public mempool, your endpoint is not one of many gossip peers — it is the single pipe between your strategy and the entity that orders blocks » (Chainstack).
- Conséquence mesurable : `eth_subscribe newPendingTransactions` ne retourne rien sur Base ; on ne peut observer que les blocs déjà produits (`newHeads`, 1 bloc toutes les 200 ms depuis Denim, 5 nov 2026, blocs canoniques, Flashblocks retiré — https://basehub.org/specifications/denim-overview/).
- Ordre : **priority fee** dans chaque bloc de 200 ms (pas de FCFS pur comme Arbitrum, pas d'enchère de builder comme Ethereum L1). Le séquenceur est l'unique acteur qui voit les transactions en attente.

**Qui peut te frontrunner, et comment :**

| Acteur | Peut-il voir ton tx avant inclusion ? | Peut-il te frontrunner ? |
|---|---|---|
| Bot externe / searcher classique | ❌ Non — il n'y a rien à écouter | ❌ Non — il ne voit ton trade qu'une fois dans un bloc, trop tard pour se placer avant |
| Ton fournisseur RPC (s'il relaie au séquenceur) | ⚠️ Il voit le contenu brut que tu lui envoies | Théoriquement oui s'il est malhonnête — d'où l'intérêt d'un RPC de confiance ou d'une soumission directe au séquenceur |
| Le séquenceur (Coinbase) | ✅ Oui — c'est son travail | En théorie oui (c'est le « Sequencer Extractable Value ») ; en pratique Coinbase s'engage publiquement à ne pas frontrunner ses utilisateurs, et l'opération est opaque — c'est une hypothèse de confiance, pas une garantie cryptographique |
| Un autre bot qui a vu le même spread | ❌ Il ne voit pas ton tx, mais il peut voir la même opportunité on-chain et envoyer son propre tx | ✅ Oui — c'est la **course à la latence** : deux bots indépendants, même spread, le premier arrivé au séquenceur gagne. Ce n'est pas du frontrunning, c'est de la concurrence |
| Après inclusion (backrun) | ✅ Tout le monde voit le bloc | Un bot peut backrunner (trader après toi) — mais sur un arbitrage atomique, il n'y a plus rien à prendre : le spread est déjà fermé dans ta transaction |

**Traduction pour Ismail :** la peur « mon trade va se voir dans le mempool et on va me frontrunner » vient d'Ethereum L1. **Sur Base, ce vecteur n'existe pas pour un acteur externe.** Ce qu'il faut protéger, c'est (a) le trajet vers le séquenceur (RPC de confiance), (b) la latence (arriver premier), (c) le fait que le spread survive jusqu'à l'inclusion (simulation + fraîcheur ≤ 2 blocs = 400 ms).

### 2.2 Options privées sur Base — ce qui marche vraiment en nov 2026

| Option | Comment ça marche | Statut Base nov 2026 | Revert protection ? | Coût / limites |
|---|---|---|---|---|
| **Soumission directe au séquenceur (RPC standard)** | `eth_sendRawTransaction` vers `mainnet.base.org` ou un RPC privé → séquenceur | ✅ Fonctionne — c'est le chemin par défaut de tout le monde | ❌ Aucune — un tx inclus qui revert paie le gas | Gas normal (~0,01 $) |
| **Base Ledgers (transactions privées Base)** | Ledger privé : dépôts cachent le destinataire, retraits cachent l'expéditeur, règlement on-chain via un contrat Portal, KYC au niveau du ledger | ✅ Live, mais **entreprise / KYC uniquement** : « Run confidential enterprise payments on Base » — ce n'est pas un RPC pour bot, c'est un produit de paiements privés avec opérateur et conformité | N/A | Opérateur + KYC requis ; inutile pour un bot d'arbitrage |
| **Tatum MEV Protection** | Routage via relais privés ; `eth_sendRawTransaction` inchangé, protection automatique | ✅ **Base Mainnet : auto-enabled** (table officielle Tatum, mise à jour 2026-03-20) ; propagation 50–400 ms plus rapide, inclusion 400–1 000 ms plus rapide selon Tatum | ⚠️ **Non prouvé sur Base** : la doc décrit le drop des txs qui revertent, mais les exemples et les mécanismes cités sont L1 ; aucune preuve publiée d'un drop garanti sur Base | Compte Tatum requis ; `eth_sendRawTransaction` gratuit (0 crédit) sur Ethereum, conditions Base à vérifier |
| **dRPC MEV Blocker** | Endpoint RPC avec MEV blocker intégré, aucune config | ✅ **Base listée** parmi les chaînes protégées (Ethereum, Base, BSC, Polygon, Solana) | ⚠️ Même réserve que Tatum : le mécanisme de simulation-and-drop est documenté pour l'écosystème L1 ; pas de preuve spécifique Base | Endpoint standard `https://base.drpc.org` |
| **GetBlock MEV-Protected RPC (Merkle)** | Endpoint RPC routé via mempool privé Merkle | ✅ **Base listée** (Ethereum, Solana, BSC, Base), plans payants uniquement | ⚠️ Même réserve | Plan payant requis |
| **Flashbots Protect (`rpc.flashbots.net`)** | RPC privé → builders Ethereum | ❌ **Ethereum L1 uniquement.** « Ethereum mainnet only, has no effect on any other chain » (docs de bots qui l'intègrent) ; le RPC est chain-id 1 | ✅ Sur L1 : ne fait pas atterrir les txs qui revertent | Gratuit, mais **inutilisable sur Base** |
| **MEV Blocker (`rpc.mevblocker.io`, CoW)** | RPC privé → enchère de backrun, 90 % reversés à `tx.origin` | ❌ **Ethereum L1 uniquement** (endpoints `/fast`, `/noreverts`, `/fullprivacy` — tous L1) ; `/noreverts` = revert protection sur L1 | ✅ Sur L1 (`/noreverts`, `/fullprivacy`) | Gratuit, mais **inutilisable sur Base** |
| **MEV-Share** | Enchère d'order flow, hints partiels, backrun uniquement | ❌ **L1 uniquement** ; « MEV-Share itself does not operate on these networks » (Base, Arbitrum) — gouvernance Aave/Chainlink SVR | N/A | — |
| **Flashbots `eth_sendBundle` / relay** | Bundle atomique vers builders | ❌ **N'existe pas sur Base** : pas de marché de builders, pas de relay ; « Flashbots-style private relays don't exist for Base in 2026 » ; « teams wanting direct sequencer bundle access need Base's own builder API » (Chainstack — API mentionnée, **aucune documentation publique trouvée**) | N/A | — |
| **Base builder API** | Accès direct au builder/séquenceur | ⚠️ **Mentionnée par Chainstack, sans documentation publique vérifiée** au 2026-11-24 — à re-vérifier, ne pas coder dessus | Inconnue | — |
| **Shutter / encrypted mempool** | Tx chiffrée, ordre fixé avant déchiffrement | ❌ Testnet Gnosis, exploration L2 — pas sur Base | N/A | — |

### 2.3 Ce qui NE marche PAS sur Base (à ne pas coder)

1. **Flashbots Protect branché sur Base** — c'est un RPC chain-id 1 ; le brancher sur 8453 ne protège rien et peut faire échouer les envois.
2. **`eth_sendBundle` vers un relay Flashbots** — il n'y a pas de relay Base ; l'appel retournera une erreur « method not found » ou partira dans le vide.
3. **Écouter le mempool public** (`newPendingTransactions`, gossip) — il n'y en a pas ; le bot qui attend un signal mempool attendra éternellement.
4. **Le flux Flashblocks pré-Denim** (`wss://mainnet.flashblocks.base.org/ws`) — retiré le 5 nov 2026 ; utiliser les blocs canoniques (`newHeads`, 200 ms).
5. **Base Ledgers comme « mempool privé du bot »** — c'est un produit de paiements privés d'entreprise avec KYC, pas un chemin de soumission de trades.
6. **Compter sur MEV-Share / les refunds de backrun** — un arbitrage atomique ne crée pas de backrun rentable, et MEV-Share n'opère pas sur Base.

### 2.4 Setup pratique recommandé pour le bot (flux exact)

```
1. Détection      WebSocket newHeads (RPC privé, ex. Chainstack/QuickNode)
                  → 1 bloc / 200 ms, état des pools en mémoire
2. Décision       math_engine.decide() : taille optimale, net > 3 $, net > gas × 3,
                  gas < plafond 2 gwei (gas.py, mesure live eth_gasPrice)
3. Preflight     preflight_roundtrip() : getAmountsOut on-chain + eth_estimateGas,
                  fraîcheur ≤ 2 blocs (400 ms) — sinon SKIP, 0 gas
4. Signature     Signer localement, ne jamais envoyer la clé au RPC
5. Envoi         eth_sendRawTransaction vers UN RPC privé de confiance
                  (Tatum/dRPC/GetBlock MEV-protected, ou direct séquenceur)
                  — pas de broadcast public (de toute façon impossible sur Base)
6. Inclusion     Bloc suivant (200 ms) ; vérifier le receipt + le profit réel
7. Garde-fous    Circuit breaker : 3 reverts → pause 1 h ; perte max 20 $/jour ;
                  kill switch ; journal de chaque décision (trades.jsonl)
```

**Coût latence de la vie privée :** sur Base, la vie privée est **gratuite en latence** — il n'y a pas de détour par des builders comme sur L1, le chemin privé *est* le chemin normal (séquenceur). Le seul surcoût mesurable vient des RPC à protection MEV qui ajoutent une simulation avant envoi (quelques dizaines de ms) — acceptable face à une fenêtre de 200 ms, mais à mesurer : si la simulation du RPC prend > 100 ms, elle coûte plus d'opportunités qu'elle n'en sauve. Le vrai coût, c'est le **choix du RPC** : le public `mainnet.base.org` est HTTP only, rate-limité (403 / RemoteDisconnected mesurés en fork test) et sans WebSocket — il faut un RPC privé dédié pour le live, même sans parler de MEV.

---

## 3. $0 MÊME SUR REVERT — la section exigée par Ismail (2026-11-24)

### 3.1 Le point de départ : ce que coûte un revert, chiffres mesurés

- **Règle de base (toutes chaînes EVM) :** une transaction incluse qui revert paie le gas consommé jusqu'au point de revert. Le travail a été fait, il est facturé. Source : Titania Research, « Revert Protection for Rollup » (2025) : « even if a transaction reverts, the gas consumed is not refunded ».
- **Mesure du bot (fork test, bloc 61 791 654) :** revert intentionnel = **54 829 gas = 0,0008 $** (à 0,0049 gwei, ETH 3 000 $). Le revert arrive tôt dans notre contrat (`require(profit >= minProfit)` en début d'`executeOperation`), donc il brûle peu de gas — c'est un choix de design, pas un hasard.
- **Prime flash loan sur revert : 0 $.** Le prêt est annulé atomiquement avec le revert — ni Aave (0,05 %) ni Balancer (0 %) ne facturent un prêt qui n'a pas eu lieu.
- **Pire cas théorique sans plafond :** si le contrat brûlait toute sa limite (450 000 gas) à 254 gwei (pic du 29 oct 2026), ça ferait ~343 $ — c'est exactement pour ça que le plafond **2 gwei** existe dans `gas.py` : au-dessus, le bot n'envoie rien. **Pire cas avec plafond :** 450 000 gas × 2 gwei × 3 000 $ = **2,70 $** si tout brûle (n'arrive pas — le revert est précoce), et **0,33 $** pour un revert précoce type mesuré (54 829 × 2 gwei). Le pire cas réel est donc de l'ordre du centime au pire des cas, pas du dollar — *à condition que le plafond soit respecté*.

### 3.2 Mécanisme par mécanisme : est-ce que ça donne $0 sur revert — et est-ce que ça existe sur Base ?

| # | Mécanisme | Comment il donnerait $0 sur revert | Existe sur Base nov 2026 ? | Verdict pour le bot |
|---|---|---|---|---|
| 1 | **Simulation off-chain avant broadcast** (`eth_call`, `eth_estimateGas`, fork Anvil, Tenderly) | On ne broadcast jamais un tx qui va revert : la simulation le voit, on SKIP, 0 gas. C'est une lecture seule. | ✅ Oui — déjà implémenté (`preflight.py`, fraîcheur ≤ 2 blocs ; `fork_simulation.py`) | **C'est LA garantie $0.** Elle ne protège pas contre un changement d'état entre la simulation et l'inclusion (400 ms), mais elle élimine ~99 % des reverts : ceux qu'on peut prévoir |
| 2 | **Proxy local d'interception (OP Security Proxy)** | Un middleware JSON-RPC entre le bot et le séquenceur : il intercepte `eth_sendRawTransaction`, simule avec revm contre l'état courant, et **abandonne le broadcast si la simulation revert** — « zero gas is burned on chain ». Overhead mesuré 11,8 ms en keep-alive ; simulation non cachée ~2,7 s (trop lente pour 200 ms sans cache d'état) | ⚠️ **Prototype / demande de subvention** (Optimism Collective, ~81 jours, GitHub `Ishant5436/op-sec-proxy`, 40 tests, MIT) — pas un service de production sur Base ; la phase finale prévoit Base, Mode, Zora, Fraxtal | **À surveiller, pas à adopter aujourd'hui.** Le concept est exactement le bon (simuler au plus près de l'envoi), mais l'implémentation n'est pas prête pour du 200 ms. À réévaluer quand le cache d'état local (objectif < 65 ms) sera livré |
| 3 | **Bundles privés avec protection revert (Flashbots `eth_sendBundle`)** | Le builder simule le bundle ; s'il revert, il n'est **pas inclus** et coûte 0 $ (sauf `revertingTxHashes` explicites). Docs Flashbots : « a bundle containing a transaction that reverts is not included in the block at all » | ❌ **Non — L1 uniquement.** Base : pas de marché de builders, pas de relay, pas d'`eth_sendBundle`. Confirmé par 3 sources indépendantes (playbook Base 2026, gouvernance Aave SVR, guides de recovery L2) | **Impossible sur Base.** C'est le mécanisme qu'Ismail décrit — il n'existe pas ici. Ne pas coder `eth_sendBundle` pour Base |
| 4 | **Flashbots Protect (revert protection)** | Le RPC privé simule et ne fait pas atterrir les txs qui revertent ; « If Protect detects that a transaction would revert, it is not included by default, so that failed attempt does not consume gas » | ❌ **Non — Ethereum L1 uniquement** (chain-id 1, `rpc.flashbots.net`) | **Impossible sur Base.** Citer Protect comme protection Base est l'erreur la plus fréquente (déjà flaggée dans `ADVANCED_RESEARCH.md` §3.1) |
| 5 | **MEV Blocker `/noreverts` / `/fullprivacy`** | Même principe : simulation + drop des txs qui revertent, via CoW/Agnostic Relay/BeaverBuild | ❌ **Non — L1 uniquement** (`/fast` = pas de revert protection ; `/noreverts` = avec, mais L1 seulement) | **Impossible sur Base** |
| 6 | **RPC privé avec simulation-and-drop (Tatum / dRPC / GetBlock-Merkle)** | Le RPC simule avant de transmettre au séquenceur et drop les échecs | ⚠️ **Non prouvé sur Base.** Les trois listent Base comme « protégée », mais leurs mécanismes de drop sont documentés pour l'écosystème L1 / builders ; aucune preuve publiée d'un drop garanti de revert sur Base. Tatum annonce Base « auto-enabled » sans détailler la simulation | **À tester, pas à supposer.** Protocole de test : envoyer sciemment un tx qui revert via ce RPC sur un fork/testnet et vérifier qu'il n'atterrit pas et ne coûte rien. Tant que ce test n'est pas fait, compter ce mécanisme comme **0 $ non garanti** |
| 7 | **Paymaster ERC-4337** | Le paymaster paierait à la place — donc 0 $ *pour Ismail*, même sur revert ? | ❌ **Non — le paymaster paie quand même.** « Validation succeeds, execution reverts, and the paymaster pays anyway » ; « If the operation fails, the Paymaster still pays the network fees » (docs ERC-4337 + audits). Le bundler simule seulement la *validation*, pas l'exécution | **Ne donne pas $0 sur revert.** Il déplace le coût vers le sponsor, qui le paiera — et qui coupera le financement après quelques reverts (griefing documenté). À exclure comme mécanisme $0-revert |
| 8 | **Relayer qui simule et drop (ERC-2771 ou relayer maison)** | Le relayer n'envoie que ce qu'il a simulé gagnant | ✅ **Possible en principe** — si le relayer est le nôtre ou celui du partenaire, avec un forwarder de confiance | **Fonctionne, mais le coût est déplacé, pas annulé** : quand sa simulation se trompe, c'est le relayer/sponsor qui paie le revert. Exiger un plafond contractuel (ex. le relayer ne couvre que N reverts/jour) et garder notre propre preflight en amont — le relayer est une 2e barrière, pas la 1re |
| 9 | **Base Transactions (EIP-8430), phases atomiques** | Les phases déjà complétées restent, les autres sont abandonnées | ⚠️ **Pas live** (Everest, dates TBD) — et la doc précise que le paiement sponsor en phase 0 « commits even if a later phase reverts » : le sponsor est remboursé en token si prévu, mais le gas est dû | **Pas utilisable aujourd'hui**, et ne donnerait pas $0 sur revert de toute façon |
| 10 | **Cancel / RBF (remplacement même nonce)** | Remplacer un tx en attente par un 0 ETH vers soi | ⚠️ Existe techniquement, mais **coûte du gas** (21 000 gas minimum, frais +10–20 % obligatoires) et **la fenêtre est de ~200 ms sur Base** : le temps de voir le tx, il est déjà dans un bloc | **Inutile pour nous.** Un cancel coûte plus cher qu'un revert précoce (0,0008 $) et arrive trop tard |
| 11 | **Revert précoce dans le contrat (`require` en tête)** | Le contrat vérifie le profit *avant* les swaps coûteux et revert immédiatement | ✅ Oui — déjà dans `contracts/FlashLoanArbitrage.sol` (`require(profit >= minProfit)`) | **Réduit le coût du revert, ne l'annule pas.** Mesuré : 54 829 gas (0,0008 $) au lieu de 450 000. C'est la dernière ligne de défense, pas la première |
| 12 | **Ne pas envoyer : fraîcheur + re-simulation juste avant l'envoi** | Re-vérifier le prix à N+1 juste avant de signer ; si le spread a disparu, abandonner sans rien envoyer | ✅ Oui — `preflight.py` (`is_fresh`, ≤ 2 blocs) + `executor.py` | **C'est le complément indispensable de la simulation** : la simulation dit « c'était gagnant au bloc N », la fraîcheur dit « c'est encore gagnant au bloc N+1 ». Sans elle, la simulation est une photo périmée |

### 3.3 Le design final qui approche le plus du $0 même sur revert

**Principe : 4 barrières en série, aucune ne suffit seule, ensemble elles rendent le revert on-chain rarissime et minuscule.**

```
Barrière 1 — MATH (0 $)         math_engine.decide() : net > 3 $ ET net > gas × 3,
                                 gas < 2 gwei, taille optimale (pas 10k $ aveugle)
Barrière 2 — PREFLIGHT (0 $)    preflight_roundtrip() : getAmountsOut on-chain +
                                 eth_estimateGas, fraîcheur ≤ 2 blocs (400 ms).
                                 LOSE / STALE / UNAVAILABLE → SKIP, 0 gas.
Barrière 3 — INTERCEPTION (0 $) [À AJOUTER] Proxy local type OP Security Proxy
                                 (ou fonction équivalente dans executor.py) :
                                 re-simuler avec revm juste avant eth_sendRawTransaction ;
                                 si ça revert → ne pas envoyer. Coût : ~12 ms (keep-alive).
Barrière 4 — CONTRAT (0,0008 $) require(profit >= minProfit) EN PREMIER dans
                                 executeOperation + deadline courte + minOutput strict.
                                 Si tout le reste a raté, le revert arrive tôt et coûte
                                 54 829 gas ≈ 0,0008 $ (0,33 $ au plafond 2 gwei).
Filet — CIRCUIT BREAKER (0 $)   3 reverts d'affilée → pause 1 h ; perte max 20 $/jour ;
                                 kill switch. Un bug systémique ne peut pas vider le wallet.
```

**Chiffrage du pire cas résiduel (avec ce design, en conditions normales) :**

| Scénario | Probabilité estimée | Coût si ça arrive | Coût attendu |
|---|---|---|---|
| Preflight dit WIN, spread encore là à l'inclusion | Cas normal (trade exécuté) | +3 $ à +70 $ (profit) | positif |
| Preflight dit LOSE/STALE/UNAVAILABLE → SKIP | ~67 % des opportunités (EV test : 67/100 skippées) | **0 $** | 0 $ |
| Preflight dit WIN mais le spread disparaît entre N et N+1 (≤ 400 ms) | Faible (spreads memes durent plusieurs blocs ; c'est le cas qui tue les bots de majors) | **0,0008 $** (revert précoce) | ~0 $ |
| Bug de contrat / taxe cachée / honeypot non détecté | Très faible si GoPlus + simulation buy/sell actifs | 0,0008 $ (revert) — ou perte totale si le contrat *n'*a pas reverté (d'où le vetting, pas le revert) | ~0 $ |
| Pic de gas pendant l'envoi | Bloqué par le plafond 2 gwei | **0 $** (pas d'envoi) | 0 $ |
| **Total attendu par opportunité** | — | — | **≈ 0,001 $ de gas de revert en espérance, contre +11,18 $ d'EV par opportunité (EV test v2)** |

**La phrase honnête à retenir :** on ne peut pas promettre « 0 $ même si le trade revert on-chain » comme une garantie protocolaire sur Base — personne ne le peut en nov 2026, parce que le mécanisme qui le permettrait (un builder qui simule et drop) n'existe pas sur cette chaîne. Ce qu'on peut promettre, et prouver, c'est : **« on n'envoie quasiment jamais un trade qui revert, et quand ça arrive malgré tout, ça coûte 0,0008 $, avec un plafond absolu de 0,33 $ et un arrêt automatique après 3 reverts »**. C'est la version honnête du $0 — et en pratique, sur 100 opportunités, le coût total des reverts est inférieur au profit d'un seul trade gagnant.

### 3.4 Ce qu'il ne faut pas faire en croyant obtenir $0 sur revert

- Ne pas envoyer des txs « pour tenter » en comptant sur le revert pour annuler : chaque tentative coûte du gas, et les bots qui spamment perdent exactement comme ça (95 % du spam Base, profit agrégé −28,07 ETH — `ADVANCED_RESEARCH.md` §5).
- Ne pas mettre `revertingTxHashes` / `canRevert=true` quelque part en espérant un drop gratuit : ces options n'existent que dans l'écosystème L1.
- Ne pas compter sur un paymaster pour absorber les reverts : il paie, puis il coupe.
- Ne pas essayer de « cancel » un tx sur Base : trop tard (200 ms) et plus cher que le revert lui-même.

---

## 4. Architecture $0 recommandée (classement)

| Rang | Option | $0 de poche ? | $0 sur revert ? | Privé ? | Verdict |
|---|---|---|---|---|---|
| 1 | **Profit paie le gas + simulation stricte + plafond gas + circuit breaker** (bot actuel, v2/v3) | ✅ Oui dès le 1er trade gagnant | ⚠️ 0,0008 $ résiduel | ✅ Oui (mempool privé du séquenceur par défaut) | **ADOPTER — c'est l'architecture de référence. Aucun tiers requis.** |
| 2 | **+ Sponsor/partenaire qui préfinance le gas, remboursé sur profits (25 % du net)** | ✅ Oui, y compris avant le 1er profit | ⚠️ Idem (le sponsor absorbe les 0,0008 $) | ✅ Oui | **ADOPTER pour le démarrage** — le seul « collab » qui a un sens économique |
| 3 | **+ RPC privé MEV-protected (Tatum/dRPC/GetBlock) + test de drop** | ✅ Oui (le RPC ne change pas qui paie) | ⚠️ À prouver par test sur Base | ✅ Oui (relais privé vers le séquenceur) | **TESTER** — ne pas supposer la protection revert ; mesurer la latence ajoutée |
| 4 | **+ Paymaster CDP (crédits Gasless Campaign) pour les tests** | ✅ Oui (crédits offerts, jusqu'à 15k $) | ❌ Non (le paymaster paie le revert) | ✅ Oui | **UTILE en test uniquement** — pas un modèle live, et les crédits sont temporaires |
| 5 | **+ Proxy d'interception local (type OP Security Proxy)** | ✅ Oui | ⚠️ Approche le $0 (2e simulation) | ✅ Oui | **SUIVRE** — pas prêt pour 200 ms aujourd'hui (simulation non cachée 2,7 s) |
| 6 | **Base Transactions EIP-8430 (sponsorship natif)** | ✅ Oui (quand live) | ❌ Non (phase 0 commit) | ✅ Oui | **ATTENDRE Everest** — dates TBD |
| 7 | **Flashbots Protect / MEV Blocker / eth_sendBundle sur Base** | — | — | — | **NE PAS ESSAYER — L1 uniquement, n'existe pas sur Base** |
| 8 | **« Sponsor gratuit sans contrepartie » (Telegram/YouTube)** | — | — | — | **ARNAQUE — ne jamais envoyer de fonds ni de clés** |

**Architecture recommandée (résumé en une phrase) :** bot v3 actuel (Balancer 0 % + simulation + preflight ≤ 2 blocs + plafond gas 2 gwei + circuit breaker) + un sponsor qui préfinance ~20 $ de gas et prend 25 % du profit net + un RPC privé de confiance — et **aucune** dépendance à un mécanisme L1 qui n'existe pas sur Base.

---

## 5. Intégration dans le bot — étapes exactes (fichiers à changer)

| # | Étape | Fichier(s) | Détail |
|---|---|---|---|
| 1 | **Journaliser le coût réel de chaque revert** (pour prouver le $0,0008 $) | `executor.py`, `circuit_breaker.py` (déjà `record_revert()`) | À chaque revert on-chain, enregistrer `gas_used × gas_price` en $ dans `trades.jsonl` ; alerter si un revert coûte > 0,50 $ (signe que le revert n'est pas précoce) |
| 2 | **Re-simulation juste avant l'envoi** (barrière 3) | Nouveau `presend.py` (ou fonction dans `executor.py`) | Après `preflight_roundtrip()`, juste avant `eth_sendRawTransaction` : re-appeler `getAmountsOut` + vérifier `is_fresh(block, block+1)` ; si LOSE/STALE → SKIP. Objectif : < 50 ms |
| 3 | **Proxy d'interception local (optionnel, v4)** | Nouveau `intercept_proxy.py` (inspiré d'OP Security Proxy, revm) | Simuler avec revm contre l'état local avant broadcast ; ne pas envoyer si revert. À n'activer que si la latence mesurée est < 65 ms (objectif du projet OP) |
| 4 | **Tester le drop d'un RPC privé MEV-protected** | Nouveau `test_private_rpc.py` | Envoyer sciemment un tx qui revert via Tatum/dRPC/GetBlock (fork ou testnet d'abord) ; vérifier : (a) atterrit-il ? (b) combien ça coûte ? Documenter le résultat dans `PRIVATE_RPC_TEST.md` — ne pas affirmer la protection sans ce test |
| 5 | **Sponsorship : config du paymaster / sponsor** | `config.yaml` (nouvelle section `sponsorship:`) | `mode: self | cdp_paymaster | partner_relayer`, `sponsor_address`, `sponsor_share_pct: 25`, `sponsor_gas_budget_usd: 20`, `sponsor_daily_cap_usd: 20`. Le bot refuse de démarrer en mode sponsor si l'adresse est vide |
| 6 | **Remboursement du sponsor sur profit** | `executor.py` (settlement) | Après chaque trade gagnant : `sponsor_cut = net × 25 %` comptabilisé dans `trades.jsonl` ; le split est une comptabilité off-chain tant qu'il n'y a pas de contrat de split — ne jamais donner au sponsor le contrôle des clés |
| 7 | **Vérifier le revert précoce du contrat** | `contracts/FlashLoanArbitrage.sol` | `require(profit >= minProfit)` doit rester la **première** vérification d'`executeOperation`, avant tout swap ; ajouter un test fork qui mesure le gas d'un revert (attendu ≈ 55k gas, pas 450k) |
| 8 | **Ne rien changer au chemin d'envoi pour « imiter Flashbots »** | — | Ne pas ajouter `eth_sendBundle`, `rpc.flashbots.net` ou MEV-Share : ils n'existent pas sur Base et feraient échouer les envois |
| 9 | **Surveiller Everest / Base Transactions** | `RESEARCH.md` (section à ajouter) | Vérifier chaque mois si EIP-8430 est activé sur Base mainnet ; quand ce sera live, migrer le sponsorship vers le `payer` natif (pas de paymaster, pas de bundler) |
| 10 | **Mettre à jour la doc** | `README.md`, `V2_CHANGELOG.md` | Ajouter la section « $0 / privé / revert » avec les chiffres de ce document (0,0008 $ mesuré, plafond 0,33 $, EV +11,18 $/opportunité) |

---

## 6. Ce qui est impossible — à dire clairement à Ismail

1. **Un revert on-chain 100 % gratuit, garanti par le protocole, sur Base en nov 2026 : impossible.** Il n'y a pas de builder qui simule et drop. Le meilleur design donne 0,0008 $ par revert, pas 0,0000 $.
2. **Un sponsor qui paie tout, sans rien en retour, sans limite : impossible.** Tout sponsor est payé — en markup (7–10 %), en % du profit, en crédits limités, ou en visibilité. S'il n'y a pas de contrepartie visible, la contrepartie est cachée — et c'est une arnaque.
3. **Annuler gratuitement un trade déjà envoyé : impossible.** Un cancel coûte du gas et arrive trop tard (200 ms).
4. **Cacher un trade au séquenceur lui-même : impossible.** Le séquenceur voit tout ce qu'il ordonne ; la protection, c'est la confiance dans Coinbase + le fait qu'un arbitrage atomique ne laisse rien à voler une fois exécuté.
5. **Un paymaster qui absorbe les reverts indéfiniment : impossible.** Il paie, puis il coupe (griefing documenté).
6. **Flashbots sur Base : n'existe pas.** Ni Protect, ni bundles, ni MEV-Share — en nov 2026.

**Ce qui est possible, et déjà en grande partie construit :** ne payer le gas que sur les profits (0,01 $/trade), ne jamais envoyer un perdant (0 $ sur ~67 % des opportunités + 0 $ sur les pics de gas bloqués), payer 0,0008 $ quand un revert passe malgré tout, et faire payer un partenaire uniquement sur le profit réel — avec des plafonds qui empêchent toute spirale de pertes.

---

## Sources — toutes vérifiées le 2026-11-24

- https://docs.base.org/specifications/base-transactions (EIP-8430, mise à jour 2026-11-13 ; Everest dates TBD)
- https://docs.base.org/get-started/private-transactions (Base Ledgers, mise à jour 2026-11-23)
- https://basehub.org/specifications/denim-overview/ ; https://basehub.org/specifications/denim-200ms-blocks/ (Denim, 5 nov 2026, 200 ms, Flashblocks retiré)
- https://docs.cdp.coinbase.com/paymaster/guides/build-sponsored-transaction-component
- https://www.alchemy.com/docs/wallets/reference/gas-manager-faqs (Gas Manager : 8 %, testnet gratuit)
- https://eco.com/support/en/articles/15254049-best-erc-4337-infrastructure-2026-alchemy-pimlico-biconomy-zerodev
- https://stablecoininsider.org/best-paymaster-providers-gas-in-usdc/ (Pimlico 10 % + 0,0075 $/op ; Alchemy 8 %)
- https://github.com/base/learn-docs/blob/HEAD/onchain-app-development/account-abstraction/gasless-transactions-with-paymaster.mdx (Base Paymaster : 10–15k $/mois, allowlist, limites par utilisateur)
- https://docs.erc4337.io/bundlers/simulation-requirements ; https://docs.erc4337.io/core-standards/erc-4337.html (« If the operation fails, the Paymaster still pays the network fees »)
- https://www.newexploits.com/blog/securing-erc-4337-smart-accounts (« Validation succeeds, execution reverts, and the paymaster pays anyway »)
- https://docs.df3ndr.com/Book/3/11/7-account_abstraction.html (« Paying for failed operations »)
- https://watswallet.com/blog/gasless-transactions-explained ; https://docs.settlemint.com/docs/concepts/custody-and-signing/gas-funding (relayer / meta-tx)
- https://chainstack.com/learn/how-to/how-to-get-base-rpc-endpoint-trading-bots-2026/ (« On Base there is no public mempool to snipe » ; « No built-in MEV relay or bundle submission »)
- https://collective.flashbots.net/t/who-actually-captures-mev-on-base-after-flashblocks-one-week-of-measurements/6120
- https://mevdao.org/blog/mev-on-layer-2-how-arbitrum-base-and-optimism-order-transactions
- https://governance.aave.com/t/arfc-aave-chainlink-svr-multi-network-expansion-base-arbitrum/24241/4 (« MEV-Share itself does not operate on these networks »)
- https://ai-frb.com/blog/base-playbook-first-private-bundle (« Flashbots-style private relays don't exist for Base in 2026 »)
- https://graph.org/What-Is-Flashbots-and-How-Does-Protect-Stop-Frontrunning-11-06 ; https://blog.web3wagmi.com/flashbots-guide (Protect : L1, 25 blocs de retry, 90 % refunds)
- https://mevdao.org/blog/flashbots-protect-vs-mev-blocker-which-private-rpc-should-you-use (MEV Blocker `/noreverts`, L1)
- https://mevdao.org/blog/what-is-mev-share-how-flashbots-pays-users-back-for-their-order-flow (90 % à tx.origin)
- https://docs.tatum.io/docs/mev-protection-transaction-bradcasting (Base auto-enabled, mise à jour 2026-03-20)
- https://blog.drpc.org/what-is-mev-blocker/ (dRPC : Base listée) ; https://getblock.io/marketplace/projects/mev-protection/ (GetBlock/Merkle : Base, plans payants)
- https://titaniaresear.ch/revert-protection-for-rollup (revert protection rollups, op-rbuilder)
- https://gov.optimism.io/t/builder-grant-proposal-op-security-proxy-local-pre-execution-revert-interception-for-the-superchain/10845 (OP Security Proxy : 11,8 ms, simulation 2,7 s non cachée, objectif < 65 ms)
- https://mohdshayan.com/blog/flash-loan-free-until-it-reverts/ (bundle revert = 0 $ sur L1 ; revert public mempool = gas plein)
- https://mevdao.org/blog/ethereum-transaction-stuck-pending-how-to-speed-up-or-cancel-it ; https://academy.binance.com/ka/articles/how-to-cancel-or-replace-a-pending-ethereum-transaction (cancel = nouvelle tx, 21 000 gas, +10 % de frais)
- https://zyekh.com/blog/mev-and-private-mempool-architecture-in-ethereum (bundles revert = 0 gas sur L1)
- https://onfinality.io/en/learn/ethereum-mev-bundle-eth-sendbundle-rpc (eth_sendBundle : builder-specific, pas dans execution-apis)
- https://www.spark.money/research/ethereum-gasless-paymaster-transaction-design (gas L2 : swap 0,10–0,50 $ ; markup 5–15 %)
- https://docs.proportion.finance/offering (modèle backer/trader on-chain)
- Fichiers du bot cités : `preflight.py` (fraîcheur ≤ 2 blocs), `gas.py` (plafond 2 gwei, gas live 0,006 gwei), `circuit_breaker.py` (20 $/jour, 3 reverts → pause 1 h), `math_engine.py` (Balancer 0 %, min 3 $), `fork_results.json` (revert 54 829 gas = 0,0008 $), `EV_RESULTS.md` (EV +11,18 $/opportunité, 33/100 exécutés), `ADVANCED_RESEARCH.md` §3.1/§5, `FORK_TEST_RESULTS.md`.
