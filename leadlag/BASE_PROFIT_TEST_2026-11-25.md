# TEST PROFIT BASE — trader pro, nouveau bot GPT — 2026-11-25

> **SYNTHÉTIQUE — tous les chiffres de simulation/fork/quote ci-dessous sont des
> QUOTES, des lectures on-chain/API et des SIMULATIONS sur fork, jamais des
> trades exécutés, jamais un profit réalisé.** Les mesures dites « live » sont
> des lectures on-chain au moment indiqué ; elles ne prouvent pas qu'un trade
> aurait été exécuté. Aucun broadcast, aucun déploiement, aucun wallet, aucune
> clé, aucun fond réel. `trade --broadcast` jamais lancé (interdit : contrat
> non audité).
> Repo : `codema-base-flashloan-bot`, commit `2ce6f98` (merge GPT).
> Fenêtre : 2026-11-25 23:22–23:46 UTC. Fichiers : `scan_live_1.json`,
> `scan_hist_61989637.json`, `scan_hist_62291100.json`,
> `scan_hist_62282100.json`, `watch_chunked.jsonl` + `watch_chunked.log`
> (50 snapshots), `watch_1.jsonl` (tentative avortée, 429).

## VERDICT — NON, pas de profit réel sur Base maintenant

**Total des nets vérifiés sur la fenêtre : 0,00 $.** 0 opportunité
vérifiée, 0 net > 0 sur 1 388 quotes évaluées (72 live + 84 + 84 + 0
historiques + 1 148 watch). La seule opportunité positive vérifiée est
**historique et expirée** : +0,0260 $ au bloc 61 989 637 (Pancake → Uni,
300 $, déjà vérifiée par la validation du merge — reproduite ici à
l'identique à 0,0002 $ près). Le marché des majors reste efficient à
±2 bp : le meilleur écart spot mesuré sur la route profonde est de
**0,23 bp** (il en manque **1,77 bp** pour le breakeven de 2 bp).
Aucun gap ≥ 0,15 % (15 bp) observé nulle part.

---

## Table des résultats (brut = quotes chaînées, net = après tous coûts simulés)

| Bloc | Paire / sens | Taille | Brut (USDC) | Coûts (USDC) | Net (USDC) | Statut | Capturable ? |
|---|---|---|---|---|---|---|---|
| 62 292 875 (live) | WETH/USDC, profonds Cake↔Uni fee 100 | 100 $ | spot +0,23 bp (jamais coté : sous le seuil) | — (arrêté avant simulation, brut < 0) | — | Non coté (268/280 routes sous breakeven spot) | Non |
| 62 292 875 (live) | WETH/USDC Pancake fee 10000 → Pancake fee 100 | 100 $ | −32,09 | — | — | CHAINED_QUOTE_LOSS | Non (impact pool mince) |
| 61 989 637 (hist.) | USDC/WETH Pancake 100 → Uni 100 | 300 $ | +0,039188 | 0,013152 (gas 634 914 u. @ 0,01 gwei + L1 + marge 1,25) | **+0,0260357** | HISTORICAL_VERIFIED | **Non — expirée** (expires bloc 61 989 639) |
| 61 989 637 (hist.) | USDC/WETH Pancake 100 → Uni 100 | 100 $ | +0,020081 | 0,012713 | +0,0073677 | BELOW_MIN_NET (min 0,01) | Non — expirée + sous le seuil |
| 61 989 637 (hist.) | WETH/USDC Uni 100 → Pancake 100 | 100 $ | +0,020086 | 0,012535 | +0,0075516 | BELOW_MIN_NET (min 0,01) | Non — expirée + sous le seuil |
| 62 299 759 (watch) | cbBTC/WETH Pancake 100 → Uni 100 | 100 $ | −0,2611 (−26,11 bp) | — | — | CHAINED_QUOTE_LOSS | Non (impact ≈ −30 bp, pool vente mince) |
| 62 299 759 (watch) | cbBTC/WETH Pancake 100 → Uni 100 | 300 $ | −2,5784 (−85,95 bp) | — | — | CHAINED_QUOTE_LOSS | Non (impact croît avec la taille) |

---

## (1) Scan live (lecture seule) — bloc 62 292 875, 23:22:26 UTC

Commande : `bot.py scan --sizes 10,30,100,300,1000,3000` (RPC Alchemy —
le RPC public par défaut a refusé : « batch RPC unavailable »).

- 22 pools découverts, 280 routes énumérées, **268 (95,7 %) sous le
  breakeven spot** (écart marginal ≤ frais) → jamais cotées.
- **72 quotes évaluées, 0 profitable, toutes CHAINED_QUOTE_LOSS.**
- Meilleurs bruts par taille (tous négatifs, tous sur des pools minces
  fee 10000, 1 % de frais + impact) : 10 $ → −0,468 ; 30 $ → −3,85 ;
  100 $ → −32,09 ; 300 $ → −152,34 ; 1 000 $ → −819,24 ;
  3 000 $ → −2 813,36. L'impact explose avec la taille : ces routes ne
  sont pas des near-miss, ce sont des pièges de liquidité.
- **Vrai near-miss (route profonde, calculé live depuis les sqrtPrice
  du scan)** : Uni WETH/USDC fee 100 `0xb4CB…` = 1 688,5337 $/WETH ;
  Pancake WETH/USDC fee 100 `0x72AB…` = 1 688,5734 $/WETH.
  **Écart spot : 0,23 bp. Breakeven : 2 bp (1 + 1). Il manque 1,77 bp.**
- Âge du snapshot à la fin du scan : 25 blocs (voir §6 : 200 ms/bloc).

## (2) Scans historiques (lecture seule)

### Bloc 61 989 637 — reproduction de la baseline : RÉUSSIE

- 84 quotes : **1 HISTORICAL_VERIFIED**, 9 BELOW_MIN_NET, 29
  CHAINED_QUOTE_LOSS, 45 UNAVAILABLE (voir ci-dessous).
- Vérifiée : Pancake 100 → Uni 100, USDC/WETH, 300 $, brut +0,039188,
  coûts 0,013152 $, **net +0,0260357 $** (simulation atomique fork
  Anvil, Morpho remboursé, expires bloc 61 989 639 — **expirée**).
  Baseline du merge : net 0,0262022 $ — écart 0,00017 $ (gas/oracle),
  brut identique. **Preuve reproduite.**
- Les 2 autres nets positifs sont sous le seuil min_net 0,01 $ :
  +0,00737 $ (même sens, 100 $) et +0,00755 $ (sens inverse, 100 $).
  La validation du merge annonçait « 2 HISTORICAL_VERIFIED » : en
  réalité 1 vérifiée + 1 positive sous le seuil — même conclusion.
- **45/84 UNAVAILABLE (« sell quote unavailable »)**, réparties sur
  toutes les venues/frais/paires : pas un pool en cause, des appels
  d'archive qui échouent par grappes (RPC). Même au bloc de référence,
  la couverture des quotes n'est que partielle.

### Bloc 62 291 100 (~1 h avant le live) — NON MESURABLE

- 84 quotes, **84 UNAVAILABLE** (50 « sell quote unavailable »,
  34 « buy quote unavailable »). Découverte OK, toutes les quotes
  échouent. Cause : couche RPC (archive / rate-limit), pas le marché.
  **Ce n'est pas un « 0 opportunité », c'est un « 0 mesuré ».**

### Bloc 62 282 100 (~6 h avant le live) — NON MESURABLE

- 14/22 pools découverts (10 « pool state unavailable »),
  152 routes, **0 quote** (toutes sous breakeven spot). Même cause :
  lectures d'état d'archive qui échouent. Non mesurable.

## (3) Watch borné 20 min (lecture seule) — 50 snapshots

Méthode : driver chunqué anti-429 (prescrit par le diagnostic parent) —
`scan()` en processus, tailles [100, 300] (les tailles prouvées des
opportunités de référence), pause 20 s, retry backoff 20/40/80 s sur
429. 23:25:48 → 23:45:54 UTC, blocs 62 293 851 → 62 299 882.

- **50/50 snapshots réussis, 0 échec, 0 retry fatal.**
- **14 000 routes énumérées, 13 426 (95,9 %) sous breakeven spot,
  1 148 quotes évaluées, 0 profitable, 0 net > 0.**
- Statuts : 1 146 CHAINED_QUOTE_LOSS, 2 UNAVAILABLE (0,17 %, bloc
  62 293 972, « sell quote unavailable »).
- **Meilleur brut : −0,2611 $ @ 100 $ (−26,11 bp)**, cbBTC/WETH
  Pancake 100 → Uni 100, bloc 62 299 759. Détail : écart spot
  +6,15 bp, frais 2 bp, **impact ≈ −30 bp** — la pool de vente
  (Uni, liquidité 3,27e13) est ~3 500× plus mince que la pool
  d'achat (Pancake, 1,14e17). L'écart marginal existe, l'exécution
  le tue.
- Meilleur brut @ 300 $ : −2,5784 $ (−85,95 bp), même route —
  l'impact croît avec la taille.
- Médiane du meilleur brut @ 100 $ par snapshot : −0,2973 $
  (−29,7 bp). Par paire, meilleur brut : USDC/WETH −3,24 $ ;
  WETH/USDC −3,25 $ ; USDC/cbBTC −0,29 $ ; cbBTC/WETH −0,26 $.
- **Aucun gap ≥ 0,15 % (15 bp) :** le plus grand écart spot impliqué
  est +6,15 bp (route mince, inexécutable) ; la route profonde est à
  +0,23 bp. Même le meilleur spot est 2,4× sous 15 bp.
- Âge snapshot : 16–23 blocs, médiane 19 (3,2–4,6 s). Scan : 3,9–5,3 s.
- Couverture : **50 blocs observés sur 6 031 écoulés = 0,83 %.**
  Un gap qui vit 5–25 s = 25–125 blocs ; l'échantillonnage (1 bloc /
  ~120) rate la plupart des gaps par construction. Borne honnête,
  pas une preuve d'absence.

## (4) Vérification des candidats — rien à vérifier

Aucun net > 0 trouvé : aucune simulation fork supplémentaire n'a été
déclenchée au-delà de celle qu'exécute déjà `scan()` (tout brut > 0
est simulé atomiquement sur fork Anvil ; aucun brut > 0 en live/watch).
Aucun `prepare` possible : il exige un contrat déployé sur mainnet —
il n'y en a aucun — et un candidat net > 0 — il n'y en a aucun.
La preuve historique a déjà été reproduite (§2) : le pipeline de
vérification fonctionne, il n'y avait rien à vérifier en live.

## (5) Comparaison avec les baselines

| Mesure | Baseline (route verification, 3b7bce3) | Ce test (nouveau bot) |
|---|---|---|
| Opportunités réelles / 24 h | 11 micro-opps, total +0,0928 $, meilleur +0,0177 $ | 0 en 20 min live ; 1 historique vérifiée +0,0260 $ (expirée) |
| Meilleur net vérifié | +0,0177 $ @ 100 $ | +0,0260 $ @ 300 $ (bloc 61 989 637, expiré) |
| Marché | Efficient à ±2 bp | Efficient à ±2 bp (écart profond 0,23 bp) |
| Gaps ≥ 0,15 % | Non mesurés | **Aucun observé** (max spot +6,15 bp, route mince) |

**Le nouveau bot trouve PAREIL, pas plus :** le même 0, mesuré avec
plus de précision (quotes chaînées sortie-achat → entrée-vente,
vérification fork atomique, coûts L2+L1 + marge). Corriger le logiciel
et changer de bot n'a pas créé d'edge — le marché est le même.

## (6) Découverte structurelle — Denim : les blocs font 200 ms

**Mesuré live par mes soins : 5,05 blocs/s** (51 blocs en 10,1 s,
confirmé sur 6 minutes de watch). Sources publiques : upgrade Denim
de Base, mainnet 5 nov 2026, bloc 53 556 127 — blocs de 2 s → **200 ms**,
5 blocs/s (base.org/blog/denim, The Block, Unchained).

Conséquence directe : **le budget de fraîcheur du bot (2 blocs) vaut
désormais 0,4 seconde** (c'était 4 s avant Denim). Un scan prend
4–5 s, soit ~25 blocs : **chaque snapshot est 16–23 blocs vieux à sa
fin, soit 8–11× le budget**. Même si un SIMULATED_OPPORTUNITY
apparaissait, il serait expiré avant la fin du scan — et `prepare`
refuserait une préparation périmée. La boucle actuelle ne peut pas
capturer un gap de 5–25 s : il faudrait une boucle complète (découverte
+ quotes + simulation + préparation + envoi) sous 0,4 s. Ce n'est pas
un problème de latence marginale, c'est un changement de régime.

## (7) RPC — le vrai goulot (mesuré, pas supposé)

- **RPC public par défaut (publicnode) : inutilisable pour ce bot**
  — « batch RPC unavailable » (l'endpoint refuse les batches).
- **Alchemy (tier gratuit, config.yaml) : 429 Too Many Requests**
  sur les bursts du full scan (confirmé par le parent : traceback
  web3 `raise_for_status` → HTTPError 429 ; batches directs de 3 et
  50 → HTTP 200 ; petit scan max_routes=5 OK). Le transport batch
  fonctionne ; c'est le volume en rafale qui déclenche le 429.
- Remède appliqué et validé : scan chunqué (2 tailles), pause 20 s,
  backoff 20/40/80 s → **50/50 snapshots, 0 échec**.
- Les scans historiques restent fragiles sur le tier gratuit
  (62 291 100 et 62 282 100 non mesurables). Un scan qui échoue par
  manque de RPC n'est pas un « 0 opportunité ».

## (8) Tests (re-run 2026-11-25, pendant le watch, sans RPC)

| Suite | Commande | Résultat |
|---|---|---|
| Nouveau moteur GPT | `.venv/bin/python -m pytest tests -q` | **23 passed** |
| Régressions (live exclus) | `.venv/bin/python -m pytest test_math_engine.py test_gas.py test_v2.py test_balancer.py test_morpho.py test_sponsor.py test_zero_cost.py test_circuit_breaker.py test_self_funded.py leadlag/test_route_verify.py polygon -k 'not live' -q` | **307 passed, 12 deselected** |

Suite identique à la validation du merge (307 passed) — reproduite à
l'identique. `test_v2` vert (incl. test de régression bare-list),
`test_morpho` 14/14, `polygon` 178/178, `leadlag/test_route_verify`
13/13 inclus dans les 307.

## (9) VERDICT FINAL

**Il n'y a pas de profit réel sur Base maintenant, avec ce bot et
cette infrastructure.**

- Total nets vérifiés sur la fenêtre (live + watch 20 min) : **0,00 $**.
- Seule opportunité positive vérifiée : **+0,0260 $, historique,
  expirée** (bloc 61 989 637).
- Il manque **1,77 bp** sur la route profonde (écart 0,23 bp vs
  breakeven 2 bp). Pour +1 $ par trade de 100 $, il faudrait des gaps
  ~100 bp plus grands que le meilleur gap statique observé (0,085 %) —
  inchangé depuis la route verification.
- **Deux blocages structurels, pas un seul :** (a) l'edge n'existe pas
  (marché efficient à ±2 bp) ; (b) même s'il existait, la boucle
  actuelle ne peut pas le capturer — budget 2 blocs = 0,4 s post-Denim
  contre 4–5 s par scan, et RPC gratuit qui 429 en rafale.
- Ce que ce test ne prouve pas : l'absence de gaps < 5 s ou
  intra-bloc (couverture watch 0,83 % des blocs ; replay antérieur
  3,99 %). Ce qu'il prouve : sur 1 388 quotes évaluées avec la
  méthode la plus stricte disponible (quotes chaînées + fork), rien
  ne passe, et la route profonde est à 1,77 bp du breakeven.

## Annexe — reproduction

```
# 1. Scan live (RPC Alchemy via config.yaml, jamais affiché)
.venv/bin/python bot.py scan --sizes 10,30,100,300,1000,3000   # BASE_RPC_URL=<alchemy>
# 2. Bloc historique de référence
.venv/bin/python bot.py scan --block 61989637 --sizes 10,30,100,300,1000,3000
# 3. Watch chunqué anti-429 (driver /tmp/watch_chunked.py, 50 snapshots, tailles 100/300)
.venv/bin/python /tmp/watch_chunked.py 50
# 4. Tests
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest test_math_engine.py test_gas.py test_v2.py test_balancer.py test_morpho.py test_sponsor.py test_zero_cost.py test_circuit_breaker.py test_self_funded.py leadlag/test_route_verify.py polygon -k 'not live' -q
```

## Fichiers de ce test (repo, non commités — le parent s'en charge)

`leadlag/BASE_PROFIT_TEST_2026-11-25.md` (ce rapport),
`scan_live_1.json`, `scan_hist_61989637.json`, `scan_hist_62291100.json`,
`scan_hist_62282100.json`, `watch_chunked.jsonl`, `watch_chunked.log`,
`watch_1.jsonl` + `watch_1.err` (tentative avortée par 429).
Drivers éphémères : `/tmp/run_scan.py`, `/tmp/watch_chunked.py`.
