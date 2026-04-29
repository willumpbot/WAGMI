# Web Page Audit — 2026-04-29 (§2 of UI Reshape)

**Purpose:** scroll-and-react document. For each of the 18 pages, four things:
- **Is** — what the page currently shows
- **Should** — what it should show post-reshape
- **Broken** — what's stale, hallucinated, or misleading
- **Verdict** — keep / merge / split / kill / rebuild

**Scale check before we start:** 18 pages, ~38,000 lines of TSX. Largest pages are `learn.tsx` (4,086 lines), `signals.tsx` (3,609), `results.tsx` (3,589), `forensics.tsx` (3,477), `backtest.tsx` (3,393). **No Next.js page should be over ~500 lines in healthy app.** These are doing the work of 6–8 components each. The reshape is going to involve breaking pages apart, not just renaming brand.

---

## Batch 1 — Core landing & live decision pages (5 of 18)

### 1. `index.tsx` — Landing / homepage (1,286 lines)

- **Is:** marketing-style landing with `StatCard` metrics (equity, win rate, P&L, sharpe, drawdown, etc.), `LiveActivityTape`, `MarketPulse`, `AgentBrainGraphic`, `ProofStrip`, `ReasoningTeaser`, `SystemStatus`. Calls `/v1/summary`, `/v1/trades/history`, `/v1/trades/equity-curve`, `/v1/llm/market-view` via `useApi` hook.
- **Should:** **two distinct things, currently fused.** (a) a public marketing/landing page for someone who has never seen WAGMI, and (b) a "what's the bot doing right now" snapshot for the operator. Right now it tries to do both and is too long for either.
- **Broken:** 1,286 lines for a landing page is excessive. Logic for trade normalization, summary stat derivation, sparkline computation is inlined. Should be ~150 lines using composed components.
- **Verdict:** **SPLIT.** New `index.tsx` (public, ~200 lines, story + 3-stat hero + CTA) and existing logic moves to `dashboard.tsx`. If you don't want a public landing, just kill this and route `/` to `/dashboard`.

### 2. `dashboard.tsx` — Operator's main view (863 lines)

- **Is:** stat tiles (equity, P&L, WR, positions), positions list (`PositionCard`), strategies summary, `SignalFunnel`, `DecisionTrail`, `AgentHealthStrip`, `LiveActivityTape`, `SniperAlerts`, time-range selector (7D/30D/90D/ALL).
- **Should:** **the one page you check first.** "Is the bot OK? What's it holding? What just decided?" Single-screen if possible. Everything else is a click away.
- **Broken:** still 863 lines but more reasonable than peers. Time-range filter likely does client-side slicing of full equity curve, which breaks at scale. Doesn't show the "bot offline 140h" health state prominently — that's currently buried in alerts.
- **Verdict:** **KEEP, refactor.** Promote bot-health (online/offline, last activity, consecutive losses, circuit breaker state) to top of page. Currently you can't tell at a glance whether the bot is even running.

### 3. `signals.tsx` — Live signal stream (3,609 lines)

- **Is:** OHLCV chart per symbol, live signals feed, activity feed, market view, lightweight charts integration. Calls `/v1/ohlcv`, `/v1/activity/feed`, `/v1/llm/market-view`, `/v1/signals`.
- **Should:** "what is the bot seeing in the market right now, and what would it (or did it) do about it." Should be the most live / WebSocket-friendly page.
- **Broken:** 3,609 lines is absurd for a single page. Almost certainly contains: chart widget, signal table, filter bar, detail drawer, several inline sub-components. Each should be its own file. Polling-based (`fetch` with intervals) — should be SSE/WS for live data.
- **Verdict:** **SPLIT into 4–5 files.** `pages/signals.tsx` (~200 lines, layout + state), `components/signals/SignalChart.tsx`, `SignalFeed.tsx`, `SignalDetailDrawer.tsx`, `SignalFilterBar.tsx`. Eventual move to WebSocket subscription via `/v1/signals/stream`.

### 4. `ai-decisions.tsx` — Decision Theater (1,437 lines)

- **Is:** explicitly described in file header as "the flagship differentiator: real-time transparent AI reasoning stream." Shows every LLM decision with full 9-agent pipeline (Regime→Trade→Risk→Critic), veto analysis, confidence grading, model routing.
- **Should:** stay as the marquee "show your work" page — but with a clearer hierarchy: latest decision (hero) → recent decisions (feed) → analytics (veto reasons, model routing, confidence calibration). Right now the analytics blur with the feed.
- **Broken:** docstring claims it shows "real-time" but data is fetched on mount (no polling visible in scan). Naming overlap with `llm-audit.tsx` and `reasoning.tsx` — **three pages for "what the LLM did"** with unclear boundaries.
- **Verdict:** **KEEP as canonical "decision feed" page.** Merge in `reasoning.tsx` (which is just 308 lines and has overlapping intent). Move analytics tiles to `llm-audit.tsx`.

### 5. `agent-intelligence.tsx` — Agent details (530 lines)

- **Is:** per-agent calibration, accuracy, decision counts, model used. Agent-level performance scoreboard.
- **Should:** "for each of the 9 agents: how is this agent doing." Calibration curves, accuracy over time, model cost, recent disagreements with peers.
- **Broken:** 530 lines is reasonable. But this page has **massive overlap with `llm-audit.tsx`** (which does similar "how is the LLM doing" analysis but at system level). Boundary needs to be: agent-intelligence = per-agent micro view; llm-audit = aggregate macro view.
- **Verdict:** **KEEP, sharpen scope.** Make this page strictly per-agent. No system-level aggregates. Each agent gets a card with: role, model, decision count (24h/7d), accuracy, calibration curve, top 3 recent decisions. Click → drilldown.

## Batch 2 — Analysis & tools (5 of 18)

### 6. `llm-audit.tsx` — LLM macro analytics (1,634 lines)

- **Is:** trigger breakdown, model routing distribution, confidence calibration curves, veto analysis, decision time-of-day heatmaps. Calls `/v1/llm/feed?limit=200`.
- **Should:** "is the LLM system as a whole pulling its weight, what is it costing, where is it well- vs. poorly-calibrated." Cost-attribution focus.
- **Broken:** 1,634 lines for an analytics page is heavy but defensible. Major risk: only fetches 200 records → calibration math on small samples is misleading. Need pagination or aggregation server-side.
- **Verdict:** **KEEP as canonical "LLM macro" view.** Add: total cost (today / 7d / 30d), per-trigger ROI (did Pre-Trade calls earn back their token cost?), per-model accuracy. Currently emphasis is on "how many calls" not "did they pay off."

### 7. `reasoning.tsx` — Agent reasoning view (308 lines)

- **Is:** smaller, more focused page for individual decision walkthroughs. 308 lines.
- **Should:** ideally a *drilldown destination* from `ai-decisions`, not a top-level nav item.
- **Broken:** unclear differentiation from `ai-decisions.tsx`. Three pages (`ai-decisions`, `agent-intelligence`, `reasoning`) all talk about "the LLM/agents." Users won't know which to click.
- **Verdict:** **MERGE into `ai-decisions` as a drilldown route** (e.g., `/ai-decisions/[decisionId]`). Drop the top-level nav entry. Saves a confusing nav slot.

### 8. `forensics.tsx` — Trade forensics (3,477 lines)

- **Is:** confidence ring widgets, scatter plot of confidence vs R:R achieved, signal quality funnel, hour-of-day win rate heatmap, trade clusters, exit timing heatmap, cumulative P&L journey, day-of-week / hour-of-day matrix. Pulls `/v1/trades/history?limit=500`. Has its own inline `linearRegression` helper.
- **Should:** the deep "why are we winning/losing" analyst page. Charts that answer specific questions: do we lose more in chop? Is confidence calibration drifting? Are exits too early/late?
- **Broken:** 3,477 lines. **Massive overlap with `results.tsx` (3,589 lines) and `performance.tsx` (2,960 lines).** Three pages all showing trade analytics with different chart selections. Inline regression math should be a util.
- **Verdict:** **MERGE forensics + results + performance into a single `/analytics` section** with subroutes: `/analytics/equity`, `/analytics/heatmaps`, `/analytics/exits`, `/analytics/funnel`. ~9,000 lines becomes ~3,000.

### 9. `results.tsx` — Backtest results display (3,589 lines)

- **Is:** equity curve, exit type timeline, by-symbol breakdown, P&L distribution, daily P&L calendar, weekly performance by symbol. Pulls `/v1/backtest/results/latest`, `/v1/trades/equity-curve?run=latest`, `/v1/trades/history?limit=200`.
- **Should:** "after a backtest run, here's the full diagnostic." The output destination of the backtest tool.
- **Broken:** name is generic — could mean live results or backtest results. Currently does both, ambiguously. Same data shape as `forensics.tsx` for many charts.
- **Verdict:** **MERGE into `/analytics`** (see above). Clearly distinguish backtest data vs. live data via tabs or banner. Right now you can't tell what dataset you're looking at — exactly the bug we hit earlier with "trades_10d.csv looks like live data, is actually backtest."

### 10. `performance.tsx` — Performance analytics (2,960 lines)

- **Is:** performance metrics, sharpe, drawdown, distributions, more analytics.
- **Should:** likely the "executive summary" of analytics — top-level KPIs, sparklines, traffic-light health.
- **Broken:** 2,960 lines and the third "trade analytics" page after forensics + results. Section headers were empty in the scan, suggesting it's a lot of inlined components without strong section structure.
- **Verdict:** **MERGE into `/analytics` as the "summary" subroute.** Keep this as the at-a-glance "is the bot making money" page; deeper drill-downs go to forensics/results equivalents.

## Batch 3 — Tools, portfolio, content (5 of 18)

### 11. `backtest.tsx` — Run/manage backtests (3,393 lines)

- **Is:** backtest configuration form, job submission (POST `/v1/backtest/run`), polling for status (`/v1/backtest/status/{id}`), result loading (`/v1/backtest/results`, `/v1/backtest/results/{id}`), comparison between runs, "Strategy Alpha Contribution" and "Monte Carlo Fan" charts.
- **Should:** "configure → run → compare." The operator's experimentation surface. Clear separation between "run a new backtest" (form-heavy) and "browse past backtests" (table + drill).
- **Broken:** 3,393 lines mixes form, job runner, results table, comparison view, and chart in one file. The "run/manage" half should be its own page; the "view results" half should redirect to `/analytics` once a run completes.
- **Verdict:** **SPLIT.** New `/backtest` (~400 lines, form + job table + comparison launcher). Results display lives in `/analytics?run=<id>`. Avoids duplicating chart logic between this page and results.tsx.

### 12. `copy-trade.tsx` — Copy trading (2,796 lines)

- **Is:** OHLCV charts, signals, market view, activity feed, sniper journal. Calls **7 endpoints** including `/api/sniper` (note the prefix mismatch — `/api` vs the `/v1` prefix the rest of the app uses).
- **Should:** the "follow the bot's trades elsewhere" surface — for users running their own copy of the strategy or signals into another exchange.
- **Broken:** 2,796 lines, 7 endpoints, mixed prefix conventions (`/v1/...` and `/api/...`). High likelihood this overlaps with `signals.tsx` (also charts + signals). Sniper-specific UI buried inside; if sniper is being re-enabled per blueprint §3.5, sniper deserves its own page or top-level surface.
- **Verdict:** **SPLIT.** Extract sniper into `/sniper` (~500 lines: hot-list, recent fires, journal, controls). Slim copy-trade to "share/export bot signals to other exchanges or webhooks" (~600 lines). Delete duplicate chart logic; reuse from `signals.tsx`.

### 13. `portfolio.tsx` — Portfolio view (1,746 lines)

- **Is:** portfolio metrics, position breakdown, exposure analytics. Section headers empty in scan — likely heavy inline JSX.
- **Should:** "what am I holding right now, what's the risk." Real-time positions + open exposure + correlation + sector caps.
- **Broken:** 1,746 lines. Likely overlaps with the dashboard's positions tile. If the bot only ever runs ~3 symbols, portfolio is overkill — a position list with risk annotations on the dashboard is enough.
- **Verdict:** **MERGE into `dashboard.tsx`** as a "Portfolio Detail" expandable section. OR, if you want it standalone: keep it but make it the "exposure / correlation / risk" page only — kick basic position list back to dashboard.

### 14. `counterfactuals.tsx` — Counterfactual analysis (429 lines)

- **Is:** displays counterfactual scenarios — "what if you had exited at TP1, taken the veto'd trade, etc." Shows the deltas computed by `bot/data/counterfactuals/scenarios.json`.
- **Should:** **the killer page that surfaces "what we left on the table."** Currently 429 lines = small, focused. Per the §7.1 audit, this data shows +$477 of TP1 underweighting — we should be using this view to drive policy changes.
- **Broken:** unclear if it shows aggregate insights or just a list. Probably under-used — you're sitting on real edge data and the page doesn't scream it.
- **Verdict:** **KEEP, level up.** Add aggregate hero stat ("Counterfactuals say: +$477 left on table this period from TP1 underweighting"). Sortable by delta. Filter by scenario type (exit_timing, veto_override). One-click "promote to rule" if pattern is significant.

### 15. `thesis.tsx` — Live thesis page (486 lines)

- **Is:** "Charts" + "X / Twitter Thread" sections. Calls `/v1/thesis/{symbol}/thread` POST. Likely a page that generates social-media-shareable thesis content.
- **Should:** clear if it's a public-facing artifact or operator tool. Currently ambiguous.
- **Broken:** thesis-thread generation feels like a marketing/social tool stuck in the trading dashboard. Different audience.
- **Verdict:** **DECIDE: keep or kill.** If you actively use this for X posting, keep it but move under a "/share" or "/social" subroute. If not, kill — the time saved maintaining it is worth more than the page.

## Batch 4 — Education content + strategies (3 of 18)

### 16. `learn.tsx` — Education content (4,086 lines)

- **Is:** the **biggest page in the app at 4,086 lines / 205KB.** Heading sections include: "What Is This Bot? / Understanding Signals / The LLM Multi-Agent System / Risk Management / How a Trade Flows / Trading Calculators / How to Copy-Trade This Bot / Glossary." Pure static content with `AccordionCard` UI. No API calls.
- **Should:** education for first-time users. Should make someone go from "what is this" to "I trust the bot enough to follow it" in 10 minutes.
- **Broken:** **4,086 lines of static content in one TSX file is an editorial / loading nightmare.** Every word change requires a Next build. Updating one section means scrolling 1,000+ lines. Should be Markdown-driven.
- **Verdict:** **MIGRATE to MDX.** Each top-level section becomes a `.mdx` file under `content/learn/`. The `learn.tsx` page becomes a layout that lists + renders MDX. Massive editing UX win. ~50× faster to update copy. Lets you write/edit on phone via GitHub web editor.

### 17. `masterclass.tsx` — Masterclass / curriculum (1,531 lines)

- **Is:** "Knowledge Check Quiz / Your Learning Journey / Bull Market Analysis / Core Concepts / Strategies / What Makes This Program Different." Static educational content with a quiz mechanic. Title says "Nunu's Masterclass."
- **Should:** clear if this is a paid product, lead magnet, or just the "deep dive" version of `/learn`. Currently overlaps with `/learn` heavily.
- **Broken:** unclear differentiation from `learn.tsx`. Two separate static-content pages totaling **5,617 lines** for educational content alone. Either one is the curriculum (course-shaped) and the other is the reference (glossary-shaped), or they're competing versions of the same idea.
- **Verdict:** **CONSOLIDATE with `/learn`.** Either: (a) `/learn` = reference/docs, `/masterclass` = course (with progression, quizzes, completion), and they MDX-share components; or (b) merge entirely. Don't keep both as static React.

### 18. `strategies/index.tsx` + `strategies/[id].tsx` — Strategies catalog

- **Is:** index lists all 23 strategies; `[id]` shows per-strategy detail. Subroute structure is correct (only place in the app using subroutes).
- **Should:** "for each strategy: what is it, how is it doing, when does it fire, what's its weight in the ensemble." This is genuinely useful — strategies are the bot's asset inventory.
- **Broken:** unknown line count from scan but likely fine. Real risk: strategy data may be stale / hardcoded — needs live data from `/v1/strategies` (which `bot/api_server.py` provides).
- **Verdict:** **KEEP, verify wiring.** Confirm live data from `/v1/strategies` (active, weight, recent performance, last fire time). Add ability to drill into per-strategy trades, recent fire/skip examples, and ensemble vote share over time. This is your "strategy fleet readiness board."

---

## Cross-page issues found across the audit

1. **Page bloat is systemic.** 6 of 18 pages exceed 2,500 lines. None should. Indicates components are inlined per-page rather than extracted to `components/`. The audit's #1 reshape recommendation is **extract first, redesign second.**

2. **Three pages are "the LLM/agents page" (`ai-decisions`, `agent-intelligence`, `reasoning`).** Need a clean split: feed (decisions over time), per-agent (calibration drilldown), system audit (cost/ROI). Currently overlapping.

3. **Three pages are "the analytics page" (`forensics`, `results`, `performance`).** ~10,000 lines total. Should be ONE `/analytics` section with subroutes.

4. **Two pages are "the education page" (`learn`, `masterclass`).** ~5,600 lines of static React. Should be MDX.

5. **Backtest data and live data are visually indistinguishable** in `results.tsx`. This is the bug pattern that bit us today (trades_10d.csv mistaken for live). Every page that displays trades needs an explicit "Source: Backtest run X" or "Source: Live paper trading" banner.

6. **API prefix inconsistency:** most calls use `/v1/...`, but `copy-trade.tsx` calls `/api/sniper` and `/api/sniper/journal`. One of those prefixes is wrong or both are valid against different backends — needs reconciliation.

7. **Polling everywhere, no real-time.** Pages that should be real-time (signals, ai-decisions, dashboard) all use `fetch()` with intervals. Server-Sent Events (SSE) or WebSockets would massively improve UX and reduce backend load.

8. **No source-of-truth indicator.** No page tells you: "Bot status: ONLINE / OFFLINE 140h", "Last decision: 5 min ago / 6 days ago", "Data source: live / backtest." This is the single most important UX upgrade — a global health strip across the top of every page.

---

## Proposed Information Architecture (post-reshape)

**6 sections × roughly 12 pages total**, down from 18 sprawling pages.

```
/                          → Public landing (200 lines, story + CTA, optional)
/dashboard                 → Operator's home: "is the bot OK?"
                              ├ Bot health strip (online/offline, last decision, equity)
                              ├ Open positions
                              ├ Recent decisions (last 5)
                              └ Today's P&L

/signals                   → Live signals + chart
                              └ /signals/:symbol  (deep view per symbol)

/decisions                 → "Decision Theater" (current ai-decisions, polished)
                              └ /decisions/:id  (per-decision drilldown — absorbs reasoning.tsx)

/analytics                 → Trade & system analytics (replaces forensics/results/performance)
                              ├ /analytics                 — summary KPIs (was performance.tsx)
                              ├ /analytics/equity          — equity curve, drawdown
                              ├ /analytics/heatmaps        — hour-of-day, day-of-week, regime grids
                              ├ /analytics/funnel          — signal → trade conversion
                              ├ /analytics/exits           — exit-timing, counterfactuals
                              └ /analytics/by-strategy     — per-strategy contribution

/agents                    → Agent system view (replaces agent-intelligence + llm-audit)
                              ├ /agents                    — system overview, cost, calibration
                              └ /agents/:role              — per-agent drilldown

/strategies                → Strategy fleet
                              ├ /strategies                — list with live weights & performance
                              └ /strategies/:id            — per-strategy detail (existing)

/sniper                    → Sniper-specific (extracted from copy-trade)
                              ├ Hot list
                              ├ Recent fires
                              ├ Journal
                              └ Controls (enable/disable, leverage cap, per-trade ceiling)

/backtest                  → Backtest runner (form + queue + comparison launcher)
                              └ Results redirect to /analytics?run=<id> with "Source: Backtest" banner

/learn                     → MDX-driven education + reference
/masterclass               → MDX-driven course (if kept distinct)

/share                     → Optional: thesis threads, social-export tools
```

**Pages eliminated entirely or merged:**
- `index.tsx` — collapses to public landing or routes to `/dashboard`
- `forensics.tsx`, `results.tsx`, `performance.tsx` → `/analytics/*`
- `reasoning.tsx` → `/decisions/:id`
- `portfolio.tsx` → expanded section on `/dashboard`
- `copy-trade.tsx` → split: sniper UI to `/sniper`, sharing to `/share`

**Net:** ~18 pages → ~12 pages. ~38,000 lines → est. ~12,000 lines after component extraction. **Editing experience improves dramatically when the average page is 300–500 lines, not 3,000.**

---

## Recommended Sequence (phone-friendly, in order of payoff)

Each step is a separate phase. Do them in order; each leaves the app working.

### Phase 1 — Brand + Health Strip (1–2 hours, mostly text)

1. Find/replace `CrazyOnSol` → `WAGMI`, `nunuIRL` → `WAGMI` across `web/`. Update brand colors if needed.
2. Add a global `<HealthStrip />` component in `Layout.tsx` showing: bot status (online/offline + last activity timestamp), current equity, today's P&L, open positions count, "Source: LIVE" or "Source: BACKTEST" tag.
3. Add a `<DataSourceBanner />` to every page that displays trade data, explicit about whether it's live or backtest.

This phase alone makes the app feel current. Phone-doable.

### Phase 2 — Kill the duplicates (4–6 hours)

4. Merge `reasoning.tsx` into `ai-decisions.tsx` as `/decisions/:id` route.
5. Decide thesis page: keep at `/share/thesis` or kill.
6. Decide masterclass: merge with learn or differentiate course-vs-reference.

Each of these is a ~1-hour task and reduces nav clutter immediately.

### Phase 3 — The big extraction (10–15 hours, do at desktop)

7. Extract per-page inline components → `web/components/{page}/`. This is mechanical refactor — split each 3,000-line page into ~6-8 components.
8. Build the `/analytics/*` subroute structure. Move charts from forensics/results/performance into appropriate analytics subroutes.
9. Build `/sniper` from extracted copy-trade content.

Pure desktop work. 1–2 days at most.

### Phase 4 — MDX migration (4–6 hours)

10. Install `@next/mdx`. Convert `learn.tsx` and `masterclass.tsx` content to `.mdx` files. Page becomes a layout/listing.

This is the biggest editing-experience win. Once done, you can update copy from your phone via GitHub web editor.

### Phase 5 — Real-time (8–12 hours, depends on backend choice)

11. Pick backend (see infrastructure plan), add SSE endpoints for `/v1/signals/stream`, `/v1/decisions/stream`, `/v1/positions/stream`.
12. Frontend swaps `fetch` polling for `EventSource` subscriptions on signals, ai-decisions, dashboard.

This is the "feels alive" upgrade. Requires backend work, so blocked on infrastructure decisions.

### Phase 6 — Polish (ongoing)

13. Loading skeletons, error boundaries, empty states.
14. Mobile responsive audit on every page.
15. Performance (bundle size, lazy-load chart libraries).

---

## What this audit doesn't cover (yet)

- **Backend reconciliation** — need a parallel audit of `bot/api_server.py` vs `api/app/` vs `bot/dashboard/server.py` to decide which backend(s) survive. That's the next document. Without resolving this, frontend can't be re-wired cleanly.
- **Component-level audit** — `web/components/` has 24 files; need to identify duplicates and consolidate. Best done during Phase 3 extraction.
- **Authentication / multi-user** — currently no auth visible. If WAGMI is being shipped as a product (per the masterclass + thesis pages), auth is a must-have. Out of scope for this audit.
- **Mobile-first redesign** — the entire app reads as desktop-first. A separate audit pass on every page from a phone would surface dozens of issues.

---

*End of audit. The infrastructure reshape plan and backend audit follow in `04_infrastructure_reshape_plan.md`.*

