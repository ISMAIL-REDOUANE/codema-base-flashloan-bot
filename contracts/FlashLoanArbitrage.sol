// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * FlashLoanArbitrage.sol — SQUELETTE v1/v2 (Base, Aave V3 flashLoanSimple)
 *
 * BUT : emprunter USDC en flash loan, acheter MEME sur DEX A (pas cher),
 * vendre MEME sur DEX B (cher), rembourser le loan + 0,05 %, garder le reste.
 *
 * ⛔⛔⛔ AVERTISSEMENT v2 — LIRE AVANT TOUT DÉPLOIEMENT ⛔⛔⛔
 *  1. CE CONTRAT COMPILE ET A ÉTÉ PROUVÉ SUR FORK (2026-11-24, §10 de
 *     FORK_TEST_RESULTS.md) : `forge build` OK (solc 0.8.20), déployé
 *     sur fork Base, cas gagnant WIN +17,24 $, cas perdant revert
 *     confirmé. Librairies installées par tarballs officiels
 *     (OZ v4.9.6 + Aave v3-core v1.19.4, voir foundry.toml).
 *     MAIS il reste NON AUDITÉ : NE PAS DÉPLOYER avec de vrais fonds
 *     sans audit (voir §10.5). La jambe Morpho (v3.3) a été prouvée
 *     sur fork comme l'Aave (FORK_TEST_RESULTS.md §11) ; le squelette
 *     Balancer compile mais n'a JAMAIS été testé on-chain — et ne le
 *     sera plus : Balancer est MORT (BIP-928, 30 oct 2026).
 *  2. AERODROME EST FAUX ICI (prouvé on-chain, FORK_TEST_RESULTS.md §7.1) :
 *     le router Aerodrome N'A PAS l'interface V2 — getAmountsOut(address[])
 *     et swapExactTokensForTokens(address[]) sont ABSENTS du bytecode.
 *     Seul existe swapExactTokensForTokens(uint,uint,Route[],address,uint)
 *     avec Route = (from, to, stable, factory). TOUTE jambe Aerodrome via
 *     ce contrat REVERTRAIT. Il faut un adaptateur Aerodrome Route-based
 *     (voir preflight.py : getAmountsOut Route-based, sélecteur 0x5509a1ac)
 *     OU se limiter aux jambes Uni V2 / Sushi V2 (vrais routers V2).
 *  3. minProfit par défaut : 3 $ (3 * 1e6 USDC) — confirmé par Ismail.
 *
 * SÉCURITÉ — lire avant tout déploiement :
 *  - Ce contrat est un SQUELETTE, NON AUDITÉ. Ne jamais déployer avec de
 *    vrais fonds sans audit + tests sur fork Base Sepolia / mainnet fork.
 *  - Les swaps ci-dessous sont des appels génériques aux routers V2
 *    (Uniswap V2 / Sushi V2 : même interface swapExactTokensForTokens).
 *    Pour Uniswap V3, il faut le SwapRouter02 (exactInputSingle) —
 *    à brancher en v2, pas en v1. Pour Aerodrome, voir §2 ci-dessus.
 *  - Le revert on-chain coûte du gas : la stratégie du bot est de NE PAS
 *    broadcaster si la simulation off-chain dit perte (voir executor.py).
 *    Le `require(profit >= minProfit)` ici n'est que le filet de sécurité
 *    si le prix a bougé entre la simulation et l'inclusion dans le bloc.
 *  - `onlyOwner` + `nonReentrant` : seul l'owner (le bot) peut lancer un
 *    arbitrage, et pas de réentrance pendant executeOperation.
 *  - Pas de clé privée dans ce repo. Le déploiement se fait depuis un
 *    coffre / Foundry avec --private-key en variable d'environnement.
 *
 * Adresses Base (vérifiées 2026-11-24, voir RESEARCH.md) :
 *  Aave PoolAddressesProvider : 0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D
 *  USDC (native)              : 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
 */

import {FlashLoanSimpleReceiverBase} from
    "@aave/core-v3/contracts/flashloan/base/FlashLoanSimpleReceiverBase.sol";
import {IPoolAddressesProvider} from
    "@aave/core-v3/contracts/interfaces/IPoolAddressesProvider.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/security/ReentrancyGuard.sol";

interface IUniswapV2Router02 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

contract FlashLoanArbitrage is
    FlashLoanSimpleReceiverBase,
    Ownable,
    ReentrancyGuard
{
    using SafeERC20 for IERC20;

    address public immutable USDC;
    address public immutable MEME; // défini à la construction par token — v1 : 1 token par déploiement
    IUniswapV2Router02 public immutable routerBuy;  // DEX A (pas cher)
    IUniswapV2Router02 public immutable routerSell; // DEX B (cher)

    uint256 public minProfit; // en USDC (6 décimales), ex: 3 * 1e6 = 3 $ (min confirmé Ismail)

    event ArbitrageExecuted(uint256 loan, uint256 profit, uint256 gasLeft);
    event ArbitrageReverted(string reason);

    constructor(
        address provider,
        address _usdc,
        address _meme,
        address _routerBuy,
        address _routerSell,
        uint256 _minProfit
    ) FlashLoanSimpleReceiverBase(IPoolAddressesProvider(provider)) {
        USDC = _usdc;
        MEME = _meme;
        routerBuy = IUniswapV2Router02(_routerBuy);
        routerSell = IUniswapV2Router02(_routerSell);
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage. `amount` = taille calculée par math_engine.py
    /// (JAMAIS une taille fixe). Appelé uniquement par l'owner (le bot).
    function executeArbitrage(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0, "amount=0");
        POOL.flashLoanSimple(
            address(this), // receiver
            USDC,          // asset emprunté
            amount,        // taille calculée off-chain
            "",            // params (vide en v1)
            0              // referralCode
        );
    }

    /// @notice Callback Aave : c'est ici que l'arbitrage a lieu, dans la
    /// même transaction que le prêt. Si on ne peut pas rembourser
    /// amount + premium, TOUTE la transaction revert (Aave l'exige).
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata /* params */
    ) external override returns (bool) {
        require(msg.sender == address(POOL), "appelant != Aave Pool");
        require(initiator == address(this), "initiateur != ce contrat");
        require(asset == USDC, "asset != USDC");

        uint256 amountOwed = amount + premium;

        // 1) USDC -> MEME sur DEX A (pas cher)
        IERC20(USDC).safeApprove(address(routerBuy), amount);
        address[] memory pathBuy = new address[](2);
        pathBuy[0] = USDC;
        pathBuy[1] = MEME;
        uint256[] memory bought = routerBuy.swapExactTokensForTokens(
            amount, 0, pathBuy, address(this), block.timestamp + 120
        );
        uint256 memeAmount = bought[1];

        // 2) MEME -> USDC sur DEX B (cher)
        IERC20(MEME).safeApprove(address(routerSell), memeAmount);
        address[] memory pathSell = new address[](2);
        pathSell[0] = MEME;
        pathSell[1] = USDC;
        uint256[] memory sold = routerSell.swapExactTokensForTokens(
            memeAmount, 0, pathSell, address(this), block.timestamp + 120
        );
        uint256 usdcBack = sold[1];

        // 3) Filet de sécurité : si le profit est sous le minimum, on
        //    revert — on paie le gas, mais on ne perd PAS le loan.
        //    (Le bot évite ce cas par la simulation off-chain.)
        require(usdcBack >= amountOwed, "pas de quoi rembourser le loan");
        uint256 profit = usdcBack - amountOwed;
        require(profit >= minProfit, "profit < minProfit");

        // 4) Rembourser Aave (le Pool tire amountOwed via transferFrom)
        IERC20(USDC).safeApprove(address(POOL), amountOwed);

        emit ArbitrageExecuted(amount, profit, gasleft());
        return true;
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

/* ==========================================================================
 * v3 — SQUELETTE Balancer V2 (0 frais) — DÉPRÉCIÉ, NE PLUS UTILISER
 * ==========================================================================
 * ⛔ BALANCER EST MORT (BIP-928, wind-down 30 oct 2026) : pools en
 *    retraits seuls, bug bounty terminé, Balancer Labs dissoute.
 *    Ce squelette est CONSERVÉ POUR RÉFÉRENCE — ne pas déployer, ne pas
 *    tester. Le remplaçant est MorphoFlashLoanArbitrage ci-dessous (v3.3).
 *
 * POURQUOI BALANCER (vérifié on-chain 2026-11-24, BALANCER_RESEARCH.md) :
 *    Vault Base : 0xBA12222222228d8Ba445958a75a0704d566BF2C8
 *    getFlashLoanFeePercentage() = 0 (lu on-chain, bloc 61 794 215).
 *    Soldes Vault Base : USDC 53 208 $ / WETH 23,27 (~39 047 $).
 *    On emprunte USDC (ou WETH), JAMAIS le meme coin (absent du Vault).
 *
 * DIFFÉRENCES AVEC AAVE (à ne pas confondre) :
 *    1. Balancer prend des TABLEAUX : flashLoan(recipient, tokens[],
 *       amounts[], userData) — même pour 1 seul token.
 *    2. Callback = receiveFlashLoan(tokens[], amounts[], feeAmounts[],
 *       userData) — feeAmounts = 0 aujourd'hui, mais le contrat DOIT
 *       rembourser amounts[i] + feeAmounts[i] (si la gouvernance monte
 *       le fee un jour, un contrat qui rembourse juste `amount` revert).
 *    3. Vérification OBLIGATOIRE : msg.sender == vault, sinon
 *       n'importe qui peut appeler receiveFlashLoan.
 *    4. Pas de flashLoanSimple : l'interface est IFlashLoanRecipient.
 *    5. Aerodrome : le router n'a PAS d'interface V2 (prouvé on-chain,
 *       FORK_TEST_RESULTS.md §7.1) — jambes Uni V2 / Sushi V2 seulement
 *       dans ce squelette, ou adaptateur Route-based à écrire.
 * ========================================================================== */

interface IBalancerVault {
    function flashLoan(
        address recipient,
        address[] memory tokens,
        uint256[] memory amounts,
        bytes memory userData
    ) external;
}

interface IFlashLoanRecipient {
    function receiveFlashLoan(
        address[] memory tokens,
        uint256[] memory amounts,
        uint256[] memory feeAmounts,
        bytes memory userData
    ) external;
}

/// @notice SQUELETTE v3 — arbitrage via Balancer Vault (0 frais).
/// @dev NON COMPILÉ, NON AUDITÉ, NON TESTÉ on-chain. Les swaps ci-dessous
///      réutilisent l'interface V2 (Uni V2 / Sushi V2 uniquement).
///      ⛔ DÉPRÉCIÉ (BIP-928) — et bug latent connu : receiveFlashLoan
///      porte `nonReentrant` alors qu'elle est appelée depuis
///      executeArbitrage (déjà sous nonReentrant) — ça reverterait
///      "ReentrancyGuard: reentrant call" (même piège trouvé et corrigé
///      sur la jambe Morpho en fork, §11). Ne pas réparer : Balancer mort.
contract BalancerFlashLoanArbitrage is IFlashLoanRecipient, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IBalancerVault public constant VAULT =
        IBalancerVault(0xBA12222222228d8Ba445958a75a0704d566BF2C8);

    address public immutable USDC;
    address public immutable MEME;
    IUniswapV2Router02 public immutable routerBuy;
    IUniswapV2Router02 public immutable routerSell;
    uint256 public minProfit; // USDC 6 décimales, ex : 3 * 1e6 = 3 $

    event BalancerArbitrageExecuted(uint256 loan, uint256 profit, uint256 gasLeft);

    constructor(
        address _usdc,
        address _meme,
        address _routerBuy,
        address _routerSell,
        uint256 _minProfit
    ) {
        USDC = _usdc;
        MEME = _meme;
        routerBuy = IUniswapV2Router02(_routerBuy);
        routerSell = IUniswapV2Router02(_routerSell);
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage Balancer. `amount` = taille calculée
    /// off-chain par math_engine.py (provider balancer, fee 0 %).
    function executeArbitrage(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0, "amount=0");
        address[] memory tokens = new address[](1);
        tokens[0] = USDC;
        uint256[] memory amounts = new uint256[](1);
        amounts[0] = amount;
        VAULT.flashLoan(address(this), tokens, amounts, "");
    }

    /// @notice Callback Balancer : swaps + remboursement dans la même tx.
    /// feeAmounts = 0 aujourd'hui — on rembourse amount + fee quand même.
    function receiveFlashLoan(
        address[] memory tokens,
        uint256[] memory amounts,
        uint256[] memory feeAmounts,
        bytes memory /* userData */
    ) external override nonReentrant {
        require(msg.sender == address(VAULT), "appelant != Vault Balancer");
        require(tokens.length == 1 && tokens[0] == USDC, "token != USDC");
        uint256 amount = amounts[0];
        uint256 amountOwed = amount + feeAmounts[0]; // fee = 0 aujourd'hui

        IERC20(USDC).safeApprove(address(routerBuy), amount);
        address[] memory pathBuy = new address[](2);
        pathBuy[0] = USDC;
        pathBuy[1] = MEME;
        uint256[] memory bought = routerBuy.swapExactTokensForTokens(
            amount, 0, pathBuy, address(this), block.timestamp + 120
        );

        IERC20(MEME).safeApprove(address(routerSell), bought[1]);
        address[] memory pathSell = new address[](2);
        pathSell[0] = MEME;
        pathSell[1] = USDC;
        uint256[] memory sold = routerSell.swapExactTokensForTokens(
            bought[1], 0, pathSell, address(this), block.timestamp + 120
        );
        uint256 usdcBack = sold[1];

        require(usdcBack >= amountOwed, "pas de quoi rembourser le loan");
        uint256 profit = usdcBack - amountOwed;
        require(profit >= minProfit, "profit < minProfit");

        // Rembourser le Vault (il vérifie son solde après le callback).
        IERC20(USDC).safeApprove(address(VAULT), amountOwed);

        emit BalancerArbitrageExecuted(amount, profit, gasleft());
    }

    function withdrawProfit() external onlyOwner {
        uint256 bal = IERC20(USDC).balanceOf(address(this));
        require(bal > 0, "rien a retirer");
        IERC20(USDC).safeTransfer(owner(), bal);
    }

    function setMinProfit(uint256 _minProfit) external onlyOwner {
        minProfit = _minProfit;
    }
}

interface IMorpho {
    function flashLoan(address token, uint256 assets, bytes calldata data) external;
}

interface IMorphoFlashLoanCallback {
    function onMorphoFlashLoan(uint256 assets, bytes calldata data) external;
}

/// @notice Arbitrage via Morpho Blue (0 frais) — jambe principale v3.3.
/// @dev NON AUDITÉ, NON DÉPLOYÉ mainnet. Jambes Uni V2 / BaseSwap V2
///      uniquement (Aerodrome : pas d'interface V2 — voir §7.1).
contract MorphoFlashLoanArbitrage is IMorphoFlashLoanCallback, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IMorpho public constant MORPHO =
        IMorpho(0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb);

    address public immutable USDC;
    address public immutable MEME;
    IUniswapV2Router02 public immutable routerBuy;  // DEX A (pas cher)
    IUniswapV2Router02 public immutable routerSell; // DEX B (cher)
    uint256 public minProfit; // USDC 6 décimales, ex : 3 * 1e6 = 3 $

    event MorphoArbitrageExecuted(uint256 loan, uint256 profit, uint256 gasLeft);

    constructor(
        address _usdc,
        address _meme,
        address _routerBuy,
        address _routerSell,
        uint256 _minProfit
    ) {
        USDC = _usdc;
        MEME = _meme;
        routerBuy = IUniswapV2Router02(_routerBuy);
        routerSell = IUniswapV2Router02(_routerSell);
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage Morpho. `amount` = taille calculée
    /// off-chain par math_engine.py (provider morpho, fee 0 %).
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
    /// executeArbitrage (déjà sous nonReentrant) via Morpho — un 2e
    /// garde reverterait ("ReentrancyGuard: reentrant call", vu en
    /// fork). La protection est `msg.sender == MORPHO` ci-dessous.
    function onMorphoFlashLoan(
        uint256 assets,
        bytes calldata data
    ) external override {
        require(msg.sender == address(MORPHO), "appelant != Morpho");
        require(assets > 0, "assets=0");
        // Le montant encodé au départ doit être celui reçu.
        uint256 expected = abi.decode(data, (uint256));
        require(expected == assets, "data != assets");

        // 1) USDC -> MEME sur DEX A (pas cher)
        IERC20(USDC).safeApprove(address(routerBuy), assets);
        address[] memory pathBuy = new address[](2);
        pathBuy[0] = USDC;
        pathBuy[1] = MEME;
        uint256[] memory bought = routerBuy.swapExactTokensForTokens(
            assets, 0, pathBuy, address(this), block.timestamp + 120
        );

        // 2) MEME -> USDC sur DEX B (cher)
        IERC20(MEME).safeApprove(address(routerSell), bought[1]);
        address[] memory pathSell = new address[](2);
        pathSell[0] = MEME;
        pathSell[1] = USDC;
        uint256[] memory sold = routerSell.swapExactTokensForTokens(
            bought[1], 0, pathSell, address(this), block.timestamp + 120
        );
        uint256 usdcBack = sold[1];

        // 3) Filet de sécurité : si le profit est sous le minimum, on
        //    revert — on paie le gas, mais on ne perd PAS le loan.
        //    (Le bot évite ce cas par la simulation off-chain.)
        require(usdcBack >= assets, "pas de quoi rembourser le loan");
        uint256 profit = usdcBack - assets;
        require(profit >= minProfit, "profit < minProfit");

        // 4) Rembourser Morpho : elle tire `assets` via transferFrom.
        //    Fee = 0, donc exactement `assets` — jamais plus.
        IERC20(USDC).safeApprove(address(MORPHO), assets);

        emit MorphoArbitrageExecuted(assets, profit, gasleft());
    }

    function withdrawProfit() external onlyOwner {
        uint256 bal = IERC20(USDC).balanceOf(address(this));
        require(bal > 0, "rien a retirer");
        IERC20(USDC).safeTransfer(owner(), bal);
    }

    function setMinProfit(uint256 _minProfit) external onlyOwner {
        minProfit = _minProfit;
    }
}

/// @notice Interface minimale Uniswap V3 SwapRouter02 (audit #7).
/// @dev Définie ici car v3-core n'est PAS dans lib/ (seuls v2-core,
///      v2-periphery, uniswap-lib, aave-v3-core, OZ).
///      ⚠️ PIÈGE VÉRIFIÉ SUR BASE (2026-11-25) : le SwapRouter02 de Base
///      (0x2626664c2603336E57B271c5C0b26F421741e481, ABI vérifiée sur
///      Basescan + tx live 0x99bbc7…) utilise le struct IV3SwapRouter à
///      7 CHAMPS, SANS `deadline` — sélecteur 0x04e45aaf. Le struct à
///      8 champs (avec deadline, sélecteur 0x414bf389) est celui du
///      SwapRouter02 canonique (Ethereum) : il REVERT sans raison sur
///      Base (prouvé en fork : swap direct USDC->WETH sur le vrai pool
///      fee 500 revert avec le struct 8 champs, OK avec 7 champs).
///      Ne JAMAIS remettre `deadline` dans ce struct sur Base.
interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(ExactInputSingleParams calldata params)
        external
        payable
        returns (uint256 amountOut);
}

/// @notice Arbitrage via Morpho Blue (0 frais) sur jambes Uniswap V3
///         (audit #7 — adaptateur CL).
/// @dev NON AUDITÉ, NON DÉPLOYÉ mainnet. Le token de loan est un
///      paramètre (USDC, WETH, cbBTC...) — l'exécuteur doit vérifier que
///      Morpho détient assez de ce token (cap 50 %, morpho_flash.py).
///      Les frais des deux jambes sont des paramètres (feeBuy/feeSell)
///      car chaque pool V3 a son propre tier. Les routes V2 restent
///      servies par MorphoFlashLoanArbitrage ci-dessus ; ce contrat ne
///      prétend exécuter QUE des jambes V3 (exactInputSingle).
contract MorphoFlashLoanArbitrageV3 is IMorphoFlashLoanCallback, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IMorpho public constant MORPHO =
        IMorpho(0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb);

    address public immutable loanToken; // ex. USDC
    address public immutable tokenOther; // ex. WETH
    ISwapRouter public immutable router; // SwapRouter02 Base
    uint24 public immutable feeBuy; // tier de la jambe achat
    uint24 public immutable feeSell; // tier de la jambe vente
    uint256 public minProfit; // en unités de loanToken

    event MorphoV3ArbitrageExecuted(uint256 loan, uint256 profit, uint256 gasLeft);

    constructor(
        address _loanToken,
        address _tokenOther,
        address _router,
        uint24 _feeBuy,
        uint24 _feeSell,
        uint256 _minProfit
    ) {
        loanToken = _loanToken;
        tokenOther = _tokenOther;
        router = ISwapRouter(_router);
        feeBuy = _feeBuy;
        feeSell = _feeSell;
        minProfit = _minProfit;
    }

    /// @notice Lance un arbitrage Morpho sur jambes V3. `amount` =
    ///         taille calculée off-chain (math_engine, provider morpho).
    function executeArbitrage(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0, "amount=0");
        MORPHO.flashLoan(loanToken, amount, abi.encode(amount));
    }

    /// @notice Callback Morpho : 2 exactInputSingle + remboursement.
    /// @dev PAS de `nonReentrant` ici : le callback est appelé DEPUIS
    ///      executeArbitrage (déjà sous nonReentrant) via Morpho — un 2e
    ///      garde reverterait. La protection est `msg.sender == MORPHO`.
    function onMorphoFlashLoan(
        uint256 assets,
        bytes calldata data
    ) external override {
        require(msg.sender == address(MORPHO), "appelant != Morpho");
        require(assets > 0, "assets=0");
        uint256 expected = abi.decode(data, (uint256));
        require(expected == assets, "data != assets");

        // 1) loanToken -> tokenOther sur la jambe achat (pas chère).
        IERC20(loanToken).safeApprove(address(router), assets);
        uint256 bought = router.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn: loanToken,
                tokenOut: tokenOther,
                fee: feeBuy,
                recipient: address(this),
                amountIn: assets,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            })
        );

        // 2) tokenOther -> loanToken sur la jambe vente (chère).
        IERC20(tokenOther).safeApprove(address(router), bought);
        uint256 sold = router.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn: tokenOther,
                tokenOut: loanToken,
                fee: feeSell,
                recipient: address(this),
                amountIn: bought,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            })
        );

        // 3) Filet de sécurité : remboursement + profit minimum.
        require(sold >= assets, "pas de quoi rembourser le loan");
        uint256 profit = sold - assets;
        require(profit >= minProfit, "profit < minProfit");

        // 4) Rembourser Morpho : elle tire `assets` via transferFrom.
        IERC20(loanToken).safeApprove(address(MORPHO), assets);

        emit MorphoV3ArbitrageExecuted(assets, profit, gasleft());
    }

    function withdrawProfit() external onlyOwner {
        uint256 bal = IERC20(loanToken).balanceOf(address(this));
        require(bal > 0, "rien a retirer");
        IERC20(loanToken).safeTransfer(owner(), bal);
    }

    function setMinProfit(uint256 _minProfit) external onlyOwner {
        minProfit = _minProfit;
    }
}

/* ==========================================================================
 * v3.3 — MORPHO BLUE (0 frais par conception) — JAMBE PRINCIPALE
 * ==========================================================================
 * POURQUOI MORPHO (vérifié 2026-11-24, voir RESEARCH.md § Morpho Blue) :
 *    Morpho Blue Base : 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb
 *    (singleton canonique, code 15 623 octets, bloc 61 806 974).
 *    Soldes Morpho Base : USDC 328 711 525,75 $ / WETH 88 713,53
 *    (~148,9 M$) — maxFlashLoan = le solde entier du contrat.
 *    TVL Morpho Blue sur Base : 3,336 Md$ (DefiLlama, 24 nov 2026).
 *
 * SIGNATURES VÉRIFIÉES contre le repo officiel morpho-org/morpho-blue
 * (src/Morpho.sol + src/interfaces/IMorphoCallbacks.sol) et la doc
 * officielle https://docs.morpho.org/developers/contracts/blue/ :
 *    function flashLoan(address token, uint256 assets, bytes calldata data) external;
 *    function onMorphoFlashLoan(uint256 assets, bytes calldata data) external;
 * Sélecteurs vérifiés par keccak : flashLoan = 0xe0232b42,
 * onMorphoFlashLoan = 0x31f57072.
 * Doc officielle : "flashFee is zero", "maxFlashLoan is the token's
 * balance of this contract", "the receiver of assets is the caller".
 * Il n'existe PAS de fonction flashFee sur Morpho : l'eth_call du
 * sélecteur ERC-3156 0xd9d98ce4 REVERT (bloc 61 806 974). Le fee 0 est
 * structurel — aucune gouvernance ne peut le monter (contrairement
 * à Balancer, mort de toute façon — BIP-928).
 *
 * DIFFÉRENCES AVEC AAVE / BALANCER (à ne pas confondre) :
 *    1. Un seul token par appel : flashLoan(token, assets, data).
 *    2. Le RECEIVER est l'appelant (msg.sender) — pas de paramètre
 *       recipient. Le contrat qui appelle reçoit les fonds.
 *    3. Callback = onMorphoFlashLoan(assets, data) — 2 paramètres
 *       seulement (pas de token, pas de fee, pas d'initiator).
 *    4. Remboursement par APPROVE : Morpho tire `assets` via
 *       transferFrom(msg.sender, address(this), assets) APRÈS le
 *       callback. Le callback DOIT donc faire
 *       approve(Morpho, assets) — fee 0, on rembourse EXACTEMENT
 *       `assets`, jamais plus.
 *    5. `data` est NON VIDE (abi.encode(amount)) : le callback
 *       décode le montant attendu et exige decoded == assets.
 *    6. Vérification OBLIGATOIRE : msg.sender == morpho, sinon
 *       n'importe qui peut appeler onMorphoFlashLoan.
 *    7. Aerodrome : le router n'a PAS d'interface V2 (prouvé on-chain,
 *       FORK_TEST_RESULTS.md §7.1) — jambes Uni V2 / BaseSwap V2
 *       seulement dans ce contrat, comme pour Aave et Balancer.
 *
 * TESTÉ SUR FORK (FORK_TEST_RESULTS.md §11, 2026-11-24) : cas gagnant
 * WIN + net >= 3 $, cas perdant SKIP 0 $ + revert confirmé.
 * NON AUDITÉ — ne pas déployer avec de vrais fonds sans audit.
 * ========================================================================== */
