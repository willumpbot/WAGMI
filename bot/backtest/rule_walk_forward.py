"""
Walk-Forward Rule Confidence Scorer (Lever 3)

Validates graduated rules by testing whether their performance holds out-of-sample.

Methodology:
  1. Partition time into train/test windows (e.g. 30-day train, 15-day test)
  2. Run LLM backtest on each window; extract which rules fired and outcomes
  3. Compute in-sample WR vs out-of-sample WR per rule
  4. Score = OOS_WR / IS_WR  (>0.8 = real edge, <0.5 = overfit)
  5. Output rule_confidence_scores.json for operator review

Usage:
    python -c "
    import sys; sys.path.insert(0,'.')
    from backtest.rule_walk_forward import RuleWalkForward
    wf = RuleWalkForward(symbols=['BTC'], budget_per_window=2.0)
    scores = wf.run(windows=3, train_days=30, test_days=15)
    wf.save_scores(scores)
    "
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.backtest.rule_walk_forward")

_OUTPUT_DIR = Path(__file__).parent.parent / "analysis" / "walk_forward"
_SCORES_PATH = _OUTPUT_DIR / "rule_confidence_scores.json"


@dataclass
class RuleWindowStats:
    """Performance stats for a single rule in a single time window."""
    rule_id: str
    window_type: str   # "train" or "test"
    window_idx: int
    fires: int = 0     # times the rule fired
    wins: int = 0      # times outcome was win (for boost/penalize context)
    vetoes: int = 0    # times the rule vetoed a signal
    veto_saves: int = 0  # vetoes where counterfactual showed price moved against

    @property
    def wr(self) -> float:
        return self.wins / self.fires if self.fires > 0 else 0.0


@dataclass
class RuleConfidenceScore:
    """Cross-window confidence score for a graduated rule."""
    rule_id: str
    action: str          # "veto", "boost", "penalize"
    is_fires: int = 0    # in-sample total fires
    is_wins: int = 0
    oos_fires: int = 0   # out-of-sample total fires
    oos_wins: int = 0
    n_windows: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_wr(self) -> float:
        return self.is_wins / self.is_fires if self.is_fires > 0 else 0.0

    @property
    def oos_wr(self) -> float:
        return self.oos_wins / self.oos_fires if self.oos_fires > 0 else 0.0

    @property
    def confidence(self) -> float:
        """OOS/IS ratio. >0.8 = real edge, 0.5-0.8 = marginal, <0.5 = suspect."""
        if self.is_fires < 5 or self.oos_fires < 3:
            return -1.0  # insufficient data
        if self.is_wr <= 0:
            return 1.0  # rule never wins in-sample — OOS also likely 0
        return min(2.0, self.oos_wr / self.is_wr)

    @property
    def verdict(self) -> str:
        c = self.confidence
        if c < 0:
            return "insufficient_data"
        if c >= 0.8:
            return "validated"
        if c >= 0.5:
            return "marginal"
        return "suspect_overfit"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "action": self.action,
            "is_fires": self.is_fires,
            "is_wr": round(self.is_wr, 3),
            "oos_fires": self.oos_fires,
            "oos_wr": round(self.oos_wr, 3),
            "confidence": round(self.confidence, 3),
            "verdict": self.verdict,
            "n_windows": self.n_windows,
            "timestamp": self.timestamp,
        }


class RuleWalkForward:
    """
    Walk-forward validator for graduated trading rules.

    Runs LLM backtests across sliding time windows, tracks which rules
    fired and their outcomes, then computes OOS confidence scores.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        budget_per_window: float = 2.0,
        raw_mode: bool = True,
    ):
        self.symbols = symbols or ["BTC"]
        self.budget_per_window = budget_per_window
        self.raw_mode = raw_mode

    def run(
        self,
        windows: int = 3,
        train_days: int = 30,
        test_days: int = 15,
        start_offset_days: int = 0,
    ) -> List[RuleConfidenceScore]:
        """
        Run walk-forward validation.

        Args:
            windows: Number of train/test pairs to run
            train_days: Days per training window
            test_days: Days per test window
            start_offset_days: Days to offset from today (0 = most recent)

        Returns:
            List of RuleConfidenceScore objects, one per graduated rule
        """
        logger.info(
            f"[WF] Starting rule walk-forward: {windows} windows × "
            f"({train_days}d train + {test_days}d test) on {self.symbols}"
        )

        # Collect per-window, per-rule stats
        all_stats: Dict[str, List[RuleWindowStats]] = {}

        for w in range(windows):
            # Calculate window date range (going back from today)
            total_offset = start_offset_days + w * (train_days + test_days)
            test_end_offset = total_offset
            test_start_offset = total_offset + test_days
            train_end_offset = test_start_offset
            train_start_offset = train_end_offset + train_days

            train_end = self._offset_date(train_end_offset)
            train_start = self._offset_date(train_start_offset)
            test_end = self._offset_date(test_end_offset)
            test_start = self._offset_date(test_start_offset)

            logger.info(
                f"[WF] Window {w+1}/{windows}: "
                f"train={train_start}→{train_end}, test={test_start}→{test_end}"
            )

            # Run training window
            train_stats = self._run_window(
                start_date=train_start,
                days=train_days,
                window_type="train",
                window_idx=w,
            )
            for rule_id, stat in train_stats.items():
                if rule_id not in all_stats:
                    all_stats[rule_id] = []
                all_stats[rule_id].append(stat)

            # Run test window
            test_stats = self._run_window(
                start_date=test_start,
                days=test_days,
                window_type="test",
                window_idx=w,
            )
            for rule_id, stat in test_stats.items():
                if rule_id not in all_stats:
                    all_stats[rule_id] = []
                all_stats[rule_id].append(stat)

        return self._compute_scores(all_stats, windows)

    def _run_window(
        self,
        start_date: str,
        days: int,
        window_type: str,
        window_idx: int,
    ) -> Dict[str, RuleWindowStats]:
        """Run a single backtest window and extract rule firing stats."""
        try:
            from backtest.engine import BacktestEngine
            from backtest.llm_integration import BacktestLLMIntegration
            from trading_config import TradingConfig

            llm = BacktestLLMIntegration(
                budget_usd=self.budget_per_window,
                raw_mode=self.raw_mode,
            )
            config = TradingConfig()
            engine = BacktestEngine(config=config, llm_integration=llm, fresh=True)

            raw_report = engine.run(
                symbols=self.symbols,
                days=days,
                start_date=start_date,
            )

            # Extract rule firing stats from backtest decisions
            return self._extract_rule_stats(raw_report, window_type, window_idx)

        except Exception as e:
            logger.error(f"[WF] Window {window_type}[{window_idx}] failed: {e}")
            return {}

    def _extract_rule_stats(
        self,
        report: Dict[str, Any],
        window_type: str,
        window_idx: int,
    ) -> Dict[str, RuleWindowStats]:
        """Extract per-rule stats from a backtest report.

        The backtest engine logs graduated_rule decisions in decisions.jsonl.
        We also look at the trade timeline for win/loss outcomes.
        """
        stats: Dict[str, RuleWindowStats] = {}

        # Load the graduated rules to get action types
        try:
            from llm.graduated_rules import get_graduated_rules_engine
            gre = get_graduated_rules_engine()
            gre._ensure_loaded()
            rule_actions = {r.rule_id: r.action for r in gre._rules}
        except Exception:
            rule_actions = {}

        # Parse decisions log for rule firings
        decisions_path = Path("data/llm/backtest_decisions.jsonl")
        if decisions_path.exists():
            with open(decisions_path) as f:
                recent_decisions = [
                    json.loads(line) for line in f
                    if line.strip()
                ]

            # Filter to decisions with graduated rule info
            for dec in recent_decisions[-5000:]:  # look at recent entries
                skip_reason = dec.get("skip_reason", "")
                notes = dec.get("notes", "")
                # Look for graduated rule fingerprints in notes
                for rule_id in rule_actions:
                    if rule_id in notes or rule_id in skip_reason:
                        if rule_id not in stats:
                            stats[rule_id] = RuleWindowStats(
                                rule_id=rule_id,
                                window_type=window_type,
                                window_idx=window_idx,
                            )
                        stats[rule_id].fires += 1
                        action = rule_actions.get(rule_id, "")
                        if action == "veto":
                            stats[rule_id].vetoes += 1

        # Cross-reference with trade timeline for win/loss
        trades = report.get("trade_timeline", [])
        for trade in trades:
            pnl = trade.get("pnl", 0)
            notes = str(trade.get("notes", "")) + str(trade.get("metadata", ""))
            for rule_id in stats:
                if rule_id in notes:
                    if pnl > 0:
                        stats[rule_id].wins += 1

        logger.info(
            f"[WF] Window {window_type}[{window_idx}]: "
            f"extracted {len(stats)} rule firing records from backtest"
        )
        return stats

    def _compute_scores(
        self,
        all_stats: Dict[str, List[RuleWindowStats]],
        windows: int,
    ) -> List[RuleConfidenceScore]:
        """Aggregate per-window stats into cross-window confidence scores."""
        try:
            from llm.graduated_rules import get_graduated_rules_engine
            gre = get_graduated_rules_engine()
            gre._ensure_loaded()
            rule_actions = {r.rule_id: r.action for r in gre._rules}
        except Exception:
            rule_actions = {}

        scores = []
        for rule_id, window_stats_list in all_stats.items():
            score = RuleConfidenceScore(
                rule_id=rule_id,
                action=rule_actions.get(rule_id, "unknown"),
                n_windows=windows,
            )
            for ws in window_stats_list:
                if ws.window_type == "train":
                    score.is_fires += ws.fires
                    score.is_wins += ws.wins
                else:
                    score.oos_fires += ws.fires
                    score.oos_wins += ws.wins
            scores.append(score)

        # Sort: validated first, then marginal, then suspect
        verdict_order = {"validated": 0, "marginal": 1, "suspect_overfit": 2, "insufficient_data": 3}
        scores.sort(key=lambda s: verdict_order.get(s.verdict, 4))
        return scores

    def save_scores(self, scores: List[RuleConfidenceScore]) -> str:
        """Save scores to analysis/walk_forward/rule_confidence_scores.json."""
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "symbols": self.symbols,
            "rules": [s.to_dict() for s in scores],
            "summary": {
                "total_rules": len(scores),
                "validated": sum(1 for s in scores if s.verdict == "validated"),
                "marginal": sum(1 for s in scores if s.verdict == "marginal"),
                "suspect": sum(1 for s in scores if s.verdict == "suspect_overfit"),
                "insufficient": sum(1 for s in scores if s.verdict == "insufficient_data"),
            },
        }
        with open(_SCORES_PATH, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[WF] Saved rule confidence scores to {_SCORES_PATH}")
        return str(_SCORES_PATH)

    @staticmethod
    def _offset_date(days_back: int) -> str:
        """Return YYYY-MM-DD string for `days_back` days ago."""
        dt = datetime.now(timezone.utc) - timedelta(days=days_back)
        return dt.strftime("%Y-%m-%d")

    @classmethod
    def load_existing_scores(cls) -> Optional[Dict]:
        """Load existing scores file if it exists."""
        if _SCORES_PATH.exists():
            with open(_SCORES_PATH) as f:
                return json.load(f)
        return None

    @classmethod
    def print_report(cls, scores: Optional[List[RuleConfidenceScore]] = None) -> None:
        """Print a human-readable summary of scores."""
        if scores is None:
            data = cls.load_existing_scores()
            if not data:
                print("No walk-forward scores found. Run RuleWalkForward().run() first.")
                return
            print(f"\n=== Rule Walk-Forward Confidence Report ===")
            print(f"Generated: {data.get('generated', 'unknown')}")
            print(f"Symbols: {data.get('symbols', [])}")
            print()
            s = data.get("summary", {})
            print(f"Summary: {s.get('validated',0)} validated, "
                  f"{s.get('marginal',0)} marginal, "
                  f"{s.get('suspect',0)} suspect, "
                  f"{s.get('insufficient',0)} insufficient data")
            print()
            print(f"{'Rule ID':<35} {'Action':<10} {'IS fires':>8} {'IS WR':>7} "
                  f"{'OOS fires':>10} {'OOS WR':>8} {'Confidence':>11} {'Verdict':<20}")
            print("-" * 110)
            for r in data.get("rules", []):
                conf = r.get("confidence", -1)
                conf_str = f"{conf:.2f}" if conf >= 0 else "  N/A"
                print(
                    f"{r['rule_id']:<35} {r['action']:<10} "
                    f"{r['is_fires']:>8} {r['is_wr']:>7.1%} "
                    f"{r['oos_fires']:>10} {r['oos_wr']:>8.1%} "
                    f"{conf_str:>11} {r['verdict']:<20}"
                )
            return

        print(f"\n=== Rule Walk-Forward Confidence Report ({len(scores)} rules) ===")
        for s in scores:
            print(f"  {s.rule_id}: IS={s.is_wr:.1%}(n={s.is_fires}) "
                  f"OOS={s.oos_wr:.1%}(n={s.oos_fires}) "
                  f"conf={s.confidence:.2f} [{s.verdict}]")
