# ArbAgent — Contenu du site web (landing page)

**Nom proposé :** ArbAgent — « L'agent d'arbitrage flash-loan sur Base ».
**Langues :** français + anglais (même page, deux versions ci-dessous).
**Hébergement proposé :** lien public d'artefact Muse (Netlify en pause jusqu'au 13 déc 2026).
**URL du site :** [TODO ISMAIL : coller ici l'URL publique de l'artefact une fois partagée.]

---

## VERSION FRANÇAISE

### Hero

**Titre :** ArbAgent — l'agent qui chasse les écarts de prix sur Base.
**Sous-titre :** Flash loan Morpho à 0 % de frais. Simulation avant chaque trade. Profit net minimum 3 $. Aucun fonds utilisateur, jamais.
**Boutons :** [Voir le dashboard live] [Create Wallet — Base Account]

### Section « Comment ça marche » (3 étapes)

1. **Détecter.** Le scanner surveille les meme coins sur Aerodrome et Uniswap, et repère les écarts de prix entre deux DEX.
2. **Simuler.** Chaque opportunité est simulée sur un fork de Base. Si le profit net simulé est < 3 $, le trade est ignoré — 0 $ de gas perdu.
3. **Exécuter.** Seules les opportunités rentables sont exécutées, en une seule transaction atomique : emprunt flash Morpho (0 %), swap, swap, remboursement. Si ça échoue, tout est annulé.

### Section « Chiffres live » (étiquetés honnêtement)

- Opportunités détectées aujourd'hui : [compteur live]
- Dernier trade exécuté : [loan / profit brut / gas / profit net]
- Taux de trades ignorés (simulation) : [ % ] — « ignoré » veut dire « 0 $ perdu ».

### Section « Sécurité & honnêteté »

- **Aucune garde :** ArbAgent ne détient jamais vos fonds. Le flash loan est remboursé dans la même transaction.
- **Aucun rendement promis :** l'arbitrage est compétitif ; l'attente réaliste est de 0 à 3 opportunités ≥ 3 $ par semaine.
- **Simulation d'abord :** les trades perdants sont annulés avant envoi, pas après.
- **Contrat audité ?** Pas encore — audit externe obligatoire avant tout usage mainnet réel. Aujourd'hui : simulation seulement.

### Section « Pourquoi Base ? »

Base n'a pas de mempool public : personne ne peut voir votre transaction avant qu'elle soit ordonnée. Les blocs durent 200 ms. Le gas coûte quelques millièmes de dollar.

### FAQ (courte)

- **Est-ce que je dois déposer de l'argent ?** Non. Il n'y a pas de dépôt.
- **Est-ce que le bot trade avec mon argent ?** Non. Il n'a accès à aucun fonds utilisateur.
- **Combien ça peut rapporter ?** On ne promet rien. Les chiffres affichés sont mesurés, pas projetés.
- **C'est quoi un flash loan ?** Un emprunt sans collatéral, remboursé dans la même transaction — sinon tout est annulé.

### Footer

ArbAgent, par CODEMA — Mohammedia, Maroc. Contact : WhatsApp 0788241783.
Base uniquement. Simulation seulement tant que l'audit n'est pas terminé.

---

## ENGLISH VERSION

### Hero

**Title:** ArbAgent — the agent hunting price gaps on Base.
**Subtitle:** Morpho flash loans at 0% fee. Simulation before every trade. Minimum net profit $3. No user funds, ever.
**Buttons:** [See the live dashboard] [Create Wallet — Base Account]

### How it works (3 steps)

1. **Detect.** The scanner watches meme coins on Aerodrome and Uniswap, spotting price gaps between two DEXs.
2. **Simulate.** Every opportunity is simulated on a Base fork. If simulated net profit is < $3, the trade is skipped — $0 gas lost.
3. **Execute.** Only profitable opportunities run, in one atomic transaction: Morpho flash loan (0%), swap, swap, repay. If it fails, everything reverts.

### Live numbers (honestly labelled)

- Opportunities detected today: [live counter]
- Last executed trade: [loan / gross profit / gas / net profit]
- Skipped-trade rate (simulation): [ % ] — "skipped" means "$0 lost".

### Safety & honesty

- **No custody:** ArbAgent never holds your funds. The flash loan is repaid in the same transaction.
- **No promised returns:** arbitrage is competitive; the realistic expectation is 0–3 executable ≥ $3 opportunities per week.
- **Simulation first:** losing trades are cancelled before broadcast, not after.
- **Contract audited?** Not yet — an external audit is mandatory before any real mainnet use. Today: simulation only.

### Why Base?

Base has no public mempool: nobody can see your transaction before it is ordered. Blocks are 200 ms. Gas costs a fraction of a cent.

### FAQ (short)

- **Do I need to deposit money?** No. There is no deposit.
- **Does the bot trade with my money?** No. It has access to no user funds.
- **How much can it earn?** We promise nothing. Displayed numbers are measured, not projected.
- **What is a flash loan?** A collateral-free loan repaid in the same transaction — otherwise everything reverts.

### Footer

ArbAgent, by CODEMA — Mohammedia, Morocco. Contact: WhatsApp 0788241783.
Base only. Simulation only until the audit is complete.

---

## SCRIPT VIDÉO DÉMO (60–90 s) — pour Base App & X (@Base, @CoinbaseDev)

**Format :** capture d'écran du dashboard + voix off. Durée cible : 75 s.

| Temps | Visuel | Voix off (EN, sous-titres FR) |
|---|---|---|
| 0–8 s | Logo ArbAgent + dashboard live | « This is ArbAgent — a flash-loan arbitrage agent on Base. » |
| 8–20 s | Scanner : une opportunité apparaît (spread, taille optimale) | « It scans meme coins on Aerodrome and Uniswap, and sizes every opportunity mathematically. » |
| 20–35 s | Simulation : trade ignoré (profit < 3 $) | « Losing trades are simulated first — and skipped. Zero gas lost. » |
| 35–50 s | Trade exécuté : loan, profit brut, gas, net | « Only net-positive trades execute — one atomic transaction, Morpho flash loan at 0% fee. » |
| 50–65 s | Bouton « Create Wallet » (Base Account) | « Users create a Base Account in one click — gasless, powered by CDP Paymaster. » |
| 65–75 s | Écran final : URL du site + tags | « ArbAgent on Base. Built by CODEMA. @Base @CoinbaseDev » |

**Texte du post X :**
> ArbAgent is live on Base: a flash-loan arbitrage agent with simulation-first execution, Morpho 0% flash loans, and gasless onboarding via Base Accounts + CDP Paymaster. Dashboard: [URL] @Base @CoinbaseDev

**Texte du post Base App :** même texte + lien du site.
**[TODO ISMAIL : enregistrer la démo (capture d'écran + voix), ou confirmer que Muse prépare la vidéo.]**
