# S2 POST-MORTEMS — the three closed owner trades (BTC ×2, CASHCAT), 2026-10-15

_Verified on bars (the server's regrade quotes were checked, not trusted). The two BTC plans are
near-duplicates (same idea `ai7fca78bf`, same fill bar, same exit bar) — **pool them as ONE block** in
any future stat or every BTC conclusion double-counts. CASHCAT is `late_logged` — narrative only,
excluded from every population._

## BTC SHORT `11624f4364` (grade r +0.685) and `7df524f101` (r +1.0)
- Target hit 2026-10-13 00:05Z (bar low 81,253). **Continuation after exit: +0.19R/+0.29R beyond target
  at most, 45 minutes later — then a +2.5% bounce** (83,075 by 02:55, 84,133 by 08:10).
- **Exit style: FULL at target won cleanly on both** (runner gross ~+0.62R vs full +1.0R) — verified on
  bars; the server's regrade numbers reproduce.
- 🔴 **Live-vs-sim gap on `11624f4364`: the real bot banked only +0.03R** (LLM partials then SL at
  83,862.5 — `owner_fills.jsonl:2-4`) on a trade every sim mode scored +0.59R to +1.0R. **The LLM exit
  layer cut the winner.** This is the single most actionable row in the three post-mortems: the new
  runner engine's "AI exit may not partial a live runner" rule exists for exactly this; worth a case-file
  note that it already cost ~0.6–1.0R once.

## CASHCAT LONG `577a41c3ac` (late_logged — narrative only)
- MAE −0.54R before the target first printed at 27.2h. The move then ran to **+2.43R (+24.9%)** at
  2026-10-14 21:00Z — **the same hour the 48h time limit would have exited the runner's remaining half.
  The clock caught the top almost to the hour** (+1.49R runner vs +1.00R full, verified).

## The one pattern (anecdote tier, n = 3, one late-logged)
Runner-vs-full is a bet on continuation past ~1R, and in these three it split exactly by vol class:
on BTC (major) the move died at the target both times and full won by ~0.33–0.38R; on the 13.7%-ATR
small cap it ran +2.43R and the runner won by +0.49R. Consistent with M12's interaction (ATR-scaling
matters most on high-vol coins) — but n=3 with a selected instance; the M28 map is where this becomes
a testable claim, not here.

---
**What matters:** the LLM exit layer once cut a winner to +0.03R that every rule-based mode banked
+0.59R–1.0R; and the runner-vs-full split so far tracks vol class.
**What would change anything:** nothing live — the v2 branch already blocks AI partials on live
runners; the M28 map tests the vol-class pattern properly.
**Confidence:** high (bars re-verified); pattern explicitly anecdote-tier.
