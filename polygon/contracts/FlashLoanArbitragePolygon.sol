// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * FlashLoanArbitragePolygon.sol — Port v4.0 du bot Base vers Polygon (137).
 *
 * BUT : emprunter USDC en flash loan 0 frais via Morpho Blue Polygon,
 * acheter WMATIC (ou MEME) sur QuickSwap V2 (pas cher), vendre sur
 * Uniswap V3 (cher), rembourser le loan, garder le reste.
 *
 * ⛔⛔⛔ AVERTISSEMENT — LIRE AVANT TOUT DÉPLOIEMENT ⛔⛔⛔
 *  1. CE CONTRAT EST NON AUDITÉ. Ne jamais déployer avec de vrais fonds
 *     sans audit + paper-trade Amoy 2–4 semaines. Preuve fork uniquement
 *     (voir FORK_TEST_RESULTS_POLYGON.md).
 *  2. MORPHO POLYGON N'EST PAS 0xBBBB… : l'adresse canonique n'a PAS de
 *     code sur Polygon. La bonne adresse est
 *     0x1bF0c2541F820E775182832f06c0B7Fc27A25f67
 *     (vérifiée 2026-11-24 : idToMarketParams == API Morpho, soldes
 *     USDC 113,7 M$ / USDT 122,0 M$, voir POLYGON_FLASH_VERIFICATION.md).
 *  3. Aerodrome N'EXISTE PAS sur Polygon — aucune jambe Aerodrome ici.
 *  4. minProfit par défaut : 3 $ (3 * 1e6 USDC) — confirmé par Ismail.
 *  5. La jambe de vente est Uniswap V3 EN DIRECT (pool.swap + callback) :
 *     le SwapRouter02 Polygon (0x68b346…) N'EXPOSE PAS exactInputSingle
 *     (sélecteur 0x414bf389 ABSENT du bytecode — vérifié 2026-11-24 par
 *     trace debug : le CALL au router revert sans sous-appel). Le router
 *     ne peut donc pas servir pour la jambe V3. Le contrat appelle donc
 *     la pool V3 directement (pattern canonique Uniswap V3) et implémente
 *     `uniswapV3SwapCallback`. La paire Sushi V2 USDC/WMATIC est vide
 *     (~12 $ de liquidité) : la V3 directe est la SEULE jambe de vente
 *     viable. Le sizing off-chain approxime la pool V3 par ses réserves
 *     virtuelles actives (slot0 + liquidité) — voir fork_test_polygon.py.
 *     sqrtPriceLimitX96 = MIN_SQRT_RATIO + 1 (4295128740) : la valeur 0
 *     (« pas de limite ») est rejetée par la pool (elle exige une borne
 *     dans [MIN, MAX]) — la periphery fait cette substitution, ici on
 *     la fait explicitement.
 *
 * SÉCURITÉ :
 *  - `onlyOwner` + `nonReentrant` sur executeArbitrage ; le callback
 *    Morpho est protégé par `msg.sender == MORPHO` (PAS de 2e
 *    nonReentrant — le callback est appelé depuis executeArbitrage,
 *    un 2e garde reverterait, même piège que sur la jambe Morpho Base).
 *  - Le revert on-chain coûte du gas (MATIC ~0,00001 $/trade) : la
 *    stratégie du bot est de NE PAS broadcaster si la simulation
 *    off-chain dit perte. Le `require(profit >= minProfit)` n'est que
 *    le filet si le prix a bougé entre simulation et inclusion.
 *  - Pas de clé privée dans ce repo. Déploiement via Foundry avec
 *    --private-key en variable d'environnement, jamais en dur.
 *
 * Adresses Polygon (vérifiées 2026-11-24, voir POLYGON_FLASH_VERIFICATION.md) :
 *  Morpho Blue Polygon : 0x1bF0c2541F820E775182832f06c0B7Fc27A25f67
 *  USDC (natif)        : 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359
 *  WMATIC              : 0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270
 *  QuickSwap V2 Router : 0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff
 *  Uni V3 SwapRouter02 : 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45
 */

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/security/ReentrancyGuard.sol";

interface IMorpho {
    function flashLoan(address token, uint256 assets, bytes calldata data) external;
}

interface IMorphoFlashLoanCallback {
    function onMorphoFlashLoan(uint256 assets, bytes calldata data) external;
}

interface IUniswapV2Router02 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

/// @notice Pool Uniswap V3 — appel DIRECT (le SwapRouter02 Polygon
/// n'expose pas exactInputSingle, voir en-tête). Seules les fonctions
/// utilisées par la jambe de vente sont déclarées.
interface IUniswapV3Pool {
    function swap(
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 sqrtPriceLimitX96,
        bytes calldata data
    ) external returns (int256 amount0, int256 amount1);

    function token0() external view returns (address);

    function token1() external view returns (address);
}

/// @notice Arbitrage via Morpho Blue Polygon (0 frais) — jambes
///         QuickSwap V2 (achat) / Uniswap V3 DIRECTE (vente, pool.swap).
/// @dev NON AUDITÉ, NON DÉPLOYÉ mainnet. La pool de vente est fixée à la
///      construction (USDC/WMATIC 0,3 % : 0x2DB87C4831B2fec2E35591221455834193b50D1B).
contract MorphoFlashLoanArbitragePolygon is
    IMorphoFlashLoanCallback,
    Ownable,
    ReentrancyGuard
{
    using SafeERC20 for IERC20;

    IMorpho public constant MORPHO =
        IMorpho(0x1bF0c2541F820E775182832f06c0B7Fc27A25f67);

    /// @dev Borne de prix « pas de limite » pour une vente token0->token1
    /// (la pool exige une valeur dans [MIN_SQRT_RATIO, MAX_SQRT_RATIO]).
    uint160 internal constant MIN_SQRT_RATIO_PLUS_ONE = 4295128740;

    address public immutable USDC;
    address public immutable WMATIC;
    IUniswapV2Router02 public immutable routerBuy; // QuickSwap V2 (pas cher)
    IUniswapV3Pool public immutable poolSell; // Uni V3 (cher), appel direct
    bool public immutable zeroForOne; // vrai si WMATIC == token0 de la pool
    uint256 public minProfit; // USDC 6 décimales, ex : 3 * 1e6 = 3 $

    event MorphoPolygonArbitrageExecuted(
        uint256 loan,
        uint256 profit,
        uint256 gasLeft
    );

    constructor(
        address _usdc,
        address _wmatic,
        address _routerBuy,
        address _poolSell,
        uint256 _minProfit
    ) {
        USDC = _usdc;
        WMATIC = _wmatic;
        routerBuy = IUniswapV2Router02(_routerBuy);
        poolSell = IUniswapV3Pool(_poolSell);
        // token0 = l'adresse la plus petite : WMATIC (0x0d50…) < USDC (0x3c49…).
        zeroForOne = poolSell.token0() == _wmatic;
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage Morpho Polygon. `amount` = taille
    /// calculée off-chain par math_engine.py (JAMAIS une taille fixe).
    /// `data` = abi.encode(amount), non vide : le callback vérifie
    /// que le montant reçu est bien celui demandé.
    function executeArbitrage(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0, "amount=0");
        MORPHO.flashLoan(USDC, amount, abi.encode(amount));
    }

    /// @notice Callback Morpho : swaps + remboursement dans la même tx.
    /// Fee = 0 par conception : on rembourse EXACTEMENT `assets`.
    /// Morpho tire le remboursement via transferFrom après ce callback,
    /// d'où l'approve(MORPHO, assets) obligatoire.
    /// @dev PAS de `nonReentrant` ici : le callback est appelé DEPUIS
    /// executeArbitrage (déjà sous nonReentrant) via Morpho.
    function onMorphoFlashLoan(
        uint256 assets,
        bytes calldata data
    ) external override {
        require(msg.sender == address(MORPHO), "appelant != Morpho");
        require(assets > 0, "assets=0");
        uint256 expected = abi.decode(data, (uint256));
        require(expected == assets, "data != assets");

        // 1) USDC -> WMATIC sur QuickSwap V2 (pas cher)
        IERC20(USDC).safeApprove(address(routerBuy), assets);
        address[] memory pathBuy = new address[](2);
        pathBuy[0] = USDC;
        pathBuy[1] = WMATIC;
        uint256[] memory bought = routerBuy.swapExactTokensForTokens(
            assets,
            0,
            pathBuy,
            address(this),
            block.timestamp + 120
        );
        uint256 wmaticAmount = bought[1];

        // 2) WMATIC -> USDC sur Uniswap V3, EN DIRECT via la pool
        //    (pool.swap + callback) — pas de router (voir en-tête).
        //    amountSpecified > 0 = montant d'entrée EXACT (WMATIC).
        (int256 amount0, int256 amount1) = poolSell.swap(
            address(this),
            zeroForOne,
            int256(wmaticAmount),
            MIN_SQRT_RATIO_PLUS_ONE,
            ""
        );
        // Vente token0->token1 : amount0 > 0 (WMATIC payé, via callback),
        // amount1 < 0 (USDC reçu par ce contrat).
        uint256 usdcBack = zeroForOne
            ? uint256(-amount1)
            : uint256(-amount0);

        // 3) Filet de sécurité : si le profit est sous le minimum, on
        //    revert — on paie le gas (MATIC ~0,0095 $ au prix mesuré),
        //    mais on ne perd PAS le loan. (Le bot évite ce cas par la
        //    simulation off-chain.)
        require(usdcBack >= assets, "pas de quoi rembourser le loan");
        uint256 profit = usdcBack - assets;
        require(profit >= minProfit, "profit < minProfit");

        // 4) Rembourser Morpho : elle tire `assets` via transferFrom.
        //    Fee = 0, donc exactement `assets` — jamais plus.
        IERC20(USDC).safeApprove(address(MORPHO), assets);

        emit MorphoPolygonArbitrageExecuted(assets, profit, gasleft());
    }

    /// @notice Callback Uniswap V3 — appelée par la pool de vente pendant
    ///         `pool.swap`. Paie le delta positif (le token vendu) à la pool.
    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata /* data */
    ) external {
        require(msg.sender == address(poolSell), "callback: not pool");
        if (amount0Delta > 0) {
            IERC20(poolSell.token0()).safeTransfer(
                msg.sender,
                uint256(amount0Delta)
            );
        } else if (amount1Delta > 0) {
            IERC20(poolSell.token1()).safeTransfer(
                msg.sender,
                uint256(amount1Delta)
            );
        }
    }

    /// @notice Retirer le profit accumulé (USDC) vers l'owner.
    function withdrawProfit() external onlyOwner {
        uint256 bal = IERC20(USDC).balanceOf(address(this));
        require(bal > 0, "rien a retirer");
        IERC20(USDC).safeTransfer(owner(), bal);
    }

    /// @notice Changer le profit minimum (ex: si le gas monte).
    function setMinProfit(uint256 _minProfit) external onlyOwner {
        minProfit = _minProfit;
    }

    /// @notice Sauvetage : retirer un token bloqué par erreur (jamais USDC du loan en cours).
    function rescueToken(address token) external onlyOwner {
        uint256 bal = IERC20(token).balanceOf(address(this));
        IERC20(token).safeTransfer(owner(), bal);
    }
}
