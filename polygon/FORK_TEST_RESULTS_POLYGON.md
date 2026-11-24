# Fork test — Morpho Blue Polygon (v4.0)

**Date :** 2026-11-24 ~22:20 UTC — **Bloc fork :** 97 902 229
**Méthode :** Anvil fork de Polygon mainnet (RPC public `https://polygon.drpc.org`,
aucun fond réel, aucune clé privée, aucun broadcast mainnet).
**Script :** `bash fork_test_polygon.sh` → `fork_test_polygon.py` →
résultats bruts `fork_results_polygon.json`.

## Ce qui a été prouvé

| Étape | Résultat |
|---|---|
| Morpho Polygon sur le fork | code présent, **15 582 octets** ; `flashFee` getter **absent** (revert confirmé) → frais **0 $ structurellement** |
| Soldes Morpho (fork) | USDC **112 261,04 $** · USDT **122 029,66 $** · WMATIC **1 000 246,35** — utilisable à 50 % : **56 130,52 $ USDC** |
| Réserves QuickSwap V2 USDC/WMATIC | 8 057,07 WMATIC / 611,27 $ USDC — prix 0,0759 $ |
| Pool Uni V3 USDC/WMATIC 0,3 % | réserves virtuelles actives 113 339,78 WMATIC / 8 601,32 $ USDC (slot0 + liquidité ; le `balanceOf` brut de la pool est trompeur — liquidité hors range) — prix 0,0759 $ |
| Spread naturel | **0,03 %** (marché aligné, comme sur Base) |
| Spread synthétique (vente de 10 % de la réserve QS) | **21,0 %** — QS 0,0627 $ vs V3 0,0759 $ |
| Décision off-chain | **EXECUTE** — loan optimal **50,22 $**, net attendu **4,83 $**, gas estimé 0,0053 $ |
| Déploiement contrat | `0xd3885d0CEE73Ee54e0864129205fbbA20Caa6A36`, bloc 97 902 233, gas 1 320 087, `MORPHO()` on-chain = `0x1bF0…5f67`, minProfit on-chain = 3 000 000 (3 $) |

## Cas gagnant — broadcast sur le fork

| Mesure | Valeur |
|---|---|
| Statut tx | **1 (succès)** — hash `2338b0d3…c9b24b0` |
| Loan | **50,22 $** (Morpho, frais 0 $) |
| Profit brut | **4,84 $** |
| Gas utilisé | 268 626 @ 136,58 gwei = **0,03669 MATIC = 0,002781 $** |
| **Profit net** | **+4,83 $ — WIN** (≥ min 3 $) |
| Événement on-chain | `MorphoPolygonArbitrageExecuted` — profit 4,84 $ |

## Cas perdant

| Mesure | Valeur |
|---|---|
| Décision off-chain (spread 0,51 %) | **SKIP** — net attendu −0,01 $ → rien broadcasté, **0 $ payé** |
| Revert mesuré (broadcast volontaire sur le fork, pour chiffrer) | raison on-chain : `pas de quoi rembourser le loan` — gas 262 332 @ 119,57 gwei = **0,031366 MATIC = 0,002378 $** |

## Float — 1,31 $ MATIC (17,2743 MATIC)

- Coût mesuré par trade (fork, gas ~137 gwei) : **0,0028 $**
- Coût prudent comptabilisé (ledger : 450 000 gas × 279 gwei live) : **0,0095 $/trade**
- Runway ledger : **~137 trades** ; pire cas (trade + revert) : **~68 trades**
- Runway au coût mesuré sur le fork (gas ×2) : **235 trades**
- Kill switch : float à 0 $ → arrêt (voir `polygon_ledger.py`)

## Leçon de debug — la jambe V3 (important)

La première version du contrat utilisait le **SwapRouter02** (`0x68b346…`)
avec `exactInputSingle` — comme sur Base. Le fork revert avec données vides.
Le `debug_traceCall` a montré :

- Morpho flashLoan ✓, callback ✓, achat QuickSwap V2 ✓,
- **le CALL au SwapRouter02 revert SANS aucun sous-appel** ;
- vérification bytecode : le sélecteur `exactInputSingle` (**0x414bf389**)
  est **ABSENT** du code déployé sur Polygon (idem `exactInput` 0xc04b8d59).
  Le contrat à cette adresse n'expose pas les swaps V3 — un test EOA direct
  confirme le revert. (La 4byte DB associe 0x04e45aaf à une variante à
  7 champs, mais l'appel échoue en `STF` : variante non fiable, non utilisée.)
- La paire **Sushi V2 USDC/WMATIC est vide (~12 $ de liquidité)** :
  pas de jambe V2 de repli.

**Correctif appliqué (v4.0) :** jambe de vente = **appel direct à la pool V3**
(`pool.swap` + `uniswapV3SwapCallback`, pattern canonique Uniswap V3),
avec `sqrtPriceLimitX96 = 4295128740` (MIN_SQRT_RATIO + 1 — la valeur 0
« pas de limite » est rejetée par la pool). C'est cette version qui a
produit le WIN ci-dessus. La doc (`POLYGON_FLASH_VERIFICATION.md`,
`polygon_config.yaml`) a été corrigée en conséquence.

## Limites

- Spread synthétique (10 %) : aucune opportunité réelle de ce type n'a été
  observée sur Polygon au moment du test (voir `MEME_POOLS_LIVE_POLYGON.md`).
- Le gas du fork (~120–160 gwei) est inférieur au gas live mesuré (279 gwei) ;
  le ledger comptabilise le cas prudent (450 000 gas × 279 gwei).
- Fork = preuve de fonctionnement du contrat, pas de profit réel.
  Avant tout usage live : paper-trade Amoy 2–4 semaines + audit payant.
