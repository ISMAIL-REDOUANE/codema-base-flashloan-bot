# Scan live — pools meme Polygon (v4.1)

**Date :** 2026-11-24 22:55 UTC — **Script :** `watchlist_run.py`
(remplace le scan one-shot `scanner_polygon.py`, toujours utilisable)
**Détail brut :** `watchlist_scan_2026-11-24_2255.json` —
**Watchlist :** `watchlist.json` (96 tokens) — **Log des runs :**
`watchlist_runs.jsonl`

## Verdict

**0 opportunité d'exécution sur 0 candidat exec à 2 venues — aucun
arbitrage meme 2-DEX sur Polygon en ce moment.** Même verdict que les
scans précédents (22:21 UTC : 0 candidat sur 80 pools), mais la
couverture est maintenant beaucoup plus large et persistante : la
watchlist suit 96 tokens et re-vérifiera leurs venues à chaque run.

## Chiffres (run 22:55 UTC)

| Mesure | Valeur |
|---|---|
| Pools récentes lues (GeckoTerminal `polygon_pos`, pages 1–5) | **100** |
| Page 6 | HTTP **429** persistant malgré 4 tentatives de backoff → **skippée et journalisée**, scan non tué |
| Profils DexScreener Polygon (`token-profiles/latest`, 2e source) | **0** (flux du moment = 100 % Solana — normal, à sonder toutes les 2–4 h) |
| Tokens vérifiés (paires DexScreener) | **96** |
| Watchlist totale | **96 tokens** (exec **0** / watch **4** / none **92**) |
| Tokens avec 2+ venues (tous tiers) | **5** — tous tier **none** (vieux tokens, voir ci-dessous) |
| Nouvelles 2e venues détectées ce run | **5** |
| Opportunités exec (GoPlus OK + spread ≥ 3 % + net > 0 $) | **0** |
| Distribution net (exec 2 venues, GoPlus OK, n=0) | > 0 $ : **0** \| ≥ 0,50 $ : **0** \| ≥ 3 $ : **0** \| ≤ 0 $ : **0** |
| Max liquidité vue parmi les 96 | **983 847,68 $** (1 gros pool hors cible) |

## Les 5 tokens à 2+ venues (tous hors fenêtre — tier `none`)

Des venues existent, mais ce sont de vieux tokens (ou stables), pas des
memes en lancement — leur plus ancienne paire a des mois/années :

| Token | Venues | Pourquoi pas exécuté |
|---|---|---|
| FUL | quickswap, sushiswap | vieux token, liq ~2 $ |
| Rp | uniswap, uniswap-v4 | vieux token, liq ~2 $ |
| VOLLAR | sushiswap, uniswap, uniswap-v4 | vieux token (meilleure paire 15 k $ mais âge > 7 j) |
| COMP | quickswap, sushiswap, uniswap, uniswap-v4 | vieux token (Compound) |
| axlUSDC | quickswap, uniswap | stablecoin bridgé, pas un meme |

## Les 4 tokens en tier `watch` (suivis, jamais exécutés)

| Token | Max liq vue | Âge max | Venues |
|---|---|---|---|
| SWCH / USDT | 1 021 $ | 33,6 h | uniswap-v4 |
| GRIPS | 1 969 $ | 40,1 h | uniswap |
| VENUE | 3 525 $ | 46,1 h | uniswap |
| XFROG | 1 316 $ | 46,2 h | uniswap |

1 seule venue chacun pour l'instant — la watchlist les re-vérifiera à
chaque run (toutes les 2–4 h) : si une 2e venue apparaît ET qu'ils
rentrent dans la fenêtre exec (5 k–100 k $, < 72 h), ils seront promus
et évalués.

## Règle de profit — CHANGEMENT 2026-11-24 (Ismail)

**Min profit 3 $ ABANDONNÉ sur Polygon.** Nouvelle règle : on entre
dans n'importe quel trade dont le net simulé est **> 0 $ après TOUS
les coûts** — flash 0 % (Morpho), frais de swap (dans les quotes),
gas (0,0095 $/trade) **+ budget revert pire cas** (~1× gas de plus,
coût total pire cas 0,019 $/trade). La décision est prise au centime
(net arrondi : 0,00 $ = bloqué). `polygon_config.yaml` est mis à jour
par Ismail lui-même (`min_profit_usd` 3,0 → 0,0) — la règle vit déjà
dans `watchlist_run.py` (`MIN_PROFIT_USD = 0.0`, `TOTAL_COST_USD`).
Chaque run rapporte la distribution du net par tranches (> 0 $, ≥ 0,50 $,
≥ 3 $) pour mesurer l'effet du changement — ce run : n=0, pas
d'effet mesurable tant qu'aucun candidat exec à 2 venues n'existe.

## Couverture v4.1 (nouveau)

- **2 sources de découverte :** GeckoTerminal new pools (pages 1–6)
  **+** DexScreener `token-profiles/latest` filtré `chainId == "polygon"`.
- **Watchlist persistante (`watchlist.json`) :** chaque token vu est
  enregistré (adresse, nom, first/last seen, venues, max liq, âge max,
  tier, GoPlus) et **re-vérifié à chaque run** — une 2e venue qui
  apparaît des heures/jours après le launch est détectée (5 ce run).
- **2 fenêtres :** exec (liq 5 k–100 k $, < 72 h, spread ≥ 3 %, net
  > 0 $) ; **watch (liq 1 k–500 k $, < 7 jours) — suivi sans
  exécution**, même avec 2 venues. Le tier est calculé sur la liquidité
  max vue et l'âge de la PLUS ANCIENNE paire (un vieux token avec une
  nouvelle pool est rétrogradé `none`, pas promu par erreur).
- **Backoff 429 :** exponentiel (+ `Retry-After`), reprise de la
  pagination — une page en échec est skippée et journalisée, le scan
  continue (page 6 ce run). Tests mockés dans `test_watchlist.py`.
- **Runner `watchlist_run.py`** (toutes les 2–4 h) : append
  `watchlist_runs.jsonl` + JSON détaillé par run.

## Bugs trouvés et corrigés pendant ce run

1. **Adresses `pos_0x…` invalides** (bug v4.0 hérité) : l'id Gecko est
   `polygon_pos_0x…`, le retrait de `polygon_` seul laissait `pos_0x…`
   — tous les appels DexScreener échouaient silencieusement.
   Corrigé (`strip_token_prefix`), test de régression ajouté.
2. **Même DEX compté 2 fois** : `uniswap_v3_polygon_pos` (Gecko) vs
   `uniswap` (DexScreener) — normalisé (`normalize_dex`) ; une même
   adresse de paire sous deux labels ne compte qu'une venue
   (BMC1x : 6 → 5 deux-venues après correction).

## Lecture

Les 100 pools les plus récentes restent quasi toutes de la poussière
(quelques dollars de réserve) ou un gros pool hors cible. Aucun token
en fenêtre exec n'a 2 venues à cet instant — le filtre fonctionne, c'est
l'état du marché. La watchlist (96 tokens, 4 en suivi actif) est
maintenant en place : le prochain run re-vérifiera chaque token, et une
2e venue qui apparaît sur SWCH, GRIPS, VENUE ou XFROG sera captée.
