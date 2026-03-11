"""
Filter annotations: converts hard signal rejections into rich context for LLM agents.

Instead of silently killing signals, each filter produces a FilterAnnotation that
tells the LLM what was measured, what the threshold is, and whether it would have
been rejected. The LLM then decides whether to proceed, adjust size, or skip.

Safety-critical gates (circuit breaker, max positions, liquidation) remain hard
rejects and cannot be overridden.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class FilterAnnotation:
    """One filter's assessment of a signal."""
    gate: str           # "rr_floor", "fee_drag", "ev_floor", "correlation", etc.
    passed: bool        # Would have passed the old hard filter?
    severity: str       # "ok" | "warning" | "reject"
    value: float        # Actual measured value
    threshold: float    # Threshold compared against
    detail: str         # Compact: "fee_drag=34%>30%"

    def to_compact(self) -> str:
        """Token-efficient string: 'fd:34%!' for reject, 'fd:18%' for ok."""
        # Short gate names
        _short = {
            "rr_floor": "rr",
            "fee_drag": "fd",
            "ev_floor": "ev",
            "correlation": "cr",
            "lev_ev_floor": "lev_ev",
            "confidence_floor": "conf",
            "chop_floor": "chop",
            "trend_alignment": "trend",
            "regime_filter": "regime",
            "adx_min": "adx",
            "squeeze": "sqz",
            "volume_chop": "vol",
            "neutral_regime": "neutral",
        }
        short_gate = _short.get(self.gate, self.gate[:4])

        if self.severity == "reject":
            return f"{short_gate}:{self._fmt_val()}!"
        elif self.severity == "warning":
            return f"{short_gate}:{self._fmt_val()}?"
        else:
            return f"{short_gate}:{self._fmt_val()}"

    def _fmt_val(self) -> str:
        """Format value compactly."""
        if self.gate in ("fee_drag",):
            return f"{self.value:.0f}%"
        elif self.gate in ("ev_floor", "lev_ev_floor"):
            return f"{self.value:.2f}"
        elif self.gate in ("rr_floor",):
            return f"{self.value:.1f}"
        elif self.gate in ("correlation",):
            return f"{self.value:.2f}"
        elif self.gate in ("confidence_floor", "chop_floor", "ranging_confidence_floor"):
            return f"{self.value:.0f}"
        elif self.gate in ("trend_alignment",):
            return f"{self.value:+.1f}"
        elif self.gate in ("adx_min",):
            return f"{self.value:.0f}"
        else:
            return f"{self.value:.2f}"


@dataclass
class AnnotatedSignal:
    """A signal enriched with filter assessments instead of being silently killed."""
    signal: Any  # strategies.base.Signal
    annotations: List[FilterAnnotation] = field(default_factory=list)
    hard_rejected: bool = False
    hard_rejection_reason: str = ""
    filter_metadata: Dict[str, Any] = field(default_factory=dict)
    # Pipeline evaluation results (only set if not hard-rejected)
    leverage: float = 1.0
    risk_multiplier: float = 1.0
    position_qty: float = 0.0

    @property
    def soft_rejected(self) -> bool:
        """Would have been rejected by the old hard-filter pipeline."""
        return any(a.severity == "reject" for a in self.annotations)

    @property
    def num_warnings(self) -> int:
        return sum(1 for a in self.annotations if a.severity == "warning")

    @property
    def num_rejects(self) -> int:
        return sum(1 for a in self.annotations if a.severity == "reject")

    @property
    def passed_all(self) -> bool:
        """Signal passes all filters (no rejects, no hard rejection)."""
        return not self.hard_rejected and not self.soft_rejected

    def to_compact_dict(self) -> dict:
        """Token-efficient format for LLM snapshot.

        Example:
        {
            "passed": true,
            "flags": "rr:2.1 ev:0.24 fd:18% cr:0.62",
            "rejects": "fd:34%! ev:0.14!",
            "meta": {"leverage": 5.0, "lev_tier": "moderate"}
        }
        """
        ok_flags = []
        reject_flags = []
        warning_flags = []

        for a in self.annotations:
            compact = a.to_compact()
            if a.severity == "reject":
                reject_flags.append(compact)
            elif a.severity == "warning":
                warning_flags.append(compact)
            else:
                ok_flags.append(compact)

        result = {
            "passed": self.passed_all,
        }
        if self.hard_rejected:
            result["hard_reject"] = self.hard_rejection_reason[:60]

        # Compact flag strings
        if ok_flags:
            result["ok"] = " ".join(ok_flags)
        if warning_flags:
            result["warn"] = " ".join(warning_flags)
        if reject_flags:
            result["reject"] = " ".join(reject_flags)

        # Useful metadata for LLM sizing decisions
        if self.filter_metadata:
            meta = {}
            for k in ("leverage", "leverage_tier", "risk_multiplier",
                       "fee_drag_pct", "ev_per_dollar", "cluster_risk",
                       "liq_gap_pct", "chop_score_smoothed",
                       "effective_confidence_floor", "trend_score"):
                if k in self.filter_metadata:
                    meta[k] = self.filter_metadata[k]
            if meta:
                result["meta"] = meta

        return result

    def to_compact_str(self) -> str:
        """Single-line string for log/debug: 'PASS rr:2.1 ev:0.24 fd:18%' or 'REJECT fd:34%! ev:0.14!'"""
        all_flags = [a.to_compact() for a in self.annotations]
        prefix = "HARD_REJECT" if self.hard_rejected else ("REJECT" if self.soft_rejected else "PASS")
        return f"{prefix} {' '.join(all_flags)}"
