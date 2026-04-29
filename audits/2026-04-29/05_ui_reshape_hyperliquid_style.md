# UI Reshape v2 — Hyperliquid-styled Scaffolding — 2026-04-29

**Supersedes:** the IA proposal in `03_web_page_audit.md` (kept for the page-by-page audit; the IA is replaced).
**Premise:** mirror Hyperliquid's nav, layout, and visual language so users don't relearn anything. WAGMI's unique content (educational material, agent transparency, learning loops) becomes additive content under HL's structure, not a competing skeleton.

---

## Premise & Honest Limitations

I tried to fetch `app.hyperliquid.xyz`, `hyperliquid.xyz`, and the gitbook docs — all returned 403 (HL blocks automated fetchers). So this doc is built from:

- **My prior knowledge of HL's UX** (which is dated and approximate)
- **What's common across serious perp DEXes** (Hyperliquid, Aevo, dYdX, GMX, Drift)
- **Direct read of our current `web/src/theme.ts`** (which I can verify)

Anywhere I'm guessing about HL specifically, I'll mark with **[ASSUME]**. Please correct anything that doesn't match HL's current state — your knowledge of their app is fresher than mine.

The aesthetic rules in §2–§3 don't depend on HL specifics — they're general "trading-tool, not AI-tool" rules grounded in our code. Confidence is high there.

---

## §1 — The "AI Style" Problem (audit of `web/src/theme.ts`)

This is grounded in code I just read. Confidence: high.

The current theme has the visual fingerprints of "AI-generated dashboard" stamped all over it. Specific issues:

**Too many gradients.** `theme.ts` exports 11 gradient tokens including `prismatic`, `iridescent`, `aurora`, `celestial`, `mesh`. Real trading apps use 0–1 gradients (usually only on hero CTAs or charts). Hyperliquid uses essentially zero gradients in the trade interface.

**Too many "glass" variants.** `Glass` exports 7 variants: `card`, `nav`, `elevated`, `crystal`, `liquid`, `frosted`, `diamond`, `void`. They're all slight variations on `background: #0d0d14, border: 1px rgba(255,255,255,0.06)`. Glassmorphism is a 2021 design-system trend that screams "I asked Claude/ChatGPT for a UI." Trading tools use opaque solid surfaces.

**Too many glow tokens.** `S` (shadows) has `glow`, `bullGlow`, `bearGlow`, `brandGlow`, `ambient`, `innerLight`. Glows draw the eye toward decoration. Trading interfaces draw the eye toward *data*.

**Spring animations.** `M.spring` (`stiffness: 320, damping: 26`) and `M.bouncy` (`stiffness: 400, damping: 18`) are playful. Bouncy UI in a trading tool reads as toy-like. HL uses 100ms linear/ease-out fades, no springs.

**Wrong green.** Brand color is `#00cc88`. HL's brand is closer to `#1fa67a` or `#13e8b6` — more teal, less saturated. Our green is "Robinhood-bright"; HL's green is "Bloomberg-terminal-serious."

**Decorative decimals in font sizes.** `F.xs = 11, F.sm = 12, F.base = 13, F.md = 14`. Fine, but used inconsistently across pages — some headers are 36px (`F['4xl']`), some are 18 — the tower of sizes invites visual chaos. HL uses ~4 sizes total: 11/12 (data), 14 (default), 18 (section labels), 24 (page title).

**The result:** every page has cards-in-cards, glows, gradients, and bouncy hover effects. That's why it feels AI-generated — because it's the union of "every nice-looking visual effect Claude knows about." Hyperliquid is the opposite: it's *aggressively boring* on chrome and *aggressively dense* on data.

## §2 — Anti-AI Aesthetic Rules

These are the rules to apply across every page. They're independent of HL's specific layout — they're general "this is a serious trading tool" rules.

### Rule 1 — Two surface levels max

Backgrounds: `#040408` (page) and `#0a0a0f` (panel). That's it. No `card`, `cardHover`, `surface`, `surfaceHover`, `crystal`, `liquid`, `frosted`. Two values, used everywhere.

### Rule 2 — Borders, not shadows

Cards/panels use a `1px solid rgba(255,255,255,0.06)` border. **Zero box-shadows on UI chrome.** Shadows are reserved for modals/popovers only. Delete every glow token from `S`.

### Rule 3 — One accent, used sparingly

A single brand color. Use it for: positive numbers, primary CTAs, active nav state. **Nothing else.** Suggested: `#13e8b6` (cleaner, more HL-like) or keep `#00cc88` if you prefer it. Pick one and never use it for backgrounds, borders, or decorative effects.

### Rule 4 — Bull/Bear binary, no third color

Green for up/profit, red for down/loss. Both at high saturation only when applied to data values. Never use them for backgrounds. Drop `purple` and `info` from the palette — they're never needed in a perp trading UI.

### Rule 5 — Monospace everywhere a number lives

Every price, P&L, percentage, leverage, time, volume → `JetBrains Mono` or equivalent. Sans (Inter) for labels and prose only. The visual signature of "trading tool not dashboard" is that all your numbers line up vertically when stacked.

### Rule 6 — Animation: 120ms ease-out, that's it

Drop `M.spring` and `M.bouncy`. Single transition: `transition: all 120ms ease-out`. Hovers, modals, route transitions — same easing, same duration. Predictable = professional.

### Rule 7 — Information density

Default row height: 28–32px (HL is around 28). Default cell padding: 8px horizontal, 4px vertical. Right now most of our tables/cards have 16–24px padding which halves the data-per-screen. Trading users want maximum data per screen.

### Rule 8 — Typography scale: 4 sizes

- 11px — table data (mono), small labels
- 13px — default body, default form inputs
- 16px — section labels (uppercase, letter-spacing 0.05em)
- 22px — page title

That's it. Drop the `F['3xl']`, `F['4xl']` tokens. Hero numbers (equity, daily P&L) can be 32px on the dashboard but use that *once per page max*.

### Rule 9 — No emojis, no icons-as-decoration

Icons are functional only (sort arrows, close X, info ?, expand). No `🔥`, `✅`, `⚠️` in UI text. Status uses dot color + label, not emoji.

### Rule 10 — Numbers are right-aligned in tables, always

Every column of numbers is right-aligned. Labels are left-aligned. Mixed alignment is the #1 readability killer in trading UIs.

## §3 — Hyperliquid's Layout (my best understanding — please correct)

**[ASSUME]** marks anything I'm not certain about. If you can confirm or correct from your phone, I'll update.

### Top-level navigation

**[ASSUME]** HL's primary nav is a horizontal bar at top, left-justified, with these tabs:

- **Trade** — the orderbook/chart/order-entry page
- **Portfolio** — your positions, P&L, history, balances
- **Vaults** — copy-trading style vault deposits
- **Leaderboard** — top traders ranked
- **Stake** — HYPE staking
- **Referrals** — referral program
- **More** — overflow (docs, points, validators, etc.)

Right side of the bar: wallet connect, account chip, settings.

**Confidence:** Trade / Portfolio / Vaults / Leaderboard are almost certainly there. Stake / Referrals are very likely. Exact ordering and presence of "More" is **[ASSUME]**.

### Trade page layout (the hero page)

**[ASSUME]** Three-column layout:

- **Left rail (~260px):** asset selector at top (search + market tabs: Perps / Spot), then a list of all markets with last price + 24h change.
- **Center (~flex):** chart at top (TradingView-style, candlestick), tabs below the chart (Positions / Orders / TWAP / Fills / Funding History).
- **Right rail (~340px):** order entry — Market / Limit / Trigger tabs, leverage slider, size input, buy/sell buttons (green/red).

Bottom strip across full width: account summary (balance, margin used, unrealized P&L, buffer).

### Portfolio page layout

**[ASSUME]** Tabbed interface:

- **Overview** — summary stats, equity curve
- **Positions** — open positions table
- **Orders** — pending orders
- **History** — closed positions
- **Funding** — funding payments history
- **TWAP** — TWAP order history

### Visual conventions

- **Background:** very dark, near-black (`#0b0e11` or similar)
- **Panel:** slightly lighter (`#161a1f` ish), with a subtle border
- **Accent:** teal-green for positive / buy, salmon-red for negative / sell
- **Numbers:** monospace, right-aligned
- **Density:** very high — table rows are tight, lots of data above the fold
- **Animation:** minimal; sub-200ms transitions, no springs

## §4 — Mapping WAGMI Content onto HL Nav

The principle: **HL's nav stays exactly the same; our content fits inside it.** Educational and unique-to-WAGMI content lives in clearly-marked sections that don't interrupt the trading flow.

### Top-nav: HL structure + WAGMI additions (marked **[+]**)

```
Trade  |  Portfolio  |  Vaults  |  Leaderboard  |  Stake  |  Referrals  |  Bot [+]  |  Learn [+]  |  More
```

The two added tabs (`Bot`, `Learn`) are WAGMI's territory. Everything left of them mirrors HL exactly — **same labels, same order, same destinations as HL's app would render** (when not connected to a real wallet, these can be read-only or redirect to HL).

### Content mapping

#### `/trade` (mirrors HL Trade page)

Three-column layout with HL's exact structure. WAGMI additions show only when **the bot has an active opinion on the selected symbol**:

- **Left rail:** unchanged. Standard market list.
- **Center (under chart):** standard tabs (Positions / Orders / Fills / Funding) **+** one new tab `Bot Signal [+]` showing: WAGMI's current signal for this symbol (action, confidence, reasoning), agent pipeline status, last decision time. Hidden if no signal active.
- **Right rail:** unchanged order entry. **Below the buy/sell buttons:** a small inline panel showing WAGMI's "would the bot take this trade right now?" — single line: ✓ ALIGNED or ⚠ DISAGREES, click for detail. Tiny, non-intrusive.

This means the Trade page looks identical to HL on first glance, but the operator has access to WAGMI's view without leaving the page.

#### `/portfolio` (mirrors HL Portfolio)

Tabbed interface, HL-standard tabs first, WAGMI tabs at the end:

- **Overview** — summary stats + equity curve (replaces our scattered dashboard)
- **Positions** — open positions table
- **Orders** — pending orders
- **History** — closed positions (replaces our `forensics.tsx` landing)
- **Funding** — funding history
- **TWAP** — if applicable
- **Forensics [+]** — deep analytics (heatmaps, by-symbol, by-regime — what's currently in `forensics.tsx`/`results.tsx`/`performance.tsx`)
- **Counterfactuals [+]** — what we left on the table (current `counterfactuals.tsx`)

History tab is the canonical "your trades" view; Forensics is the "why" behind them. This matches HL's pattern of "scoreboard → drilldown" within Portfolio.

#### `/vaults` (mirrors HL Vaults — read-only for now)

Standard HL vaults list. WAGMI doesn't run a public vault yet, so this page can either:

- **(Phase 1)** redirect users to HL's vaults page, with a banner: "WAGMI doesn't run a vault. View Hyperliquid vaults [link]."
- **(Future)** when WAGMI runs a copy-trade vault, this page hosts it with HL-standard layout.

#### `/leaderboard` (mirrors HL Leaderboard — read-only)

Same pattern. Either pull HL's public leaderboard data via their API, or link out. WAGMI's bot can be ranked alongside human traders.

#### `/bot` **[+]** (the WAGMI-specific page; this is where unique content concentrates)

Subtabs:

- **Live** — current state (bot online/offline, recent decisions, open signals across all symbols)
- **Decisions** — the "Decision Theater" feed (current `ai-decisions.tsx`)
- **Agents** — per-agent calibration & cost (current `agent-intelligence.tsx` + `llm-audit.tsx` merged)
- **Strategies** — strategy fleet status (current `strategies/`)
- **Sniper** — sniper hot list, queue, history (extracted from `copy-trade.tsx`)
- **Backtest** — backtest runner + results (current `backtest.tsx` + `results.tsx`)

This is where the "magic" of WAGMI lives. By keeping it under one top-nav tab, the trading flow (Trade / Portfolio) stays uncluttered and HL-familiar; the AI/research depth is one click away when wanted.

#### `/learn` **[+]** (educational content)

MDX-driven, separate visual treatment (slightly more "blog-like" — wider columns, larger type, less density). Sections:

- **Getting Started** — how the bot works, how to read signals
- **Strategies** — explained per strategy
- **Glossary** — terms
- **Masterclass** — the structured course (current `masterclass.tsx` content)
- **Methodology** — thesis, risk frameworks (current `thesis.tsx`)

Visually distinct enough that users know "you're now in the docs zone, not the trading zone." But still uses the same color palette and typography rules — just looser density.

## §5 — What Gets Recycled, What Gets Killed

Mapping each of the 18 current pages to its destination in the new structure:

| Current page | Becomes | Notes |
|---|---|---|
| `index.tsx` | `/trade` (default symbol) | Replace with HL-style trade page; landing collapses into trade |
| `dashboard.tsx` | `/portfolio` Overview tab | Most stat tiles fold into HL-style portfolio summary |
| `signals.tsx` | `/trade` center column ("Bot Signal" tab) + `/bot/live` | Split: per-symbol view in trade, system-wide view in bot |
| `ai-decisions.tsx` | `/bot/decisions` | Recycled wholesale, restyled |
| `agent-intelligence.tsx` | `/bot/agents` | Merged with llm-audit |
| `llm-audit.tsx` | `/bot/agents` | Merged in |
| `reasoning.tsx` | `/bot/decisions/[id]` | Drilldown route |
| `forensics.tsx` | `/portfolio/forensics` (subtab) | Recycle charts, restyle |
| `results.tsx` | `/bot/backtest/results/[id]` | Backtest results land here |
| `performance.tsx` | `/portfolio` Overview | Top-level stats fold up |
| `backtest.tsx` | `/bot/backtest` | Form + queue; results redirect |
| `copy-trade.tsx` | `/bot/sniper` + `/learn/copy-trading` | Split: sniper UI is sniper, doc is doc |
| `counterfactuals.tsx` | `/portfolio/counterfactuals` (subtab) | Recycled |
| `portfolio.tsx` | `/portfolio` Overview + Positions | Already named correctly, restructured |
| `thesis.tsx` | `/learn/methodology` | Educational content |
| `masterclass.tsx` | `/learn/masterclass` | MDX-migrated |
| `learn.tsx` | `/learn/getting-started` | MDX-migrated |
| `strategies/index.tsx` | `/bot/strategies` | Recycled |
| `strategies/[id].tsx` | `/bot/strategies/[id]` | Recycled |

**Net structural change:** 18 flat pages → 6 nav sections (Trade / Portfolio / Vaults / Leaderboard / Bot / Learn) with subroutes. Familiar to HL users; depth available for power users.

**Content preserved:** ~95%. Almost nothing gets killed — just relocated and restyled.

**Content killed:**
- The marketing-style hero on the current `index.tsx` (replaced by trade page as landing)
- Duplicate analytics across forensics/results/performance (consolidated under portfolio/forensics)
- Decorative animations, gradients, glass effects (replaced by trading-tool restraint)

## §6 — Implementation Sequence

Each phase is independently shippable. Stop anywhere and the app still works, just less complete.

### Phase 0 — Confirm assumptions (15 min, conversation)

Open HL on your phone, send me 3–5 screenshots:

1. The top nav bar (full width, including right-side wallet/settings)
2. The Trade page with all three columns visible
3. The Portfolio tabs (the row of tab labels)
4. One section of the Trade page where data density is highest (so I can tune our row heights to match)
5. Any color values you can identify (especially the exact green and red)

With these, I'll lock down the exact structure and replace **[ASSUME]** notes with verified specs. **Until this is done, anything below is provisional.**

### Phase 1 — Theme replacement (2 hours, all in `web/src/theme.ts`)

Replace the current sprawling theme with a 50-line minimalist version:

- 2 background colors, 1 panel color, 1 border color
- 1 brand color, 1 bull, 1 bear
- 4 type sizes
- 1 transition (`120ms ease-out`)
- 1 border-radius scale (4 / 6 / 8 — drop pill)
- Delete: `Glass` (all variants), gradients beyond `brand`, all "glow" shadows, spring/bouncy motion

This is mostly a deletion exercise. Every page imports from `theme.ts`, so changes propagate. Some pages may visually break — that's the goal; we'll fix them in Phase 3.

### Phase 2 — New `Layout.tsx` with HL-style top nav (3 hours)

Build the chrome:

- Horizontal top nav, fixed height (~52px), logo left, primary tabs center, wallet/settings right
- Tabs: Trade / Portfolio / Vaults / Leaderboard / Bot / Learn
- Active tab indicator: 2px green underline, no background change
- Right side: equity strip (auto-updating), bot status dot (online/offline), settings menu

Drop the current `Sidebar.tsx`. HL doesn't use a sidebar at the top level. Sidebars only appear within Trade page (left rail = market list).

### Phase 3 — Build `/trade` (HL-style) (8 hours)

The flagship page. Three columns. Even if data isn't perfectly wired, the layout shipping correctly is what makes the whole app feel right.

- Left rail: market list (pulled from `/v1/strategies` or `/v1/signals`)
- Center: chart widget (reuse Lightweight Charts from current `signals.tsx`) + tabs underneath (Positions / Orders / Bot Signal)
- Right rail: order entry form (read-only / paper mode for now)

When this page works, the app's identity is set.

### Phase 4 — `/portfolio` rebuild (6 hours)

Tabbed: Overview / Positions / Orders / History / Forensics / Counterfactuals.

Recycle existing components from `dashboard.tsx`, `forensics.tsx`, `results.tsx`, `counterfactuals.tsx`. Mostly a re-arrangement, not a rewrite. Restyle to new theme tokens.

### Phase 5 — `/bot/*` section (10 hours)

Six subtabs: Live / Decisions / Agents / Strategies / Sniper / Backtest.

Each is a recycled existing page restyled. Live is new and small (recent decisions feed across all symbols).

### Phase 6 — `/learn/*` MDX migration (5 hours)

Convert `learn.tsx` and `masterclass.tsx` to MDX. Phone-editable via GitHub web after.

### Phase 7 — `/vaults`, `/leaderboard` placeholders (1 hour)

Read-only redirect pages until WAGMI has its own vault. Branded "Powered by Hyperliquid" with link out.

### Phase 8 — Polish + mobile pass (ongoing)

Full audit on actual phone. Trade page collapses to single column on mobile (chart hides, order entry full-width). Portfolio tabs become dropdown. Standard responsive patterns.

---

## Total scope estimate

~36 hours of focused work to take the app from "AI-styled, sprawling" to "HL-clone with WAGMI superpowers." Roughly a week of evening sessions if done incrementally.

**Most valuable single chunk:** Phase 1 (theme replacement, 2h). Even before any layout changes, replacing the theme tokens makes every existing page feel less AI-generated.

**Lowest-risk start:** Phase 0 (confirm via screenshots) — pure conversation, no commits.


