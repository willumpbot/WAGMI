"""
Build comprehensive knowledge base from backtest cycles.
Extract signal-level data, patterns, and insights for agent learning.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
import re
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class KnowledgeBaseBuilder:
    """Consolidate backtest results into agent learning knowledge base."""

    def __init__(self, kb_file: str = "data/agent_knowledge_base.json"):
        self.kb_file = Path(kb_file)
        self.kb = self._load_or_create_kb()

    def _load_or_create_kb(self) -> Dict[str, Any]:
        """Load existing KB or create new one."""
        if self.kb_file.exists():
            with open(self.kb_file) as f:
                return json.load(f)
        return {
            "created": "2026-04-28",
            "purpose": "Accumulate agent learning across multiple autonomous cycles",
            "runs": [],
            "cycles": [],
            "accumulated_patterns": {},
            "regime_patterns": {},
            "setup_patterns": {},
            "symbol_edges": {},
            "strategy_consensus": {},
            "meta_learnings": [],
        }

    def ingest_cycle(self, cycle_file: Path, cycle_num: int) -> Dict[str, Any]:
        """Ingest a single cycle's backtest results into KB."""
        logger.info(f"\nIngesting Cycle {cycle_num}: {cycle_file.name}")

        with open(cycle_file) as f:
            backtest_data = json.load(f)

        raw_output = backtest_data.get("raw_output", "")
        run_id = backtest_data.get("metrics", {}).get("run_id", f"cycle_{cycle_num}")

        # Extract all dimensional data
        cycle_insights = {
            "cycle_num": cycle_num,
            "run_id": run_id,
            "timestamp": backtest_data.get("metrics", {}).get("timestamp"),
            "metrics": self._extract_metrics(raw_output),
            "regime_breakdown": self._extract_regime_breakdown(raw_output),
            "symbol_breakdown": self._extract_symbol_breakdown(raw_output),
            "setup_breakdown": self._extract_setup_breakdown(raw_output),
            "confidence_patterns": self._extract_confidence_patterns(raw_output),
            "hidden_alpha": self._extract_hidden_alpha(raw_output),
            "strategy_health": self._extract_strategy_health(raw_output),
        }

        # Record in KB
        self.kb["runs"].append(cycle_insights)

        # Accumulate patterns
        self._accumulate_patterns(cycle_insights)

        logger.info(f"  ✓ Ingested: {cycle_insights['metrics'].get('signals_generated', 0)} signals")
        logger.info(f"  ✓ Regime patterns: {len(cycle_insights['regime_breakdown'])} regimes")
        logger.info(f"  ✓ Hidden alpha: {len(cycle_insights['hidden_alpha'])} disabled strategies with edges")

        return cycle_insights

    def _extract_metrics(self, raw_output: str) -> Dict[str, Any]:
        """Extract key performance metrics."""
        metrics = {}

        # Parse structured output - look for key metrics
        lines = raw_output.split('\n')
        for line in lines:
            # Signal funnel
            if 'Signal gen:' in line:
                match = re.search(r'(\d+,?\d*)\s*\(', line)
                if match:
                    metrics['signals_generated'] = int(match.group(1).replace(',', ''))

            elif 'Executed:' in line and 'Signal gen' not in lines[max(0, lines.index(line)-1)]:
                match = re.search(r'Executed:\s+(\d+)', line)
                if match:
                    metrics['trades_executed'] = int(match.group(1))

            elif 'Win Rate:' in line and 'by position' in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    metrics['win_rate'] = float(match.group(1))

            elif line.strip().startswith('Gross PnL:'):
                match = re.search(r'\$([\d,\-\.]+)', line)
                if match:
                    metrics['gross_pnl'] = float(match.group(1).replace(',', ''))

            elif line.strip().startswith('Net PnL:'):
                match = re.search(r'\$([\d,\-\.]+)', line)
                if match:
                    metrics['net_pnl'] = float(match.group(1).replace(',', ''))

        return metrics

    def _extract_regime_breakdown(self, raw_output: str) -> Dict[str, Any]:
        """Extract per-regime performance."""
        regimes = {}

        lines = raw_output.split('\n')
        in_section = False

        for i, line in enumerate(lines):
            if 'BY REGIME' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'BY SYMBOL' in line or 'BY HOUR' in line:
                    break

                # Look for regime lines with performance data
                for regime in ['trending_bull', 'trending_bear', 'ranging', 'consolidation', 'volatile']:
                    if regime in line.lower():
                        try:
                            parts = line.split()
                            idx = parts.index('trades') if 'trades' in parts else -1
                            if idx > 0:
                                trades = int(parts[idx-1])
                                wr_idx = parts.index('WR') if 'WR' in parts else -1
                                if wr_idx > 0:
                                    wr = float(parts[wr_idx+1].rstrip('%'))
                                    pnl_idx = parts.index('PnL') if 'PnL' in parts else -1
                                    if pnl_idx > 0:
                                        pnl_str = parts[pnl_idx+1].replace('$', '').replace(',', '')
                                        pnl = float(pnl_str)

                                        regimes[regime] = {
                                            'trades': trades,
                                            'win_rate': wr,
                                            'pnl': pnl,
                                        }
                        except (ValueError, IndexError):
                            pass

        return regimes

    def _extract_symbol_breakdown(self, raw_output: str) -> Dict[str, Any]:
        """Extract per-symbol performance."""
        symbols = {}

        lines = raw_output.split('\n')
        in_section = False

        for line in lines:
            if 'BY SYMBOL' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'BY REGIME' in line or 'STRATEGY' in line:
                    break

                for symbol in ['BTC', 'ETH', 'SOL', 'HYPE']:
                    if symbol + ':' in line:
                        try:
                            parts = line.split(',')
                            # Extract events
                            events_str = parts[0].split()[-1]
                            events = int(events_str)

                            # Extract WR
                            wr_str = parts[1].strip().split('%')[0].split()[-1]
                            wr = float(wr_str)

                            # Extract PnL
                            pnl_str = parts[2].split('$')[1].strip().split()[0]
                            pnl = float(pnl_str)

                            symbols[symbol] = {
                                'events': events,
                                'win_rate': wr,
                                'pnl': pnl,
                            }
                        except (ValueError, IndexError):
                            pass

        return symbols

    def _extract_setup_breakdown(self, raw_output: str) -> Dict[str, Any]:
        """Extract per-setup performance."""
        setups = {}

        lines = raw_output.split('\n')
        in_section = False

        for line in lines:
            if 'BY SETUP TYPE' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'BY HOLD' in line or 'RISK METRICS' in line:
                    break

                for setup in ['trend_follow', 'mean_reversion', 'breakout', 'support_resist']:
                    if setup in line.lower():
                        try:
                            parts = line.split()
                            idx = parts.index('trades') if 'trades' in parts else -1
                            if idx > 0:
                                trades = int(parts[idx-1])
                                wr_idx = parts.index('WR') if 'WR' in parts else -1
                                if wr_idx > 0:
                                    wr = float(parts[wr_idx+1].rstrip('%'))
                                    setups[setup] = {
                                        'trades': trades,
                                        'win_rate': wr,
                                    }
                        except (ValueError, IndexError):
                            pass

        return setups

    def _extract_confidence_patterns(self, raw_output: str) -> Dict[str, Any]:
        """Extract confidence-based performance."""
        confidence = {}

        lines = raw_output.split('\n')
        in_section = False

        for line in lines:
            if 'CONFIDENCE ANALYSIS' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'TRAILING' in line or 'CONFIDENCE -- REGIME' in line:
                    break

                # Look for confidence buckets
                match = re.search(r'(\d+-\d+)%:\s+(\d+)\s+positions?\s+([\d.]+)%\s+WR\s+\$([-\d,\.]+)', line)
                if match:
                    bucket = match.group(1)
                    positions = int(match.group(2))
                    wr = float(match.group(3))
                    pnl = float(match.group(4).replace(',', ''))

                    confidence[bucket] = {
                        'positions': positions,
                        'win_rate': wr,
                        'pnl': pnl,
                    }

        return confidence

    def _extract_hidden_alpha(self, raw_output: str) -> Dict[str, Any]:
        """Extract hidden alpha in disabled strategies."""
        hidden = {}

        lines = raw_output.split('\n')
        in_section = False

        for line in lines:
            if 'Solo Strategy Missed Trades' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'GATE' in line:
                    break

                for strategy in ['monte_carlo_zones', 'regime_trend', 'bollinger_squeeze', 'confidence_scorer', 'multi_tier_quality']:
                    if strategy in line:
                        try:
                            parts = line.split()
                            missed = int(parts[1])
                            won = int(parts[2])
                            lost = int(parts[3])
                            wr = float(parts[4].rstrip('%'))
                            alpha = float(parts[5].rstrip('%'))

                            hidden[strategy] = {
                                'missed_signals': missed,
                                'would_have_won': won,
                                'would_have_lost': lost,
                                'win_rate': wr,
                                'alpha_pct': alpha,
                            }
                        except (ValueError, IndexError):
                            pass

        return hidden

    def _extract_strategy_health(self, raw_output: str) -> Dict[str, Any]:
        """Extract per-strategy performance."""
        strategies = {}

        lines = raw_output.split('\n')
        in_section = False

        for line in lines:
            if 'STRATEGY HEALTH' in line:
                in_section = True
                continue

            if in_section:
                if '========' in line or 'STRATEGY COMBOS' in line:
                    break

                # Look for strategy lines
                match = re.search(r'(\w+)\s+PF=([\d.]+)\s+EV=\$([-\d,\.]+)\s+net=\$([-\d,\.]+)\s+WR=([\d.]+)%', line)
                if match:
                    strategy = match.group(1)
                    strategies[strategy] = {
                        'profit_factor': float(match.group(2)),
                        'expected_value': float(match.group(3).replace(',', '')),
                        'net_pnl': float(match.group(4).replace(',', '')),
                        'win_rate': float(match.group(5)),
                    }

        return strategies

    def _accumulate_patterns(self, cycle_insights: Dict[str, Any]):
        """Accumulate patterns across cycles."""
        cycle_num = cycle_insights.get('cycle_num')

        # Accumulate regime patterns
        for regime, data in cycle_insights['regime_breakdown'].items():
            if regime not in self.kb['regime_patterns']:
                self.kb['regime_patterns'][regime] = {
                    'observations': [],
                    'avg_wr': 0,
                    'consistency': 0,
                }
            self.kb['regime_patterns'][regime]['observations'].append({
                'cycle': cycle_num,
                'trades': data.get('trades', 0),
                'wr': data.get('win_rate', 0),
                'pnl': data.get('pnl', 0),
            })

        # Accumulate setup patterns
        for setup, data in cycle_insights['setup_breakdown'].items():
            if setup not in self.kb['setup_patterns']:
                self.kb['setup_patterns'][setup] = {
                    'observations': [],
                    'avg_wr': 0,
                }
            self.kb['setup_patterns'][setup]['observations'].append({
                'cycle': cycle_num,
                'trades': data.get('trades', 0),
                'wr': data.get('win_rate', 0),
            })

        # Accumulate symbol edges
        for symbol, data in cycle_insights['symbol_breakdown'].items():
            if symbol not in self.kb['symbol_edges']:
                self.kb['symbol_edges'][symbol] = {
                    'observations': [],
                    'avg_wr': 0,
                }
            self.kb['symbol_edges'][symbol]['observations'].append({
                'cycle': cycle_num,
                'events': data.get('events', 0),
                'wr': data.get('win_rate', 0),
            })

    def save_kb(self):
        """Save knowledge base to file."""
        # Calculate aggregates before saving
        for regime in self.kb['regime_patterns'].values():
            if regime['observations']:
                regime['avg_wr'] = sum(o['wr'] for o in regime['observations']) / len(regime['observations'])
                regime['consistency'] = self._calculate_consistency(
                    [o['wr'] for o in regime['observations']]
                )

        for setup in self.kb['setup_patterns'].values():
            if setup['observations']:
                setup['avg_wr'] = sum(o['wr'] for o in setup['observations']) / len(setup['observations'])

        for symbol in self.kb['symbol_edges'].values():
            if symbol['observations']:
                symbol['avg_wr'] = sum(o['wr'] for o in symbol['observations']) / len(symbol['observations'])

        with open(self.kb_file, 'w') as f:
            json.dump(self.kb, f, indent=2)

        logger.info(f"\n[SAVED] Knowledge base to {self.kb_file}")

    def _calculate_consistency(self, values: List[float]) -> float:
        """Calculate standard deviation as consistency measure."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        import math
        return math.sqrt(variance)

    def print_summary(self):
        """Print KB summary."""
        logger.info("\n" + "="*70)
        logger.info("KNOWLEDGE BASE SUMMARY")
        logger.info("="*70)

        logger.info(f"\nCycles Ingested: {len(self.kb['runs'])}")

        total_signals = sum(r['metrics'].get('signals_generated', 0) for r in self.kb['runs'])
        total_trades = sum(r['metrics'].get('trades_executed', 0) for r in self.kb['runs'])
        total_pnl = sum(r['metrics'].get('net_pnl', 0) for r in self.kb['runs'])

        logger.info(f"Total Signals: {total_signals:,}")
        logger.info(f"Total Trades: {total_trades}")
        logger.info(f"Total PnL: ${total_pnl:,.2f}")

        logger.info(f"\nRegime Patterns: {len(self.kb['regime_patterns'])}")
        for regime, data in self.kb['regime_patterns'].items():
            logger.info(
                f"  {regime}: {len(data['observations'])} obs, "
                f"avg WR={data.get('avg_wr', 0):.1f}%, "
                f"consistency={data.get('consistency', 0):.2f}%"
            )

        logger.info(f"\nHidden Alpha Discovered:")
        for run in self.kb['runs']:
            for strategy, data in run.get('hidden_alpha', {}).items():
                if data.get('alpha_pct', 0) > 50:
                    logger.info(
                        f"  {strategy}: {data['win_rate']:.0f}% WR on "
                        f"{data['missed_signals']} signals (+{data['alpha_pct']:.0f}% alpha)"
                    )


def main():
    """Ingest all available cycles into KB."""
    builder = KnowledgeBaseBuilder()

    backtest_dir = Path("data/backtest_results")
    cycle_files = sorted(backtest_dir.glob("cycle_*.json"))

    logger.info("\n" + "="*70)
    logger.info("KNOWLEDGE BASE BUILDER")
    logger.info("="*70)

    for i, cycle_file in enumerate(cycle_files, 1):
        builder.ingest_cycle(cycle_file, i)

    builder.save_kb()
    builder.print_summary()


if __name__ == "__main__":
    main()
