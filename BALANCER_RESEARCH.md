# Recherche Balancer — Flash loan 0 frais sur Base (v3)

> ⛔⛔⛔ CORRECTION v3.3 (2026-11-24) — BALANCER EST MORT ⛔⛔⛔
> **Balancer a été liquidé (wind-down BIP-928, 30 oct 2026)** : pools en
> retraits seuls, bug bounty terminé, Balancer Labs dissoute. Le Vault
> `0xBA12…F2C8` ne doit PLUS être utilisé comme provider de flash loan.
> Tout ce document reste valable comme HISTORIQUE (les mesures on-chain
> de nov 2026 sont exactes pour leur date), mais le provider actif est
> désormais **Morpho Blue** (`0xBBBB…FFCb`, fee 0 % par conception,
> USDC 328,7 M$ / WETH 88 713,53 — voir `RESEARCH.md` § Morpho Blue et
> `FORK_TEST_RESULTS.md` §11). `balancer_flash.py` est marqué DÉPRÉCIÉ,
> l'executor ne sélectionne plus Balancer, `config.yaml` l'a retiré
> (adresse conservée en commentaire pour référence).

**Date de vérification : 2026-11-24. Recherche + intégration v3 — simulation seulement,
aucun fond réel, aucune clé privée, aucun déploiement mainnet.**
**Demande d'Ismail : « khdem b flash loan ikon 0 fees, bhal Balancer ».**

> Lecture en 30 secondes : oui, Balancer V2 fait des flash loans à **0 % sur Base**,
> vérifié on-chain (pas seulement dans la doc). Le Vault est à la même adresse que
> partout : `0xBA12…F2C8`, la prime lue on-chain est **0,00 %**. MAIS le Vault sur
> Base est petit : **USDC 53 208 $ / WETH 23,27 (~39 042 $)**, total ~92 250 $.
> Nos loans (optimal ~790 $, fork 8 848 $) passent largement ; au-delà de
> ~26 604 $ USDC (50 % du solde, marge de sécurité), on rebascule sur Aave
> (0,05 %, liquidité 13,6 M$). Le gain du 0 % : **+0,39 $** sur le trade de
> référence (790 $), **+4,42 $** sur le cas fork (8 848 $). Le 0 % ne sauve
> jamais une mauvaise taille : 10 000 $ perd toujours (−4 480,79 $).

---

## 1. Balancer V2 est-il déployé sur Base ? OUI — vérifié on-chain

| Fait | Valeur | Preuve |
|---|---|---|
| Vault V2 Base (8453) | `0xBA12222222228d8Ba445958a75a0704d566BF2C8` | `eth_getCode` : 24 512 octets, bloc 61 794 215 ; même adresse que sur toutes les chaînes (déploiement déterministe) |
| `Vault.getProtocolFeesCollector()` | `0xce88686553686DA562CE7Cea497CE749DA109f9F` | lu on-chain via `eth_call`, bloc 61 794 215 |
| `getFlashLoanFeePercentage()` | **0** (= 0,00 %, 1e18 = 100 %) | lu on-chain via `eth_call` (sélecteur `0xd877845c`, vérifié par keccak), source `rpc_live` |
| Doc officielle | « Currently there are 0 fees for flash loans » | https://docs-v2.balancer.fi/reference/contracts/flash-loans.html |
| Doc gouvernance | « In V2, governance had the ability to set flash loan fees, but they were always set to zero » | https://docs.balancer.fi/concepts/governance/protocol-fees.html |

⚠️ **Piège d'adresse — ne pas se tromper de collector :** Basescan étiquette un
autre contrat « ProtocolFeesCollector » sur Base :
`0xCcb400111263f59Da19d9DD3977BC07e548431Af`, dont `getFlashLoanFeePercentage()`
retourne **1 %**. Ce N'EST PAS le collector du Vault. Le Vault pointe vers
`0xce88…`, fee 0 %. Le code (`balancer_flash.py`) utilise uniquement l'adresse
lue depuis le Vault lui-même. Si un jour le Vault change de collector, le
`fetch_flash_loan_fee_pct()` relira le nouveau taux au lieu de supposer 0 %.

## 2. Liquidité du Vault sur Base — le vrai plafond (mesuré on-chain)

Soldes `balanceOf(Vault)` lus on-chain, bloc 61 794 215 (2026-11-24),
re-vérifiés live ensuite (identiques : USDC 53 208,01 $, WETH 39 041,66 $) :

| Token | Solde Vault | En $ | Utilisable (50 %) |
|---|---|---|---|
| USDC (native `0x8335…2913`) | 53 208,01 | 53 208,01 $ | **26 604,01 $** |
| WETH (`0x4200…0006`) | 23,27 | ~39 042 $ (à 1 678 $) | ~19 521 $ (≈ 11,6 WETH) |
| **Total Vault Base** | — | **~92 250 $** | — |

Contexte : TVL Balancer totale sur Base ≈ **383 164 $** (DefiLlama, 2026-11-24),
volume 30 j ≈ 1,95 M$, 7 j ≈ 66 k$. C'est un petit écosystème sur Base — très
loin du milliard de $ du Vault Ethereum. Conséquence directe : **Balancer est
le meilleur provider pour NOS loans (petits), pas pour les gros.** Au-delà de
26 604 $ USDC, le bot rebascule automatiquement sur Aave (voir §5).

## 3. Le design confirmé : on n'emprunte JAMAIS le meme coin

Les meme coins ne sont (presque) jamais dans des pools Balancer, donc jamais
dans le Vault. Le design v3, validé :

```
Balancer Vault --flashLoan 0 %--> USDC (ou WETH)
      --> swap USDC -> MEME sur DEX A (Uniswap V2 / Aerodrome, pas cher)
      --> swap MEME -> USDC sur DEX B (cher)
      --> remboursement USDC + 0 au Vault, dans la même transaction
      --> profit net gardé par le contrat
```

Le flash loan ne finance que l'arbitrage. Si un meme coin apparaissait un jour
dans un pool Balancer, `select_provider()` le traiterait comme n'importe quel
token non-major : repli Aave (le Vault ne le détient pas en pratique).

## 4. Alternatives 0 / bas frais — comparatif honnête

| Provider | Frais flash | Sur Base ? | Liquidité utilisable | Verdict v3 |
|---|---|---|---|---|
| **Balancer V2 Vault** | **0 %** (lu on-chain) | ✅ oui | USDC 53 k$ / WETH 23,27 | **Provider préféré** (loans ≤ 26,6 k$) |
| Aave V3 Pool | 0,05 % | ✅ oui | USDC 13,6 M$ (aToken) | **Repli** (gros loans, tokens non-majors) |
| Uniswap V3 flash swap | = frais du pool (0,05 % / 0,3 % / 1 %) | ✅ oui | liquidité du pool concerné | Non intégré : plus cher que Balancer, callback différent |
| dYdX | 0 % (historiquement) | ❌ non | — | Pas sur Base (chaîne propre) — hors sujet |
| Morpho Blue flashLoan | 0 % (doc) | ⚠️ non vérifié on-chain | non mesurée | Non intégré, non vérifié — piste v4 seulement |
| Balancer V3 Vault | 0 % by design | ❌ **non déployé sur Base** | — | Vérifié : aucun code à `0xbA13…3333`, bloc 61 794 292 |

## 5. Règle de choix du provider (implémentée, `balancer_flash.select_provider`)

1. Token emprunté = WETH ou USDC **ET** loan ≤ 50 % du solde du Vault
   → **Balancer, 0 %**.
2. Sinon (loan trop gros, token = meme coin ou autre) → **Aave, 0,05 %**.
3. Soldes : live via `fetch_vault_balances()` quand un RPC est disponible,
   sinon soldes mesurés bloc 61 794 215 (datés, signalés comme tels).
4. Le taux 0 % est relu on-chain (`fetch_flash_loan_fee_pct`) : si la
   gouvernance le monte un jour, le bot utilise le vrai taux.

## 6. Gain mesuré du 0 % — deux cas de référence (calculs rejoués)

### Cas 1 — scénario de référence v1/v2 (spread 20 %, pools 20k $ / 18k $)

| Loan | Aave 0,05 % (net) | Balancer 0 % (net) | Gain |
|---:|---:|---:|---:|
| 100 $ | +17,79 $ | +17,84 $ | +0,05 $ |
| 500 $ | +63,36 $ | +63,61 $ | +0,25 $ |
| **790,16 $ (optimal)** | **+72,68 $** | **+73,07 $** | **+0,39 $** |
| 2 000 $ | −65,05 $ | −64,05 $ | +1,00 $ (reste une perte) |
| 10 000 $ | −4 485,79 $ | −4 480,79 $ | +5,00 $ (reste une grosse perte) |

### Cas 2 — cas gagnant du fork (FORK_TEST_RESULTS.md, spread synthétique 10,41 %)

Loan 8 847,98 $, brut +426,82 $, gas mesuré 0,0066 $ :

| Provider | Prime flash | Net on-chain |
|---|---|---|
| Aave 0,05 % | −4,42 $ | **+422,39 $** |
| **Balancer 0 %** | **0 $** | **+426,81 $ (+4,42 $)** |

**Leçon de trader :** le 0 % ajoute ~0,5 % de net sur un gros trade et ~0,4 $
sur le trade de référence. C'est un vrai gain, pas un changement de jeu : le
sizing (790 $ et pas 10 000 $) vaut 4 500 $, le 0 % vaut 0,39–4,42 $.
Les deux ensemble, c'est le système avancé demandé par Ismail.

## 7. Ce qui a été intégré (v3)

- `balancer_flash.py` — constantes vérifiées, `select_provider()`,
  `fetch_flash_loan_fee_pct()` (relecture on-chain), `fetch_vault_balances()`,
  encodage `vault.flashLoan` (sélecteur `0x5c38449e`, round-trip testé),
  logique `receiveFlashLoan` (vérification `msg.sender == vault`,
  remboursement `amount + fee`).
- `math_engine.py` — `BALANCER_FLASH_FEE = 0.0`, `Costs.flash_provider`
  (`"aave"` par défaut — les tests v1/v2 ne bougent pas), `decide()`
  retourne désormais `flash_provider` + `flash_fee_rate`.
- `executor.py` — `simulate()` / `run()` choisissent le provider par
  opportunité (Balancer ≤ 26 604 $, Aave au-delà) ; le preflight utilise
  le taux du provider choisi, pas le taux Aave par défaut.
- `contracts/FlashLoanArbitrage.sol` — squelette `BalancerFlashLoanArbitrage`
  (`IFlashLoanRecipient`, `receiveFlashLoan`, remboursement `amount + fee`).
  **NON COMPILÉ, NON AUDITÉ** — même blocage `forge install` que v1/v2,
  compilation interdite sans confirmation explicite d'Ismail.
- `config.yaml` — section `flashloan:` (provider préféré/repli, plafond
  50 % du Vault, soldes mesurés) + adresses Vault/collector.
- `test_balancer.py` — 11 tests, tous verts (voir §8).
- `README.md` + `V2_CHANGELOG.md` — sections v3.

## 8. Tests (2026-11-24, tous verts)

- `test_balancer.py` : **11/11 pass** — adresses, taux, `Costs` par provider,
  comparaison fee 0 vs 0,05 % (référence + fork), sélection provider
  (bornes 26 604,00 $ / 26 604,01 $, WETH, meme coin → Aave), encodage
  flashLoan round-trip (1 et 2 tokens), checks `receiveFlashLoan`,
  exécuteur (MEME-WIN via Balancer +73,07 $, MEME-BIG 50 000 $ via Aave),
  lectures live RPC (fee 0,00 %, soldes Vault USDC 53 208,01 $ / WETH
  39 041,66 $ — le test soldes a d'abord SKIP sur RPC indisponible, puis
  PASS au 2e essai : le RPC public est instable, documenté).
- `test_math_engine.py` : **8/8 pass** (inchangé — défaut Aave conservé).
- `test_v2.py` : **11/11 pass**.
- `dry_run.py` : WOULD-EXECUTE MEME-WIN +73,07 $ [provider balancer] /
  SKIP MEME-LOSE net 1,19 $ / **total gas payé 0,00 $**.

## 9. Limites et blockers honnêtes

1. **Contrat NON compilé** : `forge install` OpenZeppelin/Aave bloqué
   (contrôle de risque d'exécution, contenu `lib/`). Aucun bytecode,
   aucun test on-chain de `receiveFlashLoan` — confirmation explicite
   d'Ismail requise avant `forge build`.
2. **Le 0 % est un paramètre de gouvernance** : il peut changer. Le bot
   le relit on-chain, mais un changement entre la lecture et le bloc
   reste possible — le contrat rembourse `amount + feeAmounts` (jamais
   juste `amount`), donc il ne revert pas pour ça, il gagne juste moins.
3. **Vault Base petit** : si d'autres bots empruntent en même temps, le
   solde peut baisser sous le loan entre la sélection et le bloc → le
   `flashLoan` revert (gas perdu, ~0,007 $). La marge 50 % + la
   simulation avant broadcast limitent ce risque, pas l'éliminent.
4. **RPC public instable** : `mainnet.base.org` a renvoyé
   `RemoteDisconnected` pendant les tests (soldes illisibles une fois
   sur deux). Pour le live : RPC dédié + fallback, sinon le choix du
   provider se fait sur des soldes datés.
5. **Aerodrome dans le contrat Solidity** : toujours faux en V2
   (pas d'interface V2 — FORK_TEST_RESULTS.md §7.1). Le squelette
   Balancer n'utilise que des jambes Uni V2 / Sushi V2.
6. **Balancer V3 absent de Base** : pas de plan B V3 sur cette chaîne.

## 10. Sources

- Docs Balancer V2 Flash Loans : https://docs-v2.balancer.fi/reference/contracts/flash-loans.html
  (« Currently there are 0 fees for flash loans », Vault `0xBA12…F2C8`).
- Docs Balancer Protocol Fees : https://docs.balancer.fi/concepts/governance/protocol-fees.html
  (« In V2, governance had the ability to set flash loan fees, but they were always set to zero » ;
  « In V3, flash loans … remain fee-free by design »).
- Docs Balancer V2 Protocol Fees (v2) : https://docs-v2.balancer.fi/concepts/governance/protocol-fees.html
  (« Flash Loan Fees … currently disabled to encourage developers »).
- Flashbots Docs, Flash Loan Basics (Balancer) : https://docs.flashbots.net/flashbots-mev-share/searchers/tutorials/flash-loan-arbitrage/flash-loan-basics
  (« We'll implement flash loans using Balancer because they don't charge any loan fees »).
- Balancer V2 deployments (Base = Vault `0xBA12…F2C8`) : https://github.com/balancer/balancer-deployments/blob/HEAD/v2/tasks/20210418-vault/readme.md
- Basescan — Vault Base : https://basescan.org/address/0xBA12222222228d8Ba445958a75a0704d566BF2C8
- Basescan — ProtocolFeesCollector (⚠️ celui du Vault : 0xce88… ; l'étiquette
  « Sobal : Protocol Fees Collector » 0xCcb4… est un autre contrat) :
  https://basescan.org/address/0xce88686553686DA562CE7Cea497CE749DA109f9F
- DefiLlama Balancer (TVL Base 383 164 $, volume 30 j Base 1,95 M$) :
  https://defillama.com/protocol/balancer
- Lectures on-chain (scripts `/tmp/balancer_check.py`, `balancer_flash.py`) :
  bloc 61 794 215 (Vault code, collector, fee 0, soldes) et bloc 61 794 292
  (V3 Vault : aucun code à `0xbA13…3333`).
