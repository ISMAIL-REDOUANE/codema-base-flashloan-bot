# Smoke test — Détecteur Amoy (10 minutes live)

**Date :** 2026-11-24, 22:31:19 → 22:42:24 UTC (10 min, intervalle 60 s)
**Commande :** `python3 amoy_detector.py --duration-minutes 10`
**Chaîne :** Polygon Amoy (80002), lecture seule, aucun broadcast.

> **Note règle 2026-11-24 (Ismail) :** ce smoke test a tourné sous
> l'ANCIENNE règle (logue seulement les opps ≥ 3 $). La nouvelle règle
> (logue tout net > 0 $ après tous les coûts, flag `gte_3_usd`)
> ne change RIEN à ces résultats : **0 spread vu** → 0 opportunité
> sous l'une ou l'autre règle.

## Résultats

| Mesure | Valeur |
|---|---|
| Cycles complétés | **10** (22:31 → 22:42, ~60 s d'intervalle) |
| Cycles en échec (RPC) | **2** (voir « Incidents RPC ») |
| Blocs observés | 53 736 745 → 53 737 400 |
| Gas Amoy mesuré | **59,6 – 61,3 gwei** → 1 trade (450 000 unités) = **0,0268 – 0,0276 POL de test** (≈ 0,0020 – 0,0021 $ simulés) |
| RPC utilisé | `polygon-amoy.drpc.org` (l'officiel `rpc-amoy.polygon.technology` est injoignable ; bascule automatique) |
| Venues présentes | **0 / 6** (Uniswap V3/V4, QuickSwap V2/V3, Sushi V2, Pancake V3 — toutes absentes, eth_getCode vide) |
| Paires vérifiées | **0** (watchlist vide : aucun token vérifié) |
| Spreads vus | **0** |
| Opportunités simulées net > 0 $ | **0** |
| Opportunités simulées ≥ 3 $ | **0** |
| Fichier `amoy_opportunities.jsonl` | **non créé** (normal : aucune opp) |
| Sortie | arrêt propre, `SMOKE_EXIT:0` |

## Incidents RPC (honestement rapportés)

Les 2 premiers cycles ont échoué à la découverte des venues (pas de
crash : le cycle est journalisé en erreur, compté dans
`daily_summary.json`, et la boucle continue) :

1. **Cycle 1 (22:31:30)** — `403 Client Error: Forbidden` sur
   `polygon-amoy-bor-rpc.publicnode.com` (Cloudflare / rate-limit).
2. **Cycle 2 (22:32:36)** — `ProxyError: RemoteDisconnected` sur le
   même RPC (connexion coupée).

Les 8 cycles suivants ont réussi via `polygon-amoy.drpc.org`. Leçon :
les RPC publics gratuits sont capricieux (réponses chunkées tronquées,
403 intermittents) — le détecteur réessaie désormais 2 fois par RPC et
tente le dernier RPC qui a répondu en premier (correctif appliqué après
ce smoke test, vérifié par `--once` : cycle OK en ~25 s). Pour un run
de 2–4 semaines, un RPC dédié (Alchemy, clé déjà dans `config.yaml`
côté Base — à ajouter ici le moment venu) serait plus fiable.

## Incidents corrigés pendant ce smoke test

1. **Adresse Pancake V3 tronquée (39 car. au lieu de 40)** dans
   `amoy_config.yaml` → le RPC rejetait l'appel (`-32602`, adresse
   hexadécimale de longueur impaire) et tuait le cycle. Corrigé :
   adresse canonique `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865`
   (vérifiée sur Arbiscan/BSC). Re-vérification on-chain : **pas de
   code sur Amoy ET pas de code sur mainnet Polygon** — Pancake V3
   n'est déployé sur Polygon PoS sur aucune des deux chaînes.
2. **Robustesse du détecteur** : validation du format des adresses
   avant tout appel RPC (une adresse invalide est ignorée avec un log,
   pas de crash) ; un cycle en échec ne tue plus la boucle ; le résumé
   journalier ne remet plus les compteurs de venues à 0 sur un cycle
   en échec.

## Verdict du smoke test

**Le détecteur fonctionne** (RPC, lecture des venues, calcul du gas,
journalisation, arrêt propre, gestion des erreurs). **Il n'a rien vu**
parce qu'il n'y a rien à voir sur Amoy : 0 venue, 0 paire, 0 spread.
Le paper-trade Amoy ne peut donc pas mesurer le marché — voir
README.md § « Ce que le paper-trade peut et ne peut pas prouver » :
le vrai signal de marché vient du scan mainnet en lecture seule.
