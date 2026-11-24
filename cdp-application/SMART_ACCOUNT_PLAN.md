# ArbAgent — Plan de re-architecture Smart Account (CDP Paymaster)

**Objet :** passer l'exécution du bot d'un EOA classique à un smart account, pour pouvoir utiliser le CDP Paymaster (le sponsoring de gas ne fonctionne qu'avec des smart accounts ; un EOA upgradé EIP-7702 fonctionne aussi).
**Statut :** PLAN SEULEMENT — aucune modification de code dans ce pack.
**Date :** 2026-11-24.

## 1. Pourquoi c'est nécessaire

- Le CDP Paymaster ne sponsorise que les smart accounts (EIP-4337) — un EOA classique ne peut pas en bénéficier.
- Sans cette migration, les crédits CDP (si approuvés) sont inutilisables par le bot.
- La migration est aussi un prérequis pour le « pay gas from retained profit » (ERC-20 paymaster) : le profit USDC reste dans le smart account et paie le gas suivant.

## 2. Option recommandée : CDP Smart Wallet (Embedded Wallets)

| Option | Avantages | Inconvénients |
|---|---|---|
| **CDP Smart Wallet (recommandé)** | Intégration native avec le CDP Paymaster ; pas de gestion de bundler ; support Base Accounts direct | Dépendance à l'infra CDP (acceptable : c'est le programme qui finance) |
| Kernel / ZeroDev smart account | Plus portable, standard ERC-4337 | Intégration Paymaster CDP à vérifier ; plus de travail |
| EOA upgradé EIP-7702 | Garde la même adresse EOA | EIP-7702 sur Base à vérifier au moment de l'implémentation ; délégation révocable à gérer |

**Décision :** CDP Smart Wallet en premier. **[TODO ISMAIL : confirmer — aucun coût, juste un choix technique.]**

## 3. Architecture cible

```
Aujourd'hui (EOA) :            Après (smart account) :
EOA (Ismail)                    Smart account CDP (owner = Ismail)
  └─> appelle                    ├─> owner : MorphoFlashLoanArbitrage
      MorphoFlashLoanArbitrage   │     (le contrat reste owner = smart account)
      (owner = EOA)              ├─> Paymaster CDP : sponsorise le gas des UserOps
                                 └─> Profit USDC retenu dans le smart account
                                      → paie le gas suivant (ERC-20 paymaster, phase 2)
```

- Le contrat `MorphoFlashLoanArbitrage` ne change pas de logique : seul son `owner` passe de l'EOA au smart account.
- Le `minProfit ≥ 3 $`, le plafond gas 2 gwei et le disjoncteur restent identiques.
- Le smart account est le seul appelant autorisé par le paymaster (allowlist, voir `GAS_POLICY.md`).

## 4. Étapes (ordre)

1. **Créer le smart account** dans le portail CDP (compte d'Ismail) — pas de fonds nécessaires à ce stade.
2. **Configurer le Paymaster CDP** sur Base Mainnet (+ Base Sepolia pour les tests) avec la policy de `GAS_POLICY.md` (allowlist = contrat, plafonds).
3. **Transférer l'ownership du contrat** (déploiement mainnet futur) vers le smart account — à faire au moment du déploiement mainnet, pas avant.
4. **Adapter l'off-chain** : l'envoi de transaction devient un UserOp (via le bundler CDP) au lieu d'une transaction EOA brute.
5. **Tester de bout en bout sur Base Sepolia** (voir §5) avant toute chose sur mainnet.
6. **Tester le basculement crédits → float autofinancé** (coupure simulée des crédits).

## 5. Tests sur Base Sepolia (gratuits, à faire d'abord)

- Faucets test ETH (aucun ne donne du mainnet ETH — Sepolia seulement, c'est le but) :
  - Chainlink faucet : 0,5 test ETH par drip.
  - Alchemy faucet : 0,1 ETH / 24 h.
  - CDP faucet : 0,0001 ETH par claim, jusqu'à 1 000 claims / 24 h.
- Scénario de test : déployer le contrat sur Sepolia → smart account CDP → Paymaster Sepolia → exécuter un arbitrage simulé (spread synthétique) → vérifier que le gas est sponsorisé (0 ETH dépensé par le smart account) et que le profit net ≥ 3 $ est respecté.
- Critère de succès : 5 trades simulés consécutifs sur Sepolia avec gas sponsorisé à 0 $ et garde `minProfit` respectée.

## 6. Fichiers à toucher plus tard (ne pas modifier maintenant)

| Fichier | Changement prévu |
|---|---|
| `config.yaml` | Nouvelle section `smart_account:` (adresse, type CDP/Kernel/EIP-7702, paymaster URL) ; `gas_payer: "cdp-paymaster"` quand les crédits sont approuvés |
| `executor.py` | Envoi via UserOp (bundler CDP) au lieu de transaction EOA brute ; garde `minProfit` inchangée |
| `gas.py` | Lecture du gas sponsorisé (UserOp) en plus du gas EOA ; plafond 2 gwei inchangé |
| `sponsor.py` | Le « sponsor » devient le paymaster CDP : le partage 25 % ne s'applique plus (Ismail autofinance en attendant, part sponsor 0 %) — à mettre à jour quand les crédits arrivent |
| `zero_cost.py` | Allow-list : ajouter `cdp-paymaster` comme payeur de gas autorisé (Ismail paie toujours 0 $) |
| `contracts/FlashLoanArbitrage.sol` | `owner` = smart account au déploiement ; aucune logique modifiée |
| `test_*.py` | Nouveaux tests : UserOp sponsorisée sur fork Sepolia, basculement crédits → float |
| `dry_run.py` | Afficher le payeur de gas (CDP / float Ismail) dans le résumé |

## 7. Risques connus

- **Latence ERC-4337 :** un UserOp passe par un bundler (+~22 000 gas, et un délai) — pour une course de 200 ms, c'est un handicap. Mitigation : simulation stricte avant envoi, et priorité au bundler CDP (même infra que le Paymaster).
- **Crédits non approuvés :** la migration reste utile (le smart account servira aussi au « pay gas from profit »), mais le gas reste autofinancé par Ismail en attendant.
- **EIP-7702 :** si l'option EIP-7702 est choisie, vérifier sa disponibilité sur Base au moment de l'implémentation.
- **Aucun fonds réel** n'est engagé pendant cette migration : tests Sepolia d'abord, mainnet seulement après audit.
