# REVERT_PROTECTION_POLYGON.md — Revert = 0 $ de gas sur Polygon ?

**Date :** 2026-11-24 — **Demande d'Ismail :** « Non mbritch nkhser dak l gas
— l9a liya chi solution wch dar revert mnkhlsch lgas » (je ne veux perdre
AUCUN gas sur les reverts).

**Contexte :** le bot a déjà la simulation preflight (les perdants sont
SKIP avant broadcast = 0 $). Le résidu, ce sont les trades qui passent
la simulation mais revert on-chain (races / changement d'état entre la
simulation et l'inclusion). Revert mesuré sur le fork Polygon :
**0,031366 MATIC ≈ 0,0024 $** ; prudent **0,0095 $** (450 000 unités ×
279 gwei). La question est donc : existe-t-il un mécanisme VÉRIFIÉ qui
fait que ce revert ne coûte rien ?

## VERDICT — NON, pas sur Polygon aujourd'hui

**Aucun service vérifié ne donne 0 $ sur un revert on-chain pour un
appel de contrat arbitraire sur Polygon (chaîne 137).** Sur une chaîne
EVM publique, le gas est payé que la transaction réussisse ou échoue —
la seule façon d'avoir 0 $ est que la transaction en échec **n'atteigne
jamais la chaîne** (relai qui simule et jette avant inclusion). Ce
mécanisme n'existe, vérifié, que sur Ethereum.

| Option | Sur Polygon ? | 0 $ sur revert ? | Verdict |
|---|---|---|---|
| MEV Blocker `/noreverts` | **Non — Ethereum seulement** | Oui (simule et jette) | ❌ Inutilisable ici |
| Flashbots Protect | **Non — Ethereum seulement** | Oui | ❌ Inutilisable ici |
| FastLane Atlas | Oui (live) | **Non — « No Free Reverts »** | ❌ Ne résout pas le problème |
| Polygon Private Mempool | Oui (live 2026-04-02, gratuit) | **Non documenté** | ⚠️ Non vérifié — ne pas prétendre au 0 $ |
| dRPC MEV Blocker | Oui | Non (vie privée MEV seulement) | ❌ Pas de garantie revert |
| Blink (ex-Merkle) | Oui | Non (frontrunning/sandwich seulement) | ❌ Pas de garantie revert |
| bloXroute Protect | Oui (multichaîne) | Non (frontrunning seulement) | ❌ Pas de garantie revert |
| Paymaster ERC-4337 | Oui | **Non — EntryPoint facture le gas même en revert** | ❌ Confirmé impossible |
| Gas refunds (EIP-3529) | — | **Non — refund SELFDESTRUCT supprimé, max gasUsed/5** | ❌ Mort depuis 2021 |

## Détail par option (sources)

### 1. MEV Blocker `/noreverts` — le mécanisme existe, mais Ethereum seulement ❌

- Docs officielles (lues 2026-11-24) :
  https://docs.mevblocker.io/reference/api/transaction-endpoints
  - `/noreverts` : « No revert guarantee. Transactions are simulated
    in a pending block. » — c'est EXACTEMENT le mécanisme voulu
    (simuler, jeter si revert → 0 $ gas).
- MAIS docs officielles, page d'introduction :
  https://docs.mevblocker.io/ — **« Supported chains : All features
  are supported on Ethereum. »**
- Confirmé par des comparatifs indépendants :
  - https://www.mempool.ink/mev-blocker — Chains : Ethereum ;
    Trade-offs : « Ethereum mainnet only ».
  - https://www.zily.io/learn/tools/directory/mev-blocker/ —
    « MEV Blocker's documented routing features are limited to
    Ethereum mainnet. »
  - https://openchainbench.com/benchmarks/mev-protect-rpc —
    « Flashbots and MEV Blocker are Ethereum-only by design ».
- Site officiel https://mevblocker.io : « MEV Blocker (Ethereum
  Mainnet) », Chain ID 1.
- **Check live (2026-11-24) :** `POST https://rpc.mevblocker.io/noreverts`
  `eth_chainId` depuis ce sandbox : **aucune réponse utilisable**
  (requête sans réponse ; le contrôle `POST https://polygon.drpc.org`
  `eth_chainId` a retourné `0x89` = Polygon, donc le client HTTP
  fonctionne — c'est l'endpoint MEV Blocker qui n'a rien renvoyé).
  La preuve retenue est la doc officielle, pas ce check.
- **Verdict :** le 0 $ revert existe chez MEV Blocker, mais pas sur
  Polygon. Inutilisable pour ce bot.

### 2. Flashbots Protect — même situation ❌

- Ethereum seulement (même constat que MEV Blocker, voir les
  comparatifs mempool.ink : Chains Ethereum pour Flashbots Protect
  comme pour MEV Blocker). Pas de relai Polygon.
- **Verdict :** inutilisable ici.

### 3. FastLane Atlas — live sur Polygon, mais PAS de revert gratuit ❌

- Blog officiel FastLane :
  https://fastlane.ghost.io/state-locks-and-deltas/ — section
  Limitations : **« No Free Reverts : Failed metatransactions still
  incur gas costs. »** (leurs propres mots). Les « Execution Hooks »
  permettent de SAUTER une opération qui va échouer (donc moins de
  gas gaspillé), mais une métatransaction en échec paie quand même
  son gas.
- De plus, Atlas est un framework **solvers / intents pour apps** :
  il faut intégrer l'app à l'entrypoint Atlas et faire concourir des
  solvers — ce n'est pas une route d'envoi pour un bot d'arbitrage
  autonome qui exécute sa propre transaction.
- Relai PFL sur Polygon : très peu de validateurs participants —
  la doc Skandha (PR etherspot/skandha#243) note qu'il faut attendre
  le tour du bon validateur, « usually takes hours and may take even
  longer ». Inutilisable pour de l'arbitrage en secondes.
- **Verdict :** ne donne pas le 0 $ revert, et ne correspond pas à
  l'architecture du bot.

### 4. Polygon Private Mempool — existe, mais 0 $ revert NON documenté ⚠️

- Annonce officielle Polygon Labs (2026-04-02) :
  https://polygon.technology/blog/polygon-launches-private-mempool-mev-protection-is-now-a-one-line-integration
  - Endpoint privé de soumission : les transactions vont directement
    aux producteurs de blocs élus (modèle VeBloP), en contournant le
    mempool public. Protège du frontrunning et du sandwich.
  - Free tier ouvert à toutes les apps Polygon ; tiers entreprise
    payants (API key, stablecoin ou POL).
- **Ce qui n'est dit NULLE PART dans l'annonce ni dans les articles
  dérivés :** simulation des transactions, rejet des transactions
  qui revertraient, ou garantie 0 $ sur revert. La protection
  documentée porte sur l'ORDRE (frontrunning/sandwich), pas sur
  l'échec d'exécution. Une transaction qui revert et qui est incluse
  par un producteur paie son gas normalement.
- **Endpoint non publié :** l'annonce dit « full integration docs
  and endpoint configuration are available in the Polygon docs » et
  il existe une page de demande d'accès — l'URL exacte de l'endpoint
  n'est pas publique. On ne peut donc pas l'implémenter sans passer
  par la demande d'accès Polygon.
- **Verdict :** option réelle pour la protection MEV (utile contre le
  frontrunning, qui est une cause de races), mais **NON VÉRIFIÉE pour
  le 0 $ revert**. Le module `revert_protection.py` la prévoit comme
  route `private` (endpoint TBD, désactivée par défaut, marquée
  NON VÉRIFIÉE) — elle ne doit JAMAIS être présentée comme une
  solution 0 $ revert.

### 5. dRPC MEV Blocker / Blink / bloXroute — vie privée MEV seulement ❌

- dRPC : https://blog.drpc.org/what-is-mev-blocker/ — MEV Blocker
  supporté sur Ethereum, Base, BNB, **Polygon**, Solana. Mais le
  mécanisme est la protection de la vie privée (cacher la transaction
  aux bots) — **aucune simulation / drop de revert documentée**.
  Une transaction en échec envoyée via dRPC atterrit on-chain et
  paie son gas.
- Blink (ex-Merkle) : https://www.merkle.io/private-mempool —
  supporte Polygon, mais la protection listée est « Frontrunning &
  sandwich attacks » uniquement (comparatif mempool.ink). Pas de
  garantie revert.
- bloXroute Protect : relai privé multichaîne, protection
  frontrunning via BDN. Aucune garantie revert documentée.
- **Verdict :** utiles contre le MEV, inutiles contre le coût du revert.

### 6. Paymaster ERC-4337 — confirmé IMPOSSIBLE ❌

- Trail of Bits, « Six mistakes in ERC-4337 smart accounts » :
  https://blog.trailofbits.com/2026/03/11/six-mistakes-in-erc-4337-smart-accounts/
  — « once `validateUserOp` succeeds, the bundler gets paid
  regardless of whether execution later reverts. This is the same
  model as normal Ethereum transactions, where miners collect fees
  even on failed txs ».
- Docs ERC-4337, Simulation Requirements :
  https://docs.erc4337.io/bundlers/simulation-requirements —
  « If a bundler submits a bundle and a `UserOperation` reverts
  during validation onchain : The bundler pays for all gas used ».
- Wiki FContext, ERC-4337 Paymaster Risk :
  « Execution can still revert and consume gas. »
- **Verdict :** un paymaster déplace QUI paie le gas (le sponsor),
  il ne l'annule pas. Le revert coûte toujours du gas à quelqu'un.
  Ne pas construire dessus.

### 7. Gas refunds (EIP-3529) — morts ❌

- EIP-3529 : https://eips-wg.github.io/EIPs/3529/ — « Remove gas
  refunds for `SELFDESTRUCT`, and reduce gas refunds for `SSTORE` » ;
  max refund = `gas_used // 5`. Les gas tokens (CHI/GST2) sont
  devenus sans valeur. Un refund ne rembourse de toute façon jamais
  un revert (il est appliqué APRÈS l'exécution, plafonné à 1/5 du
  gas utilisé).
- **Verdict :** aucune voie par les refunds.

### 8. Cas confirmé par PolygonScan : un revert paie toujours ❌

- Aide PolygonScan : « A failed transaction still costs you the
  fee… the gas fee is still deducted because of the computation
  already done. » C'est la règle du protocole sur Polygon PoS.

## Ce qui est implémenté (v4.2) — sans fausse promesse

Le module `revert_protection.py` ne prétend PAS au 0 $ revert. Il
fait trois choses vérifiées :

1. **Re-simulation au moment de l'envoi** : `eth_call` de la
   transaction contre le DERNIER bloc, juste avant le broadcast,
   + fenêtre de fraîcheur de la quote (30 s par défaut). Si la
   re-simulation échoue ou si le net tombe ≤ 0 → DROP avant envoi
   (0 $ gas). Ça réduit la fenêtre de course de secondes à
   ~le temps entre la re-sim et l'envoi. Ça ne supprime pas le
   risque résiduel.
2. **Routage + journal** : route `public` (défaut) ou `private`
   (Polygon Private Mempool, endpoint TBD, désactivée par défaut,
   marquée NON VÉRIFIÉE). Chaque tentative est journalisée
   (`dropped_presend` / `sent` / `executed` / `reverted_onchain` +
   gas payé) dans `revert_protection_log.jsonl`.
3. **Politique de repli fail-closed** : si la route protégée est
   injoignable/lente → NE PAS ENVOYER par défaut. Broadcast public
   seulement si `allow_public_fallback=true` ET si le net couvre le
   budget revert (garde `polygon_guard.py`).

## Le résidu — chiffré honnêtement

Coût d'un revert on-chain (mesuré fork Polygon, bloc 97 902 229) :
**0,0024 $** ; prudent (450 000 unités × 279 gwei) : **0,0095 $**.

Coût attendu des reverts résiduels par trade tenté :

```
E[revert] = taux_de_course × coût_revert
```

| Taux de course (trades passant la sim mais revert on-chain) | Coût attendu / trade tenté |
|---|---|
| 1 % | 0,000095 $ |
| 5 % | 0,000475 $ |
| 10 % | 0,00095 $ |
| 20 % | 0,0019 $ |

À 5 % de courses : 100 trades tentés → ~5 reverts → **~0,0475 $**
perdus en gas de revert. Sur le float de 1,31 $, c'est négligeable
en $ — mais ce n'est pas 0 $, et il faut le dire. Le taux de course
réel ne sera connu qu'avec le paper-trade Amoy (c'est lui qui le
mesurera : chaque `reverted_onchain` du journal compte).

## Ce qu'il faudrait pour un vrai 0 $ revert sur Polygon

1. Que Polygon (ou un relai tiers) publie un endpoint de soumission
   avec simulation-et-drop documenté, comme `/noreverts` de MEV
   Blocker sur Ethereum — à ce jour, rien de tel n'est documenté
   pour Polygon.
2. Ou que le bot passe par un **solver / intent** (ex. un solveur
   qui exécute et ne paie que s'il réussit) — aucun programme de ce
   type n'est vérifié pour l'arbitrage flash-loan sur Polygon.
3. Ou attendre que MEV Blocker / Flashbots Protect s'étendent à
   Polygon (à surveiller : docs.mevblocker.io, « Supported chains »).

En attendant, la défense réelle est : **preflight + re-simulation
au dernier moment + net > 0 $ après budget revert + journal** —
et accepter le résidu chiffré ci-dessus.

## Fichiers (v4.2)

- `REVERT_PROTECTION_POLYGON.md` — ce rapport.
- `revert_protection.py` — routeur (re-simulation, routage, journal,
  repli fail-closed). Mode dry-run par défaut : rien n'est broadcast.
- `test_revert_protection.py` — tests (voir le fichier).
- `polygon_config.yaml` — section `revert_protection:` ajoutée.
- `README.md` + `V2_CHANGELOG.md` — section v4.2.

## Note de fusion (agent parallèle)

Un autre agent modifie en parallèle les fichiers partagés
(`polygon_config.yaml`, `README.md`, `V2_CHANGELOG.md`) pour les
grosses pools / memes / triangle. Les ajouts v4.2 ci-dessous sont
suffisamment petits pour être ré-appliqués si cet agent les écrase :

```yaml
# --- PROTECTION REVERT v4.2 (voir REVERT_PROTECTION_POLYGON.md) ---
revert_protection:
  route: "public"
  private_endpoint: null
  private_timeout_seconds: 3.0
  max_quote_age_seconds: 30
  allow_public_fallback: false
  log_file: "revert_protection_log.jsonl"
```
