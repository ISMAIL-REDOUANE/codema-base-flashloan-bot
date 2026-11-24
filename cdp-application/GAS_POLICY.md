# ArbAgent — Gas Policy (pour le formulaire CDP)

**Objet :** politique de sponsoring du gas pour ArbAgent, à coller / résumer dans la réponse du formulaire « Coinbase Paymaster Gas Credits » (question obligatoire : gas policy + mitigation farmers/bots).
**Date :** 2026-11-24.

## 1. Principe

Le gas n'est sponsorisé que pour **notre propre contrat d'arbitrage**, jamais pour le public en général. Il n'existe **aucun endpoint ouvert** de sponsoring : personne d'autre que le bot ne peut déclencher une transaction sponsorisée.

## 2. Allowlist (liste blanche stricte)

- **Seul contrat autorisé :** `MorphoFlashLoanArbitrage` (adresse : **[TODO : adresse après déploiement mainnet — le contrat n'est pas encore déployé, simulation seulement aujourd'hui]**).
- Le paymaster n'accepte que les UserOperations dont le `callData` cible ce contrat et dont l'appelant est le smart account du bot.
- Toute autre adresse, tout autre contrat, tout autre appelant → rejet automatique.
- L'allowlist est modifiable uniquement par Ismail (owner), avec un délai de 24 h et une annonce publique sur le dashboard.

## 3. Plafonds proposés (à confirmer avant soumission)

| Plafond | Valeur proposée | Justification |
|---|---|---|
| Gas max par UserOp | 0,10 $ | Un trade d'arbitrage sur Base coûte ~0,001–0,02 $ ; 0,10 $ laisse une marge de 5–100× pour les pics |
| Dépenses gas par jour | 20 $ | = plafond du disjoncteur du bot (perte journalière max 20 $) |
| Dépenses gas par mois | 500 $ | 25 jours × 20 $ ; les crédits de 15 000 $ couvrent ~30 mois à ce rythme |
| Trades sponsorisés par jour | 50 max | = plafond du disjoncteur du bot |
| Profit net minimum par trade | 3 $ | Garde on-chain `minProfit` : un trade sous 3 $ revert, donc ne consomme pas de gas sponsorisé inutilement |

**[TODO ISMAIL : confirmer ces plafonds — ils sont modifiables après approbation.]**

## 4. Mitigation « farmers / bots » (réponse à la question obligatoire du formulaire)

Le risque que le formulaire veut écarter, c'est le sponsoring ouvert exploité par des fermes de bots. Notre cas est l'inverse :

1. **Pas de sponsoring ouvert :** le paymaster ne sponsorise qu'un seul contrat, le nôtre, appelé par un seul smart account, le nôtre. Il n'y a rien à « farmer ».
2. **Pas d'utilisateur sponsorisé :** les visiteurs du site créent un Base Account pour *suivre* le bot, pas pour envoyer des transactions sponsorisées. Leurs wallets ne reçoivent aucun gas sponsorisé.
3. **Garde on-chain :** chaque trade exige un profit net simulé ≥ 3 $ avant envoi, et un profit net on-chain ≥ 3 $ (`require(profit >= minProfit)`), sinon la transaction revert. Un attaquant ne peut pas transformer le sponsoring en extraction : un trade non rentable ne s'exécute pas.
4. **Plafond gas 2 gwei :** le bot ne surenchérit jamais au-delà de 2 gwei, donc pas de guerre de gas.
5. **Disjoncteur :** 3 reverts → pause 1 h ; perte journalière max 20 $ → arrêt du jour ; 50 trades/jour max.
6. **Monitoring + kill switch :** chaque UserOp sponsorisée est loguée (montant, contrat, résultat) ; Ismail peut couper le sponsoring en une action (révocation du paymaster) ; alertes si la dépense journalière dépasse 50 % du plafond.
7. **Pas de valeur extractible :** le profit d'un trade va à une seule adresse (Ismail), jamais à un tiers ; il n'y a pas de token, pas d'airdrop, pas de récompense à farmer.

## 5. Maximiser l'impact des crédits (réponse à la 2e partie de la question)

- Chaque dollar de crédit finance uniquement des trades **déjà simulés rentables** (≥ 3 $ net) : le crédit ne paie jamais un trade perdant, puisque les perdants sont annulés avant envoi (coût 0 $).
- Les crédits servent aussi à l'onboarding : le bouton « Create Wallet » fait découvrir Base Accounts aux visiteurs du dashboard, sans que leur wallet reçoive de gas sponsorisé.
- Si les crédits s'épuisent, le bot repasse automatiquement sur le float gas autofinancé d'Ismail (~20 $ ETH) : aucune interruption, aucun coût caché pour un tiers.

## 6. Texte court à coller dans le formulaire (EN)

> Gas is sponsored only for our own arbitrage executor contract (allowlisted, single address, single smart-account caller). No open sponsorship endpoint exists, so there is nothing to farm: visitors create a Base Account to follow the bot, their wallets receive no sponsored gas. Every trade is simulated off-chain first and requires ≥ $3 simulated net profit; the contract enforces minProfit ≥ $3 on-chain, so unprofitable trades never execute. Caps: $0.10 gas per UserOp, $20/day, $500/month, 50 trades/day max, 2 gwei gas cap, circuit breaker (pause after 3 reverts). All sponsored UserOps are logged and the sponsorship can be revoked in one action. No token, no airdrop, no reward to farm.
