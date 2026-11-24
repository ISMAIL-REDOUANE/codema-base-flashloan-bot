# V2 CHANGELOG — Bot Flash Loan Base / meme coins sghar

**Date : 2026-11-24. Intégration complète de `ADVANCED_RESEARCH.md` (548 lignes,
recherche profonde GitHub + web) dans le code v1. Simulation seulement —
aucun fond réel, aucune clé privée, aucun broadcast mainnet.**

Règles d'Ismail appliquées : min profit **3 $** partout, sizing mathématique
par opportunité (jamais de taille fixe), simulation avant envoi (0 gas sur
les perdants), système avancé = gagner, ou au moins ne pas perdre.

---

## 1. Fichiers créés (v2)

| Fichier | Rôle |
|---|---|
| `gas.py` | **Correctif finding #4** : gas UNIFIÉ (live RPC + plafond 2 gwei). `fetch_live_gas_price_gwei()`, `gas_cost_usd_from_gwei()`, `gas_ok()`. Stdlib only. |
| `v3_quote.py` | **Amélioration n°1** : quoter V3 on-chain (QuoterV2 `quoteExactInput`, 0xcdca1753) + formule Python mono-tick (liquidité concentrée, largeur de tick par tier). |
| `preflight.py` | **Amélioration n°3** : simulation EVM réelle (`getAmountsOut` on-chain, `eth_estimateGas`, fraîcheur ≤ 2 blocs). Aerodrome Route-based (0x5509a1ac). |
| `circuit_breaker.py` | **Amélioration n°6** : perte max 20 $/jour, 50 trades/jour, 3 reverts → pause 1 h, kill switch, max 2 trades/token/heure, état persisté (`circuit_state.json`). |
| `websocket_listener.py` | **Amélioration n°5** : WebSocket `eth_subscribe` (newHeads + logs pools) + `PollingFallback` documenté comme trop lent post-Denim. |
| `ev_test.py` | **Amélioration n°10** : EV sur 100 opportunités simulées (seed 42, reproductible). |
| `EV_RESULTS.md` | Résultats EV (voir §4). |
| `test_v2.py` | 11 tests v2 (gas, V3, GoPlus, breaker, preflight, EV). |
| `V2_CHANGELOG.md` | Ce fichier. |

## 2. Fichiers modifiés (v2)

| Fichier | Changement |
|---|---|
| `math_engine.py` | `Costs` : gas unifié (défaut 0,0675 $, plus 1,20 $), min profit 3,0 $ par défaut, plafond gas 2 gwei dans `decide()` ; `kelly_fraction_honest()` + borne de Wilson (0,10× si < 30 trades, 0 si 0 trade mesuré). |
| `config.yaml` | `gas_price_max_gwei: 2.0`, `kelly_cap: 0.10`, adresse QuoterV2, `goplus_api` + `require_goplus_pass`, sections `limits:` et `stream:`, min 3 $ partout. |
| `scanner.py` | GoPlus (`fetch_goplus_security`, `vet_token_goplus`, `apply_goplus_to_candidate`) ; `goplus_unknown` = rejet dans `passes_filters()` ; `scan_token(..., goplus_check=True)`. |
| `executor.py` | `run(..., rpc_url, breaker)` : preflight EVM pour chaque EXECUTE (LOSE/STALE/UNAVAILABLE → SKIP), circuit breaker, fraîcheur ≤ 2 blocs. `simulate_evm()` avec détection Aerodrome. |
| `dry_run.py` | Coûts v2 (gas unifié, min 3 $). |
| `test_math_engine.py` | 8 tests (coûts unifiés, gas cap 254 gwei, Kelly honnête). |
| `contracts/FlashLoanArbitrage.sol` | ⛔ Avertissement v2 : NE COMPILE PAS (confirmation requise) ; Aerodrome FAUX dedans (pas d'interface V2) ; minProfit 3 $. Logique de swap inchangée (non vérifiable sans compilation). |
| `requirements.txt` | Cœur stdlib-only documenté ; web3/websockets optionnels (déjà dans `.venv/`). |
| `README.md` | Section Changelog v2 + limites honnêtes + architecture v2. |

## 3. Résultats des tests (vérifiés le 2026-11-24)

```
python3 test_math_engine.py  → 8/8 PASS
python3 test_v2.py           → 11/11 PASS (dont 3 live : gas RPC, quoter V3, preflight)
python3 dry_run.py           → WOULD-EXECUTE +72,68 $ / SKIP 1,11 $ / gas total 0,00 $
python3 ev_test.py           → voir §4
```

**Scénario de référence (spread 20 %, pools 20k/18k $, gas unifié 0,0675 $) :**

| Taille | NET v2 | Verdict |
|---:|---:|---|
| 100 $ | +17,79 $ | WIN |
| 500 $ | +63,36 $ | WIN |
| 2 000 $ | −65,05 $ | LOSS |
| 10 000 $ | −4 485,79 $ | LOSS |
| **790,16 $ (optimale)** | **+72,68 $** | **EXECUTE** |

(En v1, avec gas supposé 1,20 $ : optimale 790 $ → +71,55 $. Même conclusion.)

**Gas cap (finding #4) — testé :** 254 gwei → SKIP (« gas trop cher »),
1,5 gwei → EXECUTE. Plafond 2 gwei.

## 4. EV mesuré — 100 opportunités simulées (seed 42)

| Métrique | Valeur |
|---|---|
| Opportunités | 100 |
| EXECUTE / SKIP | 33 / 67 (dont 4 par plafond gas) |
| Net total | **+1 117,60 $** |
| **EV par opportunité** | **+11,18 $** |
| EV par trade exécuté | +33,87 $ (min +3,17 $, max +311,39 $) |
| Gas total payé (exécutés) | 4,52 $ |
| Max drawdown | 0,00 $ |
| **Verdict** | **GO (modèle)** — voir limites ci-dessous |

**Ce que l'EV prouve :** si les spreads des memes sont distribués comme
supposé (55 % petits 0–3 %, 30 % moyens 3–10 %, 15 % grands 10–30 %) et si
le gas reste sous le plafond, le modèle trouve assez de trades à +3 $
pour que l'EV soit positive.
**Ce qu'elle ne prouve PAS :** le win rate réel est de 100 % PAR
CONSTRUCTION de `decide()` (tout EXECUTE a net > 3 $). En live, une partie
revertera ou sortira perdante (prix qui bouge, MEV, taxes, frais
dynamiques). Le vrai go/no-go exige 100 simulations FORK (preflight
on-chain). Détail : `EV_RESULTS.md`.

## 5. Vérifications LIVE (Base mainnet, lectures seules, 0 gas)

| Vérification | Résultat |
|---|---|
| `eth_gasPrice` live | **0,006 gwei → 0,0081 $** (bloc ~61 793 000, source `rpc_live`) |
| QuoterV2 `quoteExactInput` | **100 USDC → 0,05959 WETH** (fee 500, gas estimé 85 364) — FONCTIONNE |
| QuoterV2 `quoteExactInputSingle` | **REVERT** (2 formes d'appel, fees 500 et 3000, pools existants confirmés via `factory.getPool`) — NE PAS UTILISER sur Base |
| Preflight round-trip USDC→WETH→USDC (Uni V2, 100 $) | **LOSE, net on-chain −0,76 $**, bloc 61 793 161 — attendu (spread naturel ~0 %) |
| GoPlus API (USDC) | Fonctionne (réponse live vérifiée) |
| Polling (3 polls) | Latence moyenne **~350 ms > 200 ms** (bloc Denim) — le polling est trop lent, comme documenté |

## 6. Résultats fork repris de l'agent fork-test (`FORK_TEST_RESULTS.md`)

- **Économie prouvée sur fork Anvil** : spread synthétique 10,41 % →
  loan optimal 8 847,98 $, **NET on-chain +422,39 $** (Python prédisait
  +421,04 $, écart 1,35 $). Gas réel 0,0049 gwei. Revert mesuré : **0,0008 $**.
- **Aave** : prime flash 0,05 % confirmée on-chain ; liquidité USDC dans
  le **aToken aBasUSDC (~13,6 M $)**, pas dans le Pool (123 $).
- **Sushi V2 quasi mort** sur WETH/USDC Base (~2,8k $) — ne pas compter dessus.
- **Aucun vrai meme coin 5k–100k $ avec 2 paires V2 trouvé** dans cet essai
  (GeckoTerminal, 15 pools) — le scanner devra tourner en continu.

## 7. Limites honnêtes — ce que v2 ne fait TOUJOURS PAS

1. **Le contrat NE COMPILE PAS** : `forge install` OpenZeppelin v4.9.6 +
   Aave v3-core bloqué par un contrôle de risque d'exécution. **Confirmation
   explicite d'Ismail requise** avant `forge build`. Sans ça : pas de
   déploiement, pas de test de `executeOperation` / `require(profit >= 3 $)`
   on-chain. (`fork_test.sh` est prêt et attend.)
2. **Aerodrome dans le contrat est FAUX** (prouvé on-chain §7.1 du
   fork-test) : le router Aerodrome n'a pas `swapExactTokensForTokens`
   V2. Le Python (`preflight.py`) gère le Route-based ; le contrat
   Solidity doit être corrigé (adaptateur) AVANT tout déploiement avec
   une jambe Aerodrome. Ne jamais déployer le contrat tel quel sur une
   jambe Aerodrome — il reverterait à chaque fois.
3. **QuoterV2 `quoteExactInputSingle` revert sur Base** (vérifié) — on
   utilise `quoteExactInput` (path 1 hop), qui fonctionne. Cause du
   revert non élucidée : à signaler si on veut utiliser la forme Single.
4. **Slipstream (Aerodrome) et Uniswap V4 non couverts** : quoter V3
   Uniswap seulement ; frais dynamiques Slipstream non modélisés.
5. **RPC public rate-limité** : `mainnet.base.org` renvoie 403 /
   `RemoteDisconnected` sous charge (vu pendant les tests v2, en même
   temps que le fork Anvil). Pour le live : RPC dédié + fallback.
6. **MEV** : pas de mempool privée sur Base ; Flashbots Protect est L1
   only. Protection = atomicité + simulation + minOutput + gas cap.
7. **EV = modèle** (§4) : spreads supposés, pas mesurés sur des pools
   réels ; win rate 100 % par construction. Go/no-go réel = 100
   simulations fork (non faites en v2 — dépend du fork-test).
8. **Latence 200 ms non prouvée** : le `WebSocketListener` est un
   squelette ; aucune mesure d'exécution < 200 ms n'existe. Le polling
   mesuré (~350 ms) est déjà trop lent.
9. **Liquidations Aave / oracle-lag** (recherche §2) : NON implémentés —
   v3, comme scanner passif seulement.
10. **Aucun audit** du contrat, aucun déploiement, aucun fond réel.

## 8. Prochaines étapes (dans l'ordre)

1. Ismail confirme la compilation (`forge install` OpenZeppelin + Aave)
   → `forge build` → `bash fork_test.sh` (preuve contrat on-chain).
2. Corriger le contrat : adaptateur Aerodrome Route-based (ou retirer
   Aerodrome des jambes) ; lire la liquidité Aave via le aToken.
3. RPC dédié Base + 2e RPC en fallback ; ETH sur Base pour le gas.
4. 100 simulations fork (preflight on-chain) sur des memes réels →
   EV réel → go/no-go live.
5. Audit du contrat avant tout déploiement mainnet — non négociable.

---

# v3 — Flash loan 0 frais via Balancer (2026-11-24)

**Demande d'Ismail : « khdem b flash loan ikon 0 fees, bhal Balancer ».**
Détail complet : `BALANCER_RESEARCH.md`. Simulation seulement.

## v3.1 Fichiers créés

| Fichier | Rôle |
|---|---|
| `balancer_flash.py` | Vault `0xBA12…F2C8`, fee 0 % lu on-chain, `select_provider()` (Balancer ≤ 26 604 $ USDC, Aave au-delà), `fetch_vault_balances()`, encodage `vault.flashLoan` (sélecteur `0x5c38449e`, round-trip testé), checks `receiveFlashLoan` (msg.sender == Vault, remboursement amount + fee). |
| `test_balancer.py` | 11 tests v3 (voir §v3.3). |
| `BALANCER_RESEARCH.md` | Recherche vérifiée : Vault, fee 0 %, soldes, alternatives, gain mesuré, limites. |

## v3.2 Fichiers modifiés

| Fichier | Changement |
|---|---|
| `math_engine.py` | `BALANCER_FLASH_FEE = 0.0`, `Costs.flash_provider` (`"aave"` par défaut — tests v1/v2 inchangés), `decide()` retourne `flash_provider` + `flash_fee_rate`. |
| `config.yaml` | Section `flashloan:` (provider préféré/repli, plafond 50 % du Vault, soldes mesurés) + adresses Vault/collector ; `balancer_v3_vault: ""` (non déployé sur Base). |
| `executor.py` | `simulate()` / `run()` choisissent le provider par opportunité ; le preflight utilise le taux du provider choisi (correctif : sinon le net on-chain aurait gardé la prime Aave). `SimulationResult.provider` + `provider_reason`. |
| `contracts/FlashLoanArbitrage.sol` | Squelette `BalancerFlashLoanArbitrage` ajouté (`IFlashLoanRecipient`, `receiveFlashLoan`, remboursement amount + fee). ⛔ NON COMPILÉ, NON AUDITÉ — même blocage `forge install`, confirmation requise. Logique Aave inchangée. |
| `README.md` | Section v3. |
| `V2_CHANGELOG.md` | Cette section v3. |

## v3.3 Résultats des tests (vérifiés le 2026-11-24)

```
python3 test_balancer.py     → 11/11 PASS (dont 2 live : fee 0,00 % lu on-chain,
                               soldes Vault USDC 53 208,01 $ / WETH 39 041,66 $)
python3 test_math_engine.py  → 8/8 PASS (inchangé)
python3 test_v2.py           → 11/11 PASS (inchangé)
python3 dry_run.py           → WOULD-EXECUTE +73,07 $ [provider balancer] /
                               SKIP 1,19 $ / gas total 0,00 $
```

**Comparaison fee 0 % vs 0,05 % (même opportunité, spread 20 %, pools 20k/18k $) :**

| Taille | Aave (net) | Balancer (net) | Gain |
|---:|---:|---:|---:|
| 100 $ | +17,79 $ | +17,84 $ | +0,05 $ |
| 500 $ | +63,36 $ | +63,61 $ | +0,25 $ |
| **790,16 $ (optimale)** | **+72,68 $** | **+73,07 $** | **+0,39 $** |
| 10 000 $ | −4 485,79 $ | −4 480,79 $ | +5,00 $ (reste une perte) |

**Cas fork (loan 8 847,98 $, brut +426,82 $, gas 0,0066 $) :**
Aave +422,39 $ → Balancer **+426,81 $ (+4,42 $)**.

## v3.4 Limites v3 (honnêtes)

1. **Contrat NON compilé** : même blocage `forge install` — confirmation
   explicite d'Ismail requise. Aucun test on-chain de `receiveFlashLoan`.
2. **Le 0 % est un paramètre de gouvernance** : il peut changer. Le bot le
   relit on-chain, et le contrat rembourse `amount + feeAmounts` (jamais
   juste `amount`).
3. **Vault Base petit (~92 k$)** : un loan > 26 604 $ USDC bascule sur Aave ;
   si d'autres bots empruntent en même temps, le solde peut baisser sous le
   loan entre la sélection et le bloc → revert (gas ~0,007 $).
4. **RPC public instable** : `mainnet.base.org` a renvoyé `RemoteDisconnected`
   pendant les tests (soldes illisibles 1 fois sur 2, puis OK). Live = RPC dédié.
5. **Aerodrome dans le contrat Solidity** : toujours faux en V2 — le squelette
   Balancer n'utilise que Uni V2 / Sushi V2.
6. **Balancer V3 absent de Base** ; Morpho 0 % non vérifié on-chain (piste v4).
7. **Deux erreurs d'écriture attrapées par les tests** (corrigées) : un
   sélecteur `getFlashLoanFeePercentage()` initialement faux (0x13e7b9c4 au
   lieu de 0xd877845c — vérifié par keccak) et un décalage d'offset dans le
   décodage du calldata. C'est pour ça qu'on teste l'encodage par round-trip.

# v3.1 — Modèle sponsor : 20 $ de gas, 25 % du net (2026-11-24)

Approuvé par Ismail (« Mzyana dik tari9a dyal sponsor »). Simulation
seulement — aucun fond réel, aucune clé privée, aucun broadcast mainnet.

## v3.1.1 Fichiers créés

| Fichier | Rôle |
|---|---|
| `sponsor.py` | Moteur de partage : `split_profit()` (arrondi au centime, sponsor arrondi, Ismail prend le reste), `record_trade()` (append `trades.jsonl` + déduction gas du prefund + part sponsor du jour), `check_trade()` / `can_trade()` (plafond, prefund, kill switch), `prefund_remaining()` / alerte < 5 $, `load_from_config()` (parseur `sponsorship:` sans PyYAML). |
| `test_sponsor.py` | 12 tests sponsor (partage, plafond, prefund, kill switch, intégration executor/dry-run). |
| `trades.jsonl` | Ledger append-only des trades exécutés (régénéré par `dry_run.py`, flag `simulated: true` en dry-run). |

## v3.1.2 Fichiers modifiés

| Fichier | Changement |
|---|---|
| `config.yaml` | Nouvelle section `sponsorship:` : enabled true, prefund 20 $, part 25 %, `sponsor_wallet: ""` (vide, à remplir), plafond jour 20 $, kill switch false, alerte prefund 5 $, `state_file` / `trades_file`. Chaque champ commenté (français/darija). |
| `executor.py` | `run(..., sponsor=None)` : chaque EXECUTE passe par `check_trade()` — bloqué (plafond/kill switch/prefund) -> SKIP avec raison STOP explicite, 0 $/0 $ ; autorisé -> `record_trade()` (partage + gas déduit du prefund, `simulated=True` en dry_run). Chaque SKIP logue `sponsor 0.00 $ / Ismail 0.00 $`. |
| `dry_run.py` | Crée le ledger depuis `config.yaml`, le passe à `run()`, affiche les totaux sponsor/Ismail + prefund restant, écrit le partage dans `simulation_log.txt` et `trades.jsonl`. |
| `README.md` | Section v3.1 : deal, exemple chiffré, ce que le sponsor doit fournir, auto-financement à 0 %. |

## v3.1.3 Résultats des tests (vérifiés le 2026-11-24)

```
python3 test_sponsor.py     → 12/12 PASS
python3 test_math_engine.py → 8/8 PASS (inchangé)
python3 test_v2.py          → 11/11 PASS (inchangé)
python3 test_balancer.py    → 11/11 PASS (inchangé)
python3 dry_run.py          → WOULD-EXECUTE +73,07 $ [sponsor 18,27 $ / Ismail 54,80 $]
                              / SKIP 1,19 $ [sponsor 0,00 $ / Ismail 0,00 $] / gas total 0,00 $
```

**Exemples numériques vérifiés :** net 100 $ → sponsor 25 $ / Ismail 75 $ ;
net 0 $ → 0 $ / 0 $ ; net 73,07 $ (cas Balancer) → **sponsor 18,27 $ /
Ismail 54,80 $**. Plafond : 5 trades à 16 $ de net (4 $ de part chacun =
20 $) → le 6e est **bloqué** avec raison STOP, rien n'est ajouté.
Prefund : gas 15,50 $ dépensé → reste 4,50 $ → **alerte** ; gas 20 $ →
reste 0 $ → **blocage**. Kill switch → tous les trades bloqués.

## v3.1.4 Ce que le sponsor doit encore fournir

1. **Son adresse wallet** (`sponsor_wallet` dans `config.yaml` — vide pour
   l'instant) : c'est là que sa part de 25 % sera versée en live.
2. **~20 $ d'ETH de prefund** sur Base (que pour le gas).
3. Rien d'autre : pas de clé privée, pas de contrôle du bot — le bot ne
   trade jamais au-delà du plafond journalier de 20 $ convenu.

**Alternative** : Ismail s'auto-finance (`sponsor_share_pct: 0` dans
config.yaml) → 100 % du profit pour lui, le prefund reste le sien.

## v3.1.5 Limites honnêtes

- Le partage est calculé sur le net **simulé** en dry-run : en live, seul
  le net **réel** (on-chain) sera partagé — le flag `simulated` dans
  `trades.jsonl` distingue les deux, pour que le sponsor ne confonde
  jamais une simulation avec de l'argent dû.
- Le versement réel de la part sponsor (transfert on-chain vers
  `sponsor_wallet`) n'est PAS implémenté : en v3.1, le bot ne fait que
  calculer et journaliser ce qui est dû. Le paiement live est une étape
  v4, après audit.
- Le prefund gas en live est une hypothèse de 20 $ : si le gas réel
  dépasse durablement ~0,008 $/trade, le prefund s'épuisera plus vite et
  l'alerte < 5 $ se déclenchera plus tôt — c'est son rôle.

## v3.2 Mode $0 TOTAL (2026-11-24, exigence d'Ismail : « mnkhls wlo, 0$ »)

### Fichiers créés / changés
- **Créé** `zero_cost.py` — `ZeroCostGuard` : `check_zero_cost()` (ALLOW/BLOCK
  avec raison), `charge_ismail()` (kill switch dès 0,01 $), `ismail_paid_usd`
  (doit rester 0,00 $), `append_ledger()`, `load_from_config()`,
  `trade_from_result()`.
- **Créé** `test_zero_cost.py` — 15 tests.
- **Changé** `config.yaml` — section `zero_cost:` : `enabled: true`,
  `ismail_pays_usd_max: 0.0` (contrainte DURE), `allowed_flash_providers:
  ["balancer"]` (Aave BLOQUÉ en mode $0), `rpc: "alchemy-free"`,
  `gas_payer: "sponsor"` (repli `cdp-credits`, approbation en attente),
  `infra_cost_usd: 0.0`.
- **Changé** `executor.py` — `run(..., zero_cost=None)` : chaque EXECUTE passe
  par le garde $0 AVANT tout enregistrement ; bloqué → SKIP `ZERO_COST: ...`,
  rien n'est enregistré ; autorisé → la ligne `trades.jsonl` porte
  `ismail_paid_usd` (0,00 $) et `zero_cost: true`.
- **Changé** `sponsor.py` — `record_trade(..., extra=None)` : le gas est
  déduit du prefund sponsor UNIQUEMENT ; chaque entrée porte
  `ismail_paid_usd: 0.0` (jamais d'Ismail).
- **Changé** `dry_run.py` — charge le garde $0, l'affiche :
  `ZERO-COST : Ismail a payé 0.00 $ (max 0.00 $)`.
- **Changé** `README.md` — tableau des coûts « $0 TOTAL » (voir ci-dessous).

### Tableau des coûts — qui paie quoi ?

| Coût | Qui paie ? | Solution $0 | Statut |
|---|---|---|---|
| Prime flash loan | Personne (Balancer 0 %) | Vault Balancer, fee 0 % on-chain ; Aave BLOQUÉ | ✅ |
| Gas (gagnants) | Sponsor (prefund 20 $) | ~0,008 $/trade ; repli crédits CDP 1 000 $ en attente | ✅ |
| Gas (perdants) | 0 $ — SKIPPÉS avant broadcast | Simulation + preflight | ✅ |
| Gas (revert) | Sponsor, max 0,33 $ au plafond 2 gwei | Circuit breaker après 3 reverts ; mesuré 0,0046 $ en fork | ⚠️ résiduel plafonné, jamais Ismail |
| RPC Base | 0 $ | Alchemy free tier (Base-Bot) | ✅ |
| Infra | 0 $ | Muse / Foundry / Anvil / GitHub gratuits | ✅ |
| Audit professionnel payant | — | AUCUNE solution $0 aujourd'hui | ⛔ live bloqué tant que non financé |

### Tests (2026-11-24)
```
python3 test_zero_cost.py   → 15/15 PASS
python3 test_math_engine.py → 8/8 PASS (inchangé)
python3 test_v2.py          → 11/11 PASS (inchangé — une AssertionError
                              transitoire sur un test live RPC public
                              RemoteDisconnected, re-run propre : 11/11)
python3 test_balancer.py    → 11/11 PASS (inchangé)
python3 test_sponsor.py     → 12/12 PASS (inchangé)
python3 dry_run.py          → WOULD-EXECUTE +73,07 $ [sponsor 18,27 $ / Ismail 54,80 $]
                              / SKIP 1,19 $ / gas total 0,00 $
                              ZERO-COST : Ismail a payé 0.00 $ (max 0.00 $)
```

**Preuves vérifiées :** Balancer autorisé / Aave bloqué en mode $0 ;
gas > prefund sponsor bloqué ; crédits CDP en attente bloqués (approuvés →
autorisés) ; kill switch sur une charge de 0,01 $ à Ismail ; 20 trades
(10 gagnants / 10 perdants) → `ismail_paid_usd` = **0,00 $** et les 10
lignes `trades.jsonl` le prouvent une par une.

### v3.2.1 Le seul trou honnête : l'audit payant
Un audit professionnel coûte de l'argent et il n'existe pas de solution
$0 pour lui aujourd'hui (Slither/Aderyn gratuits + revue manuelle en
attendant). **Le live reste donc BLOQUÉ** tant que l'audit n'est pas
financé — par le sponsor, ou par les profits futurs du bot une fois
l'audit... ce qui est un cercle : on ne peut pas gagner sans live, et on
ne peut pas aller en live sans audit. Les deux sorties réalistes : (1) le
sponsor finance l'audit ; (2) on reste en simulation jusqu'à trouver un
audit gratuit/bounty (concours d'audit, audit communautaire) — aucune des
deux n'est promise ici.

---

# v3.3 — Balancer mort (BIP-928) → Morpho Blue, flash loan 0 frais (2026-11-24)

**Balancer a été liquidé (wind-down BIP-928, 30 oct 2026)** : pools en
retraits seuls, bug bounty terminé, Balancer Labs dissoute. Le Vault
`0xBA12…F2C8` ne doit plus être utilisé. Le remplaçant est **Morpho Blue**
— même fee 0 %, mais par conception (pas un paramètre de gouvernance)
et liquidité ~3 500× plus grande. Simulation seulement — aucun fond réel,
aucune clé privée, aucun broadcast mainnet.

## v3.3.1 Fichiers créés

| Fichier | Rôle |
|---|---|
| `morpho_flash.py` | Morpho `0xBBBB…FFCb`, fee 0 % structurel (pas de getter `flashFee` — revert vérifié), `select_provider()` (Morpho ≤ 50 % du solde, Aave au-delà), `fetch_morpho_balances()`, `verify_no_flash_fee_getter()`, encodage `flashLoan(token, assets, data)` (sélecteur `0xe0232b42`, round-trip testé), checks `onMorphoFlashLoan` (msg.sender == Morpho, montant décodé == assets, remboursement = assets exactement). |
| `test_morpho.py` | 12 tests v3.3 (voir §v3.3.3). |
| `fork_test_morpho.py` / `fork_test_morpho.sh` | Preuve fork Morpho (miroir du §10 Aave) ; RPC lu dans `config.yaml`, jamais affiché ni logué. |
| `fork_results_morpho.json` | Résultats machine du run canonique (§11). |

## v3.3.2 Fichiers modifiés

| Fichier | Changement |
|---|---|
| `math_engine.py` | `MORPHO_FLASH_FEE = 0.0`, `Costs.flash_provider` accepte `"morpho"` (taux forcé à 0) ; `"balancer"` conservé dans `FLASH_FEE_BY_PROVIDER` pour compat historique seulement — l'executor ne le sélectionne plus. |
| `config.yaml` | Section `flashloan:` : provider préféré `morpho`, repli `aave`, `morpho_fee_rate: 0.0`, soldes mesurés Morpho bloc 61 806 974 (USDC 328 711 525,75 $ / WETH 88 713,53) ; `balancer_vault` commenté comme déprécié ; `zero_cost.allowed_flash_providers: ["morpho"]`. |
| `executor.py` | `simulate()` / `run()` choisissent le provider via `morpho_flash` (Morpho 0 % / Aave 0,05 %) ; soldes live Morpho lus avec `rpc_url`. |
| `zero_cost.py` | `ALLOWED_PROVIDERS_DEFAULT = ("morpho",)` ; messages « seule Morpho 0 % est autorisée » ; `load_from_config` défaut `morpho`. |
| `balancer_flash.py` | Marqué DÉPRÉCIÉ en tête de fichier (BIP-928) — conservé pour référence, non supprimé. |
| `contracts/FlashLoanArbitrage.sol` | `MorphoFlashLoanArbitrage` ajouté (`IMorpho` + `IMorphoFlashLoanCallback`, `onMorphoFlashLoan(uint256 assets, bytes calldata data)`, remboursement `approve(Morpho, assets)` exact, minProfit 3 $). `forge build` OK (exit 0). Squelette Balancer marqué déprécié + bug latent documenté (`nonReentrant` sur le callback — voir §v3.3.4). Aerodrome toujours faux (pas d'interface V2) — jambes Uni V2 / BaseSwap V2 seulement. |
| `test_balancer.py` | 11 tests conservés (module déprécié, référence historique) ; en-tête de dépréciation ; test executor mis à jour : le routage actuel est Morpho (MEME-WIN +73,07 $, MEME-BIG 50 000 $ via Morpho — ex-Balancer -> Aave). |
| `test_zero_cost.py` | Références Balancer → Morpho (`_morpho_trade`, `test_morpho_allowed`, provider `"morpho"`, allow-list `("morpho",)`) — mêmes assertions $0. |
| `dry_run.py` | Docstring / message de repli : Morpho au lieu de Balancer. |
| `RESEARCH.md` | Nouvelle section Morpho Blue (adresse, signatures, fee 0 structurel, soldes, TVL 3,336 Md$, sources) + ligne dans le tableau des adresses. |
| `BALANCER_RESEARCH.md` | Correction wind-down en tête de fichier (BIP-928, 30 oct 2026). |
| `FORK_TEST_RESULTS.md` | Nouvelle section §11 (preuve fork Morpho) + lignes Morpho/Balancer dans le tableau §0. |
| `README.md` | Section v3.3 ; v3 marquée dépréciée ; tableau des coûts $0 : Morpho. |

## v3.3.3 Résultats des tests (vérifiés le 2026-11-24)

```
python3 test_morpho.py       → 12/12 PASS (dont 2 live : pas de getter flashFee,
                               soldes Morpho USDC 328,7 M$ / WETH ~88 714,
                               + preuve fork WIN +17,58 $)
python3 test_math_engine.py  → 8/8 PASS (inchangé)
python3 test_v2.py           → 11/11 PASS (inchangé)
python3 test_balancer.py     → 11/11 PASS (module déprécié, routage Morpho)
python3 test_sponsor.py      → 12/12 PASS (inchangé)
python3 test_zero_cost.py    → 15/15 PASS (allow-list Morpho)
python3 dry_run.py           → WOULD-EXECUTE +73,07 $ [provider morpho] /
                               SKIP 1,19 $ / gas total 0,00 $
                               ZERO-COST : Ismail a payé 0.00 $ (max 0.00 $)
```

**Comparaison fee 0 % vs 0,05 % (même opportunité, spread 20 %, pools 20k/18k $) :**
identique à v3 (Morpho remplace Balancer chiffre pour chiffre) —
optimale 790,16 $ : Aave +72,68 $ → Morpho **+73,07 $ (+0,39 $)** ;
cas fork 8 847,98 $ : Aave +422,39 $ → Morpho **+426,81 $ (+4,42 $)**.

**Preuve fork Morpho (§11, bloc 61 807 834) :** spread synthétique
10,236 % → loan optimal 366,50 $ → **WIN +17,58 $** (gas 0,0042 $) ;
perdant SKIP 0 $ + revert confirmé (0,0040 $).

## v3.3.4 Bug trouvé et corrigé (leçon)

Premier run fork : revert `ReentrancyGuard: reentrant call` sur
`estimate_gas`. Cause : `nonReentrant` à la fois sur `executeArbitrage`
et sur le callback `onMorphoFlashLoan` — or le callback est appelé
depuis `executeArbitrage` via Morpho, dans le même cadre : le 2e garde
reverte. Fix : pas de `nonReentrant` sur le callback (protection =
`msg.sender == MORPHO`). Le squelette Balancer a le même bug latent —
documenté, non réparé (Balancer mort).

## v3.3.5 Limites v3.3 (honnêtes)

1. **Contrat NON AUDITÉ** : audit obligatoire avant tout déploiement
   mainnet (non négociable).
2. **Aerodrome dans le contrat Solidity** : toujours faux en V2 — jambes
   Uni V2 / BaseSwap V2 seulement, ou adaptateur Route-based à écrire.
3. **Aucun vrai meme coin testé** : la preuve utilise WETH/USDC avec
   spread synthétique ; le scanner doit trouver un vrai meme 5k–100k $
   avec spread réel sur 2 DEXs.
4. Un test Morpho live a échoué une fois sur un run (RPC public
   `mainnet.base.org` instable, `RemoteDisconnected`) puis passé aux
   re-runs : le RPC public est fragile — live = RPC dédié + fallback.
5. Les soldes Morpho mesurés (bloc 61 806 974) sont datés : avec un RPC,
   `fetch_morpho_balances()` les remplace par les soldes live.

# v3.4 — Gas autofinancé : Ismail paie le gas (~20 $ float), garde 100 % (2026-11-24)

Décision d'Ismail (2026-11-24 21:47) : « Flblan lwel o ana an7at flous
dyal l gas » — Plan 1 (CDP 15 k$, produit + application) ET il finance
le gas lui-même. Contrainte « 0 $ total » levée pour le **GAS
SEULEMENT** ; prime flash loan 0 % (Morpho uniquement). La section
`sponsorship:` est INACTIVE (`enabled: false`, part 0 %).

## v3.4.1 Fichiers créés / changés

- **CRÉÉ `self_funded.py`** : `FloatLedger` — float 20 $, `ismail_paid_usd`
  (gas dépensé), `profits_usd`, `float_remaining_usd` ; `can_afford`
  (bloque si pire cas = gas + budget revert > float) ; kill switch à
  0 $ (réarmé par `top_up`) ; `split_profit` 0/100 ; `record_trade`
  (entrées `funding_mode: "self_funded"`) ; `load_from_config` (lit
  `funding:`) ; `float_status_line()` ; `status()` sans effet de bord.
- **CRÉÉ `test_self_funded.py`** : 16 tests (voir § v3.4.3).
- **`config.yaml`** : nouvelle section `funding:` (payer "ismail",
  float_usd 20.0, sponsor_share_pct 0, gas_payer "ismail",
  min_profit_usd 3.0, low_float_alert_usd 5.0, state_file
  "float_state.json", trades_file "trades.jsonl") ; `sponsorship:`
  marquée INACTIVE (`enabled: false`, part 0 %).
- **`zero_cost.py`** : interrupteur de mode (`mode` = "zero_cost" ou
  "self_funded", défaut "zero_cost" dans la classe, "self_funded" lu
  depuis `config.yaml` quand `funding.payer == "ismail"`) ; branche
  `_check_self_funded` (gas Ismail depuis le float, pire cas, net
  >= min 3 $ après gas, Morpho seul, aucun coût hors-gas) ;
  `trade_from_result` étendu (float_remaining_usd, min_profit_usd,
  revert_budget_usd) ; `status()` inclut le mode. Section `zero_cost:`
  de la config **inchangée** (mode $0 historique conservé).
- **`sponsor.py`** : `split_profit` sur ledger désactivé retourne
  (0, net) — Ismail 100 % (jamais 0/0 par erreur) ; champ
  `funding_mode` porté dans les entrées et `status()` ;
  `load_from_config` déduit `funding_mode` de `enabled`.
- **`executor.py`** : paramètre `funding=None` — pas de check sponsor,
  pas de plafond sponsor ; le garde bascule en mode "self_funded" ;
  enregistrement dans le FloatLedger (une seule ligne par EXECUTE, gas
  SIMULÉ `r.gas_usd` déduit — `gas_paid_usd` vaut 0,00 $ sans
  broadcast) ; sans garde, `can_afford` reste le garde-fou.
- **`dry_run.py`** : mode autofinancé par défaut (FloatLedger +
  garde self_funded, sponsor None) ; imprime la ligne
  `FINANCEMENT : Ismail — float 20.00 $ / dépensé 0.00 $ / restant
  20.00 $ / profit 0.00 $` ; totaux via `funding.split_profit`.
- **`test_sponsor.py`** : `test_load_from_config` mis à jour
  (`enabled: false`, part 0,0 %, `funding_mode: "self_funded"`) —
  reflète la config v3.4 délibérée, PAS une régression (les autres
  tests sponsor sont intacts).

## v3.4.2 Résultats des tests (vérifiés le 2026-11-24)

Toutes les suites passent (85/85) :

| Suite | Résultat |
|---|---|
| test_math_engine.py | 8/8 |
| test_v2.py | 11/11 |
| test_balancer.py | 11/11 (module déprécié conservé) |
| test_sponsor.py | 12/12 |
| test_zero_cost.py | 15/15 (section `zero_cost:` inchangée) |
| test_morpho.py | 12/12 |
| **test_self_funded.py** | **16/16** |

`test_self_funded.py` couvre : config `funding:` ; bascule de mode du
garde depuis la config ; split 100/0 (FloatLedger + SponsorLedger part
0 % + ledger désactivé) ; comptabilité sur 20 trades (10 gagnants +
5 reverts + 5 SKIP jamais enregistrés : dépensé 1,05 $, restant
18,95 $, profit 730,70 $) ; blocage float épuisé ; kill switch à 0 $
(réarmé par recharge) ; Morpho seul + Aave bloqué (garde et executor) ;
min-profit 3 $ après gas (2,50 $ et 3,00 $ bloqués, 3,01 $ autorisé) ;
gas payé par Ismail autorisé avec float, bloqué sans float, gas sponsor
refusé en mode autofinancé ; intégration executor de bout en bout
(EXECUTE Morpho +73,07 $, 1 seule ligne trades.jsonl taguée
`funding_mode: "self_funded"`, float 19,93 $).

Dry-run v3.4 vérifié : WOULD-EXECUTE MEME-WIN +73,07 $ [provider
morpho] / SKIP MEME-LOSE 1,19 $ / gas payé 0,00 $ ;
`FINANCEMENT : Ismail — float 20.00 $ / dépensé 0.07 $ / restant
19.93 $ / profit 73.07 $`.

## v3.4.3 Le float de 20 $ — combien de trades ?

| Coût gas / trade | Trades couverts | Avec budget revert (pire cas) |
|---|---|---|
| ~0,005 $ (mesuré en fork, 0,0049 gwei) | ~4 000 | ~2 000 |
| 0,0675 $ (modèle Costs, 450 000 unités × 0,05 gwei × 3 000 $) | ~296 | ~148 |
| 2,70 $ (plafond 2 gwei) | 7 | 3 |

Au rythme estimé de 0–3 opportunités ≥ 3 $/semaine, le float de 20 $
dure des mois. Le profit est en USDC, le gas en ETH : le profit ne
recharge PAS le float — recharge manuelle quand il approche de 5 $
(alerte).

## v3.4.4 Limites v3.4 (honnêtes)

1. **Contrat NON AUDITÉ** : audit obligatoire avant tout déploiement
   mainnet (non négociable).
2. **Adresse publique d'Ismail + float ~20 $ ETH sur Base toujours
   manquants** — à fournir par Ismail (adresse publique seulement,
   jamais de clé privée).
3. **Aerodrome dans le contrat Solidity** : toujours faux en V2.
4. **Aucun vrai meme coin testé** : preuves WETH/USDC, spread synthétique.
5. Plan 1 CDP 15 k$ (produit + application) : travail non commencé —
   reframing produit (site + Base Account/Smart Wallet + démo +
   politique gas) à lancer avec le feu vert d'Ismail.

# v4.0 — Port Polygon (2026-11-24, ~22:20 UTC)

Décision d'Ismail : travailler uniquement avec ses 1,31 $ MATIC sur
Polygon (17,2743 MATIC), flash loan 0 frais obligatoire. Le bot Base est
intact ; le port vit dans `polygon/`.

## v4.0.1 Fichiers créés (polygon/)

- `POLYGON_FLASH_VERIFICATION.md` — Phase 1 : Morpho Blue Polygon vérifié
  0 frais (`0x1bF0c2541F820E775182832f06c0B7Fc27A25f67`, code 15 582 o,
  `flashFee` absent, soldes USDC 112 261 $ / USDT 122 030 $ / WMATIC
  1 000 246, bloc 97 901 631) ; V4 flash accounting vérifié (PoolManager
  `0x67366782…`, non implémenté) ; Aave 0,05 % (repli payant, bloqué) ;
  Balancer mort, dYdX mort. **Deux pièges évités** : l'adresse canonique
  `0xBBBB…` n'a pas de code sur Polygon ; le SwapRouter02 Polygon
  n'expose pas `exactInputSingle` (voir v4.0.3).
- `polygon_config.yaml` — chaîne 137, RPC drpc.org (+ fallbacks),
  MATIC 0,0758 $, gas live 279 gwei, cap 1 000 gwei, min profit 3 $,
  float 17,2743 MATIC = 1,31 $, Morpho 0 frais seul en allow-list.
- `contracts/FlashLoanArbitragePolygon.sol` + `foundry.toml` —
  Morpho Polygon + QuickSwap V2 (achat) + **Uni V3 directe** (`pool.swap`
  + callback, pool `0x2DB87C…`) ; minProfit 3 $ ; `forge build` exit 0,
  bytecode 5 661 o.
- `polygon_flash.py`, `polygon_gas.py`, `polygon_ledger.py`,
  `scanner_polygon.py`, `fork_test_polygon.py` / `fork_test_polygon.sh`,
  `test_polygon.py` — port complet (0 frais, gas, float, scan, fork, tests).
- `FORK_TEST_RESULTS_POLYGON.md` — fork bloc 97 902 229 (détail § v4.0.2).
- `MEME_POOLS_LIVE_POLYGON.md` — scan live 2026-11-24 ~22:25 UTC.

## v4.0.2 Résultats fork Polygon (vérifiés 2026-11-24)

- Spread synthétique 21,0 % (vente de 10 % de la réserve QuickSwap :
  QS 0,0627 $ vs V3 0,0759 $ ; spread naturel 0,03 %).
- Décision off-chain : EXECUTE, loan optimal 50,22 $, net attendu 4,83 $.
- **Cas gagnant (broadcast fork) : WIN net +4,83 $** — profit brut 4,84 $,
  gas 268 626 @ 136,58 gwei = 0,03669 MATIC = 0,002781 $.
- **Cas perdant : SKIP 0 $** (net attendu −0,01 $) ; revert mesuré sur le
  fork 0,031366 MATIC = 0,002378 $ (raison : `pas de quoi rembourser
  le loan`).
- Float 1,31 $ : ~137 trades au coût prudent (0,0095 $/trade), ~68 pire
  cas, 235 au coût mesuré fork. Kill switch à 0 $.

## v4.0.3 Leçon de debug — la jambe V3 (correction majeure)

La v1 du contrat utilisait le SwapRouter02 + `exactInputSingle` (comme
Base). Le fork revert avec données vides ; `debug_traceCall` a montré
que le CALL au router revert **sans aucun sous-appel** ; vérification
bytecode : sélecteur `exactInputSingle` (0x414bf389) **absent** du code
déployé, test EOA direct confirme. La paire Sushi V2 USDC/WMATIC est
vide (~12 $). **Correctif : vente V3 en appel direct à la pool**
(`pool.swap` + `uniswapV3SwapCallback`), `sqrtPriceLimitX96 =
4295128740` (MIN_SQRT_RATIO + 1 — la valeur 0 est rejetée par la pool).
C'est cette version qui a produit le WIN. Config + doc de vérification
corrigées en conséquence.

## v4.0.4 Scan live Polygon (vérifié 2026-11-24 ~22:25 UTC)

80 pools récentes lues (GeckoTerminal `polygon_pos`, pages 1–4 ; page 5
= HTTP 429 rate limit) ; **0 candidat** (liq 5 k–100 k $, < 72 h),
**0 paire 2-venues**. Max liquidité vue : 984 227,83 $ (1 pool hors
plafond). Toutes les 80 rejetées pré-filtre pour liquidité hors
fenêtre (ex. 27,92 $, 0 $, 1,35 $, 33,99 $). Le filtre est correct et
les rejets sont journalisés — c'est l'état du marché, pas un bug.
**Aucun arbitrage meme 2-DEX sur Polygon en ce moment** ; scan à
relancer toutes les 2–4 h.

## v4.0.5 Corrections arithmétiques (2 erreurs ×1000 attrapées par les tests)

1. Soldes Morpho Polygon d'abord surévalués 1000× (USDC 112 261 $ et non
   113,7 M$ — confusion unités brutes/1e6). Corrigé partout.
2. Coût gas Polygon d'abord sous-évalué 1000× (formule) : réel
   450 000 gas × 279 gwei = 0,12555 MATIC ≈ **0,0095 $/trade** — le gas
   Polygon coûte ~2× celui de Base en $, pas « quasi gratuit ».
   Corrigé dans `polygon_gas.py`, `polygon_ledger.py`, config, tests.
   Bonus : le helper RPC `_rpc` passait par urllib (IncompleteRead +
   308 fantôme sur les grosses réponses chunkées de drpc) — réécrit
   avec `requests` ; le test live passe maintenant (20/20, 0 skipped).

## v4.0.6 Résultats des tests (vérifiés 2026-11-24 ~22:25 UTC)

- `polygon/test_polygon.py` : **20/20** (0 frais, gas, math, float,
  kill switch, min-profit 3 $, contrat compilé, config, live RPC).
- Base inchangée : math 8/8, v2 11/11, balancer 11/11, morpho 12/12,
  sponsor 12/12, $0 15/15, self_funded 16/16.

## v4.0.7 Ce qui manque encore (avant tout live)

Paper-trade Amoy 2–4 semaines + audit payant (aucune solution 0 $) ;
aucun vrai meme coin testé (preuves WETH/USDC + spread synthétique) ;
100 simulations fork non lancées ; jambe Aerodrome toujours cassée sur
Base ; payout sponsor on-chain non implémenté (Base v4, après audit).

# v4.1 — Règle net > 0 $ + grosses pools + triangle + watchlist memes (2026-11-24 ~22:43–23:20 UTC)

## v4.1.1 Changement de règle (Ismail) : min 3 $ abandonné sur Polygon

Nouvelle règle : EXECUTE ssi net simulé **> 0 $ après TOUS les coûts**
— flash 0 % (Morpho), frais de swap (dans les quotes), gas du trade
**et budget revert** (pire cas : gas + gas de revert ; coût total
budgété = 2 × gas). `polygon_guard.py` (nouveau) : `polygon_costs()`
(gas_usd = 2 × gas, min_profit 0.0, gas_multiple 0.0),
`polygon_decide()` (enveloppe `decide()` de Base, inchangé), `tranche()`
/ `tranche_counts()` (>0$ / ≥0,50$ / ≥3$ / ≤0$).
- `polygon_config.yaml` : min_profit_usd 3,0 → 0,0 (math/executor/
  funding), `revert_budget_multiple: 1.0`, `gas_multiple: 3.0 → 0.0`.
- Contrat `FlashLoanArbitragePolygon.sol` : minProfit on-chain **0,01 $**
  (plancher anti-poussière, justification : éviter les trades de
  poussière dont le profit est inférieur aux erreurs d'arrondi ; le
  garde off-chain fait le vrai calcul).
- `polygon_ledger.py` : MIN_PROFIT_USD = 0,0.
- `fork_test_polygon.py` : section 6b (petit net) — simulation de
  fractions poussées, choix de celle dont le net attendu est le plus
  proche de 0,50 $ ; déploiement avec minProfit 0,01 $ vérifié
  on-chain (`minProfit() == 10000`).
- **Preuve fork (bloc 97 903 345) :** WIN +4,78 $ (loan 49,52 $, gas
  0,0028 $) ; **petit net WIN +0,50 $** (loan 16,66 $, attendu 0,49 $,
  tranche ≥0,50$ — aurait été SKIP à l'ancienne barre de 3 $) ;
  perdant SKIP (net −0,01 $), revert confirmé on-chain 0,0014 $.
  Détail : `polygon/FORK_TEST_RESULTS_POLYGON.md` § v4.1.
- Le bot **Base garde min 3 $** (fichiers Base non touchés).

## v4.1.2 Grosses pools — verdict MONITOR-ONLY

Priorité d'Ismail : les grosses pools auraient moins de concurrence sur
Polygon. `polygon/big_pools.py` (lecture seule) : 7 paires majors,
venues découvertes live DexScreener (top 6, liq ≥ 10 k $), classées
on-chain (V2 / Uni V3 / Algebra), quotes QuoterV2 / getAmountsOut /
réserves virtuelles, tailles 1 000 $ / 5 000 $ / 20 000 $, net via
`polygon_guard` (tranches rapportées).
- **6 échantillons (22:51–23:18 UTC), 126 mesures : toutes négatives.**
  Échantillons corrigés (Algebra incluses, blocs 97 903 998 /
  97 904 286 / 97 904 555) : **63 mesures, 0 net > 0 $**, meilleur spread **−0,014 %**
  (USDC.e/DAI, 1 000 $), meilleur net −0,02 $ partout. Meilleur achat
  et meilleure vente souvent la **même venue** (marché aligné).
- Bugs trouvés et corrigés en cours de route : (1) pairAddress Balancer
  composite (« pool-tokens », pas une adresse) faisait planter web3
  via le chemin ENS → Balancer exclu + `Web3.is_address` défensif ;
  (2) `TOKENS[adresse]` + dépaquetage 3-tuple excluaient silencieusement
  les venues Algebra et les V2 sans router — les 3 premiers échantillons
  sont supplantés (`big_pools_samples_superseded_pre-algebra-fix.jsonl`).
- Détail : `polygon/BIG_POOLS_POLYGON.md`, bruts `big_pools_samples.jsonl`.

## v4.1.3 Triangle — verdict MONITOR-ONLY

`polygon/triangle_detector.py` (lecture seule — **aucun code de
broadcast**, vérifié statiquement par les tests) : 3 triples de grosses
pools × 2 sens × 3 tailles, chaque jambe cotée on-chain sur la meilleure
venue (le montant d'entrée = sortie réelle de la jambe précédente),
frais sur chaque jambe, gas budgété 600 000 unités + budget revert.
- **3 échantillons (22:57 / 23:01 / 23:09 UTC, blocs 97 903 718 /
  97 903 868 / 97 904 182), 54 évaluations : 0 net > 0 $.** Meilleur net
  **−4,19 $** (WMATIC → WETH → USDT → WMATIC, 1 000 $) ; pire −2 449 $
  (20 000 $). La perte croît avec la taille (impact AMM) : 0,5–1,3 % à
  1 000 $, 6–12 % à 20 000 $. Prior « textbook-only » confirmé.
- Conditions de passage en exécutable (non remplies) : net > 0 $ répété
  + preuve fork WIN + mêmes guards (kill switch, float ledger, max 10 %).
- Détail : `polygon/TRIANGLE_EVALUATION.md`, bruts `triangle_samples.jsonl`.

## v4.1.4 Memes — watchlist persistante, 0 opportunité

`polygon/watchlist.py` + `watchlist_run.py` (agent dédié, vérifié) :
store JSON persistant (venues, liquidité, first-seen, re-vérification
d'une 2e venue à chaque run), 2e source DexScreener
(`token-profiles/latest`), tier WATCH (1 k–500 k $, < 7 j, suivi sans
exécuter) + tier EXEC inchangé (5 k–100 k $, < 72 h, spread ≥ 3 %),
backoff 429 avec pages skippées journalisées, runner re-scan 2–4 h.
- **Run 22:55 UTC : 100 pools GeckoTerminal lues (pages 1–5 ; page 6
  skippée sur 429 persistant malgré 4 tentatives), 0 profil DexScreener
  Polygon (flux du moment 100 % Solana), 96 tokens vérifiés → watchlist
  96 (exec 0 / watch 4 / none 92), 5 paires à 2 venues (FUL, Rp,
  VOLLAR, COMP, axlUSDC — tous vieux tokens / stable, tier none),
  4 en watch (SWCH, GRIPS, VENUE, XFROG — 1 venue chacun),
  0 opportunité exec.** Distribution net : >0$ 0 | ≥0,50$ 0 | ≥3$ 0.
- Bugs corrigés pendant le run : préfixe `polygon_pos_0x…` invalide
  pour DexScreener ; même DEX compté 2 fois (labels Gecko vs
  DexScreener) → normalisation + déduplication par adresse de paire.
- Détail : `polygon/MEME_POOLS_LIVE_POLYGON.md`,
  `watchlist_scan_2026-11-24_2255.json`, `watchlist_runs.jsonl`.

## v4.1.5 Résultats des tests (vérifiés le 2026-11-24 ~23:20 UTC)

- `test_polygon.py` : **25/25** (était 20/20 ; + garde v4.1, petit net
  +0,50 $ autorisé, 0,00 $ / négatif bloqués, tranches).
- `test_watchlist.py` : **31/31** (2e venue détectée, watch jamais
  exécuté, backoff 429, bornes des tiers, net +0,50 $ autorisé).
- `test_big_pools_triangle.py` : **21/21** (math triangle pure, frais
  par jambe, gas + revert, tranches, MONITOR-ONLY statique, filtres
  DexScreener, classification).
- **Polygon total (périmètre v4.1) : 77/77.** Base inchangée 85/85 (math 8/8, v2 11/11,
  balancer 11/11, morpho 12/12, sponsor 12/12, $0 15/15, self_funded
  16/16) — fichiers Base non touchés, `amoy_papertrade/` non touché.
  (Avec les 22 tests v4.2 revert-protection, le total Polygon est 99/99 ;
  voir § v4.2 pour le chiffre combiné de l'agent revert.)

## v4.2 Protection revert Polygon — verdict honnête (2026-11-24 ~22:50 UTC)

Demande d'Ismail : « mbritch nkhser dak l gas » — le revert doit coûter
0 $. Vérifié (docs officielles + checks live) : **aucun service ne
donne 0 $ sur un revert ON-CHAIN sur Polygon aujourd'hui.**
- MEV Blocker `/noreverts` (simulation + drop avant inclusion) existe
  mais **Ethereum seulement** (docs : « All features are supported on
  Ethereum ») — endpoint `rpc.mevblocker.io/noreverts` sans réponse
  exploitable depuis le sandbox ; même constat Flashbots Protect.
- FastLane Atlas (Polygon) : **« No Free Reverts »** (blog officiel) +
  framework solvers, pas une route pour un bot autonome ; relai PFL :
  très peu de validateurs (latence en heures).
- Polygon Private Mempool : existe (gratuit, live 2026-04-02, anti-
  frontrunning) mais **AUCUNE simulation / drop de revert documentée** ;
  endpoint non publié (accès sur demande). NE PEUT PAS prétendre au 0 $.
- dRPC / Blink (ex-Merkle) / bloXroute Protect : vie privée MEV
  seulement, aucune garantie revert documentée.
- Paymaster ERC-4337 : **NE PEUT PAS** rendre le revert 0 $
  (EntryPoint facture le gas même en revert — Trail of Bits, docs
  ERC-4337). EIP-3529 : refund SELFDESTRUCT supprimé, max gasUsed/5.
- Résidu chiffré : revert on-chain 0,0024 $ mesuré / 0,0095 $ prudent ;
  E[revert] = taux de course × coût : 5 % → 0,000475 $/trade tenté
  (~0,05 $ pour 100 trades tentés). Négligeable en $, mais pas 0 $.

Implémenté (`polygon/revert_protection.py`, 22/22 tests) : **re-simulation
`eth_call` au dernier bloc + fenêtre de fraîcheur 30 s + net > 0 $** —
tout trade qui revert en re-sim, quote trop vieille ou net <= 0 est
DROPPÉ avant broadcast (0 $ gas, sender jamais appelé). Routage
`public` (défaut) / `private` (Polygon Private Mempool, endpoint TBD,
désactivé, marqué NON VÉRIFIÉ pour le revert). Repli **fail-closed**
par défaut : route privée down → NE PAS ENVOYER ; public seulement si
`allow_public_fallback=true` ET net couvrant le budget revert.
Journal `revert_protection_log.jsonl` : dropped_presend / sent /
executed / reverted_onchain + gas payé. Sender par défaut = dry-run
(rien n'est broadcast). Config : section `revert_protection:` dans
`polygon_config.yaml`. Rapport complet :
`polygon/REVERT_PROTECTION_POLYGON.md`.

Tests : polygon **78/78** au dernier run combiné (test_revert_protection
22/22 — stable, fichier v4.2 ; test_polygon + test_watchlist en cours
d'édition par l'agent big pools/triangle au même moment, comptes en
mouvement) ; Base inchangée 85/85 (math 8/8, v2 11/11, balancer 11/11,
morpho 12/12, sponsor 12/12, $0 15/15, self_funded 16/16).
