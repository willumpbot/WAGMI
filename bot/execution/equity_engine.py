"""
EquityEngine — read-only derive/reconcile façade (Phase 0.5 PR-2).

NOT a new number source. `data/trade_source.py::get_run_stats()` stays the
single canonical derivation (epoch_equity + sum(in-epoch ledger net_pnl)).
This module adds nothing to that math except three well-defined, additive
correction terms and packages the result for callers that need to compare
the mutable accumulator (`RiskManager.equity`) against ledger truth.

Mirrors `feedback/live_edge.py`'s return-None-not-fake discipline: when the
epoch has no equity baseline stamped (`epoch_equity is None`), every method
here returns None. Callers must treat None as "can't derive/reconcile here",
never as $0 or as license to silently fall back to a guess.

OPEN-position / unrealized policy (decision, locked — see BUILD SPEC 0.5
PR-2 "OPEN-position/unrealized policy"):

    derived_equity_live = epoch_equity
                         + sum(in-epoch ledger net_pnl)
                         + sum(open-position realized_pnl)

NO unrealized mark-to-market is ever included. `execution/risk.py`'s
`check_unrealized_risk` has zero live callers (backtest only) — adding
unrealized MTM here would silently change circuit-breaker/sizing semantics,
which is explicitly out of scope for this PR. `RiskManager` does not hold a
reference to the position manager, so it cannot compute
sum(open-position realized_pnl) itself; the engine takes that number as an
injected scalar (`open_realized_pnl`) that the CALLER computes and passes
in. In production that caller is `multi_strategy_main.py`, which owns
`pos_mgr` and can sum `pos.realized_pnl` over open positions (this mirrors
how TP1 partial legs land in the accumulator today: msm:3805 books them
per-event while the ledger only gets a row on full close, msm:4145).

The three `reconcile()` correction terms fix the three known false-alarm
sources in the existing (pre-PR-2) drift comparator:

  - open_realized_pnl: TP1 legs already hit the accumulator per-event but
    the ledger has no row for them yet (row only written on full close).
    Without this term, every open TP1'd position looks like phantom drift.
  - pending_pnl: the just-closed trade's net PnL during the narrow window
    where equity has been booked (risk.py update_equity) but the ledger row
    for that same close hasn't been written yet (fixed properly in PR-3's
    ordering fix; this term lets a caller absorb the window in the
    meantime).
  - funding_addback: sum of in-epoch funding (`get_run_stats()["funding"]`)
    added back while `EQUITY_DEDUCT_FUNDING` is false — ledger net_pnl
    already includes funding per the ledger identity
    (gross - fees + funding == net), so when the accumulator doesn't
    deduct funding separately this term keeps the two sides comparable.

This PR does not change what any decision reads: `derive()`/`reconcile()`
are pure functions over already-computed inputs, called nowhere yet except
the (behavior-preserving) delegation in `execution/risk.py`'s existing
`compute_ledger_drift()`.
"""
from pathlib import Path
from typing import Any, Dict, Optional


class EquityEngine:
    """Thin, stateless façade over `data.trade_source.get_run_stats()`.

    Every method is read-only: no writes, no network calls, no mutation of
    any RiskManager/position-manager state. Instantiate freely — there is
    no per-instance state to share or reuse.
    """

    def derive(
        self,
        open_realized_pnl: float = 0.0,
        ledger_path: Optional[Path] = None,
    ) -> Optional[float]:
        """Live derived equity = get_run_stats(epoch=True)["derived_equity"]
        + open_realized_pnl.

        Returns None when the active epoch has no `epoch_equity` baseline
        stamped yet (`data/epoch.py::get_active_epoch()["epoch_equity"] is
        None`) — NEVER a fabricated number. Callers must fall back to the
        accumulator in that case, exactly like `trade_source.derive_equity`
        already documents.

        Args:
            open_realized_pnl: sum of `realized_pnl` over currently-open
                positions (e.g. TP1 legs already booked to the accumulator
                but not yet ledgered). Caller-supplied — see module
                docstring's OPEN-position policy. Default 0.0 preserves
                today's ledger-only view.
            ledger_path: override the ledger file (tests only).
        """
        from data.trade_source import get_run_stats

        stats = get_run_stats(epoch=True, ledger_path=ledger_path)
        derived = stats.get("derived_equity")
        if derived is None:
            return None
        return derived + open_realized_pnl

    def reconcile(
        self,
        accumulator: float,
        open_realized_pnl: float = 0.0,
        pending_pnl: float = 0.0,
        funding_addback: float = 0.0,
        ledger_path: Optional[Path] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compare `accumulator` (typically `RiskManager.equity`) against
        ledger-derived truth, adjusted by the three correction terms.

            adjusted_drift = accumulator
                            - (derived + open_realized_pnl + pending_pnl
                               + funding_addback)

        Returns None when there's no epoch baseline to reconcile against
        (mirrors `derive()`'s None discipline) — same condition as today's
        `execution/risk.py::compute_ledger_drift()`.

        With all three correction terms left at their 0.0 defaults, this is
        BYTE-IDENTICAL to the pre-PR-2 `compute_ledger_drift` math
        (`accumulator - derived`) — the terms are inert plumbing until a
        caller (PR-4 observe-mode wiring) passes real values.

        Returns:
            {
              "accumulator": float,       # the input accumulator, as given
              "derived": float,            # get_run_stats()["derived_equity"]
              "adjusted_drift": float,     # accumulator - adjusted derived
              "epoch_id": str,
              "components": {
                  "open_realized_pnl": float,
                  "pending_pnl": float,
                  "funding_addback": float,
              },
            }
            or None.
        """
        from data.trade_source import get_run_stats

        stats = get_run_stats(epoch=True, ledger_path=ledger_path)
        derived = stats.get("derived_equity")
        if derived is None:
            return None
        adjusted_derived = derived + open_realized_pnl + pending_pnl + funding_addback
        adjusted_drift = accumulator - adjusted_derived
        return {
            "accumulator": accumulator,
            "derived": derived,
            "adjusted_drift": adjusted_drift,
            "epoch_id": stats.get("epoch_id", ""),
            "components": {
                "open_realized_pnl": open_realized_pnl,
                "pending_pnl": pending_pnl,
                "funding_addback": funding_addback,
            },
        }
