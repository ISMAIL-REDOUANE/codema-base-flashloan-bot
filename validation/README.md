# Validation du moteur atomique

Modification préparée depuis `f2a9d2c6dba8edbeede4163bd1068457cba1805a`.
Vérifications locales du 25 novembre 2026. Aucun fonds mainnet engagé.

| Vérification | Résultat |
|---|---|
| Compilation solc 0.8.20, optimizer 200 | Réussie, y compris les contrats Polygon utilisés par leurs tests |
| Tests du nouveau moteur et du contrat | 23 réussis |
| Régressions Base, leadlag et Polygon | 306 réussis, 12 tests live exclus |
| Syntaxe Python | 99 fichiers valides hors dépendances |
| Cycle historique, bloc 61 989 637 | Reçu local réussi et principal Morpho entièrement remboursé |
| Préparation sur le code déployé localement | `UNSIGNED_REVALIDATED`, net prudent ≈0,02618 USDC |
| Deux snapshots récents du watch | 22 pools, 280 routes par snapshot, aucune opportunité positive détectée |

La preuve historique [`historical_61989637.json`](historical_61989637.json)
utilise les pools réellement enregistrés Pancake
`0x72AB388E2E2F6FaceF59E3C3FA2C4E29011c2D38` et Uniswap
`0xb4CB800910B228ED3d0834cF79D697127BBB00e5`. Le prêt de 300 USDC produit
0,039188 USDC brut. La transaction locale consomme 421 497 gas. L'estimation
prudente utilise un gas limit majoré, 0,01 gwei et une marge totale de 25 %,
plus L1 et opérateur lus au bloc historique : ≈0,012986 USDC de coûts budgétés,
donc ≈0,026202 USDC net simulé. Ces coûts sont une estimation, pas une facture
mainnet réglée. Les coûts de déploiement, de retrait et d'infrastructure sont
exclus. La préparation réelle ajoute une borne haute sur les frais L1.

Le test local protège aussi contre une perte couverte par un ancien solde du
contrat. Les régressions couvrent le sélecteur QuoterV2 correct, la sortie de
vente chaînée sur la sortie d'achat, l'indisponibilité de l'oracle, les clés de
test publiques, la fraîcheur et l'absence de renvoi automatique après timeout.
La CI est configurée mais n'a pas tourné sur GitHub pendant ce travail.

[`watch_summary.json`](watch_summary.json) mesure environ **30–32 secondes**
par snapshot sur le RPC public, soit **150–158 blocs** de retard au retour.
Cela ne respecte pas le budget d'exécution de deux blocs. Le bot le rapporte
et refuse une préparation périmée. Il faut une infrastructure beaucoup plus
rapide pour une capture en production ; ce travail ne démontre pas qu'elle
respectera le budget sur un fournisseur donné.

Les chiffres de replay historiques déjà présents dans le dépôt n'ont pas été
recalculés. Leurs positifs dynamiques ne sont plus rejetés collectivement à
partir de deux contre-exemples. Le replay corrigé lit les frais dans chaque
échantillon, garde le brut, et ne fabrique pas un net avec un gas absent.

Reproduire : `python scripts/verify_historical.py` puis
`python scripts/verify_preparation.py`. Les deux scripts écrivent exclusivement
sur leur instance Anvil locale et utilisent Base en lecture. Le résultat
historique n'est pas une opportunité actuelle, ni une garantie de revenu.
