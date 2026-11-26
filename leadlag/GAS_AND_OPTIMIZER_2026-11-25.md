# Gas + optimiseur de taille — 2026-11-25

> **SIMULATION — tous les chiffres ci-dessous sont des simulations (fork Anvil local,
> quotes QuoterV2, estimations de gas). Aucun trade réel, aucun profit réalisé,
> aucun fonds engagé, aucun broadcast mainnet.**

## 1. Gas du contrat `AtomicArbitrage.sol`

Mesuré sur le fork historique du bloc **61 989 637** (route Pancake → Uni,
USDC/WETH, 300 USDC, `scripts/verify_historical.py`, Anvil local, RPC Alchemy
lecture seule). Le gas de référence de la validation historique était 421 497.

| Mesure | Avant (solc 0.8.20, stockage + SafeERC20) | Après (solc 0.8.28, transient, sans SafeERC20) |
|---|---|---|
| `local_gas_used` (receipt, trade à froid) | **421 497** | **287 318** (−134 179, −31,8 %) |
| `local_gas_used` (trade à chaud, slots USDC+WETH pré-chauffés 1 wei) | — | **270 218** (−17 100 de plus) |
| `gas_units` (estimation `eth_estimateGas`) | 627 750 | 423 347 |
| Net simulé @ 300 USDC (même fork, même bloc) | +0,0262 $ | +0,0304 $ |

### Ce qui a changé
- **solc 0.8.20 → 0.8.28** (`package.json` épinglé `"solc": "0.8.28"`).
  Le transient storage (EIP-1153) exige ≥ 0.8.24 ; Cancun est actif sur Base
  et supporté par le fork Anvil. Le pragma du contrat reste `^0.8.20`
  (0.8.28 le satisfait) ; `scripts/compile_contracts.cjs` n'a pas eu besoin
  de modification de code.
- **Les 7 variables de stockage deviennent transient** (`pending`, `activePool`,
  `activeToken`, `remainingInput`, `activeKind`, `running`, `inCallback`)
  + une transient `activeInputIsToken0` ajoutée pour que `_pay` n'appelle plus
  `token0()` (2 appels externes économisés).
- **SafeERC20 retiré** là où les tokens sont connus (USDC, WETH, cbBTC) :
  `transfer`/`approve` directs avec vérification explicite du bool de retour
  (`_transfer`/`_approve`).
- **Tous les checks de sécurité sont inchangés** : owner-only, deadline /
  lastBlock, validation des routes, auth du callback, rejet des partial-fill,
  budget d'input, minProfit, remboursement du loan, check `allowance == 0`.
  Les revert strings sont identiques.

### Cible < 250 000 : NON ATTEINTE (honnêtement)
Meilleur mesuré : **270 218** (à chaud) — il manque 20 218 gas. Analyse par
trace (callTracer, fork historique) : les deux swaps externes dominent —
Pancake buy 113 217 + Uni sell 81 316 = **194 533 (~69 %)**, du code AMM
externe, non modifiable. Transfert du loan Morpho 32 063, approve exact
25 341, remboursement transferFrom ~6 428, logique propre ~29–47k.
Plancher estimé : ~232k coûts externes fixes + ~46k logique − 17,1k slot
chaud USDC ≈ **261k**. La cible < 250k n'est **pas atteignable sur cette
route** (Pancake → Uni @ 300 USDC) en gardant tous les checks de sécurité.

### Idées essayées et rejetées (mesurées, pas supposées)
- **Approval permanente (standing approval)** : `approveLender(token)` en
  `type(uint256).max` une fois, au lieu d'un approve exact par trade.
  Résultat : 288 299 gas (runs 200) / 288 020 (runs 10 000) — **pire** de
  +981 / +702 vs l'approve exact. Le SSTORE d'approve économisé (20 000)
  est annulé par la perte du refund de clear (4 800) + une lecture
  d'allowance. **Rejeté et entièrement reverté** (contrat, mocks, tests,
  scripts). Ne pas re-proposer sans nouvelle preuve.
- **Optimizer runs 200 → 10 000** : −279 gas seulement. Reverté à 200.
- **Slots USDC/WETH pré-chauffés (`--warm`, `seed_dust`)** : dust USDC seul
  −17 100 ; dust WETH seul **−0 (voir point ouvert)** ; les deux −17 100.
  Le `--warm` est un outil de mesure (steady-state), pas un mode de
  production : il simule un exécuteur déjà utilisé.

## 2. Optimiseur de taille (`arb/runtime.py`, `bot.py`)

### Méthode
Le net vs taille est concave, mais une recherche séquentielle (ternary /
golden-section) exigerait ~80 allers-retours RPC dépendants par route
(minutes + risque 429). Implémenté : **bracketing grossier → fin par
niveaux, en batches** : niveau 1 = 12 points en grille log sur
[10, min(50 % du solde Morpho, cap)] ; niveaux 2–3 = 9 points linéaires
chacun, zoomés sur le meilleur point (largeurs ×2,675 puis ×1,25).
**6 batches RPC par route, 30 tailles évaluées max.** Le gas est
indépendant de la taille au premier ordre, donc l'optimiseur maximise le
**gross chaîné** (sortie exacte du buy → entrée exacte du sell) ; seule la
meilleure taille passe la simulation fork Anvil complète, qui calcule le
vrai net. Le check « amount × 2 > balance » est conservé comme borne
supérieure de la range. `--sizes` reste disponible comme override manuel ;
`--size-cap` (défaut 500 000 USDC) borne l'optimiseur. Le JSON de scan
porte `size_mode`, `optimal_size_usdc`, `optimal_gross_usdc`,
`optimizer_evaluated`, `optimizer_unquotable_routes`.

### Tests (MockCLPool mode CPAMM)
- `MockCLPool` kind=2 ajouté : courbe constant-product avec réserves
  explicites (`output = input × reserveOut / (reserveIn + input)`), concave
  en taille. Test on-chain `test_mock_cpamm_curve_and_trade` : un trade de
  300 (synthétique) via des pools à 2 000 / 2 010 retourne **exactement**
  la prédiction CPAMM et le lender est remboursé.
- `tests/test_runtime.py` : `FakeCLQuoter` CPAMM avec optimum connu par
  grille fine (4 001 points). L'optimiseur trouve l'optimum à ≤ 10 % en
  taille et ≤ 5 % en gross, avec ≤ 30 tailles et ≤ 6 batches ; il respecte
  le cap de solde (optimum sur la borne quand il lie), le `--size-cap`,
  retourne `None` quand la range est vide, et choisit la plus petite taille
  (10) quand il n'y a pas d'edge (gross négatif partout).

### Résultat live — bloc 61 989 637 (scan optimiseur, `bot.py scan`)
Fichier : `leadlag/optimizer_scan_61989637.json` (22 pools, 280 routes,
266 sous le breakeven spot, 14 routes optimisées, 0 non-quotable).

| Route (meilleure) | Taille | Gross simulé | Net simulé (fork-vérifié) |
|---|---|---|---|
| Pancake 100 → Uni 100, USDC/WETH (ancien : 300 USDC, +0,0260 $) | **335,58 USDC** | **+0,039645 $** | **+0,030875 $** |
| Même opportunité, sens inverse (WETH/USDC, Uni 100 → Pancake 100) | 335,58 USDC | +0,039710 $ | +0,031189 $ |

- **L'optimum (335,58 $) est hors de l'ancienne grille** (entre 300 et
  1 000) : la grille fixe avait choisi 300 comme meilleur point.
- Décomposition du gain net +0,0049 $ vs l'ancien résultat : **+0,00046 $
  de la taille** (gross 0,039188 → 0,039645, +1,2 %) et **~+0,0044 $ de la
  baisse de gas** (coûts totaux ~0,0132 $ → 0,0088 $).
- 2 routes `HISTORICAL_VERIFIED` (les deux sens de la même opportunité) ;
  2 autres routes vérifiées mais sous le seuil min-net 0,01 $ (nets
  +0,00023 $ et +0,00049 $, fork-vérifiés) ; toutes les routes cbBTC en
  `CHAINED_QUOTE_LOSS` avec l'optimum à la taille minimale (10 USDC).
- Le net du scan (+0,0309 $) utilise le modèle de coût prudent du bot
  (gas estimé 423 347 × marge 1,25) ; le receipt réel (287 318) donnerait
  un net légèrement supérieur. Le chiffre rapporté est le prudent.

## 3. Tests

- `tests/` (GPT) : **29 passed** (23 d'origine + 5 optimiseur + 1 CPAMM).
- Suite racine `-k 'not live'` : **307 passed, 12 deselected** (inchangé).
- `npm run build -- --test` (solc 0.8.28) : compilation OK, artefacts `out/`
  reconstruits (gitignored).

## 4. Points ouverts

1. **Cible gas < 250k manquée** (270 218 à chaud). Voir §1 : le plancher est
   dominé par les swaps AMM externes. Toute baisse supplémentaire exigerait
   de retirer des checks de sécurité (refusé) ou de changer de route.
2. **Anomalie dust WETH : 0 gas économisé.** Le seed est confirmé : après
   `seed_dust(weth)`, le solde WETH de l'exécuteur vaut bien 1 wei avant le
   trade (sonde `/tmp/weth_dust_probe.py`), et le receipt de seed est
   `status == 1`. Le modèle SSTORE simple prédit −12 300 gas. Le chiffre
   mesuré (287 318, identique au froid) contredit le modèle ; une
   investigation par prestate-tracer (diff des slots) est nécessaire avant
   toute explication. Ne pas supposer que le slot WETH est « déjà chaud »
   en production.
3. **Le net +0,0309 $ est une simulation historique**, pas un profit : il
   date du bloc 61 989 637, expiré depuis longtemps (blocs Base 200 ms,
   budget de fraîcheur 2 blocs = 0,4 s). Le marché live reste efficient
   à ±2 bp (test de profit du 25 nov : 0 net > 0 $ sur 1 388 quotes).
4. **Sous-modules `lib/` sales dans le working tree** (`uniswap-lib`,
   `v2-core` : pointeurs modifiés ; `v2-periphery` : fichier modifié) —
   état pré-existant, non touché par ce travail, à ne pas commiter.
5. **Rien n'est commité** (consigne du parent). Fichiers modifiés :
   `contracts/AtomicArbitrage.sol`, `arb/runtime.py`, `bot.py`,
   `package.json`, `package-lock.json`, `scripts/verify_historical.py`,
   `tests/test_runtime.py`, `tests/test_atomic.py`,
   `tests/contracts/AtomicMocks.sol` ; nouveau : ce rapport +
   `leadlag/optimizer_scan_61989637.json`.
