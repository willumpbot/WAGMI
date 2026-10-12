# PREREG: re-calls, x-alerts, scale-in, runner slice (Syndicate 2.0)

Written 2026-10-11 BEFORE any entry/exit was joined to a price outcome. Only event counts were looked at
(334 CAs; 297 with a human call; 29 with >=2 distinct human callers, C2 delays 0h..389h; 36 bot "5x" first-alerts;
the bot posts NO 2x alerts, lowest 🔥 tier is 5x).

## Universe and events
- Rows: history_calls.jsonl, chat contains "Syndicate", 2026-08-24 -> 2026-10-08. Human = sender not ending in "bot".
- C1 = first human message with the CA. C2 = first message from a 2nd distinct human. Bot-only coins (37) are out of
  (a)(c)(d); they can enter (b).
- 5X = first 🔥 alert by @Phanes_bot for the CA with multiplier >= 5 (alert time).
- SYN2X (substitute for the non-existent 2x alert): first bar after C1 whose CLOSE >= 2x the C1 entry; buy at that close.
- Pool: caller_grade.py pool choice at the CA's first call. Bars: GeckoTerminal minute where cached/fetched, else hourly.

## Entry / exit mechanics
- Entry at event t: close of the first minute bar starting >= floor(t, 1min) if within 60 min; else open of the first
  hourly bar starting >= t if within 60 min. No trade within 60 min after t (or no pool) = DEAD = -100%, never dropped.
- Exits evaluated on bar OHLC. Same-bar ambiguity resolved pessimistically (stop before target).
- Horizon end beyond the last available bar (calls near data end): marked at last close, flagged and counted.
- Costs (round trip, subtracted from each tranche in % of its stake): 3% if Phanes card LP (latest card at or before the
  entry) >= $50K, else 8%; no card -> 8%. Dead = -100% (no extra cost).

## Tests (primary metric first)
(a) RE-CALL. Coins with C2 within 96h of C1 (primary; all horizons stay inside cached C1+7d hourly). Outcomes at H=72h after
    entry: net return (mean, median) and P(touch 2x before 0.5x). Comparisons:
    a1 paired: C2-entry vs C1-entry, same coins.
    a2 control: C2-entry vs time-matched entry on NON-re-called coins (1 human caller) at their C1 + d (d = that coin's
    C2 delay); control value = mean over all eligible controls ALIVE at C1+d. Secondary: deads counted as -100%;
    run-up matched (control price at C1+d / its C1 entry in the same bucket <1x, 1-2x, >=2x as the re-called coin).
    Secondary: 7d horizon for a1 (extension fetch); delays > 96h reported descriptively.
(b) X-ALERT entries 5X and SYN2X: P(touch +100% (2x entry) within 7d), P(-50% touched first), mean/median 7d net.
    Reference = same probabilities from C1 entries.
(c) SCALE-IN vs ALL-IN at C1: 1/3 at C1; 1/3 limit-buy at 0.6 x running high since C1 (first touch within 7d, fill at
    min(open, level)) or skip (cash 0%); 1/3 at C2 if within 7d, else skip. All tranches marked at C1+7d close.
    Metric: return per unit of budget (skips earn 0); also per unit deployed.
(d) EXITS from C1 entry, 7d: HOLD (7d close); ALL@1.5x, ALL@2x (limit sell at target, else 7d close; no stop);
    SLICE@1.5x, SLICE@2x (75% at target; 25% runner exits at 0.5 x peak-since-entry, peak includes the current bar's
    high (pessimistic), fill min(open, level), else 7d close). Report mean, median, share of gross profit from top 5% /
    top 1% calls, and how many of the top-10 runners (by 7d peak/C1 entry) each rule still held at the peak bar.

## Split, inference, multiplicity
- Discovery: event day (C1 for a/c/d, alert for b) before 2026-09-20 00:00 UTC; holdout on/after.
- Day-clustered bootstrap (resample UTC days of the event), 5000 reps, 95% percentile CIs.
- 15 primary comparisons: a1 x2 outcomes, a2 x2, b 2 entries x2 probs (vs C1 base), c 1, d 4 rules vs HOLD + 2
  SLICE vs ALL@same target. "Supported" only if discovery 99.67% CI (Bonferroni 0.05/15) excludes 0 AND holdout 95%
  CI excludes 0 with the same sign. Everything else is descriptive. Expected power is LOW for (a) (~23 coins).
