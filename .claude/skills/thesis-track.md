# /thesis-track — Prediction Accuracy Tracking

## Description
Track how accurate the Trade Agent's directional theses are, and how often the Critic's counter-theses are correct. The core feedback loop: predict → trade → compare → learn → predict better.

## Arguments
- `$ARGUMENTS` — Optional: "summary" (overview), "deep" (detailed per-setup analysis), "last N" (last N trades), "by-regime" (accuracy per regime), "by-setup" (accuracy per setup type)

## Workflow

### 1. Load Decision and Trade Data
- Read `bot/data/llm/decisions.jsonl` for thesis and counter-thesis records
- Read `bot/data/trades.csv` for actual outcomes
- Parse decision notes for: THESIS:, COUNTER:, OUTLOOK:, CONFLUENCE:, setup= fields
- Match decisions to trade outcomes by symbol + timestamp proximity

### 2. Thesis Accuracy Analysis
For each matched decision-trade pair:

**Thesis vs Outcome:**
- Extract the thesis directional prediction (e.g., "SOL likely +3% next 6h")
- Compare against actual price movement during hold period
- Classify: thesis_correct (direction matched) or thesis_wrong (direction opposed)
- Calculate thesis accuracy rate overall

**Counter-Thesis Accuracy:**
- For trades where Critic challenged with counter_thesis
- Did the counter-thesis predict better than the trade thesis?
- Counter-thesis accuracy rate → feeds Critic's vacc calibration
- Flag: if counter-thesis is consistently right, Critic should veto more

**Thesis Quality Scoring:**
- Specific thesis ("SOL +3% because 4/4 align") vs vague ("probably up")
- Time-bound thesis ("next 6h") vs open-ended ("eventually")
- Evidence-cited thesis (mentions ctx, regime, BTC) vs unsupported

### 3. Breakdown by Dimensions

**By Regime:**
| Regime | Thesis Accuracy | Counter Accuracy | n |
| trend | X% | Y% | N |
| range | X% | Y% | N |
| ... | | | |

**By Setup Type:**
| Setup | Thesis Accuracy | Avg PnL | n |
| trend_at_zone | X% | $Y | N |
| zone_validated | X% | $Y | N |
| solo_regime_trend | X% | $Y | N |
| ... | | | |

**By Confluence Quality:**
| Quality | Thesis Accuracy | Avg PnL |
| convergent | X% | $Y |
| timeframe | X% | $Y |
| redundant | X% | $Y |

### 4. Actionable Insights
Based on the data, generate recommendations:
- "Thesis accuracy in trend regime is 72% — your strongest prediction environment"
- "Counter-thesis accuracy is 61% — Critic is slightly better than random, needs calibration"
- "trend_at_zone setup has 75% thesis accuracy — highest conviction setup, size up"
- "solo_regime_trend has 42% thesis accuracy — stop taking these trades alone"
- "Convergent confluence trades have 68% thesis accuracy vs 45% for redundant — weight confluence quality more"

### 5. Output Format
Present as a clean report with:
- Overall thesis accuracy % with trend arrow (improving/declining)
- Top 3 most predictable setups (highest thesis accuracy)
- Top 3 least predictable setups (lowest thesis accuracy)
- Critic counter-thesis track record
- Specific recommendations for improving prediction accuracy
