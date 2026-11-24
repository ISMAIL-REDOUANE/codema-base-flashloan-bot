# FORK TEST — Résultats V2 (2026-11-24)

**Seuil utilisé : min_profit_usd = 3,00 $** (confirmé par Ismail le 2026-11-24,
`config.yaml` mis à jour en conséquence : sections `math` et `executor`).

**Aucun fond réel, aucune clé privée d'utilisateur, aucun broadcast mainnet.**
Tout s'est passé sur un fork local jetable d'Anvil (Base mainnet, chain 8453).
La seule clé utilisée est la clé de TEST publique d'Anvil (compte 0).

## 0. Ce qui est PROUVÉ vs NON PROUVÉ

| Élément | Statut |
|---|---|
| Le contrat Solidity compile et se déploie | ✅ **PROUVÉ 2026-11-24** — voir §10 |
| `executeOperation` / `require(profit >= minProfit)` on-chain | ✅ **PROUVÉ** — cas gagnant WIN +$17,24, cas perdant revert confirmé (§10) |
| L'économie de l'arbitrage sur le fork (vrais routers, vraies réserves) | ✅ **PROUVÉ** — net réel +422,39 $ (§4) |
| Le sizing mathématique (Python) vs le réel on-chain | ✅ **PROUVÉ** — écart 1,35 $ (§4) |
| La règle GAS : perdant = SKIP, 0 gas | ✅ **PROUVÉ** (§5) |
| Le coût d'un revert sur Base | ✅ **MESURÉ** — 0,0008 $ (§5) |
| Prime flash Aave 0,05 % + liquidité dispo | ✅ **PROUVÉ on-chain** (§2) |
| Un vrai meme coin 5k–100k $ avec 2 paires V2 | ❌ **Non trouvé** dans cet essai (§3) |
| **Morpho Blue 0 % (fee structurel, pas de getter flashFee)** | ✅ **PROUVÉ 2026-11-24** — voir §11 |
| **Contrat MorphoFlashLoanArbitrage sur fork** | ✅ **PROUVÉ** — cas gagnant WIN +$17,58, cas perdant revert confirmé (§11) |
| **Balancer** | ⛔ **MORT (BIP-928, 30 oct 2026)** — ne plus utiliser, voir §11.5 |

## 1. ⛔ BLOCAGE : compilation du contrat impossible pour l'instant

> ✅ **RÉSOLU le 2026-11-24 — voir §10.** Ismail a autorisé la compilation
> (« kmel lkhedma, aya haja dirha nta »). Les librairies officielles ont
> été installées **par tarballs** (pas de `forge install`, pas de sous-module
> git) : OpenZeppelin v4.9.6 + Aave v3-core v1.19.4, remappings manuels.
> `forge build` OK, contrat déployé et testé sur le fork (WIN +17,24 $).
> Le récit ci-dessous est conservé pour l'historique.

**Ce qui s'est passé, dans l'ordre :**
1. Foundry 1.10.0 installé proprement (téléchargement officiel vérifié,
   `forge/anvil/cast 1.10.0`, commit `083e229941`).
2. `forge install OpenZeppelin/openzeppelin-contracts@v4.9.6` lancé —
   le contenu cloné dans `lib/` a **échoué un contrôle de risque
   d'exécution** du système (fichier `.git` de sous-module). Instruction
   reçue : ne pas exécuter / compiler / charger ce contenu, et demander
   confirmation avant de continuer.
3. J'ai **arrêté immédiatement** le `forge install` en cours (clone
   d'`aave-v3-core` interrompu) et je n'ai **pas** lancé `forge build`.

**Conséquence :** pas de bytecode, pas de déploiement du contrat sur le fork,
pas de test de `executeArbitrage` / `executeOperation` / du `require`.
Les scripts `fork_test.py` / `fork_test.sh` (chemin complet : compilation +
déploiement + `eth_call` + broadcast sur le fork) sont prêts et attendent.

**Pour débloquer :** Ismail doit confirmer explicitement qu'on peut compiler
avec les dépendances officielles OpenZeppelin v4.9.6 + Aave v3-core
(`forge install` puis `forge build`). Une fois confirmé, la commande est :
```bash
cd ~/workspace/crypto-base-flashloan-bot
export PATH="$HOME/.foundry/bin:$PATH"
forge install OpenZeppelin/openzeppelin-contracts@v4.9.6 --no-commit
forge install aave/aave-v3-core --no-commit
forge build            # solc 0.8.20, optimizer 200 runs (voir foundry.toml)
bash fork_test.sh      # fork + déploiement + cas gagnant/perdant on-chain
```
`fork_test.py` a déjà été corrigé en attendant : clé Anvil corrigée
(`...f2ff80`), tx EIP-1559 (voir §6), adresses checksum pour GeckoTerminal.

## 2. Outils trouvés / installés

| Outil | Résultat |
|---|---|
| `forge` / `anvil` / `cast` | Absents → installés, **Foundry 1.10.0** (build 2026-11-19) |
| `solc` | Absent → non installé (Foundry télécharge solc 0.8.20 au build) |
| `node` | 24.22.1 (déjà présent) |
| `python3` | 3.12.3, `web3` 8.0.0 installé dans `.venv/` (pip système bloqué par PEP 668 → venv local) |
| RPC fork | `https://mainnet.base.org` (public, sans clé) |

## 3. Commandes exactes (reproductibles)

```bash
cd ~/workspace/crypto-base-flashloan-bot
export PATH="$HOME/.foundry/bin:$PATH"
# Fork Anvil (jetable) :
anvil --fork-url https://mainnet.base.org --chain-id 8453 --port 8545 \
  --gas-price 50000000 --no-rate-limit
# Simulation (sans compilation) :
.venv/bin/python fork_simulation.py
# Résultats machine : fork_results.json
```

**Bloc du fork au lancement : 61 791 654** (`0x3aedda6` au démarrage d'Anvil,
61 791 654 au premier appel du script). Le fork est stateful : chaque
exécution modifie l'état — redémarrer Anvil pour des chiffres propres.

## 4. CAS GAGNANT — round-trip réel sur le fork ✅

### État réel lu on-chain (bloc 61 791 654)
- **Aave V3** : `FLASHLOAN_PREMIUM_TOTAL` = **5 bps = 0,05 %** (confirmé).
  Liquidité USDC disponible : **13 637 593,65 $** — mais attention, elle
  est dans le **aToken aBasUSDC** (`0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB`),
  **pas** dans le Pool (qui ne détient que **123,47 $**). La v1 supposait
  le Pool : correction à appliquer dans le code/scanner.
- **Uniswap V2 WETH/USDC** (`0x88A43bbDF9D098eEC7bCEda4e2494615dfD9bB9C`) :
  289,79 WETH / 486 389,15 $ → prix **1 678,44 $/WETH**.
- **Aerodrome WETH/USDC volatile** (`0xcDAC0d6c6C59727a65F871236188350531885C43`) :
  206,46 WETH / 347 100,72 $ → prix **1 681,18 $/WETH**.
- **SushiSwap V2 WETH/USDC** (`0x2F8818D1B0f3e3E295440c1C0cDDf40aAA21fA87`) :
  0,83 WETH / 1 395,68 $ → **~2 800 $ de liquidité totale : inutilisable**
  comme jambe de vente (plafond 10 % = 139 $ de loan).
- Spreads naturels : Uni↔Sushi **0,07 %**, Uni↔Aerodrome **0,16 %** —
  comme attendu, rien à arbitrer sur une paire liquide.

### Spread synthétique (fonds fictifs du fork)
Vente de **14,49 WETH** contre USDC sur Uni V2 → prix Uni **1 522,61 $**
vs Aero **1 681,18 $** → **spread 10,41 %**. (Sur un petit pool, vendre
5 % de la réserve fait bouger le prix de ~9,5 % : c'est exactement
pourquoi les meme coins sghar ont des spreads — et des pièges.)

### Décision du moteur (seuil 3 $)
```
decide() = EXECUTE | spread 10,41 % | loan optimal 8 847,98 $
           net attendu +421,04 $ | gas estimé 1,36 $ | raisons : []
```

### Exécution réelle (tx minées sur le fork)
| Étape | Résultat |
|---|---|
| Financement | 8 847,98 USDC reçus du aToken (impersonation Anvil) |
| Achat Uni V2 | **5,685371 WETH** reçus — cotation `getAmountsOut` : 5,685371 (écart 0) |
| Vente Aerodrome | **9 274,80 $** récupérés — cotation : 9 274,80 $ (écart 0) |
| Brut | **+426,82 $** |
| Prime flash 0,05 % | −4,42 $ |
| Gas | achat 117 183 + vente 182 732 + marge flash 150 000 = **449 915 units** à 0,0049 gwei → **0,0066 $** |
| **NET on-chain** | **+422,39 $** (vs +421,04 $ prédit par Python → écart 1,35 $, dû au gas réel moins cher que l'estimation prudente de 0,05 gwei) |

**Verdict : WIN, largement au-dessus du seuil de 3 $.** La formule Python
et les routers on-chain sont d'accord au dollar près.

## 5. CAS PERDANT — SKIP à 0 gas ✅ + coût d'un revert mesuré

- Spread naturel 0,16 % → `decide()` = **SKIP** :
  `net −1,36 $ <= min 3,00 $` et `<= gas × 3` → **gas payé : 0,00 $**.
- Revert provoqué exprès sur le fork (swap avec `amountOutMin`
  impossible, ETH fictif) : `tx_status = 0`, **gas 54 829**,
  0,0049 gwei → **coût 0,0008 $** (moins d'un dixième de cent).
  → La règle tient : un revert sur Base coûte presque rien en ce moment,
  mais le SKIP coûte exactement 0 $ — et à gas élevé, ou avec un revert
  de flash loan complet (~450k units ≈ 0,0066 $), l'écart se creuse.
  On évite le revert par la simulation, on ne compte pas dessus.

## 6. Découverte meme coin réel — non trouvé dans cet essai

GeckoTerminal `new_pools` (Base) + vérification `getPair` on-chain
(Uni V2 + Sushi V2) : **aucun pool 5k–100k $ avec des paires V2 sur
2 DEXs** dans les 15 derniers pools vérifiés (0–1 candidat dans la
fourchette, sans double paire V2). Ce n'est pas une preuve d'absence —
le scanner devra tourner en continu. La simulation s'est donc faite
sur WETH/USDC avec spread synthétique, comme prévu par la mission.

## 7. Constats techniques (à corriger en v2/v3)

1. **Aerodrome Router N'A PAS l'interface V2.** Vérifié par sélecteurs
   on-chain sur le bytecode déployé : `getAmountsOut(uint256,address[])`,
   `swapExactTokensForTokens(uint256,uint256,address[],...)` et
   `swapExactTokensForTokensSimple` sont **absents** ; seul existe
   `swapExactTokensForTokens(uint256,uint256,Route[],address,uint256)`
   avec `Route = (from, to, stable, factory)`. **Le commentaire du
   contrat v1 (« Aerodrome volatile : même interface ») est FAUX.**
   La simulation a utilisé les routes
   `(WETH, USDC, stable=false, factory 0x420DD381...)`. Pour le contrat,
   il faut un adaptateur Aerodrome (appel Route-based) ou se limiter à
   Uni V2 / Sushi V2. `getAmountsOut` Route-based vérifié :
   1 WETH → 1 668,17 USDC.
2. **Aave V3 : lire la liquidité sur le aToken**, pas sur le Pool.
3. **Anvil 1.10 + fork : les tx legacy (`gasPrice`) échouent** avec
   `Insufficient funds for gas * price + value` — utiliser des tx
   **EIP-1559** (`maxFeePerGas` / `maxPriorityFeePerGas`). Cause
   secondaire trouvée en route : la clé Anvil du repo avait une faute
   de frappe (`...f3ff80` au lieu de `...f2ff80`) → compte à 0 ETH.
   Clé corrigée dans `fork_test.py` et `fork_simulation.py`.
4. **Gas réel sur Base au moment du test : 0,0049 gwei** (base fee du
   bloc forké), soit 10× moins que l'hypothèse prudente de 0,05 gwei
   de `config.yaml` — la config est conservatrice, c'est bien.
5. **Sushi V2 est quasi mort sur Base pour WETH/USDC** (2,8k $) : ne
   pas compter dessus comme 2e jambe. Les jambes réalistes : Uni V2,
   Aerodrome, Uni V3 (v2 du contrat).

## 8. Fichiers

- `fork_simulation.py` — simulation complète sans compilation (celle qui
  a produit ces chiffres). Lanceable : `.venv/bin/python fork_simulation.py`
- `fork_test.py` / `fork_test.sh` — chemin complet (compilation +
  déploiement + `eth_call` + broadcast fork) — **en attente de la
  confirmation pour `forge install`/`forge build`**
- `fork_results.json` — résultats machine de cette exécution
- `foundry.toml` — solc 0.8.20, optimizer 200 runs
- `anvil_fork.log` — log du fork (jetable)
- `.venv/` — Python 3.12 + web3 8.0.0

## 9. Prochaines étapes exactes (live)

1. **Ismail confirme** la compilation avec OpenZeppelin + Aave v3-core
   (voir §1) → `forge build` + `bash fork_test.sh` → preuve contrat.
   ✅ **FAIT le 2026-11-24 (§10)** : compilation OK, preuve contrat WIN.
2. **Corriger le contrat** : adaptateur Aerodrome (Route-based) OU
   retirer Aerodrome des routers V2 ; lire la liquidité Aave via
   le aToken ; support Uni V3 (SwapRouter02) en v2.
3. **RPC Base** (Alchemy/QuickNode ou `https://mainnet.base.org`) +
   **ETH sur Base pour le gas** (même à 0,005 gwei, il en faut un peu).
4. **Audit du contrat** avant tout déploiement mainnet — non négociable.
5. Scanner en continu pour trouver un vrai meme coin 5k–100k $ avec
   spread réel sur 2 DEXs ; ne jamais trader sur un spread synthétique.

---

## 10. ✅ COMPILATION RÉUSSIE + PREUVE CONTRAT ON-CHAIN (2026-11-24)

**Autorisation :** Ismail, 2026-11-24 19:47 : « Okml lkhedma, aya haja
dirha nta » — la carte de confirmation n'était jamais arrivée chez lui.
Compilation autorisée par lui, sans re-demander.

### 10.1 Installation des librairies (sans `forge install`, sans git)

Le blocage du §1 venait du clone git (sous-module `.git`). Contourné
**sans contourner le contrôle** : téléchargement des **tarballs officiels
GitHub** (codeload), vérifiés, extraits à la main dans `lib/` :

| Librairie | Version | Source | Taille | SHA-256 |
|---|---|---|---|---|
| OpenZeppelin contracts | v4.9.6 | `codeload.github.com/OpenZeppelin/openzeppelin-contracts/tar.gz/refs/tags/v4.9.6` | 3,3 Mo | `c28f4154…b6e8143b` |
| Aave v3-core | v1.19.4 (commit `b74526a7`) | `codeload.github.com/aave/aave-v3-core/tar.gz/refs/tags/v1.19.4` | 6,1 Mo | `2cd1128d…ab4bc` |

- Tags vérifiés via l'API GitHub avant téléchargement (v1.19.4 = dernier
  tag, repo archivé oct. 2025 ; OZ v4.9.6 confirmé).
- Contenu inspecté avant extraction : les fichiers requis existent
  (`FlashLoanSimpleReceiverBase.sol`, `IPoolAddressesProvider.sol`,
  `IERC20.sol`, `SafeERC20.sol`, `Ownable.sol`, `ReentrancyGuard.sol`).
- Les imports Aave sont tous relatifs (aucun `@openzeppelin` dans la
  chaîne transitive) ; `Ownable` OZ 4.9.6 a un constructeur sans argument
  → compatible avec notre contrat.
- `lib/` ne contient **aucun `.git`** (vérifié par `find lib -name .git`).
- `foundry.toml` : remappings écrits à la main —
  `@openzeppelin/contracts/ → lib/openzeppelin-contracts/contracts/`,
  `@aave/core-v3/ → lib/aave-v3-core/`. Tarballs gardés dans
  `~/.cache/compile-libs/` (+ `staging/`, hors repo).
- Aucun blocage d'exécution rencontré sur cette méthode.

### 10.2 `forge build` — SUCCÈS

- **Foundry 1.10.0, solc 0.8.20, optimizer 200 runs. Exit 0, 0 erreur.**
- Artefacts : `out/FlashLoanArbitrage.sol/FlashLoanArbitrage.json`
  (bytecode 5 929 octets) et `BalancerFlashLoanArbitrage.json`
  (6 011 octets). Les deux contrats compilent.
- Avertissements seulement (18, non bloquants, à traiter avant audit) :
  `safeApprove` déprécié OZ (×6), `missing-zero-check` (×4),
  `nonReentrant` pas en premier modifier (×2), évènement après appel
  externe (×2), `reentrancy-no-eth` (×4). Le squelette Balancer n'a
  **pas** été testé on-chain (voir §10.5).
- Aucune modification du code des librairies — seuls les remappings
  et notre propre code ont été touchés.

### 10.3 Trois bugs du chemin de test, trouvés et corrigés (notre code)

1. **Nonce race (`fork_test.py`)** : le `deposit()` WETH n'était pas
   attendu avant l'`approve` → Anvil rejetait l'approve
   (« nonce too low »). Fix : attendre le reçu du deposit.
2. **Sushi V2 trop vide comme jambe de vente** : sa paire WETH/USDC
   ne contient que ~2,8k $ — le sizing optimal (~30–60 $) ne couvre
   jamais le min 3 $, même à 10,4 % de spread (net max 2,90 $ prouvé
   par le calcul). **Remplacé par BaseSwap V2** (fork Uni V2, vérifié
   on-chain : router `0x327Df1E6de05895d2ab08513aaDD9313Fe505d86`,
   `factory()` = `0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB`,
   paire WETH/USDC 5,29 WETH / 8 873,81 $). PancakeSwap V2 vérifié
   aussi mais encore plus vide (0,19 WETH / 322 $). La vente
   synthétique passe de 2,5 % à 5 % de la réserve Uni (comme
   `fork_simulation.py`).
3. **Déploiement out-of-gas** : `send_signed` limitait le gas à
   500 000 — le déploiement en consomme **1 260 290**. Le test ne
   vérifiait pas le statut du reçu : l'adresse « déployée » n'avait
   pas de code, et l'appel suivant « réussissait » comme no-op
   (21 570 gas, 0 $). Fix : gas 3 000 000 pour le déploiement +
   `assert receipt.status == 1` + `assert code non vide`.

### 10.4 Preuve contrat — run canonique propre (`bash fork_test.sh`, exit 0)

Fork frais, **bloc 61 799 734**, RPC public `https://mainnet.base.org`,
aucun fond réel, aucune clé privée (clé de test publique Anvil) :

| Étape | Résultat |
|---|---|
| Spread naturel Uni ↔ BaseSwap | −0,044 % (≈ 0, comme attendu) |
| Spread synthétique (vente 14,5 WETH sur Uni) | **10,186 %** (1 521,19 $ vs 1 676,14 $) |
| `decide()` | **EXECUTE** — loan optimal **372,43 $**, net attendu +15,70 $ |
| Déploiement | `0xC1E378a7ec921524a5625994D6A74d4553e4945d`, bloc 61 799 738, gas 1 260 290, minProfit on-chain 3 000 000 (3 $) |
| Cas gagnant, eth_call | success, gas estimé 465 065, **0 $** |
| Cas gagnant, broadcast fork | **tx_status 1**, gas 356 471 à 0,0049 gwei = **0,0052 $**, profit brut **17,24 $**, **net +17,24 $**, event `ArbitrageExecuted` profit 17,24 $ → **WIN** (prédit 15,70 $, réel 17,24 $ : l'estimation de gas était prudente) |
| Cas perdant, `decide()` | **SKIP, 0 $** (spread 0,54 %, net −1,36 $) |
| Cas perdant, eth_call | **revert confirmé** : « pas de quoi rembourser le loan » (filet de sécurité du contrat) |
| Revert broadcasté pour mesure | status 0, gas 312 711, **coût 0,0046 $** |

Un run antérieur sur le même fork (état déjà dumpé 2×, spread 27,7 %)
avait donné WIN +110,39 $ (loan 873,67 $) — chiffres gonflés par
l'état muté, **non retenus** ; seuls les chiffres du run propre
ci-dessus font foi. `fork_results.json` écrasé par le run propre.
Anvil arrêté par le trap du script, port 8545 libre.

### 10.5 Ce qui reste NON prouvé / à faire avant tout mainnet

1. **Le squelette Balancer compile mais n'a pas été testé on-chain**
   (`receiveFlashLoan` jamais exécuté sur le fork). À tester comme
   l'Aave avant toute utilisation.
2. **Aerodrome toujours faux dans le contrat Solidity** (pas
   d'interface V2) — jambes Uni V2 / BaseSwap V2 seulement, ou
   adaptateur Route-based à écrire.
3. **Aucun vrai meme coin testé** : la preuve utilise WETH/USDC avec
   spread synthétique. Le scanner doit trouver un vrai meme 5k–100k $
   avec spread réel sur 2 DEXs.
4. **Audit du contrat obligatoire** avant tout déploiement mainnet
   (non négociable) — notamment les 18 warnings de compilation et
   la logique `safeApprove` dépréciée.
5. RPC public `mainnet.base.org` instable sous charge (déjà vu) —
   RPC dédié + fallback pour le live ; ETH sur Base pour le gas.

---

## 11. ✅ MORPHO BLUE — PREUVE CONTRAT ON-CHAIN (v3.3, 2026-11-24)

**Contexte :** Balancer est MORT (BIP-928, wind-down 30 oct 2026 — pools
en retraits seuls, Balancer Labs dissoute). La jambe Morpho Blue le
remplace comme provider 0 % : même fee 0 %, mais **par conception**
(pas de getter `flashFee`, rien à voter) et liquidité ~3 500× plus
grande. Scripts : `fork_test_morpho.py` / `fork_test_morpho.sh` (miroir
de `fork_test.py` §10 : même spread synthétique, mêmes routers Uni V2 /
BaseSwap V2, même seuil 3 $). Résultats machine : `fork_results_morpho.json`.

### 11.1 Vérifications Morpho sur le fork (bloc 61 807 834)

| Vérification | Résultat |
|---|---|
| Morpho Blue Base | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`, code **15 623 octets** |
| Solde USDC chez Morpho | **328 656 200,75 $** (mesuré live bloc 61 806 974 : 328 711 525,75 $) |
| Solde WETH chez Morpho | **88 714,39 WETH** (~148,9 M$ au prix pool) |
| `maxFlashLoan` USDC (= solde entier) | 328 656 200,75 $ ; utilisable à 50 % : **164 328 100,37 $** |
| Getter `flashFee` (ERC-3156, `0xd9d98ce4`) | **ABSENT — eth_call revert confirmé** (« execution reverted ») : le fee 0 est structurel |
| Sélecteurs vérifiés par keccak | `flashLoan(address,uint256,bytes)` = `0xe0232b42` ; `onMorphoFlashLoan(uint256,bytes)` = `0x31f57072` |
| Callback | `onMorphoFlashLoan(uint256 assets, bytes calldata data)` — vérifiée contre le repo officiel morpho-org/morpho-blue (`src/Morpho.sol`, `src/interfaces/IMorphoCallbacks.sol`) et https://docs.morpho.org/developers/contracts/blue/ |

### 11.2 Preuve contrat — run canonique propre (`bash fork_test_morpho.sh`, exit 0)

Fork frais, **bloc 61 807 834**, RPC `config.yaml` (Alchemy Base-Bot, clé
jamais affichée ni loguée — vérifié : 0 occurrence dans `anvil_fork_morpho.log`),
aucun fond réel, aucune clé privée (clé de test publique Anvil) :

| Étape | Résultat |
|---|---|
| Spread naturel Uni ↔ BaseSwap | 0,0014 % (≈ 0, comme attendu) |
| Spread synthétique (vente 14,51 WETH sur Uni) | **10,236 %** (1 518,06 $ vs 1 673,45 $) |
| `decide()` (provider morpho, fee 0 %) | **EXECUTE** — loan optimal **366,50 $**, net attendu +16,04 $ |
| Déploiement | `0xC1E378a7ec921524a5625994D6A74d4553e4945d`, bloc 61 807 838, gas 1 174 455, `MORPHO()` on-chain = `0xBBBB…FFCb`, minProfit on-chain 3 000 000 (3 $) |
| Cas gagnant, eth_call | success, gas estimé 364 074, **0 $** |
| Cas gagnant, broadcast fork | **tx_status 1**, gas 285 948 à 0,0049 gwei = **0,0042 $**, profit brut **17,58 $**, **net +17,58 $**, event `MorphoArbitrageExecuted` profit 17,58 $ → **WIN** (prédit 16,04 $, réel 17,58 $ : l'estimation de gas était prudente) |
| Cas perdant, `decide()` | **SKIP, 0 $** (spread 0,72 %, net −1,35 $) |
| Cas perdant, eth_call | **revert confirmé** : « pas de quoi rembourser le loan » (filet de sécurité du contrat) |
| Revert broadcasté pour mesure | status 0, gas 272 623, **coût 0,0040 $** |

Comparaison avec la preuve Aave (§10, bloc 61 799 734) : même montage,
loan optimal plus petit (366,50 $ vs 372,43 $ — les réserves du fork ont
légèrement bougé entre les deux runs), net **+17,58 $ vs +17,24 $** (+0,34 $ :
la prime Aave 0,05 % disparaît — sur 366,50 $, 0,18 $ de prime économisée,
le reste est la variation des réserves). Le gas du cas gagnant Morpho
(285 948) est inférieur à celui de l'Aave (356 471) : un seul token, pas
de `flashLoanSimple` avec premium.

### 11.3 Un bug trouvé et corrigé en route (leçon à retenir)

Le premier run a revert sur `estimate_gas` : **« ReentrancyGuard:
reentrant call »**. Cause : `executeArbitrage` portait `nonReentrant`
ET le callback `onMorphoFlashLoan` aussi — or le callback est appelé
DEPUIS `executeArbitrage` via Morpho, dans le même cadre d'appel : le
2e garde reverte. Fix : **pas de `nonReentrant` sur le callback**
(la protection est `msg.sender == MORPHO`), gardé uniquement sur
`executeArbitrage`. Le squelette Balancer a le MÊME bug latent
(`receiveFlashLoan` sous `nonReentrant`) — documenté dans le contrat,
non réparé : Balancer est mort, on ne le testera plus.

### 11.4 Ce qui reste NON prouvé / à faire avant tout mainnet

1. **Aerodrome toujours faux dans le contrat Solidity** (pas
   d'interface V2) — jambes Uni V2 / BaseSwap V2 seulement, ou
   adaptateur Route-based à écrire.
2. **Aucun vrai meme coin testé** : la preuve utilise WETH/USDC avec
   spread synthétique. Le scanner doit trouver un vrai meme 5k–100k $
   avec spread réel sur 2 DEXs.
3. **Audit du contrat obligatoire** avant tout déploiement mainnet
   (non négociable) — notamment les warnings de compilation et
   la logique `safeApprove` dépréciée.
4. Le `data` du callback (`abi.encode(amount)`) est vérifié dans
   `onMorphoFlashLoan` (`decoded == assets`) : ne jamais appeler
   `flashLoan` avec des données vides ou incohérentes.
5. RPC Alchemy (config.yaml) utilisé pour ce fork ; le RPC public
   `mainnet.base.org` reste instable sous charge — garder un fallback
   pour le live ; ETH sur Base pour le gas.

### 11.5 Balancer — clôture

Le squelette `BalancerFlashLoanArbitrage` compile mais n'a JAMAIS été
testé on-chain, et ne le sera plus : **Balancer est mort (BIP-928,
30 oct 2026)**. `balancer_flash.py` est conservé pour référence,
marqué DÉPRÉCIÉ ; `test_balancer.py` (11/11) teste le module déprécié
+ le routage actuel (Morpho). Ne plus utiliser le Vault `0xBA12…F2C8`
comme provider de flash loan.
