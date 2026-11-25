# Test RÉEL end-to-end — Base Sepolia (84532)

**Date :** 2026-11-25 ~00:05–01:00 UTC — **Testnet uniquement, 0 $ réel, 0 mainnet.**

## VERDICT — en attente de funding, pas d'exécution réelle pour l'instant

**Le pipeline complet n'a PAS encore été exécuté.** Tout est construit, compilé,
vérifié on-chain et testé en dry-run — mais le wallet de test a **0 ETH Sepolia**,
donc aucun déploiement ni arbitrage réel n'a eu lieu. **BLOQUANT : 0,25 ETH testnet**
à récupérer par Ismail (2 min, navigateur, $0 — étapes exactes § Phase 2).
Une fois financé, une seule commande lance tout : `python3 sepolia/deploy_sepolia.py --all`.

Ce qui est PROUVÉ dès maintenant (on-chain, pas simulé) :
- Morpho Blue **existe** sur Base Sepolia (adresse canonique, 15 623 octets,
  DOMAIN_SEPARATOR non nul) **et détient de la vraie liquidité** :
  **120 324 USDC + 1,3485 WETH** → le flash loan 0 frais est réellement possible.
- Aave V3 **existe aussi** (2 déploiements, providers + pools avec code) → fallback confirmé.
- Uniswap V3 **existe** (factory + router + pools USDC/WETH à tous les tiers).
- Pas de router V2 connu sur Sepolia → les 2 venues V2 seront déployées
  (code Uniswap V2 canonique, vérifié byte à byte vs mainnet, § Phase 4).
- Tests : **12/12 verts** (artifacts, sizing, sécurité, gate de funding, dry-run).

## Phase 1 — Ce qui existe sur Base Sepolia (vérifié on-chain, bloc ~63 216 000)

| Contrat | Adresse | Code | Verdict |
|---|---|---|---|
| Morpho Blue | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` | 15 623 o | ✅ RÉEL — détient 120 324 USDC + 1,3485 WETH |
| Uni V3 Factory | `0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24` | 24 535 o | ✅ (≠ router V2 mainnet — même adresse, autre contrat) |
| Uni V3 SwapRouter02 | `0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4` | 24 497 o | ✅ |
| Uni V3 pools USDC/WETH (100/500/3000/10000) | `0x5718…`, `0x94bf…`, `0x4688…`, `0x4664…` | 22 142 o chacun | ✅ |
| Aave Provider A → Pool A | `0xd449FeD49d9C443688d6816fE6872F21402e41de` → `0x07eA79F68B2B3df564D0A34F8e19D9B1e339814b` | 6 840 / 1 892 o | ✅ fallback |
| Aave Provider B → Pool B | `0xE4C23309117Aa30342BFaae6c95c6478e0A4Ad00` → `0x8bAB6d1b75f19e9eD9fCe8b9BD338844fF79aE27` | 6 697 / 1 853 o | ✅ fallback |
| WETH (predeploy) | `0x4200000000000000000000000000000000000006` | 2 041 o | ✅ |
| USDC (Circle) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | 1 798 o, 6 déc. | ✅ |
| Multicall3 | `0xcA11bde05977b3631167028862bE2a173976CA11` | 3 808 o | ✅ |
| Uni V2 Router02 / Sushi V2 / Uni V3 Factory canonique | adresses mainnet | 0 o | ❌ absents sur Sepolia |
| Aerodrome | — | — | non vérifié (non nécessaire) |

RPC : Alchemy Base Sepolia (app « Base-Bot », clé dans `sepolia_config.json`,
**gitignored**), fallback `https://sepolia.base.org`. Gas Sepolia : 0,006 gwei.
Preuves brutes : `sepolia/probe_sepolia.json`, `probe2_sepolia.json`.

**Choix du lender : Morpho Blue** (le contrat `MorphoFlashLoanArbitrage` du repo,
inchangé, est utilisé tel quel — il est codé pour Morpho + jambes V2).

## Phase 2 — Wallet de test + FUNDING (BLOQUANT)

- Wallet testnet frais, généré localement (eth_account) :
  **adresse `0x207F25f511e5B5e0C19BFD6ac3Cd2D85cce771B1`**
  Clé privée : **uniquement** dans `sepolia/.test-wallet.json` (gitignored,
  jamais affichée, jamais commitée, jamais utilisée sur mainnet).
- Solde actuel : **0 ETH** → `deploy_sepolia.py --check-funding` sort en code 2
  avec le message `FUNDING REQUIRED` (testé).

### Ce qu'Ismail doit faire (navigateur, ~2 min, $0)
1. Aller sur **https://faucets.chain.link/base-sepolia**
2. Connecter **SON propre wallet MetaMask** (pas le wallet de test).
3. Réclamer **0,5 ETH test + 25 LINK test**.
4. Envoyer **0,25 ETH test** au wallet de test :
   `0x207F25f511e5B5e0C19BFD6ac3Cd2D85cce771B1`
5. Dire à Muse que c'est fait → relancer `python3 sepolia/deploy_sepolia.py --all`.

Pourquoi Chainlink et pas un autre faucet : Alchemy exige 0,001 ETH d'activité
sur Ethereum mainnet à la même adresse (le wallet frais ne qualifie pas) ;
le faucet PoW pk910 n'est pas résolvable depuis cette VM ; les autres demandent
un compte (CDP, QuickNode) ou un captcha. Aucun faucet à API sans login n'a pu
être utilisé — **aucun funding n'a été simulé ou inventé**.

Besoin total : **0,21 ETH** (0,20 pour le seeding des pools + ~0,01 de gas).

## Phase 3 — Déploiement (PRÊT, non exécuté — attend le funding)

`sepolia/deploy_sepolia.py --all` déploie, dans l'ordre :
1. `TestMeme` (ERC20 test, 1 000 000 TMEME au déployeur).
2. V2 Factory A + Router A (venue « DEX A »), V2 Factory B + Router B (« DEX B »).
3. `MorphoFlashLoanArbitrage` avec **loan token = WETH** (voir § Phase 4),
   `minProfit = 0,001 WETH` (~1,68 $).
4. Adresses + tx hashes → `sepolia/deployment.json`.

## Phase 4 — Arbitrage réel (PRÊT, non exécuté — attend le funding)

### Design du test (honnête, documenté)
- **Deux venues V2 fraîches** (code Uniswap V2 canonique) : il n'existe pas de
  router V2 connu sur Sepolia. La Factory et le Router sont déployés deux fois
  (DEX A et DEX B) — pools réelles, swaps réels, code réel.
- **Spread créé délibérément** (c'est le but du test — mesurer le pipeline,
  pas découvrir un spread de marché) :
  - Pool A : 0,10 WETH + 100 MEME → 1 MEME = 0,001 WETH
  - Pool B : 0,10 WETH + 66,666… MEME → 1 MEME = 0,0015 WETH (**spread 50 %**)
- **Token de prêt = WETH, pas USDC** : Morpho Sepolia détient 1,35 WETH ;
  seeder des pools USDC demanderait ~20 000 USDC (les faucets donnent 10–20 USDC)
  alors que le WETH vient du wrap de l'ETH du faucet. Le contrat est
  token-agnostique (son paramètre `USDC` = adresse du token emprunté) — le
  chemin de code du flash loan exercé est **identique**.
- **Sizing mathématique** (`math_engine.find_optimal_loan`, pools L + spread 50 %) :
  prêt optimal **0,008866 WETH (~14,86 $)**, net attendu **+$3,28 (~0,001957 WETH)**,
  au-dessus de la règle min-profit 3 $ du bot. Le script re-vérifie ce sizing
  par des **quotes live on-chain** (`getAmountsOut` sur les deux routers) pour
  plusieurs tailles de prêt et n'exécute que si le net simulé > minProfit,
  puis simule `executeArbitrage` par `eth_call` (0 gas) avant d'envoyer.
- **Preuve de canonicité V2** (`sepolia/verify_v2_artifacts.py`) :
  factory runtime 13 859 o = mainnet, router runtime 17 891 o = mainnet
  (optimizer runs 999999 factory / 200 router, solc 0.5.16 / 0.6.6).
  Seul écart : le hash de création de la Pair diffère du hash canonique
  (`e8e45841…` vs `96e8ac…`) **à cause des métadonnées du compilateur**
  (chemins de sources) — la logique est identique. Comme tous les forks V2
  (SushiSwap, PancakeSwap), la constante est adaptée à NOTRE factory :
  `UniswapV2Library.pairFor()` patchée dans `lib/v2-periphery` (commentaire
  dans le fichier + vérification que le router embarque bien le nouveau hash).
  Sans ce patch, le router calculerait de fausses adresses de pairs.

### Ce qui sera enregistré (quand financé)
Pour chaque tx : hash, bloc, gas utilisé — déploiement, wrap, createPair,
addLiquidity, `executeArbitrage`, `withdrawProfit` — vérifiables sur
https://sepolia.basescan.org. Le rapport sera complété avec les résultats
réels (profit/perte en WETH, gas payé).

### Si Morpho n'avait pas existé
Fallback prévu (non utilisé — Morpho existe) : Aave `FlashLoanArbitrage`
(adresses provider A/B ci-dessus) ou, en dernier recours seulement, un mock
lender étiqueté **TEST DOUBLE** — jamais présenté comme un vrai lender.

## Tests — 12/12 verts

`.venv/bin/python -m unittest sepolia.test_sepolia -v` — 7,8 s :
artifacts (forge + V2), cohérence du hash V2, tailles = mainnet, sizing
(prêt 14,86 $ / net 3,28 $), gitignore des secrets, non-fuite de la clé
(setup_rpc + deploy), Morpho live avec liquidité, gate de funding (exit 2),
dry-run déploiement (6 contrats, 0 envoi, 0 état persisté).

## Fichiers créés (tout dans `sepolia/`, sauf les libs V2)

- `sepolia_config.json` (RPC Sepolia — **gitignored**, contient la clé Alchemy)
- `.test-wallet.json` (wallet test — **gitignored**, jamais imprimé)
- `setup_rpc.py`, `probe_sepolia.py`, `probe2_sepolia.py`, `probe3_sepolia.py`,
  `probe_sepolia.json`, `probe2_sepolia.json` (Phase 1)
- `foundry.toml`, `contracts/TestMeme.sol`, `contracts/Arb.sol`
  (compilation du contrat Morpho + token test)
- `compile_v2.sh`, `artifacts-v2/factory-0.5.16.json`,
  `artifacts-v2/router-0.6.6.json`, `verify_v2_artifacts.py` (V2 canonique)
- `deploy_sepolia.py` (pipeline complet : deploy → seed → arb, `--dry-run`,
  `--check-funding`, `--step`, reprise via `deployment.json`)
- `test_sepolia.py` (12 tests), `SEPOLIA_REAL_TEST.md` (ce rapport)
- `lib/v2-core` (v1.0.1), `lib/v2-periphery`, `lib/uniswap-lib` (v2.1.0)
  (+ `foundry.lock`, `.gitmodules` — ajoutés par `forge install`)
- `out/` + `cache/` (build — gitignored)

**Rien n'a été commité** (le parent gère GitHub). **Aucune modification de
`polygon/`** (autres agents). **Aucune tx mainnet, aucun fond réel.**
