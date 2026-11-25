// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * CurveFlashArbPolygon.sol — Jambe Curve pour le bot Polygon (v4.5).
 *
 * BUT : exploiter la route 4-jambes mesurée live le 2026-11-25 :
 *   Morpho USDC natif (flash 0 %) -> USDC.e (Uni V3 0,01 %)
 *   -> USDT (Uni V3 0,01 %) -> USDC.e (Curve am3pool, fee 0,001 %)
 *   -> USDC natif (Uni V3 0,01 %) -> remboursement Morpho.
 * Quotes live vérifiées (blocs 97 921 306–308 puis 97 921 961–963,
 * 97 922 005) : 1 000 $ -> net +1,11 $ ; 5 000 $ -> +5,61 $ ;
 * 20 000 $ -> +21,60 $ (gas budgété 2× ~0,032 $).
 *
 * ⛔⛔⛔ AVERTISSEMENT — LIRE AVANT TOUT DÉPLOIEMENT ⛔⛔⛔
 *  1. CE CONTRAT EST NON AUDITÉ. Ne jamais déployer avec de vrais fonds
 *     sans audit + paper-trade. Preuve fork uniquement (voir
 *     CURVE_LEG_FORK_TEST_2026-11-25.md). Le mainnet reste BLOQUÉ
 *     (audit + approbation d'Ismail par batch).
 *  2. CORRECTION IMPORTANTE vs le rapport LOW_FEE_PROFIT_POLYGON.md :
 *     la jambe Curve NE rend PAS de l'USDC natif. Vérifié on-chain
 *     (bloc 97 921 969) : underlying_coins(1) du am3pool =
 *     0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174 = USDC.e (bridgé),
 *     PAS l'USDC natif (0x3c49…). Les amTokens Aave v2 de Polygon
 *     wrappent l'USDC.e. Donc exchange_underlying(2, 1) rend de
 *     l'USDC.e, et une 4e jambe (USDC.e -> USDC natif, V3 0,01 %)
 *     est OBLIGATOIRE avant de rembourser Morpho. Sans elle, le
 *     remboursement en USDC natif serait impossible. Le coût de
 *     cette jambe (~0,011 %) est inclus dans les nets ci-dessus.
 *  3. La fenêtre est un prix STALE (USDT ~0,9988 $ global, Curve
 *     à 1,0001, volume ~0). Elle meurt si l'USDT repeg à 1,0000 $
 *     ou si quelqu'un trade le pool Curve. Le contrat ne protège
 *     que par le revert atomique (minProfit + minDy) : le bot ne
 *     doit broadcaster qu'après re-simulation off-chain.
 *  4. Les jambes V3 sont en DIRECT (pool.swap + callback) : le
 *     SwapRouter02 Polygon n'expose pas exactInputSingle (vérifié
 *     2026-11-24, voir FlashLoanArbitragePolygon.sol).
 *  5. Morpho Polygon N'EST PAS 0xBBBB… : la bonne adresse est
 *     0x1bF0c2541F820E775182832f06c0B7Fc27A25f67.
 *
 * SÉCURITÉ :
 *  - `onlyOwner` + `nonReentrant` sur executeArbitrage ; callback
 *    Morpho protégé par `msg.sender == MORPHO` ; callback V3
 *    protégé par `msg.sender == poolA || msg.sender == poolB`.
 *  - `minDy` (paramètre) = sortie minimale USDC.e de la jambe Curve,
 *    calculée off-chain depuis la quote live avec une marge de
 *    slippage (ex : quote × 0,9995). Si Curve rend moins, revert.
 *  - `require(profit >= minProfit)` (0,01 $) = filet atomique.
 *  - Pas de clé privée dans ce repo.
 *
 * Adresses Polygon (vérifiées on-chain 2026-11-25, bloc 97 921 969) :
 *  Morpho Blue Polygon : 0x1bF0c2541F820E775182832f06c0B7Fc27A25f67
 *  USDC (natif)        : 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359
 *  USDC.e (bridgé)     : 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
 *  USDT                : 0xc2132D05D31c914a87C6611C10748AEb04B58e8F
 *  V3 USDC/USDC.e 0,01%: 0xD36ec33c8bed5a9F7B6630855f1533455b98a418
 *    (token0 = USDC.e, token1 = USDC, fee = 100)
 *  V3 USDC.e/USDT 0,01%: 0xDaC8A8E6DBf8c690ec6815e0fF03491B2770255D
 *    (token0 = USDC.e, token1 = USDT, fee = 100)
 *  Curve am3pool       : 0x445FE580eF8d70FF569aB36e80c647af338db351
 *    (coins : amDAI(0) / amUSDC(1) / amUSDT(2) ;
 *     underlying : DAI(0) / USDC.e(1) / USDT(2) ; fee 0,001 %, A=2000)
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

/// @notice Pool Uniswap V3 — appel DIRECT (voir en-tête).
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

/// @notice Curve StableSwap (pool "aave") — seules les fonctions
///         utilisées sont déclarées. exchange_underlying(i, j, dx, min_dy)
///         échange le token sous-jacent i contre le sous-jacent j.
///         Sélecteur 0xa6417ed6 vérifié présent dans le bytecode du
///         am3pool (bloc 97 921 969).
interface ICurveStableSwap {
    function exchange_underlying(
        int128 i,
        int128 j,
        uint256 dx,
        uint256 min_dy
    ) external returns (uint256);

    function get_dy_underlying(
        int128 i,
        int128 j,
        uint256 dx
    ) external view returns (uint256);
}

/// @notice Arbitrage 4-jambes via Morpho Blue Polygon (0 frais) :
///         USDC -> USDC.e -> USDT -> USDC.e (Curve) -> USDC.
/// @dev NON AUDITÉ, NON DÉPLOYÉ mainnet. Preuve fork uniquement.
contract CurveFlashArbPolygon is
    IMorphoFlashLoanCallback,
    Ownable,
    ReentrancyGuard
{
    using SafeERC20 for IERC20;

    IMorpho public constant MORPHO =
        IMorpho(0x1bF0c2541F820E775182832f06c0B7Fc27A25f67);

    /// @dev Bornes de prix « pas de limite » pour pool.swap
    /// (la pool exige une valeur dans [MIN_SQRT_RATIO, MAX_SQRT_RATIO]).
    uint160 internal constant MIN_SQRT_RATIO_PLUS_ONE = 4295128740;
    uint160 internal constant MAX_SQRT_RATIO_MINUS_ONE =
        1461446703485210103287273052203988822378723970341;

    /// @dev Indices des sous-jacents dans le am3pool Curve :
    ///      0 = DAI, 1 = USDC.e, 2 = USDT (vérifié on-chain).
    int128 internal constant CURVE_I_USDT = 2;
    int128 internal constant CURVE_J_USDCE = 1;

    address public immutable USDC;
    address public immutable USDCE;
    address public immutable USDT;
    IUniswapV3Pool public immutable poolA; // USDC / USDC.e, fee 100
    IUniswapV3Pool public immutable poolB; // USDC.e / USDT, fee 100
    ICurveStableSwap public immutable curvePool; // am3pool
    /// @dev Vrai si USDC.e == token0 de la pool (vendu avec zeroForOne).
    bool public immutable zeroForOneA; // poolA : USDC.e == token0
    bool public immutable zeroForOneB; // poolB : USDC.e == token0
    uint256 public minProfit; // USDC 6 décimales, ex : 0,01 $ = 10 000

    event CurveFlashArbExecuted(
        uint256 loan,
        uint256 profit,
        uint256 gasLeft
    );

    constructor(
        address _usdc,
        address _usdce,
        address _usdt,
        address _poolA,
        address _poolB,
        address _curvePool,
        uint256 _minProfit
    ) {
        USDC = _usdc;
        USDCE = _usdce;
        USDT = _usdt;
        poolA = IUniswapV3Pool(_poolA);
        poolB = IUniswapV3Pool(_poolB);
        curvePool = ICurveStableSwap(_curvePool);
        // Sécurité : les pools doivent être celles attendues.
        require(
            poolA.token0() == _usdce && poolA.token1() == _usdc,
            "poolA != USDC.e/USDC"
        );
        require(
            poolB.token0() == _usdce && poolB.token1() == _usdt,
            "poolB != USDC.e/USDT"
        );
        zeroForOneA = true; // token0 de poolA == USDC.e (vérifié ci-dessus)
        zeroForOneB = true; // token0 de poolB == USDC.e (vérifié ci-dessus)
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage Curve 4-jambes via Morpho Polygon.
    /// `amount` = taille calculée off-chain (JAMAIS une taille fixe).
    /// `minDy` = sortie minimale USDC.e de la jambe Curve, calculée
    /// off-chain depuis la quote live (quote × 0,9995 recommandé).
    /// `data` = abi.encode(amount, minDy) : le callback vérifie que le
    /// montant reçu est bien celui demandé.
    function executeArbitrage(
        uint256 amount,
        uint256 minDy
    ) external onlyOwner nonReentrant {
        require(amount > 0, "amount=0");
        MORPHO.flashLoan(USDC, amount, abi.encode(amount, minDy));
    }

    /// @notice Callback Morpho : 4 swaps + remboursement, même tx.
    /// Fee Morpho = 0 par conception : on rembourse EXACTEMENT `assets`.
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
        (uint256 expected, uint256 minDy) = abi.decode(
            data,
            (uint256, uint256)
        );
        require(expected == assets, "data != assets");

        // Jambe 0 : USDC -> USDC.e (V3 poolA, fee 100).
        // On vend USDC (token1) : zeroForOne = !zeroForOneA.
        uint256 usdceAmt = _swapV3(poolA, !zeroForOneA, assets);

        // Jambe 1 : USDC.e -> USDT (V3 poolB, fee 100).
        // On vend USDC.e (token0) : zeroForOne = zeroForOneB.
        uint256 usdtAmt = _swapV3(poolB, zeroForOneB, usdceAmt);

        // Jambe 2 : USDT -> USDC.e (Curve am3pool, exchange_underlying).
        // ATTENTION : la sortie est de l'USDC.e (underlying_coins(1)),
        // PAS de l'USDC natif — d'où la jambe 3 (voir en-tête).
        IERC20(USDT).safeApprove(address(curvePool), usdtAmt);
        uint256 usdceBack = curvePool.exchange_underlying(
            CURVE_I_USDT,
            CURVE_J_USDCE,
            usdtAmt,
            minDy
        );

        // Jambe 3 : USDC.e -> USDC natif (V3 poolA, fee 100).
        // On vend USDC.e (token0) : zeroForOne = zeroForOneA.
        uint256 usdcBack = _swapV3(poolA, zeroForOneA, usdceBack);

        // Filet de sécurité : si le profit est sous le minimum, on
        // revert — on paie le gas, mais on ne perd PAS le loan.
        // (Le bot évite ce cas par la simulation off-chain.)
        require(usdcBack >= assets, "pas de quoi rembourser le loan");
        uint256 profit = usdcBack - assets;
        require(profit >= minProfit, "profit < minProfit");

        // Rembourser Morpho : elle tire `assets` via transferFrom.
        // Fee = 0, donc exactement `assets` — jamais plus.
        IERC20(USDC).safeApprove(address(MORPHO), assets);

        emit CurveFlashArbExecuted(assets, profit, gasleft());
    }

    /// @notice Swap V3 exact-input sur une pool, en direct.
    /// @return amountOut le montant reçu (token de sortie).
    function _swapV3(
        IUniswapV3Pool pool,
        bool zeroForOne,
        uint256 amountIn
    ) internal returns (uint256 amountOut) {
        uint160 limit = zeroForOne
            ? MIN_SQRT_RATIO_PLUS_ONE
            : MAX_SQRT_RATIO_MINUS_ONE;
        (int256 amount0, int256 amount1) = pool.swap(
            address(this),
            zeroForOne,
            int256(amountIn),
            limit,
            ""
        );
        // zeroForOne (vente token0) : amount1 < 0 = token1 reçu.
        // !zeroForOne (vente token1) : amount0 < 0 = token0 reçu.
        amountOut = zeroForOne
            ? uint256(-amount1)
            : uint256(-amount0);
    }

    /// @notice Callback Uniswap V3 — appelée par poolA ou poolB pendant
    ///         `pool.swap`. Paie le delta positif (le token vendu) à la pool.
    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata /* data */
    ) external {
        require(
            msg.sender == address(poolA) || msg.sender == address(poolB),
            "callback: not pool"
        );
        if (amount0Delta > 0) {
            IERC20(IUniswapV3Pool(msg.sender).token0()).safeTransfer(
                msg.sender,
                uint256(amount0Delta)
            );
        } else if (amount1Delta > 0) {
            IERC20(IUniswapV3Pool(msg.sender).token1()).safeTransfer(
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
