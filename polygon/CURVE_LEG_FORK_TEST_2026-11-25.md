# Jambe Curve — test fork (v4.5) — 2026-11-25

## Verdict en une phrase

**La route est INEXÉCUTABLE.** La quote dit WIN sur le papier
(+4,32 $ à 5 000 $ au bloc du fork), mais l'exécution revert :
`exchange_underlying` du am3pool dépose l'USDT dans **Aave v2, dont la
réserve USDT est GELÉE** → revert `VL_RESERVE_FROZEN ('3')`.
Le contrat fonctionne, Morpho fonctionne, les deux jambes V3
fonctionnent — c'est la jambe Curve qui ne peut pas s'exécuter.
**L'edge papier est un piège : qui broadcasterait cette route paierait
~0,007–0,010 $ de gas par revert et gagnerait 0 $.**

**PAS PRÊT POUR MAINNET** — et ce n'est même pas (seulement) une
question d'audit : la route ne peut pas s'exécuter du tout tant
qu'Aave v2 est gelé. L'audit reste par ailleurs obligatoire avant
toute utilisation mainnet (aucun contrat de ce repo n'est audité).

---

## 1. La correction (découverte de ce test)

Le rapport `LOW_FEE_PROFIT_POLYGON.md` affirmait que le am3pool
« trade de l'USDC natif ». **Faux.** Vérifié on-chain
(bloc 97 921 969, puis re-vérifié au bloc du fork 97 922 458) :

| Appel | Résultat |
|---|---|
| `underlying_coins(1)` du am3pool `0x445FE580…` | **USDC.e `0x2791Bca1…`** (pas USDC natif) |
| `underlying_coins(0)` / `(2)` | DAI / USDT |
| `fee()` | 0,001 % ; A = 2000 |

Conséquence : `exchange_underlying(2, 1)` rend de l'**USDC.e**, et une
**4e jambe (USDC.e → USDC natif, V3 0,01 %) est obligatoire** avant de
rembourser Morpho. La route corrigée est donc 4 swaps, pas 3.

Coût de la correction (bloc 97 922 005) : à 5 000 $, la jambe 4 coûte
**0,51 $** (leg2 5 005,62 → leg3 5 005,11). Net annoncé avant : 5,63 $ ;
**net corrigé : 5,08 $**. La route reste WIN sur le papier — mais
inexécutable (voir §3).

## 2. Re-quote live (lecture seule, même bloc, 3 jambes + Morpho)

RPC public `https://polygon.drpc.org`. Route corrigée 4 swaps,
quotes au même bloc pour les 4 jambes.

### Bloc 97 922 005 (re-quote de validation)

| Taille | leg0 USDC→USDC.e | leg1 USDC.e→USDT | leg2 Curve USDT→USDC.e | leg3 USDC.e→USDC | Brut | Gas budgété (2×) | **Net** |
|---|---|---|---|---|---|---|---|
| 1 000 $ | 999,89 | 1 001,03 | 1 001,14 | 1 001,04 | +1,04 | 0,032 | **+1,01** |
| 5 000 $ | 4 999,45 | 5 005,12 | 5 005,62 | 5 005,11 | +5,11 | 0,032 | **+5,08** |
| 20 000 $ | 19 997,49 | 20 019,82 | 20 021,57 | 20 019,24 | +19,24 | 0,032 | **+19,20** |

Gas budgété : 750 000 unités × 280 gwei × 0,0758 $ × 2 (trade + revert)
= 0,0318 $.

### Bloc 97 922 458 (bloc du fork — chiffres utilisés par le test)

| Taille | leg0 | leg1 | leg2 Curve | leg3 | Brut | Gas budgété | **Net** |
|---|---|---|---|---|---|---|---|
| 1 000 $ | 999,89 | 1 000,88 | 1 000,98 | 1 000,88 | +0,88 | 0,026 | **+0,86** |
| 5 000 $ | 4 999,44 | 5 004,34 | 5 004,84 | 5 004,34 | +4,34 | 0,026 | **+4,32** |
| 20 000 $ | 19 997,44 | 20 016,81 | 20 018,56 | 20 016,27 | +16,27 | 0,026 | **+16,24** |

Gas budgété ici : 0,0261 $ (prix du gas du fork au moment de la quote,
~230 gwei).

**Morpho Blue Polygon** `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` :
solde USDC natif **75 540,27 $** (inchangé sur toutes les vérifications
de la journée) → prêt max à la règle des 50 % : **37 770,13 $**.
Le prêt de 20 000 $ est donc couvert ; celui de 100 000 $ ne l'est pas
(voir garde §5).

### La fenêtre se referme lentement

Net à 20 000 $ : +19,20 $ (bloc 97 922 005) → +16,24 $ (bloc 97 922 458,
~17 min plus tard). L'edge papier survit mais **décroît** (l'USDT
remonte vers 1 $ et/ou le prix Curve dérive). Il mourra si l'USDT
re-peg ou si quelqu'un trade le pool Curve.

## 3. Pourquoi ça revert — la preuve

### 3.1 Les flags gelés, lus on-chain

Aave v2 LendingPool `0x8dFf5E27EA6b7AC08EbFdf9eB090F32ee9a30fcf`,
`getReserveData` (bit 57 de la configuration = `isFrozen`),
bloc 97 922 458 :

| Réserve | active | **frozen** | borrowEnabled | paused |
|---|---|---|---|---|
| DAI | 1 | **1** | 0 | 0 |
| USDC.e | 1 | **1** | 0 | 0 |
| USDT | 1 | **1** | 0 | 0 |
| USDC natif | 0 | 0 | 0 | 0 (pas une réserve) |

**Les trois underlyings du am3pool sont gelés.** Aave v2 Polygon est
dépréciée par la gouvernance au profit de v3 : les réserves sont
gelées (dépôts interdits, emprunts désactivés). `exchange_underlying`
doit déposer l'underlying dans Aave pour minter l'amToken — tout
deposit revert.

### 3.2 La trace de la transaction qui revert

Exécution 5 000 $ sur le fork — tx
`bca0bf0612000e5004a6b7d62f97532cbdf3e43fc7d0fe874e77d412159b8fc3`
(bloc 97 922 460, status 0). Arbre d'appels (`cast trace` /
`debug_traceTransaction` avec callTracer) :

```
executeArbitrage → MORPHO.flashLoan            ✓ USDC transféré
  → onMorphoFlashLoan
    → V3 USDC→USDC.e swap                     ✓ callback payé
    → V3 USDC.e→USDT swap                     ✓ callback payé
    → USDT.approve(Curve)                     ✓
    → CURVE.exchange_underlying(2,1,…)        ✗ REVERT
        → USDT.transferFrom                   ✓ (USDT bien transféré au pool)
        → AAVE_LendingPool.deposit(USDT,…)    ✗ REVERT
            → ValidationLogic                 ✗ Error('3')
```

La raison du revert le plus profond, décodée de la trace :
**`'3'`** = `VL_RESERVE_FROZEN` dans `Errors.sol` officiel d'Aave v2
(« Action cannot be performed because the reserve is frozen »,
vérifié sur le code source GitHub `aave/protocol-v2`, 2026-11-25).

La raison `'3'` ne peut venir que du deposit Aave dans la jambe
Curve — donc **Morpho + les deux jambes V3 ont RÉUSSI avant**.
Le contrat et sa mécanique sont sains ; c'est l'environnement
(Aave v2 gelé) qui bloque.

Une première trace identique avait été obtenue sur un fork antérieur
(tx `276e418b45ec48d4b69a4e708c57652151b6dd588354317b056e9a93b61d8ebd`,
bloc 97 922 191, même gas 489 126) — le résultat est reproductible.

### 3.3 Il n'y a pas d'autre pool Curve sur Polygon

API Curve (`api.curve.fi/api/getPools/polygon`, 2026-11-25) : **2 pools
seulement** — amWBTC/renBTC (503 k$) et amDAI/amUSDC/amUSDT (2,26 M$).
Aucun pool Curve non-aave, aucun pool en USDC natif. Il n'existe donc
**aucune jambe Curve de rechange** sur Polygon.

Autres voies envisagées et rejetées :
- `exchange` (amToken → amToken) : il faudrait détenir de l'amUSDT,
  qui ne se minte qu'en déposant de l'USDT dans Aave v2 gelé.
- Sens inverse (acheter l'USDT sur Curve, vendre sur Uni) : **perd
  de l'argent** à toutes les tailles (−1,57 $ à 1 000 $).

## 4. Contrat

**Nouveau fichier** `polygon/contracts/CurveFlashArbPolygon.sol`
(6 560 bytes de bytecode, compilé `forge build` exit 0 — seuls des
avertissements de lint sur les casts `int256`, même pattern que le
contrat existant). Aucun contrat ni config existant modifié.

Route : Morpho flash USDC → V3 USDC→USDC.e (fee 100) → V3 USDC.e→USDT
(fee 100) → Curve `exchange_underlying(2, 1, amount, minDy)` →
V3 USDC.e→USDC (fee 100) → remboursement Morpho.

| Fonction | Rôle |
|---|---|
| `executeArbitrage(uint256 amount, uint256 minDy)` (onlyOwner, nonReentrant) | Lance le flash loan Morpho avec `(amount, minDy)` encodés |
| `onMorphoFlashLoan(...)` | Les 4 jambes + vérification `profit >= minProfit` (0,01 $) + remboursement |
| `_swapV3ExactIn(pool, tokenIn, tokenOut, amountIn, zeroForOne)` | Swap direct `pool.swap` + callback (le SwapRouter02 revert sur Polygon — pattern déjà prouvé du contrat existant) |
| `_v3Callback(...)` | Paie le token d'entrée au pool appelant (vérifie `msg.sender` = pool attendu) |
| `setMinProfit(uint256)` | Change le plancher on-chain |
| `getRouteQuote()` | Vue : expose les adresses et le minProfit (pas de quote — le quoter est off-chain) |
| `CurveFlashArbExecuted(assets, profit, gasleft)` | Événement de succès (jamais émis à ce jour : aucun trade n'a abouti) |

**Helpers** `polygon/curve_route.py` (ajouts à la fin du fichier,
le quoter existant est inchangé) :
- `check_aave_frozen(w3)` — lit les flags `isFrozen` des 3 réserves
  Aave v2 (lecture seule).
- `route_guard_decision(net_usd, aave_frozen, min_profit_usd)` — décision
  off-chain pure : `EXECUTE` ssi net > 0 **ET** Aave non gelé.
  Un net positif ne suffit pas : c'est ce garde qui empêche de brûler
  du gas sur une route inexécutable.
- `AAVE_VL_RESERVE_FROZEN = "3"` (constante documentée).

## 5. Résultats du fork

Fork Anvil Polygon, bloc **97 922 458**, RPC `polygon.drpc.org`,
chaîne 137. Déploiement bloc 97 922 459, contrat
`0x06D6EdD1Cc26279E8f0246e0b9d524AB5e88767D`, gas de déploiement
**1 286 751** unités. `MORPHO()` et `minProfit()` (= 10 000 = 0,01 $)
vérifiés on-chain après déploiement.

| Test | Résultat mesuré |
|---|---|
| Exécution 5 000 $ (eth_call) | **Revert** — `('execution reverted', '0x')` (web3.py ne remonte pas la raison ; elle est dans la trace) |
| Exécution 5 000 $ (broadcast fork) | **status 0**, tx `bca0bf06…59b8fc3`, bloc 97 922 460, **gas 489 126 unités**, prix effectif 200,59 gwei → **coût du revert 0,0074 $** (à 280 gwei : 0,0104 $), raison profonde **`'3'` VL_RESERVE_FROZEN** |
| Garde loan trop gros (100 000 $) | **status 0**, tx `f9c61f6f…d2ee63`, **gas 53 696**, coût **0,0007 $**, raison profonde **`'transfer reverted'`** — revert chez Morpho (transfert > solde), avant tout swap |
| Solde du contrat après revert | **0 USDC** — le revert est atomique, Morpho n'a rien perdu |
| Net mesuré sur un trade complet | **0 $ — aucun trade n'a abouti.** Le gas d'un trade réussi reste **INCONNU** (l'estimation 750 000 unités n'est pas mesurée) |

**Gas mesuré vs estimé :** l'estimation de 650 000 unités (rapport
initial) puis 750 000 unités (route corrigée 4 swaps) concerne un
trade **complet** — elle n'a jamais pu être mesurée. Le seul gas
mesuré est celui du **revert : 489 126 unités** (reproductible à
l'unité sur deux forks distincts). Un trade complet coûterait plus
cher que le revert (les 4 jambes + le remboursement s'ajoutent).

### Comportement des gardes

- **Garde off-chain** (`route_guard_decision`) : **SKIP /
  `aave_v2_frozen`** aux trois tailles, malgré un net papier positif
  (+0,86 / +4,32 / +16,24 $). C'est le comportement voulu : ne jamais
  broadcaster une route dont la jambe Curve est condamnée à revert.
- **Garde loan trop gros** : revert chez Morpho avant tout swap,
  53 696 unités (0,0007 $) — le garde de taille fonctionne.
- **minProfit on-chain (0,01 $)** : **inatteignable en bout de chaîne
  tant que la jambe Curve est bloquée** (le `require` est après la
  jambe 3). Il est couvert par les tests unitaires (logique pure),
  pas par le fork. Si Aave v2 était un jour dégelé, il faudrait
  re-tester ce chemin en fork avant toute utilisation.
- **minDy** : calculé comme quote × 0,9995 (marge 0,05 %), testé en
  unitaire ; le chemin on-chain est également inatteignable tant que
  la jambe Curve revert avant le contrôle de `minDy` (le deposit
  Aave a lieu avant la vérification du `min_dy` dans le pool Curve).

## 6. Tests

- **Nouveau** `polygon/test_curve_leg.py` — **12/12 verts**
  (`../.venv/bin/python -m unittest polygon.test_curve_leg -v`) :
  net de la route corrigée sur les quotes enregistrées (bloc
  97 922 005), minDy, garde off-chain (5 cas dont
  « SKIP même avec net positif si Aave gelé »), la correction
  elle-même (l'ancienne route 3 swaps surévaluait le brut de
  exactement leg2 − leg3 = 0,51 $ à 5 000 $), mapping `'3'` =
  VL_RESERVE_FROZEN.
- **Régression** (suites existantes, inchangées) :
  `test_low_fee` 20/20, `test_polygon` 25/25, `test_pro_scan` 23/23,
  `test_realtime_listener` 19/19, `test_revert_protection` 22/22,
  `test_curve_leg` 12/12 → **121/121 verts**.
- **Script fork** `polygon/fork_test_curve.py` + `fork_test_curve.sh`
  (exit 0). Résultats détaillés : `polygon/curve_fork_results.json`
  (17 étapes). **Helper de debug** `polygon/debug_curve.py` (déploie
  + broadcast + imprime le hash de tx pour `cast trace`) — conservé
  pour reproduire la trace.

## 7. La fenêtre est-elle encore ouverte ?

**Sur le papier : oui, mais elle se referme.** Re-quote après les
tests (bloc 97 922 461) : net **+0,86 / +4,32 / +16,24 $**
(1k / 5k / 20k) — toujours WIN, mais le net à 20 000 $ a perdu
~15 % en ~17 minutes. L'edge existe tant que l'USDT reste sous son
peg (~0,9988 $) ET que personne ne trade le am3pool (volume 0 —
c'est précisément ce qui le rend stale). **En exécution : non,
elle n'a jamais été ouverte** — la jambe Curve ne peut pas
s'exécuter, quelle que soit la taille du net papier.

## 8. Comment surveiller (lecture seule, 0 $)

À vérifier avant chaque décision, et en continu si la route doit
être reprise un jour :

1. **Prix de l'USDT** (source de l'edge) : si l'USDT revient à
   1,0000 $, le spread disparaît. Surveiller CoinGecko / le prix
   Uni V3 USDC.e/USDT.
2. **Prix du am3pool** : `get_dy_underlying(2, 1, montant)` —
   si quelqu'un trade le pool, il se reprice et l'edge meurt.
   Surveiller aussi le volume du pool (tout trade > 0 le tue).
3. **Solde Morpho USDC** : `balanceOf(Morpho)` — doit rester
   > 2 × la taille du prêt visé (règle des 50 %).
4. **Flags Aave v2** — **la condition de déblocage** :
   `check_aave_frozen(w3)` dans `curve_route.py`. Si un jour
   `any_frozen` passe à `False`, **re-tester en fork** avant toute
   chose (et l'audit reste obligatoire). En pratique, Aave v2 ne
   sera pas dégelée : la gouvernance l'a dépréciée au profit de v3.
5. **Le garde off-chain** : `route_guard_decision(net, frozen)` doit
   dire `EXECUTE` (net > 0 **et** Aave non gelé) avant tout broadcast.
   Aujourd'hui il dit `SKIP` — ne pas broadcaster.

Commandes (lecture seule) :

```bash
cd ~/workspace/crypto-base-flashloan-bot/polygon
../.venv/bin/python -m curve_route        # re-quote live de la route 4 swaps
../.venv/bin/python -c "from curve_route import check_aave_frozen; \
  from web3 import Web3; print(check_aave_frozen(Web3(Web3.HTTPProvider('https://polygon.drpc.org'))))"
```

Reproduire le fork test complet (0 $, fork local uniquement) :

```bash
bash fork_test_curve.sh
```

## 9. Fichiers

| Fichier | Statut |
|---|---|
| `polygon/contracts/CurveFlashArbPolygon.sol` | **Nouveau** — contrat de la route 4 swaps |
| `polygon/curve_route.py` | Ajouts : `check_aave_frozen`, `route_guard_decision`, `AAVE_VL_RESERVE_FROZEN` |
| `polygon/fork_test_curve.py` | **Nouveau** — test fork (re-quote, Aave gelé, déploiement, exécution, gardes, re-quote) |
| `polygon/fork_test_curve.sh` | **Nouveau** — lance Anvil + forge build + test (corrige aussi le `pkill -f` qui se tuait lui-même) |
| `polygon/test_curve_leg.py` | **Nouveau** — 12 tests unitaires, 12/12 |
| `polygon/debug_curve.py` | **Nouveau** — helper de debug (déploie + broadcast + hash pour `cast trace`) |
| `polygon/curve_fork_results.json` | Résultats détaillés du run (17 étapes) |
| `polygon/CURVE_LEG_FORK_TEST_2026-11-25.md` | Ce rapport |

**Aucun commit GitHub** (le parent s'en charge). Aucun fichier
existant modifié à l'exception de l'ajout de fonctions en fin de
`curve_route.py`. Aucun fond réel, aucune clé privée d'utilisateur,
aucun broadcast mainnet — tout s'est passé sur des forks Anvil
jetables avec la clé de test publique d'Anvil.

## 10. Conclusion

- La route 4 swaps corrigée est **réelle sur le papier** (net
  +0,86 / +4,32 / +16,24 $ au bloc du fork) mais **inexécutable** :
  Aave v2 est gelée, la jambe Curve revert avec `VL_RESERVE_FROZEN`.
- Le contrat est sain (Morpho + V3 prouvés par la trace), les gardes
  fonctionnent (off-chain SKIP, loan trop gros revert tôt), le revert
  coûte **489 126 unités ≈ 0,007–0,010 $**.
- **Décision à prendre** : abandonner la route Curve (le dégel
  d'Aave v2 n'arrivera pas), OU la garder sous surveillance au cas
  où — en sachant que même dégelée, il faudrait un audit + un
  re-test fork complet avant tout mainnet.
