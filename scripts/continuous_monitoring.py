#!/usr/bin/env python3
"""
Continuous Monitoring Loop — Autonomous learning that runs in background.

Runs continuously, checking for new trade data every 60 seconds.
On each iteration:
1. Load latest trades
2. Compute metrics
3. Compare to previous metrics
4. Flag anomalies
5. Update KB

Can be backgrounded: python continuous_monitoring.py > monitoring.log 2>&1 &
"""

import csv
import json
import os
import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

class MonitoringSession:
    def __init__(self, data_dir="./bot/data"):
        self.data_dir = data_dir
        self.trades_file = f"{data_dir}/trades.csv"
        self.kb_file = f"{data_dir}/monitoring_kb.json"
        self.last_trade_count = 0
        self.iteration = 0
        self.session_start = datetime.utcnow()
        self.load_or_init_kb()

    def load_or_init_kb(self):
        """Load KB or initialize if missing."""
        if os.path.exists(self.kb_file):
            try:
                with open(self.kb_file) as f:
                    self.kb = json.load(f)
            except:
                self.kb = self.init_kb()
        else:
            self.kb = self.init_kb()

    def init_kb(self):
        """Initialize empty KB."""
        return {
            'session_start': self.session_start.isoformat(),
            'iterations': 0,
            'last_update': None,
            'alerts': [],
            'metrics_history': [],
            'trade_count_history': [],
        }

    def save_kb(self):
        """Save KB to disk."""
        with open(self.kb_file, 'w') as f:
            json.dump(self.kb, f, indent=2, default=str)

    def load_trades(self):
        """Load all trades from CSV."""
        if not os.path.exists(self.trades_file):
            return []

        trades = []
        try:
            with open(self.trades_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        trades.append({
                            'timestamp': row.get('timestamp', ''),
                            'symbol': row.get('symbol', ''),
                            'side': row.get('side', ''),
                            'pnl': float(row.get('pnl', 0)),
                            'regime': row.get('regime', ''),
                            'strategy': row.get('strategy', ''),
                            'leverage': float(row.get('leverage', 0)),
                            'confidence': float(row.get('confidence', 0)),
                        })
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            self.log(f"ERROR loading trades: {e}")
            return []

        return trades

    def compute_metrics(self, trades):
        """Compute current metrics."""
        if not trades:
            return None

        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'trade_count': len(trades),
            'total_pnl': sum(t['pnl'] for t in trades),
            'win_rate': sum(1 for t in trades if t['pnl'] > 0) / len(trades),
            'by_regime': {},
            'by_symbol': {},
            'by_strategy': {},
        }

        # By regime
        regime_pnl = defaultdict(float)
        regime_count = defaultdict(int)
        for t in trades:
            regime = t['regime'] or 'unknown'
            regime_pnl[regime] += t['pnl']
            regime_count[regime] += 1

        for regime in regime_pnl:
            metrics['by_regime'][regime] = {
                'pnl': regime_pnl[regime],
                'count': regime_count[regime],
                'wr': sum(1 for t in trades if t['regime'] == regime and t['pnl'] > 0) / regime_count[regime],
            }

        # By symbol
        symbol_pnl = defaultdict(float)
        symbol_count = defaultdict(int)
        for t in trades:
            symbol = t['symbol']
            symbol_pnl[symbol] += t['pnl']
            symbol_count[symbol] += 1

        for symbol in symbol_pnl:
            metrics['by_symbol'][symbol] = {
                'pnl': symbol_pnl[symbol],
                'count': symbol_count[symbol],
                'wr': sum(1 for t in trades if t['symbol'] == symbol and t['pnl'] > 0) / symbol_count[symbol],
            }

        # By strategy
        strategy_pnl = defaultdict(float)
        strategy_count = defaultdict(int)
        for t in trades:
            strategy = t['strategy']
            strategy_pnl[strategy] += t['pnl']
            strategy_count[strategy] += 1

        for strategy in strategy_pnl:
            metrics['by_strategy'][strategy] = {
                'pnl': strategy_pnl[strategy],
                'count': strategy_count[strategy],
                'wr': sum(1 for t in trades if t['strategy'] == strategy and t['pnl'] > 0) / strategy_count[strategy],
            }

        return metrics

    def check_anomalies(self, metrics, prev_metrics):
        """Check for anomalies vs previous metrics."""
        alerts = []

        if not prev_metrics:
            return alerts

        # Check for drawdown
        prev_wr = prev_metrics.get('win_rate', 0)
        curr_wr = metrics.get('win_rate', 0)
        if curr_wr < prev_wr - 0.1:
            alerts.append({
                'type': 'win_rate_drop',
                'severity': 'warning',
                'message': f'WR dropped {prev_wr*100:.1f}% -> {curr_wr*100:.1f}%',
                'timestamp': datetime.utcnow().isoformat(),
            })

        # Check for new losing symbol
        curr_symbols = set(metrics['by_symbol'].keys())
        prev_symbols = set(prev_metrics['by_symbol'].keys())
        for sym in curr_symbols:
            if sym in prev_symbols:
                curr_pnl = metrics['by_symbol'][sym]['pnl']
                prev_pnl = prev_metrics['by_symbol'][sym]['pnl']
                if curr_pnl < prev_pnl - 100:  # Lost >$100 since last check
                    alerts.append({
                        'type': 'symbol_drawdown',
                        'symbol': sym,
                        'severity': 'warning',
                        'pnl_change': curr_pnl - prev_pnl,
                        'timestamp': datetime.utcnow().isoformat(),
                    })

        return alerts

    def log(self, message):
        """Print timestamped log message."""
        ts = datetime.utcnow().isoformat()
        print(f"[{ts}] {message}")

    def iterate(self):
        """Run one monitoring iteration."""
        self.iteration += 1
        now = datetime.utcnow()

        self.log(f"--- Iteration {self.iteration} ---")

        # Load trades
        trades = self.load_trades()
        self.log(f"Loaded {len(trades)} trades")

        if len(trades) == self.last_trade_count and self.iteration > 1:
            self.log(f"No new trades (still {len(trades)} total)")
            return

        if len(trades) > self.last_trade_count:
            new_trades = len(trades) - self.last_trade_count
            self.log(f"NEW: +{new_trades} trades")

        # Compute metrics
        metrics = self.compute_metrics(trades)
        if not metrics:
            self.log("ERROR: Could not compute metrics")
            return

        self.log(f"PnL: ${metrics['total_pnl']:.2f} | WR: {metrics['win_rate']*100:.1f}% | Trades: {metrics['trade_count']}")

        # Check for anomalies
        prev_metrics = self.kb['metrics_history'][-1] if self.kb['metrics_history'] else None
        alerts = self.check_anomalies(metrics, prev_metrics)
        if alerts:
            for alert in alerts:
                self.kb['alerts'].append(alert)
                self.log(f"ALERT: {alert['message']}")

        # Update KB
        self.kb['iterations'] += 1
        self.kb['last_update'] = now.isoformat()
        self.kb['trade_count_history'].append(len(trades))
        self.kb['metrics_history'].append(metrics)

        # Keep history to last 100 iterations
        if len(self.kb['metrics_history']) > 100:
            self.kb['metrics_history'] = self.kb['metrics_history'][-100:]
        if len(self.kb['alerts']) > 1000:
            self.kb['alerts'] = self.kb['alerts'][-1000:]

        self.last_trade_count = len(trades)
        self.save_kb()
        self.log(f"KB updated ({len(self.kb['alerts'])} alerts)")

    def run(self, interval_seconds=60):
        """Run continuous monitoring loop."""
        self.log(f"Starting continuous monitoring (interval: {interval_seconds}s)")

        try:
            while True:
                self.iterate()
                self.log(f"Sleeping {interval_seconds}s until next iteration...")
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            self.log("Monitoring stopped by user")
        except Exception as e:
            self.log(f"ERROR: {e}")
            raise

def main():
    session = MonitoringSession()
    session.run(interval_seconds=60)

if __name__ == '__main__':
    main()
