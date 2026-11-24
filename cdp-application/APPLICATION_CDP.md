# Demande CDP — Base Gasless Campaign (Paymaster Gas Credits)

**Formulaire :** https://docs.google.com/forms/d/1yPnBFW0bVUNLUN_w3ctCqYM9sjdIQO3Typ53KXlsS5g/viewform
**Statut :** BROUILLON — ne pas soumettre avant que tous les [TODO ISMAIL] soient remplis et la landing page live.
**⚠️ NE PAS SOUMETTRE SANS ISMAIL :** la soumission utilise son compte CDP.

> Rappel : une demande de 1 000 $ (« demo ») a déjà été envoyée le 2026-11-21 à 18:52 (projet flash-loan-base, compte CDP sous codemaofficiel@gmail.com) — reçue, **sans réponse d'approbation/refus au 2026-11-24**. Cette nouvelle demande vise les paliers supérieurs, avec un produit. Ne pas présenter la demande de 1 000 $ comme approuvée.

## 1. Champs du formulaire et réponses proposées

| Champ du formulaire | Réponse proposée |
|---|---|
| Email | [TODO ISMAIL : email du compte CDP — probablement codemaofficiel@gmail.com, à confirmer] |
| Email used on CDP account | [TODO ISMAIL : même email que ci-dessus, à confirmer] |
| ProjectID (CDP Portal Dashboard) | [TODO ISMAIL : copier le ProjectID depuis https://portal.cdp.coinbase.com — NE PAS INVENTER] |
| App / product name | ArbAgent **[TODO ISMAIL : confirmer le nom final — alternatives : FlashAgent, ArbPilot]** |
| Website | [TODO ISMAIL : URL publique de la landing page (lien artefact Muse) — voir CHECKLIST.md] |
| What are you building? | ArbAgent is a public arbitrage dashboard and flash-loan arbitrage agent on Base. It detects meme-coin price gaps across Aerodrome and Uniswap, simulates every opportunity on a Base fork, and executes only trades with ≥ $3 simulated net profit via Morpho Blue flash loans (0% fee) in one atomic transaction. Users follow the bot live and create a Base Account (Smart Wallet) in one click. The bot never holds user funds — no custody, no deposits. Built by CODEMA (Mohammedia, Morocco). |
| Amount requested (checkboxes) | Voir §2 ci-dessous |
| CDP Embedded or Server Wallets? | Yes — CDP Embedded Wallets (Base Accounts / Smart Wallet) for the « Create Wallet » button |
| Supporting Base Accounts? | Yes — Base Accounts supported in the main UI |
| Proof-of-placement link | [TODO ISMAIL : URL de la landing avec le bouton « Create Wallet » visible — après mise en ligne] |
| Proof-of-post link | [TODO ISMAIL : lien du post démo sur Base App & X — après publication] |
| Gas policy + mitigating farmers/bots (obligatoire) | Voir §3 ci-dessous (texte complet dans GAS_POLICY.md) |

## 2. Stratégie des cases à cocher ($10k / $5k / $1k)

Le formulaire propose trois cases (total 16 000 $, plafond annoncé 15 000 $ — traiter 15 000 $ comme le plafond réel).

| Case | Montant | Condition | Recommandation |
|---|---|---|---|
| $10,000 | Base Account support + onboarded to Paymaster | Intégration Base Accounts + Paymaster | ✅ **COCHER** — c'est le cœur de la demande : le produit supporte Base Accounts et utilise le Paymaster |
| $5,000 | Preferred « Create Wallet » placement | Bouton « Create Wallet » bien visible dans l'UI principale | ✅ **COCHER** — le bouton est prévu dans l'interface principale de la landing / du dashboard (voir PRODUCT_SPEC.md §4.2) |
| $1,000 | Demo of Base Account integration posted on Base App & X (tag @Base, @CoinbaseDev) | Vidéo démo publiée | ✅ **COCHER** — la démo vidéo est prévue (script dans WEBSITE_CONTENT.md) ; la publier avant ou juste après la soumission, et coller le lien en preuve |

**Recommandation : cocher les trois cases.** Chacune correspond à un livrable réel que le produit s'engage à fournir. Le total affiché (16 000 $) dépasse le plafond de 15 000 $ : le montant accordé sera plafonné par Coinbase, ce n'est pas un motif de refus.

## 3. Réponse « gas policy + farmers/bots » (à coller dans le formulaire, EN)

> Gas is sponsored only for our own arbitrage executor contract (allowlisted, single address, single smart-account caller). No open sponsorship endpoint exists, so there is nothing to farm: visitors create a Base Account to follow the bot, their wallets receive no sponsored gas. Every trade is simulated off-chain first and requires ≥ $3 simulated net profit; the contract enforces minProfit ≥ $3 on-chain, so unprofitable trades never execute. Caps: $0.10 gas per UserOp, $20/day, $500/month, 50 trades/day max, 2 gwei gas cap, circuit breaker (pause after 3 reverts). All sponsored UserOps are logged and the sponsorship can be revoked in one action. No token, no airdrop, no reward to farm.
>
> Impact: every credit dollar funds only pre-simulated profitable trades (≥ $3 net) — credits never pay for a losing trade, since losers are cancelled before broadcast ($0). If credits run out, the bot falls back to a self-funded ~$20 ETH gas float, with no interruption and no cost to any third party.

(Texte complet et justifications : `GAS_POLICY.md`.)

## 4. Avant de soumettre — vérifications

- [ ] Landing page en ligne à l'URL indiquée (bouton « Create Wallet » visible)
- [ ] ProjectID copié depuis le portail CDP (pas inventé)
- [ ] Nom du produit confirmé par Ismail
- [ ] Vidéo démo enregistrée (ou au moins planifiée avec date)
- [ ] Les trois cases cochées
- [ ] Ismail relit les réponses et soumet lui-même depuis son compte CDP
