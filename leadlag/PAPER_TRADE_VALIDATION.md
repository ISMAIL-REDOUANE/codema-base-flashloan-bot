# Validation paper-trade lead-lag — POOLS SGHAR sur Base

**Date :** 2026-11-25, run 10:43–11:13 UTC (30 min : calibration 10 min + live 20 min)
**Mode : PAPER UNIQUEMENT** — lecture seule, aucune exécution, aucun broadcast,
aucun wallet, aucune clé, aucun fond réel. **Aucune ENTRY papier n'est un profit,
un gain, ni un trade exécutable.** Les « nets » ci-dessous sont des simulations.

**Fichiers :**
- Système : `leadlag/paper_trade.py` (paires small pools, branches sans signal Binance)
- Analyseur : `leadlag/analyze_paper.py`
- Données : `leadlag/paper_entries.jsonl` (2 273 lignes), `leadlag/paper_analysis.json`
- Log : `leadlag/paper_run1.log`

---

## 1. La règle d'entrée (paroles d'Ismail + math du repo)

> « nta radir — ila kan spread kbar mn tax o dakchi, dkhol »
> (« c'est toi qui fais — si le spread est plus grand que les frais et tout, entre »)

**Règle :** net **prévu** > 0 $ après **TOUS** les coûts → ENTRY papier, sinon SKIP.
Coûts comptés (guard math du repo, `polygon_guard` / `math_engine`) :
- frais swap du **tier réel** de la pool (lu on-chain, jamais supposé),
- impact prix à la taille du trade (liquidité tick du pool, formule V3 mono-tick,
  ancrage exact QuoterV2 à 1 000 $),
- gas Base live × 2 = trade + budget revert (**0,0089 $/trade** mesuré pendant le run),
- flash 0 % Morpho.

**Seuil PAR POOL** (raffinement Ismail 10:22) : chaque pool a son propre breakeven
(fee tier + impact + gas + revert), logué dans chaque évaluation. Une pool à
0,01 % a un threshold ~0,03–0,10 %, une pool à 0,3 % ~0,60 % : la même prédiction
peut être ENTRY sur l'une et SKIP sur l'autre.

**Méthode** (raffinement Ismail 10:17) : on NE compare PAS les prix Binance vs Base.
On compare les **order books** : imbalance bid/ask Binance (`/api/v3/depth`,
`data-api.binance.vision` — `api.binance.com` = HTTP 451 depuis cette VM) →
mouvement de prix **PRÉDIT** (régression imbalance → move, calibrée pendant la
phase A) → net prévu. Base N'A PAS d'order book (Uniswap V3 = AMM) : l'équivalent
côté Base = la liquidité par tick (virtual order book). Si la corrélation mesurée
est ~0, le signal est du bruit et le système bloque les entrées.

---

## 2. Paires testées — découverte et vérification

Redirection Ismail 10:36 : **« rah kynin mouvement kbar »** (les gros mouvements
sont dans les petites pools). Sélection par GeckoTerminal (pools Uni V3 Base,
TVL 10 k$–500 k$, volume 24 h > 0, buys ET sells > 0 — anti-honeypot), puis
vérification DexScreener + on-chain (`factory.getPool` + `slot0` + liquidité)
+ listing Binance (`/api/v3/depth` — erreur = pas listé).

| Paire | Pool (vérifiée on-chain, bloc 62 063 525) | TVL | Vol 24 h | Buys / Sells 24 h | Binance |
|---|---|---|---|---|---|
| **ETH/USDC** (contrôle, major) | fee 100 `0xb4CB8009…` (L 1,09e17) | — | — | — | ETHUSDT listé |
| **SOSO/USDC** fee 100 | `0x29183f918920a2aef0115a9c7374945589968aea` (L 5,21e17) | 94 k$ | 638 k$ | 3 240 / 3 790 | **NON listé** |
| **AERO/USDC** fee 500 | `0xe5b5f522e98b5a2baae212d4da66b865b781db97` (L 2,56e17) | 129 k$ | 127 k$ | 2 523 / 2 385 | **AEROUSDT listé** |
| **ICNT/USDC** fee 500 | `0x9331f571f79d1e186a095c93756b5680a43932ac` (L 3,79e17) | 130 k$ | 291 k$ | 3 014 / 3 337 | **NON listé** |

Tokens vérifiés : SOSO `0x624e2e7f…`, AERO `0x940181a9…`, ICNT `0xE0Cd4cAc…`
(tous 18 décimales, lus on-chain). Backup non retenu : NVDAc/USDC fee 3000
(TVL 70 k$, vol 202 k$, Binance non listé, threshold ~0,6 % intéressant).

**Paires NON listées (SOSO, ICNT) :** pas de signal Binance → on mesure leurs
mouvements DEX bruts et on logue **OPPORTUNITY** (rétrospectif : le mouvement
réalisé a dépassé le seuil min de la pool) ou **MEASURE**. Une OPPORTUNITY n'est
PAS une prédiction : le mouvement a déjà eu lieu.

---

## 3. Thresholds PAR POOL (mesurés live, médiane sur 567 évaluations/pool)

| Paire | Tier | Threshold | $ à la taille optimale |
|---|---|---|---|
| ETH/USDC | 100 bps (0,01 %) | **0,0334 %** | 0,0334 $ @ 100 $ |
| ETH/USDC | 500 bps (0,05 %) | **0,1054 %** | 0,2635 $ @ 250 $ |
| ETH/USDC | 3000 bps (0,3 %) | **0,6001 %** | 12,00 $ @ 2 000 $ |
| SOSO/USDC | 100 bps (0,01 %) | **0,0993 %** | 0,0993 $ @ 100 $ |
| AERO/USDC | 500 bps (0,05 %) | **0,2337 %** | 0,2337 $ @ 100 $ |
| ICNT/USDC | 500 bps (0,05 %) | **0,2059 %** | 0,2059 $ @ 100 $ |

**Leçon :** même tier 0,01 %, SOSO a un seuil **3× celui d'ETH** (0,0993 % vs
0,0334 %) — la liquidité effective près du tick est plus fine. Le seuil n'est
pas le fee : il est mesuré par pool. (Défaut connu, voir §8 : la grille de
tailles commence à 100 $ — le vrai seuil SOSO serait ~0,073 % à 50 $.)

---

## 4. Calibration (10 min, n = 190 échantillons/paire)

**Paires listées — corrélation imbalance Binance → move Binance :**

| Paire | Bande choisie | Corrélation | Pente (% move / unité imbalance) | dt médian |
|---|---|---|---|---|
| ETH/USDC | imb05@next | 0,115 | 0,0228 | 3,0 s |
| AERO/USDC | imb01@next2 | 0,180 | 0,0326 | 3,0 s |

Corrélation faible (0,12–0,18) : le signal existe mais il est **minuscule**.
Pente ~0,02–0,03 % de mouvement par unité d'imbalance : même une imbalance
parfaite ne prédit que ~0,005–0,025 % de mouvement (voir §5).

**Paires NON listées — distribution des mouvements DEX bruts (calibration) :**

| Paire | \|move\| +1 cycle : médiane | p95 | max | max +2 cycles |
|---|---|---|---|---|
| SOSO/USDC | 0,0000 % | 0,137 % | 0,903 % | 1,204 % |
| ICNT/USDC | 0,0000 % | 0,063 % | 0,442 % | 0,442 % |

Médiane 0,0000 % : la plupart des cycles, la pool ne bouge pas du tout.
Les mouvements arrivent par **sauts atomiques** (1 trade = 1 saut).

---

## 5. Résultats live (20 min, 1 504 évaluations, 376/paire)

| Paire | Décisions | Meilleur net | Move prédit max |
|---|---|---|---|
| ETH/USDC | 376 SKIP | **−0,0275 $** (prédit) | 0,0049 % |
| AERO/USDC | 376 SKIP | **−0,2090 $** (prédit) | 0,0247 % |
| ICNT/USDC | 375 MEASURE + **1 OPPORTUNITY** | +0,0295 $ (rétrospectif) | — (pas de signal) |
| SOSO/USDC | 340 MEASURE + **36 OPPORTUNITIES** | **+0,5686 $** (rétrospectif) @ 250 $ | — (pas de signal) |

**ENTRIES papier (prédiction Binance) : 0.**
**OPPORTUNITÉS rétrospectives : 37** (36 SOSO + 1 ICNT), dont **29 événements
distincts** (28 SOSO + 1 ICNT — le même saut apparaît sur 2 cycles consécutifs).
Somme des nets rétrospectifs distincts : **2,90 $** (3,48 $ en comptant les
doublons). Directions distinctes : LONG 18, SHORT 11 — **38 % de SHORT**,
inexécutables avec le contrat actuel (LONG-only, pas de flash-borrow de l'asset).

**Pourquoi 0 ENTRY :** le mouvement prédit maximum est de 0,0049 % (ETH) et
0,0247 % (AERO) — **7× à 10× en dessous** des seuils les plus bas (0,0334 % et
0,2337 %). Le modèle ne peut pas déclencher : ce n'est pas un problème de
fenêtre, c'est le signal qui est trop faible. Sur les paires listées, 42 % des
prédictions sont SHORT (316/752) — même avec un signal plus fort, presque la
moitié serait inexécutable.

**Validation hors-échantillon (phase LIVE, prédit vs réalisé Binance) :**
ETH corr +1 cycle 0,144 / +2 cycles 0,120 ; AERO 0,158 / 0,208. Corrélation
réelle mais faible — cohérente avec la calibration. Le signal n'est pas du
bruit pur, il est juste **trop petit pour couvrir les coûts**.

---

## 6. La thèse testée : « les petites pools bougent plus »

**Mouvements DEX réalisés, phase LIVE (|move| par cycle) :**

| Paire | \|mv\| +1 cycle médiane | p95 | max | max +2 cycles | Cycles où \|move\| > seuil min |
|---|---|---|---|---|---|
| **ETH/USDC (contrôle)** | 0,0054 % | 0,0299 % | 0,0609 % | 0,0684 % | 42/376 (11,2 %) |
| AERO/USDC | 0,0000 % | 0,0257 % | 0,2678 % | 0,2678 % | 2/376 (0,5 %) |
| ICNT/USDC | 0,0000 % | 0,0630 % | 0,1879 % | 0,2358 % | 1/376 (0,3 %) |
| **SOSO/USDC** | 0,0000 % | **0,1002 %** | **0,2967 %** | **0,4269 %** | 36/376 (9,6 %) |

**Verdict — thèse PARTIELLEMENT confirmée :**
- **SOSO bouge vraiment plus :** p95 0,100 % vs 0,030 % pour ETH (3,3×),
  max 0,297 % vs 0,061 % (4,9×), max +2 cycles 0,427 % vs 0,068 % (6,2×).
- **Mais AERO et ICNT ne confirment pas :** leurs p95 (0,026 % / 0,063 %) sont
  du même ordre qu'ETH. Ce n'est pas « les petites pools » en général — c'est
  **SOSO en particulier** (le token le plus tradé des trois : 638 k$/jour).
- **Et surtout : les mouvements de SOSO sont imprévisibles avec ce système.**
  Pas de listing Binance → pas de signal order book → pas de leader. Les sauts
  sont atomiques (1 trade = 1 saut, 1 bloc). On les voit après coup, on ne peut
  pas les anticiper. Même le meilleur net rétrospectif (+0,5686 $) reste < 1 $.
- Note : ETH aussi a des mouvements réalisés au-dessus de son seuil min dans
  11,2 % des cycles — les mouvements existent partout, c'est la **prédiction**
  qui manque, pas le mouvement.

---

## 7. « Est-ce que les entrées auraient survécu au bloc suivant ? »

**Pour les ENTRY (prédiction) : sans objet — il n'y a eu aucune ENTRY.**
Rien à tester pour la survie.

**Pour les OPPORTUNITÉS (rétrospectives) :** la question ne s'applique pas non
plus — le mouvement a **déjà eu lieu** au moment où on le logue. La vraie
question est : **aurait-on pu le prédire ?** Réponse : non, avec ce système.
- SOSO/ICNT : aucun leader (pas de Binance) — rien ne précède le saut.
- AERO (listé) : les mouvements prédits (max 0,0247 %) restent 10× sous le seuil.
- Les sauts SOSO durent 1 cycle (~3 s) : même avec une prédiction parfaite,
  il faudrait entrer dans le même bloc — le cycle actuel (~3 s, depth Binance
  ~2 s) ne le permet pas.

---

## 8. Défauts connus du système (trouvés pendant ce run)

1. **Grille de tailles trop haute** (signalé par l'audit root-cause parallèle,
   vérifié) : les tailles testées commencent à 100 $ — le vrai seuil SOSO
   serait ~0,0730 % à 50 $ (surestimation de 36 %). Le gas ×2 pèse 9 % du
   seuil à 100 $. **Fix : grille dès 25 $/50 $.**
2. **SHORT inexécutable** : 42 % des prédictions sont SHORT, le contrat repo est
   LONG-only (pas de flash-borrow de l'asset). **Fix : SHORT via Morpho
   (emprunt de l'asset) ou filtrer les SHORT.**
3. **Couverture 6,6 %** : on ne regarde qu'Uni V3. Aerodrome Slipstream =
   ~79 % du volume top-20 Base — jamais quoté. C'est le trou principal
   (observation d'Ismail 11:07 : deux pools, même coin, gros écart de prix
   sur DexScreener — jamais cherché avant). Scan cross-venue en cours
   (agent parallèle).
4. **Cycle ~3,1 s** (depth Binance 1,5–2,5 s + RPC) : trop lent pour des sauts
   d'1 bloc, mais la vitesse n'est pas le goulot actuel (le signal est 10×
   trop faible — aller plus vite ne créerait pas de signal).
5. **RPC public Base fragile** (HTTP 403 par moments) — Alchemy en primaire,
   public en fallback.

---

## 9. Verdict de préparation pour le protocole 7 jours

**Critères GO (rapport lead-lag) :** ≥ 5 signaux/semaine avec net simulé > 1 $
**ET** lag médian ≥ 2 s.

| Critère | Mesuré (30 min) | Verdict |
|---|---|---|
| Signaux avec net > 1 $ | **0** (meilleur net rétrospectif 0,57 $, meilleur net prédit −0,03 $) | ✗ |
| Lag médian | ~2–4 s (mesuré précédemment, confirmé par dt_next médian 3,0 s) | ✓ |
| Entrées papier (prédiction) | 0 / 752 évaluations (paires listées) | ✗ |

**Verdict : NO-GO pour le protocole 7 jours tel quel.**
30 minutes ne suffisent pas, en principe, à juger un protocole de 7 jours —
mais la calibration montre que le problème n'est pas la fenêtre : le mouvement
prédit maximum (0,005–0,025 %) est **7× à 10× sous les seuils**. Sept jours du
**même** système mesureraient la même chose : ~0 entrée attendue, pour 0 DH
de coût (lecture seule) mais 7 jours de perdu. Le protocole 7 jours qui vaut
la peine est un **autre** système : cotation Aerodrome Slipstream + cross-venue
(Uni V3 vs Aerodrome vs PancakeSwap V3, même bloc, même paire) — c'est le
FIX N° 1 de l'audit et l'observation d'Ismail 11:07, déjà en cours par des
agents parallèles (scan cross-venue + étude des repos GitHub d'experts,
livrable `leadlag/GITHUB_EXPERT_REPOS.md`).

**Si le scan cross-venue trouve un écart réel :** protocole 7 jours sur la
paire/venue concernée, mêmes critères GO (≥ 5 signaux/sem net > 1 $).

### Commande du run 7 jours (quand le système cross-venue sera prêt)

```bash
cd ~/workspace/crypto-base-flashloan-bot
nohup .venv/bin/python leadlag/paper_trade.py --duration-minutes 10080 \
  --calibration-minutes 60 > leadlag/paper_run_7d.log 2>&1 &
```

(10 080 min = 7 jours. Calibration 60 min pour un modèle plus solide.
Le run est lecture seule — aucun risque de fond — mais il doit tourner sans
interruption : à lancer sur une machine qui ne s'arrête pas, ou en cron qui
le relance s'il tombe.)

**Note cron pour le parent :** ne pas cronner le run 30 min en boucle tel quel
(il réécrirait `paper_entries.jsonl` à chaque fois — il faudrait d'abord un
`--out` daté + une rotation des logs). Le cron utile après le scan cross-venue :
un run continu 7 jours du système cross-venue, avec relance automatique si le
processus meurt (`pgrep -f paper_trade.py || relancer`), et une analyse
quotidienne de `paper_entries.jsonl`.

---

## 10. Limites honnêtes

- **Fenêtre de 30 min, calme** : ce n'est pas le protocole 7 jours. Un événement
  rare (gros mouvement, listing, volatilité) peut ne pas apparaître en 30 min.
- **Latence REST (~950 ms)** : le prix Binance est déjà vieux d'~1 s au moment
  de l'évaluation ; la depth prend 1,5–2,5 s. Le signal arrive en retard.
- **Les ENTRY papier ignorent** la latence d'exécution, l'inclusion en bloc et
  la concurrence — **une ENTRY papier n'est pas un trade exécutable**.
- **Les OPPORTUNITÉS sont rétrospectives** : le mouvement a déjà eu lieu. Leur
  net (+0,57 $ max) n'est pas un profit — c'est ce qu'aurait rapporté un trade
  parfait, dans le bon sens, à la bonne taille, entré avant le saut. Personne
  ne peut entrer avant un saut sans signal.
- **Les nets rétrospectifs se chevauchent** : 37 opps = 29 événements distincts
  (le même saut compte 2 fois sur 2 cycles). Somme distincte 2,90 $, pas 3,48 $.
- **Une seule fenêtre, un seul jour** : SOSO bouge aujourd'hui ; rien ne dit
  qu'il bougera demain. La thèse « petites pools » n'est confirmée que sur
  1 pool sur 3, sur 30 minutes.

---

## 11. Vérification croisée (audit root-cause parallèle, 11:05)

L'audit indépendant a re-compté `paper_entries.jsonl` en cours de run et trouve
les mêmes chiffres : 19 opps SOSO à 11:05, max move 0,4269 %, max net rétro
0,5686 $ — **conformes** à cette analyse finale (37 opps, mêmes maxima).
Son verdict : le 0 est ~70 % absence réelle + ~30 % notre cécité (couverture
Uni V3 seule, seuil trop strict, SHORT inexécutable, pas de leader petites
pools). Détails : `leadlag/ROOT_CAUSE_AUDIT.md`.

---

## 12. Ce qu'il faut retenir (en une phrase)

**Ismail avait raison sur le fait — SOSO bouge 3 à 6 fois plus qu'ETH — mais
le mouvement n'est pas attrapable avec le lead-lag Binance : pas de leader,
sauts atomiques, signal 10× trop faible. Le prochain test qui compte, c'est
le cross-venue (Aerodrome vs Uni V3), pas 7 jours de plus du même système.**
