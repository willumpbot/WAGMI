"""
Execution Forensics: Analyze slippage, stop mechanics, fill rates.

Deep dive into why trades lose money: are stops hit in noise or at real reversals?
What's the slippage distribution by symbol/time/size? Are fills partial?
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.learning.execution_forensics")


class ExecutionForensics:
    """Audits execution quality to find friction losses."""

    def __init__(self, trades_csv_path: str = "data/trades.csv", data_dir: str = "data/learning"):
        self.trades_csv_path = trades_csv_path
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._report_file = os.path.join(data_dir, "execution_forensics.json")
        logger.info("[EXEC_FORENSICS] Initialized")

    def analyze_recent_trades(self, limit: int = 100) -> Dict[str, Any]:
        """
        Analyze last N trades for execution quality issues.

        Returns:
            {slippage_analysis, stop_mechanics, fill_analysis, recommendations}
        """
        logger.info(f"[EXEC_FORENSICS] Analyzing last {limit} trades")

        # TODO: Implementation
        # 1. Read trades.csv (last N)
        # 2. For each trade:
        #    - entry_slippage = (live_entry - snapshot_entry) / entry
        #    - exit_slippage = (exit_price - tp1/tp2/sl) if hit by stop
        #    - was it a clean loss (SL hit) vs trailing vs early exit?
        # 3. Group by:
        #    - Symbol (BTC/ETH/SOL/HYPE)
        #    - Time-of-day (UTC hour)
        #    - Size tier (<5, 5-7, 7+)
        #    - Regime (from trade_profile)
        # 4. Calculate:
        #    - Median slippage per group
        #    - % of SL hits in noise (confidence > 75% but regime=illiquid/unknown)
        #    - % of partial fills
        # 5. Identify worst-case combinations (e.g., "SOL 6-9pm EST = 2.3% avg slippage")

        findings = {
            "analyzed_trades": 0,
            "slippage_analysis": {
                "avg_entry_slippage": 0.0,
                "avg_exit_slippage": 0.0,
                "by_symbol": {},
                "by_time_of_day": {},
                "by_size_tier": {},
            },
            "stop_mechanics": {
                "total_sl_hits": 0,
                "sl_hits_in_noise": 0,
                "noise_percentage": 0.0,
            },
            "fill_analysis": {
                "partial_fills": 0,
                "full_fills": 0,
                "fill_rate": 0.0,
            },
            "recommendations": [],
            "high_priority_finding": None,
        }

        # TODO: If slippage > 1% on specific symbol+time, that's high priority
        # TODO: If >40% of stops hit in noise, recommend wider stops

        self._save_report(findings)
        return findings

    def _save_report(self, findings: Dict[str, Any]):
        try:
            with open(self._report_file, "w") as f:
                json.dump(findings, f, indent=2)
        except Exception as e:
            logger.error(f"[EXEC_FORENSICS] Failed to save report: {e}")

    def get_latest_report(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self._report_file):
            try:
                with open(self._report_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load report: {e}")
        return None
