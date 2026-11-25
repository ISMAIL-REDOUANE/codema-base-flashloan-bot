# CODEMA : lancer et vérifier

Le moteur actuel couvre USDC, WETH et cbBTC, les factories Base Uniswap V3 et
Pancake V3, et leurs différents niveaux de frais. Les autres venues, V2,
Aerodrome, Polygon et les meme coins restent hors de ce chemin d'exécution.
Un `dexId` ou une TVL DexScreener ne suffit pas à autoriser un pool.

## Installation reproductible

Python 3.12 et Node 22+ :

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run build
```

Le paquet npm fournit Anvil sur Linux x64. Un autre environnement peut fournir
son propre binaire par `ANVIL_BIN`. Aucune installation globale de solc/forge
n'est requise. Les bibliothèques Solidity existantes sont vendoriées dans `lib/`.

## Scanner sans portefeuille

```sh
.venv/bin/python bot.py scan --sizes 10,30,100,300,1000,3000
.venv/bin/python bot.py watch --iterations 2 --sizes 10,100,300
```

`BASE_RPC_URL` choisit le RPC. Le défaut public fonctionne pour la recherche,
mais ne suffit pas nécessairement pour trader : la validation réelle expire
après **deux blocs**, sans assouplissement automatique. Le watch publie les
blocs manqués et l'âge du snapshot. Il ne prétend pas couvrir chaque transaction
ou tous les états entre deux blocs. Une seule instance du watch ne peut pas
garantir de capturer les écarts brefs. La sélection des tailles est une grille
explicite, sans promesse d'optimum global.

Les frais des pools sont déjà inclus dans les sorties, donc jamais retranchés
deux fois. Le prêt Morpho est effectivement exécuté dans la simulation. Le
montant de prêt utilise les décimales du vrai token, avec un plafond de 50 % du
solde disponible chez Morpho. Les montants de valorisation sont en **USDC**,
sans supposer que son cours en dollars restera toujours égal à un.

Interprétation des statuts :

| Statut | Signification |
|---|---|
| `CHAINED_QUOTE_LOSS` | Sortie exacte des deux swaps inférieure au prêt, avant gas |
| `UNVERIFIED_CANDIDATE` | Quote positive, simulation atomique désactivée avec `--quotes-only` |
| `BELOW_MIN_NET` | Cycle simulé mais marge insuffisante après les coûts |
| `UNAVAILABLE` | Une preuve manque ou un appel échoue ; aucun envoi autorisé |
| `HISTORICAL_VERIFIED` | Cycle rentable dans un ancien état de bloc, déjà expiré |
| `SIMULATED_OPPORTUNITY` | Cycle vérifié encore récent ; nouvelle validation requise sur le contrat déployé |

Les coûts utilisent un gas limit majoré de 20 %, puis une marge de 25 % sur
L2 + L1 + opérateur. `getL1Fee` reçoit une enveloppe sérialisée complète. La
préparation réelle utilise aussi `getL1FeeUpperBound` pour couvrir le vrai nonce
et la signature. Un oracle indisponible bloque le verdict. Le prix WETH/USDC
provient d'un pool enregistré au même bloc que les quotes.

## Reproduire la preuve historique

```sh
.venv/bin/python scripts/verify_historical.py
.venv/bin/python scripts/verify_preparation.py
```

Ce script utilise seulement le RPC public en lecture et une instance Anvil
sur `127.0.0.1`. Il installe le runtime localement, exécute la route historique
Pancake → Uniswap au bloc 61 989 637 et vérifie le reçu, le remboursement et le
solde de profit. La clé Anvil est publique, réservée aux tests, et refusée par
la commande de trading réel. Un fournisseur d'archive peut être nécessaire si
le RPC public limite les anciennes données. Les coûts historiques ne couvrent
pas les frais de déploiement, de retrait, d'hébergement ou d'abonnement RPC.

## Préparer le déploiement et une transaction

Le contrôleur est une **adresse publique**. Ne jamais fournir une clé dans le
chat, un fichier versionné ou un argument de commande.

```sh
.venv/bin/python bot.py deployment --owner "$CODEMA_OWNER"
```

Cette commande produit une transaction de création non signée. Elle n'envoie
rien. Le portefeuille doit déployer le contrat sur Base et conserver son
adresse dans `CODEMA_CONTRACT`. Le projet ne contient pas de déploiement mainnet
effectué par cette modification.

Enregistrer **une seule ligne de candidat** de `quotes` dans `candidate.json`.
La préparation ignore son ancien prix, re-vérifie le bytecode du vrai contrat,
son propriétaire et Morpho, re-quote au nouveau bloc, puis simule la transaction
complète et chiffre les frais :

```sh
.venv/bin/python bot.py prepare --owner "$CODEMA_OWNER" \
  --contract "$CODEMA_CONTRACT" --candidate candidate.json \
  --min-net 0.01 --max-network-cost 0.05
```

Cela retourne une transaction **non signée**, ou `UNAVAILABLE` si les contrôles
échouent. Copier une transaction de fork en remplaçant son adresse est refusé.

## Envoi explicite d'une seule transaction

La commande suivante effectue un **vrai envoi** si les contrôles passent.
Elle n'est jamais appelée par `scan`, `watch`, les tests ou la preuve historique.
La clé doit être injectée par le gestionnaire de secrets de l'opérateur dans
`CODEMA_PRIVATE_KEY`. Les frais d'une transaction incluse qui revert restent
payables ; la marge positive d'une simulation ne garantit pas l'inclusion.

```sh
.venv/bin/python bot.py trade --broadcast --owner "$CODEMA_OWNER" \
  --contract "$CODEMA_CONTRACT" --candidate candidate.json \
  --min-net 0.01 --max-network-cost 0.05
```

Cette commande revalide tout, signe avec le propriétaire, contrôle à nouveau
fraîcheur/nonce/frais, puis soumet **une seule fois**. Elle exige un portefeuille
avec assez d'ETH pour les frais. Elle ne propose pas de boucle automatique
d'envois ni de budget journalier implicite. `SUBMITTED` ne signifie pas profit
réalisé : vérifier le reçu. `SUBMISSION_UNKNOWN` fournit le hash calculé
localement ; le rechercher avant de retenter. Le profit reste dans le contrat ;
seul son propriétaire peut appeler `withdraw(token)` via le portefeuille.

Le nouveau contrat est testé mais n'a pas subi d'audit externe. Cette livraison
ne prouve pas une rentabilité durable et n'a engagé aucun fonds mainnet.

## Tests

```sh
node scripts/compile_contracts.cjs --test
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest test_math_engine.py test_gas.py test_v2.py \
  test_balancer.py test_morpho.py test_sponsor.py test_zero_cost.py \
  test_circuit_breaker.py test_self_funded.py leadlag/test_route_verify.py \
  polygon -k 'not live' -q
```

Les tests EVM sont synthétiques et locaux. Ils couvrent notamment le prêt,
les callbacks, le budget d'entrée, les pertes avec un solde préexistant suffisant
pour les masquer, l'expiration et la compatibilité des deux callbacks de venue.
Les tests de régression vérifient le sélecteur V2 indépendant, le cas d'un faux
positif de quelques dixièmes de bp, les frais complets et l'absence de renvoi
automatique après un timeout de soumission. Les anciens rapports de replay et
leurs comptages ne sont pas recalculés par ce travail ; leurs chiffres de net
ne constituent pas une preuve d'exécution actuelle.
