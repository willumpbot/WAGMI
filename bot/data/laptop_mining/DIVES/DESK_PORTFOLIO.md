# DIVE — the desk as ONE book (open plans, deduped), 2026-10-15

_Portfolio agent + verifier over plans_snapshot (as_of 1792023073) and 60d of 1h returns. Dedupe
verdict first: the duplicate rows are **RE-LOGS** (identical `filled_at`/qty/levels/expiry, log ts
+4.1h) — 5 distinct structures, not 8 positions. Flagged upstream: whatever writes the snapshot
double-logged every non-bot coin plan ~4h apart._

## Exposure (deduped)
| structure | notional | $ to stop | stop distance |
|---|---|---|---|
| VVV SHORT | $122 | $5.13 | 4.20% |
| RSR LONG tight | $90 | $12.09 | 13.4% |
| RSR LONG wide | $83 | $11.08 | 13.4% |
| HYPE SHORT 82.2 | $193 | $12.63 | 6.5% |
| HYPE SHORT 82.0 | $184 | $12.05 | 6.5% |
| **Total** | **$673** | **$53** | net SHORT $327 |

## Correlation / clustering (60d 1h log returns; eqw per-day beside pooled)
- VVV–HYPE 0.41 eqw (0.37 pooled); each coin vs BTC: VVV 0.41, RSR 0.55, HYPE 0.58 (eqw).
- **M7 applies to the same-direction short cluster (VVV+HYPE): λ = 1.637 [1.538, 1.737] — treat the
  three shorts as ~1.64 positions' worth of simultaneous-stop risk, not 3.** A clustered bad week can
  realize ~$29.8 ≈ 3× one plan's risk.

## BTC shock (M5) — the one scenario that hits everything at once
- Betas (eqw per-day, 60d — run ~20% hotter than pooled): VVV **1.75**, RSR 1.72, HYPE 1.27.
- A 2σ BTC up-hour (81 bps) moves VVV +120–142 bps = **eats 28–34% of VVV's remaining stop distance**,
  HYPE +91–103 bps (14–16%), while the RSR longs gain — net book ≈ −$3 per such hour. The desk's
  correlated-loss scenario is a sharp BTC pump, and VVV is the weakest link in it.

## Carry
All five legs currently COLLECT: VVV +$0.04/d, HYPE +$0.11/d, RSR (shorts pay longs) ≈ +$0.68/d →
**≈ +$0.83/day**, dominated by the volatile RSR leg (24h-mean extrapolation, not a promise).

---
**What matters:** $53 total stop risk, but M7 says the shorts stop together (λ1.64) and a 2σ BTC pump
is the single scenario that stresses VVV (0.37 ATR from its stop) while the whole book is net short.
**What would change the plan:** the re-log duplication upstream is worth a one-line fix so exposure math
never depends on manual dedupe.
**Confidence:** high (every number above survived independent re-derivation; betas/correlations carry
their eqw-vs-pooled gap explicitly).
