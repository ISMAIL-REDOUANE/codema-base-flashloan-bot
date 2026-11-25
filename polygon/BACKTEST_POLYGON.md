# BACKTEST Polygon v4.3 — les opportunités PASSÉES (7 jours)

Date : 2026-11-24 ~23:57 UTC — **Phase 1 TERMINÉE, Phase 2 ARRÊTÉE.**

## VERDICT

**AUCUN BACKTEST HISTORIQUE N'EST POSSIBLE depuis ce sandbox : aucune
source d'état historique ne fonctionne.** Il n'y a donc AUCUNE liste
d'opportunités passées à montrer — et on n'en a INVENTÉ aucune.

Le seul signal qui reste est le scan live (lecture seule, mainnet),
comme décidé par Ismail (« signal = scan mainnet ghir, bla Amoy »).

## Phase 1 — chemins de données testés (preuves, pas des suppositions)

Méthode de test : `eth_call` slot0() sur la pool Uni V3 WMATIC/USDC.e
`0xA374094527e1673A86dE625aa59517c5dE346d32` au bloc d'il y a 7 jours
(bloc ~97 603 568), plus `eth_blockNumber` / `get_block` (baseFee).
Probes : `/tmp/probe_history.py`, `/tmp/probe_history2.py`.

| Source | Test | Résultat |
|---|---|---|
| drpc `polygon.drpc.org` — archive 7j | slot0 @ bloc -302 400 | **ÉCHEC** — HTTP 400, erreur code 27 : `Unknown state. First available state is 1` |
| drpc — fenêtre d'archive | slot0 @ -128 / -200 / -256 / -500 / -1000 | -128 OK, **-200 et au-delà ÉCHEC** — fenêtre utile = **~128 derniers blocs (~4 min)** |
| drpc — 1er probe (23:53) | slot0 @ bloc -302 400 | **1 succès isolé** (tick -301484, baseFee 246 gwei) — **jamais reproduit** (5+ tentatives ensuite, toutes 400). Cause probable : load-balancing drpc vers un nœud archive une fois, puis nœuds prunés. **Non utilisable.** |
| publicnode `polygon-bor-rpc.publicnode.com` — archive | slot0 @ -7j et -1j | **ÉCHEC** — HTTP 403 Cloudflare (get_block OK, mais pas eth_call archive) |
| BlastAPI public | eth_call @ -7j et latest | **ÉCHEC** — HTTP 403 : « Blast API is no longer available. Please update your integration to use Alchemy's API » |
| Ankr public `rpc.ankr.com/polygon` | eth_call @ -7j et latest | **ÉCHEC** — « Unauthorized: You must authenticate your request with an API key » |
| 1RPC `1rpc.io/matic` | eth_call @ -7j et latest | **ÉCHEC** — « You've reached the usage limit for your current plan » (quota IP partagé épuisé) |
| LlamaRPC `polygon.llamarpc.com` | eth_call @ -7j et latest | **ÉCHEC** — connexion coupée (RemoteDisconnected) |
| publicnode `polygon-bor.publicnode.com` | eth_call | **ÉCHEC** — erreurs proxy/connexion |
| Matic officiel `rpc-mainnet.matic.network` | eth_call | **ÉCHEC** — erreurs proxy/connexion |
| polygon-rpc.com | eth_call | **ÉCHEC** — réponse non-JSON |
| Alchemy (clé de `../config.yaml`) | `polygon-mainnet.g.alchemy.com` | **ÉCHEC** — `MATIC_MAINNET is not enabled for this app` (la clé existe mais le réseau Polygon n'est pas activé sur l'app « Base-Bot » ; l'app n'a que Base + Sepolia). La clé n'a été ni affichée, ni loguée, ni codée en dur. |
| The Graph hébergé (Uniswap V3 Polygon) | requête pools | **ÉCHEC** — connexion refusée (service hébergé arrêté ; le réseau décentralisé exige une clé API) |
| GeckoTerminal OHLCV | `pools/{pool}/ohlcv/day` | **OK** (bougies journalières) — mais **non utilisable comme preuve de spread** : les closes de deux pools ne sont pas simultanées (dernier trade de chaque pool, à des moments différents) — un « spread » calculé dessus serait un artefact, pas une opportunité exécutable. Non utilisé. |
| DexScreener token-pairs | paires WMATIC | **OK** — état ACTUEL seulement (découverte des venues, pas d'historique) |

## Ce qui débloquerait un vrai backtest (action côté Ismail, $0)

**Option 1 — Alchemy (recommandée, gratuite) :** sur
dashboard.alchemy.com, app « Base-Bot » (compte
Ismailredouane97@gmail.com), activer le réseau **Polygon Mainnet
(MATIC_MAINNET)** — ou créer une app gratuite avec Polygon activé.
Ensuite la même clé sert `polygon-mainnet.g.alchemy.com` et l'archive
complète devient disponible (Alchemy sert l'historique complet même
en free tier). Re-tester alors : `eth_call` slot0 @ bloc -7j.

**Option 2 — clé API gratuite ailleurs :** Ankr (compte gratuit, clé
personnelle), Chainstack ou QuickNode (trial gratuit) — n'importe quel
endpoint archive Polygon.

Une fois une source archive disponible, le replay est direct : les
fonctions de `pro_scan.py` (découverte des venues) + `polygon_guard.py`
(règle net > 0 $) + appels `eth_call` avec `block_identifier=bloc`
suffisent — le module `backtest.py` avait été esquissé puis SUPPRIMÉ
volontairement (ne pas livrer un module dont la source de données
n'existe pas).

## Ce qui n'a PAS été fait (et pourquoi)

- **Phase 2 (replay 7 jours) : ARRÊTÉE** comme ordonné — aucune source
  d'état historique ne fonctionne, donc aucun replay n'est possible.
- **Aucune histoire fabriquée** : ni spread OHLCV, ni données live
  présentées comme du passé. Les scans live restent la seule mesure.
- **Aucun fichier existant modifié** — seul ce rapport
  (`BACKTEST_POLYGON.md`) a été créé. `backtest.py` /
  `test_backtest.py` (esquissés avant la conclusion Phase 1) ont été
  supprimés pour ne pas livrer un module sans source de données.

## CAVEAT (valable aussi pour un futur backtest)

Même avec une source archive, un spread historique n'est PAS un profit
gagné : latence, concurrence, gas réel au moment de l'inclusion. Un
backtest rapporte « des spreads qui ont existé », pas « de l'argent
qu'on aurait gagné ».
