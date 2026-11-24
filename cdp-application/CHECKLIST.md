# ArbAgent — Checklist : ce qu'Ismail doit fournir / décider

**But :** soumettre les demandes CDP Gasless Campaign (15 000 $) + Founders Fuel. Rien ne peut être soumis sans ces éléments — **aucun n'est inventé dans ce pack**.

## 🔴 Bloquant — sans ça, pas de soumission

- [ ] **1. Compte CDP + ProjectID**
  - Aller sur https://portal.cdp.coinbase.com, se connecter avec son compte CDP.
  - Copier le **ProjectID** du projet (celui du bot, ou en créer un : « ArbAgent »).
  - Coller le ProjectID dans `APPLICATION_CDP.md` §1.
  - ⚠️ Ne jamais partager le mot de passe ni la clé API CDP — juste le ProjectID (public, non sensible).

- [ ] **2. Email du compte CDP**
  - Confirmer l'email utilisé sur le compte CDP (probablement codemaofficiel@gmail.com — **à confirmer**, pas deviné).
  - C'est l'email à mettre dans les deux formulaires.

- [ ] **3. Nom final du produit**
  - Proposé : **ArbAgent**. Alternatives : FlashAgent, ArbPilot.
  - Le nom apparaît dans les deux demandes + la landing + la démo. Décision d'Ismail.

- [ ] **4. URL du site (landing page)**
  - **Option recommandée : lien public d'artefact Muse** (la landing sera construite comme page web et partagée par lien public).
  - Pourquoi pas Netlify : les déploiements production sont en pause jusqu'au **13 déc 2026** (crédits épuisés, cycle 13 nov–12 déc) — impossible de déployer la landing sur Netlify avant cette date.
  - Action : confirmer que le lien public d'artefact Muse convient comme « website » pour le formulaire CDP, puis coller l'URL dans `APPLICATION_CDP.md` §1 et `APPLICATION_FOUNDERS_FUEL.md` §3.
  - Alternative (si CDP refuse un lien artefact) : attendre le 13 déc et déployer sur Netlify, ou acheter le domaine (agentdigital.ma ou autre — décision domaine séparée, en attente).

## 🟡 Nécessaire avant soumission (peut être fait en parallèle)

- [ ] **5. Bouton « Create Wallet » visible sur la landing**
  - À intégrer dans la page (CDP Embedded Wallets). Preuve : capture d'écran / lien direct.
  - Condition du palier 5 000 $.

- [ ] **6. Vidéo démo (60–90 s)**
  - Script prêt dans `WEBSITE_CONTENT.md`. Enregistrer la capture du dashboard + voix off (ou confirmer que Muse prépare la vidéo).
  - Publier sur Base App et sur X en taguant @Base et @CoinbaseDev. Copier les liens en preuve.
  - Condition du palier 1 000 $.

- [ ] **7. Confirmer les plafonds de la gas policy**
  - Proposés : 0,10 $/UserOp, 20 $/jour, 500 $/mois, 50 trades/jour, 2 gwei max.
  - Voir `GAS_POLICY.md` §3 — modifiables, mais il faut un chiffre avant de soumettre.

- [ ] **8. Confirmer le mode de financement du gas en attendant**
  - Décision déjà prise par Ismail le 2026-11-24 : **il finance le gas lui-même** (~20 $ de float ETH sur Base) en attendant les crédits, et **il garde 100 % du profit (part sponsor 0 %)**.
  - Action restante : envoyer ~20 $ d'ETH sur Base vers le wallet du bot (adresse à confirmer au moment du déploiement — pas de fonds maintenant, simulation seulement).

## 🟢 Décisions techniques (recommandations dans le pack, à valider)

- [ ] **9. Smart account : CDP Smart Wallet (recommandé)** — voir `SMART_ACCOUNT_PLAN.md` §2. Alternatives : Kernel/ZeroDev, EIP-7702.
- [ ] **10. Confirmer que la re-architecture smart account peut démarrer** (tests Sepolia gratuits, aucun fonds réel).

## 📅 Ordre suggéré

1. Aujourd'hui : items 1–3 (ProjectID, email, nom) — 15 minutes.
2. Cette semaine : item 4 (landing live via artefact Muse) + item 5 (bouton Create Wallet).
3. Ensuite : item 6 (vidéo démo + posts) + item 7 (plafonds).
4. Puis : soumettre les deux demandes le même jour (Ismail soumet lui-même depuis son compte CDP).
5. En parallèle : démarrer la migration smart account (tests Sepolia, 0 $).
6. Réponse Founders Fuel attendue sous 30–60 jours ; Gasless Campaign : délai non publié — re-vérifier la demande de 1 000 $ de nov. 2026 en parallèle (toujours sans réponse au 2026-11-24).

## 📁 Fichiers du pack

| Fichier | Contenu |
|---|---|
| `PRODUCT_SPEC.md` | Concept produit, fonctionnalités, jalons |
| `WEBSITE_CONTENT.md` | Textes landing FR + EN, script vidéo démo |
| `GAS_POLICY.md` | Politique gas + mitigation farmers/bots |
| `APPLICATION_CDP.md` | Réponses formulaire Gasless Campaign + stratégie cases $10k/$5k/$1k |
| `APPLICATION_FOUNDERS_FUEL.md` | Demande Founders Fuel (plan de lancement) |
| `SMART_ACCOUNT_PLAN.md` | Plan de migration smart account (plan seulement, 0 code modifié) |
| `CHECKLIST.md` | Ce fichier — ce qu'Ismail doit fournir / décider |
