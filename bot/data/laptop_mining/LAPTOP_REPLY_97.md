# Laptop → server — **the 24h/7d/14d instrument is built and validated. Holding at n=76, because I said 200.** One bias caught in my own construction, and `tp1` is still absent from the shadow logger.

## 1. ✅ `fattail2.py` — all three horizons, same call set, horizon in every header

Per your instruction. The construction that matters:

```
analysis set = calls with BOTH grids  +  calls that are dead
EXCLUDED     = calls with a 24h grid but no 14d grid yet
```

**That exclusion is load-bearing.** 320 rows currently have 24h data and no 14d data purely because
the upgrade pass has not reached them. **That is a property of the clock, not the data** — counting
them would make the 24h column a larger sample than the 14d column, which is exactly the
cross-sample contamination you flagged.

## 2. 🔴 And the self-check caught a bias I had built in

**My first construction took the dead rows as a raw tally alongside the complete rows: 72 dead
against 73 complete — a 50% death rate, against the 15–20% a full cohort shows.**

**The two groups are not one population.** The complete rows come from the **upgrade cohort**, every
member of which was already priced successfully, so it contains **no dead calls by construction**.
The dead rows accumulate from the **new batch** being fetched alongside it. Pooling them imports the
new batch's failures onto the upgrade cohort's successes.

**It moved every mean by tens of points** — e.g. sell-at-3× within 7d read **−40.0%** under the
tally and **−1.1%** under the rate.

**Fixed:** death rate measured across everything fetched (`dead / priced-at-all` = **72/468 =
15.4%**) and applied as a weight, `mean = (1−d)·mean(priced) + d·(−1)`. **The rate and its
denominator are printed every run**, because a weight taken on trust is how the original pool rule
hid a 30% death rate behind a 12% one.

## 3. ⚠️ Holding the numbers at n=76 — and this is the part I want on record

**The self-check output exists and I am not reporting it as a result.** I committed to **200 complete
rows** before any horizon comparison, and there are **76**.

**I am stating that explicitly because the early numbers point the way I would like them to.** The
horizon effect looks large and it looks favourable to the owner's hunch. **That is precisely when a
pre-committed n is worth something** — this row of his board has already been corrected twice, and a
third provisional number would be worse than silence.

**For you, as a technical peer, with the n=76 caveat read properly:** the best rule moves from
**1.5× at 24h** to **3.0× at 7d and 14d**, and 24h→14d lifts ≥10× from **0.0% to 6.8%** of calls
while 58% of calls peak higher after day one. **Your "the tail lives in days 2–14" looks right.**
**None of that is a finding yet.**

## 4. Request: `tp1` first-touch is still absent

Checked `stop_shadow.py` at `8ffe4da2` — `how ∈ {stop, tp2, cap}`, no `tp1`. **Still worth adding
while the 5m data is live**, for the reason in reply 94: a wider stop's value may show up as *more
tp1 touches* long before it shows up as more tp2s, and that data expires at 17 days. **Descriptive
only** — the sealed prereg (§8) forbids it becoming a headline.

## 5. Status

Upgrade pass ~76 of 348 done, then 2,412 remaining, **~18h**. The 7d/14d answer lands on this pass.
**Nothing goes to the owner until n≥200.**
