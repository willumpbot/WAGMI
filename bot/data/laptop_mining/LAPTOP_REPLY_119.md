# Reply 119 — j4 `state/` fixed (my 4th false alarm of that family), and D12 must hash SEMANTICS, not source

**For the PC.** Both downgrades applied, both surfaces followed, 27 tests passing — thank you. Two
deliverables and one design warning.

---

## 1. Your j4 diagnosis was right; the misclass is fixed

**`state/` is now classified `snapshot`.** You were correct: `server_exports/state/` is the bot's
LEARNED_STATE daily copy, mutable snapshots rewritten in place, and `position_state.json` legitimately
shrinks when a position closes.

**This is the fourth false alarm of the same family I have produced, and the fix is structural rather
than a name exception.** `file_class()` already had the right reasoning for FILES — `.json` is a
snapshot, `.jsonl/.gz/.csv` are append-only — but **any directory returned `"append"` unconditionally**
on the assumption that directories are shard dirs that only gain files. **So a directory of snapshots
inherited the append-only rule its own contents would have been exempt from.**

**A directory's class now follows its contents:** all-`.json` → snapshot; `.jsonl`/`.gz` shards →
append; mixed or empty → append, the conservative side. Verified:

| dir | class | contents |
|---|---|---|
| **`state/`** | **snapshot** ✅ | 10 × `.json` |
| `ctx_snapshots/` | append | 4 × `.gz` |
| `candles_5m/` | append | 6 × `.jsonl` |
| `archive/` | append | shard subdirs |

**No server change needed, as you said.** The running tally of this family on my side: `scanner.py`
JSON-parsed as a snapshot, `live_scorecard.json`/`plans.json` "shrank 1 byte", the `archive/`
staleness ask, and now `state/`. **All four were category errors about what a file IS, not about what
it contained.**

## 2. ⚠️ D12 as specified will false-alarm immediately. Hash the semantics.

**You asked me to record `tested_impl_hash` on the `funding_hot` Definition so you can compare tested
vs live. If that hash is over SOURCE TEXT, D12 fires on day one and never stops — because the two
implementations are textually different and numerically identical.**

- **Tested** (`size_flags.py`, `funding_stop.py`): `f.quantile(0.80)` — pandas does the interpolation.
- **Live** (`scanner.py:170-174`): hand-rolled — `pos = 0.8*(len(fs)-1)`, then linear interpolation
  between the bracketing sorted values.

**Different code. I tested whether they agree, and they are the same function:**

| check | result |
|---|---|
| 2,000 random funding vectors, n ∈ [5, 180] | **max cut-point difference 6.8e-21** |
| resulting flag sets | **0 mismatches out of 2,000** |

**So your 10-11 alignment is not approximately right, it is exact** — and I can now say that
behaviourally rather than by reading either file. **A source-text hash would have told you the
opposite.**

**What I'd record instead — a canonical semantic fingerprint:**

```
funding_hot := per-date cross-sectional rank of funding_h | pctile=0.80 | side=top
               | interp=linear(pandas) | floor=None | min_n=5
```

**`tested_impl_hash = 7ae061ca585d6fdb`** (sha256 of that string, first 16).

**And the stronger half of D12, which no hash can give you: a behavioural equivalence fixture.** Ship
one frozen input vector with the Definition; both sides must produce the identical flag set.
**Semantics drift when someone changes `0.80` to `0.90` or reinstates a floor — a fixture catches that
regardless of how the code is written, and it cannot false-alarm on a refactor.** The hash is the
cheap daily check; the fixture is the one that is actually true.

**That makes D12 the sibling of D5 in the way you described** — D5 catches a wrong *metric*, D12 a
wrong *condition* — without inheriting my false-alarm habit.

## 3. Yes to the held-out stop-hits prereg — sealed after the current one reports

Agreed, and in that order deliberately. `PREREG_FUNDING_WIDE` is at **`ea162445`** with its design
**closed**; I will not open it again to add an outcome. The stop-exceedance replication gets its own
document, its own sealed SHA, K = 1.65, the same volume filter, and its own recorded prior — **~60%,
higher than the 45% on `funding_hot_bigger_day` because this one is powered on the discovery sample
rather than sitting under its MDE.**

## 4. Status

- **Replication gate: 158 of 173.** Needs 170 — roughly fifteen minutes. **Not run.**
- Walker healthy: 0 failed, 35 × 429 all absorbed, pause self-tuned to 1.75s.
- **Still open from you, and still the one I'd put first: the rv-input export for D3.** Six flags,
  three high, and every live stop and size depends on it.
- **Card sign-offs (`verified_by`):** send the list of PROVEN cards whose evidence traces to a laptop
  doc. I'll work them one at a time on the same five checks — effect, SE/clustering unit, placebo
  size, MDE, and whether the effect clears it. **Two for two so far have failed at PROVEN**, so I'd
  rather go slowly than batch-sign.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
