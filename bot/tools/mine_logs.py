#!/usr/bin/env python
"""WAGMI log miner — read-only, LLM-FREE. Turn the 1.3GB log firehose into learning.

The bot's structured logs (logs/bot_YYYYMMDD.log) hold the full decision history —
every signal, pipeline verdict, regime call, shadow-gate, and close — that the
structured data files don't fully capture (the "why"). This mines them into a
decision FUNNEL + behavior aggregates so we can see where signals die, when the
bot is active, and how it behaves — the raw material for learning.

Writes coordination/LOG_INTELLIGENCE.md + prints a summary. Bounded to recent logs.
Usage: python bot/tools/mine_logs.py [days_back]
"""
import os
import sys
import json
import glob
import collections
import datetime

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BOT, "logs")
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 5

# Substrings to prefilter lines before json.loads (speed on huge files).
MARKERS = ("SIGNAL_GENERATED", "Pipeline done", "TRADE_CLOSED", "SHADOW-GATE",
           "[EXIT-AGENT]", "[REGIME]", "GRAD_VETO", "COOLDOWN-DROP", "LLM-FIRST TRADE",
           "safety reject", "EXPLORATION")


def _hour(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).hour
    except Exception:
        return None


def main():
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=DAYS)).strftime("%Y%m%d")
    files = sorted(f for f in glob.glob(os.path.join(LOGS, "bot_2026*.log"))
                   if os.path.basename(f).replace("bot_", "").replace(".log", "") >= cutoff)

    signals = collections.Counter()          # symbol_side -> count
    sig_by_hour = collections.Counter()
    pipe_action = collections.Counter()      # flat/proceed/...
    pipe_regime = collections.Counter()
    closes = collections.Counter()           # outcome
    close_pnl = collections.defaultdict(float)
    exit_actions = collections.Counter()
    shadow_gates = 0
    grad_vetoes = 0
    cooldown_drops = 0
    safety_rejects = collections.Counter()
    real_trades = 0
    exploration = 0
    n_lines = 0

    for path in files:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not any(m in line for m in MARKERS):
                        continue
                    n_lines += 1
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    msg = str(o.get("msg", ""))
                    data = o.get("data", {}) or {}
                    if "SIGNAL_GENERATED" in msg:
                        sym = data.get("symbol", "?"); side = data.get("side", "?")
                        signals[f"{sym}_{side}"] += 1
                        h = _hour(data.get("timestamp") or o.get("ts"))
                        if h is not None:
                            sig_by_hour[h] += 1
                    elif "Pipeline done" in msg:
                        for tok in msg.split():
                            if tok.startswith("action="):
                                pipe_action[tok.split("=", 1)[1]] += 1
                            if tok.startswith("regime="):
                                pipe_regime[tok.split("=", 1)[1]] += 1
                    elif "TRADE_CLOSED" in msg:
                        closes[data.get("outcome", "?")] += 1
                        try:
                            close_pnl[data.get("symbol", "?") + "_" + data.get("side", "?")] += float(data.get("pnl") or 0)
                        except Exception:
                            pass
                    elif "[EXIT-AGENT]" in msg:
                        for tok in msg.split():
                            if tok.startswith("action="):
                                exit_actions[tok.split("=", 1)[1]] += 1
                    elif "SHADOW-GATE" in msg:
                        shadow_gates += 1
                    elif "GRAD_VETO" in msg:
                        grad_vetoes += 1
                    elif "COOLDOWN-DROP" in msg:
                        cooldown_drops += 1
                    elif "LLM-FIRST TRADE" in msg:
                        real_trades += 1
                        if "EXPLORATION" in msg:
                            exploration += 1
                    elif "safety reject" in msg:
                        for tok in msg.split():
                            if "reject" in tok.lower():
                                safety_rejects[msg.split(":")[-1].strip()[:40]] += 1
                                break
        except Exception:
            continue

    tot_sig = sum(signals.values())
    L = [f"# WAGMI Log Intelligence — {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
         f"Mined {len(files)} log files ({DAYS}d), {n_lines:,} decision-event lines.", "",
         "## Decision funnel",
         f"- Signals generated: **{tot_sig:,}**  →  real entries taken: **{real_trades}** ({exploration} exploration overrides)",
         f"- Pipeline verdicts: {dict(pipe_action.most_common())}",
         f"- Cooldown-drops (pre-LLM): {cooldown_drops:,}  |  shadow-gates: {shadow_gates:,}  |  grad-vetoes: {grad_vetoes:,}",
         f"- Signal→entry conversion: {real_trades/tot_sig*100:.2f}%" if tot_sig else "- no signals",
         "",
         "## Where signals cluster (symbol_side)",
         "  " + ", ".join(f"{k}:{v}" for k, v in signals.most_common(12)),
         "",
         "## Signals by hour (UTC)",
         "  " + ", ".join(f"{h:02d}h:{sig_by_hour[h]}" for h in sorted(sig_by_hour)),
         "",
         "## Closed trades",
         f"- Outcomes: {dict(closes.most_common())}",
         "- Net PnL by symbol_side: " + ", ".join(f"{k}:{v:+.1f}" for k, v in sorted(close_pnl.items(), key=lambda x: -x[1])),
         "",
         "## Exit-agent action distribution",
         f"  {dict(exit_actions.most_common())}",
         "",
         "## Pipeline regime distribution",
         f"  {dict(pipe_regime.most_common())}",
         ]
    txt = "\n".join(L)
    with open(os.path.join(BOT, "..", "coordination", "LOG_INTELLIGENCE.md"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
