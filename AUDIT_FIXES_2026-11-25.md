# Corrections des 15 findings de l'audit ChatGPT — 2026-11-25

**Audit :** `~/workspace/user/files/CODEMA_Flashloan_Audit_2026-11-25_0_mxer.md`
(15 findings : 10 P1 + 5 P2, sur l'archive `codema-base-flashloan-bot-master.zip`).
**Repo :** `~/workspace/crypto-base-flashloan-bot/` — **AUCUN commit** (le parent s'en charge).
**Règle :** AUCUN broadcast, AUCUN wallet, AUCUNE clé, AUCUN fond.
**Périmètre :** tout sauf `leadlag/` (autre agent : findings #1, #2 et partie
cross-venue de #11 — terminés, vérifiés et poussés par le parent, commit
`3b7bce3`, rapport `leadlag/ROUTE_VERIFICATION.md`).

**Verdict : 15/15 CORRIGÉ, 0 restant.** Chaque finding a son test vert.
Tous les résultats de simulation/fork sont étiquetés **synthétiques**.

## Suite complète re-run le 2026-11-25 (après toutes les corrections)

| Suite | Commande | Résultat |
|---|---|---|
| Racine | `.venv/bin/python test_math_engine.py` | TOUS LES TESTS PASSENT |
| Racine | `.venv/bin/python test_v2.py` | TOUS LES TESTS V2 PASSENT |
| Racine | `.venv/bin/python test_morpho.py` | 14/14 |
| Racine | `.venv/bin/python test_balancer.py` | 11/11 |
| Racine | `.venv/bin/python test_sponsor.py` | 12/12 |
| Racine | `.venv/bin/python test_zero_cost.py` | 15/15 |
| Racine | `.venv/bin/python test_self_funded.py` | 17/17 |
| Racine | `.venv/bin/python test_gas.py` | 7/7 |
| Racine | `.venv/bin/python test_circuit_breaker.py` | 5/5 |
| Fork preflight | `.venv/bin/python test_fork_preflight.py` | 3/3 (synthétique) |
| Fork V3 | `.venv/bin/python fork_test_v3.py` | 1/1 (synthétique) |
| Polygon | `cd polygon && ../.venv/bin/python -m unittest discover -s . -p "test_*.py" -t .` | **178/178 OK** |

Note : un run de `test_fork_preflight.py` a montré 1 échec transitoire
(port Anvil/RPC), les 2 runs suivants sont 3/3 — flakiness d'environnement,
pas du code.

---

## P1 — #1 cross-tx : couverture ~3,3 % des blocs — CORRIGÉ (autre agent)

**Confirmé.** Le cross-tx n'observait qu'environ 1 bloc sur 30, pas 1 sur 3.
**Correction (leadlag/, autre agent, commit `3b7bce3`) :** replay 24 h
`leadlag/replay.py` — couverture mesurée honnêtement :
**17 250 / 432 001 blocs = 3,99 %** ; 414 751 blocs (96,01 %) non observés.
Un 0 sur ce replay ne prouve pas l'absence de gaps — il borne seulement
les gaps qui vivent ≥ 5 s. Preuve : `leadlag/ROUTE_VERIFICATION.md` § replay,
`replay_24h_summary.json`. **Ce finding n'est pas dans mon périmètre.**

## P1 — #2 label « vérifié » ne vérifie pas le cycle coté — CORRIGÉ (autre agent)

**Confirmé.** Le label REAL reposait sur des quotes analytiques, sans
re-quote de la jambe de vente au montant réel.
**Correction (leadlag/, autre agent, commit `3b7bce3`) :**
`leadlag/route_verify.py` + `size_optimizer.py` — cycle atomique complet
simulé à chaque taille, quotes au montant et au sens réels de chaque jambe,
fees lues on-chain au bloc, statuts `FULLY_QUOTER_VERIFIED` /
`PARTIALLY_VERIFIED` / `NOT_VERIFIED` par jambe. Les 2 meilleurs événements
apparents (E1/E2) re-vérifiés NÉGATIFS (−0,0470 $ / −0,0782 $) avec la vraie
fee au bloc. Preuve : `leadlag/ROUTE_VERIFICATION.md` § (a)–(b), table
route/bloc/taille optimale/brut/fees/impact/gas/net. **Hors de mon périmètre.**

## P1 — #3 scanner : holders = 0 par défaut, le scanner rejette ses propres candidats — CORRIGÉ

**Confirmé.** `MemeCandidate.holders` valait 0 par défaut, `passes_filters`
exigeait ≥ 20 holders, `scan_token` ne renseignait jamais holders, et
`apply_goplus_to_candidate` ne transférait pas `holder_count`.

**Avant** (`scanner.py`) : `holders: int = 0` ; `apply_goplus_to_candidate`
lisait `holder_count` dans une variable locale seulement.

**Après** :
- `MemeCandidate` gagne `holders_known` / `holders_source` / `age_known` —
  « inconnu » ≠ 0, le statut de disponibilité est propagé.
- `vet_token_goplus_detailed()` retourne `holder_count`.
- `apply_goplus_to_candidate()` transfère `holder_count` au candidat.
- `passes_filters()` rejette explicitement les holders/âge inconnus (avec
  la raison), au lieu de les confondre avec 0.
- `scan_token()` vette une fois par token, transfère holders + âge, et
  imprime la raison de rejet la plus fréquente au lieu de retourner 0
  en silence.

**Tests** (`test_v2.py`) : `test_scanner_unknown_holders_rejected_explicitly`
(contre-exemple de l'audit : 2 pools, spread 20 %, holders inconnus → 0
candidat avec raison explicite ; holders vérifiés → passe),
`test_scanner_holders_propagated` (GoPlus + DexScreener mockés → 1 candidat,
holders=500, âge ~10 h, spread 20 %). **Vert.**

## P1 — #4 scanner : mauvais endpoint DexScreener — CORRIGÉ

**Confirmé.** `fetch_pairs_from_dexscreener` appelait
`/latest/dex/pairs/base/{token_address}`, qui attend une adresse de PAIRE.

**Avant** : `/latest/dex/pairs/base/{token_address}` ; sélection USDC sur le
symbole seul.

**Après** : `/token-pairs/v1/base/{tokenAddress}` (schéma de réponse adapté) ;
`_is_usdc_quote()` sélectionne l'USDC par son ADRESSE
(`USDC_BASE = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`), le symbole n'est
qu'un repli quand l'adresse est absente ; `pairs_age_hours()` depuis
`pairCreatedAt`.

**Test** : `test_scanner_dexscreener_token_pairs_endpoint` (assert l'URL
`/token-pairs/v1/base/`) + `test_scanner_usdc_address_not_symbol`. **Vert.**

## P1 — #5 scanner : taxes GoPlus en décimal 0–1 non converties — CORRIGÉ

**Confirmé.** `_tax()` ne convertissait pas : une taxe de 50 % (0,50)
comparée à `max_tax_pct=5.0` PASSAIT.

**Avant** : taxe 0,50 → comparée à 5,0 → passe.

**Après** : normalisation en % (0,50 → 50), seuil 5 % = 0,05 en décimal ;
taxe absente → `tax_unknown` → UNKNOWN (jamais 0) ; `GOPLUS_REJECT_FLAGS`
inclut désormais `not_open_source`, `too_few_holders`, `tax_unknown`.

**Tests** : `test_goplus_tax_decimal` (0,50 → 50 % REJET ; 0,05 → 5 % PASSE),
`test_goplus_tax_unknown` (taxe absente → UNKNOWN),
`test_goplus_not_open_source_and_few_holders_reject`. **Vert.**

## P1 — #6 preflight : pas de simulation de la transaction complète — CORRIGÉ

**Confirmé.** Le « preflight EVM » ne faisait que deux `getAmountsOut` sur
`latest`, n'appelait jamais `executeArbitrage`, ne vérifiait ni transferts
ni callbacks ni remboursement, n'appelait pas `estimate_gas_swap`, coût gas fixe.

**Avant** (`preflight.py`) : quotes sans bloc fixé, gas figé 450 k.

**Après** :
- `preflight.py` : `eth_call` / `get_amounts_out` / `get_reserves` /
  `estimate_gas_swap` prennent un paramètre `block` ; `preflight_roundtrip`
  épingle LES DEUX quotes sur UN SEUL bloc (lu une fois) et retourne le net
  en pleine précision ; le gas reste un budget figé (450 k) avec une note
  explicite : un `eth_estimateGas` par jambe depuis une EOA est impossible
  pour ce flux (les tokens n'existent qu'en cours de transaction, après le
  flash loan — l'estimation reverterait sur solde nul) ; le gas exact est
  donc mesuré sur fork. Constante `FORK_TX_OVERHEAD_GAS = 150_000`
  documentée comme estimation. `PreflightResult` gagne `l1_fee_usd` (#12).
  `executor.simulate_evm` récupère le bloc une fois et le passe.
- **Nouveau `fork_preflight.py`** : lance un fork Anvil (subprocess,
  `--fork-url`, `--fork-block-number`, port vérifié avec `SO_REUSEADDR`),
  déploie `MorphoFlashLoanArbitrage` depuis
  `out/FlashLoanArbitrage.sol/MorphoFlashLoanArbitrage.json` ;
  `fork_preflight()` fait eth_call + estimate_gas + envoi impersonné de
  `executeArbitrage` depuis le owner, retourne un dict étiqueté
  **synthétique** (statut WIN/REVERT, gas_estimate, gas_used, raison de
  revert décodée `0x08c379a0`). Helpers `impersonate` / `stop_impersonate` /
  `set_balance` (anvil_setBalance — l'impersonné Morpho détient l'USDC mais
  0 ETH pour le gas).
- Clé de test Anvil corrigée :
  `0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80`
  (se termine par `f2ff80`, PAS `f3ff80` — vérifié via
  `cast wallet private-key --mnemonic "test test … junk"`).

**Résultats fork (synthétiques, fork mainnet Base, blocs ~62 098 770–62 098 880) :**
- REVERT : statut REVERT, raison exacte « pas de quoi rembourser le loan »,
  gas consommé **327 643** (eth_estimateGas échoue sur un tx qui revert —
  attendu, `gas_estimate=None` + `gas_estimate_error` renseigné).
- WIN (mouvement whale : 1 000 000 USDC de Morpho impersonné, swap
  USDC→WETH sur Uni V2) : statut WIN, gas estimé **364 032**, gas consommé
  **285 915**.
- Preflight à bloc épinglé (bloc 62 098 880) : LOSE, net −0,7577 $ (marché
  réel, pas de spread — attendu).

**Tests** : `test_fork_preflight.py` **3/3 vert** (re-run le 2026-11-25 :
blocs 62 104 122 / 62 104 180 / 62 104 233, mêmes valeurs).

## P1 — #7 contrat Base V2-only, pas de route CL exécutable — CORRIGÉ

**Confirmé.** Le contrat Base n'utilisait que `swapExactTokensForTokens`
(V2), tokens/routers immuables ; aucune route CL (Slipstream / Uni V3)
n'était exécutable par lui ; l'exécuteur préparait de l'USDC sans
intégration du prêt cbBTC.

**Avant** : `contracts/FlashLoanArbitrage.sol` = V2 seul ; `executor.py`
acceptait n'importe quelle paire de DEX sans vérifier l'exécutabilité.

**Après** :
- **Nouveau `route.py`** : `Route` / `Leg` typés, mapping `DEX_KIND`,
  `ADAPTER_FOR_KIND` (seuls `v2` et `v3-uni` ont un adaptateur),
  `route_executable_by_contract(route, adapters=("v2",))` avec raisons
  explicites, `build_route_from_candidate()`. Démo vérifiée : V2+V2 → True ;
  Aero+V2 → False (Aerodrome Classic n'a pas d'interface V2) ; V3+V3 par
  défaut → False (adaptateur non autorisé), avec `("v2","v3-uni")` → True.
- **`executor.py`** : `simulate()` bloque sur l'exécutabilité de la route
  AVANT tout EXECUTE (route non exécutable → SKIP avec raison explicite) ;
  supporte `loan_token` / `loan_token_symbol` / `adapters` (prêt non-USDC/WETH
  sans soldes vérifiés dans `vault_balances` → SKIP « prêt non intégré »).
  `run(mode='live')` lève toujours une exception — **blocage explicite
  conservé tel quel**.
- **Nouveau contrat `MorphoFlashLoanArbitrageV3`** (ajouté à
  `contracts/FlashLoanArbitrage.sol`, après `IMorphoFlashLoanCallback` —
  ordre requis par Solidity) : params `loanToken` / `tokenOther` / `router` /
  `feeBuy` / `feeSell` / `minProfit`, `executeArbitrage` via flash Morpho,
  callback 2× `exactInputSingle` + remboursement + garde `minProfit` +
  `withdrawProfit` / `setMinProfit`. Interface `ISwapRouter` minimale
  définie inline (pas de v3-core dans `lib/`).
- **DÉCOUVERTE CLÉ (vérifiée 2026-11-25, Basescan ABI + tx live
  `0x99bbc768…`) :** le SwapRouter02 de Base
  (`0x2626664c2603336E57B271c5C0b26F421741e481`, 24 497 octets, « Uniswap V3:
  Swap Router02 » vérifié sur Basescan, compilateur v0.7.6) utilise le
  struct `ExactInputSingleParams` à **7 champs SANS `deadline`** — sélecteur
  `0x04e45aaf`. Le struct à 8 champs avec deadline (sélecteur `0x414bf389`,
  canonique sur Ethereum) REVERT sans raison sur Base — prouvé sur fork
  (swap direct USDC→WETH sur le vrai pool fee-500 revert avec 8 champs ;
  la quote QuoterV2 du même swap fonctionne). Le contrat et le test fork
  utilisent le struct à 7 champs ; docstring : ne jamais rajouter `deadline`
  sur Base.
- Nouveaux helpers de test : `contracts/TestToken.sol`,
  `contracts/TestV3Minter.sol` (mint + `uniswapV3MintCallback`).

**Résultats fork V3 (synthétiques, fork mainnet Base, blocs ~62 101 241–243) :**
deux pools V3 synthétiques via la vraie factory
(`0x33128a8fC17869897dcE68Ed026d694621f6FDfD`), deux tiers de fee
(3000 / 10000 — un pool par paire+fee, donc deux tiers requis pour deux
prix), token MEME frais ; pool A 1 MEME = 0,01 USDC, pool B 1 MEME =
0,011 USDC (spread 10 %). **WIN : profit 7,98 USDC sur 100 USDC, gas
estimé 409 203, gas consommé 321 487. REVERT : après vente de 200 000 MEME
sur le pool B (prix sous le pool A), `executeArbitrage` revert comme attendu.**
Leçons de debug consignées : `createPool` exige 5 000 000 gas (2 M
insuffisant) ; prix V3 en unités BRUTES (MEME 18 déc, USDC 6 déc :
1 MEME = 0,01 USDC → prix brut 10^-14, pas 0,01 — la 1re tentative a
initialisé des prix absurdes avec de la liquidité poussière et le swap
revertait sans raison) ; liquidité L ≈ 3,8e17 par pool.

**Tests** : `fork_test_v3.py` **1/1 vert** (re-run 2026-11-25 : blocs
62 104 279 / 62 104 281, profit 7,98 USDC, gas 321 487). `forge build` OK.
Fixtures de test (`test_balancer.py`, `test_morpho.py`, `test_sponsor.py`,
`test_zero_cost.py`, `test_self_funded.py`, `dry_run.py`) : dexes
`"aerodrome", "uniswap"` → `"uniswap", "sushi"` (V2-only) — toutes vertes
après le changement.

## P1 — #8 `encode_quote_single` : ordre des champs faux — CORRIGÉ

**Confirmé.** `v3_quote.py:74,79` encodait (tokenIn, tokenOut, fee,
amountIn, sqrtPriceLimitX96) alors que le struct officiel
`IQuoterV2.ExactInputSingleParams` est (tokenIn, tokenOut, **amountIn**,
**fee**, sqrtPriceLimitX96) — amountIn recevait 500 et fee recevait
100 000 000 (> uint24.max) → calldata invalide. La conclusion
« quoteExactInputSingle REVERT sur Base » était donc INVALIDE.

**Avant** : ordre (tokenIn, tokenOut, fee, amountIn, sqrtPriceLimitX96).

**Après** : ordre officiel (tokenIn, tokenOut, amountIn, fee,
sqrtPriceLimitX96) + contrôle de borne uint24 ; ajout de
`decode_quote_single()` et `decode_quote_single_result()` ;
ajout de `quote_single_onchain()` ; docstrings corrigées.

**Test live (lecture seule, RPC Alchemy de config.yaml, clé jamais
affichée), bloc ~62 093 375 :** décodage vérifié amountIn=100 000 000,
fee=500 ; **quoteExactInputSingle REVERT TOUJOURS avec le bon calldata**
(3 variantes : limit 0 / MAX-1, fees 500/3000, USDC→WETH et WETH→USDC)
alors que quoteExactInput sur le même pool fonctionne (100 USDC →
**0,06099416239264347 WETH**, gas ~86 344). Conclusion honnête consignée
dans le code : l'ancienne preuve était invalide, mais la conclusion
(« inutilisable sur Base ») est CONFIRMÉE par le test corrigé ;
quoteExactInput (path) reste la route qui fonctionne.

**Tests** (`test_v2.py`) : `test_v3_quote_single_encoding` (décodage + ancien
encodage buggé reproduit : amountIn=500, fee=100 000 000 ; fee >
uint24.max refusée), `test_v3_quote_single_live` (single=revert/indisponible
ET path fonctionne sur le même pool ; skip propre en cas d'échec RPC).
**Vert.**

## P1 — #9 arrondi gas au centime : $0,0044 → $0,00 — CORRIGÉ

**Confirmé.** `_round2` arrondissait chaque coût gas au centime :
`charge_gas(0,0044)` retournait True sans rien déduire
(100 × 0,0044 $ = 0,00 $ au lieu de 0,44 $).

**Avant** (`self_funded.py:58-60,140,184,187`, `math_engine.py:237,333`) :
arrondi à 2 décimales à chaque accumulation.

**Après** :
- `math_engine.py` : `find_optimal_loan` ne round plus aucune valeur
  retournée (pleine précision float ; `decide` utilise le net non arrondi) ;
  grille abaissée 10 $ → **1 $** (grille géométrique 60 points depuis 1 $ ;
  `hi <= 1` → « liquidité trop faible ») ; candidats clampés à `hi`
  (`min(v, hi)`) et `best_loan = min(best_loan, hi)` — une erreur float
  produisait loan 50000,00000000015 > cap. `POLICIES` documente la
  différence délibérée de seuil (Base min 3 $ + gas×3 vs Polygon min 0 $ +
  gas×0). Vérifié numériquement : cas sub-cent (spread 0,05 %, fees 1 bp/jambe,
  gas 0,001 $) → net optimal **+0,0001259 $**, decide EXECUTE (l'ancien
  arrondi l'aurait mis à 0,00 → SKIP).
- `self_funded.py`, `sponsor.py`, `zero_cost.py` : `_round_usd`
  (micro-dollar, 6 décimales) pour toute accumulation/persistance/ledger ;
  `_round2` gardé UNIQUEMENT pour l'affichage et les splits de payout
  (`split_profit`, que les tests assertent au centime, ex. 73,07 × 25 % =
  18,27). Appliqué par script (self_funded 22 occurrences, sponsor 13,
  zero_cost 18) ; `_round2` ré-ajouté comme affichage seul dans les trois
  fichiers après le renommage par le script.
- Attentes de tests qui consacraient l'arrondi buggé corrigées aux valeurs
  exactes : `test_worst_case_cost` : 0,0066 → **0,0132** (était 0,02) ;
  nouveau `test_gas_subcent_accumulates` : 100 × charge_gas(0,0044) →
  ismail_paid 0,44, float_remaining 19,56, worst_case_cost(0,0044) ==
  0,0088 ; `test_executor_self_funded_end_to_end` : gas 0,0675 (était 0,07),
  float 19,9325 (était 19,93), profits = net exact 73,069686… (comparé à
  1e-6, sanity vs 73,07) ; `test_sponsor.py` prefund_remaining 19,9934
  (était 19,99).
- Effet de bord du changement de grille corrigé : optimal loan désormais
  785,876 (était 790,16 — région d'optimum plate, net identique à 0,001 $) ;
  `test_morpho.py` + `test_balancer.py` `test_fee_zero_vs_aave_reference`
  assertent désormais loan dans (780, 800) et flash_fee depuis le loan réel.

**Tests** (`test_math_engine.py`) : `test_optimal_loan_subcent_precision`,
`test_find_optimal_loan_small_sizes` (pools cap 4,50 $ trouvent l'optimum
~3–4 $). **Vert.**

## P1 — #10 `verify_signal_exact` Polygon : entrée de vente = prix spot — CORRIGÉ

**Confirmé.** `polygon/realtime_listener.py:646-684` calculait `out_a`
(exact) mais l'entrée de vente depuis un prix spot (`res_b/res_a`) au lieu
de `out_a`, et `expected_net_usd` / `action` venaient de `polygon_decide`
sur réserves approximatives — le net ne dépendait pas de la quote de vente
(contre-exemple de l'audit : vente à 1 $ → toujours +0,47 $ EXECUTE).

**Avant** : `sell_in = amount * res_b / res_a` (spot) ; verdict de
`polygon_decide` sur réserves approximatives.

**Après** : nouveau helper `_exact_cycle_net()` — jambe d'achat cotée
on-chain, son `out_a` EXACT devient l'entrée de la jambe de vente (jamais
un re-calcul au prix spot) ; retour en $ depuis `out_b` ; coûts exacts
soustraits (flash Morpho 0 % + gas trade+revert via `polygon_costs`) ;
verdict dérivé de ce net à la taille testée ; si la taille optimale
approximative diffère de > 10 %, re-quote exacte à cette taille et on garde
le meilleur net ; action EXECUTE seulement si net >
`ONCHAIN_MIN_PROFIT_USD` (0,01, le plancher du contrat — un net dans
]0 ; 0,01] reverterait on-chain). Le retour garde les anciennes clés
(method/spread_pct/expected_net_usd/action/optimal_loan_usd) + nouvelles
(size_tested_usd, size_optimal_approx_usd, size_revalidated, usdc_back_usd,
gross_usd, flash_fee_usd, gas_total_usd, above_onchain_floor). Import
étendu à `polygon_costs` + `ONCHAIN_MIN_PROFIT_USD`. Note : `evaluate_pair`
ne renseignait jamais `best_buy_v` / `best_sell_v` — `verify` retrouve les
venues dans `pair["venues"]` par adresse de paire, ce qui fonctionne ;
aucun changement nécessaire là.

**Tests** (`polygon/test_realtime_listener.py`, classe `TestVerifySignalExact`,
5 tests) : contre-exemple de l'audit (achat 1 000 $ → ~987 tokens, vente →
~0,91 $ → SKIP, net < −900 $ — mesuré construit manuellement car
`evaluate_pair` ne choisit jamais un vendeur en effondrement comme meilleur
prix), cas positif (+23 $ → EXECUTE), pool d'achat thin (out_a ~499 pas
1 000 → SKIP), revalidation de taille optimale (5 000 $ perd par impact →
garde 1 000 $), venues manquantes → None. **24/24 vert** (suite listener).

## P2 — #11 granularité des tailles (3 tailles seulement) — CORRIGÉ

**Partie math (mon périmètre) :** grille `find_optimal_loan` abaissée à
**1 $** (voir #9) — l'optimum est désormais cherché sur 60 points
géométriques de 1 $ à `hi`, pas 3 tailles fixes. `POLICIES` documente les
seuils par chaîne. **Vert** (`test_math_engine.py`).
**Partie cross-venue (leadlag/, autre agent) :** `size_optimizer.py` —
grille **1 $–1 000 $** sur les 3 routes, taille optimale 1 $ sur les 3
routes, aucun seuil fixe supposé (threshold calculé par taille).
Preuve : `leadlag/ROUTE_VERIFICATION.md` § (b) + `size_optimizer_results.json`.

## P2 — #12 coût gas complet de la transaction exacte (dont L1 Base) — CORRIGÉ

**Confirmé.** Coût gas figé (0,0044 $) sans composante L1, sans conversion
USD datée.

**Avant** (`gas.py`) : gas L2 seul, montant figé.

**Après** :
- `GasPriceOracle` `0x420000000000000000000000000000000000000F`, sélecteur
  `getL1Fee` `0x49948e0e`, sélecteur `executeArbitrage` `0xf7c7724f`
  (tous deux vérifiés par keccak le 2026-11-25) ; `get_l1_fee_wei()`
  (encodage ABI `bytes` : offset 32 + longueur + données paddées — la 1re
  version utilisait offset 0, corrigée) ; dataclass `EthPrice` (prix +
  source datée, source requise — un prix sans source est refusé avec
  ValueError) ; `fetch_eth_price_usd()` via API publique CoinGecko ;
  `estimate_full_tx_cost_usd()` (L2 + L1, sources étiquetées) ;
  `GasReading` gagne `l1_fee_usd` / `l1_source` / `total_cost_usd`.
- `preflight_roundtrip` prend `tx_data` + `eth_price_source`, ajoute la fee
  L1 mesurée au coût gas (`PreflightResult.l1_fee_usd`) ; `simulate_evm`
  construit le calldata via `execute_arbitrage_calldata()` et le passe.

**Mesures live (2026-11-25 ~12:45 UTC, lecture seule) :** ETH 1 643,18 $
(CoinGecko) ; fee L1 pour `executeArbitrage(100 USDC)` = 2 482 283 377 wei
≈ **0,000004 $** — négligeable mais MESURÉE, pas supposée ; coût complet
L2 0,0370 $ + L1 0,000004 $.

**Tests** : `test_gas.py` **7/7 vert**.

## P2 — #13 chemins absolus, requirements.txt, tests exigeant config.yaml — CORRIGÉ

**Confirmé partiellement.** Chemins `/home/hatch` codés en dur dans
`leadlag/cross_venue.py:53,56,94,101` — **lecture seule, hors de mon
périmètre** (autre agent, fichier non modifié). Dans MON périmètre :
vérifié par grep le 2026-11-25 : **AUCUN chemin `/home/hatch` codé en dur
hors `leadlag/`**.

**Corrections dans mon périmètre :**
- **Tests exigeant config.yaml :** helper `_config_path()` ajouté à
  `test_self_funded.py`, `test_sponsor.py`, `test_zero_cost.py`
  (config.yaml si présent, sinon config.yaml.example) ; loaders
  (`load_from_config` dans `sponsor.py`, `zero_cost.py`, `self_funded.py`)
  acceptent désormais `path=None` → env `CODEMA_CONFIG` → `"config.yaml"`.
- **`test_v2.py` `_rpc_url_for_live_test()` :** essaie désormais
  `config.yaml` PUIS `config.yaml.example`, puis le RPC public ; les URLs
  placeholder (`YOUR_…`) de l'example sont ignorées (sinon le fallback RPC
  serait cassé par le placeholder).
- **requirements.txt (réécrit) :** dépendances désormais DÉCLARÉES, versions
  vérifiées dans `.venv` (`pip list`, 2026-11-25) : `web3>=8.0`,
  `eth-abi>=6.0`, `eth-utils>=6.0`, `websockets>=17.0`. Vérifié :
  **pyyaml N'EST PAS une dépendance** — aucun fichier ne l'importe (les
  loaders utilisent un parseur stdlib) ; il n'est donc PAS ajouté (l'ancien
  fichier le listait en optionnel, ce qui était trompeur). `pytest`
  optionnel (tests en `python3 test_x.py` / `python3 -m unittest`) ;
  foundry (forge/anvil) = binaire système, pas pip (commande d'install
  documentée dans le fichier).

**Preuve :** `requirements.txt` ; grep `/home/hatch` hors leadlag/ propre ;
suites racine vertes sans config.yaml requis.

## P2 — #14 plafond provider revalidé APRÈS réoptimisation ; pas de verdict sur ancien solde — CORRIGÉ

**Confirmé.** `executor.py` / `morpho_flash.py` : le plafond Morpho n'était
pas revalidé après réoptimisation de la taille ; un verdict exécutable
pouvait reposer sur un solde daté si la lecture live échouait.

**Avant** : sélection du provider une seule fois, avant réoptimisation ;
soldes mesurés au bloc 61 806 974 réutilisés.

**Après** (`executor.py`) :
- `simulate()` revalide le plafond Morpho APRÈS réoptimisation : si le
  loan ré-optimisé à 0 % dépasse `usable_usd`, il est plafonné à
  `usable_usd` et re-décidé ; la taille finale ne dépasse jamais le plafond
  du provider.
- `run()` : si `rpc_url` est donné et `fetch_morpho_balances()` échoue,
  Morpho est supposé indisponible (soldes 0,0 → repli Aave) — JAMAIS de
  verdict exécutable sur des soldes datés.

**Tests** (`test_morpho.py`, ajoutés le 2026-11-25, suite désormais 14 tests) :
- `test_provider_cap_revalidated_after_reoptimization` — cas construit où
  la branche se déclenche vraiment : spread 2 %, pools 10 k$ → optimal
  Aave **33,53 $**, optimal Morpho (0 %) **35,05 $** ; plafond utilisable
  34 $ (solde 68 $) : la 1re sélection choisit Morpho (33,53 ≤ 34), la
  réoptimisation pousse à 35,05 > 34 → **loan final plafonné à 34,00 $**
  (assert `loan_usd <= 34.0`, provider `morpho`, action EXECUTE, net > 0).
  Vérifié en probe : avec un solde de 100 $ (utilisable 50 $), l'optimal
  785,88 $ ne tient pas chez Morpho → repli Aave documenté (raison
  explicite), pas de dépassement de plafond.
- `test_stale_balances_never_authorize_morpho` — lecture live mockée en
  échec (`fetch_morpho_balances` → None) : `run()` avec `rpc_url` →
  provider **aave**, raison contenant « 0.00 » ; `simulate()` avec soldes
  0,0 → **aave** également. Aucun verdict Morpho sur les soldes datés du
  bloc 61 806 974.
**Vert : 14/14.**

## P2 — #15 circuit breaker : une seule méthode d'enregistrement — CORRIGÉ

**Confirmé.** `circuit_breaker.py:121,127,138` : deux chemins incohérents —
`record_real_trade` comptait un trade perdant comme revert SANS déclencher
la pause ; `record_revert` ne comptait ni le gas ni le trade.

**Avant** :
```python
def record_real_trade(self, net_usd, token_address=""):
    self.net_today_usd += net_usd
    self.trades_today += 1
    if net_usd < 0:
        self.consecutive_reverts += 1   # SANS vérification de la pause
def record_revert(self):
    self.consecutive_reverts += 1       # ni gas, ni trade compté
    if self.consecutive_reverts >= 3:
        self.paused_until = time.time() + 3600
```

**Après** — `record_receipt(status, gas_usd, token_address, tx_hash, net_usd)`
unique :
- `status` ∈ `"success" | "revert" | "simulated"` (autre valeur → ValueError).
- `success` : net RÉEL (déjà net du gas) compté dans `net_today` +
  `trades_today` ; reverts remis à 0, sauf si net < 0 (perte anormale →
  +1 revert, **AVEC** pause).
- `revert` : perte = −`gas_usd`, trades +1, reverts +1, pause à 3
  d'affilée. Le gas du revert est désormais compté comme perte.
- `simulated` : rien n'est compté (0 $ réellement perdu).
- **Déduplication :** un même `tx_hash` ne compte jamais deux fois
  (retour `"duplicate"`, `seen_tx_hashes` persisté, plafonné à 500).
- Un seul appel met à jour ENSEMBLE compteurs de pertes, trades, reverts
  ET pause — pas de double comptage possible.
- `record_real_trade(net, token, tx_hash="")` et
  `record_revert(gas_usd=0.0, token_address="", tx_hash="")` deviennent de
  fines enveloppes de `record_receipt` (signatures rétro-compatibles ;
  l'ancien `record_revert()` sans argument fonctionne toujours, gas 0).
- `status()` inchangé (arrondi à 2 décimales = affichage seul, valeur
  interne en pleine précision).

**Tests** (nouveau `test_circuit_breaker.py`, **5/5 vert**) :
- `test_three_losing_real_trades_pause` — 3 × −0,10 $ → pause 1 h
  (avant : aucune pause).
- `test_three_reverts_count_gas_and_trades` — 3 × revert 0,01 $ → net
  −0,03 $, 3 trades, pause.
- `test_duplicate_tx_hash_counted_once` — 3 enregistrements du même hash
  → 1 seul compté.
- `test_success_resets_reverts_and_simulated_counts_nothing`.
- `test_record_receipt_rejects_unknown_status`.
Démo `circuit_breaker.py` vérifiée : après 3 reverts, `trades_today=5`
(2 réels + 3 reverts comptés), `paused=True`.

---

## Ce qui reste ouvert (hors périmètre des 15 findings)

1. **NonfungiblePositionManager sur Base :** le candidat
   `0x03bfc20f…` n'a PAS de code ; le canonique `0xC36442b4…` a 2 109 octets
   mais son `factory()` eth_call retourne vide (« 0x ») — **à vérifier
   avant toute utilisation** dans un test fork V3 avec positions.
2. **Adaptateur Aerodrome Slipstream absent** du contrat (route.py refuse
   ces routes — c'est le comportement voulu, pas un bug) ; le quoter
   Aerodrome du scan cross-venue ne peut pas adresser les pools
   individuellement (problème de tag de factory) — pré-requis avant tout
   usage live.
3. **Couverture cross-tx 3,99 %** : le 0 du replay ne prouve pas l'absence
   de gaps < 5 s — borne honnête, pas une preuve d'absence.
4. **quoteExactInputSingle sur Base** : revert confirmé avec le bon
   calldata — la fonction reste inutilisable ; quoteExactInput (path)
   est la route qui fonctionne.
5. **Flakiness live** : `test_fee_live_rpc` a échoué une fois sur
   `RemoteDisconnected` (réseau) puis est repassé vert — les tests live
   dépendent du RPC Alchemy (429 possibles).
6. **Aucun commit GitHub fait** — fichiers modifiés non commités (parent).

## Fichiers modifiés (hors leadlag/)

`scanner.py`, `route.py` (nouveau), `executor.py`, `v3_quote.py`,
`math_engine.py`, `self_funded.py`, `sponsor.py`, `zero_cost.py`,
`preflight.py`, `fork_preflight.py` (nouveau), `fork_test_v3.py` (nouveau),
`gas.py`, `circuit_breaker.py`, `test_circuit_breaker.py` (nouveau),
`requirements.txt`, `contracts/FlashLoanArbitrage.sol`,
`contracts/TestToken.sol`, `contracts/TestV3Minter.sol`,
`polygon/realtime_listener.py`, `polygon/test_realtime_listener.py`,
`test_v2.py`, `test_math_engine.py`, `test_morpho.py`, `test_balancer.py`,
`test_sponsor.py`, `test_zero_cost.py`, `test_self_funded.py`,
`test_gas.py`, `test_fork_preflight.py`.
