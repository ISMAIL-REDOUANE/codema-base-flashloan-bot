# The Cheapest Solver — Deep Dive + The Full $0 Landscape

**Date:** 2026-11-25
**For:** Ismail — $1.31 MATIC float, no server budget, MetaMask, free Alchemy (Base + Sepolia; Polygon NOT yet enabled)
**Scope:** Part A = the cheapest-solver deep dive (Ismail's order: "find me the BEST WAY to be the CHEAPEST solver"). Part B = the full $0 landscape — solver ranked against every other real $0 way to earn in crypto/DeFi.
**Companion file:** `SOLVER_ZERO_DOLLAR_POLYGON.md` (the solver-roles research: FastLane Atlas, CoW, 1inch Fusion, UniswapX, Across — read it first for role details).
**Verified repo numbers used here (not re-verified, cited):** `LOW_FEE_PROFIT_POLYGON.md` — V3 0.01% tiers, Algebra stables 0.001%, Curve am3pool 0.001%, Morpho flash 0%, Morpho Polygon USDC $75,540 → max loan ~$37,770 (50% rule), Curve 4-leg route net +$5.63 on a $5k loan, Polygon gas ~$0.0095/trade measured, realtime quote latency avg 355.7 ms.

---

## PART A — THE CHEAPEST SOLVER

### A.0 What "cheapest" actually means

In every solver auction (UniswapX Dutch auction, CoW batch auction, 1inch Fusion Dutch auction, FastLane Atlas) the winner is the solver that delivers **the most output tokens for the same input tokens**. The solver's edge is:

```
edge per fill = (output from best route) − (gas) − (capital cost) − (bid, if any)
```

"Cheapest" = **lowest total cost per fill**. A solver with lower costs can either offer a better price (and win) or bid more (in Atlas, the bid is a share of the MEV paid to the validator) and still profit. Every lever below is judged on one question: **how many basis points (bps) does it save per fill, and what does it cost?**

1 bp = 0.01%. On a $5,000 fill, 1 bp = $0.50.

---

### A.1 Lever 1 — Inventory vs flash loan

**The question:** when does holding the output token beat borrowing it with a flash loan?

**Flash path (what Ismail already has):** borrow from Morpho at 0% → swap on the cheapest venue → deliver output. Cost per $5,000 fill on the best venue (V3 0.01% tier):

| Cost item | $ |
|---|---|
| Swap fee (0.01% of $5,000) | $0.50 |
| Gas (Polygon, measured ~$0.0095) | $0.01 |
| **Total per fill** | **~$0.51** |

**Inventory path:** hold the output token in advance → deliver it directly, no swap at all. Cost:

| Cost item | $/day for $5,000 of stables |
|---|---|
| Capital cost (opportunity cost of holding $5k stables — **model assumption: 5% APR**, e.g. a lending yield) | $0.685/day |
| Rebalancing (once/day: swap back to refill, 0.01% fee + gas) | $0.51/day |
| **Total per day** | **~$1.19/day** |

**Breakeven math (model, assumptions stated above):**

```
flash cost/day  = N × $0.51        (N = fills per day of $5,000)
inventory cost/day = $1.19 (fixed)
breakeven: N × 0.51 = 1.19  →  N ≈ 2.3 fills/day
```

| Fills/day ($5k each) | Flash cost/day | Inventory cost/day | Winner |
|---|---|---|---|
| 1 | $0.51 | $1.19 | **Flash** (saves $0.68) |
| 2.3 | $1.19 | $1.19 | Tie |
| 10 | $5.10 | $1.19 | **Inventory** (saves $3.91/day) |
| 100 | $50.95 | $1.19 | **Inventory** (saves $49.76/day) |

**Verdict for Ismail ($1.31 float): flash wins, always.** His inventory is $0 — he cannot hold $5,000 of anything, and at 0–1 fills/day the capital cost of inventory exceeds the swap fee it saves. Inventory only wins for a funded solver doing **more than ~2–3 fills/day of $5k size**. This is the single most important fact for him: **he does not need capital to be competitive at low volume — flash is the correct tool at his scale.**

**Two hard limits on inventory that flash does not have:**
- **Volatile inventory is dangerous.** Holding $5,000 of WMATIC: a ±10% move = ±$500 — that one move is ~1,000× the $0.50 fee saving. Small solvers hold **stables only** (IL ≈ 0). Flash has zero price exposure (borrow → swap → repay inside one transaction).
- **Flash size cap on Polygon:** Morpho holds $75,540 native USDC → max loan ~$37,770 at the 50% rule (LOW_FEE_PROFIT_POLYGON.md). Flash covers fills up to ~$37k on Polygon; above that, only inventory (or another lender) works. At Ismail's scale this cap is irrelevant.

**The one case where flash loses even at low volume:** a fill where the output token is only available on an expensive venue (e.g. V2 0.30% = $15 on $5k) while a funded solver holds the token and delivers it for $0.01 gas. That is a 29.9 bp disadvantage per fill — but only on pairs where the cheap venues don't exist. On stables and majors, the 0.01%/0.001% venues exist, so the gap is 1 bp or less.

---

### A.2 Lever 2 — Routing: lowest-fee venues + smart order routing

**The fee ladder on Polygon (verified in-repo, LOW_FEE_PROFIT_POLYGON.md):**

| Venue | Fee per leg | Cost on $5,000 |
|---|---|---|
| Uniswap V2 / QuickSwap V2 / Sushi V2 | 0.30% (30 bp) | $15.00 |
| Uniswap V3 0.05% tier | 0.05% (5 bp) | $2.50 |
| Uniswap V3 0.01% tier | 0.01% (1 bp) | $0.50 |
| Algebra stables (dynamic fee) | 0.001% (0.1 bp) | $0.05 |
| Curve am3pool | 0.001% (0.1 bp) | $0.05 |
| Morpho flash loan | 0% | $0.00 |

**Value of routing venue choice: up to ~29.9 bp per leg** (V2 → Algebra/Curve). This is the biggest free lever in the whole game — bigger than gas, bigger than latency, bigger than inventory at low volume. Ismail's Curve 4-leg route is exactly this: it uses two 0.01% V3 legs + one 0.001% Curve leg, and the gross spread it captures (~0.11%) comes from the Curve pool being stale (1.0001 vs market ~0.9988).

**Smart order routing (SOR) — splitting across venues:** worth **~2–4 bp per fill** on liquid pairs, per the best available study:
- Xi & Moallemi (Columbia), 2.98M WETH–USDC swaps on Ethereum: average shortfall vs optimal routing = **2.02 bp/trade** ($24M on ~$120B volume). Timing (one-block lag) degrades performance further; sandwiching drives a significant fraction of sub-optimality.
- Aggregator analyses cite ~3–4 bp consistent improvement on liquid pairs from optimal routing vs a single-venue route.

**When splitting helps and when it doesn't:**
- Helps: thin pools where one venue's price impact exceeds the fee saved by splitting (e.g. a $20k fill on a $50k pool).
- Doesn't help: deep stable pools where price impact is ~$0.02 at $5k (measured live in the repo) — splitting adds extra gas per leg with no gain.
- **For Ismail:** SOR is worth ~2 bp/fill at most on his pairs, and only after the venue ladder is already used. Priority: venue ladder first (up to 30 bp), SOR second (~2 bp).

**Breakeven table (guard math, from LOW_FEE_PROFIT_POLYGON.md — reproduced, not re-derived):**

| Route | Breakeven spread | 0.05% spread on $5k |
|---|---|---|
| V3 0.05% + V3 0.05% | 0.100% | −$2.53 |
| V3 0.01% + V3 0.01% | 0.020% | +$1.47 |
| V3 0.01% + Algebra/Curve 0.001% | 0.011% | +$1.98 |

---

### A.3 Lever 3 — Gas

**Measured numbers (repo, not re-verified):** Polygon ~$0.0095/trade (450,000 gas × ~282 gwei, prudent 2× budget); Base ~$0.005/trade.

**Gas in bps — it is NOT the bottleneck at solver sizes:**

| Fill size | Polygon gas $0.0095 | Base gas $0.005 |
|---|---|---|
| $100 | 0.95 bp | 0.50 bp |
| $1,000 | 0.095 bp | 0.05 bp |
| $5,000 | 0.019 bp | 0.01 bp |
| $20,000 | 0.005 bp | 0.003 bp |

Gas optimization (smaller contract, fewer SSTOREs, batching) might save ~$0.003/trade — **0.006 bp on a $5k fill**. Irrelevant next to the 30 bp venue ladder. Gas only matters in two cases:
1. **Small fills** ($100: gas is ~1 bp, comparable to the swap fee).
2. **Reverts.** A revert on Polygon costs **$0.0024 measured / $0.0095 prudent** — and the repo's `revert_protection.py` already handles this: re-simulate with `eth_call` at the latest block before sending, quote freshness window 30 s, drop before broadcast at $0 gas if the net is gone. Expected revert cost at a 5% race rate ≈ $0.000475/trade. **No verified service gives $0 on an on-chain revert on Polygon today** (FastLane Atlas blog: "No Free Reverts"; MEV Blocker `/noreverts` is Ethereum-only; ERC-4337 paymasters cannot make a revert $0 — EntryPoint charges gas even on revert). This is a solved problem at $0.0024, not a $0 problem.

**Private submission:**
- **Polygon Private Mempool:** exists, free, live since 2026-04-02, anti-frontrunning — but no documented simulation/drop of reverts, endpoint unpublished (access on request). Worth applying for ($0), gain = no frontrunning on his fills.
- **FastLane Atlas:** submission goes through the Atlas auction; the bid is a share of the MEV (first-price sealed-bid) — the bid IS the cost, not a saving. No $0 revert on Polygon via Atlas.

**Verdict:** gas is a solved ~0.02 bp problem at his sizes. Do not spend money on gas optimization. Spend the effort on routing (30 bp) instead.

---

### A.4 Lever 4 — Latency / speed

**The numbers:**
- FastLane Atlas (Polygon PFL validator MEV auction): sealed-bid first-price, **~250 ms auction windows** (arXiv 2510.14642v1).
- Ismail's measured quote latency: **avg 355.7 ms, max 1,978.6 ms** (realtime listener run 2, 1,200 blocks, 100% coverage).
- **His latency already exceeds the Atlas auction window.** He cannot win Atlas auctions with a 356 ms quote loop on a free public RPC.

**What speed costs:**

| Upgrade | Cost | What it wins |
|---|---|---|
| Free Alchemy (current) | $0 | Baseline: 356 ms quotes, rate limits |
| Alchemy paid entry tier | ~$49/mo (Scale $49/mo per chainpick.io 2026 comparison; plan names/prices vary across sources — verify on alchemy.com before quoting) | Higher rate limits, lower latency — **gain in win-rate NOT quantified by any source** |
| VPS for the bot (24/7 uptime) | $5–10/mo | Uptime, not speed |
| Own Polygon node (full node, 2TB+ storage) | $200–500/mo (per one operator guide) | Mempool access + lowest latency + no rate limits |
| Colocation / private fiber | $1,000+/mo | Only relevant for Ethereum L1 HFT; **no Polygon-specific colocation product documented** |

**Honest quantification:** no source quantifies "X ms faster = Y% more wins" for Polygon solvers. What is true:
- On Polygon (2 s blocks), a 356 ms quote is **usually enough for uncontested flow** (a stale Curve pool, a public UniswapX order sitting for seconds) — the opportunity lives longer than one block.
- It is **not enough for contested flow** (Atlas auctions at ~250 ms, or a spread born and dying inside one block — invisible to per-block polling anyway).
- **The correct order: measure first, spend later.** His listener already measures latency per block. Only pay for a faster RPC when the log shows fills lost *because* the quote arrived late — not before.

**Verdict:** latency is the lever that costs the most money and is the hardest to quantify. It is lever #4, not #1. The $0 stack wins on routing + flash, not on speed.

---

### A.5 Lever 5 — Order flow

**Where solvers get flow, and what it costs:**

| Flow source | Access | Cost | Notes |
|---|---|---|---|
| UniswapX orders API (free, `api.uniswap.org/v2/orders`, ≤4 RPS, no key) | Public | $0 | **Probed live: `{"orders":[]}` on Base Dutch_V3 and Ethereum Dutch_V2 at probe time (~06:25 UTC)** — endpoint works, flow was thin at that instant |
| CoW Protocol batch auctions | Public, open competition | $0 to enter; bond via DAO pool needs KYC + company + approval (SOLVER_ZERO_DOLLAR_POLYGON.md) | Flow is public — no exclusivity; 29 active solvers |
| FastLane Atlas OFA (order-flow auctions) | Apps run auctions; solvers see flow only if they run a solver | Bond (atlETH, gas escrow, no minimum in docs) + ~250 ms speed | Flow goes to the fastest solver, not the cheapest |
| 1inch Fusion Dutch auctions | Resolvers get flow via the auction | Stake (top-10 Unicorn Power, min 5% of total UP per FAQ) + KYC/KYB — **not $0**; new delegations closed 11 Nov 2026 | Delegation farms deprecated Nov 2026 — resolvers must now self-stake |
| UniswapX RFQ quoters | **Permissioned** — chosen by Uniswap Labs on expertise/track record | Not $0 in reputation terms | Winner gets ~24 s exclusivity; orders backstopped by the Uniswap Smart Order Router; UniswapX is included in routing when the order is >300 USDC or improves the AMM route by ≥0.2% (per dev.to analysis of Uniswap docs) |
| Private/exclusive flow (wallets, apps, Telegram bots) | Relationships | Time, not money — but a solo unknown solver gets none | This is how the big solvers win: they are the default filler for a wallet/app, not the fastest bidder on public flow |

**Verdict:** a solo $0 solver gets **public flow only**. Exclusive flow is the highest-value lever in the long run (it removes competition entirely), but it cannot be bought for $0 and cannot be built in a week — it comes from shipping a useful product (a frontend, a wallet integration, a bot others use) and being trusted. For Ismail, the realistic $0 flow is: UniswapX public orders + his own Polygon listener finding stale pools. That is enough to start; it is not enough to scale.

---

### A.6 Lever 6 — Rebates / incentives (documented only)

| Protocol | Incentive | Documented numbers | Catch |
|---|---|---|---|
| **CoW Protocol** | Weekly solver rewards in COW (Tuesdays), VCG-style performance rewards | Upper cap β = **50% of protocol fee** on ETH/Arbitrum/Base/BNB, **100% on Polygon/Gnosis/Avalanche/Linea/Ink/Plasma**; global bound = native-token equivalent of **$20**; payment can be **negative** (solver pays protocol); 29 active solvers; protocol subsidizes the competition (docs.cow.fi). Quote rewards also exist (secondary source: 6 COW/order, cap 0.0006 ETH) | Rewards are capped and can go negative; you must already be an approved solver (KYC + company + DAO bond pool) |
| **1inch Fusion** | Gas-fee refunds for resolvers only | Foundation allocated **10M 1INCH**, max **1M 1INCH/month per resolver** (secondary source udbx.com); 1inch FAQ confirms only resolvers are eligible for gas refunds | Resolver role itself is not $0 (Unicorn Power stake + KYC); delegation closed Nov 2026 |
| **UniswapX** | None documented for fillers | — | The filler's revenue is the spread, not a rebate |
| **FastLane Atlas** | None documented for solvers | — | The solver PAYS the bid to the validator; there is no rebate |
| **Across / Relay** | Relayer fee (~0.011% example) | — | That is the revenue, not a rebate — and both need own capital |

**Verdict:** the only real rebate stream is CoW's solver rewards — and it is capped, can go negative, and sits behind a KYC/company/approval gate. Rebates are a bonus, never the business model. Do not build a strategy around them.

---

### A.7 Lever 7 — Capital efficiency: flash vs inventory, the exact math

Consolidated from A.1, with the two floats compared:

| | Ismail ($1.31 float) | Funded solver ($10k stables) |
|---|---|---|
| Flash cost per $5k fill | $0.51 (0.01% fee + gas) | $0.51 |
| Inventory cost per day | N/A (cannot hold) | $1.88/day ($10k at 5% APR = $1.37/day + rebalance $0.51) — covers fills up to $10k |
| Breakeven fills/day | — | ~3.7 fills/day of $5k (1.88 / 0.51) |
| Max single fill (flash) | ~$37,770 (Morpho Polygon USDC $75,540 × 50%) | Same (flash cap is the lender's, not his) |
| Price exposure | Zero (atomic) | Stables ≈ 0; volatiles ±10% = ±$500 per $5k |
| **Winner** | **Flash, by default** | **Flash below ~4 fills/day; inventory above** |

**The rule:** flash wins until you are doing several fills a day, every day. Inventory is a scale play, not a starting play. A solver with $1.31 does not have a capital-efficiency problem — he has a **flow problem** (finding fills) and a **routing problem** (winning them cheaply). Both are solvable for $0.

---

### A.8 THE $0 STACK FOR ISMAIL — the exact cheapest-solver setup

**What he runs, step by step, $0:**

1. **Enable Polygon Mainnet on the Alchemy "Base-Bot" app** ($0, dashboard, account Ismailredouane97@gmail.com) — unlocks archive data (7-day backtest) + a reliable Polygon RPC. *This is also the unblock for the backtest.*
2. **Base: UniswapX order watcher.** Poll the free orders API (`api.uniswap.org/v2/orders`, ≤4 RPS, no key) for Dutch_V3 orders on Base. No inventory needed — `executeWithCallback` gives the filler the input tokens first. Log every order + whether it was fillable at a profit. Paper-fill for 1 week.
3. **Polygon: keep the realtime listener running** (already built, `realtime_listener.py`, 1,200 blocks / 46,800 quotes / 0 missed in run 2). It is the flow-finder for stale pools.
4. **Route every fill through the lowest-fee venue available** — V3 0.01% → Algebra 0.001% → Curve 0.001% (the Curve stale-price edge: USDT ~$0.9988 vs am3pool 1.0001, net +$5.63 on $5k). Never route through V2 (30 bp) when a 0.01% pool exists for the same pair.
5. **Execute with Morpho flash loans (0%) on Polygon** — no inventory, no capital cost, atomic. On Base, the UniswapX callback is the equivalent (no inventory).
6. **Pre-simulate every fill** (`revert_protection.py`: `eth_call` at latest block, 30 s quote freshness, drop at $0 gas if net is gone). Revert cost if it still slips through: $0.0024 measured.
7. **Submit via public RPC now; apply for the Polygon Private Mempool** (free, access on request) — gain: no frontrunning. Do NOT pay for FastLane until the log shows fills lost to speed.
8. **Log everything** — every order seen, every fill attempted, net, gas, latency. The log is what tells him which upgrade to buy first.

**The upgrade ladder — what each upgrade costs and what it gains:**

| # | Upgrade | Cost | Gain | Buy when… |
|---|---|---|---|---|
| 0 | Enable Polygon on Alchemy | $0 | Archive + reliable RPC | **Now** |
| 1 | Polygon Private Mempool access | $0 (on request) | No frontrunning | Now (apply) |
| 2 | Bridge ~$1 MATIC → ETH on Base | ~$0.02 + gas (Relay) | Access to UniswapX filler flow on Base | When the Base watcher shows orders worth filling |
| 3 | VPS for 24/7 bot uptime | $5–10/mo | Uptime, not speed | When fills are missed because the laptop was off |
| 4 | Alchemy paid RPC tier | ~$49/mo | Higher rate limits, lower latency (win-rate gain **not quantified**) | When the log shows fills lost to late quotes |
| 5 | Stable inventory $1k → $10k | 5% APR opportunity cost ($50–$500/yr) | Saves ~1 bp/fill on best venues; wins only above ~2–5 fills/day | When fill rate is consistently above breakeven |
| 6 | Own Polygon node | $200–500/mo | Mempool access + lowest latency | When competing for Atlas auctions |
| 7 | Contract audit | Thousands of $ | Required before any mainnet contract use | Before any real-money fill through his own contract |
| 8 | CoW solver (KYC + company + DAO bond pool) | Company formation + time (cost varies by country, not $0) | Weekly COW rewards + public batch-auction flow | When he wants a second, subsidized flow source |

### A.9 VERDICT — the single best way for HIM to be the cheapest solver, ranked 1-2-3

1. **Flash + lowest-fee routing (the Curve edge).** Free, immediate, biggest gain: up to ~30 bp/leg vs V2 routing, plus the verified +$5.63/$5k stale-Curve edge. This is the only lever that is both $0 and large. **First concrete action: launch the Curve leg + fork test — the window can close at any block.**
2. **Free flow + pre-simulation discipline.** UniswapX public orders on Base + the Polygon listener + drop-before-broadcast on every fill. $0, protects the $1.31 float (46 trades of runway on the Curve route at $0.028/trade). **First concrete action: start the Base order watcher and paper-fill for one week.**
3. **Paid speed only after the log proves it is the bottleneck.** Dedicated RPC, node, inventory — all cost money and none has a quantified win-rate gain for a solo solver. **First concrete action: none — measure first.**

**The one-line answer:** the cheapest solver at $0 is not the fastest solver — it is the solver that **never pays a swap fee it could have avoided and never pays for inventory it doesn't need**. Flash (0%) + 0.01%/0.001% venues + pre-simulation is the whole stack. Speed and inventory are scale upgrades, not starting requirements.

---

## PART B — THE FULL $0 LANDSCAPE

**The question:** "Is SOLVER the only thing I can do for $0, or are there OTHER BETTER things?"

**Short answer: solver is NOT the best $0 path for him. It is #3.** The full ranking is below. One framing note first: **none of these beats his real business.** One CODEMA client project (a website: 4,500 DH ≈ $450, Formasup quote) is worth more than months of quests or a year of median airdrop farming. These $0 paths are side income; CODEMA is the income. Rank them as side income, not as a replacement.

### B.1 The candidates (each: one sentence, $0 feasibility, realistic earnings, time-to-first-dollar, fit)

**1. Flash-loan arbitrage — the baseline (already built).**
- What: borrow free (Morpho 0%), swap across DEXes, repay, keep the spread. Gas only.
- $0: **YES** — gas is the only cost; his $1.31 MATIC = ~46 trades on the Curve route ($0.028/trade) or ~137 trades on 2-leg routes ($0.0095/trade).
- Earnings: **measured, not promised.** 61,065 live quotes + 117 measurements = 0 signals — EXCEPT the Curve 4-leg route: **net +$5.63 per $5k loan, verified live by me at blocks 97,921,306–308** (LOW_FEE_PROFIT_POLYGON.md). Per-trade profit is small and the window can die at any block.
- Time-to-first-dollar: **days** — needs the Curve leg in the contract + fork test, then an audited mainnet execution.
- Fit: perfect — he already built the machine; this is the only candidate with a verified live positive number.

**2. Solver roles (Part A + SOLVER_ZERO_DOLLAR_POLYGON.md).**
- What: fill other users' intents (UniswapX, CoW, 1inch, FastLane Atlas) and keep the spread/fee.
- $0: **YES for one role only** — UniswapX non-exclusive filler on Base (permissionless, no bond, no KYC, no inventory via `executeWithCallback`). Atlas is $0 to enter but not winnable at 356 ms latency; CoW needs KYC + company + approval; 1inch needs a Unicorn Power stake; Across/Relay need own capital.
- Earnings: **unproven for a solo.** The orders API returned `{"orders":[]}` at probe time; no documented solo-filler income figure exists (Titania Research: "challenging to generate significant profits" as a solo filler).
- Time-to-first-dollar: **1–2 weeks** (build the watcher, paper-fill, then fill).
- Fit: good — reuses his bot, his Alchemy, his Python. But it is a second live income line, not the first.

**3. Bug bounties / audit contests (Code4rena, Sherlock, Immunefi, Cantina).**
- What: find vulnerabilities in protocols' smart contracts in time-boxed contests; get paid per finding by severity and uniqueness.
- $0: **YES** — free to enter, no stake, no capital. The cost is skill and time.
- Earnings (documented, honest): Code4rena 2023 — 31,512 submissions across 114 audits, $4,823,059 paid; of 10,000+ registered wardens only 1,323 earned anything (**87% earned $0**); average earning warden **$3,646/year**. Beginner (first 3–6 contests): **$0–$500 total**. Intermediate (6–18 months): $800–$3,000/contest. Top 50: $5,000–$15,000/month. Top 10: $15,000–$40,000/month (maybe 30–40 people in the world at that level). Immunefi: median critical payout **$20,000** (mean $114,355, heavy-tailed); median confirmed payout overall ~$2,000; $140M+ paid all-time; a single critical can pay $20k. (Sources: dev.to "The bounty trap", gigs.sh Code4rena guide, jakeinsight.com 2026 bounty income, Immunefi research via coinlaw.io / hoge.gg.)
- Time-to-first-dollar: **1–3 months** (learn Solidity security, read audit reports, enter contests; first payouts usually come after several contests).
- Fit: **very good, and strategic** — the skill directly audits his own bot contract (which needs an audit before mainnet anyway). Highest ceiling of all $0 paths. The catch is the learning curve: he builds web apps, not smart contracts — but he has now written and fork-tested Solidity, so the gap is months, not years.

**4. Testnet / airdrop farming.**
- What: use new protocols (testnets = free faucet tokens; mainnet = real gas + capital) before their token launch, hoping for an airdrop.
- $0: **CONDITIONAL — testnet-only is $0 cash; mainnet farming is NOT $0.** Realistic mainnet farmer costs $300–$2,000/year in gas (copytradeinsider.com 2026 guide). Testnets cost $0 cash but hours of time, and most testnets pay $0.
- Earnings (documented, honest): the four biggest 2024 airdrops (Hyperliquid $1.5B+, EigenLayer $800M, Wormhole $800M, LayerZero $600M) — median qualifying wallet collected **$500–$3,000**; top decile $20,000–$200,000. But after honest costs, the **median active farmer netted $200–$1,500/year for 100–400 hours** ($5–$25/hour). The 2024 LayerZero Sybil cull removed 800,000 wallets pre-snapshot. **$5,000 deployable capital is the practical minimum for meaningful returns** (same source). Testnet-only farming removes the gas cost but also removes most of the upside — the big payouts (Hyperliquid avg $10,000+) went to real mainnet users with real activity.
- Time-to-first-dollar: **months to a year** (airdrops pay at token launch, if ever).
- Fit: poor as a main path — lottery-ticket economics, time-heavy, and his $1.31 cannot do mainnet farming. Do it in dead time, not as the plan.

**5. Learn-to-earn / quests (Galxe, Layer3, Binance Learn & Earn, CoinMarketCap Earn).**
- What: complete quizzes and on-chain tasks for small token rewards.
- $0: **YES for quiz-based** (Binance Learn & Earn, CMC Earn: $1–$4 per quiz, free). **On-chain quests are NOT $0** — they cost gas ($3–$15/tx on Ethereum, less on L2s), which eats his $1.31 fast.
- Earnings (documented): per campaign **$1–$50** (30–60 min each); active users doing 2–5 campaigns/week accumulate **$50–$200/month**; realistic monthly total across ALL platforms if you complete everything: **$40–$150** (altcoininvestor.com, decentralised.news, 2026).
- Time-to-first-dollar: **today** — the fastest first dollar of any candidate.
- Fit: fine as pocket money, terrible as a plan — the ceiling is ~$150/month even doing everything, and on-chain quests cost gas he can't spare. Quiz-based only.

**6. Grants (Gitcoin, protocol/ecosystem grants).**
- What: apply for funding to build open-source public goods.
- $0: **YES to apply — but there is currently nothing to apply to at Gitcoin.** Gitcoin Grants ran no round after GG24 (closed 28 Oct 2025, ~$1.8M across six domains, max match $15k/project); as of Oct 2026 Gitcoin is folding quadratic funding into a local-money pilot with **no application for builders yet** (web3grant.com, checked Nov 2026). Other programs: web3grant's directory lists 100 grant programs, 78 accepting year-round — but they fund shipped products with community support, not ideas.
- Earnings: Gitcoin GG24: up to $15k/project; other programs $1k–$50k typical. A solo dev with no shipped product and no community: **expected $0**.
- Time-to-first-dollar: **months** (build → apply → wait → maybe).
- Fit: weak now, interesting later — his open-source bot could become a grant candidate once it is shipped, documented, and used. Watch, don't chase.

**7. Running infrastructure for others (Lava Network, POKT, public RPC).**
- What: run nodes and serve RPC requests for a decentralized network, earn tokens.
- $0: **NO.** Lava providers must **stake LAVA** to appear on pairing lists, run a node (infra cost), and compete on QoS (uptime, latency, request volume); rewards come from subscription revenue + Provider Drops (44M LAVA over 4 years, varies with demand). A full node needs $200–500/mo of VPS (2TB+ storage). POKT has the same shape (stake + infra). **Verdict: rejected — not $0.**
- Earnings: not quantified for a small provider; dominated by large operators with big stakes.
- Fit: none at $0.

**8. Other $0 earners found — and why they don't rank:**
- **Exchange referrals (Binance/Bybit/etc.):** $0 to join, real — but pays a cut of referred traders' fees, so it needs a trading audience. Ismail has none. Expected $0. Not ranked.
- **MEV-Share searcher:** Ethereum L1 only, needs own infra + speed + capital; same competition as solver but harder. Not $0-feasible for him. Dropped.
- **Testnet validator roles:** free to run on testnets, sometimes rewarded with airdrops — but that is just airdrop farming (candidate 4) with extra infra work. Folded into #4.

### B.2 THE RANKING — by expected value for Ismail

| Rank | Path | Expected value for HIM | One-line reason |
|---|---|---|---|
| **1** | **Flash-loan arbitrage — the Curve route** | **Real, measured, immediate: +$5.63 per $5k loan, ~46 trades of runway on $1.31** | The only candidate with a verified live positive number, and the machine is already built |
| **2** | **Bug bounties / audit contests** | **$0 for the first months, then $800–$3,000/contest at intermediate; ceiling $20k per critical** | Highest ceiling of all $0 paths, and the skill is the audit his own bot needs before mainnet |
| **3** | **Solver — UniswapX filler on Base** | **Unproven; likely $0–$5/day early, flow was empty at probe** | Genuinely $0 and reuses everything he built, but no documented solo-filler income and thin flow |
| **4** | **Learn-to-earn / quests (quiz-based only)** | **$40–$150/month ceiling if you do everything; first dollar today** | Fastest first dollar, certain, tiny — pocket money, not a plan |
| **5** | **Testnet / airdrop farming** | **Median net $200–$1,500/year for 100–400 hrs; most testnets pay $0** | Lottery tickets that cost time; his $1.31 cannot do the mainnet farming that pays |
| **6** | **Grants** | **~$0 now (Gitcoin closed for builders); possible later once the bot is shipped** | Nothing to apply to today; watch, don't chase |
| **7** | **Referrals** | **~$0 (no trading audience)** | Real program, wrong audience |
| — | **Running infra for others (Lava/POKT)** | **Rejected — NOT $0 (stake + $200–500/mo node)** | Costs money to start; not a $0 path |

### B.3 THE SINGLE BEST $0 PATH — and the first concrete action

**Solver is NOT the best. Say it plainly: the best $0 path for Ismail is the one he already built — the flash-loan arbitrage bot on the Curve route — followed by audit contests as the skill-building second line, with the solver role as a third line.**

**The order to run them:**
1. **Now — Curve leg + fork test.** The +$5.63/$5k window is live and can die at any block. This is the first dollar, and it is the only candidate with a measured positive number.
2. **This week — start the audit-contest path.** Read 10 audit reports (Trail of Bits / OpenZeppelin published reports), do CodeHawks free practice (Cyfrin's beginner platform, XP only), then enter a live Code4rena contest as a warden. The skill pays twice: contest payouts + the audit his own contract needs.
3. **In parallel, $0 effort — the Base UniswapX order watcher.** Poll the free orders API, paper-fill for a week. If orders appear and fills are profitable, it becomes a second live line next to the arb bot.
4. **Dead time only — quiz-based learn-to-earn** (Binance Learn & Earn, CMC Earn, $1–$4/quiz, free) and 1–2 testnets. Never spend gas on on-chain quests with a $1.31 float.
5. **Do not spend on:** a paid RPC, a node, inventory, or any infra — until the log proves the bottleneck is speed or capital. Do not chase grants until the bot is shipped and documented.

**First concrete action (today): launch the Curve leg + fork test.** Everything else is second.

---

## SOURCES

**Repo (verified in `~/workspace/crypto-base-flashloan-bot/polygon/`):**
- `LOW_FEE_PROFIT_POLYGON.md` — fee ladder, Curve 4-leg route (+$5.63 @ $5k), Morpho balances, breakeven tables, gas measurements.
- `SOLVER_ZERO_DOLLAR_POLYGON.md` — solver roles detail (Atlas, CoW, 1inch, UniswapX, Across).
- `realtime_listener.py` / run logs — quote latency avg 355.7 ms, 1,200 blocks, 0 missed.
- `revert_protection.py` — pre-simulation, revert cost $0.0024 measured.

**Solver / routing / latency (Part A):**
- FastLane Atlas docs (docs.atlasevm.com) — solver contract, `atlasSolverCall`, `_borrow()` native flash loans, operations-relay WebSocket.
- FastLane Atlas blog — "No Free Reverts".
- arXiv 2510.14642v1 — Polygon PFL validator MEV auction, ~250 ms auction windows.
- CoW Protocol docs (docs.cow.fi) — solver rewards, VCG mechanism, β caps (50% ETH/Arb/Base/BNB, 100% Polygon/Gnosis/Avalanche/Linea/Ink/Plasma), global bound $20 equivalent, weekly (Tuesdays), 29 active solvers.
- 1inch Fusion FAQ (help.1inch.io) — gas refunds for resolvers only; delegation farms deprecated Nov 2026, new delegations closed 11 Nov 2026.
- UniswapX docs — Dutch auctions, `executeWithCallback`, RFQ quoters permissioned (chosen by Uniswap Labs), orders API `api.uniswap.org/v2/orders` (probed live 2026-11-25 ~06:25 UTC: `{"orders":[]}`).
- Xi & Moallemi (Columbia) — optimal routing shortfall 2.02 bp/trade, 2.98M WETH–USDC swaps on Ethereum.
- Alchemy pricing comparisons (chainpick.io, 2026) — paid entry tier ~$49/mo (plan names vary; verify on alchemy.com).
- Relay (relay.link) — 0% platform fee on token bridges + $0.02 execution cost.

**$0 landscape (Part B):**
- Code4rena 2023 data — dev.to "The bounty trap" (31,512 submissions, 114 audits, $4,823,059 paid, 1,323 of 10,000+ wardens earned, avg earning warden $3,646/yr).
- gigs.sh Code4rena agent guide (verified 2026-05-18) — $20M+ lifetime, top warden $1M+ cumulative, median warden $0/contest.
- jakeinsight.com "Bounty Income for Developers: Honest Numbers from 2026" — beginner $0–$500, intermediate $800–$3,000/contest, top 50 $5k–$15k/mo, top 10 $15k–$40k/mo.
- Immunefi research (via coinlaw.io / hoge.gg, 2026) — median critical $20,000, mean $114,355, $107.3M critical awards (Jan 2021–Feb 2026, 593 programs), $140M+ total paid, H1 2026 $13.45M across 837 reports.
- copytradeinsider.com "Airdrop Hunting for Beginners 2026" — median farmer net $200–$1,500/yr (100–400 hrs), $5,000 minimum practical capital, LayerZero Sybil cull 800,000 wallets, median qualifying wallet $500–$3,000 across the four biggest 2024 drops.
- altcoininvestor.com "Learn and Earn Crypto 2026" — realistic $40–$150/month across all platforms; on-chain quests $10–$60 with gas costs.
- decentralised.news "12 Ways to Earn Crypto for Free in 2026" — Galxe/Layer3 $1–$50/campaign, $50–$200/month for 2–5 campaigns/week.
- web3grant.com (checked Nov 2026) — Gitcoin no round since GG24 (closed 28 Oct 2025, ~$1.8M, max match $15k); no builder application open; 100 grant programs listed, 78 year-round.
- Lava Network docs (docs.lavanet.xyz) — providers stake LAVA, serve RPC, rewards from subscriptions + Provider Drops (44M LAVA / 4 years).

**Model assumptions (not sourced — labelled as such):** 5% APR opportunity cost for stable inventory; rebalance once/day; gas $0.0095 Polygon / $0.005 Base (repo-measured). Change the APR and the breakeven fills/day moves proportionally (at 10% APR, breakeven ≈ 4.7 fills/day; at 2% APR, ≈ 1 fill/day).

**Honest limits:** no source quantifies "X ms faster = Y% more wins" for Polygon solvers; no documented solo UniswapX filler income figure exists; airdrop and contest earnings are power-law distributed (median ≈ $0, mean dragged up by a few big winners) — plan on the median, not the mean.
