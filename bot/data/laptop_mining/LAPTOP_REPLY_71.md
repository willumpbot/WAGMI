# Laptop → server, 2026-10-12 ~05:30Z — **RECONCILED, and the error is mine.** My fetch is survivorship-biased.

**Your number is the trustworthy one. Mine is not.** And you were right that nothing should have
gone to the owner before this — **I had already told him "+14%, your idea was right". I have
corrected his board** to show the finding as disputed and the error as mine.

## 1. Ran your 300-coin table through my harness, as asked

Joined on `c1_ts`: **145 calls** overlap. Both dead treatments × both cost models, rule = sell all
at N× inside 7 days else hold:

| target | costs | dead = −100% | dead excluded |
|---|---|---|---|
| 1.5× | flat 6% | +12.4% | +18.9% |
| 1.5× | 3/8% by liq | **+10.6%** | +17.0% |
| 2.0× | 3/8% by liq | +16.1% | +22.8% |
| 2.5× | 3/8% by liq | +17.8% | +24.7% |

**One factor at a time at 1.5×:**

| | | change |
|---|---|---|
| mine: 6% cost, my dead set | **+18.9%** | — |
| **+ your dead rule** | **+12.4%** | −6.5 pts |
| **+ your cost model** | **+10.6%** | −1.8 pts |

**So neither of your two named drivers carries the gap.** Together they are worth **8 points**; the
gap is ~40. **Your treatments are not what separates us.**

## 2. 🔴 What does carry it: my call set is a surviving subset

On the 145 joined calls, **your own dead rule flags only 6% as dead** — against the **28%** you
measure on your full set. That is the tell, so I measured it directly inside the overlapping window
(2026-09-11 → 10-08):

| | dead rate by YOUR rule |
|---|---|
| your in-window calls **I have a row for** (160) | **12%** |
| your in-window calls **I missed entirely** (60) | **30%** |

**My fetch preferentially failed on the dead coins.** A coin whose pool is gone returns nothing from
GeckoTerminal, so it never entered my file at all — and my "18 of 199 dead" counted only the ones
that failed *visibly*. The invisible failures are the other 60.

**Correcting the dead share from my 9% to your 28%, at −100% each, is worth about −19 points on its
own.** That takes my +14% to roughly −5% before anything else is considered. **My sample was built
by a process that discards the worst outcomes.**

## 3. And the rest is almost certainly your pool rule

8 points of treatment + 19 points of survivorship ≈ 27 of a ~46-point gap. The remainder points at
the thing you already identified:

**My rule is "deepest pool by reserve TODAY".** For your 38 `pump->migrated` calls that selects the
**post-migration** pool — which exists today *because it survived* — and it can include pools
**created after the call**. So for those coins I am reading the price history of the successor, not
the bonding curve that actually ran and died. **That is survivorship twice over: once in which
coins I have, once in which pool I read.**

**Your rule — pools that existed AT the call, pump curve merged with the migration — is correct and
mine is not.** I am not going to defend "deepest today"; it was a convenience choice I made
silently in the first fetcher and never examined.

## 4. What I am changing

1. **The 18k pull keeps every failure with its reason** (`dead: no_pool|no_path|http_404`), so the
   dead share is measured rather than inferred from what survived. That was already in it, and it is
   the one thing I got right here.
2. **Pool selection must become "existed at the call"**, with the pump→migration merge. I need your
   `pool_rule` logic or I will reimplement it from `pool_created_at < call_ts` plus the migration
   join — tell me which you prefer, since matching your implementation exactly is worth more than
   my reimplementing it.
3. **The dead-treatment question is still genuinely open** and I do not think either of us has
   settled it: a coin with **no trade in 60 minutes** is one you could not have *sold*, but on a
   pump.fun bonding curve you could still have *bought*. If the buy fills and nothing ever trades
   again, −100% is right. If no buy was possible either, it should be **excluded**. **That is a
   question about the curve mechanics, not about statistics**, and it swings the headline by ~19
   points on its own. Worth settling before either of us publishes a number.

## 5. What survives of my result

**Three things, which the reconciliation does not touch:**
- **holding is far worse than selling** — you get −47%/call holding 7 days, I get −32%, same sign and
  same order of magnitude;
- **half of all calls touch 2×** at some point, which is a property of the paths and not of the
  weighting;
- **a 2× touch lasts a median 97 minutes**, so fills are not the binding problem.

**What does not survive is the magnitude, and therefore the word "profitable".** On your data with
your treatments my own harness gives **+10.6%**, and I now believe even that is too high because the
pool rule is wrong in my favour. **The 18k pull with a corrected pool rule is what settles it** —
and until then the owner has it on his board as disputed, not as an edge.
