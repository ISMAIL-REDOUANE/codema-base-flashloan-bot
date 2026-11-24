# Scan live — pools meme Polygon (v4.0)

**Date :** 2026-11-24 ~22:25 UTC — **Script :** `scanner_polygon.py`
**Détail brut :** `meme_scan_polygon_2026-11-24.json`

## Verdict

**0 token avec 2 venues sur 0 candidat — aucun arbitrage meme 2-DEX
sur Polygon en ce moment.** Même verdict que sur Base (20 candidats, 0 avec
2e paire, 19:53 UTC).

## Chiffres

| Mesure | Valeur |
|---|---|
| Pools récentes lues (GeckoTerminal `polygon_pos`, pages 1–4) | **80** |
| Page 5 | HTTP **429** (rate limit GeckoTerminal — même limite que le scan Base) |
| Candidats (liq 5 000–100 000 $, < 72 h) | **0** |
| Max liquidité vue parmi les 80 | **984 227,83 $** (1 pool au-dessus du plafond 100 k $ — pas un meme) |
| Raison du rejet des 80 pools | liquidité hors fenêtre 5 k–100 k $ (exemples dans le JSON : 27,92 $, 0 $, 1,35 $, 33,99 $, 371,11 $…) |

## Lecture

Les 80 pools les plus récentes de Polygon sont quasi toutes de la poussière
(quelques dollars à quelques centaines de dollars de réserve) ou, pour une
d'entre elles, un gros pool > 984 k $ hors cible. Aucune nouvelle pool meme
dans la fenêtre 5 k–100 k $ au moment du scan. Le filtre fonctionne
correctement (les rejets sont journalisés avec liq/âge dans le JSON) —
ce n'est pas un bug de scan, c'est l'état du marché à cet instant.

## Conséquence

Le bot Polygon est techniquement prêt (contrat prouvé sur fork, flash 0 $),
mais il n'y a **rien à arbitrer en ce moment**. Le scan doit tourner toutes
les 2–4 h en watchlist (comme prévu) et n'exécuter que si un token obtient
une 2e venue avec un spread ≥ 3 %. Un relancement du scan après quelques
heures peut donner un résultat différent — les launches sont éphémères.
