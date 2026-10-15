# M28 DISCOVERY READ — the map is FLAT: no mined condition moves the live machinery by even half an MDE with consistency across weightings. (Confirmation half UNTOUCHED.)

_2026-10-15. `m28_build.py` (176 coins → 25,965 moments; 18,668 discovery / 7,297 confirmation SEALED
and unopened; filters hashed d716c09e) + `m28_fit.py`. Design + Amendment 1 (b740d002) + amended seal
(boundary daykey 20693). EXPLORATORY; no condition is frozen in this pass — the freeze is its own
amendment, written cold, together with the L2 label descriptives._

## 0. Gates (both passed, one after a corrected spec)

- **Null gate:** 48 contrasts on an independent martingale draw — max |z| 1.44; overall D and A CIs
  cover 0. The pipeline finds nothing on noise.
- **Positive control:** the FIRST spec HALTed the run pre-read — it demanded 30 bps detection on
  `fund_hot`, the worst-clustered condition, whose own MDE is ~0.17 R (~85 bps): a mis-specified bar,
  not a broken pipeline (the injection steps recovered correctly). Corrected spec, recorded in the
  script: **linearity** (injections of 0.05/0.10 R recovered to 4 decimal places on both a clustered
  and a dispersed condition) and **detection at 1.5× the condition's own MDE** (z 3.34) — passed.
- **Per-condition MDEs are the honest sensitivity**: median contrast 0.046 R (~23 bps), dispersed
  conditions ~0.06 R, clustered conditions up to ~0.17 R. The survivor profile's MDE term is
  per-condition.

## 1. The read (D = direction content, A = machinery/cost; R units; wider CI governs)

**Overall:** D ≈ 0 for both styles (as it must be — random-time entries; CIs cover 0 with the honest
width ±0.1 R). A: runner −0.0021 R [−0.0139, +0.0081]; full_1R +0.0027 R [+0.0020, +0.0037] — a
~1.4 bps-at-median-sf machinery term, within the null's own A range at this precision; descriptive.

**Contrasts: NOTHING clears an exploratory bar.** Top |z| = 2.57 (full|A|fund_pctl) against a null
whose own max was 1.44 — and its equal-weighted versions flip sign (pooled −0.0032, eqw-coin +0.0004):
the desk's clustering standard kills it. The two largest point estimates (fund_pctl on D, ~−0.10 R
pooled: high-funding-percentile moments lean short — the carry/crowding intuition) sit at z ≈ 1.4,
indistinguishable from the null's own extremes, though notably their eqw-week versions are LARGER
(−0.26 R) — a candidate for a longer panel, not for this one's freeze. The pre-stated signs scored:
`waking_24h` → D negative expected; observed ≈ 0 (n=380 hot moments — under-covered at this spacing);
`btc_shock_24h` → A worse expected; observed −0.0008 R, z −1.1, direction right, size negligible.

## 2. What this means, in the project's own arc

The map agrees with M13 and the cross-study conclusion from the other side: **at ~23–85 bps
sensitivity, no mined condition tells the live machinery where it earns or bleeds.** The machinery's
cost is flat across funding regimes, vol regimes, trend states, attention flags, and BTC shocks. The
levers that change returns remain what M1–M13 said: trade selection and risk sizing — which is exactly
what the owner-label questions (L2) and the forward-label corpus are for, and those are gated on label
n, not on more map.

## 3. Pre-registered next steps (nothing read from the sealed half)

- **Freeze decision (next pass, cold):** on this evidence the honest freeze is likely **NOTHING** —
  no candidate has discovery support worth spending the one sealed read on; the sealed 7,297 moments
  keep their value for a longer panel or a sharper design. If any condition is frozen it must carry
  discovery |z| materially above the null max and a mechanism, per the seal's survivor profile.
- **L2 label descriptives** (n≈5 filled clusters — descriptive only, MDE ~0.6–0.9 R) ship with the
  freeze pass.
- **Twin gates** (`m28_gates.py`): consistency gate runnable now; fidelity gate UNDECIDABLE until ≥30
  closed real legs — the desk's open plans resolving tonight start that count.

## Limits
Carried from the design: sim fills at levels (optimistic); 1h map resolution (5m-vs-1h delta to be
measured on the gate population); oi_chg 2% coverage (dead column, reported not used); waking_24h
coverage thin at 24h spacing; one venue; 212d one-regime panel; control pools point-in-time but
bar-shape-stationarity assumed.
