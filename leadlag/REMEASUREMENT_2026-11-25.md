# RE-MESUREMENT — Le « 0 opportunité » change-t-il avec le code corrigé ?

> **SYNTHÉTIQUE — tous les chiffres ci-dessous sont des QUOTES, des lectures
> d'API publiques et des SIMULATIONS sur fork, jamais des trades exécutés,
> jamais un profit réalisé.** Les mesures dites « live » sont des lectures
> on-chain / API au moment indiqué ; elles ne prouvent pas qu'un trade
> aurait été exécuté.
> Date : 2026-11-25. Repo : `codema-base-flashloan-bot`, commit `d68c8e2`
> (15/15 findings de l'audit ChatGPT corrigés). Fichiers de ce travail :
> `leadlag/remeasure_scan.py` + `remeasure_scan_results.json`,
> `leadlag/remeasure_fork.py` + `remeasure_fork_results.json`,
> `leadlag/remeasure_listener_compare.py` + `remeasure_listener_compare.json`,
> `leadlag/remeasure_scan.log`, `leadlag/remeasure_fork_majors.log`,
> `polygon/remeasurement_signals.jsonl`, `polygon/remeasurement_listener*.log`.
> Code corrigé pendant ce travail : `scanner.py` (forme de réponse
> /token-pairs/v1) + test de régression dans `test_v2.py`.

---

## (0) Rappel — ce que l'audit avait trouvé (et ce qui a été corrigé)

| # | Bug (audit, confirmé) | Correction appliquée (commit d68c8e2) |
|---|---|---|
| #3 | Scanner : `holders` défaut 0 + filtre ≥ 20 → 0 candidat systématique ; GoPlus ne transférait pas `holder_count` | `holders_known`/`holders_source`/`age_known` ; transfert GoPlus ; rejet explicite si inconnu |
| #4 | Endpoint DexScreener `/latest/dex/pairs/base/<token>` attend une adresse de PAIRE | `/token-pairs/v1/base/<tokenAddress>` ; USDC sélectionné par adresse |
| #5 | Taxes GoPlus décimal 0–1 comparées à 5.0 → taxe 50 % PASSAIT ; `not_open_source` non bloquant | Normalisation ×100 ; taxe absente → UNKNOWN ; `not_open_source`/`too_few_holders`/`tax_unknown` bloquants |
| #6 | Preflight : 2 `getAmountsOut` sur `latest`, jamais `executeArbitrage` | `fork_preflight.py` : fork Anvil + déploiement + exécution impersonnée + gas réel + raison de revert |
| #7 | Contrat Base V2-only, aucune route CL exécutable | `route.py` typé ; `MorphoFlashLoanArbitrageV3` (struct 7 champs SANS `deadline` sur Base) |
| #8 | `encode_quote_single` : ordre (fee, amountIn) inversé → calldata invalide | Ordre officiel (amountIn, fee) + décodeurs ; single REVERT TOUJOURS sur Base même corrigé (test live), path OK |
| #9 | Gas arrondi au centime : 100 × 0,0044 $ = 0,00 $ | Pleine précision (micro-dollar) ; grille 1 $ |
| #10 | `verify_signal_exact` Polygon : entrée de vente = prix spot, net indépendant de la quote de vente | `out_a` exact → entrée de vente ; net et verdict dérivés du cycle exact |
| #12 | Gas figé 0,0044 $, pas de L1 | Gas complet L2+L1 mesuré (L1 ≈ 0,000004 $) |
| #14 | Plafond provider non revalidé après réoptimisation | Revalidation + jamais de verdict sur soldes datés |
| #15 | Circuit breaker : 2 chemins incohérents | `record_receipt` unique + déduplication par tx_hash |

---

## (1) Scanner memes Base (code corrigé) — 45 tokens, 0 candidat

**Méthode (live, APIs publiques) :** découverte GeckoTerminal `new_pools`
pages 1–8 (72 h, réserve 5k–100k $, quote WETH/USDC) → **31 nouveaux tokens** ;
+ **14 tokens PASS1** du scan 2026-11-24 (comparaison avant/après sur les
MÊMES tokens). Pour chaque token : `scan_token(goplus_check=True)` réel
(code corrigé) + diagnostic (raisons de rejet explicites).

**Démo endpoint #4 (live, 1 token) :** ancien URL
`/latest/dex/pairs/base/<token>` → **0 paire** (aucune clé `pairs` dans la
réponse) ; nouveau URL `/token-pairs/v1/base/<token>` → **1 paire**.
Le fix #4 fonctionne en live.

**Résultat : 45 tokens scannés, 0 candidat (nouveau code).**

| Mesure | Valeur |
|---|---|
| Tokens scannés | 45 (31 GT-nouveaux + 14 PASS1) |
| Tokens avec ≥ 2 paires (toutes quotes) | **0** |
| Tokens avec ≥ 2 pools USDC | **0** |
| Tokens avec 1 seule paire | 45/45 |
| Tokens avec 0 pool USDC | 44/45 |
| GoPlus REJECT / PASS / UNKNOWN | 37 / 6 / 2 |
| Candidats NOUVEAU code | **0** |
| Candidats ANCIEN code (simulé, mêmes données) | **0** |

**Pourquoi 0 — et ce n'est PLUS le même 0 qu'avant :**
- **Avant (bugs) :** 0 systématique pour 3 raisons indépendantes —
  endpoint #4 → 0 paire ; holders #3 → rejet systématique ; taxes #5 →
  faux PASS. Le code ne pouvait RIEN trouver, même si des opportunités
  existaient.
- **Maintenant (code corrigé, preuves qu'il fonctionne) :**
  - les paires SONT récupérées (démo § endpoint, 1 paire/token) ;
  - les holders SONT transférés (ex. token `0xc945…` : holders=406,
    GoPlus PASS — sous l'ancien code il aurait été rejeté `holders=0`) ;
  - les taxes SONT lues (0,0 % sur les PASS ; `tax_unknown` sur 27 tokens
    → UNKNOWN, rejet explicite) ;
  - `not_open_source` bloque désormais (ex. PASS1 `0x822c…` : 1 164 holders
    mais REJECT `not_open_source` — sous l'ancien code, ce flag n'était
    pas bloquant).
- **Le 0 actuel est structurel (marché), pas logiciel :** les 45 tokens
  n'ont qu'**UNE seule paire** chacun — il n'existe pas de deuxième venue
  pour le même token, donc pas de spread cross-venue possible. Les memes
  frais naissent sur UN dex, pas deux. (Vérification indépendante :
  endpoint `/latest/dex/tokens/<token>` donne les mêmes comptes —
  1/1/0 paires sur 3 tokens contrôlés.)
- **Les rejets GoPlus sont réels :** top flags — `too_few_holders` (30),
  `tax_unknown` (27), `owner_can_pause` (24), `mintable` (20). Les tokens
  frais ont 2–7 holders, sont mintables, pausables. Sur les 14 PASS1
  (17–19 h d'âge) : 13 REJECT, 1 REJECT `not_open_source` malgré 1 164
  holders. Seul 1 token sur 45 est PASS avec ≥ 20 holders.
- **Note de prudence :** les comptes de paires sont des instantanés
  (ex. `0xc945…` : 1 paire au scan ~13:03, 0 paire aux deux endpoints
  ~13:10 — paire disparue ou index fluctuant). La conclusion (0 token
  avec ≥ 2 paires) tenait sur les deux endpoints au moment du contrôle.

**Nouveau bug trouvé PENDANT cette re-mesure (et corrigé) :**
`fetch_pairs_from_dexscreener` supposait une réponse
`{"pairs": [...]}` — en live, `/token-pairs/v1` renvoie un **tableau JSON
nu** `[{paire}, ...]`. Le scan initial a crashé (`AttributeError: 'list'
object has no attribute 'get'`). Le test du fix #4 mockait le schéma
dict supposé — c'est pourquoi le bug a passé les tests. **Corrigé dans
`scanner.py`** (accepte les deux formes) + **test de régression ajouté**
dans `test_v2.py` (`test_scanner_token_pairs_bare_list_response`, mocke
la vraie forme live). Leçon : un mock qui reproduit l'hypothèse ne
prouve rien sur le live.

**Verdict scanner : le fix #3/#4/#5 FONCTIONNE (le scanner voit
désormais les données réelles), mais le 0 NE CHANGE PAS — parce que les
memes frais de Base n'ont qu'une seule pool. La thèse « memes sans
concurrence » échoue sur la structure du marché, pas sur le code.**

---

## (2) Fork preflight (code corrigé) — pipeline prouvé, 0 candidat à forker

**Majors WETH/USDC, 100 $, bloc courant (fork Anvil, SYNTHÉTIQUE) :**
deux runs indépendants, même résultat.

| Run | Bloc fork | Statut | Raison de revert | Gas consommé |
|---|---|---|---|---|
| 1 | 62 106 593 | **REVERT** | « pas de quoi rembourser le loan » | 327 643 |
| 2 (--candidates) | ~62 106 6xx | **REVERT** | « pas de quoi rembourser le loan » | 327 643 |

Le pipeline complet fonctionne de bout en bout (fork → déploiement du
contrat Morpho → `executeArbitrage` impersonné → revert décodé + gas
réel). Sur les majors il n'y a pas de spread : le loan ne peut pas être
remboursé → REVERT — c'est le comportement ATTENDU, pas un échec du
pipeline. (Identique au test fork de l'audit : REVERT, gas 327 643.)

**Candidats du scan : 0 candidat à forker** (0 candidat au §1, donc 0
run V2/V2). Les jambes non-V2 sont marquées inapplicables dans le
rapport fork (contrat V2-only, audit #7) — aucun candidat n'existait
de toute façon.

**Tests fork (re-run) :** `test_fork_preflight.py` **3/3 vert**
(WIN synthétique avec whale, gas 285 915 ; LOSE bloc épinglé, net
−0,7577 $).

**Verdict fork : le pipeline d'exécution complète fonctionne ; il n'y
avait rien à exécuter.**

---

## (3) Listener Polygon (code corrigé) — [SECTION EN COURS — À COMPLÉTER À LA FIN DU RUN]

[À compléter : blocs traités, quotes, signaux, vérifications,
comparaison ancien vs nouveau, closest misses.]

---

## (4) Synthèse avant / après fixes

| Mesure | AVANT (code buggé) | APRÈS (code corrigé) | Le 0 change-t-il ? |
|---|---|---|---|
| Scanner memes Base | 0 candidat systématique (endpoint 0 paire, holders 0, taxes fausses) | **0 candidat** (45 tokens, tous 1 seule paire) | **NON** — le 0 est désormais prouvé structurel, pas logiciel |
| Preflight fork | 2 `getAmountsOut`, jamais `executeArbitrage` | Pipeline complet : REVERT majors, gas 327 643 | **N/A** — rien à exécuter (0 candidat) |
| Listener Polygon | Verdicts `exact-quote` faux (net indépendant de la vente) | [à compléter] | [à compléter] |
| Cross-venue Base | 0 écart RÉEL (29 groupes) | 11 micro-opps réelles, +0,0928 $/24 h (déjà fait, `ROUTE_VERIFICATION.md`) | **OUI, marginalement** : 0 → 11 micro-événements (+0,002 à +0,018 $, 5–25 s) |
| Comptabilité gas | 100 × 0,0044 $ = 0,00 $ | 100 × 0,0044 $ = 0,44 $ | Mesure corrigée, pas d'opportunité créée |

**Opportunité historique vs réellement capturable :**
- Scanner : aucune opportunité historique détectée (pas de 2e pool) →
  rien à capturer.
- Cross-venue (déjà vérifié) : 11 événements historiques réels, mais
  capturables seulement en théorie (5–25 s de vie, contrat actuel V2-only
  + V3-Uni, pas Aerodrome Slipstream ; revenu max 0,09 $/jour à 100 $).
- Fork majors : gap historique 0 → non capturable (REVERT).

**Ce qui manque pour passer positif (en bp) :** inchangé par les fixes —
au bloc du scan, ~1,6 bp de gap sur WETH/cbBTC (gap 0,0273 % vs
threshold 0,0409 %) ; pour +1 $ par trade de 100 $, des gaps ~100 bp
plus grands que le meilleur gap statique observé (0,085 %).

## (5) VERDICT FINAL

**Le 0 NE CHANGE PAS avec le code corrigé — mais il est désormais un
0 MESURÉ, pas un 0 buggé.** Les trois causes logicielles du 0 sont
éliminées (le scanner voit les paires, les holders et les taxes réels ;
le preflight simule la transaction complète ; la vérification Polygon
chaîne les quotes exactes). Ce qui reste est le marché :
- les memes frais de Base n'ont qu'**une seule pool** (45/45 tokens) ;
- les majors cross-venue sont efficients à **±2 bp** ;
- les seules opportunités réelles mesurées sont **11 micro-événements /
  24 h, +0,09 $/jour**.

Corriger le logiciel a rendu les mesures fiables ; cela n'a pas créé
d'edge. La prochaine étape logique n'est plus de corriger le code, mais
de décider : surveiller les paires statiques Cake↔Uni WETH/USDC (seules
avec des gaps vérifiés), ou pivoter vers une autre source d'edge
(bug bounties / audit contests, meilleur chemin $0 identifié
précédemment).

## (6) Tests (re-run 2026-11-25)

| Suite | Commande | Résultat |
|---|---|---|
| Racine | `.venv/bin/python test_v2.py` | TOUS LES TESTS V2 PASSENT (incl. nouveau test `test_scanner_token_pairs_bare_list_response`) |
| Racine | `.venv/bin/python test_morpho.py` | 14/14 |
| Racine | `.venv/bin/python test_self_funded.py` | 17/17 |
| Racine | `.venv/bin/python test_math_engine.py` | TOUS LES TESTS PASSENT |
| Racine | `.venv/bin/python test_circuit_breaker.py` | 5/5 |
| Racine | `.venv/bin/python test_gas.py` | 7/7 |
| Racine | `.venv/bin/python test_balancer.py` | 11/11 |
| Racine | `.venv/bin/python test_sponsor.py` | 12/12 |
| Racine | `.venv/bin/python test_zero_cost.py` | 15/15 |
| Fork preflight | `.venv/bin/python test_fork_preflight.py` | 3/3 (synthétique) |
| leadlag | `../.venv/bin/python -m unittest test_route_verify` | 13/13 |
| Polygon | `cd polygon && ../.venv/bin/python -m unittest discover` | 178/178 OK |

## Annexe — commandes de reproduction

```
# 1. Re-scan memes Base (code corrigé)
cd ~/workspace/crypto-base-flashloan-bot/leadlag
../.venv/bin/python remeasure_scan.py        # -> remeasure_scan_results.json
# 2. Fork preflight majors (+ candidats V2 s'il y en avait)
../.venv/bin/python remeasure_fork.py --candidates   # -> remeasure_fork_results.json
# 3. Listener Polygon 30 min (2 runs appendés, redémarrage service)
cd ../polygon
../.venv/bin/python realtime_listener.py --duration-minutes 30 --out remeasurement_signals.jsonl
# 4. Comparaison ancien vs nouveau (audit #10)
cd ../leadlag && ../.venv/bin/python remeasure_listener_compare.py
# 5. Tests
cd ~/workspace/crypto-base-flashloan-bot && .venv/bin/python test_v2.py
```
