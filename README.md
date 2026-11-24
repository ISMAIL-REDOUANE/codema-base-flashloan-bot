# Bot Flash Loan — Base, Meme Coins Sghar (v1)

**Bni mn 0, bla flous 7qiqiyn, simulation seulement.**
Chaîne : Base (8453). Cible : meme coins sghar, liquidité 5k–100k $,
là où il y a **moins de concurrence** (pas WETH/USDC, tous les bots
sont déjà dessus).

## L'idée en 3 lignes (darija)

1. **Flash loan** : katslef USDC bla collateral, katkhdem bih f nafs
   l-transaction, katrje3o f nafs l-transaction. Ila ma rje3tihch,
   kolchi kayt-annula.
2. **Arbitrage** : katchri MEME rkhis f DEX A (Aerodrome), katbi3o
   ghali f DEX B (Uniswap V2 / Sushi). L-far9 howa l-profit.
3. **L-calcul kaygoul ch7al ndkhlo** : machi 10 000 $ fixe. L-moteur
   kay7seb l-taille li kat-maximisi l-profit NET, 7it l-price impact
   kayakel l-profit ila dkhelti kbir.

## La formule, en mots simples

Pool V2 : `x * y = k`. Ila chriti bzaf, l-prix kaytla3 3lik.
Sortie d'un swap : `out = y * in*(1-frais) / (x + in*(1-frais))`

```
MEME acheté = amm_out(loan, pool A)
USDC récupéré = amm_out(MEME, pool B)
NET = USDC récupéré - loan - frais_flash (0,05 %) - gas
```

On teste des dizaines de tailles (10 $ → plafond) et on garde celle
avec le plus grand NET. Plafonds durs : max 10 % de la plus petite
réserve USDC, max 50 000 $ (config.yaml).

**Kelly** : pour le capital PROPRE (pas le loan), on utilise Kelly
quart (max 25 % de la bankroll par idée). Le loan, lui, est remboursé
atomiquement — le capital à risque, c'est surtout le gas.

## La preuve chiffrée (même opportunité, spread 20 %, pools 20k / 18k $)

| Taille du loan | USDC récupéré | NET | Verdict |
|---:|---:|---:|---|
| 100 $ | 117,91 $ | **+16,66 $** | WIN |
| 500 $ | 563,68 $ | **+62,23 $** | WIN |
| 2 000 $ | 1 936,01 $ | **-66,19 $** | LOSS |
| 10 000 $ | 5 519,28 $ | **-4 486,92 $** | LOSS |
| **790 $ (optimale)** | 863,31 $ | **+71,55 $** | **EXECUTE** |

→ 10 000 $ perd 4 487 $ là où 500 $ gagne 62 $. C'est le price impact.
Le calcul a raison, la taille fixe a tort.
Tests : `python3 test_math_engine.py` — 6 tests, tous passent
(3 scénarios : spread 20 % petit pool, spread 2 % SKIP, grosses pools 5 %).

## La règle GAS — la plus importante

> **Si le trade serait perdant, on ne le broadcast PAS. Gas payé : 0 $.**

- **Simulation off-chain d'abord** (`executor.py`) : on calcule le NET
  avant d'envoyer quoi que ce soit. Simulation = `eth_call` / calcul
  local = **0 gas, 0 $**.
- On broadcast **seulement si** `NET > 3 $` **ET** `NET > gas × 3` **ET**
  `gas < 2 gwei` (plafond v2 — au-dessus, on n'envoie rien).
- Le `revert` dans le contrat Solidity (`require(profit >= minProfit)`)
  n'est que le **filet de sécurité** si le prix bouge entre la simulation
  et le bloc. Un revert on-chain coûte du gas — donc on l'évite par la
  simulation, on ne compte pas dessus.

Dry-run vérifié :
```
[dry-run] WOULD-EXECUTE MEME-WIN spread 20.0% loan 790 $ net +72.68 $ (gas : 0 $)
[dry-run] SKIP MEME-LOSE spread 2.0% net 1.11 $ — gas payé : 0 $
TOTAL gas payé : 0.00 $
```
Voir `simulation_log.txt`. (Chiffres v2 : gas unifié 0,0675 $, min 3 $ —
en v1, c'était +71,55 $ avec un gas supposé de 1,20 $.)

## Changelog v2 (2026-11-24) — ce qui a changé

Intégration complète de `ADVANCED_RESEARCH.md` (recherche profonde GitHub + web).
Détail : `V2_CHANGELOG.md`. En résumé :

1. **Gas unifié** (`gas.py`) : le bug v1 est corrigé — config et moteur
   disent maintenant la même chose (0,0675 $ par défaut, mesuré live :
   0,006 gwei -> 0,0081 $ le 2026-11-24). **Plafond 2 gwei** : au-dessus,
   aucun broadcast (pic 254 gwei = swap 70 $ le 29 oct 2026).
2. **Quoter V3 réel** (`v3_quote.py`) : quote on-chain via QuoterV2
   `quoteExactInput` — **vérifié live : 100 USDC -> 0,05959 WETH**.
   Découverte : `quoteExactInputSingle` REVERT sur Base (vérifié 2 fees,
   2 formes) — ne pas l'utiliser. Formule Python mono-tick en repli.
3. **Preflight EVM réel** (`preflight.py`) : `getAmountsOut` on-chain
   avant broadcast — **vérifié live** (round-trip USDC->WETH->USDC :
   net on-chain -0,76 $, LOSE, bloc 61793161). Aerodrome : cotation
   Route-based (le router Aerodrome n'a PAS getAmountsOut V2 — prouvé
   par le fork-test). Fraîcheur ≤ 2 blocs.
4. **Filtre GoPlus** (`scanner.py`) : honeypot / taxes / mint / proxy /
   pause / blacklist — REJECT dur, UNKNOWN = on ne trade pas.
5. **Circuit breaker** (`circuit_breaker.py`) : perte max 20 $/jour,
   50 trades/jour max, 3 reverts -> pause 1 h, kill switch, max 2 trades
   par token/heure. État persisté.
6. **Flux temps réel** (`websocket_listener.py`) : WebSocket `eth_subscribe`
   (post-Denim, blocs 200 ms) ; polling documenté comme trop lent —
   mesuré : latence polling ~350 ms > 200 ms (bloc).
7. **EV mesuré** (`ev_test.py` -> `EV_RESULTS.md`) : 100 opportunités,
   33 exécutées, EV **+11,18 $ par opportunité**, net total +1 117,60 $,
   drawdown 0 $ (modèle). Verdict : GO (modèle) — le go/no-go RÉEL exige
   100 simulations fork.
8. **Kelly honnête** : 0,10× tant que < 30 trades, borne de Wilson, 0 si
   aucun trade mesuré — plus de `p = 60 %` inventé.

## ⚠️ Limites honnêtes de v2 (lire avant tout live)

- **✅ COMPILATION RÉSOLUE le 2026-11-24** (Ismail : « kmel lkhedma,
  aya haja dirha nta ») : librairies installées par tarballs officiels
  (OZ v4.9.6 + Aave v3-core v1.19.4), `forge build` OK, contrat déployé
  sur fork Base — cas gagnant WIN **+17,24 $**, cas perdant revert
  confirmé. Détails : `FORK_TEST_RESULTS.md` §10. Reste : audit avant
  tout mainnet ; **v3.3 : la jambe Morpho est prouvée sur fork aussi
  (WIN +17,58 $, §11) et Balancer est MORT (BIP-928, 30 oct 2026) —
  ne plus utiliser le Vault `0xBA12…F2C8`.**
- **Aerodrome dans le contrat est FAUX** (prouvé on-chain) : le router
  Aerodrome n'a pas l'interface V2. Le Python (preflight) gère le
  Route-based ; le contrat Solidity doit être corrigé (adaptateur)
  avant tout déploiement avec une jambe Aerodrome.
- **RPC public rate-limité** : `mainnet.base.org` renvoie parfois 403 /
  RemoteDisconnected sous charge (vu pendant les tests). Pour le live,
  il faut un RPC dédié (Alchemy / QuickNode / Chainstack) + 2e RPC en fallback.
- **Slipstream (Aerodrome) et Uniswap V4 non couverts** : quoter V3
  Uniswap seulement. Les frais dynamiques Slipstream ne sont pas modélisés.
- **MEV** : pas de mempool privée sur Base — la protection reste
  l'atomicité + simulation + minOutput, pas Flashbots Protect (L1 only).
- **EV = modèle, pas réel** : spreads supposés, win rate 100 % par
  construction. Le vrai go/no-go = 100 simulations fork.

## Architecture

```
config.yaml                  — tous les seuils (RPC, min profit 3 $, plafonds,
                               gas max 2 gwei, limits: circuit breaker)
gas.py                       — v2 : gas UNIFIÉ (live RPC + plafond 2 gwei)
math_engine.py               — AMM x*y=k, taille optimale, Kelly honnête, decide()
v3_quote.py                  — v2 : quoter V3 on-chain (quoteExactInput) + formule Python
preflight.py                 — v2 : simulation EVM (getAmountsOut on-chain, Aerodrome Route-based)
test_math_engine.py          — 8 tests, 3 scénarios réalistes + gas cap + Kelly honnête
test_v2.py                   — 11 tests v2 (gas, V3, GoPlus, breaker, preflight, EV)
scanner.py                   — DexScreener + filtres (liquidité 5k-100k $,
                               holders, âge) + v2 GoPlus (honeypot/taxes/mint)
executor.py                  — simulate() avant broadcast, mode dry_run only
                               + v2 preflight EVM + circuit breaker
circuit_breaker.py           — v2 : perte max/jour, max trades, pause reverts, kill switch
websocket_listener.py        — v2 : WebSocket eth_subscribe (Denim 200 ms) + polling (lent)
ev_test.py / EV_RESULTS.md   — v2 : EV sur 100 opportunités simulées
dry_run.py / simulation_log.txt — démo gagnant SKIPPÉ / perdant SKIPPÉ
contracts/FlashLoanArbitrage.sol — squelette Aave V3 flashLoanSimple,
                               Ownable + ReentrancyGuard, NON AUDITÉ, NON COMPILÉ
                               (⛔ Aerodrome FAUX dedans — voir V2_CHANGELOG.md)
RESEARCH.md                  — toutes les adresses Base vérifiées + sources
ADVANCED_RESEARCH.md         — recherche profonde GitHub + web (548 lignes)
FORK_TEST_RESULTS.md         — résultats du test fork Anvil (agent fork-test)
```

## Lancer

```bash
python3 math_engine.py        # démo du calcul
python3 test_math_engine.py   # tests
python3 dry_run.py            # simulation gagnant + perdant
```

## V2 — Test fork Anvil (2026-11-24) — seuil min profit : **3 $**

Détail complet : `FORK_TEST_RESULTS.md` (+ `fork_results.json`).

**Le contrat n'a PAS pu être compilé/déployé** : le contenu des dépendances
clonées (`lib/`, OpenZeppelin + Aave) a échoué un contrôle de risque
d'exécution — compilation en attente de confirmation d'Ismail
(`forge install` puis `forge build`, voir §1 du doc). La simulation
ci-dessous prouve quand même l'économie, sans le bytecode.

**Fork Base mainnet, bloc 61 791 654** (RPC public `https://mainnet.base.org`,
aucun fond réel) :
- Aave V3 : prime flash **0,05 % confirmée on-chain** ; liquidité USDC
  **13,64 M $** — dans le aToken aBasUSDC, pas dans le Pool (123 $).
- Réserves réelles : Uni V2 289,79 WETH / 486 389 $ ; Aerodrome 206,46 WETH /
  347 101 $ ; Sushi V2 quasi vide (2,8 k $ — inutilisable).
- Spread naturel 0,16 % → rien à arbitrer. Spread synthétique 10,41 %
  (vente de 14,49 WETH sur Uni V2, fonds fictifs du fork).
- **Cas gagnant (swaps RÉELS minés sur le fork)** : loan optimal **8 847,98 $**
  (calcul, pas une taille fixe) → **9 274,80 $** récupérés → brut +426,82 $,
  prime flash −4,42 $, gas 449 915 units à 0,0049 gwei = 0,0066 $ →
  **NET +422,39 $** (Python prédisait +421,04 $ — écart 1,35 $).
  Cotations `getAmountsOut` = exécution réelle à 0 $ près.
- **Cas perdant** : spread 0,16 % → `decide()` = **SKIP, gas 0,00 $**.
  Revert mesuré exprès sur le fork : 54 829 gas = **0,0008 $**.
- **Constat majeur** : le Router Aerodrome N'A PAS l'interface V2
  (vérifié par sélecteurs on-chain) — le contrat v1 ne peut pas
  l'utiliser tel quel, il faut les routes `(from, to, stable, factory)`.
- Aucun vrai meme coin 5k–100k $ avec 2 paires V2 trouvé dans cet essai
  (GeckoTerminal + `getPair` on-chain) — le scanner devra tourner en continu.

**Ce qui est prouvé :** l'économie de l'arbitrage + le sizing + la règle
gas. **Ce qui ne l'est pas :** le contrat lui-même (compilation, déploiement,
`require(profit >= 3 $)`) — en attente de confirmation.

## ⚠️ Ce qu'il faut encore (Ismail)

1. **Confirmer la compilation** avec OpenZeppelin v4.9.6 + Aave v3-core
   (voir `FORK_TEST_RESULTS.md` §1) → ensuite `bash fork_test.sh`.
2. **Corriger le contrat** : adaptateur Aerodrome (Route-based) ; lire la
   liquidité Aave via le aToken ; support Uni V3 en v2.
3. **RPC URL Base** (Alchemy / QuickNode, ou `https://mainnet.base.org`
   pour les tests) — à mettre dans `config.yaml`, jamais de clé en dur.
4. **ETH sur Base pour le gas** — même en live, il faut un peu d'ETH
   pour broadcaster les trades gagnants. En dry-run : 0 $.
5. **Seuils confirmés** : `min_profit_usd` = **3 $** (Ismail, 2026-11-24),
   `max_pct_liquidity` (10 %), `kelly_cap` (**0,10** en v2 — honnête,
   tant que < 30 trades mesurés), `gas_price_max_gwei` (2),
   perte max 20 $/jour — à ajuster après les premiers tests sur fork.
6. **V3 (pas en v2)** : adaptateur Aerodrome Route-based DANS le contrat,
   support Slipstream / Uniswap V4, audit du contrat avant tout déploiement mainnet.

## 🆕 v3 — Flash loan 0 frais via Balancer (2026-11-24, demande d'Ismail)

> ⛔ **DÉPRÉCIÉ v3.3 (2026-11-24) : Balancer est MORT (BIP-928, wind-down
> 30 oct 2026).** Ne plus utiliser le Vault `0xBA12…F2C8`. Le remplaçant
> est Morpho Blue — voir § v3.3 ci-dessous. Cette section est conservée
> comme historique (les mesures de nov 2026 sont exactes pour leur date).

Ismail : « khdem b flash loan ikon 0 fees, bhal Balancer ». Fait et vérifié
on-chain — voir `BALANCER_RESEARCH.md` pour les preuves complètes.

- **Balancer V2 Vault sur Base** : `0xBA12222222228d8Ba445958a75a0704d566BF2C8`
  (même adresse partout, code présent). Prime lue on-chain :
  `getFlashLoanFeePercentage()` = **0,00 %** (bloc 61 794 215).
- **Soldes du Vault Base** : USDC **53 208 $** / WETH **23,27 (~39 042 $)** —
  total ~92 250 $. Nos loans passent ; au-delà de **26 604 $** USDC (50 %
  du solde), le bot rebascule sur Aave (0,05 %, liquidité 13,6 M$).
- **On n'emprunte jamais le meme coin** (absent du Vault) : on emprunte
  USDC/WETH à 0 %, on swap sur Uniswap/Aerodrome, on rembourse.
- **Gain mesuré** : référence 790,16 $ → **+73,07 $** (vs +72,68 $ Aave,
  +0,39 $) ; cas fork 8 847,98 $ → **+426,81 $** (vs +422,39 $, +4,42 $).
  Le 0 % ne sauve pas une mauvaise taille : 10 000 $ perd toujours.
- **Nouveaux fichiers** : `balancer_flash.py` (sélection provider, lecture
  fee/soldes on-chain, encodage `vault.flashLoan`), `test_balancer.py`
  (11/11), `BALANCER_RESEARCH.md`. Contrat : squelette
  `BalancerFlashLoanArbitrage` ajouté (NON compilé — même blocage
  `forge install`, confirmation d'Ismail requise).
- **Balancer V3** : NON déployé sur Base (aucun code à `0xbA13…3333`).

**Aucun fond réel, aucune clé privée, aucun broadcast mainnet en v3.**

## 🆕 v3.1 — Modèle sponsor : 20 $ de gas, 25 % du net (2026-11-24, approuvé par Ismail)

Ismail : « Mzyana dik tari9a dyal sponsor ». Implémenté dans `sponsor.py` (+ `config.yaml`, section `sponsorship:`).

- **Le deal** : le sponsor préfinance **~20 $ d'ETH** (que pour le gas — à ~0,008 $/trade = ~2 500 trades). Sur chaque trade gagnant : **sponsor 25 % / Ismail 75 %** du profit net. Trade perdant ou SKIP : **0 $ / 0 $** pour tout le monde.
- **Exemple** : net +73,07 $ (cas de référence 790,16 $, fee 0 %) → **sponsor 18,27 $ / Ismail 54,80 $**. Net 100 $ → 25 $ / 75 $. Net 0 $ → 0 $ / 0 $.
- **Plafond journalier sponsor : 20 $/jour.** Le 6e trade qui dépasserait le plafond est **BLOQUÉ avant exécution** avec une raison STOP explicite — le bot ne trade jamais au-delà du deal.
- **Prefund** : chaque gas est déduit des 20 $ ; **alerte sous 5 $**, arrêt à 0 $. **Kill switch** : le sponsor (ou Ismail) coupe tous les trades.
- **Traçabilité** : chaque trade exécuté est appendé dans `trades.jsonl` (net, parts, gas, provider) avec un drapeau `simulated: true` en dry-run — le sponsor ne confond jamais une simulation avec de l'argent dû.
- **Ce que le sponsor doit fournir** : son adresse wallet (`sponsor_wallet` dans config.yaml, vide pour l'instant) + ~20 $ d'ETH de prefund. Rien d'autre — pas de clé privée, pas de contrôle du bot.
- **Ismail peut s'auto-financer** : `sponsor_share_pct: 0` → 100 % du profit pour lui, le prefund reste le sien.
- **Tests** : `test_sponsor.py` **12/12** (partage, plafond, alerte prefund, kill switch, intégration executor/dry-run).

## 🆕 v3.2 — Mode $0 TOTAL : Ismail paie 0 $, pas même 1 $ (2026-11-24, exigence d'Ismail)

Ismail : « ana mnkhls wlo, 0$, kolchi n9lbo lih 3la l7al ». Implémenté dans `zero_cost.py` (+ section `zero_cost:` dans `config.yaml`) — le garde **$0** : chaque EXECUTE passe par `check_zero_cost()` AVANT tout enregistrement. Le moindre dollar à la charge d'Ismail → trade **BLOQUÉ** avec la raison explicite `ZERO_COST: Ismail paierait X $`, et la moindre charge détectée déclenche un **kill switch** qui bloque tous les trades suivants.

### Tableau des coûts — qui paie quoi ?

| Coût | Qui paie ? | Solution $0 | Statut |
|---|---|---|---|
| Prime flash loan | Personne (Morpho 0 %) | Morpho Blue, fee 0 % par conception (pas de getter flashFee — vérifié bloc 61 806 974) — Aave 0,05 % **BLOQUÉ** en mode $0 ; Balancer MORT (BIP-928) | ✅ vérifié |
| Gas (trades gagnants) | Sponsor (prefund 20 $) | ~0,008 $/trade ; repli crédits CDP 1 000 $ (demande 21 nov, **en attente** — `cdp-credits` bloqué tant que non approuvé) | ✅ |
| Gas (trades perdants) | **0 $** — SKIPPÉS avant broadcast | Simulation + preflight EVM (perdant = 0 gas, prouvé en fork) | ✅ |
| Gas (revert on-chain) | Sponsor (prefund) — max **0,33 $** au plafond 2 gwei | Circuit breaker après 3 reverts ; revert mesuré en fork : 0,0046 $ | ⚠️ résiduel plafonné, **jamais Ismail** |
| RPC Base | **0 $** | Alchemy free tier (app Base-Bot, déjà dans `config.yaml`) | ✅ |
| Infra (VM, cron, outils) | **0 $** | Muse, Foundry, Anvil, GitHub — gratuits | ✅ |
| Audit professionnel payant | — | **AUCUNE solution $0 aujourd'hui** | ⛔ **live bloqué** tant qu'il n'est pas financé (sponsor ou profits futurs) ; en attendant Slither/Aderyn (gratuits) + revue manuelle |

- **Preuve par trade** : chaque ligne de `trades.jsonl` porte `ismail_paid_usd` (toujours 0,00 $) — sur 20 trades simulés (10 gagnants / 10 perdants), Ismail a payé **0,00 $** et les 10 lignes du ledger le prouvent.
- **Tests** : `test_zero_cost.py` **15/15** (Morpho autorisé, Aave bloqué, gas > prefund bloqué, crédits CDP en attente bloqués, kill switch sur 0,01 $, 20 trades à 0,00 $). Suites existantes inchangées : math 8/8, v2 11/11, Balancer 11/11 (déprécié, v3.3), sponsor 12/12, Morpho 12/12 (v3.3).
- **Limite honnête** : le $0 **garanti** sur un revert on-chain est impossible sur Base aujourd'hui (voir `ZERO_COST_PRIVATE.md` §3.2 — Flashbots n'existe que sur Ethereum L1). Le résiduel est plafonné (0,33 $ max) et payé par le sponsor, jamais par Ismail.

## 🆕 v3.3 — Balancer mort → Morpho Blue, flash loan 0 frais (2026-11-24)

**Balancer a été liquidé (BIP-928, wind-down 30 oct 2026)** : pools en
retraits seuls, bug bounty terminé, Balancer Labs dissoute. Le Vault
`0xBA12…F2C8` ne doit plus être utilisé. Le remplaçant est **Morpho Blue**,
vérifié comme Balancer l'avait été — en mieux :

- **Morpho Blue sur Base** : `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
  (singleton canonique, code 15 623 octets, bloc 61 806 974).
- **Frais 0 % par conception** : docs Morpho officielles (« flashFee is
  zero ») — et il n'existe AUCUNE fonction `flashFee` sur le contrat :
  l'eth_call du sélecteur ERC-3156 revert. Aucune gouvernance ne peut
  monter ce fee (contrairement à Balancer, où c'était un paramètre).
- **Liquidité énorme** : USDC **328,7 M$** / WETH **88 713,53** (~148,9 M$)
  chez Morpho (bloc 61 806 974) — `maxFlashLoan` = le solde entier du
  contrat. La règle 50 % donne ~164 M$ utilisables : en pratique, ce
  n'est plus le provider qui limite le loan, mais le moteur (max 10 %
  de la plus petite réserve, max 50 000 $). TVL Morpho Blue sur Base :
  **3,336 Md$** (DefiLlama, 24 nov 2026).
- **Callback vérifiée** contre le repo officiel morpho-org/morpho-blue
  et la doc : `flashLoan(address token, uint256 assets, bytes calldata data)`
  (sélecteur `0xe0232b42`), `onMorphoFlashLoan(uint256 assets, bytes calldata data)`
  (sélecteur `0x31f57072`). Le receiver est l'appelant ; le remboursement
  se fait par `approve(Morpho, assets)` exact — fee 0, on rembourse
  exactement `assets`.
- **Preuve fork** (`FORK_TEST_RESULTS.md` §11, bloc 61 807 834) :
  spread synthétique 10,236 %, loan optimal **366,50 $**, cas gagnant
  **WIN +17,58 $** (gas 285 948 à 0,0049 gwei = 0,0042 $), cas perdant
  **SKIP 0 $** + revert confirmé (coût mesuré 0,0040 $). Un bug
  `ReentrancyGuard: reentrant call` (double `nonReentrant` sur
  `executeArbitrage` + callback) a été trouvé et corrigé en route.
- **Nouveaux fichiers** : `morpho_flash.py` (sélection provider,
  lecture soldes on-chain, vérification d'absence de getter flashFee,
  encodage `flashLoan`), `test_morpho.py` (**12/12**),
  `fork_test_morpho.py` / `fork_test_morpho.sh`. Contrat :
  `MorphoFlashLoanArbitrage` ajouté (jambes Uni V2 / BaseSwap V2
  seulement — Aerodrome toujours faux, pas d'interface V2).
- **Changements** : `config.yaml` (provider préféré `morpho`, repli
  `aave`, `balancer_vault` commenté comme déprécié ; allow-list $0 =
  `["morpho"]`), `executor.py` (route via Morpho), `math_engine.py`
  (`MORPHO_FLASH_FEE = 0.0`, `Costs(flash_provider="morpho")`),
  `zero_cost.py` (Morpho seul autorisé), `balancer_flash.py` marqué
  DÉPRÉCIÉ (conservé pour référence), `test_balancer.py` 11/11 (tests
  du module déprécié conservés + test executor mis à jour vers Morpho),
  `test_zero_cost.py` 15/15 (références Balancer → Morpho).
- **Chiffres inchangés pour Ismail** : référence 790,16 $ → **+73,07 $**
  (vs +72,68 $ Aave) ; dry-run WOULD-EXECUTE +73,07 $ [provider morpho]
  / SKIP 1,19 $ / gas total 0,00 $ ; Ismail a payé **0,00 $**.

**Aucun fond réel, aucune clé privée, aucun broadcast mainnet en v3.3.**

## 🆕 v3.4 — Gas AUTOFINANCÉ : Ismail paie le gas (~20 $ float), garde 100 % (2026-11-24, décision d'Ismail)

Décision d'Ismail (2026-11-24 21:47) : **« Flblan lwel o ana an7at
flous dyal l gas »** — Plan 1 (CDP 15 k$, produit + application) ET il
finance le gas lui-même. La contrainte « 0 $ total » est levée pour le
**GAS SEULEMENT** ; la prime de flash loan reste **0 % (Morpho
uniquement)**. Pas de sponsor : la section `sponsorship:` de
`config.yaml` est **INACTIVE** (`enabled: false`, part 0 %).

- **Nouveau `self_funded.py`** : `FloatLedger` — float 20 $, `ismail_paid_usd`
  (gas dépensé), `profits_usd`, `float_remaining_usd` (le profit USDC ne
  recharge PAS le float ETH — le gas est en ETH, le profit en USDC).
  `can_afford(gas)` bloque un trade quand le float ne couvre pas le
  **pire cas = gas + budget revert** (par défaut 2 × gas). Kill switch
  quand le float tombe à **0 $** (tout trade stoppe, raison claire ;
  réarmé par une recharge `top_up`). `split_profit` : **0 / 100**
  (sponsor 0 $, Ismail 100 %). Chaque entrée de `trades.jsonl` porte
  `funding_mode: "self_funded"`.
- **Interrupteur de mode `zero_cost.py`** : le garde $0 a deux modes —
  `zero_cost` (sponsor, comportement historique) et `self_funded`
  (nouveau, **mode par défaut** quand `config.yaml funding.payer ==
  "ismail"`). En mode autofinancé : gas payé par Ismail depuis le float
  (autorisé si le float couvre le pire cas), net **≥ 3 $ APRÈS gas +
  prime**, Morpho 0 % seul (Aave 0,05 % toujours bloqué), aucun coût
  hors-gas à la charge d'Ismail. La section `zero_cost:` de la config
  est inchangée (mode $0 historique conservé).
- **`sponsor.py`** : ledger désactivé → `split_profit` retourne (0, net)
  (Ismail 100 %, jamais 0/0 par erreur) ; entrées taguées `funding_mode`.
- **`executor.py` / `dry_run.py`** : nouveau paramètre `funding` —
  pas de check sponsor, pas de plafond sponsor ; le garde bascule en
  mode `self_funded` ; enregistrement dans le FloatLedger (une seule
  ligne par EXECUTE, gas **SIMULÉ** déduit du float en dry-run).
  Dry-run : `FINANCEMENT : Ismail — float 20.00 $ / dépensé 0.07 $ /
  restant 19.93 $ / profit 73.07 $`.
- **Tests** : `test_self_funded.py` **16/16** (comptabilité sur 20
  trades, blocage float épuisé, kill switch à 0 $, split 100/0,
  Morpho seul, Aave bloqué, min-profit 3 $ après gas, intégration
  executor de bout en bout). Toutes les suites passent : math 8/8,
  v2 11/11, balancer 11/11, sponsor 12/12, $0 15/15, morpho 12/12,
  self_funded 16/16 (**85/85**). Un test sponsor a été mis à jour
  (`test_load_from_config` : `enabled: false`, part 0,0 % — reflète la
  config v3.4 délibérée, pas une régression).
- **Combien de trades pour 20 $ ?** Gas mesuré en fork ~0,005 $/trade
  → **~4 000 trades** (~2 000 avec budget revert) ; modèle Costs
  (0,0675 $) → **~296 trades** (~148 pire cas) ; plafond 2 gwei
  (2,70 $/trade) → **7 trades** (3 pire cas). Au rythme estimé de
  0–3 opportunités ≥ 3 $/semaine, le float de 20 $ dure des mois.

**Aucun fond réel, aucune clé privée, aucun broadcast mainnet en v3.4 —
Ismail doit encore fournir son adresse publique (jamais de clé privée)
et le float ~20 $ en ETH sur Base.**

## 🆕 v4.0 — Port Polygon : flash loan 0 frais vérifié, float 1,31 $ MATIC (2026-11-24, décision d'Ismail)

Décision d'Ismail (2026-11-24 21:56) : travailler **uniquement avec
ses 1,31 $ sur Polygon** (17,2743 MATIC), avec un flash loan **0 frais**.
Le bot Base reste intact — le port vit dans `polygon/` et ne touche rien
d'autre.

- **Fournisseur 0 frais vérifié : Morpho Blue Polygon
  `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67`** (PAS l'adresse canonique
  `0xBBBB…` — elle n'a AUCUN code sur Polygon). Vérifié : code 15 582
  octets, `flashFee` getter absent (frais 0 structurel), `idToMarketParams`
  + `market` conformes à l'API Morpho, soldes USDC 112 261 $ / USDT
  122 030 $ / WMATIC 1 000 246 (bloc 97 901 631). Détails :
  `polygon/POLYGON_FLASH_VERIFICATION.md`. Candidat B (Uniswap V4 flash
  accounting) vérifié comme mécanisme 0 frais (PoolManager
  `0x67366782…`), non implémenté en v4.0. Aave V3 Polygon = 0,05 %
  (repli payant, bloqué en mode 0 frais). Balancer = MORT (BIP-928),
  dYdX = mort.
- **Contrat `polygon/contracts/FlashLoanArbitragePolygon.sol`** :
  Morpho Polygon + achat QuickSwap V2 (USDC→WMATIC) + **vente Uniswap V3
  EN DIRECT** (`pool.swap` + `uniswapV3SwapCallback`) — le SwapRouter02
  Polygon (`0x68b346…`) **n'expose pas `exactInputSingle`** (sélecteur
  0x414bf389 absent du bytecode, prouvé par trace fork + test EOA), et
  la paire Sushi V2 USDC/WMATIC est vide (~12 $). minProfit 3 $,
  `forge build` OK (bytecode 5 661 octets).
- **Fork test Polygon** (`polygon/FORK_TEST_RESULTS_POLYGON.md`, bloc
  97 902 229) : spread synthétique 21 %, loan optimal 50,22 $,
  **WIN net +4,83 $** (gas 0,0028 $) ; cas perdant **SKIP 0 $**, revert
  mesuré 0,031366 MATIC = 0,002378 $. Gas Polygon ~2× plus cher que
  Base en $ (279 gwei live) — **PAS « quasi gratuit »**.
- **Scan live Polygon** (`polygon/MEME_POOLS_LIVE_POLYGON.md`) : 80 pools
  récentes lues, **0 candidat, 0 paire 2-venues** — rien à arbitrer en
  ce moment (même verdict que Base). Le scan doit tourner toutes les
  2–4 h en watchlist.
- **Float 1,31 $ MATIC** (`polygon/polygon_ledger.py`, adapté du
  FloatLedger Base) : ~137 trades au coût prudent (450 000 gas ×
  279 gwei = 0,0095 $/trade), ~68 pire cas (trade + revert) ; 235 au
  coût mesuré sur le fork. Kill switch à 0 $.
- **Tests** : `polygon/test_polygon.py` **20/20** (0 frais, gas, math,
  float, kill switch, min-profit, live RPC). Toutes les suites Base
  inchangées : math 8/8, v2 11/11, balancer 11/11, morpho 12/12,
  sponsor 12/12, $0 15/15, self_funded 16/16.

**Reste avant tout live (les deux chaînes) : paper-trade Amoy 2–4
semaines + audit payant. Aucun fond réel, aucune clé privée, aucun
broadcast mainnet en v4.0.**
