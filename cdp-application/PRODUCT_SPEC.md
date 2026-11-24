# ArbAgent — Product Spec (CDP Gasless Campaign)

**Date :** 2026-11-24
**Statut :** Spécification pour la demande de crédits gas CDP — pas encore de produit live.
**Chaîne :** Base (8453) uniquement.
**Moteur :** flash loan Morpho Blue 0 % + arbitrage cross-DEX (Aerodrome ↔ Uniswap V2 / BaseSwap V2).
**Règle d'or :** simulation d'abord, exécution seulement si profit net simulé ≥ 3 $.

> Nom proposé : **ArbAgent** — « L'agent d'arbitrage flash-loan sur Base ».
> Alternatives : FlashAgent, ArbPilot. **[TODO ISMAIL : confirmer le nom final.]**
> Marque affichée proposée : « ArbAgent, par CODEMA ». [TODO ISMAIL : confirmer.]

## 1. Le produit en une phrase

ArbAgent est un tableau de bord public d'arbitrage : il détecte en temps réel les écarts de prix des meme coins sur Base, les simule, et n'exécute que les opportunités rentables (profit net ≥ 3 $) via un flash loan Morpho Blue — sans jamais détenir les fonds des utilisateurs.

## 2. À qui ça sert

- **Utilisateurs curieux / traders :** ils voient en direct les opportunités détectées, leur taille optimale calculée mathématiquement, et le résultat (exécuté / ignoré / pourquoi).
- **Coinbase / Base (pour la demande CDP) :** le produit embarque Base Accounts (Smart Wallet) : chaque visiteur peut créer un wallet en un clic (« Create Wallet » dans l'interface principale) et suivre le bot.
- **Ismail / CODEMA :** vitrine technique + moteur d'arbitrage réel, sans vendre de promesse de rendement.

## 3. Ce que l'utilisateur peut faire (et ne peut PAS faire)

| Action | Oui / Non |
|---|---|
| Voir les opportunités détectées en direct (token, spread, taille optimale, profit net simulé) | ✅ Oui |
| Créer un wallet Base Account en un clic (« Create Wallet ») | ✅ Oui |
| Voir l'historique des trades (simulés puis réels) avec profit net et gas payé | ✅ Oui |
| S'abonner aux alertes (opportunité ≥ 3 $ détectée) | ✅ Oui (phase 2) |
| Déposer des fonds dans le produit | ❌ Non — **aucune garde (no custody)** |
| Laisser le bot trader avec ses fonds | ❌ Non — le bot ne trade qu'avec le flash loan, jamais avec des fonds utilisateurs |
| Copier automatiquement les trades (copy-arb) | 🔶 Phase 2 — seulement via un vault non-custodial audité, jamais avant audit |

**Principe de non-garde :** le bot n'a jamais accès aux fonds d'un utilisateur. Le flash loan est emprunté et remboursé dans la même transaction ; le profit net va à une seule adresse (celle d'Ismail). Aucun dépôt, aucun retrait utilisateur n'existe dans le produit.

## 4. Fonctionnalités (v1 — ce qui sera live au lancement)

1. **Dashboard live :** opportunités détectées (token, DEX A/B, spread, taille optimale, profit net simulé, statut : exécuté / ignoré + raison).
2. **Base Account « Create Wallet » :** bouton dans l'interface principale (exigence du palier 5 000 $ de la campagne) via CDP Embedded Wallets / Smart Wallet.
3. **Historique transparent :** chaque trade exécuté montre loan, profit brut, frais flash (0 %), gas payé, profit net. Les chiffres simulés sont étiquetés « simulé », jamais présentés comme des gains réels.
4. **Garde-fous affichés :** min profit 3 $, plafond gas 2 gwei, disjoncteur (pause après 3 reverts), taille max 50 % du solde Morpho.
5. **Page « Comment ça marche » :** explication honnête (flash loan, simulation, risques, aucune garantie de profit).

## 5. Fonctionnalités (phase 2 — après crédits + audit)

- Alertes opportunités (email / Telegram).
- Vault copy-arb non-custodial (audit externe obligatoire avant).
- Support Uniswap V4 (70 % des nouveaux lancements) et adaptateur Aerodrome Route.

## 6. Stack technique (réel, déjà construit en simulation)

- **Moteur :** Python (`math_engine.py` : sizing optimal AMM + Kelly fractionné ; `scanner.py` : détection ; `executor.py` : dry-run ; `preflight.py` : simulation EVM).
- **Contrat :** `MorphoFlashLoanArbitrage` (Solidity, `contracts/FlashLoanArbitrage.sol`) — compilé, `forge build` exit 0 ; preuve fork bloc 61 807 834 : WIN +17,58 $ (loan 366,50 $), perdant SKIP 0 $, revert 0,0040 $.
- **Flash loan :** Morpho Blue `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`, fee 0 % (docs officielles), soldes live USDC ~328,9 M$ / WETH ~148,9 M$.
- **Garde-fous :** `zero_cost.py` (mode 0 $), `circuit_breaker.py` (perte journalière max 20 $, 50 trades/jour max), `gas.py` (plafond 2 gwei).
- **Tests :** math 8/8, v2 11/11, Morpho 12/12, sponsor 12/12, mode 0 $ 15/15.
- **Site :** page publique (voir `WEBSITE_CONTENT.md`) — hébergée via lien public d'artefact Muse (Netlify en pause jusqu'au 13 déc 2026, crédits épuisés).

## 7. Honnêteté du produit (ce qu'on ne promet pas)

- Aucun rendement garanti. Attente réaliste documentée : 0–3 opportunités exécutables ≥ 3 $/semaine, net souvent ≈ 0 $.
- Aucun frais caché pour l'utilisateur : il n'y a pas d'utilisateur payant en v1.
- Le gas des transactions du bot est sponsorisé par les crédits CDP (si approuvés) ou, en attendant, financé par Ismail lui-même (~20 $ de float ETH sur Base, il garde 100 % du profit, part sponsor 0 %).
- Audit professionnel du contrat obligatoire avant tout usage mainnet avec des fonds réels (aujourd'hui : simulation seulement, aucun fonds réel, aucune clé privée dans le repo).

## 8. Jalons (pour Founders Fuel : lancement public sous 3 mois)

| Jalon | Date cible |
|---|---|
| Pack de demande CDP + Founders Fuel prêt | 2026-11-24 ✅ |
| Landing page publique (lien artefact Muse) | Semaine du 24 nov 2026 |
| Bot re-architecturé en smart account + tests Base Sepolia | Déc 2026 |
| Demo vidéo publiée (Base App + X) | Déc 2026 |
| Demande CDP soumise (+ Founders Fuel en parallèle) | Dès que la landing est live |
| Lancement public du dashboard | Jan 2027 (≤ 3 mois) |
| Audit externe du contrat | Avant tout mainnet réel (financement : crédits/profits/sponsor) |
