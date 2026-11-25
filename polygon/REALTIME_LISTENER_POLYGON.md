# Ecoute temps reel Polygon v4.4 — newHeads + Multicall3

Date : 2026-11-25 00:08–00:38 UTC — run live 30 min, blocs 97906575 → ~97907751.
Mode : MONITOR-ONLY (lecture seule + eth_call, aucun envoi, aucun portefeuille,
aucune cle). La porte d'audit avant tout usage live reste en place.

## VERDICT

**0 signal net > 0 $ sur 14 265 quotes, 431 blocs traites.**
L'ecoute temps reel fonctionne (websocket stable, 0 deconnexion), mais ce run
ne prouve PAS qu'aucune opportunite n'a existe : **couverture ~37 % seulement**
des blocs ecoules (voir § Fiabilite — le repli rotation a fait perdre ~63 %
des blocs apres UNE erreur Multicall). Sur les 431 blocs evalues, rien que
le polling n'aurait manque : le meilleur net mesure est **-0,0164 $**
(GHST/USDT, artefact reserves virtuelles, comme en pro-scan).

## Architecture

```
wss newHeads (drpc) ──> file de blocs ──> worker ──> 1x Multicall3 aggregate3
   (~2 s/bloc, baseFee)                      (~78 lectures d'etat)
                                                    │
                                              calcul local (reserves
                                              virtuelles + polygon_guard)
                                                    │
                                              net > 0 $ ? ──> signal JSONL
                                              (re-verifie par quote exacte
                                              QuoterV2 / getAmountsOut
                                              quand possible)
```

- **Transport** : `wss://polygon.drpc.org` (verifie : abonnement newHeads OK,
  headers avec baseFeePerGas) ; repli `wss://polygon-bor-rpc.publicnode.com`
  (verifie aussi). BlastAPI = 403, polygon-rpc.com = 401 (cle requise).
  Reconnexion avec backoff 1/2/4/8/16/30 s, max 10 tentatives, puis arret
  propre (fail-closed). Si aucun wss : polling `eth_blockNumber` / 2 s.
- **Couverture par bloc** : 15 paires, 44 venues (inventaire charge depuis
  le dernier `pro_scan_measurement_*.json` ; tokens resolus une fois au
  demarrage : majors via big_pools, mid-caps via pro_scan.resolve_midcap,
  watchlist via watchlist.json + verification on-chain ; jamais devines).
  - intra-Uni : 4 paires majors, tiers V3 0,01/0,05/0,3/1 % + V4
  - mid-caps : LINK, AAVE, GHST, SAND, QUICK (MAI absente de l'inventaire
    pro-scan : paires non resolues, SKIP)
  - watchlist : axlUSDC/USDC
  - tailles : 1 000 / 5 000 / 20 000 $ ; regle net > 0 $ (polygon_guard v4.1 :
    flash 0 %, frais swap, gas + budget revert ; gas = baseFee du bloc,
    sinon 279 gwei / 0,0095 $ prudent ; prix MATIC rafraichi / 10 min).
- **Efficacite** : 1 appel `aggregate3` par bloc (~78 sous-appels : V2
  getReserves x1, V3 slot0+liquidite x2, Algebra globalState+liquidite x2,
  V4 extsload x2 ; Multicall3 `0xcA11...CA11` verifie : 3 808 o de code).
  Etats lus AU bloc de l'en-tete (`block_identifier`) quand le RPC le
  permet. Aucun appel DexScreener/CoinGecko par bloc.
- **Methode de quote** : reserves virtuelles locales (exacte pour V2 ;
  approximation documentee pour V3-concentre/Algebra/V4 — meme methode
  que big_pools.py / pro_scan.py). Un signal est re-verifie par quote
  exacte (QuoterV2 / getAmountsOut) quand la venue le permet ; sinon
  `verification: null`.

## Resultats du run 30 min (2026-11-25 00:08:49–00:38:52 UTC)

| Metrique | Valeur |
|---|---|
| Transport | ws `wss://polygon.drpc.org`, 0 deconnexion, 0 reconnexion |
| Blocs traites | 431 |
| Blocs ecoules (est.) | ~1 176 (cadence mesuree ~1,53 s/bloc) |
| Couverture | ~37 % |
| Quotes (paire x taille) | 14 265 (39/bloc en mode Multicall) |
| Signaux net > 0 $ | **0** (0 verifie) |
| Meilleur net | -0,0164 $ (GHST/USDT, $1k/$5k/$20k, bloc 97907158) |
| Erreurs RPC | 1 (1 appel Multicall en echec) |
| Latence bloc -> quote | moy. 3 561 ms, max 35 908 ms (faussee par le mode rotation, voir ci-dessous) |
| Latence en mode Multicall | ~470–493 ms (300 premiers blocs) |

Phases du run :
1. **Blocs 1–300 (~00:08–00:16, mode Multicall)** : parfait — 0 bloc manque,
   39 quotes/bloc, latence 470–493 ms < 2 s. Le design tient la cadence.
2. **Apres 1 erreur Multicall (~00:16)** : bascule definitive en mode
   rotation (5 paires/bloc, lectures individuelles) — 9 a 13 s/bloc,
   file d'attente saturee, ~745 blocs reellement manques. C'est LA cause
   de la couverture de 37 %.

## Defauts trouves par ce run (et corriges)

1. **Bascule rotation trop brutale** : UNE erreur Multicall (transitoire,
   cause sous-jacente avalee — non loguee) faisait basculer definitivement
   en rotation, incapable de tenir 2 s/bloc. Corrige : 3 tentatives
   aggregate3 (0,5 s d'intervalle) avant bascule + log de l'erreur
   sous-jacente (`MULTICALL_RETRIES = 3`, tests ajoutes).
2. **Compteur de blocs manques gonfle (~2x)** : la file d'attente ET le
   calcul d'ecart comptaient les memes blocs abandonnes. Corrige : une
   seule source de verite (ecart entre blocs traites) ; le compteur du
   run (1 478) est donc surestime — couverture reelle ~37 %, pas 23 %.
   (Test de regression ajoute : ecart de 4 blocs = 4 manques.)
3. **Latence `--once` variable** : 332 ms au premier smoke test, 2 492 ms
   au second — variabilite du RPC public drpc (l'agent pro-scan tournait
   en parallele). A surveiller : un RPC dedie (Alchemy avec Polygon
   active) stabiliserait la latence.

## Ce que ce run ne prouve pas

- Avec 37 % de couverture, une opportunite de quelques secondes a pu
  exister dans un bloc non evalue. Le verdict « 0 signal » vaut pour les
  431 blocs evalues, pas pour toute la fenetre.
- La methode reserves virtuelles sous-estime les spreads sur pools
  concentres fins (ex. GHST/USDT : spread affiche -99,85 % — artefact
  connu, meme en pro-scan). Un signal passe par cette methode serait
  re-verifie par quote exacte avant toute conclusion.
- **Recommandation** : second run 30 min avec les correctifs ci-dessus
  (retry Multicall) pour mesurer la couverture reelle en mode nominal ;
  si la couverture reste < 90 %, passer a un RPC dedie.

## Fichiers

- `realtime_listener.py` — listener (CLI : `--duration-minutes 30`,
  `--once`, `--live`, `--transport {ws,poll}`, `--out`, `--max-reconnects`)
- `test_realtime_listener.py` — **19/19 tests verts** (handler, cas
  synthetique positif EXECUTE, batching Multicall, rotation, retry
  Multicall, backoff fail-closed, comptage des manques, check statique
  no-broadcast)
- `realtime_signals.jsonl` — 6 lignes : run_start, 4 stats (tous les
  100 blocs), run_end (0 signal)
- `realtime_run_2026-11-25.log` — log complet du run
