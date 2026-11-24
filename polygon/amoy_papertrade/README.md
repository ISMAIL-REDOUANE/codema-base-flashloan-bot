# Paper-trade Polygon Amoy — Détecteur lecture seule (v4.0)

**Testnet Amoy (chaîne 80002) UNIQUEMENT. Lecture seule. Aucun broadcast,
aucun wallet, aucune clé privée, aucun fonds réel. Simulation seulement.**

Ce dossier est le paper-trade du bot Polygon v4.0 (port Base → Polygon,
flash loan Morpho 0 %, float 1,31 $ MATIC). Il ne touche à RIEN d'autre :
ni aux fichiers Base, ni aux fichiers mainnet Polygon (`polygon/`).

---

## État vérifié le 2026-11-24 — lire d'abord

| Élément | Résultat |
|---|---|
| RPC officiel `rpc-amoy.polygon.technology` | **INJOIGNABLE** depuis ce sandbox (HTTP 000, 2 tentatives, 22:26 UTC) |
| RPC `polygon-amoy.drpc.org` | ✅ répond — chainId `0x13882` = 80002, bloc 53 736 523 |
| RPC `polygon-amoy-bor-rpc.publicnode.com` | ✅ répond — chainId `0x13882` = 80002 |
| RPC Ankr | ❌ exige une clé API — exclu |
| Gas Amoy live | ~60,2 gwei → 1 trade (450 000 unités) = **0,027 POL de test** |
| Activité chaîne | bloc 53 736 523 = 12 txs ; bloc −5 = 15 txs (chaîne vivante, trafic faible) |
| Uniswap V3 (factory `0x1F98…`) | ❌ **pas de code** sur Amoy ; absent de la liste officielle Uniswap (41 réseaux, `developers.uniswap.org/deployments`, vérifié 2026-11-24) |
| Uniswap V4 (PoolManager `0x6736…`) | ❌ **pas de code** sur Amoy |
| QuickSwap V2 (factory `0x5757…`, router `0xa5E0…`) | ❌ **pas de code** sur Amoy ; docs QuickSwap : Mainnet + Mumbai (déprécié) seulement |
| QuickSwap V3 (factory `0x411b…`) | ❌ **pas de code** sur Amoy |
| Sushi V2 (factory `0xc35D…`, router `0x1b02…`) | ❌ **pas de code** sur Amoy |
| Pancake V3 (factory `0x0BFb…`) | ❌ **pas de code** sur Amoy |
| Morpho Polygon (`0x1bF0…`) | ❌ **pas de code** sur Amoy (pertinent pour les tests de contrat futurs) |
| Aave V3 Pool mainnet (`0x794a…`) | ❌ **pas de code** sur Amoy |
| GeckoTerminal / DexScreener | ❌ **aucun support Amoy** (GeckoTerminal : `polygon_pos` et `polygon-zkevm` seulement) |
| Mainnet : tokens à 2 venues | **0** (scan 2026-11-24 : 0 candidat sur 80 pools) — la watchlist Amoy est donc vide aussi |

**Conséquence honnête : le détecteur tourne, mais il n'a RIEN à poller sur
Amoy aujourd'hui.** Ce n'est pas un bug : Amoy n'héberge aucun DEX de
production. Un paper-trade de 2–4 semaines sur Amoy mesurerait 0
opportunité — il ne peut pas valider le marché. Voir « Ce que le
paper-trade peut et ne peut pas prouver » ci-dessous.

---

## Comment lancer le détecteur

```bash
cd ~/workspace/crypto-base-flashloan-bot/polygon/amoy_papertrade

# 1 cycle (vérification rapide)
python3 amoy_detector.py --once

# Vérifier juste la présence des venues (eth_getCode)
python3 amoy_detector.py --discover

# Boucle 10 minutes (smoke test)
python3 amoy_detector.py --duration-minutes 10

# Boucle continue toutes les 60 s (Ctrl+C pour stopper)
python3 amoy_detector.py --loop
```

Python 3 système + `requests` + `PyYAML` suffisent (aucun wallet, aucun
`web3.py`). Le script ne contient **aucun code de signature** : que des
`eth_call` / `eth_getCode` / `eth_blockNumber` / `eth_gasPrice`.

## Comment lire les logs

| Fichier | Contenu |
|---|---|
| `amoy_detector.log` | journal texte horodaté de chaque cycle (bloc, gas, venues présentes/absentes, paires, spreads) |
| `amoy_opportunities.jsonl` | **1 ligne JSON par opportunité SIMULÉE à net > 0 $ après TOUS les coûts** (flash 0 %, swap, gas, budget revert) : timestamp, paire, venues, spread %, loan optimal, net simulé exact, `gte_3_usd` (true si net ≥ 3 $), gas (POL test + $ simulés). Vide tant qu'aucune venue n'existe. |
| `daily_summary.json` | compteurs par jour : cycles, paires vérifiées, spreads vus, **net ≤ 0 $ (compteur seulement, jamais de détail)**, opps net > 0 $, opps ≥ 3 $, spread max, venues présentes/absentes, erreurs RPC. |

« $ simulés » = le POL de test est valorisé au prix MATIC mainnet
(0,0758 $ le 2026-11-24) **comme référence seulement** — le POL de test
vaut 0 $ en réalité. Deux compteurs sont rapportés séparément : le
nombre d'opportunités simulées **à net > 0 $** (toute rentabilité, même
infime) et le nombre d'opportunités **≥ 3 $** (les significatives).
Le chiffre qui compte pour le STOP RULE est le **nombre
d'opportunités simulées ≥ 3 $ par semaine**, pas leur valeur $.

## RÈGLE D'ARRÊT (STOP RULE)

**Si moins de 1 opportunité simulée ≥ 3 $ par semaine → STOP.
Ne pas financer le mainnet. Le marché est mort pour ce bot.**

**Changement de règle 2026-11-24 (Ismail) :** le min profit de 3 $ est
ABANDONNÉ comme seuil de journalisation — le détecteur logue désormais
TOUTE opportunité simulée à net > 0 $ après tous les coûts (flash 0 %,
swap, gas, budget revert = 1 × gas), avec son net exact et un flag
`gte_3_usd`. La RÈGLE D'ARRÊT ci-dessus ne change pas : elle reste
évaluée sur les opps ≥ 3 $ — mais le compte des opps à net > 0 $ est
rapporté séparément (il montre s'il existe au moins une activité
rentable, même sous 3 $).

C'est la règle du plan de recherche initial (étape 1 : détecteur
lecture seule, 2–4 semaines). Elle s'applique au paper-trade **mainnet**
(voir ci-dessous) : sur Amoy, le compteur restera à 0 tant qu'aucun DEX
n'y est déployé, ce qui ne prouve rien sur le marché mainnet — ça prouve
seulement qu'Amoy est vide.

## Ce que le paper-trade peut et ne peut pas prouver

- ✅ **Peut prouver :** le pipeline de détection fonctionne (RPC, lecture
  des pools, calcul du spread, journalisation) ; une venue qui apparaît
  sur Amoy serait détectée automatiquement au cycle suivant.
- ❌ **Ne peut PAS prouver sur Amoy :** la fréquence réelle des
  opportunités (pas de DEX, pas de pools, pas de memes sur Amoy).
- ➡️ **Le vrai paper-trade du marché, c'est le mainnet en lecture seule :**
  `scanner_polygon.py` (toutes les 2–4 h) + calcul `decide()` — on
  observe les pools mainnet, on simule, on ne broadcast RIEN. C'est
  exactement ce que fait déjà le scan mainnet (0 deux-venues le
  2026-11-24). Si ce compteur reste à 0 pendant 2–4 semaines → STOP,
  ne pas financer le mainnet.
- ➡️ **Les tests de contrat sur Amoy** (exécuter le flash loan pour de
  faux) exigent un pas supplémentaire : déployer soi-même des pools de
  test sur Amoy (factory V2 + tokens de test) avec du POL du faucet.
  Ce n'est PAS de la détection lecture seule — c'est une étape séparée,
  à décider explicitement, jamais automatique.

## Faucets Amoy (pour plus tard — NE RIEN FINANCER MAINTENANT)

Source : docs officiels Polygon, page « Test token faucets »
(`docs.polygon.technology/tools/gas/matic-faucet`, mise à jour
2026-11-12). **Ne créer aucun wallet et ne réclamer aucun token
maintenant** — ces liens servent uniquement quand l'étape « déployer des
pools de test » sera décidée.

| Faucet | Réseau / token | Lien |
|---|---|---|
| Polygon Faucet (officiel) | Amoy → **POL** | https://faucet.polygon.technology |
| Alchemy Faucet | Amoy → POL | via `alchemy.com` (lien « Alchemy Polygon Amoy POL faucet » depuis la page docs ci-dessus) |
| QuickNode Polygon Faucet | Amoy | https://faucet.quicknode.com |
| GetBlock Faucet | Amoy | https://getblock.io |
| StakePool Faucet | Amoy | https://faucet.stakepool.dev.br |

Notes : le token de gas Amoy est le **POL** (migration MATIC → POL,
sept. 2024 ; certaines configs affichent encore « MATIC »). Les
faucets donnent ~0,1–0,5 POL par demande (limites journalières).
Explorateur Amoy : https://amoy.polygonscan.com.

## Fichiers

| Fichier | Rôle |
|---|---|
| `amoy_config.yaml` | chaîne 80002, RPCs, règles (copiées de `polygon_config.yaml`), venues + preuves d'absence, watchlist (vide) |
| `amoy_detector.py` | détecteur lecture seule (`--once` / `--loop` / `--duration-minutes N` / `--discover`) |
| `amoy_opportunities.jsonl` | opportunités simulées à net > 0 $ après tous les coûts (créé au premier hit ; vide sinon) |
| `daily_summary.json` | compteurs journaliers (créé au premier cycle) |
| `amoy_detector.log` | journal des cycles |
| `SMOKE_TEST.md` | résultat du smoke test 10 min (2026-11-24) |
| `README.md` | ce fichier |
