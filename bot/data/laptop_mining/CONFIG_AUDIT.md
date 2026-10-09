# Config audit — all three "validated fix" knobs are now closed. None says what we thought.

_2026-10-08. Verified by reading `bot/trading_config.py`, `bot/feedback/`, `bot/backtest/` and
`bot/.env` directly. Not a mining result — a fact-check of the knobs the July swarm recommended and
that `COMMAND_CENTER.md` has been telling the owner to change._

---

## Headline

**`ENSEMBLE_CONFIDENCE_FLOOR` is a backtest-only knob. Setting it cannot change live trading.** The
live floor is `AdaptiveConfidenceFloor`, bounded [20, 80], starting at 30. And the documented current
value (55) has been wrong since July — it is 20.

**All three knobs the July swarm flagged are now closed. None is a pending action.**

| knob | documented | actual | status |
|---|---|---|---|
| `ENSEMBLE_CONFIDENCE_FLOOR` | `:412`, now 55.0, target 80 | **`:476`, now 20.0** | **backtest-only — cannot affect live** |
| `TIME_STOP_HOURS` | `:241`, now 2, target 48 | `:283`, now 2 | **leave alone** (`EXITS_V2.md`) |
| `ADX_MIN_TRENDING` | `:227`, now 10.0, gate >60 | `:263`, now 10.0 | **UNMEASURABLE** — 14 weeks of signals cannot resolve it (`ADX_GATE.md`). Leave at 10 |

Every line number in the inherited table had drifted. The values are what matter, and one of those was
wrong too.

---

## 1. The confidence floor was deliberately lowered, not left stock

`bot/trading_config.py:475-486`:

```python
ensemble_confidence_floor: float = field(
    default_factory=lambda: _env_float("ENSEMBLE_CONFIDENCE_FLOOR", 20.0)
)  # LIVING VALUES fix 2026-07-15: code default corrected 55.0 -> 20.0 to match
   # the runtime floor already in force (.env ENSEMBLE_CONFIDENCE_FLOOR=20 + ...
   # The old 55.0 was a dormant silent-gate: data/trade_ledger.csv (n=99, test rows
   # excluded) shows conf<55 n=12 WR=67% avg +$0.29/tr while conf 55-80 n=79
   # loses -$117.69 combined ... a 55 floor blocks the non-losing low band and
   # admits the losing band.
```

`bot/.env:54` confirms `ENSEMBLE_CONFIDENCE_FLOOR=20`. So "it's still stock at 55, raise it to 80" was
describing a value that had already been changed, for a documented reason, eleven weeks earlier.

**I could not verify the n=99 evidence** — `bot/data/trade_ledger.csv` does not exist on this machine.
That file is the basis for the whole band argument, so please confirm it from the desktop.

## 2. It only feeds the backtester

Every consumer of the field:

```
bot/backtest/config_validator.py:361,363,364,373,375   (validation only)
bot/backtest/coordinator.py:321       confidence_floor=self.config.ensemble_confidence_floor
bot/backtest/engine.py:315            confidence_floor=self.config.ensemble_confidence_floor
bot/backtest/engine.py:947            ensemble.confidence_floor = ... + self._dynamic_floor_adj
```

All four are under `bot/backtest/`. **Nothing in the live trading path reads it.** The comment says so
too: *"this field is only the bootstrap/env override consumed by backtest/engine.py,
manual/runner.py, param_optimizer.py."*

## 3. The live floor is adaptive, and 80 is already its ceiling

`bot/feedback/adaptive_confidence.py`:
```python
ABSOLUTE_MIN_FLOOR = 20.0
ABSOLUTE_MAX_FLOOR = 80.0
DEFAULT_FLOOR      = 30.0
```
`get_floor()` returns `max(ABSOLUTE_MIN_FLOOR, min(ABSOLUTE_MAX_FLOOR, base))` with additive bounded
symbol and regime adjustments. The live caller is `bot/feedback/loop.py`:
```python
64:   self.confidence = AdaptiveConfidenceFloor(data_dir=data_dir)
150:  adaptive_floor = self.confidence.get_floor(strategy, symbol, regime)
```

**So the swarm's "target 80" is exactly `ABSOLUTE_MAX_FLOOR`** — the top of the range the adaptive
system already explores on its own. Pinning the backtest knob to 80 tests the ceiling; it does not
install it.

---

## What this means

1. **Re-run the backtest if you want, but don't expect it to change live behaviour.** It won't — and
   `COMMAND_CENTER.md` has been promising the owner it would.
2. **The real question is whether `AdaptiveConfidenceFloor` is converging sensibly.** That is
   answerable from `trade_ledger.csv` + the floor's own state files, both of which live on the
   desktop. **Can you dump them to `bot/data/laptop_mining/` or report the current per-strategy
   floors?**
3. **`ADX_MIN_TRENDING` is now examined and the answer is "unmeasurable".** See `ADX_GATE.md`: the
   test declared its own design void (placebo size 0.000, 80%-power MDE not reached even at 0.40R).
   Leave it at 10 — raising it to 60 would discard **92.5%** of signal flow to buy an effect this
   sample cannot measure at any size. Every ADX bucket has negative mean R, so the gate rearranges
   losses rather than creating a winner.

## Caveat on my own claim
I verified the *wiring* (which modules read which field) by grep and by reading the call sites. I did
**not** run the live bot to confirm the adaptive path actually executes in production, and I cannot —
the desktop owns live ops. If `feedback/loop.py` is not running in your deployment, the live floor
could be coming from somewhere else entirely, and that would be worth knowing.
