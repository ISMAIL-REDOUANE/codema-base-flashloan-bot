# Lead-Lag Binance ↔ Base — mesure de latence + méthode (PAS du latency arbitrage)

Date : 2026-11-25. Auteur : mesure + analyse (lecture seule).
Question d'Ismail : « être à Tokyo à côté de Binance et à côté de Base pour ne rien
rater ; mesurer la latence Binance ↔ Base ; trouver la méthode ; on fait du
LEAD-LAG, pas du latency arbitrage. »
Fichiers : `leadlag/` — `measure_rtt.py`, `measure_rtt2.py`, `leadlag_stream.py`,
`analyze_leadlag.py`, `analyze_leadlag2.py`, `measurements.jsonl` (1 600 lignes),
`rtt_run1.txt`, `rtt_run2.txt`.

## 0. Verdict en une phrase

**Le lead-lag existe (la DEX suit Binance avec ~2–4 s de retard), mais il n'est
pas gagnable par ce bot sur les majors : les mouvements sont de ~0,1 % —
exactement le breakeven — et le signal arrive déjà ~1 s en retard depuis
cette VM. Tokyo raccourcit la boucle (~1,9 s → ~0,5 s) mais ne change pas
l'économie : le problème est la taille des mouvements, pas la vitesse.**

---

## 1. Latence réseau — mesurée depuis CETTE VM (New York, US)

Egress de la VM : **New York City, US** (IP 87.81.226.61, vérifié via ipinfo.io).
C'est pour ça que Binance bloque : `api.binance.com` répond **HTTP 451**
(géo-blocage US) sur REST et WebSocket.

| Endpoint | Mesure | Médiane | p95 | n | Note |
|---|---|---|---|---|---|
| api.binance.com (REST ping) | curl | 624 ms | 748 ms | 20 | **HTTP 451 — ce n'est pas un vrai ping**, c'est le temps de la réponse d'erreur |
| stream.binance.com (WS) | handshake | — | — | 5 | **HTTP 451, rejeté** |
| data-api.binance.vision (REST ping) | curl | 1 226 ms | 2 476 ms | 20 | HTTP 200 — endpoint public Binance pour régions restreintes |
| data-api.binance.vision (ticker) | curl | 1 205 ms | 1 386 ms | 20 | HTTP 200 |
| data-stream.binance.vision (WS) | handshake | — | — | 5 | **Timeout (30 s) à chaque tentative — inutilisable depuis cette VM** |
| mainnet.base.org (eth_blockNumber) | curl | 393 ms | 502 ms | 20 | HTTP 200, RPC public |
| alchemy-base (eth_blockNumber) | curl | 641 ms | 837 ms | 20 | HTTP 200, URL lue dans config.yaml en mémoire, **clé jamais affichée ni loguée** |
| polygon.drpc.org (eth_blockNumber) | curl | 370 ms | 437 ms | 20 | HTTP 200 |

**Décalage d'horloge :** l'horloge locale est **~1 190 ms en retard** sur
Binance (serverTime − local, médiane de 10 échantillons, +1 116 à +1 429 ms).
Toutes les comparaisons de timestamps Binance dans ce rapport sont corrigées
de −1 190 ms, avec une incertitude de ±150 ms.

**Latence d'arrivée du signal (REST, pas WS) :** délai entre le timestamp
d'un trade Binance (corrigé) et sa réception locale : **médiane 952 ms,
p95 3 060 ms** (n = 700). Autrement dit : depuis cette VM, on apprend un
mouvement Binance **~1 seconde après qu'il a eu lieu** — avant même de
commencer à décider quoi que ce soit.

**Conséquence immédiate :** le WebSocket Binance (la source temps réel) est
inaccessible depuis cette VM (451 + timeout). La mesure ci-dessous utilise
donc le REST polling (aggTrades, 2 s) — suffisant pour la question posée
(« le gap survit-il 1–2 s ? »), insuffisant pour mesurer un lag en
millisecondes. La résolution de la mesure est de **2 s (Base) / 4 s (Polygon)**.

---

## 2. Lead-lag prix — mesuré en direct, 12 minutes

**Fenêtre : 2026-11-25 07:10:40–07:22:40 UTC (720 s).** Marché calme :
BTC 59 320 $ → 59 098 $ (−0,37 %), ETH 1 662 $ → 1 656 $ (−0,36 %).
Sources : Binance aggTrades (Vision REST, 2 s), Base Uniswap V3 QuoterV2
`quoteExactInput` 1 000 USDC → WETH / cbBTC (fee 500, RPC public, 2 s),
Polygon QuoterV2 `quoteExactInputSingle` 1 000 USDC.e → WETH (fee 500, drpc, 4 s).
1 600 enregistrements : Binance 700 (0 erreur), Base 613 + 107 erreurs
(**14,9 % d'échecs** — RPC public qui coupe : IncompleteRead /
RemoteDisconnected), Polygon 180 (0 erreur).

Adresses vérifiées pendant la mesure (pas devinées) : cbBTC Base
`0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` (DexScreener ; pools Uni V3
USDC/cbBTC fee 100/500/3000 confirmées via factory.getPool, liquidité
5,8 M$). WBTC n'a **aucun pool Uni V3 sur Base** (getPool = 0x0 aux fees
100/500/3000/10000) — sa liquidité est ailleurs (Aerodrome).

### 2.1 Le lag : la DEX suit Binance avec ~2–4 s de retard

Corrélation croisée des log-rendements (Binance[t] vs DEX[t+lag]) :

| Paire | Résolution | Pic de corrélation | Lag du pic | Beta @lag0 | Beta @lag+1 |
|---|---|---|---|---|---|
| ETH Binance → Base WETH | 2 s | 0,318 | **+1 bin (+2 s)** | 0,134 | 0,133 |
| BTC Binance → Base cbBTC | 2 s | 0,409 | **+1 bin (+2 s)** | 0,002 | 0,214 |
| ETH Binance → Base WETH | 4 s | 0,402 | **+1 bin (+4 s)** | 0,149 | 0,198 |
| BTC Binance → Base cbBTC | 4 s | 0,586 | **+1 bin (+4 s)** | 0,086 | 0,353 |
| ETH Binance → Polygon WETH | 4 s | 0,264 (pic diffus) | pas de pic net | 0,174 | 0,129 |

Lecture : le pic de corrélation est systématiquement **1 bin après** le
mouvement Binance, aux deux résolutions — la DEX suit avec **~2–4 s de
retard** (résolution de la mesure : 2 s). Le beta est faible (0,09–0,35) :
dans une fenêtre calme, les rendements sont dominés par le bruit de
microstructure (spread, arrondi des ticks, staleness des quotes), ce qui
atténue le beta — le chiffre à retenir est le **lag (~2–4 s)**, pas le beta.
Polygon ne montre pas de pic net (poll 4 s + latence drpc + pool mince).

### 2.2 La taille des mouvements : ~0,1 % — exactement le breakeven

Mouvements Binance par bin de 4 s : **max 0,105 %** (BTC et ETH, 1 bin
chacun en 12 min), p95 0,032–0,040 %, médiane 0,007–0,008 %. **Aucun
mouvement >0,1 % par bin de 2 s en 12 minutes.** Le marché était calme,
mais c'est le régime normal : un mouvement >0,1 % toutes les ~12 min par
actif, à cette résolution.

### 2.3 Le gap stationnaire : Base suit Binance à ±0,06 % près

Gap = (prix Binance − prix DEX) / prix DEX, bins alignés de 4 s.
Attention : mon prix DEX est un prix **d'exécution pour 1 000 $** (quote
post-fee, fee 0,05 % incluse) — pas un mid. Corrigé de la fee (+0,05 %) :

| Paire | Gap médian (corrigé fee) | p5 | p95 | max | \|gap\| > 0,1 % |
|---|---|---|---|---|---|
| ETH : Binance vs Base WETH | **−0,006 %** | −0,036 % | +0,058 % | +0,079 % | 0 / 172 |
| BTC : Binance vs Base cbBTC | **−0,007 %** | −0,037 % | +0,059 % | +0,091 % | 1 / 174 |
| ETH : Binance vs Polygon WETH | −0,247 % (brut) | −0,291 % | −0,151 % | −0,131 % | 175 / 175 |

**Base : après correction de la fee, le gap médian est ~0,00 % et ne dépasse
jamais le breakeven (0,1 %) sauf 1 bin sur 174.** La DEX suit Binance
quasiment parfaitement à la résolution 4 s.

**Polygon : le −0,247 % est un offset structurel, pas un signal.**
Décomposition mesurée : USDC.e → USDC = 0,99975 (−0,025 %, quoté
on-chain) + fee 0,05 % incluse dans ma quote (−0,05 %) + résidu ~−0,17 %
(impact prix d'un quote de 1 000 $ sur un pool mince / staleness).
Ce n'est **pas un edge tradeable** — c'est le prix d'un pool fin coté en
USDC.e, pas une dislocation de l'ETH.

### 2.4 Le seul vrai événement : le plus gros mouvement de la fenêtre

Mouvement Binance maximal : **−0,104 % (ETH) / −0,105 % (BTC) en 4 s**,
même bin (mouvement de marché). Chronologie du gap (Binance − DEX) :

| | −4 s | 0 s (le mouvement) | +4 s | +8 s | +12 s |
|---|---|---|---|---|---|
| ETH | +0,028 % | **−0,024 %** (DEX pas encore baissée) | — | +0,083 % | +0,119 % |
| BTC | +0,030 % | **−0,075 %** (DEX pas encore baissée) | −0,005 % | +0,101 % | +0,118 % |

Lecture : après le mouvement baissier, la DEX met **~4 s à suivre**
(gap négatif = DEX encore au prix haut, puis retour à ~0 à +4 s).
Ensuite le gap oscille à ±0,1 % (bruit / overshoot), pas une fenêtre
stable. **Même le plus gros mouvement de 12 min est à peine au breakeven
(0,104 % de mouvement brut contre 0,10 % de frais aller-retour + gas)** —
et il faudrait l'exécuter dans les ~4 s où la DEX n'a pas encore suivi.

---

## 3. Tokyo : ce que ça prend, ce que ça gagne, ce que ça ne règle pas

### 3.1 Binance est bien à Tokyo (AWS ap-northeast-1)

Confirmé par plusieurs sources indépendantes (pas une déclaration
officielle de Binance — Binance ne publie pas l'emplacement) :
mesures de latence + IPs dans AWS AS16509 ap-northeast-1
(BJF Trading Group, nov 2026 ; Arbitron, nov 2026 ; Albers et al.,
*Quantitative Finance* 2025). RTT REST mesurés par des tiers :
**Tokyo ~20–25 ms**, Singapour/Séoul ~70–100 ms, **US ~120–180 ms**,
Europe ~270 ms ; minimum physique New York ↔ Tokyo : **140–180 ms**
aller-retour. Depuis cette VM (New York), le benchmark US serait ~164 ms —
mais on mesure **~950 ms en REST et un WS inutilisable** : le chemin
réseau de cette VM est bien plus lent que le benchmark (probablement
proxy/routage), ce qui rend le gain de Tokyo encore plus grand *pour
cette VM*.

### 3.2 Coûts (sources publiques, nov 2026)

| Option | Prix | Source |
|---|---|---|
| AWS t3.small ap-northeast-1 (2 vCPU, 2 Go) | **0,0272 $/h ≈ 19,86 $/mois** on-demand | DoiT Compute ; vmprices 20,82 $/mois avec disque |
| AWS t3.micro ap-northeast-1 | 0,0136 $/h ≈ 9,93 $/mois | DoiT Compute |
| AWS t4g.small ap-northeast-1, free tier 750 h/mois | ~6,15 $/mois (EBS + IPv4) | DevelopersIO (free tier prolongé fin 2026) |
| AWS c6i.large Tokyo (vrai serveur trading) | ~68 $/mois, 1,8–3,5 ms vers Binance | GridBotWars |
| Même t3.small en us-east-1 (comparaison) | ~15,18 $/mois | aws-pricing.com |

Caveat : t3 est **burstable** (crédits CPU) — pas idéal pour du 24/7 à
faible latence ; un c6i/c7g (40–120 $/mois) est le vrai standard trading.
Un VPS « Tokyo » bon marché hors AWS (Vultr, Hetzner…) n'est pas dans
AWS ap-northeast-1 : la latence vers Binance y est plus élevée
(quelques ms de plus, à mesurer, pas devinée).

### 3.3 « À côté de Base » : impossible en même temps que Tokyo

Le séquenceur Base est **centralisé, opéré par Coinbase, hébergé sur AWS,
principalement aux US** (Chainstack 2026 ; ai-frb : « AWS us-east-1 »).
Coinbase ne publie pas l'emplacement exact — us-east-1 (Virginie du Nord)
est la meilleure information publique, pas une certitude officielle.
Conséquences :
- **Tokyo → séquenceur Base (us-east-1) : ~150–200 ms** (trans-Pacifique,
  incompressible).
- **us-east-1 → Binance (Tokyo) : ~120–180 ms.**
- **On ne peut pas être à côté des deux :** la jambe trans-Pacifique
  (~150–200 ms) est inévitable dans un sens ou dans l'autre. Le choix de
  la ville ne décide pas la course — c'est le RPC (dédié, proche du
  séquenceur) et la vitesse du code de décision qui comptent.
- Le séquenceur Base est derrière Cloudflare (Glassnode Latency Monitor) :
  chaque soumission passe par un edge Cloudflare avant le séquenceur.

### 3.4 Ce que Tokyo gagne vs cette VM — et ce qu'il ne règle pas

Boucle complète (événement Binance → inclusion Base) :
- **Cette VM :** ~950 ms (signal REST) + ~356 ms (quote Python) +
  ~400 ms (RPC public) + 200 ms (bloc Base) ≈ **~1,9 s**.
- **VPS Tokyo (t3.small, code optimisé, RPC dédié) :** ~20 ms (Binance) +
  ~50 ms (décision) + ~150–200 ms (Tokyo → us-east-1) + 200 ms (bloc)
  ≈ **~0,5 s**. Gain : ~1,4 s.
- **VPS us-east-1 :** ~150 ms (Binance) + ~50 ms + ~20 ms (séquenceur) +
  200 ms ≈ **~0,4 s** — équivalent, la jambe trans-Pacifique étant
  simplement de l'autre côté.

**Ce que Tokyo ne règle PAS :** le bloc Base de 200 ms (plancher
incompressible) ; le **breakeven de ~0,1 %** (frais aller-retour + gas) ;
le fait que la DEX reprice en ~4 s ; le besoin d'un **compte Binance
financé** pour hedger (pas 0 $) ; les rate limits du RPC public
(14,9 % d'échecs mesurés ici).

---

## 4. La méthode LEAD-LAG (système papier — pas du latency arbitrage)

**Lead-lag ≠ latency arbitrage.** Latency arbitrage = être le plus rapide
à exploiter un écart de prix (course à la milliseconde, HFT). Lead-lag =
utiliser le **leader (Binance) comme signal prédictif** du suiveur (DEX) :
quand Binance bouge, la DEX *va* bouger dans le même sens avec un retard
mesuré (~2–4 s) — on entre sur la DEX **avant** qu'elle ait fini de
suivre, pas pour être le plus rapide du monde, mais pour être dans la
fenêtre de retard.

### 4.1 Signal
- Source : Binance (spot BTCUSDT / ETHUSDT). Prix de référence = dernier
  trade (aggTrades) ou best bid/ask.
- Déclencheur : mouvement Binance |Δ| ≥ **0,15 %** sur 4 s (au-dessus du
  bruit : p95 des mouvements 4 s = 0,03–0,04 %, max observé 0,105 % —
  le seuil 0,15 % ne se déclenche quasiment jamais sur les majors en
  marché calme ; c'est le point : le signal est rare).
- Filtre : mouvement confirmé par 2 ticks consécutifs (évite le
  bruit d'un seul trade).

### 4.2 Prédiction
- Mouvement DEX attendu = **beta × mouvement Binance**, beta mesuré
  0,15–0,35 à 4 s (atténué par le bruit ; borne haute ~0,6 sur BTC à
  lag +1). En pratique : on suppose un suivi quasi-total à horizon
  8–12 s (le gap retourne à ~0), mais la mesure ne le prouve qu'à ±0,1 %.
- Lag attendu : **~2–4 s** (pic de corrélation à +1 bin).

### 4.3 Entrée (règle du garde, math du repo)
- Entrer **uniquement si** net prédit > 0 $ après TOUS les coûts :
  net = |mouvement| × taille − frais DEX aller (0,05 %) − frais DEX
  retour (0,05 %) − gas (~0,005 $ Base) − budget revert (1× gas).
  Sur les majors : breakeven ≈ **0,10–0,11 %** de mouvement.
- Taille : optimale selon `polygon_decide` / `math_engine` (jamais fixe).
- Exécution : **DEX uniquement** (flash loan Morpho 0 % si le contrat
  existe pour Base ; sinon achat spot avec l'inventaire — qui n'existe
  pas à 0 $). Pas de hedge Binance dans la version 0 $ (voir §4.4).

### 4.4 Sortie / hedge — le point honnête
- **Sortie DEX seule :** on revend sur la DEX après qu'elle a suivi
  (8–12 s). Risque : le prix Binance repart dans l'autre sens entre
  temps → la DEX ne suit pas → perte. C'est du trading directionnel
  déguisé, pas de l'arbitrage sans risque.
- **Hedge Binance (la vraie version) :** vendre/acheter simultanément
  sur Binance pour verrouiller l'écart → nécessite un **compte Binance
  financé avec du capital déposé + des frais taker (0,10 % standard)**.
  **Ce n'est PAS 0 $.** Sans hedge, le lead-lag est une prédiction,
  pas un arbitrage.
- **Re-simulation pré-envoi** (`revert_protection.py`) : re-coter au
  dernier bloc, abandonner à 0 $ de gas si le gap a disparu.

### 4.5 Protocole de paper-test (0 $, aucune exécution)
1. Brancher le feed Binance (Vision REST 2 s depuis cette VM ; WS si
   un jour accessible) + les quotes DEX (déjà construits ici).
2. Tourner **7 jours, 24/7** (ou au minimum 3 jours incluant une
   session volatile US) ; logger chaque signal, le gap à +2 s / +4 s /
   +8 s / +12 s, et le net simulé.
3. **Critères go / no-go :**
   - GO si : ≥5 signaux/semaine avec net simulé > 1 $ ET lag médian
     ≥2 s (fenêtre exploitable par une boucle ~0,5–1 s).
   - NO-GO si : <1 signal/semaine OU net simulé médian ≤ 0 $ OU lag
     médian <1 s.
4. Ne passer à l'exécution (fork, puis mainnet avec audit + approbation
   d'Ismail) que si GO — et seulement sur les paires qui passent le test.

---

## 5. Verdict : le lead-lag est-il faisable pour lui ?

**Sur les majors (BTC/ETH), avec ce setup : NON.**
- Le lag mesuré (~2–4 s) est réel, mais les mouvements sont de ~0,1 % —
  exactement le breakeven. Même avec une boucle parfaite, le profit
  par événement est ~0 $.
- Le signal arrive avec ~1 s de retard depuis cette VM (REST) ; la
  boucle totale est de ~1,9 s contre une fenêtre de ~4 s — trop juste,
  et chaque seconde perdue mange le peu de marge qu'il y a.
- Tokyo raccourcit la boucle à ~0,5 s (gain réel, ~20 $/mois), mais
  **ne change pas l'économie** : 0,1 % de mouvement − 0,1 % de frais
  = 0 $, à n'importe quelle vitesse.

**Les seules exceptions possibles (non testées ici) :**
- **Paires fines (thin pairs)** : la DEX y reprice plus lentement
  (moins de compétition), le lag peut être de dizaines de secondes et
  les mouvements plus grands — mais : risque honeypot, taille limitée,
  impact prix. À tester en paper-test, jamais en aveugle.
- **Sessions volatiles** (annonces macro, liquidations) : les mouvements
  dépassent 0,1 % et la DEX lag davantage — la fenêtre de 12 min mesurée
  ici était calme ; un paper-test de 7 jours incluant de la volatilité
  est nécessaire avant de conclure définitivement.

**Ce que « être à Tokyo » changerait vraiment :** le feed Binance
(~950 ms → ~20 ms) et la qualité du RPC. Ce que ça ne changerait pas :
le breakeven, le bloc de 200 ms, le besoin de capital Binance pour
hedger. **Priorité actuelle : la route Curve (+5,63 $ à 5 k$, déjà
vérifiée live) reste le meilleur chemin 0 $ — le lead-lag est une
deuxième ligne, en paper-test seulement.**

## 6. Prochaine étape exacte

1. **Paper-test lead-lag 7 jours** (0 $) : réutiliser `leadlag_stream.py`
   (Binance REST + quotes Base/Polygon), ajouter la détection de signal
   (seuil 0,15 % / 4 s) et le calcul du net simulé, logger, appliquer
   les critères go/no-go (§4.5). Étendre aux paires fines si les majors
   restent à zéro.
2. Si GO sur une paire : test fork du contrat d'exécution, puis audit,
   puis approbation d'Ismail avant tout mainnet.
3. Si NO-GO : abandonner le lead-lag, garder la route Curve + les
   autres voies 0 $ (audit contests, solver UniswapX).

## Annexe — fichiers, reproductibilité, limites

- `leadlag_stream.py` : 3 threads (Binance 2 s, Base 2 s, Polygon 4 s),
  720 s, 1 600 lignes. `analyze_leadlag.py` (bins 2 s),
  `analyze_leadlag2.py` (bins 4 s, gaps, tailles de mouvements).
- **Limites honnêtes :** (1) fenêtre calme de 12 min — un seul
  événement >0,1 % ; les chiffres de lag/beta sont bruités (corrélations
  0,3–0,6, beta atténué par le bruit de microstructure) ; (2) résolution
  2–4 s — un lag en millisecondes est invisible ici (il faudrait le WS,
  bloqué) ; (3) correction d'horloge ±150 ms ; (4) prix DEX = prix
  d'exécution 1 000 $ post-fee, pas un mid — la correction de fee
  (+0,05 %) est appliquée dans §2.3 ; (5) RPC public Base : 14,9 %
  d'échecs — en production, retries + RPC dédié ; (6) deux exécutions
  de mesure ont vu leur approbation expirer sans réponse (mesure Alchemy
  et sonde WS) — les résultats ont été livrés par l'outil et sont
  utilisés ici, mais le parent doit confirmer qu'ils sont acceptés ;
  la clé Alchemy n'a été utilisée qu'en mémoire, jamais affichée ni
  loguée.
- **Aucun broadcast, aucun wallet, aucune clé, aucun fonds réel.
  Aucun fichier existant modifié. Aucun commit.**
- Adresses : QuoterV2 Base `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a` ;
  cbBTC Base `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` (DexScreener) ;
  QuoterV2 Polygon `0x61fFE014bA17989E743c5F6cB21bF9697530B21e`.
- Sources colocation : BJF Trading Group (nov 2026) ; Arbitron (nov 2026) ;
  PapaProxy (juil 2026) ; Albers et al., *Quantitative Finance* 2025 ;
  DoiT Compute / vmprices (prix AWS, nov 2026) ; Chainstack (2026) ;
  ai-frb (Base Playbook) ; Glassnode Latency Monitor (mainnet-sequencer.base.org).
