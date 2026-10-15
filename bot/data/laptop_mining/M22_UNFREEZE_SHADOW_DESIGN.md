# M22 DESIGN — the unfreeze question, answered in shadow: would a LIVING gate (recency-weighted, per SERVER_EXPLORE A) have beaten the FROZEN gate on realized R? SHADOW ONLY — no live gate changes, ever.

**Status: DESIGN, before any code. EXPLORATORY, HYPOTHESIS cap. A shadow study by construction changes
no live gate** (the P1 unfreeze decision is the owner's/server's; M22 only measures whether it would
have helped). Panel first. Server's scheme is taken VERBATIM from SERVER_EXPLORE_2026-10-13 §A — M22
does not re-derive it, it BACKTESTS it.

## 0. What is fixed vs measured
FIXED (SERVER_EXPLORE A, used as-is): recency w_i = 0.5^(age/45); n_eff = (Σw)²/Σw²; m = Σw·R/Σw;
size mult = clip(1 + 1.25·m·n_eff/(n_eff+13), 0.25, 1.5); long/solo block iff n_eff ≥ 13 and
m + 0.84·se < 0; R = realized_rr where present (81/295) else reconstructed from the TRADE_OPENED sl
(293 matched, agrees ±0.01). MEASURED: the difference in realized outcome between the FROZEN gate that
was actually live at each trade's open and the LIVING gate that A's formula would have computed from
only the data available THEN.

## 1. The comparison (point-in-time, the whole study)
Walk the trade ledger in order. At each candidate trade's open ts:
- FROZEN state = what the live gate actually was then (from conf_floor_decisions / floor_decisions_log
  / entry_gate_log — the real block/size decisions the bot recorded).
- LIVING state = A's formula applied to the recency-weighted window of trades CLOSED STRICTLY BEFORE
  this open (point-in-time; no trade sees its own outcome or any later one).
Each trade gets: was it blocked under frozen? under living? its size mult under each? and its realized
R. The shadow P&L of each policy = Σ over trades of (allowed? size_mult · R : 0), in R and in % of
notional net of fees (A's fee/gross ratio per trade).

## 2. The reads
- Headline: living shadow-P&L − frozen shadow-P&L, in R, with day-block bootstrap CI (trades cluster
  in days/regimes); equal-weighted-by-day beside pooled.
- Decomposition: trades the two policies TREAT DIFFERENTLY only (block/allow flips and size changes) —
  the rest cancel; the headline attaches to the differing subset with its own n.
- Direction split: long gate / short gate / solo gate separately (A shows them diverging — longs block
  on, shorts 1.5) — each is its own cell with its own n_eff; a cell under n_eff 13 falls back exactly
  as A specifies (all-time, not off).
- The honest null: this is a backtest of a FIXED formula on ONE realized history — no resampling can
  manufacture a forward claim. So the deliverable is explicitly "on the trades we have, unfreezing
  would have changed realized R by X [CI]"; it is NOT "unfreezing will help forward." State the n of
  differing trades and the MDE; if the differing subset is tiny (likely — frozen and living agree most
  of the time), the verdict is UNDERPOWERED and the recommendation is "keep shadowing live, re-read at
  n_differing ≥ K."

## 3. Guards specific to this study
- Look-ahead is the whole risk: the living window at trade i must contain only trades with CLOSE ts <
  open ts of i. Exploration/blocked-go probes count as evidence FLAGGED (A's rule). A trade cannot
  influence its own gate.
- Regime confound: realized R is regime-correlated and so is recency weighting's emphasis on recent
  (possibly one-regime) trades — report the differing-subset outcome by BTC-vol tercile so a "living
  wins" is not just "living overweighted a lucky recent regime."
- No forward promise, no live change: the result informs the server's unfreeze decision; it does not
  make it, and nothing in M22 writes a gate.

## 4. Panel questions
(a) Is the frozen-state reconstruction from the decision logs faithful (do conf_floor_decisions +
floor_decisions_log + entry_gate_log actually pin what the gate was at each open, or is there slippage
— MEASURE the match rate against recorded block outcomes); (b) the R reconstruction (realized_rr vs
TRADE_OPENED-sl) — carry A's ±0.01 agreement as a stated bound and check the 214 reconstructed rows
don't dominate a direction cell; (c) differing-subset size and MDE MEASURED with DB/export access
before any verdict; (d) is there any path by which this shadow silently becomes a live change (there
must not be — confirm the output is a number, never a gate write).
