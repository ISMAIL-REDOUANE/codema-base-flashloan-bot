# GitHub Expert Repos — What the Pros Actually Do (and What We Copy)

**Date:** 2026-11-25
**Task:** Ismail's order — "look at the repos of expert people on GitHub, how they work, and learn from them too."
**Method:** 9 repos cloned to `/tmp` (never run, built, imported, or copied — read as text only), core files read directly. Every claim below comes from code actually read, with file paths cited. No repo is described from its README alone.
**Scope:** our bot = Python flash-loan arb (Base + Polygon), Morpho 0% flash, Uniswap V3 quoting only, ~3 s cycle, public RPC, $1.31 float, 0 live opportunities in 61,065+ quotes. Entry rule: net > $0 after ALL costs, per-pool threshold.

## Headline verdict (read this first)

**The closest comparable repo independently reproduces our zero.** `starky2000/base-flash-arb-lab` — Python, Base, same method (flash borrow, buy on one DEX, sell on another, same-block quotes) — found **0 profitable cycles in 8 rounds across 13 tokens**, best case −3.3 bp, "the loss was approximately the sum of the two pool fees." Our 0 is not a bug in our code. It is the market.

The experts' edge over us is **not a secret threshold**. It is three things:
1. **Coverage** — they quote every venue (Aerodrome Slipstream = 78.9% of Base top-20 volume, PancakeSwap V3, V4, Curve, Balancer). We quote one venue (Uni V3 = 6.6%).
2. **Trigger** — they react to a swap event / pending transaction, then simulate. We poll blocks every ~3 s.
3. **Speed** — Rust core, in-process simulation, ms-level. We are Python at 356 ms quote latency.

None of those three guarantees profit. They only guarantee we *see* the opportunity if it exists. The honest sequence is: fix coverage (Aerodrome + cross-venue, $0) → measure 7 days → if still 0, the market is efficient at our scale and the pivot is bug bounties (already our #1 $0 path since the Curve route died 2026-11-25).

---

## 1. Repo table

| # | Repo | Stars* | Last commit | Chain(s) | Language | Verdict for us |
|---|------|--------|-------------|----------|----------|----------------|
| 1 | [BowTiedDevil/degenbot](https://github.com/BowTiedDevil/degenbot) | ~576 | 2026-11-23 | EVM (Base incl.) | Rust core + thin Python shell | **The reference architecture.** Copy its patterns, not its codebase. |
| 2 | [starky2000/base-flash-arb-lab](https://github.com/starky2000/base-flash-arb-lab) | 3 | 2026-10-28 | Base | Python | **Closest to us. Copy the most from this one.** Independently confirms our 0. |
| 3 | [akari-sora/aave-oracle-lag-arb](https://github.com/akari-sora/aave-oracle-lag-arb) | 40 | 2026-11-06 | mainnet / Arbitrum / Base / Optimism | TypeScript (viem) + Solidity | Different strategy (leveraged, needs collateral — NOT $0). Copy its engineering, not the strategy. |
| 4 | [sail-money/Sailor](https://github.com/sail-money/Sailor) | n/r | 2026-09-11 | Base (multi-venue) | TypeScript (viem) | **Best Aerodrome integration notes in the open.** Copy the venue cookbook. |
| 5 | [FastLane-Labs/atlas](https://github.com/FastLane-Labs/atlas) | 166 | 2025-10-17 | Polygon (+EVM) | Solidity | Solver-auction framework. Not a bot. Entry is $0 but unwinnable at our latency (~250 ms windows). |
| 6 | [Dimanoshe/flashblocks-rs](https://github.com/Dimanoshe/flashblocks-rs) | 1 | 2026-11-12 | Base | Rust (+Python module) | **Flashblocks are DEAD (retired 2026-11-05, Denim).** Copy its replacement: newHeads + logsBloom prefilter. |
| 7 | [nenadcodecrypto-hub/v2-arbitrage-bot-base](https://github.com/nenadcodecrypto-hub/v2-arbitrage-bot-base) | n/r | 2026-01-22 | Base | TypeScript + Solidity | Useful Aerodrome contract pattern. Scanner is broken (does not compile). No flash loan (own funds). |
| 8 | [rdin777/atomic-arbitrage-executor](https://github.com/rdin777/atomic-arbitrage-executor) | 1 | 2026-10-13 | Base | TypeScript | **Does not compile.** `executeArbitrage()` is called but never defined. Do not copy. |
| 9 | [rdin777/base-arbitrage-project](https://github.com/rdin777/base-arbitrage-project) | 0 | 2026-10-10 | Base | TypeScript + Solidity | **The detector is a MOCK** (hardcoded 0.57% opportunity). Do not copy. |
| R | [aerodrome-finance/slipstream](https://github.com/aerodrome-finance/slipstream) | n/r | 2026-04-10 | Base | Solidity | The venue's own contracts. Reference only — addresses in §3/L2 must be verified on-chain before use. |

\* Stars as observed at study time. "n/r" = not recorded in this study.

---

## 2. Per-repo findings (from code read, not README)

### 2.1 BowTiedDevil/degenbot — the professional reference

**What it is:** a production-grade MEV/arbitrage engine. Rust core with a thin Python shell. Covers Uniswap V2/V3/V4, Curve, Balancer, Aerodrome (V2 state + Solidly family), PancakeSwap V3, Aave V3.

**How it FINDS gaps — graph search + backrun trigger, not polling.**
- `rust/crates/foundation/degenbot-pathfinding/src/` — `graph.rs`, `graph/expansion.rs`, `plan.rs`: it builds a **graph of pools** and expands candidate paths (anchored DFS — `rust/crates/engine/degenbot-strategy/src/anchored_dfs.rs`). It does not check one pair at a time; it searches the whole graph for a profitable cycle.
- `rust/crates/engine/degenbot-strategy/src/backrun.rs` — the **backrun arm**: `MEVBlocker` feed → hub classification → exact-sim oracle gate → budgeted bid. It reacts to a *target transaction* (a user's swap), not to a block timer. The decision layer is a pure function (`decide`), testable without a network.
- `rust/crates/foundation/degenbot-pools/src/` — one module per pool family: `families/concentrated_liquidity/`, `families/solidly.rs` (Aerodrome's model), `families/curve_stableswap.rs`, `state/aerodrome_v2_state.rs`, `state/v3_pancakeswap_storage_slots.rs`, `state/v4_state.rs`, `sim/` (in-process swap simulation), `solve/` (optimal-input solvers: `bounded_brent.rs`, `mobius_*`, `profit_envelope/`, `gas_floor.rs`, `gate.rs`).

**How it DECIDES — simulation is the gate, budgets are hard caps.**
- `backrun.rs` safety model (quoted from the file header): "observe-only default: no bid unless `bid_mode` is set AND the budget is non-zero; no bid without a passing sim (the oracle gate is upstream of `decide`); hard per-bundle + cumulative budget caps; STOP kill-switch file: existence halts all bidding, then the loop; a target whose tx already mined never dispatches."
- `rust/crates/engine/degenbot-arbitrage/src/pool_divergence.rs` — **per-pool divergence memo**: a pool whose state the solver read wrong is flagged `SolverCalc` across every path through it; the dispatch leaf skips paths through recently-divergent pools after the FIRST failure instead of letting every path fail independently and burn its own retry count. Decay window `POOL_DIVERGENCE_DECAY_BLOCKS = 100` blocks; per-path suppression after 10 consecutive failures (`PATH_SUPPRESS_THRESHOLD`). Identity key is the pool's chain identity (V2/V3 address, V4 `poolId` bytes32 — NOT the shared PoolManager address).
- Execution adapter seam (`ExecutionAdapter`: Encode + Probe + Assess + Fee): one opportunity = one transaction; a revert = zero gross (the sim must pass or nothing is sent).

**How it EXECUTES — three submission slots** (`backrun.rs`, `SubmissionSlot` enum):
- `Mevblocker` — signed backrun bid through `eth_sendBundle` on the searcher WebSocket; raw-broadcast fan-out leads with the private endpoint.
- `PublicFanOut` — no auction, signed backrun across public relays.
- `BuilderRelay` — the TARGET's verbatim signed bytes + the signed backrun leave as ONE `eth_sendBundle` POST to every relay; deliberately NO public raw fan-out (a stray broadcast would leak the backrun outside the bundle).

**How it is BUILT FOR SPEED:** Rust core, in-process `evm2` simulation (no RPC round-trip per sim), pool state kept in memory and updated from events, multicall batching. The Python shell is only orchestration.

**Verdict for us:** copy the *patterns* (graph search, backrun trigger, sim-as-gate, hard budget caps, STOP file, per-pool divergence memo, one-opportunity-one-tx). Do NOT copy the codebase — it is a large Rust workspace, and a rewrite costs weeks for a gain the root-cause audit says is ~10% with current signal. **MEVBlocker/Flashbots bundles are Ethereum-only and do not apply on Base** (private sequencer, no public mempool) — the bundle *mechanism* doesn't transfer; the *react-to-a-transaction* pattern does.

### 2.2 starky2000/base-flash-arb-lab — the closest repo to ours (copy the most)

**What it is:** Python, Base, flash-loan cross-DEX arbitrage lab. The most comparable repo in this study — same language, same chain, same method, same question. Its honesty matches ours: it reports the zero instead of hiding it.

**How it FINDS gaps — one adapter per venue, pinned-block quotes, staleness gate.**
- `case-studies/03-base-cross-dex.md` (method section): venues = Uniswap V3 and PancakeSwap V3 (+ Uniswap V4 once the adapter existed), "discovered through their factories across every fee tier." Quotes are "exact, from each venue's own quoter at a pinned block."
- **Critical method detail we do NOT do yet:** "The sell leg is re-quoted against the *quantity the buy leg returned*, not against the same dollar size, because that is what a real cycle does." (We quote both legs at the same dollar size — that overstates the sell leg.)
- **Depth-artifact filters:** "a pool is dropped when its own round trip loses more than 3%, and any quote more than 5% away from the median is reported as excluded rather than ranked. Both filters exist because a nearly-empty pool quotes an absurd price." (This is exactly the artifact class our cross-venue scan must classify.)
- Sample: 8 rounds across 13 tokens, at $100 and $500 notional.

**How it DECIDES — conservative costs, fail-closed preflight.**
- Costs: two pool fees (inside the quote) + gas from live base fee + OP-stack L1 data component. Flash-loan premium: "Balancer V2 charges 0 on Base" — **STALE, do not copy: Balancer is dead (BIP-928, wound down 30 Oct 2026).**
- Gas observed ~0.006 gwei; 450,000 gas = **$0.0057**. (Matches our measured ~$0.005 on Base.)
- Adapter design (from the repo's adapter code): batched quoter prefetch, min profit **$2**, 30 bps slippage applied twice, conservative gas model (850k units × 1.5 + L1 buffer), **fail-closed preflight**: max quote age 2 blocks, gas cap 0.5 gwei, deadline +55 s, operator balance check, **$2/day + $20 total gas-loss reservations** (a hard budget for how much gas may ever be burned on failures).

**Its numbers — the independent confirmation of our zero** (`case-studies/03-base-cross-dex.md`):
- Quotes for 5,000 USDC → WETH, one block: Pancake V3 0.01% best; Uni V3 0.05% −4.4 bp; Uni V3 0.01% −7.5 bp; Pancake V3 0.05% −10.0 bp; Uni V3 0.3% −39.3 bp; Uni V4 0.3% −79.6 bp; Uni V3 1% −175.2 bp.
- "The best cycle — buy the cheapest pool, sell into the dearest — loses **15.0 bp** after gas, and three pools were excluded as depth artifacts before ranking."
- Across the sample: $100 → 3 rounds, 13 tokens, **0 profitable**; $500 → 5 rounds, 11 tokens, **0 profitable**. Best case per round was −3.3 bp at $100 and −3.8 bp at $500, both on WETH, "and in both cases the loss was approximately **the sum of the two pool fees**."
- Conclusion (quoted): "On Base, at retail sizes, cross-DEX price differences on liquid pairs have been arbitraged below the fee it costs to cross both pools. The market is not inefficient; it is efficient to a fraction of a basis point, and the fee schedule is the floor."
- What it does not prove (quoted): "Long-tail tokens and brand-new pools are not covered here. Dislocations are larger there, and so is the probability that the pool is empty and the quote is meaningless." Priority fees, builder tips and failed-transaction costs are not modelled — "All three make the real number worse, not better."

**Verdict for us:** the single highest-value repo. Copy: per-venue adapters + factory discovery across all fee tiers; sell-leg re-quote against buy-leg output; the two depth-artifact filters (round-trip >3% drop, >5% from median exclude); the fail-closed preflight checklist; the gas-loss reservation budget. Do NOT copy: the Balancer 0-fee claim (dead), the $2 min profit (ours is net > $0 — keep ours, it is stricter in the right direction).

### 2.3 akari-sora/aave-oracle-lag-arb — different strategy, excellent engineering

**What it is:** borrows WETH from Aave at the Chainlink oracle price, sells it on a DEX where it trades above the oracle, buys back after convergence. Chains: mainnet / Arbitrum / Base / Optimism. TypeScript (viem) + Solidity (`OracleLagArb.sol`).

**How it DECIDES — the config is the lesson** (`bot/core.ts`, `CFG`):
- `openPremiumBps: 300` (3% premium to open), `minEdgeBps: 50` (0.5% minimum edge), `targetHf: 1.3` (health factor), `minWethPerTx: 0.5`, `maxWethPerTx` (0 = unlimited).
- **`confirmSeconds: 15`** — "the premium must stay above the threshold for 15 consecutive seconds before opening, filtering out single-large-order spikes that get arbed flat in the next block." (Our paper-trade saw exactly this failure mode: atomic 1-trade jumps. A persistence filter is the fix.)
- `closePremiumBps: 30`, `emergencyHf: 1.1`, `emergencyTargetHf: 1.3`, `emergencyMaxPremiumBps: 1000`, `exitMaxPremiumBps: 300`.
- `gasLimitMult: 1.25` ("between estimation and on-chain the price moves, a flash swap may cross more ticks"), `maxFeeBaseMult: 2` (maxFeePerGas = base fee × 2 + tip).
- `pollMs: 3000`, `minTickMs: 500` (minimum gap between decisions when blocks come fast — Arbitrum does 4 blocks/second).
- `aggregator: "kyber"` (default) — "before opening, ask the aggregator (can sell to Uniswap V3/V4, Aerodrome, Curve, market makers); only use a single pool if the aggregator isn't better." `aggSlippageBps: 100`.
- `minPoolWeth: 5` — "if a pool holds less than 5 WETH, treat it as a dead pool: don't open there, and don't keep holding because it shows a premium."
- `actionFailAlert: 5` — alert after 5 consecutive failed actions (sim or send).
- `checkConfig()`: TARGET_HF must be ≥ 1.05 (USDC LTV 0.75 / liquidation threshold 0.78 → 1.04) — the config validates itself against protocol constants before starting.
- Addresses "verified on-chain 2026-10-30 from Aave PoolAddressesProvider → getPool / getReserveData, Uniswap V3 factory → getPool."

**How it EXECUTES — the contract guard worth copying** (`OracleLagArb.sol`):
- `open()`: sells WETH on Uni V3 with **`sqrtPriceLimitX96` set at oracle price × (1 + minEdge)** — the pool price is pushed to that line and stops automatically, so every WETH sold is at least minEdge above the oracle. (Our contracts pass `sqrtPriceLimitX96 = 0` — no price limit. A limit is a strictly stronger guarantee than `amountOutMinimum` alone.)
- Uses Uniswap V3 **flash swap** (not flash loan) to compress steps.
- `transient` storage for `_activePool` (callback only accepts the active pool) and `_flashMode` (prevents others using the contract as a flash-loan receiver). Router whitelist, owner-only.
- Sizing via `maxWethForHealthFactor` (health-factor target).

**Verdict for us:** **do NOT copy the strategy.** It is a leveraged short-ETH position, not risk-free arbitrage: it needs collateral deposited in Aave, carries health-factor / liquidation risk, and the edge is oracle lag (Chainlink updates slower than the DEX). It is NOT $0 and NOT risk-free. **Copy the engineering:** `confirmSeconds` persistence filter; aggregator-first routing (Kyber); `minPoolWeth` dead-pool gate; `actionFailAlert` after 5 consecutive failures; `gasLimitMult` 1.25 / `maxFeeBaseMult` 2; `sqrtPriceLimitX96` as an execution guard; transient callback guards; self-validating config.

### 2.4 sail-money/Sailor — the Aerodrome integration bible

**What it is:** a multi-venue agent framework (DCA basket across Uniswap V3, an Aerodrome Slipstream fork, and Uniswap V4). The value for us is one file: `scaffold/.agents/skills/sailor-mandates/references/venue-cookbook.md` — nine field-derived patterns from a real build, "all solved, funds never at risk because the fail-closed gates held."

**Aerodrome — verify the pool→factory→router chain on-chain, never from docs** (cookbook entry 1):
- "Forks ship generations — Aerodrome alone has run three Slipstream generations, each with its own factory+router pair — and docs, memory, or a prior session's notes can point at the wrong generation's router for the pool you're actually trading."
- The move: require `SwapRouter.factory() == pool.factory()` (a plain view-call check, cheap to make part of `configure()`) before wiring a router to a pool.
- Concrete Base map (verified on-chain, 2026-09): three CL generations — (1) legacy factory `0x5e7BB1…` → router `0xBE6D…`, (2) `legacyCLFactory2` → raw tickSpacing, (3) the newest "Gauges V3" factory `0xf8f2eB…` → single-factory SwapRouter `0x698Cb2…`. "Current Base CL liquidity (cbHYPE, etc.) sits on `0xf8f2eB…`, so that's the pair to use."
- **The quoter is a different contract from the router:** newest generation is served by **MixedQuoterV3 `0xCd2A7D…`**, which tags the path's `int24` hop with the factory bit (`0x80000 | tickSpacing` = newest) so its shared `quoteExactInput` / `quoteExactInputSingleV3` can disambiguate factories — "whereas the single-factory router uses the **raw** tickSpacing. Getting these crossed (tagged vs raw, or router vs quoter generation) is the exact failure this entry warns about."
- ⚠️ Addresses above are truncated as written in the source. **Verify the full addresses on BaseScan + the on-chain `factory()` check before any use.** (Our root-cause audit already verified Aerodrome addresses on-chain at block 62,071,176: 3 CLFactories + MixedQuoterV3 + SwapRouter + FactoryRegistry — use those, not these truncated notes.)

**Other cookbook entries directly applicable to us:**
- **Entry 2 — match the deployed ABI exactly:** "Uniswap V3's `slot0()` returns 7 fields; Slipstream's returns 6. Decoding a 6-word return against a 7-field interface overruns the returned bytes and reverts — and a revert thrown while *decoding* the return data of an otherwise successful external call, inside a `try`'s success arm, is **not** caught by that `try`'s `catch`." A unit test mocked against the wrong interface passes anyway. The move: pull the venue's real ABI from the verified deployed contract, and gate on a simulation against the *real* pool.
- **Entry 3 — recover a V4 PoolKey without logs:** read the V4 `PositionManager`'s `poolKeys(bytes25)` mapping (a plain storage read on the top 25 bytes of the `poolId`) — no event log needed. (Relevant when we add V4 support; free-tier RPCs cap `eth_getLogs` to narrow windows.)
- **Entry 4 — re-verify pool liquidity immediately before build/execution, not just at plan time:** "pools drain. A pool that had real depth when the mandate was planned had its liquidity go to zero by the time the permission went live." Probe `getLiquidity()` (V3-family) / reserves (V2-family) immediately before committing.
- **Entry 6 — never let a per-leg `try`/`catch` swallow a leg:** in the field this "silently dropped **all three** V4 legs of a five-leg basket — the loop kept going, logged nothing distinguishing, and the run *looked* clean." A failed leg is an outcome, not noise: record it in the ledger (`acted` / `skipped` with `reason`) and report attempted-vs-executed counts in every tick summary.
- **Entry 7 — V4 Universal Router action order:** read it off a **live, successfully-mined transaction** against the same deployed router — "the deployed contract's accepted shape is the spec, full stop." (Their router required settle-first: `SETTLE(payerIsUser=true)` → `SWAP` → `TAKE`, not the canonical `SWAP` → `SETTLE_ALL` → `TAKE_ALL`.)
- **Entry 8 — multi-hop struct drift:** route as chained single-hops (`SETTLE` → `SWAP(A→B)` → `SWAP(B→C, amountIn = OPEN_DELTA)` → `TAKE(C)`) instead of a multi-hop struct — reuses the single-hop struct already verified.
- **Entry 9 — nonces come from chain state, not a local counter:** "a **mined-but-reverted** transaction still consumes the sender's nonce on-chain; a tracker that doesn't know this drifts one behind after the very first revert, and every following send reuses an already-spent value." Re-derive the nonce from chain (`getTransactionCount(address, 'pending')`) immediately before every send, and await each receipt before sending the next.

**Verdict for us:** the single best source for the Aerodrome fix (#1). Copy entries 1, 2, 4, 6, 9 immediately; entries 3, 7, 8 when we touch V4.

### 2.5 FastLane-Labs/atlas — the solver-auction framework (not a bot)

**What it is:** a permissionless, modular smart-contract framework for Execution Abstraction. Apps publish user intents (UserOperations); solvers compete in an auction to fill them; a bundler combines the winning SolverOperation(s) into one transaction. `README.md`.

**How it works (from the README):** the frontend embeds the Atlas SDK, chooses an Operations Relay (bloXroute BDN, SUAVE, on-chain, or another chain), and publishes a `DAppControl` contract defining `BidFormat`, `BidValue`, `AllocateValue` (mandatory) plus optional `PreOps` / `PreSolver` / `PostSolver` hooks (executed via delegatecall inside try/catch — if one solver's solution reverts, the next solver's solution begins). The auctioneer signs a `DAppOperation` containing a `CallChainHash` (view-callable via `getCallChainHash(SolverOperations[])`) so the bundler cannot tamper with execution order. Ex-post bids: `_bidKnownIteration()` sorts known bids; `_bidFindingIteration()` computes bids on-chain by executing each solver op and checking balance deltas. Gas accounting enforces that each solver pays only for its own operation. `Permit69` lets Atlas move user/dapp funds from a valid Execution Environment (deployed deterministically via create2, user address as salt) after a single approval. `_contribute()` lets actors sponsor gas by donating to the Atlas escrow.

**What it means for a solver:** entry is $0 to enter (bond = gas only, `atlETH` = POL, no minimum in the docs; 1 auction per block per bonded account; Atlas has native flash loans via `_borrow()` escrow; permissionless, no KYC) — but the auction windows run **~250 ms** (arXiv 2510.14642v1, cited in our solver research). Our quote latency alone is 356 ms average. **We cannot win Atlas auctions with current infra.** The framework also lives on Polygon, which is where our bot already is — but speed is the gate, not the chain.

**Verdict for us:** do NOT build on Atlas now. It is infrastructure for solver competition, not an arbitrage bot, and it assumes sub-second infra we do not have. Revisit only after the log proves speed is the bottleneck *and* we have paid infra. The one copyable idea: **ex-post bid measurement** — execute a candidate solution in simulation and measure the balance delta to price it — which is already what our pre-simulation does.

### 2.6 Dimanoshe/flashblocks-rs — Flashblocks are dead; the replacement is here

**What it is:** a Rust crate (+ Python module, `pip install flashblocks`) decoding Base Flashblocks — the 200 ms preconfirmation blocks the Flashbots article (Oct 2026) described as the fast path.

**The critical finding — from its README:** "Base activated **Denim on Nov 5, 2026: a complete canonical block every 200 ms, and Flashblocks were RETIRED** (`wss://mainnet.flashblocks.base.org/ws` still accepts connections but streams nothing)." The Flashbots article's Flashblocks approach is already outdated. The current way is `eth_subscribe("newHeads")` with a **logsBloom prefilter** (read the header first; only fetch the block if its bloom holds a watched topic — no false negatives), plus **backfill**: "Public WebSocket endpoints drop headers under load (one public stream delivered 59% of the blocks)" — the listener remembers the last block and backfills skipped ones by number. Latency ~165 ms in the author's example (mostly RPC read time). Reaction path 5–8 ms in the author's measurements.

**Verdict for us:** do NOT build on Flashblocks (retired). **Copy the replacement:** newHeads + logsBloom prefilter + block-number backfill into our realtime listener. $0 — it is a client-side change, and the Python module exists if we want it. This is the single cheapest latency win in this study.

### 2.7 nenadcodecrypto-hub/v2-arbitrage-bot-base — good contract, broken scanner

**What it is:** atomic cross-DEX arbitrage executor for Uniswap V3 ↔ Aerodrome Slipstream V3 on Base. TypeScript scanner + Solidity executor (`contracts/ArbExecutorUniAerodrome.sol`).

**The contract pattern (worth copying):** one executor per DEX pair; **Model A — the contract holds funds** (USDC/cbBTC), owner pays gas. Uni leg: router `exactInputSingle` with `amountOutMinimum`. Aero leg: **direct pool swap** — `IAerodromeSlipstreamPool.swap(recipient, zeroForOne, int256(amountIn), sqrtPriceLimitX96, "")` with the price limit set to `MIN_SQRT_RATIO + 1` / `MAX_SQRT_RATIO - 1` by direction, then **balance-delta accounting** (`balanceAfter - balanceBefore`) + `require(amountOut >= minAmountOut, "INSUFFICIENT_OUTPUT")`. The callback `uniswapV3SwapCallback` (Aerodrome Slipstream pools use the same callback signature) checks `msg.sender == aerodromeSlipstreamPool` and pays `amount0Delta` / `amount1Delta`. Constructor caches token order from the pool (`token0()` / `token1()`), caches `zeroForOneUSDCtoCbBTC`, and max-approves router + pool. Profit = balance delta, emitted in `ArbCompleted`.

**The scanner (do NOT copy):** `bot/scanner.ts` (110 lines) listens to Uni pool Swap events + reads the Aerodrome pool `slot0`, uses a **fixed 0.3% spread threshold**, no fee/impact math, no sizing, no simulation — and calls `executeArbitrage()`, which is **NEVER defined anywhere in the repo. The repo as cloned does not compile.** Last commit 2026-01-22 ("Testnet finished").

**Verdict for us:** copy the *contract* pattern (direct pool.swap + callback + balance-delta + min-output) into our Aerodrome executor — but with **Morpho flash loan as the funding leg, not contract-held funds** (Model A needs own capital; we have $1.31). Note the Uni leg passes `sqrtPriceLimitX96: 0` — replace with a real limit per §2.3. Do not copy the scanner.

### 2.8 rdin777/atomic-arbitrage-executor — does not compile, do not copy

**What it is (claimed):** WS Swap-event listener on a Uni pool + `slot0` read of an Aerodrome pool, spread > 0.3% fixed threshold. **What the code actually is:** `bot/scanner.ts` (110 lines) calls `executeArbitrage()` — **the function is never defined in the repo. It does not compile.** No fee/impact math, no sizing, no simulation, no flash loan. 1 star, last commit 2026-10-13.

**Verdict:** use only as a cautionary example of what a toy bot looks like. Nothing to copy.

### 2.9 rdin777/base-arbitrage-project — the detector is a mock, do not copy

**What it is (claimed):** cross-DEX arb bot, Uni → Aerodrome. **What the code actually is:** `bot/index.ts` is a **MOCK with a hardcoded 0.57% opportunity** and no real detection loop. The contract is a real EIP-3156 flash-loan executor (Uni → Aerodrome `exactInputSingle`, on-chain `minProfit`) — but with **leg-1 `amountOutMinimum = 0`**, i.e. no slippage protection on the first leg. 0 stars, last commit 2026-10-10.

**Verdict:** do not copy. The hardcoded "opportunity" is the exact failure mode our `label_synthetic_results` skill exists to prevent: a number that looks like a finding and is actually invented. The contract's `amountOutMinimum = 0` is an anti-pattern — never do this.

---

## 3. Ranked lessons — exactly what to copy into OUR repo

Ranked by expected value for OUR setup ($0, Python, $1.31 float, Uni-V3-only, 3 s cycle, 0 live opps). Each lesson names the target file in our repo, the change, the problem it fixes, and the cost.

### L1 — Multi-venue same-block quoting with per-venue adapters + sell-leg re-quote [HIGHEST VALUE]
- **Source:** base-flash-arb-lab §2.2 (case-study 03 method + adapter design); degenbot §2.1 (`degenbot-pools/src/families/*`, `degenbot-pathfinding/src/graph.rs`).
- **Copy into:** `leadlag/cross_venue.py` (in progress by the parallel agent — coordinate, do not duplicate) + a new `leadlag/venues/` adapter package (one adapter per venue: Uni V3, Aerodrome Slipstream, PancakeSwap V3, Uni V4) + `polygon/` quoter.
- **Exact change:** (a) discover pools through each venue's factory across **every fee tier**; (b) quote all venues at the **same pinned block**; (c) **re-quote the sell leg against the quantity the buy leg returned**, not the same dollar size; (d) drop a pool when its own round trip loses >3%; (e) exclude (and log as excluded, with reason) any quote >5% from the median — a nearly-empty pool quotes an absurd price.
- **Fixes:** 6.6% coverage — the single biggest known blindness (Aerodrome = 78.9% of Base top-20 volume, never watched).
- **Cost:** $0. **Expected value:** high *information* value, uncertain *profit* value — the source repo ran this exact method and got 0 on majors. It converts our unknown into a measured unknown. That is still the right first step: you cannot fix what you cannot see.

### L2 — Aerodrome Slipstream quoting + the generation trap [HIGHEST VALUE, part of L1]
- **Source:** Sailor cookbook entry 1–2 (§2.4); v2-arbitrage-bot-base `ArbExecutorUniAerodrome.sol` (§2.7); degenbot `state/aerodrome_v2_state.rs`, `families/solidly.rs` (§2.1).
- **Copy into:** new `leadlag/aerodrome_quoter.py` (quoting via MixedQuoterV3 `quoteExactInputSingleV3`, path hop tagged `0x80000 | tickSpacing`) + new `contracts/AerodromeFlashArb.sol` (direct `pool.swap` + `uniswapV3SwapCallback` + balance-delta + `minAmountOut`, funded by **Morpho flash**, not contract-held funds) + `leadlag/paper_trade.py` (add Aerodrome as a quoted venue).
- **Exact change:** (a) before wiring any router to any pool, assert `SwapRouter.factory() == pool.factory()` on-chain; (b) use the **Gauges V3 factory `0xf8f2eB…` → SwapRouter `0x698Cb2…`** pair for current liquidity, quoter **MixedQuoterV3 `0xCd2A7D…`** — and verify all full addresses on BaseScan first (truncated here; our root-cause audit's on-chain-verified list at block 62,071,176 is the authority); (c) **never use the quoter's tagged tickSpacing on the router** (router takes raw tickSpacing) and never the reverse; (d) declare Slipstream's `slot0()` as **6 fields**, not Uni V3's 7 — a 7-field decode of a 6-word return reverts, and `try`/`catch` does not catch a decode revert in the success arm; (e) pull the ABI from the verified deployed contract, never from the nearest similar-looking interface.
- **Fixes:** the 79% coverage gap, concretely — this is fix #1 from the root-cause audit, now with the exact addresses and the exact trap to avoid.
- **Cost:** $0.

### L3 — Event-driven trigger + persistence filter (stop polling blocks)
- **Source:** degenbot backrun arm (§2.1); flashblocks-rs bloom prefilter (§2.6); aave-oracle-lag-arb `confirmSeconds: 15` (§2.3).
- **Copy into:** `polygon/realtime_listener.py` + `leadlag/paper_trade.py`.
- **Exact change:** (a) subscribe `newHeads`, read the header first, fetch the block **only if its logsBloom holds a watched Swap topic** (no false negatives — the bloom cannot miss a real event); (b) remember the last block number and **backfill skipped blocks by number** (public WS streams drop headers under load — one stream delivered 59%); (c) trigger evaluation off a **Swap event on a watched pool**, not off a 3 s timer; (d) add a **persistence filter**: a signal must survive `confirmSeconds` (15 s, from aave-oracle-lag-arb) before it counts — our paper-trade showed atomic 1-trade jumps that are gone by the next block; a single-block spike is not an opportunity.
- **Fixes:** 3 s cycle (~10% of the root-cause weight) + the weak-signal problem (single-block spikes counted as signal). **Note the limit:** the root-cause audit says speed gains are ≈ 0 with the current signal — this makes us *see* faster, it does not create signal.
- **Cost:** $0 (client-side change; the `flashblocks` Python module exists if wanted).

### L4 — Fail-closed preflight + hard gas-loss budget + per-pool divergence memo
- **Source:** base-flash-arb-lab adapter (§2.2); degenbot `pool_divergence.rs` + `backrun.rs` safety model (§2.1); Sailor cookbook entry 6 (§2.4).
- **Copy into:** `polygon/polygon_guard.py` + `leadlag/paper_trade.py` + the executor.
- **Exact change:** (a) preflight checklist before any send: quote age ≤ 2 blocks, gas cap, deadline (+55 s), operator balance check — **fail closed** (any check fails → no send, logged with reason); (b) a **hard gas-loss reservation**: $2/day + $20 total, ever, for failed transactions — when the budget is exhausted, the bot stops sending (this is what protects the $1.31 float from death by a thousand reverts); (c) a **STOP kill-switch file** — its existence halts all bidding, then the loop (degenbot's model); observe-only default — no bid unless an explicit flag AND a non-zero budget are set; (d) **per-pool divergence memo**: when a pool's state reads wrong (sim fails with a solver-calc error), skip every path through that pool for 100 blocks after the first failure — don't let each path burn its own retry count; (e) **never let a `try`/`catch` swallow a leg** — every failed leg is recorded with a reason and the tick summary reports attempted-vs-executed counts.
- **Fixes:** protects the $1.31 float; stops one stale pool from burning repeated sims; makes silent drops visible.
- **Cost:** $0.

### L5 — Size grid from $25 + a real solver (fix the known 36% overestimate)
- **Source:** degenbot `solve/` (`bounded_brent.rs`, `profit_envelope/`, `gas_floor.rs`) (§2.1); root-cause audit finding #5 (our bug: grid starts at $100, true SOSO threshold is 0.0730% at $50).
- **Copy into:** `math_engine.py` / `polygon/polygon_guard.py` (the sizing function) + `leadlag/paper_trade.py` (evaluation sizes).
- **Exact change:** (a) extend the evaluation size grid down to **$25**; (b) replace the fixed grid with a **bounded optimizer** (Brent-style solve for the profit-maximising loan size — the same shape as our existing `find_optimal_loan`, extended per-path rather than per-pair); (c) log the per-pool threshold at every size, as already decided.
- **Fixes:** the known threshold bug (36% overestimate at $100; gas ×2 = 9% of threshold at $100).
- **Cost:** $0.

### L6 — Execution guards: real `sqrtPriceLimitX96` + transient callback guards
- **Source:** aave-oracle-lag-arb `OracleLagArb.sol` (§2.3); v2-arbitrage-bot-base (§2.7, negative example: `sqrtPriceLimitX96: 0`).
- **Copy into:** `contracts/MorphoFlashLoanArbitrage.sol`, `polygon/contracts/CurveFlashArbPolygon.sol`, and any new Aerodrome executor.
- **Exact change:** (a) pass a real `sqrtPriceLimitX96` on every V3-family swap (a price limit is strictly stronger than `amountOutMinimum` alone — the pool stops at the line); (b) add `transient` storage guards in callbacks (`_activePool` — callback only accepts the active pool; `_flashMode` — nobody else can use the contract as a flash-loan receiver); (c) never pass `amountOutMinimum = 0` on any leg (the rdin777 anti-pattern, §2.9).
- **Fixes:** execution safety — the last line of defence if a quote goes stale between sim and mine.
- **Cost:** $0.

### L7 — Aggregator-first routing + dead-pool gate + failure alerts
- **Source:** aave-oracle-lag-arb `bot/core.ts` (§2.3).
- **Copy into:** the quoter + `leadlag/paper_trade.py` + the listener.
- **Exact change:** (a) ask an aggregator (Kyber — free API) first for a route across Uni V3/V4, Aerodrome, Curve, market makers; fall back to a single pool only if the aggregator isn't better; (b) **dead-pool gate**: a pool holding less than 5 WETH-equivalent is dead — don't trade there, and don't hold a position because it shows a premium; (c) **alert after 5 consecutive failed actions** (sim or send); (d) `gasLimitMult: 1.25` and `maxFeeBaseMult: 2` for gas estimation headroom; (e) self-validating config — the bot refuses to start if its parameters violate protocol constants (e.g. health-factor floor).
- **Fixes:** coverage (aggregator sees venues we don't) + stale-pool noise + silent failure.
- **Cost:** $0 (Kyber API is free).

### L8 — Nonces from chain state; await receipts; surface every failure
- **Source:** Sailor cookbook entries 6 and 9 (§2.4).
- **Copy into:** the executor / `sepolia/deploy_sepolia.py` and any send loop.
- **Exact change:** (a) never track the next nonce locally — re-derive it from chain (`getTransactionCount(address, 'pending')`) immediately before every send, because a **mined-but-reverted** transaction still consumes the nonce; (b) await each receipt before sending the next; (c) every failed leg is an outcome with a reason, never a swallowed `continue`.
- **Fixes:** the cascading "nonce too low" failure after the first revert; invisible dropped legs.
- **Cost:** $0.

### L9 — V4 support: PoolKey recovery + router order from a live tx + chained single-hops
- **Source:** Sailor cookbook entries 3, 7, 8 (§2.4).
- **Copy into:** V4 work, when we add it (V4 support is currently missing from the Base scanner).
- **Exact change:** (a) recover a V4 `PoolKey` from the `PositionManager.poolKeys(bytes25)` storage mapping (top 25 bytes of the `poolId`) — no event log needed; (b) when a V4 router program reverts, decode a **live successfully-mined transaction** against the same deployed router and match its action layout exactly (theirs required settle-first: `SETTLE(payerIsUser=true)` → `SWAP` → `TAKE`); (c) route multi-hop as chained single-hops with the second leg's input wired to the first leg's output via open-delta accounting, not a multi-hop struct.
- **Fixes:** unblocks V4 (70% of new Base launches, per our earlier finding).
- **Cost:** $0. **Priority:** after L1–L3 — V4 matters for new launches, but majors first.

### L10 — Rust core + in-process simulation (do NOT copy yet)
- **Source:** degenbot architecture (§2.1).
- **What it is:** Rust core, pool state in memory, in-process EVM simulation, ms-level reaction. It is the single biggest structural difference between the pros and us.
- **Why not now:** a rewrite costs weeks; the root-cause audit attributes only ~10% of our zero to speed, and says the gain is ≈ 0 with the current signal (our predicted moves max 0.009–0.018% vs thresholds 0.033–0.167% — the model can never trigger, at any speed). **Rule from our own solver research: measure first, spend later.** Speed only pays after the log proves it is the bottleneck. Python at 3 s is fine for *measurement*; Rust pays for *execution* — and we have nothing to execute yet.
- **Cost:** $0 in money, very expensive in time. **Trigger to revisit:** the 7-day Aerodrome paper test shows real entries that we lose to latency (predicted net > $0, but the gap closes before our 3 s cycle sees it).

---

## 4. Top 3 things to implement next, in order

### #1 — Aerodrome Slipstream quoting + same-block cross-venue quoting (L1 + L2)
The fix #1 from the root-cause audit, now with exact instructions: per-venue adapters, factory discovery across all fee tiers, same pinned block, sell-leg re-quote against buy-leg output, the 3%/5% depth-artifact filters, MixedQuoterV3 with tagged tickSpacing, the `factory()` on-chain check, and the 6-field `slot0` trap. This closes the 79% coverage gap for $0. **Success criterion:** 7 days of Aerodrome-vs-Uni-V3 same-pair measurement; GO/NO-GO by the same rule as before (≥5 entries/week predicted net > $1).

### #2 — Event-driven trigger + persistence filter + fail-closed preflight (L3 + L4)
newHeads + logsBloom prefilter + block backfill; evaluate off Swap events, not a timer; 15 s persistence filter; preflight checklist (age ≤ 2 blocks, gas cap, deadline, balance check); $2/day + $20 total gas-loss budget; STOP file; per-pool divergence memo (100-block skip). This turns the poller into a reactor and puts a hard ceiling on what failure can cost the $1.31 float. $0.

### #3 — $25 size grid + real solver + execution guards (L5 + L6)
Fix the known 36% threshold overestimate, solve optimal size per path (Brent-style), and harden the contracts with real `sqrtPriceLimitX96` + transient callback guards + never `amountOutMinimum = 0`. $0. This is the last mile of "our machine is correct" — after this, a zero is a market verdict, not a machine verdict.

---

## 5. Not applicable / dead / scam — say so plainly

| Thing | Why not for us |
|---|---|
| **MEVBlocker / Flashbots bundles** (`eth_sendBundle`) | Ethereum-only. Base has no public mempool (private sequencer); Polygon's private mempool has no documented revert-drop. The *bundle* mechanism doesn't transfer. The *react-to-a-tx* pattern does (§2.1, L3). |
| **Flashblocks** | **Retired 2026-11-05 (Denim).** The endpoint still accepts connections but streams nothing. Use newHeads + bloom prefilter instead (§2.6). |
| **Balancer flash loans** | **Dead (BIP-928, wound down 30 Oct 2026).** base-flash-arb-lab's "Balancer V2 charges 0 on Base" is stale. Do not copy (§2.2). |
| **Aave oracle-lag strategy** (borrow at oracle, sell above, buy back) | Leveraged directional position, needs collateral, liquidation risk. NOT $0, NOT risk-free. Copy its engineering, not the strategy (§2.3). |
| **Atlas solver auctions** | $0 to enter, but ~250 ms windows — unwinnable at our 356 ms quote latency. Revisit only with paid infra *after* the log proves speed is the bottleneck (§2.5). |
| **rdin777 repos** | One doesn't compile (`executeArbitrage` never defined); the other hardcodes a fake 0.57% "opportunity" and passes `amountOutMinimum = 0`. Nothing to copy (§2.8, §2.9). |
| **degenbot full codebase** | Production Rust workspace. Copy patterns, not code — rewrite cost dwarfs the ~10% speed share of our zero (§2.1, L10). |
| **v2-arbitrage-bot-base Model A** (contract holds funds) | Needs own capital. We have $1.31. Use its *contract pattern* with Morpho flash funding instead (§2.7). |

---

## 6. Honest bottom line

The experts confirm our measurements twice over:

1. **The market is efficient at our scale.** base-flash-arb-lab (Python, Base, same method) got 0 profitable cycles on majors, best −3.3 bp, "the loss was approximately the sum of the two pool fees." Our 61,065 quotes say the same thing in our own numbers.
2. **The edge the pros have is coverage + trigger + speed — not a secret signal.** Nobody in these repos has a Binance order-book signal that predicts moves; degenbot reacts to transactions that already happened (backrun), and aave-oracle-lag-arb waits 15 s for a premium to *persist* — the opposite of predicting. Our lead-lag paper test (0 ENTRY in 567 cycles, predicted moves 7–10× below thresholds) is consistent with the literature the audit cited (Cont et al. 2014: predictive OFI R² ≈ 0.0003).
3. **The remaining untested ground is narrow and specific:** same-pair cross-venue gaps (what Ismail spotted on DexScreener — our scan never looked) and Aerodrome's 79% of volume (never quoted). That is exactly top-3 item #1. If 7 days of that also returns 0, the honest conclusion is the one already ranked: **bug bounties / audit contests are the best $0 path** — and the skill they build is the audit our own bot needs before mainnet anyway.

**No repo in this study shows a solo $0 bot earning real money on majors in 2026.** The repos that earn are either (a) measuring and reporting zero honestly (base-flash-arb-lab), (b) running leveraged/collateralised strategies (aave-oracle-lag-arb), or (c) production infrastructure with paid speed (degenbot, Atlas solvers). That is the truth to carry into the next decision.
