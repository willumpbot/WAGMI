"""
Simple direct extraction from backtest raw_output using string operations.
More robust than regex for this messy formatted output.
"""

import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def extract_number_after(text: str, marker: str) -> float:
    """Find a marker and extract the number that follows it."""
    idx = text.find(marker)
    if idx == -1:
        return 0.0

    start = idx + len(marker)
    # Find the first number after the marker
    num_str = ""
    i = start
    while i < len(text):
        c = text[i]
        if c.isdigit() or c in '.-,':
            num_str += c
        elif num_str:
            break
        i += 1

    if num_str:
        try:
            return float(num_str.replace(',', ''))
        except:
            return 0.0
    return 0.0


def extract_section(text: str, start_marker: str, end_marker: str) -> str:
    """Extract text between two markers."""
    start = text.find(start_marker)
    if start == -1:
        return ""

    end = text.find(end_marker, start + len(start_marker))
    if end == -1:
        end = len(text)

    return text[start:end]


def parse_backtest_file(cycle_file: Path) -> dict:
    """Parse a single backtest file."""
    with open(cycle_file) as f:
        data = json.load(f)

    raw = data['metrics']['raw_output']

    result = {
        'run_id': data['metrics']['run_id'],
        'timestamp': data['metrics']['timestamp'],
    }

    # Extract metrics
    result['signals_generated'] = extract_number_after(raw, 'Signal gen:')
    result['trades_executed'] = extract_number_after(raw, 'Executed:')
    result['win_rate'] = extract_number_after(raw, 'Win Rate:')
    result['gross_pnl'] = extract_number_after(raw, 'Gross PnL:')
    result['net_pnl'] = extract_number_after(raw, 'Net PnL:')

    # Extract hidden alpha (solo strategies)
    hidden = {}
    for strategy in ['monte_carlo_zones', 'regime_trend', 'bollinger_squeeze', 'confidence_scorer', 'multi_tier']:
        if strategy in raw:
            # Find the line with this strategy
            idx = raw.find(strategy)
            line_end = raw.find('\n', idx)
            if line_end == -1:
                line_end = idx + 100

            line = raw[idx:line_end]
            parts = line.split()

            try:
                # Format: strategy_name  Missed  Won  Lost   WR%   Alpha%
                # Find indices of numbers
                missed = won = lost = wr = alpha = 0

                for i, part in enumerate(parts):
                    if part.isdigit():
                        if missed == 0:
                            missed = int(part)
                        elif won == 0:
                            won = int(part)
                        elif lost == 0:
                            lost = int(part)
                    elif '%' in part:
                        num = part.rstrip('%')
                        try:
                            val = float(num)
                            if wr == 0:
                                wr = val
                            else:
                                alpha = val
                        except:
                            pass

                if missed > 0:
                    hidden[strategy] = {
                        'missed_signals': missed,
                        'would_have_won': won,
                        'would_have_lost': lost,
                        'win_rate': wr,
                        'alpha_pct': alpha,
                    }
            except:
                pass

    result['hidden_alpha'] = hidden
    return result


def main():
    """Parse all backtest files."""
    logger.info("Parsing Backtest Files")
    logger.info("="*70)

    backtest_dir = Path("data/backtest_results")
    cycle_files = sorted(backtest_dir.glob("cycle_*.json"))

    results = []
    total_signals = 0
    total_trades = 0
    total_pnl = 0.0

    for cycle_file in cycle_files:
        result = parse_backtest_file(cycle_file)
        results.append(result)

        signals = result.get('signals_generated', 0)
        trades = result.get('trades_executed', 0)
        pnl = result.get('net_pnl', 0)
        wr = result.get('win_rate', 0)

        total_signals += signals
        total_trades += trades
        total_pnl += pnl

        logger.info(f"\n{cycle_file.name}:")
        logger.info(f"  Signals: {signals:,.0f}")
        logger.info(f"  Trades: {trades}")
        logger.info(f"  WR: {wr:.1f}%")
        logger.info(f"  Net PnL: ${pnl:,.2f}")

        # Show hidden alpha
        hidden = result.get('hidden_alpha', {})
        if hidden:
            logger.info(f"  Hidden Alpha:")
            for strat, data in hidden.items():
                logger.info(
                    f"    {strat}: {data['win_rate']:.0f}% WR on "
                    f"{data['missed_signals']} signals (+{data['alpha_pct']:.0f}% alpha)"
                )

    logger.info("\n" + "="*70)
    logger.info("AGGREGATE")
    logger.info("="*70)
    logger.info(f"Total Signals: {total_signals:,.0f}")
    logger.info(f"Total Trades: {total_trades}")
    logger.info(f"Total Net PnL: ${total_pnl:,.2f}")

    # Save results
    with open('data/parsed_backtest_summary.json', 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"\n[SAVED] Parsed summary to data/parsed_backtest_summary.json")


if __name__ == "__main__":
    main()
