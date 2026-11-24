# RESEARCH — Adresses vérifiées, Base (chain 8453)

Date de vérification : 2026-11-24. Toutes les adresses ci-dessous ont été
recoupées sur au moins 2 sources indépendantes. **Ne jamais utiliser une
adresse non vérifiée sur Basescan avant un envoi réel.**
Règle d'or : re-vérifier chaque adresse sur https://basescan.org avant
tout déploiement mainnet — les adresses peuvent changer (proxy, nouvelle
version du router).

## ⛔ CORRECTION v3.3 (2026-11-24) — Balancer est MORT

Balancer a été liquidé (wind-down **BIP-928, 30 oct 2026**) : pools en
retraits seuls, bug bounty terminé, Balancer Labs dissoute. Le Vault
`0xBA12…F2C8` ne doit PLUS être utilisé comme provider de flash loan.
Le remplaçant est **Morpho Blue** (ci-dessous) : même fee 0 %, mais par
conception (pas un paramètre de gouvernance) et liquidité ~3 500× plus
grande. Détail : `BALANCER_RESEARCH.md` (correction en tête de fichier).

## Morpho Blue — flash loan 0 frais (provider préféré, v3.3)

| Fait | Valeur | Preuve |
|---|---|---|
| **Morpho Blue Base (8453)** | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` | Singleton canonique, même adresse sur toutes les chaînes ; code présent, 15 623 octets, bloc 61 806 974 |
| `flashLoan(address token, uint256 assets, bytes calldata data)` | sélecteur `0xe0232b42` | Docs Morpho officielles https://docs.morpho.org/developers/contracts/blue/ ; repo morpho-org/morpho-blue `src/Morpho.sol` |
| `onMorphoFlashLoan(uint256 assets, bytes calldata data)` | sélecteur `0x31f57072` | Même sources ; vérifié par keccak le 2026-11-24 |
| **Frais flash** | **0 % par conception** | Docs officielles : « flashFee is zero » ; il n'existe AUCUNE fonction `flashFee` sur le contrat — l'eth_call du sélecteur ERC-3156 `0xd9d98ce4` REVERT (« execution reverted », bloc 61 806 974). Aucune gouvernance ne peut monter ce fee. |
| `maxFlashLoan` | = solde du token chez Morpho | Docs officielles : « maxFlashLoan is the token's balance of this contract » (liquidité + collatéral de tous les marchés + dons) |
| Receiver | = l'appelant (`msg.sender`) | Docs officielles : « The receiver of assets is the caller » — pas de paramètre recipient |
| Remboursement | `approve(Morpho, assets)` exact | Morpho tire `assets` via `transferFrom` après le callback ; fee 0 donc on rembourse exactement `assets` |
| **Soldes Morpho Base, bloc 61 806 974** | **USDC 328 711 525,75 $ / WETH 88 713,53 (~148,9 M$)** | Lus on-chain (`balanceOf`) ; re-vérifiés sur fork bloc 61 807 834 : USDC 328 656 200,75 $ / WETH 88 714,39 |
| TVL Morpho Blue sur Base | **3,336 Md$** | DefiLlama, 24 nov 2026 |
| Preuve fork | **WIN +17,58 $** (loan 366,50 $), perdant SKIP 0 $ | `FORK_TEST_RESULTS.md` §11, bloc 61 807 834 |

Sources : docs Morpho officielles (ci-dessus) ; docs.eco.com (référence
Morpho Blue, Base morpho = `0xBBBB…FFCb`) ; agent.zbang.net (page
contract-powers Base, contrat « Morpho », source vérifiée) ; darknavy.org
(rapport d'exploit Base : source de flash loan Morpho Blue `0xbbbb…ffcb`,
`Morpho.flashLoan(USDC, 97_000e6, data)`, callback `onMorphoFlashLoan`
sélecteur `0x31f57072`).

| Rôle | Adresse Base (8453) | Sources |
|---|---|---|
| **Morpho Blue (flash loan 0 %)** | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` | docs.morpho.org/developers/contracts/blue, docs.eco.com, agent.zbang.net, darknavy.org — vérifié on-chain (code 15 623 o, bloc 61 806 974) |
| **Aave V3 Pool** | `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5` | docs.eco.com (Aave V3), aave.com/docs/resources/addresses, Dedaub v3.md (vérifié on-chain 2026-05-29), Avail docs |
| **Aave V3 PoolAddressesProvider** | `0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D` | docs.eco.com, Aave Address Book, Dedaub. ⚠️ Une source secondaire (BootNodeDev) affiche `...ad64B` en dernier caractère — la majorité + docs officiels disent `...ad64D`. Vérifier sur Basescan via `getPool()` du provider. |
| **Aave V3 PoolDataProvider** | `0x2d8A3C5677189723C4cB8873CfC9C8976FDF38Ac` | agent-credit/contracts.md (GitHub) — à re-vérifier |
| **Aave V3 UiPoolDataProvider** | `0x5d4D4007A4c6336550DdAa2a7c0d5e7972eebd16` | BootNodeDev / Aave Address Book — à re-vérifier |
| **WETH** | `0x4200000000000000000000000000000000000006` | developers.uniswap.org (Base Deployments), topofbase.com, Basescan |
| **USDC (native, Circle)** | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | developers.circle.com, Basescan token page, topofbase.com — 6 décimales |
| **USDbC (bridged, legacy — NE PAS confondre avec USDC)** | `0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA` | Dedaub Uniswap V2.md |
| **Uniswap V3 Factory** | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` | developers.uniswap.org (Base Deployments, officiel) |
| **Uniswap V3 SwapRouter02** | `0x2626664c2603336E57B271c5C0b26F421741e481` | developers.uniswap.org (officiel) |
| **Uniswap V3 QuoterV2** | `0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a` | developers.uniswap.org (officiel). ⚠️ Certains blogs donnent `0xC5290058...` — c'est l'adresse **Base Sepolia**, pas mainnet. |
| **Uniswap UniversalRouter** | `0x6fF5693b99212Da76ad316178A184AB56D299b43` | developers.uniswap.org (officiel) |
| **Uniswap V2 Factory (Base)** | `0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6` | Dedaub v2.md (vérifié `eth_getCode` 2026-05-21), DeepWiki Uniswap docs. ⚠️ L'ancienne proposition gov donnait `0x5C69bE...` (adresse Ethereum) — ne pas utiliser sur Base. |
| **Uniswap V2 Router02 (Base)** | `0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24` | Dedaub v2.md, DeepWiki. Même adresse que sur BNB/Arbitrum. |
| **Aerodrome Router (Classic AMM)** | `0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43` | aerodrome.finance/security, docs.eco.com, DeFiScan |
| **Aerodrome PoolFactory** | `0x420DD381b31aEf6683db6B902084cB0FFECe40Da` | aerodrome.finance/security, docs.eco.com, DeFiScan |
| **Aerodrome Slipstream CLFactory** | `0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A` | DeFiScan / RevertFinance deploy script |
| **Aerodrome Slipstream SwapRouter (legacy)** | `0xBE6D8f0d05cC4be24d5167a3eF062215bE6D18a5` | DeFiScan. ⚠️ Nouvelle génération Gauges V3 : router `0x698Cb2b6dd822994581fEa6eA4Fc755d1363A92F`, quoter `0xCd2A7D98e82D6107eac1828ce8DeAA6acB65b555` — vérifier la génération du pool avant usage. |
| **SushiSwap V2 Factory (Base)** | `0x71524B4f93c58fcbF659783284E38825f0622859` | sushiswap/v2-core DeepWiki, Basescan label "SushiSwap V2: Factory" |
| **SushiSwap V2 Router02 (Base)** | `0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891` | sushiswap/v2-core DeepWiki, Basescan label "Sushi: Router v2" |
| **SushiSwap V3 Factory (Base)** | `0xc35DADB65012eC5796536bD9864eD8773aBc74C4` | docs.sushi.com/contracts/clamm, Basescan label |

## Flash loan — frais vérifiés

- **Morpho Blue : 0 % par conception** (pas un paramètre de gouvernance —
  il n'y a pas de fonction `flashFee` : l'eth_call revert, vérifié bloc
  61 806 974). `flashLoan(token, assets, data)` — le receiver est
  l'appelant, `maxFlashLoan` = le solde du token chez Morpho, callback
  `onMorphoFlashLoan(uint256 assets, bytes calldata data)` (sélecteur
  `0x31f57072`). Remboursement : `approve(Morpho, assets)` exact.
  Soldes Base : USDC **328,7 M$** / WETH **88 713,53**. Voir § Morpho Blue
  ci-dessus et `FORK_TEST_RESULTS.md` §11 (WIN +17,58 $ sur fork).
- **Aave V3 : 0,05 %** (`FLASHLOAN_PREMIUM_TOTAL` = 5 bps), confirmés par
  aave.com/docs/aave-v3/guides/flash-loans : « The flash loan fee is set
  to 0.05% at deployment and can be changed by governance vote. Read
  `FLASHLOAN_PREMIUM_TOTAL` for the current value. »
  V2 chargeait 0,09 % — ne pas confondre.
- `flashLoanSimple()` = 1 seul actif, moins de gas, frais jamais annulés.
  `flashLoan()` = plusieurs actifs, frais annulables pour les
  `flashBorrowers` approuvés. **V1 utilise `flashLoanSimple()` en USDC.**
- Le code NE DOIT PAS hardcoder 0,05 % en production : lire
  `FLASHLOAN_PREMIUM_TOTAL()` sur le Pool au runtime (le contrat le fait
  via le premium retourné dans `executeOperation`).

## Réseau

- Chain ID Base mainnet : **8453** (0x2105), RPC public : `https://mainnet.base.org`
- Explorer : https://basescan.org — Base Sepolia testnet : chain 84532,
  RPC `https://sepolia.base.org`
- Gas token : ETH (bridgé). Base = L2 OP-Stack, gas très bas vs Ethereum,
  mais un revert on-chain coûte quand même du gas — d'où la règle :
  **simuler off-chain avant tout broadcast.**

## Non vérifié / à ne pas utiliser tel quel

- Adresses de pools meme-coin individuels : elles changent à chaque token,
  on les découvre via les factories (`getPair` / `getPool`) et DexScreener,
  jamais en dur.
- Adresses de tokens meme : à découvrir via scanner, vérifier honeypot
  avant tout trade.
- Prix ETH/USD en config : hypothèse de travail, à remplacer par un oracle
  / CoinGecko au runtime.
