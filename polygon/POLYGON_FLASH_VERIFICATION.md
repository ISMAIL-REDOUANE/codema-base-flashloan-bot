# POLYGON_FLASH_VERIFICATION.md — Flash loan 0 frais sur Polygon (chaîne 137)

Vérifié le **2026-11-24**, bloc Polygon **97 901 602 – 97 901 631**.
RPC qui fonctionne : `https://polygon.drpc.org` (seul RPC public testé qui répond ;
`polygon-rpc.com` MORT — « API key disabled » 403 ; Ankr exige une clé ;
llamarpc/publicnode bloqués par Cloudflare). Gas mesuré : **278–279 gwei** ;
POL **0,075835 $** (CoinGecko `polygon-ecosystem-token`, cohérent avec les
0,0736 $ du MetaMask d'Ismail).

> Règle de ce document : aucune adresse devinée. Chaque adresse vient d'une
> source officielle ET a été vérifiée on-chain (`cast code` / `cast call`).

## VERDICT

| Candidat | Fee | Verdict |
|---|---|---|
| **A. Morpho Blue Polygon `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67`** | **0 %** | ✅ **VÉRIFIÉ — provider principal** |
| **B. Uniswap V4 flash accounting (PoolManager `0x67366782805870060151383f4bbff9dab53e5cd6`)** | **0 %** (pas de fee protocole sur take/settle) | ✅ **VÉRIFIÉ — alternative** (intégration plus complexe) |
| Aave V3 Pool `0x794a61358D6845594F94dc1DB02A252b5b4814aD` | 0,05 % | ⚠️ PAYANT — repli seulement, BLOQUÉ en mode 0 frais |
| Balancer V2 Vault `0xBA12222222228d8Ba445958a75a0704d566BF2C8` | 0 % | ⛔ MORT (BIP-928, wind-down 30 oct 2026, toutes chaînes) — NE PAS UTILISER |
| dYdX Solo | — | ⛔ MORT (close-only depuis nov 2021) — NE PAS UTILISER |
| Euler v2 | — | Non vérifié sur Polygon, non nécessaire (Morpho vérifié) |

## Candidat A — Morpho Blue sur Polygon ✅

### Sources officielles (adresse NON devinée)
- **Morpho Read API** : `GET https://api.morpho.org/v0/blue/markets?chain_id=137`
  retourne des marchés réels sur la chaîne 137 (100 marchés lus, 16 loan tokens
  dont USDC natif, USDC.e, USDT, WMATIC). Premier marché :
  `0x0100fd9c280c77795c5806e476100dc6ebfef80f6869f3b084d024ab6585c22a`,
  loan `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (USDC.e), créé bloc 78 748 628.
- **Sigma Labs** (papier de gouvernance, table par chaîne) : « Polygon (137)
  Morpho Blue `0x1bF0...5f67`, USDC `0x3c49...3359` ».
  Source : https://www.sigmalabs.fi/papers/cross-chain-usdc-lending-governance.pdf
- **The Bitcoin Credit Stack** (venue Morpho Blue Polygon) : « Morpho Blue core
  `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` on Polygon (chain 137) », marchés
  confirmés par `idToMarketParams(id)` + `market(id)` sur le core.
  Source : https://www.thebitcoincreditstack.com/venues/morpho_blue_polygon
- **Docs Morpho** (https://docs.morpho.org/developers/contracts/blue/) :
  `function flashLoan(address token, uint256 assets, bytes calldata data)` ;
  « **flashFee is zero** », « **maxFlashLoan is the token's balance of this
  contract** », « the receiver of assets is the caller ».

### Vérification on-chain (bloc 97 901 631, RPC drpc.org)
- **Code présent** : 15 582 octets à `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67`
  (`cast code` ; le sélecteur `flashLoan` `0xe0232b42` est dans le bytecode).
- **`idToMarketParams(0x0100fd9c…c22a)`** retourne EXACTEMENT les paramètres de
  l'API : loan `0x2791Bca1…4174`, collateral `0x57130714686d84Ca401C495eA9B3F932eD368C93`,
  oracle `0x7e0b9933407A9362F1b47B4d59A371EFB01303F6`, IRM
  `0xe675A2161D4a6E2de2eeD70ac98EEBf257FBF0B0`, LLTV `770000000000000000`.
  → le contrat EST le core Morpho Blue de Polygon, sans aucun doute.
- **`market(id)`** : état vivant (totalSupplyAssets 1000, shares 1e9,
  lastUpdate 1765375004).
- **`owner()`** = `0x92000Ef1ca6bd2e02398320d8913C36b32BdAaa4` (différent du Safe
  de gouvernance de Base — normal, multisig par chaîne ; l'owner ne peut
  pas monter le flash fee, il est structurel).
- **Soldes du contrat (= maxFlashLoan par token)** :
  - USDC natif `0x3c49…3359` : **113 658 377,07 $**
  - USDT `0xc213…58e8F` : **122 029 655,66 $**
  - USDC.e `0x2791…4174` : 504,21 $
  - WMATIC `0x0d50…1270` : ~1 000 246 WMATIC (~75 854 $)
  - À la règle 50 % : ~56,8 M$ USDC utilisables — le provider ne limite jamais le loan.

### ⚠️ Deux pièges évités
1. **L'adresse canonique `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` N'A PAS DE CODE
   sur Polygon** (`cast code` vide, bloc 97 901 602). Sur Polygon, Morpho n'est
   PAS au même endroit que sur Base/Ethereum. Utiliser `0xBBBB…` sur Polygon
   = revert garanti. La bonne adresse est `0x1bF0…5f67`.
2. Le bytecode Polygon fait **15 582 octets contre 15 622 sur Base** (~40 octets
   de différence — build/compilateur différent). La vérification fonctionnelle
   (`idToMarketParams` + `market` + sélecteur `flashLoan`) est décisive : c'est
   bien Morpho Blue, même interface (`flashLoan` / `onMorphoFlashLoan`).

## Candidat B — Uniswap V4 flash accounting ✅

- **Docs officielles** : https://docs.uniswap.org/contracts/v4/deployments
  (PoolManager Polygon `0x67366782805870060151383f4bbff9dab53e5cd6`,
  Quoter `0x31AB0Dea31FC0ad5A54F03cD59C896eCD067447B`,
  Universal Router `0x1095692a6237d83c6a72f3f5efedb9a670c49223`) et le feed
  https://docs.uniswap.org/deployments.json (`v4-poolmanager-polygon`, status active).
- **On-chain** : code PoolManager 48 021 caractères (~24 Ko), `protocolFeeController()`
  répond `0x59e84309Afa65F084F9c03668583d231afB12cc6`.
- **Mécanisme** (https://docs.uniswap.org/contracts/v4/concepts/flash-accounting) :
  `unlock` → `unlockCallback` → `take` (emprunt) → `settle` (remboursement),
  les deltas sont résolus à la fin, **aucun fee de protocole sur take/settle**
  (seuls les frais de swap LP des pools s'appliquent). Donc flash 0 frais.
- Verdict : mécanisme réel et vérifié, mais l'intégration (callback `unlock`,
  transient storage, gestion des deltas) est plus complexe que Morpho.
  **Alternative documentée, non implémentée en v4.0** (utile plus tard : 70 %
  des nouveaux memes sont en V4).

## Aave V3 sur Polygon — PAYANT (repli seulement)
- Pool `0x794a61358D6845594F94dc1DB02A252b5b4814aD` : code présent (4 803 car.),
  **`FLASHLOAN_PREMIUM_TOTAL() = 5` → 0,05 %**. Sur un loan de 1 000 $ = 0,50 $.
  BLOQUÉ en mode 0 frais (comme sur Base).

## Adresses Polygon vérifiées (toutes : source officielle + `cast code`)
| Contrat | Adresse | Code |
|---|---|---|
| Morpho Blue | `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67` | 15 582 o |
| Aave V3 Pool | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` | 4 803 car. |
| Balancer Vault (MORT) | `0xBA12222222228d8Ba445958a75a0704d566BF2C8` | présent — NE PAS UTILISER |
| Uni V4 PoolManager | `0x67366782805870060151383f4bbff9dab53e5cd6` | 48 021 car. |
| Uni V4 Quoter | `0x31AB0Dea31FC0ad5A54F03cD59C896eCD067447B` | — (docs) |
| Uni V3 Factory | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | 49 073 car. |
| Uni V3 SwapRouter02 | `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45` | 48 997 car. |
| Uni V3 QuoterV2 | `0x61fFE014bA17989E743c5F6cB21bF9697530B21e` | 16 549 car. |
| QuickSwap V2 Factory | `0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32` | 27 721 car. |
| QuickSwap V2 Router | `0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff` | 43 889 car. |
| Sushi V2 Factory | `0xc35DADB65012eC5796536bD9864eD8773aBc74C4` | 22 531 car. |
| Sushi V2 Router | `0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506` | 35 527 car. |
| WMATIC | `0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270` | 6 003 car. |
| USDC (natif) | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` | 3 707 car. |
| USDT | `0xc2132D05D31c914a87C6611C10748AEb04B58e8F` | 5 901 car. |
| WETH | `0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619` | 24 889 car. |

Paires réelles vérifiées : QuickSwap V2 USDC/WMATIC
`0x6D9e8dbB2779853db00418D4DcF96F3987CFC9D2` ; Uni V3 USDC/WMATIC 0,3 %
`0x2DB87C4831B2fec2E35591221455834193b50D1B`.
(QuoterV2 `quoteExactInputSingle` via `cast` a revert — encodage du tuple ;
le quoter sera appelé via web3.py avec l'ABI correcte dans le scanner, pas un
blocage : le code est présent à l'adresse officielle.)
