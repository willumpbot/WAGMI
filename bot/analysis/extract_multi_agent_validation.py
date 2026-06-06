#!/usr/bin/env python3
"""
Extract multi-agent decision validation data from bot logs.

Parses bot/logs/bot_*.log files and extracts:
- Multi-agent pipeline decisions (regime, trade decision, risk sizing, critic verdict)
- Outcomes (trade executed, closed, PnL)
- Cross-agent consistency metrics
"""

import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import csv

def parse_log_file(log_path):
    """Extract multi-agent decisions from a log file."""
    decisions = []

    with open(log_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
                msg = entry.get('msg', '')
                ts = entry.get('ts', '')

                # Pipeline completion — full multi-agent decision
                if '[MULTI-AGENT] Pipeline done:' in msg:
                    match = re.search(
                        r'action=(\w+)\s+conf=([0-9.]+)\s+regime=(\w+)\s+consistency=([0-9.]+)',
                        msg
                    )
                    if match:
                        decisions.append({
                            'ts': ts,
                            'type': 'pipeline',
                            'action': match.group(1),
                            'confidence': float(match.group(2)),
                            'regime': match.group(3),
                            'consistency': float(match.group(4)),
                            'raw_msg': msg,
                        })

                # Exit agent decisions
                elif '[MULTI-AGENT] Exit agent:' in msg:
                    match = re.search(
                        r'Exit agent:\s+(\w+)\s+action=(\w+)\s+urgency=(\w+)',
                        msg
                    )
                    if match:
                        decisions.append({
                            'ts': ts,
                            'type': 'exit',
                            'symbol': match.group(1),
                            'action': match.group(2),
                            'urgency': match.group(3),
                            'raw_msg': msg,
                        })
            except json.JSONDecodeError:
                continue
            except Exception as e:
                pass

    return decisions

def main():
    log_dir = Path('logs')  # Relative to bot/ directory
    all_decisions = []

    # Parse available log files
    if not log_dir.exists():
        log_dir = Path('../bot/logs')  # Try from analysis/ directory

    log_files = sorted(log_dir.glob('bot_2026*.log'), reverse=True)[:7]  # Last 7 days

    print(f"Parsing {len(log_files)} log files...")
    for log_file in log_files:
        decisions = parse_log_file(log_file)
        all_decisions.extend(decisions)
        print(f"  {log_file.name}: {len(decisions)} decisions")

    # Summarize
    pipeline_decisions = [d for d in all_decisions if d['type'] == 'pipeline']
    exit_decisions = [d for d in all_decisions if d['type'] == 'exit']

    print(f"\n=== MULTI-AGENT VALIDATION DATA ===")
    print(f"Total pipeline decisions: {len(pipeline_decisions)}")
    print(f"Total exit decisions: {len(exit_decisions)}")

    # Action distribution
    action_counts = defaultdict(int)
    for d in pipeline_decisions:
        action_counts[d['action']] += 1
    print(f"\nAction distribution (pipeline):")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(pipeline_decisions)
        print(f"  {action}: {count} ({pct:.1f}%)")

    # Regime distribution
    regime_counts = defaultdict(int)
    for d in pipeline_decisions:
        regime_counts[d['regime']] += 1
    print(f"\nRegime distribution:")
    for regime, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(pipeline_decisions)
        print(f"  {regime}: {count} ({pct:.1f}%)")

    # Confidence by action
    print(f"\nConfidence by action:")
    for action in sorted(action_counts.keys()):
        confs = [d['confidence'] for d in pipeline_decisions if d['action'] == action]
        if confs:
            avg_conf = sum(confs) / len(confs)
            print(f"  {action}: avg={avg_conf:.2f}, min={min(confs):.2f}, max={max(confs):.2f}")

    # Export to CSV for analysis
    output_file = Path('bot/analysis/multi_agent_validation_data.csv')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['ts', 'type', 'action', 'confidence', 'regime', 'consistency', 'symbol', 'urgency']
        )
        writer.writeheader()
        for d in all_decisions:
            row = {
                'ts': d.get('ts'),
                'type': d.get('type'),
                'action': d.get('action'),
                'confidence': d.get('confidence'),
                'regime': d.get('regime'),
                'consistency': d.get('consistency'),
                'symbol': d.get('symbol'),
                'urgency': d.get('urgency'),
            }
            writer.writerow(row)

    print(f"\nExported {len(all_decisions)} records to {output_file}")

if __name__ == '__main__':
    main()
