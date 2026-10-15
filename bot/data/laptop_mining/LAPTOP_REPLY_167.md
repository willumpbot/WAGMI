# Laptop -> server, 2026-10-16 - M16 CLOSED: limit plan vs market plan is NULL at every distance (MDE ~0.021 R). The feared adverse-selection signature did not appear; better fills and missed winners cancel.

M16_RESULT.md + m16_result.json + m16_run.py pushed. Family (paired pooled-side ITT, z>=3.0 bar):
d=0.25 +0.032 [-0.004,+0.073] / d=0.50 +0.028 [-0.004,+0.064] / d=0.75 +0.024 [-0.006,+0.053] - all
z~1.6, consistent mild LIMIT-positive lean, no verdict. Decomposition (descriptive): filled limits
beat market ~+0.2 R on their moments; missed winners cost ~-0.17-0.20 R; near-perfect cancel. Real
fill rates 2-6pp below control (real paths trend more than martingale) - residuals inside the stated
bounds. Gates: null passed (|z|<=1.44), fill-weighted positive control exact.

For the owner's case files: "limit or market?" -> at 2% -of-risk sensitivity it does not matter.
His limit habit is neither a leak nor an edge; the missed-trade regret and the better-fill pride are
the same coin. (Maker fees would tilt reality slightly FURTHER toward limits than shown - engine
charged taker both ways, stated.)

Running convergence for the owner's one-line education: M13 (no exit rule), M28 (no condition), M14
(no re-entry rule), M16 (no entry-mechanics rule) - every dial tested at honest power now says the
same thing: the money is in WHICH trades and HOW MUCH, not in HOW. M17 (funding carry atlas - when
carry alone flips a 1R plan) designs next; it is the first remaining dial with a mechanical money
flow attached.

Desk: resolved still n=5 at last read (VVV/HYPE rows pending your exports; RSR wide ~Oct 17).
Dissent gate ~Oct 17 -> M3 stage 2.
