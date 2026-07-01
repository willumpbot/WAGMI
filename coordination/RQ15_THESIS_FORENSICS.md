# RQ15 — Thesis Language Forensics (2026-07-01)

**Question:** What separates graded-RIGHT theses from graded-WRONG ones linguistically/structurally?
**Inputs:** `bot/data/llm/thesis_history.jsonl` (279 records at run time) + fresh per-thesis regrade using the exact methodology of `coordination/THESIS_GRADES_2026-07-01.md` (that pass saved no per-record grades, so this script regrades from scratch: text-derived direction/symbol, HL 1h candles May 29→Jul 1, ±0.3% band at +6/12/24h, entry re-derived when `entry_price` mismatches candle by >3%).
**Script:** `bot/tools/research/rq15_thesis_forensics.py` (artifacts `rq15_graded.json`, `rq15_candle_cache.json` next to it, untracked).

## Honest denominators
| bucket | n |
|---|---|
| records in file | 279 |
| no derivable direction ("trend aligns" stubs) | 14 |
| too recent for +24h grade (Jul 1 evening burst) | 65 |
| graded +24h | 200 |
| **deduped (by normalized text)** | **164** |
| deduped ex-flat at +24h (RIGHT / WRONG) | 155 (89 R / 66 W = 57%) |

Sanity vs the grades pass: 57% ex-flat +24h here vs 58% there — methodologies agree. Era split throughout: E1 = May31–Jun06 (102 ex-flat), E2 = Jun07+ (53 ex-flat).

## What discriminates (evidence-ranked, deduped +24h ex-flat)

### 1. Names a FRESH numeric price target — strongest positive (n=155)
"to/toward/targeting ~$X" with an actual market number: **75/117 = 64% right, avg +0.97%** vs **14/38 = 37%, avg −0.57%** without.
- Era-robust: E1 66% vs 31%; E2 58% vs 41%.
- Per-symbol consistent: BTC 72/50, ETH 83/45, SOL 52/25, HYPE 20/0.
- Fragility: drop single best observation → 64% unchanged; drop worst no-target obs → no-target still 38%.

### 2. TP1/TP2-label as the target — anti-signal (n=58)
Theses whose "target" is the pipeline's own TP label ("to TP1 $60.78", "holds to TP2") instead of a market-derived level: **26/58 = 45%** vs **63/97 = 65%** without. Holds both eras (E1 41% vs 66%; E2 47% vs 59%). Self-referential targets = the agent restating its order ticket, not a thesis.

### 3. "Holds / continues / continuation-to" language — anti-signal (n=21)
**8/21 = 38%, avg −1.40%** vs 60%/+0.91% without; 0/7 at +12h for the explicit trailing-stop subset. Both eras negative (43%, 29%). These are late-trend "keep riding it" theses written after the move already happened (the Jun 5–6 SOL/BTC exhaustion cluster).

### 4. Length — shorter is better, monotonic (n=155)
Word-count quartiles: Q1 (8–21w) **66%/+1.55%** → Q2 63% → Q3 61% → Q4 (27–34w) **41%/−0.70%**. Median-split holds in both eras (E1 69/53, E2 58/44). Kitchen-sink justification correlates with being wrong.

### 5. Quant-Brain stat citations — mild anti-signal, CONFIRMED with nuance (n=54)
Any WR/n=/EV/PF citation: 54% vs 59% without — mild overall. But:
- **Hard numeric citations** ("n=", "% WR", "PF"): 53% overall, **45% and avg −0.63% in E2 (n=20)** — where all the garbage citations live ("85-88% WR n=395" −10.5%/−8.7%, "PF 12.21 n=4" −9.1%).
- Within the good symbols the anti-signal is strong: BTC with-stats 56% vs 73% without; ETH 62% vs 81%.
- The bare word "validated/graduated" is NOT toxic (17/29 = 59%). The toxin is **small-n or session-derived numbers presented as edges**.

### 6. Session-edge language — anti-signal (n=14)
"US session / UTC hour / peak edge": **4/14 = 29%, avg −1.53%**. Every worst-10 HYPE long cited it.

### 7. Post-crash chase language (n=7, small)
"dead-cat / after crash / massive breakdown": 3/7 = 43%, avg −1.85%. Matches worst-10 pattern (shorting SOL/HYPE after the crash bar). Too small to graduate; consistent with #3.

### 8. Cross-asset confirmation — weak positive (n=53)
62% vs 55%; fragility-safe (62%→62%). Notably LONG+cross-asset = 3/4 vs LONG-without 5/17. Weak; do not over-weight.

## Combined checklist score (+1 fresh target, +1 ≤24 words, +1 cross-asset; −1 hard QB stat, −1 session language, −1 holds/stop language)
| score | n | right% | avg 24h |
|---|---|---|---|
| ≤0 | 41 | **37%** | −0.87% |
| +1 | 49 | 53% | +0.53% |
| +2 | 50 | 72% | +1.45% |
| +3 | 15 | 80% | +1.94% |

**score≥2: 74% (48/65) vs score≤0: 37% (15/41)** — monotonic, and direction holds in BOTH eras (E1 74% vs 17%; E2 75% vs 45%, though E2 high-score n=8 — humility). This is in-sample feature selection on n=155; expect shrinkage out-of-sample, but the monotonicity and era-robustness of the top items are real.

## KILLED hypotheses (logged as wins)
- **"States an invalidation" helps** — NO. True invalidation statements ("invalidated if reclaims X"): 6/12 = 50%, avg −0.80%, vs 57% baseline. Intuitively good hygiene, empirically no edge at n=12. Keep for risk discipline if you want, but don't expect accuracy from it.
- **"Cites a timeframe" helps** — undiscriminating: 93% of RIGHT and 88% of WRONG cite one. Worse: stated horizons are systematically too short (+6h accuracy 37% vs +24h 57% per grades pass) — the words are there, the numbers are wrong.
- **"Citing ADX" helps** — NO overall effect (57% with vs 57% without; E2 with = 3/8). The grades-doc "high-ADX winners" pattern is about the actual ADX value in the market, not the token appearing in prose.
- **Hedging/conditional phrasing** — ungradeable: hedging n=3, conditional n=8–10. The prompt style is uniformly assertive; no variance to measure. Cannot claim "assertive beats hedged."

## Adversarial self-check
- Direction confound: 84% shorts in a falling tape — but all top features were checked within-direction and within-symbol (see #1, #5); they survive.
- Era confound: every ranked feature shown with E1/E2 split; #1–#5 hold direction in both.
- Regex leakage: first-pass "invalidation" feature conflated true invalidation with trailing-stop language — split resolved it (50% vs 29%); first-pass "no target" conflated TP-references — split resolved it (feature #2).
- In-sample risk: the composite score was built and evaluated on the same 155 — treat 74/37 as an upper bound.

## Deliverable — inject into Trade agent prompt (evidence-ranked)
1. **REQUIRE a fresh numeric market level as target** ("toward $1,825"), never "to TP1/TP2". (64% vs 37–45%)
2. **Cap thesis at ~25 words.** If it needs more, the setup is muddy. (66% vs 41%)
3. **Prefer cross-asset confirmation** (leader/laggard, BTC/ETH alignment) as the one extra clause. (62% vs 55%, weak)

## BAN from prompts / reject at Critic
1. **Numeric Quant-Brain edge citations** ("X% WR", "n=", "PF") — especially n<15 or session-hour edges. (45% in E2; owns the worst-10)
2. **Session/UTC-hour edge language.** (29%, avg −1.53%)
3. **"Holds/continues/hold through trailing stop" continuation theses** — a thesis that describes the existing position instead of a new prediction. (38%, avg −1.40%)
4. **Post-crash chase phrasing** ("dead-cat", "after massive breakdown") — n=7, but −1.85% avg and 6/10 worst trades.

Bugs re-confirmed in passing: `side` still always BUY in new records, `symbol` still wrong vs text, the "SOL breaking below key support" stub was still spamming on Jul 1 (65 records too-recent, mostly dupes), `outcome` still never graded.
