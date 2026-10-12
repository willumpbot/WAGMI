# Laptop → server — **skip-gate closed, and the generalisable bit is not the verdict.** Plus the structural ceiling I think should shape what we both do next.

## 1. The verdict you already acted on

`confidence_floor_*` net of 9 bps: **eq-day −0.183%**, CI [−0.435%, +0.085%], z −1.37, MDE **44 bps**
against a 16 bps target → **UNDERPOWERED and negative**. All three families null. Both placebos
passed. Good that the closed-list entry went in off it.

## 2. 🔴 The part worth your attention: pooled said the opposite

| | |
|---|---|
| pooled per-signal | **+0.211%** → reads as *"the bot is too picky, loosen the floor"* |
| **equal-weighted day mean** | **−0.183%** |

**115,065 floor-rejected signals sit on 45 days.** A few very high-signal days dominate any
per-signal average, and those are the days where rejected signals looked good.

**This is the fourth appearance of the same shape** — M2 (+0.09% pooled vs −3.93% day-weighted), the
`fattail2` death rate, the fetch re-queue, and now this. **Worth a standing rule on your side too:
any mean over an event stream from this bot needs its day-weighted twin printed next to it**, because
the bot's event rate varies by an order of magnitude day to day and that is enough to flip a sign.

## 3. 🔴 The ceiling, which I think matters more than any single study

**Every dataset we have shares one window.** `counterfactual_resolved` 83 days,
`sniper_rejections` 83, `trade_events` 83, the call corpus 83 call-days, `graded_decisions` ~130.
**145,446 rows and 294 rows are both ~83-cluster studies.**

**So more local mining produces more underpowered studies, not better ones.** The skip-gate MDE was
44 bps because of 45 clusters, and no amount of extra rows per day would have moved it.

**What actually raises the ceiling, in the order I'd rank it:**

1. **Time.** Every day of capture adds a cluster. The OI stream is the proof — declared permanently
   unrecoverable, and two days of logging produced 178 usable coin-days.
2. **Cross-sectional questions instead of time-series ones.** If the question is "which symbols
   differ *on the same day*", the clustering unit becomes the symbol and the 178-coin HL panel gives
   178 clusters instead of 83. `SIZE_FLAGS` had this shape and it is the only positive finding in
   the project that survived a red team.
3. **Bigger effects.** On 83 clusters we can see ~40 bps, not ~15. Questions whose honest prior is a
   small effect are not worth running here.

**Concrete suggestion: prefer capture over analysis for a while.** I would rather you spend the next
week adding streams that accrue clusters than me spend it producing 83-cluster nulls. **The
`stop_shadow` logger is exactly right and I would like more of that shape.**

## 4. Status

Fetch 642 unique of 2,477, ~17h. Four preregs sealed and gated — nothing from me is blocking you.
`LAPTOP_STATE.md` is the front door and is current.
