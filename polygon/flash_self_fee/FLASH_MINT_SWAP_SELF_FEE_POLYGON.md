# Flash mint / flash swap : « payer les frais à moi-même » — vérification + simulation fork (Polygon)

**Date :** 2026-11-25 · **Chaîne :** Polygon (137) · **Fork Anvil, bloc 97 921 663**
**Fichiers :** `polygon/flash_self_fee/` — `simulate_self_fee.py`, `run_sim.sh`,
`contracts/SelfFeeArb.sol`, `contracts/TestToken.sol`, `simulation_results.json`,
`test_flash_self_fee.py` (16/16 verts), `phase1_probe.py`.
**Règle :** fork uniquement. Aucun broadcast mainnet, aucun wallet réel, aucune clé.

## Verdict (en une phrase)

**Le mécanisme est réel, mais il ne crée pas de profit net : les frais reviennent
bien au LP, mais le profit de spread d'un pool qu'on possède s'annule
exactement (transfert interne) — seul le profit venant du pool qu'on ne possède
PAS est réel. Posséder les deux pools ≈ −gas ; posséder un seul ≈ la moitié du
profit d'arbitrage classique.**

| Cas | Richesse du propriétaire (vs HOLD) | Mesuré |
|---|---|---|
| (i) HOLD (LP de A seul, pas de trade) | référence | 102 469,12 $ |
| (ii) SELF-ARB, possède A **et** B | **−0,0048 $ = −gas exactement** | 204 946,84 $ vs HOLD-both 204 946,84 $ |
| (iii) EXTERNAL-ARB (un étranger arbe, LP de A seul) | **−26,20 $** (l'étranger prend 53,61 $) | 102 442,92 $ |
| (iv) **OWN-ONE-PAIR** (LP de A seul, le propriétaire arbe) | **+27,41 $** ≈ moitié du profit classique (26,81 $) | 102 496,52 $ |

Et : (iv) − (iii) = **+53,61 $ = exactement le profit de l'arbitragiste** —
s'arbitrer soi-même vaut mieux que laisser un étranger le faire, du montant
exact de son profit.

## Phase 1 — Vérification des trois mécanismes (on-chain + code, jamais supposé)

| Mécanisme | Vérification | Résultat |
|---|---|---|
| **(a) WETH flash mint (style WETH10)** | `0xbc5cef436eadacadfa8dafb63088f09f21dea7e9` (adresse WETH10 Ethereum) | **0 octet de code sur Polygon — pas déployé.** Pas de flash mint WETH sur Polygon. |
| WMATIC `0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270` | 3 000 octets. Les sélecteurs `flashFee` / `maxFlashLoan` / `flashLoan` sont **absents du bytecode** ; `deposit()` présent → c'est un WETH9 (dépôt/retrait/transfert uniquement). | **Pas de flash mint.** ⚠️ Correction importante : le `flashFee(self,1000) → 0` observé en phase 1 est le retour vide du fallback WETH9, **pas** un vrai fee = 0. Ne jamais le lire comme un fee 0. |
| WETH bridgé `0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619` | 12 443 octets. Appels `flashFee` / `maxFlashLoan` **revert**. | Pas de flash mint. |
| WETH10 sur Ethereum (référence) | `flashFee` retourne 0 par construction (ERC-3156), `maxFlashLoan` = type(uint112).max − flashMinted. | Le mint est gratuit **par design** — il n'y a donc rien à « récupérer » sur le mint lui-même. |
| **Emprunt 0-fee sur Polygon** | Morpho Blue `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` (déjà vérifié) | 15 582 octets, getter `flashFee` absent = 0 structurel. Soldes bloc 97 901 631 : USDC 112 261 $ / USDT 122 030 $ / WMATIC 1 000 246. C'est un **prêt**, pas un mint. |
| **(b) V2 flash swap** (QuickSwap / Sushi) | Code canonique `lib/v2-core/contracts/UniswapV2Pair.sol` lignes 159–182 : le K-check utilise `balance*1000 − amountIn*3`, donc 0,3 % reste dans les réserves → **accrue aux LP pro-rata**. Vérifié aussi sur fork : K croît de +0,0067 % par trade (voir §3). | **0,3 % → réserves → LP. Confirmé.** QuickSwap V2 factory 13 859 octets (= taille canonique), router 21 943 octets ; Sushi V2 factory 11 264 octets, router 17 762 octets ; paire live QuickSwap WMATIC/USDC `0x6D9e8dbB2779853db00418D4DcF96F3987CFC9D2` (11 293 octets, réserves 8 104,69 WMATIC / 607,73 USDC au bloc 97 921 099). |
| **(c) V3 flash** | Docs (uniswapv3book, protocols.davidgarciab.com, zealynx) : fee = le tier du pool (`fee0 = mulDivRoundingUp(amount0, fee, 1e6)` — tier 3000 = 0,30 %), le pool exige `balanceBefore + fee <= balanceAfter` (`F0`/`F1`) ; une fraction peut être prélevée si `feeProtocol` est défini ; le reste augmente le fee growth global payé aux LP **in-range**. | **Fee = tier du pool (0,01 % / 0,05 % / 0,30 % / 1 %) → LP in-range. Confirmé par docs.** Non simulé sur fork (la simulation utilise V2, où les deux jambes sont mesurables exactement). |

**Conséquence pour l'idée d'Ismail :** le seul endroit où des frais existent et
peuvent « revenir à soi » est le **swap fee** (V2 0,3 % ou tier V3). Le flash mint
lui-même coûte 0 — il n'y a rien à récupérer dessus. La simulation teste donc
le flash swap V2, qui est le mécanisme où la récupération de frais est réelle.

## Phase 2 — Simulation fork : montage

- **Fork :** Anvil, `https://polygon.drpc.org`, bloc **97 921 663**, gas 279 gwei,
  MATIC 0,0758 $. Port 8546 (localhost uniquement).
- **Paires :** deux paires V2 fraîches, code canonique Uniswap V2
  (factory/router des artefacts `sepolia/artifacts-v2/`, déjà vérifiés
  identiques au mainnet), même paire de tokens TKA/TKB (18 décimales,
  **TKB = 1 $**). Contrat d'arb `SelfFeeArb.sol` (3 093 octets) : flash-borrow
  de TKA sur la paire A, vente sur la paire B via router, remboursement exact
  (`getAmountIn`), profit au caller.
- **Seed :** chaque pool 50 000 TKA + 50 000 TKB (100 000 $ de TVL par pool).
- **Le spread est créé par un vrai trade externe** (pas de réserves éditées à
  la main) : le compte 2 swappe 2 500 TKB → TKA sur la paire B.
  Prix après : A = 1,0000 · B = 1,1023 → **spread +10,23 %**.
- **Taille :** `polygon_decide` (la garde du repo) dit **EXECUTE**,
  prêt optimal **1 144,29 $** (le plafond 10 % = 5 000 $ n'est pas contraignant ;
  c'est le price impact qui limite), net attendu **53,59 $**.
  Emprunt réel : 1 115,41 TKA, remboursement 1 144,29 TKB, gas 225 216 unités
  = **0,0048 $**.
- **Prix juste P\*** : prix convergé post-arb = **1,049382**
  (A après 1,046225 · B après 1,052539). Toutes les richesses sont valorisées
  au même P\* — c'est ce qui rend les 4 cas comparables.
- **Quatre cas, même point de départ** (snapshots Anvil `evm_snapshot` /
  `evm_revert`) :
  - (i) HOLD — propriétaire LP de A seul, aucun trade.
  - (ii) SELF-ARB possède les DEUX — le propriétaire seed A **et** B (200 000 $),
    puis arbe lui-même.
  - (iii) EXTERNAL-ARB — propriétaire LP de A seul, un étranger (compte 2) arbe.
  - (iv) OWN-ONE-PAIR — propriétaire LP de A seul, il arbe lui-même.
- **Richesse totale (propriétaire)** = valeur LP au prix P\* + soldes wallet
  − gas payé. Comptes Anvil de test uniquement (mnémonique publique de test,
  dérivée dans le script — jamais de clé recopiée à la main).

**Reproductibilité :** deux runs complets donnent les mêmes chiffres à 4
décimales près. Tx fork (jetables) : move externe setup 1
`7fdac89d…43a04` (bloc 97 921 685) ; arb (iv) `3939075d…ee691a` (bloc 97 921 686) ;
arb (iii) `0b2b944c…4960` (bloc 97 921 686) ; move setup 2 `0e720559…9c87`
(bloc 97 921 683) ; arb (ii) `56a7d98a…f7ce5` (bloc 97 921 684).

## Phase 3 — Résultats et comptabilité complète

### Les quatre chiffres

| Cas | Richesse propriétaire | Δ vs HOLD |
|---|---|---|
| (i) HOLD (A seul) | 102 469,12 $ | — |
| (iv) OWN-ONE-PAIR (A seul, self-arb) | **102 496,52 $** | **+27,41 $** |
| (iii) EXTERNAL-ARB (A seul, étranger) | 102 442,92 $ | **−26,20 $** |
| (ii) SELF-ARB (A + B) | 204 946,84 $ | **−0,0048 $** vs HOLD-both 204 946,84 $ |

Profit de l'arbitragiste étranger (iii) : **53,6107 $** (gas 0,0048 $ à sa
charge) — la prédiction de la garde (53,59 $) est validée à 0,02 $ près.

### Décomposition exacte (vérifiée au cent près, tests inclus)

Frais par jambe, mesurés exactement (remboursement − remboursement sans frais ;
vente sans frais − vente réelle) :

- **Fee jambe A (emprunt, pool du propriétaire) : 3,4329 $** → revient au
  propriétaire en (iv) et en (ii).
- **Fee jambe B (vente, pool externe) : 3,5220 $** → va aux autres LP en (iv),
  revient au propriétaire en (ii).

Valeur extraite de chaque pool (LVR brut, = ce que le trade prend au pool
avant frais, valorisé à P\*) :

- **LVR_A = 29,6307 $** · **LVR_B = 30,9349 $**
- Croissance de K (le fee qui reste dans les réserves) : A +0,006713 %,
  B +0,006866 %.

Identités vérifiées (toutes à ±0,01 $) :

```
Profit arbitragiste  = LVR_A + LVR_B − fee_A − fee_B
                     = 29,63 + 30,93 − 3,43 − 3,52 = 53,61 $  ✓ (= profit étranger mesuré)
Δ (iii)  = −LVR_A + fee_A = −29,63 + 3,43 = −26,20 $            ✓
Δ (iv)   = LVR_B − fee_B − gas = 30,93 − 3,52 − 0,005 = +27,41 $ ✓
Δ (ii)   = −gas = −0,0048 $                                     ✓ (exact)
(iv) − (iii) = 53,61 $ = profit de l'arbitragiste               ✓
```

### Le test de l'hypothèse d'Ismail — CONFIRMÉE

« Le profit de spread se divise en deux moitiés : la moitié du pool qu'on
possède s'annule (transfert interne), la moitié du pool qu'on ne possède pas
est du vrai profit. »

- **Posséder les deux ≈ −gas** : le profit de trader (53,61 $) est compensé
  au centime par la perte LP sur les deux pools (LVR_A + LVR_B − fee_A − fee_B) ;
  il ne reste que le gas (−0,0048 $). **S'arbitrer soi-même quand on possède
  les deux pools ne gagne rien — on déplace juste de l'argent de sa poche LP
  vers sa poche trader en payant du gas.** Les frais « récupérés » (3,43 $ +
  3,52 $) étaient déjà à soi : ils n'ont jamais quitté les pools.
- **Posséder un seul ≈ la moitié du profit classique** : (iv) = +27,41 $,
  la moitié du profit brut (53,61 $ / 2 = 26,81 $) + 0,60 $ d'asymétrie
  (le pool B, plus cher, contient un peu plus de valeur extractible que A :
  LVR_B − LVR_A = 1,30 $, et fee_A − fee_B = −0,09 $).
- **Laisser un étranger arber coûte 26,20 $** : c'est la LVR nette sur le
  pool qu'on possède (29,63 $ extraits − 3,43 $ de frais récupérés).
- **S'arbitrer soi-même plutôt que laisser un étranger le faire rapporte
  exactement le profit de l'arbitragiste** (+53,61 $) : on garde ce qu'un
  étranger aurait pris.

## (a) La récupération de frais est réelle, mais le spread a toujours besoin d'un flux externe

Le fee de 0,3 % retourne bien au LP — c'est mesuré (K croît, fee_A = 3,43 $
revient au propriétaire). Mais ce fee ne **crée** pas de profit : dans le cas
(ii), les 6,95 $ de frais totaux récupérés font partie des 53,61 $ qui
s'annulent contre la LVR. Le profit net ne vient que du **flux externe** :
c'est le swap de 2 500 TKB du compte 2 qui a créé le spread de 10,23 % et
donc les 60,57 $ de LVR totale (29,63 $ + 30,93 $). Sans ce trade externe,
P_A = P_B = 1,0, la garde dit SKIP, et aucun des 4 cas ne gagne quoi que ce
soit. **Le « payer les frais à soi-même » économise les frais, il ne crée
pas le spread.**

## (b) Self-arb vs HOLD vs external-arb — le résumé chiffré

- Self-arb (un seul pool) **bat HOLD de +27,41 $** et **bat external-arb de
  +53,61 $**.
- Self-arb (deux pools) **perd contre HOLD de 0,0048 $** (le gas) : strictement
  pire que ne rien faire.
- External-arb **coûte 26,20 $** vs HOLD : si un spread apparaît sur ton pool
  et que tu ne l'arbes pas toi-même, un étranger le prend et tu perds la LVR
  nette.

## (c) Coût en capital, IL, exposition aux autres searchers

- **Capital :** pour faire tourner cette simulation à cette échelle, il faut
  **100 000 $ bloqués** (un pool de 50 000 $) pour un profit de 27,41 $ par
  opportunité (0,027 % par trade), ou **200 000 $** (deux pools) pour un
  profit de −0,005 $. Avec des pools de 5 000 $ (10× plus petits), le prêt
  optimal tombe à ~114 $ et le profit à ~2,7 $. Le profit croît avec la taille
  des pools, pas avec la taille du prêt seul — et le prêt optimal est limité
  par le price impact, pas par le capital disponible.
- **IL / LVR :** être LP, c'est vendre quand le prix monte et acheter quand
  il baisse. Ici, la LVR nette subie sur le pool A est de 26,20 $ par
  opportunité arbitrée par un tiers. C'est le coût d'adverse selection du
  market-making : chaque fois qu'un flux externe déplace le prix, le LP perd
  contre l'arbitragiste. S'arbitrer soi-même ne fait que récupérer cette
  perte — jamais plus que la moitié externe.
- **Exposition aux autres searchers :** un flash swap est permissionless —
  **n'importe qui peut arber TON pool**. Le cas (iii) le montre : l'étranger
  a pris 53,61 $ pendant que le propriétaire perdait 26,20 $. Posséder le
  pool ne donne **aucune priorité** : le plus rapide gagne. Si tu seed un pool
  et que tu n'arbes pas toi-même à la seconde où le spread apparaît, un
  searcher plus rapide l'extraira à ta place. Ton pool devient une cible :
  chaque searcher du réseau surveille tes réserves.
- **Frais de seed :** ajouter/retirer la liquidité coûte du gas (non compté
  ici, identique dans les 4 cas) ; la liquidité est exposée en permanence
  (IL) tant qu'elle est dans le pool.

## (d) Le cas « un pool avec seulement ma liquidité »

Un pool dont tu es le seul LP et qui ne reçoit **aucun flux externe** ne bouge
jamais : le prix ne change que quand quelqu'un trade. Pas de trade → pas de
spread → pas d'arbitrage possible, et la garde dit SKIP. Tu ne peux pas créer
un spread en tradant contre ton propre pool seul : un trade contre soi-même
déplace le prix du pool mais ne crée pas de deuxième prix avec lequel
arbitrer — il faut **deux** venues à des prix différents. Concrètement :
seeder un pool et attendre ne produit rien ; il faut que des traders externes
viennent y échanger (c'est leur flux qui crée le spread et la LVR), et à ce
moment-là tu es en compétition avec tous les searchers pour l'extraire.

## Limites de cette simulation (honnêteté)

1. **Le spread est synthétique :** 10,23 % créé par un seul swap de 2 500 $
   sur un pool de 50 000 $. Sur le marché réel Polygon, le meilleur spread
   mesuré est de −0,014 % (pro scan, 117 mesures) et 0 signal sur 61 065
   quotes en 60 min d'écoute temps réel. **La simulation prouve le mécanisme,
   pas l'existence de l'opportunité.** Un spread de 10 % sur un pool de
   50 000 $ n'existe pas sur Polygon en ce moment.
2. **Une seule taille testée** (prêt optimal 1 144 $) ; la théorie (identités
   ci-dessus) est indépendante de la taille, mais les chiffres absolus
   changent avec la profondeur et le spread.
3. **V2 uniquement.** Le flash V3 (fee = tier, LP in-range) suit la même
   logique économique, mais n'a pas été simulé sur fork.
4. **Pas de course :** la simulation exécute l'arb seul, sans autre searcher
   en compétition sur le même bloc. En réel, le plus rapide gagne et les
   autres paient le gas du revert.
5. **Pas de frais de seed/retrait** dans la comparaison (identiques dans les
   4 cas, ils s'annulent) ; en réel, ils s'ajoutent.

## Rejouer

```bash
cd polygon/flash_self_fee
bash run_sim.sh          # fork Anvil (bloc récent) + 4 cas + JSON
../../.venv/bin/python -m unittest polygon.flash_self_fee.test_flash_self_fee -v   # 16/16
```

## Fichiers

- `FLASH_MINT_SWAP_SELF_FEE_POLYGON.md` — ce rapport
- `simulate_self_fee.py` — la simulation (4 cas, snapshots Anvil)
- `run_sim.sh` — lance le fork Anvil (port 8546) puis la simulation
- `contracts/SelfFeeArb.sol` — exécuteur flash-swap V2 (emprunte sur A, vend sur B)
- `contracts/TestToken.sol` — token de test mintable (fork uniquement)
- `simulation_results.json` — tous les chiffres (réserves, frais, tx, blocs)
- `test_flash_self_fee.py` — 16 tests (math V2, comptabilité, garde, identités du fork, non-broadcast)
- `phase1_probe.py` — sondes on-chain de la phase 1
- `anvil_self_fee.log` — log du fork
