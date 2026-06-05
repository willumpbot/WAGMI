# Walk-Forward Rule Validation

## Purpose

Prevents overfitting in graduated rules by validating in-sample patterns hold out-of-sample.

## How It Works

```
Time axis: [----train_1----][--test_1--][----train_2----][--test_2--]...

For each window:
  1. Run LLM backtest on train window
  2. Track which graduated rules fired + outcomes
  3. Run LLM backtest on test window (same rules, frozen)
  4. Compute rule accuracy on unseen data

Rule confidence = OOS_WR / IS_WR
  > 0.8 = validated (real edge, promote to production)
  0.5-0.8 = marginal (keep but monitor)
  < 0.5 = suspect overfit (candidate for demotion)
```

## Running Walk-Forward

```python
import sys; sys.path.insert(0, 'bot')
from backtest.rule_walk_forward import RuleWalkForward

# Quick run (2 windows, BTC only, 2 USD budget per window)
wf = RuleWalkForward(symbols=['BTC'], budget_per_window=2.0)
scores = wf.run(windows=2, train_days=30, test_days=15)
path = wf.save_scores(scores)
print(f"Scores saved to {path}")

# Print report
RuleWalkForward.print_report(scores)
```

Or from the command line after session reset:
```bash
cd bot && python -c "
import sys
sys.path.insert(0, '.')
from backtest.rule_walk_forward import RuleWalkForward
wf = RuleWalkForward(symbols=['BTC', 'ETH'], budget_per_window=2.0)
scores = wf.run(windows=2, train_days=30, test_days=15)
wf.save_scores(scores)
RuleWalkForward.print_report(scores)
"
```

## Output

Scores written to `analysis/walk_forward/rule_confidence_scores.json`.

## Important Notes

- Budget per window is for ONE symbol. Multi-symbol costs multiply.
- Each window pair costs ~2 LLM budget units: `windows × symbols × budget_per_window × 2`
- For 2 windows × BTC+ETH × $2 per window: `2 × 2 × $2 × 2 = $16` total
- At 22:30 UTC session reset, run with budget=2.0 per window first

## Integration With Production Rules

After running, manually review `rule_confidence_scores.json`:
- `verdict = "suspect_overfit"` → set `active = false` in graduated_rules.json
- `verdict = "validated"` → keep active, possibly increase weight
- `verdict = "insufficient_data"` → gather more data before judging
