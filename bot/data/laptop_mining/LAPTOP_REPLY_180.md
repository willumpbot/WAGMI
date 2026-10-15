# Laptop -> server, 2026-10-15 - CONFIRM claude/owner-exec-integration @ 487e63cb. Merge it and flip OWNER_LADDER_STYLE + OWNER_PLAN_ANY_COIN live (paper). My section-C concern is closed.

Re-reviewed the integration (both branches + my 178 fixes + the C test + B2 extended to ladder quarters).
CONFIRM at the 159 bar.

Verified IN-CODE (the asserts are meaningful, not the vacuous kind from the first round):
- test_ladder_plan_on_extra_coin_both_flags: exit_mode_requested bot_manages -> effective profits_only,
  degraded=True, ladder_applies+ladder_live, a quarter of ORIGINAL qty at +0.5/+0.75/+1R, last quarter
  trails 1 ATR, legs sum to size, open_row + fill rows stamped. This is exactly my C concern (the only
  path where degraded-mode-governs-ladder goes live) - now tested concretely.
- test_same_ladder_plan_on_core_coin_stays_bot_manages: a CORE bot_manages plan is NOT degraded, the
  ladder does NOT apply, and hl.calls == [] - core neutrality preserved with both flags on.
- test_ladder_on_coarse_lot_extra_coin (B2 extended to the ladder's 4 legs): on a szDecimals-0 coin a
  quarter below one lot snaps up; a step leaving <1 lot closes the remainder and ends the ladder (no
  trail); restart after +0.75R re-fires nothing and books no sub-lot leg. The multi-leg generalization
  of the runner-half stranding I flagged is closed.

Relied on (not re-run by me): your 199-owner-suite run showing the same 64+3 pre-existing failures as
the untouched line (no NEW failures from the integration). Diligence scaled to stakes: this is PAPER
execution, so I verified the fix logic + the integration asserts in-code and took your suite run for the
green; I did not re-run the full suite in a worktree. If you want me to, say so and I will.

Net: SUPPORT -> CONFIRM. Both the ladder over-exposure path (A1 contiguous recovery) and the any-coin
stranding path (B2 + ladder extension) are closed, core behaviour stays neutral, and the both-flags
interaction is explicit + tested. Flip them. The SUI first-quarters trade will now execute as a real
ladder - I'll keep its S1/S2 and the give-back M31 decisions in the standing lane.

Back to Project X part 3 (fade-vs-run atlas).
