"""
Learning Dashboard
Real-time monitoring of autonomous learning cycle progress.
"""

import json
from pathlib import Path
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LearningDashboard:
    """Monitor autonomous learning progress."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)

    def show_status(self):
        """Display current status of learning cycles."""

        print("\n" + "=" * 70)
        print("AUTONOMOUS LEARNING DASHBOARD")
        print("=" * 70 + "\n")

        # Check backtest results
        results_dir = self.data_dir / "backtest_results"
        if results_dir.exists():
            results = list(results_dir.glob("*.json"))
            print(f"[BACKTEST] Results: {len(results)} files")
            for result_file in sorted(results)[-3:]:
                size_kb = result_file.stat().st_size / 1024
                mod_time = datetime.fromtimestamp(result_file.stat().st_mtime)
                print(f"   - {result_file.name} ({size_kb:.1f} KB, {mod_time.strftime('%H:%M:%S')})")

        # Check knowledge base
        kb_file = self.data_dir / "agent_knowledge_base.json"
        if kb_file.exists():
            with open(kb_file) as f:
                kb = json.load(f)
            runs = kb.get("runs", [])
            print(f"\n[KNOWLEDGE] Base: {len(runs)} learning runs")
            if runs:
                latest_run = runs[-1]
                print(f"   Latest: {latest_run.get('run_id', 'unknown')}")
                print(f"   Patterns: {len(kb.get('accumulated_patterns', {}))} regimes tracked")

        # Check insights tracker
        insights_file = self.data_dir / "agent_insights_tracker.json"
        if insights_file.exists():
            with open(insights_file) as f:
                insights = json.load(f)
            cycles = insights.get("cycles", {})
            print(f"\n[INSIGHTS] Tracker: {len(cycles)} cycles analyzed")
            if cycles:
                latest_cycle_key = sorted(cycles.keys())[-1]
                print(f"   Latest: {latest_cycle_key}")

        # Check learning reports
        reports_dir = self.data_dir / "learning_reports"
        if reports_dir.exists():
            reports = list(reports_dir.glob("*.md"))
            print(f"\n[REPORTS] Generated: {len(reports)} reports")
            for report in sorted(reports)[-3:]:
                print(f"   - {report.name}")

        print("\n" + "=" * 70 + "\n")

    def show_learnings(self):
        """Display discovered patterns so far."""

        insights_file = self.data_dir / "agent_insights_tracker.json"
        if not insights_file.exists():
            print("No insights yet — waiting for first cycle completion...")
            return

        with open(insights_file) as f:
            insights = json.load(f)

        print("\n" + "=" * 70)
        print("DISCOVERED PATTERNS")
        print("=" * 70 + "\n")

        if not insights.get("consolidated_patterns", {}):
            print("(No patterns discovered yet — awaiting cycle completion)")
            return

        # Regime patterns
        if "regime_patterns" in insights.get("consolidated_patterns", {}):
            print("REGIME UNDERSTANDING:\n")
            for regime, pattern in insights["consolidated_patterns"]["regime_patterns"].items():
                avg_wr = pattern.get("avg_wr", 0)
                consistency = pattern.get("consistency", 0)
                num_obs = pattern.get("num_observations", 0)
                confidence_bar = "█" * int(consistency * 10) + "░" * (10 - int(consistency * 10))
                print(f"  {regime:25} | WR: {avg_wr:5.1f}% | {confidence_bar} {consistency:.0%} | {num_obs} obs")

        # Setup patterns
        if "setup_patterns" in insights.get("consolidated_patterns", {}):
            print("\nSETUP QUALITY:\n")
            for setup, pattern in insights["consolidated_patterns"]["setup_patterns"].items():
                avg_wr = pattern.get("avg_wr", 0)
                num_obs = pattern.get("num_observations", 0)
                print(f"  {setup:25} | WR: {avg_wr:5.1f}% | {num_obs} observations")

        # Hypotheses
        if insights.get("hypothesis_tracker", {}):
            high_conf = {
                k: v for k, v in insights["hypothesis_tracker"].items()
                if v.get("validation_confidence", 0) >= 60
            }
            if high_conf:
                print("\nVALIDATED HYPOTHESES (60%+ confidence):\n")
                for edge_name, hyp in high_conf.items():
                    conf = hyp.get("validation_confidence", 0)
                    cycles = len(hyp.get("observations", []))
                    print(f"  {edge_name:40} | {conf:.0f}% confidence | {cycles} cycles")

        print("\n" + "=" * 70 + "\n")

    def show_next_steps(self):
        """Display next steps in the learning process."""

        kb_file = self.data_dir / "agent_knowledge_base.json"
        if not kb_file.exists():
            print("\n[NEXT STEP] Run Cycle 1 (365-day backtest)")
            print("Command: python autonomous_learning_loop.py")
            return

        with open(kb_file) as f:
            kb = json.load(f)

        runs = kb.get("runs", [])
        cycles_done = len(runs)

        print(f"\n[PROGRESS] {cycles_done}/5 cycles complete\n")
        for i in range(1, 6):
            status = "[DONE]" if i <= cycles_done else "[TODO]"
            focus = [
                "Validate pipeline, baseline knowledge",
                "Build regime understanding",
                "Discover setup-conditional patterns",
                "Validate cross-regime interactions",
                "Confirm edges, full synthesis"
            ][i - 1]
            print(f"{status} Cycle {i}: {focus}")

        if cycles_done < 5:
            next_cycle = cycles_done + 1
            print(f"\n[NEXT] Start Cycle {next_cycle}")
            print(f"Command: python continuous_learning_orchestrator.py")

        print()


if __name__ == "__main__":
    dashboard = LearningDashboard()
    dashboard.show_status()
    dashboard.show_learnings()
    dashboard.show_next_steps()
