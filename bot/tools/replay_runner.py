"""
Replay runner — executes the FULL-SYSTEM historical replay INSIDE a sandbox.

This script is copied into a code sandbox by tools/replay_harness.py and run
with cwd = sandbox root. It refuses to run anywhere else (marker file check),
so it can never write into the production bot directory.

Pipeline it runs (all REAL production code paths):
  candles (HL/CCXT, point-in-time windows) -> strategies -> ensemble
  -> RiskFilterChain (6 gates) -> 9-agent LLM coordinator (CLI-routed claude -p)
  -> PositionManager exits (profit-lock geometry, trailing, 5m intra-bar fills,
     taker fees both sides, funding accrual)

Configuration via env (set by the harness):
  REPLAY_MODE=1              (required)
  REPLAY_SYMBOLS=BTC,ETH,SOL
  REPLAY_START=2026-06-20    (walk start)
  REPLAY_END=2026-06-27      (walk end, hard bound)
  REPLAY_DAYS=11             (fetch depth back from REPLAY_END; extra = warmup)
  REPLAY_EQUITY=500
  REPLAY_BUDGET_USD=5.0
  REPLAY_MAX_LLM_CALLS=60    (hard cap, enforced in BacktestLLMIntegration)
  REPLAY_LLM_SLEEP_S=15      (rate-limit between LLM pipelines)
  USE_CLI_LLM=true           (route agents through claude -p subscription)

Outputs (all inside the sandbox):
  replay_out/results.json        engine report
  replay_out/trade_events.jsonl  full position-manager trade log
  replay_out/llm_summary.json    honest LLM call accounting
"""
import json
import os
import sys
from pathlib import Path


def _die(msg: str) -> None:
    print(f"REPLAY RUNNER REFUSED: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    # ── Safety: only ever run inside a harness-built sandbox ──────────
    if not os.getenv("REPLAY_MODE"):
        _die("REPLAY_MODE env not set (must be launched by tools/replay_harness.py)")
    if not Path(".replay_sandbox").exists():
        _die(f"no .replay_sandbox marker in cwd ({os.getcwd()}) — "
             "refusing to run outside a sandbox")

    sys.path.insert(0, os.getcwd())

    # Load the copied .env for production-parity agent config, but never
    # override the harness-set env vars (override=False).
    try:
        from dotenv import load_dotenv
        load_dotenv(".env", override=False)
    except Exception:
        pass

    symbols = [s.strip().upper() for s in
               os.getenv("REPLAY_SYMBOLS", "BTC,ETH,SOL").split(",") if s.strip()]
    start = os.getenv("REPLAY_START") or None
    end = os.getenv("REPLAY_END") or None
    days = int(os.getenv("REPLAY_DAYS", "11"))
    equity = float(os.getenv("REPLAY_EQUITY", "500"))
    budget = float(os.getenv("REPLAY_BUDGET_USD", "5.0"))

    print(f"[REPLAY] sandbox={os.getcwd()}")
    print(f"[REPLAY] symbols={symbols} start={start} end={end} days={days} "
          f"equity=${equity:.0f} budget=${budget:.2f} "
          f"cap={os.getenv('REPLAY_MAX_LLM_CALLS')} "
          f"sleep={os.getenv('REPLAY_LLM_SLEEP_S')}s")

    from trading_config import TradingConfig
    from backtest.engine import BacktestEngine
    from backtest.llm_integration import BacktestLLMIntegration

    config = TradingConfig()
    config.starting_equity = equity

    llm = BacktestLLMIntegration(budget_usd=budget)
    engine = BacktestEngine(config=config, llm_integration=llm, yes=True)

    report = engine.run(symbols, days=days, start_date=start, end_date=end)

    # ── Dump outputs ──────────────────────────────────────────────────
    out = Path("replay_out")
    out.mkdir(exist_ok=True)

    (out / "results.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")

    with open(out / "trade_events.jsonl", "w", encoding="utf-8") as f:
        for ev in engine.pos_mgr.trade_log:
            f.write(json.dumps({
                "symbol": ev.symbol, "action": ev.action, "side": ev.side,
                "price": ev.price, "qty": ev.qty, "pnl": ev.pnl, "fee": ev.fee,
                "leverage": ev.leverage, "strategy": ev.strategy,
                "timestamp": str(ev.timestamp), "metadata": ev.metadata,
            }, default=str) + "\n")

    llm_summary = {
        "llm_calls": llm.llm_calls,
        "llm_failures": llm.llm_failures,
        "total_cost_usd": round(llm.total_cost_usd, 4),
        "candles_with_llm": llm.candles_with_llm,
        "candles_fallback": llm.candles_fallback,
        "pre_filter_skips": llm.pre_filter_skips,
        "call_cap": llm.max_llm_calls,
        "call_cap_reached": llm.call_cap_reached,
        "budget_exhausted": llm.budget_exhausted,
        "agent_costs": dict(llm.agent_costs),
        # Entry-event trigger filter accounting (REPLAY_CAMPAIGN_PLAN §2.1)
        "replay_entry_events": getattr(llm, "replay_entry_events", 0),
        "replay_starved_events": getattr(llm, "replay_starved_events", 0),
        "replay_cooldown_skips": getattr(llm, "replay_cooldown_skips", 0),
        "replay_symbol_calls": dict(getattr(llm, "_replay_symbol_calls", {}) or {}),
        "fee_model": {
            "taker_fee_bps_per_side": config.taker_fee_bps,
            "slippage_bps": getattr(config, "slippage_bps", 0),
            "funding_rate_per_8h": getattr(config, "backtest_funding_rate", 0.0001),
        },
        "symbols": symbols, "start": start, "end": end, "days": days,
        "starting_equity": equity,
        "final_equity": engine.risk_mgr.equity,
    }
    (out / "llm_summary.json").write_text(
        json.dumps(llm_summary, indent=2), encoding="utf-8")

    print(f"[REPLAY] DONE — llm_calls={llm.llm_calls} "
          f"cap_reached={llm.call_cap_reached} "
          f"final_equity=${engine.risk_mgr.equity:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
