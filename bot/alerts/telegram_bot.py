"""
Telegram command bot for runtime control and monitoring.

Commands:
  /status       - Bot status, equity, positions
  /positions    - Open position details
  /ml           - ML learner stats
  /performance  - Rolling win rate and metrics
  /close <sym>  - Force close a symbol's position
  /closeall     - Force close all positions
  /pause        - Pause trading (signals still evaluated, no opens)
  /resume       - Resume trading
  /manual_positions - List manually-detected positions (not bot-managed)

Security: Only the configured Telegram user ID is allowed.
All commands logged to data/logs/telegram.csv.
"""

import csv
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("bot.alerts.telegram_bot")

_LOG_DIR = os.path.join("data", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "telegram.csv")
_LOG_HEADERS = ["timestamp", "user_id", "command", "args"]


def _ensure_log():
    os.makedirs(_LOG_DIR, exist_ok=True)
    if not os.path.exists(_LOG_FILE):
        with open(_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_LOG_HEADERS)


def _log_command(user_id: int, command: str, args: str = ""):
    _ensure_log()
    try:
        with open(_LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),
                str(user_id), command, args,
            ])
    except Exception:
        pass


class TelegramCommandBot:
    """
    Polls Telegram for commands and dispatches to bot runtime.

    Uses simple getUpdates polling (no webhook server needed).
    Hooks into the MultiStrategyBot instance for live state access.
    """

    def __init__(
        self,
        token: str,
        allowed_user_id: int,
        bot_instance=None,
    ):
        self.token = token
        self.allowed_user_id = allowed_user_id
        self.bot = bot_instance
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._offset = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._paused = False
        self._quiet_mode = False     # Only circuit breakers + daily summary
        self._digest_mode = False    # Batch updates every 30-60 min
        self._digest_buffer = []     # Buffered messages for digest mode
        self._last_digest_ts = 0.0   # Last digest flush timestamp

        if not token:
            logger.info("Telegram bot: no token configured, commands disabled")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self):
        """Start polling in a background thread."""
        if not self.token:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram command bot started")

    def stop(self):
        self._running = False

    def _poll_loop(self):
        import requests
        while self._running:
            try:
                resp = requests.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 10},
                    timeout=15,
                )
                if resp.status_code != 200:
                    time.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    self._handle_message(msg)

            except Exception as e:
                logger.debug(f"Telegram poll error: {e}")
                time.sleep(5)

    def _handle_message(self, msg: dict):
        import requests
        chat_id = msg.get("chat", {}).get("id")
        user_id = msg.get("from", {}).get("id")
        text = (msg.get("text") or "").strip()

        if not text or not chat_id:
            return

        # Security: only allow configured user
        if self.allowed_user_id == 0:
            # No user ID configured — refuse commands (security: don't auto-authorize)
            logger.error(
                f"TELEGRAM_ALLOWED_USER_ID not set! "
                f"Commands DISABLED. Add TELEGRAM_ALLOWED_USER_ID={user_id} to .env"
            )
            try:
                requests.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            f"Setup required: Add TELEGRAM_ALLOWED_USER_ID={user_id} "
                            f"to your .env file, then restart the bot."
                        ),
                    },
                    timeout=10,
                )
            except Exception:
                pass
            return
        elif user_id != self.allowed_user_id:
            logger.warning(f"Unauthorized Telegram command from user {user_id}")
            return

        parts = text.split()
        command = parts[0].lower().split("@")[0]  # strip bot mention
        args = " ".join(parts[1:])

        _log_command(user_id, command, args)

        response = self._dispatch(command, args)
        if response:
            try:
                requests.post(
                    f"{self._base_url}/sendMessage",
                    json={"chat_id": chat_id, "text": response, "parse_mode": "Markdown"},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"Failed to send Telegram reply: {e}")

    def _dispatch(self, command: str, args: str) -> str:
        handlers = {
            "/status": self._cmd_status,
            "/positions": self._cmd_positions,
            "/ml": self._cmd_ml,
            "/performance": self._cmd_performance,
            "/llm": self._cmd_llm,
            "/mode": lambda: self._cmd_mode(args),
            "/health": self._cmd_health,
            "/uplift": self._cmd_uplift,
            "/progression": self._cmd_progression,
            "/close": lambda: self._cmd_close(args),
            "/closeall": self._cmd_closeall,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
            "/copytrades": self._cmd_copytrades,
            "/telemetry": self._cmd_telemetry,
            "/replay": self._cmd_replay,
            "/proposals": self._cmd_proposals,
            "/approve": lambda: self._cmd_approve_proposal(args),
            "/reject": lambda: self._cmd_reject_proposal(args),
            "/kill": lambda: self._cmd_kill(args),
            "/unkill": self._cmd_unkill,
            "/ops": self._cmd_ops,
            # Knowledge roadmap & signal analysis commands
            "/roadmap": self._cmd_roadmap,
            "/promote": self._cmd_promote,
            "/demote": lambda: self._cmd_demote(args),
            "/curriculum": self._cmd_curriculum,
            "/knowledge": self._cmd_knowledge,
            "/signals": self._cmd_signals,
            "/analyze": lambda: self._cmd_analyze(args),
            "/accuracy": self._cmd_accuracy,
            "/growth": self._cmd_growth,
            "/risk": self._cmd_risk,
            "/rl": self._cmd_rl,
            "/survival": self._cmd_survival,
            "/learn": self._cmd_learn,
            "/edge": lambda: self._cmd_edge(args),
            "/signal": lambda: self._cmd_submit_signal(args),
            "/thesis": self._cmd_thesis,
            "/sniper": self._cmd_sniper,
            "/sim": self._cmd_sim,
            "/trade": lambda: self._cmd_trade(args),
            "/exit": lambda: self._cmd_exit(args),
            "/journal": self._cmd_journal,
            "/equity": self._cmd_equity,
            "/perf": self._cmd_perf,
            "/optimize": self._cmd_optimize,
            "/manage": lambda: self._cmd_manage(args),
            "/health": self._cmd_health,
            "/tracker": self._cmd_tracker,
            "/intel": self._cmd_intel,
            "/ask": lambda: self._cmd_ask(args),
            "/snapshot": self._cmd_snapshot,
            "/costs": self._cmd_costs,
            "/copilot": lambda: self._cmd_copilot_trade(args),
            "/quiet": self._cmd_quiet,
            "/loud": self._cmd_loud,
            "/digest": self._cmd_digest,
            "/live": self._cmd_live,
            "/help": self._cmd_help,
            # Premium alert system commands (2026-04-16)
            "/watch": self._cmd_watch,
            "/alerts": self._cmd_alerts,
            "/briefing": self._cmd_briefing,
            "/edges": self._cmd_edges,
            "/siminject": lambda: self._cmd_siminject(args),
            "/simstatus": self._cmd_simstatus,
        }
        handler = handlers.get(command)
        if handler:
            try:
                return handler()
            except Exception as e:
                return f"Error: {e}"
        return ""

    def _cmd_status(self) -> str:
        if not self.bot:
            return "Bot not connected"
        eq = self.bot.risk_mgr.equity
        n_pos = self.bot.pos_mgr.get_open_count()
        daily = self.bot.risk_mgr.circuit_breaker.daily_pnl
        paused = "PAUSED" if self._paused else "ACTIVE"
        return (
            f"*Status: {paused}*\n"
            f"Equity: ${eq:,.2f}\n"
            f"Open positions: {n_pos}\n"
            f"Daily PnL: ${daily:+,.2f}\n"
            f"Tick: {self.bot._tick}"
        )

    def _cmd_positions(self) -> str:
        if not self.bot:
            return "Bot not connected"
        from data.fetcher import DataFetcher
        from trading_config import DEFAULT_SYMBOLS
        open_pos = self.bot.pos_mgr.get_open_positions()
        if not open_pos:
            return "No open positions"
        lines = []
        for sym, pos in open_pos.items():
            price = self.bot.fetcher.latest_price(sym, DEFAULT_SYMBOLS.get(sym, type('', (), {'coingecko_id': sym.lower()})()).coingecko_id) or 0
            pnl = (price - pos.entry) * pos.qty * pos.leverage if pos.side == "LONG" else (pos.entry - price) * pos.qty * pos.leverage
            lines.append(
                f"*{sym}* {pos.side} {pos.leverage:.0f}x\n"
                f"  Entry: {pos.entry} | State: {pos.state}\n"
                f"  SL: {pos.sl} | TP1: {pos.tp1} | TP2: {pos.tp2}\n"
                f"  Unrealized: ${pnl:+,.2f} | Realized: ${pos.realized_pnl:+,.2f}"
            )
        return "\n\n".join(lines)

    def _cmd_ml(self) -> str:
        if not self.bot or not self.bot.ml:
            return "ML disabled"
        ml = self.bot.ml
        return (
            f"*ML Learner*\n"
            f"Trade outcomes: {len(ml.outcomes)}\n"
            f"Snapshots: {len(ml.snapshots)}\n"
            f"Trade model: {'trained' if ml.weights is not None and len(ml.weights) > 0 else 'waiting'}\n"
            f"Snapshot model: {'trained' if ml.snapshot_weights is not None else 'waiting'}\n"
            f"Fast model: {'trained' if ml.fast_weights is not None else 'waiting'}"
        )

    def _cmd_performance(self) -> str:
        from data.learning import get_performance
        perf = get_performance()
        if not perf:
            return "No performance data yet"
        return (
            f"*Performance*\n"
            f"Trades: {perf.get('total_trades', 0)}\n"
            f"WR (20): {perf.get('win_rate_20', 0):.0%}\n"
            f"WR (50): {perf.get('win_rate_50', 0):.0%}\n"
            f"Avg R:R: {perf.get('avg_rr', 0):.2f}\n"
            f"TP1 rate: {perf.get('tp1_success_rate', 0):.0%}\n"
            f"TP1->SL: {perf.get('tp1_to_sl_rate', 0):.0%}\n"
            f"Total PnL: ${perf.get('total_pnl', 0):+,.2f}"
        )

    def _cmd_close(self, args: str) -> str:
        if not self.bot:
            return "Bot not connected"
        symbol = args.strip().upper()
        if not symbol:
            return "Usage: /close SYMBOL"
        from trading_config import DEFAULT_SYMBOLS
        price = self.bot.fetcher.latest_price(
            symbol, DEFAULT_SYMBOLS.get(symbol, type('', (), {'coingecko_id': symbol.lower()})()).coingecko_id
        )
        if not price:
            return f"Cannot get price for {symbol}"
        event = self.bot.pos_mgr.force_close(symbol, price, "TELEGRAM_CLOSE")
        if event:
            return f"Closed {symbol} @ {price} | PnL: ${event.pnl:+,.2f}"
        return f"No open position for {symbol}"

    def _cmd_closeall(self) -> str:
        if not self.bot:
            return "Bot not connected"
        from trading_config import DEFAULT_SYMBOLS
        closed = []
        for sym in list(self.bot.pos_mgr.get_open_positions().keys()):
            price = self.bot.fetcher.latest_price(
                sym, DEFAULT_SYMBOLS.get(sym, type('', (), {'coingecko_id': sym.lower()})()).coingecko_id
            )
            if price:
                event = self.bot.pos_mgr.force_close(sym, price, "TELEGRAM_CLOSE")
                if event:
                    closed.append(f"{sym}: ${event.pnl:+,.2f}")
        if closed:
            return "Closed:\n" + "\n".join(closed)
        return "No positions to close"

    def _cmd_llm(self) -> str:
        if not self.bot:
            return "Bot not connected"
        mode = self.bot.llm_mode
        triggers = self.bot._llm_triggers
        rate = triggers.rate_stats
        return (
            f"*LLM Meta-Brain*\n"
            f"Mode: {mode.name}\n"
            f"Calls (1h): {rate['calls_last_hour']}/{rate['max_per_hour']}\n"
            f"Calls (24h): {rate['calls_last_day']}/{rate['max_per_day']}\n"
            f"Pending events: {triggers.event_count}\n"
            f"Events: {triggers.event_summary}"
        )

    def _cmd_mode(self, args: str) -> str:
        if not self.bot:
            return "Bot not connected"
        from llm.autonomy import LLMMode, describe_mode
        args = args.strip()
        if not args:
            mode = self.bot.llm_mode
            return (
                f"Current LLM mode: *{mode.name}* ({mode.value})\n"
                f"{describe_mode(mode)}\n\n"
                f"Usage: /mode <0-5>\n"
                f"0=OFF, 1=ADVISORY, 2=VETO\\_ONLY, 3=SIZING, 4=DIRECTION, 5=FULL"
            )
        try:
            new_mode_val = int(args)
            if new_mode_val < 0 or new_mode_val > 5:
                return "Mode must be 0-5"
            new_mode = LLMMode(new_mode_val)
            old_mode = self.bot.llm_mode
            self.bot.llm_mode = new_mode
            return (
                f"LLM mode changed: {old_mode.name} -> *{new_mode.name}*\n"
                f"{describe_mode(new_mode)}"
            )
        except (ValueError, KeyError):
            return "Invalid mode. Use /mode <0-5>"

    def _cmd_health(self) -> str:
        if not self.bot:
            return "Bot not connected"
        from trading_config import DEFAULT_SYMBOLS
        from execution.time_sizing import is_weekend, is_low_liquidity_hours

        lines = ["*Health Check*"]

        # Bot status
        eq = self.bot.risk_mgr.equity
        cb = self.bot.risk_mgr.circuit_breaker
        lines.append(f"Equity: ${eq:,.2f}")
        lines.append(f"CB: {'TRIPPED' if cb.tripped else 'OK'}")
        lines.append(f"Paused: {'YES' if self._paused else 'NO'}")
        lines.append(f"Weekend: {'YES' if is_weekend() else 'NO'}")
        lines.append(f"Low-liq hours: {'YES' if is_low_liquidity_hours() else 'NO'}")

        # Exchange connectivity
        fetcher = self.bot.fetcher
        stats = fetcher.get_stats()
        lines.append(f"\n*Data*")
        lines.append(f"CCXT requests: {stats['ccxt_requests']}")
        lines.append(f"CCXT failures: {stats['ccxt_failures']}")
        lines.append(f"CoinGecko: {stats['cg_requests']}")
        lines.append(f"Cache entries: {stats['cache_hits']}")

        # Symbol status (compact)
        symbols_ok = 0
        symbols_fail = 0
        for sym in DEFAULT_SYMBOLS:
            if sym in self.bot._last_prices and self.bot._last_prices[sym] > 0:
                symbols_ok += 1
            else:
                symbols_fail += 1
        lines.append(f"\n*Symbols*: {symbols_ok} OK, {symbols_fail} no data")

        # LLM status
        from llm.recovery import get_error_stats
        err_stats = get_error_stats()
        lines.append(f"\n*LLM*")
        lines.append(f"Mode: {self.bot.llm_mode.name}")
        lines.append(f"API calls: {err_stats.total_calls}")
        lines.append(f"Errors: {err_stats.total_errors} ({err_stats.error_rate:.1f}%)")
        lines.append(f"Consecutive errs: {err_stats.consecutive_errors}")

        # Watchdog status
        try:
            wd = self.bot.watchdog.get_status()
            lines.append(f"\n*Watchdog*")
            lines.append(f"Running: {'YES' if wd['running'] else 'NO'}")
            lines.append(f"Last heartbeat: {wd['last_heartbeat_s_ago']:.0f}s ago")
            lines.append(f"Stalled: {'YES' if wd['stalled'] else 'NO'}")
            lines.append(f"Total errors: {wd['total_errors']}")
            lines.append(f"Exchange: {'OK' if wd['exchange_healthy'] else 'DOWN'}")
            if wd.get('drawdown_pct', 0) > 0:
                lines.append(f"Drawdown: {wd['drawdown_pct']:.1f}%")
        except Exception:
            pass

        # Recent health events from DB
        try:
            from data.db import get_health_events
            events = get_health_events(hours=6, severity="ALERT")
            if events:
                lines.append(f"\n*Recent Alerts ({len(events)})*")
                for e in events[:3]:
                    lines.append(f"  {e['event_type']}: {e['message'][:80]}")
        except Exception:
            pass

        # Signal performance (7d)
        try:
            from data.db import get_signal_performance
            sp = get_signal_performance(7)
            if sp.get("total", 0) > 0:
                lines.append(f"\n*Signal Performance (7d)*")
                lines.append(f"Signals scored: {sp['total']}")
                lines.append(f"Win rate: {sp['win_rate']:.0%}")
                lines.append(f"Avg score: {sp['avg_score']:.0f}/100")
                lines.append(f"Total PnL: ${sp['total_pnl']:+,.2f}")
        except Exception:
            pass

        return "\n".join(lines)

    def _cmd_uplift(self) -> str:
        from llm.uplift_analytics import compute_uplift, format_uplift_report
        analytics = compute_uplift()
        return format_uplift_report(analytics)

    def _cmd_progression(self) -> str:
        if not self.bot:
            return "Bot not connected"
        from llm.progression import format_progression_status
        return format_progression_status(self.bot.llm_mode)

    def _cmd_copytrades(self) -> str:
        from classification.human_copy_classifier import format_copy_trades_telegram
        from execution.candidate import CandidateLogger
        candidates = CandidateLogger.load_candidates()
        return format_copy_trades_telegram(candidates)

    def _cmd_health(self) -> str:
        """Run sniper system health check."""
        try:
            from manual.health_check import run_health_check
            health = run_health_check(quick=True)
            return health.format_telegram()
        except Exception as e:
            return f"Health check error: {e}"

    def _cmd_sniper(self) -> str:
        """Show manual sniper signal summary and recent signals."""
        try:
            if self.bot and hasattr(self.bot, '_manual_sniper') and self.bot._manual_sniper:
                from manual.alerts import format_daily_summary
                summary = self.bot._manual_sniper.get_daily_summary()
                return format_daily_summary(summary)
            return "Manual Sniper System not active. Set MANUAL_SNIPER_ENABLED=true"
        except Exception as e:
            return f"Sniper status error: {e}"

    def _cmd_sim(self) -> str:
        """Show sniper simulator status — virtual $100 account tracking."""
        try:
            status = None
            if self.bot and hasattr(self.bot, '_sniper_simulator') and self.bot._sniper_simulator:
                status = self.bot._sniper_simulator.get_status()
            else:
                # Fallback: read from disk
                import json as _json
                status_path = os.path.join("data", "manual", "sim_status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        status = _json.load(f)

            if not status:
                return "Sniper Simulator not active. Enable MANUAL_SNIPER_ENABLED=true"

            equity = status.get("current_equity", 100)
            starting = status.get("starting_equity", 100)
            growth = status.get("growth_pct", 0)
            total = status.get("total_trades", 0)
            wr = status.get("win_rate", 0)
            pf = status.get("profit_factor", 0)
            daily = status.get("daily_pnl", 0)
            weekly = status.get("weekly_pnl", 0)
            days = status.get("days_elapsed", 1)
            streak = status.get("current_streak", 0)
            dd = status.get("max_drawdown", 0)
            open_pos = status.get("open_positions", [])

            streak_str = f"+{streak}W" if streak > 0 else f"{streak}L" if streak < 0 else "0"

            lines = [
                f"*Sniper Simulator*",
                f"${starting:.0f} -> ${equity:.2f} ({growth:+.1f}%) | {days}d",
                f"",
                f"*Stats:* {total} trades | WR {wr:.0f}% | PF {pf:.1f}",
                f"*Streak:* {streak_str} | Max DD: {dd:.1f}%",
                f"*Today:* ${daily:+.2f} | Week: ${weekly:+.2f}",
            ]

            if open_pos:
                lines.append(f"\n*Open ({len(open_pos)}):*")
                for p in open_pos[:5]:
                    sym = p.get("symbol", "?")
                    side = p.get("side", "?")
                    entry = p.get("entry", 0)
                    lines.append(f"  {sym} {side} @ ${entry:.2f}")

            # Per-symbol breakdown
            by_sym = status.get("by_symbol", {})
            if by_sym:
                lines.append(f"\n*By Symbol:*")
                for sym, s in sorted(by_sym.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
                    lines.append(
                        f"  {sym}: {s['trades']}t WR={s['wr']:.0f}% P&L=${s['pnl']:+.2f}"
                    )

            return "\n".join(lines)
        except Exception as e:
            return f"Sim status error: {e}"

    def _cmd_telemetry(self) -> str:
        from data.fetchers.telemetry import Telemetry
        return Telemetry.format_telegram()

    def _cmd_replay(self) -> str:
        from engine.replay_engine import replay_from_csv, format_replay_report
        # Replay the main candidate log
        csv_path = os.path.join("data", "analysis", "trade_candidates.csv")
        if not os.path.exists(csv_path):
            return "No trade log found for replay."
        result = replay_from_csv(csv_path)
        return format_replay_report(result)

    def _cmd_proposals(self) -> str:
        from llm.strategy_discovery.research_agent import list_proposals, format_proposals_telegram
        proposals = list_proposals()
        return format_proposals_telegram(proposals)

    def _cmd_approve_proposal(self, args: str) -> str:
        proposal_id = args.strip()
        if not proposal_id:
            return "Usage: /approve <proposal_id>"
        from llm.strategy_discovery.sandbox import approve_proposal
        p = approve_proposal(proposal_id)
        if p:
            return f"Proposal approved: {p.name} ({p.proposal_id})"
        return f"Cannot approve {proposal_id} (not found or wrong status)"

    def _cmd_reject_proposal(self, args: str) -> str:
        proposal_id = args.strip()
        if not proposal_id:
            return "Usage: /reject <proposal_id>"
        from llm.strategy_discovery.sandbox import reject_proposal
        p = reject_proposal(proposal_id)
        if p:
            return f"Proposal rejected: {p.name} ({p.proposal_id})"
        return f"Cannot reject {proposal_id} (not found)"

    def _cmd_kill(self, args: str) -> str:
        from execution.ops_guard import OpsGuard
        guard = OpsGuard()
        reason = args.strip() or "Telegram kill switch"
        guard.kill(reason)
        return f"KILL SWITCH ACTIVATED: {reason}\nAll execution halted. Use /unkill to resume."

    def _cmd_unkill(self) -> str:
        from execution.ops_guard import OpsGuard
        guard = OpsGuard()
        guard.unkill()
        return "Kill switch deactivated. Trading can resume."

    def _cmd_ops(self) -> str:
        from execution.ops_guard import OpsGuard
        guard = OpsGuard()
        return guard.format_status()

    # ── Knowledge Roadmap & Signal Analysis Commands ─────────────

    def _cmd_roadmap(self) -> str:
        from llm.knowledge_roadmap import format_roadmap_status
        return format_roadmap_status()

    def _cmd_promote(self) -> str:
        from llm.knowledge_roadmap import promote_phase
        result = promote_phase()
        if result["success"]:
            return (
                f"PROMOTED to Phase {result['to_phase']}: {result['phase_name']}\n"
                f"LLM Mode: {result['llm_mode']}\n"
                f"Money: {'$' + str(result['max_stake_usd']) + ' max' if result['money_allowed'] else 'Paper only'}"
            )
        return f"Cannot promote: {result['reason']}"

    def _cmd_demote(self, args: str) -> str:
        from llm.knowledge_roadmap import demote_phase
        args = args.strip()
        if not args:
            return "Usage: /demote <phase_number> [reason]"
        parts = args.split(None, 1)
        try:
            target = int(parts[0])
        except ValueError:
            return "Invalid phase number"
        reason = parts[1] if len(parts) > 1 else "manual demotion"
        result = demote_phase(target, reason)
        if result["success"]:
            return f"Demoted to Phase {result['to_phase']}: {result['phase_name']}\nReason: {result['reason']}"
        return f"Cannot demote: {result['reason']}"

    def _cmd_curriculum(self) -> str:
        from llm.self_teaching import get_teaching_engine
        report = get_teaching_engine().get_curriculum_report()
        c = report["curriculum"]
        k = report["knowledge"]
        return (
            f"*LLM Curriculum*\n"
            f"Level: {c['level']} - {c['level_name']}\n"
            f"Hours at level: {c['hours_at_level']:.0f}h\n"
            f"Total hours: {c['total_hours']:.0f}h\n"
            f"Trades analyzed: {c['trades_analyzed']}\n"
            f"Hypotheses: {c['hypotheses_total']} total, "
            f"{c['hypotheses_validated']} validated, {c['hypotheses_invalidated']} invalidated\n"
            f"Prediction accuracy: {c['prediction_accuracy']:.0%}\n"
            f"Sniper profiles: {c['sniper_profiles']}\n"
            f"Novel rules: {c['novel_rules']}\n"
            f"\n*Knowledge Base*\n"
            f"Total entries: {k['total_entries']}\n"
            f"Avg confidence: {k['avg_confidence']:.0%}\n"
            f"Validated: {k['validated_count']}"
        )

    def _cmd_knowledge(self) -> str:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()
        kb = engine.knowledge

        axioms = kb.get_axioms()
        principles = kb.get_principles(min_confidence=0.6)
        anti = kb.get_anti_patterns()
        hypotheses = kb.get_active_hypotheses()
        stats = kb.get_stats()

        lines = [
            f"*Knowledge Base ({stats['total_entries']} entries)*\n",
            f"*Axioms ({len(axioms)})*:",
        ]
        for a in axioms[:5]:
            lines.append(f"  - {a['content'][:80]}")

        lines.append(f"\n*Principles ({len(principles)})*:")
        for p in principles[:5]:
            lines.append(f"  - [{p.get('confidence', 0):.0%}] {p['content'][:80]}")

        if anti:
            lines.append(f"\n*Anti-Patterns ({len(anti)})*:")
            for a in anti[:3]:
                lines.append(f"  - {a['content'][:80]}")

        if hypotheses:
            lines.append(f"\n*Active Hypotheses ({len(hypotheses)})*:")
            for h in hypotheses[:3]:
                lines.append(f"  - {h['content'][:80]}")

        return "\n".join(lines)

    def _cmd_signals(self) -> str:
        from signals.telegram_ingest import get_recent_signals
        signals = get_recent_signals(10)
        if not signals:
            return "No signals ingested yet."

        lines = [f"*Recent Ingested Signals ({len(signals)})*\n"]
        for s in reversed(signals[-5:]):
            ago = int(time.time() - s.get("timestamp", 0))
            lines.append(
                f"  {s.get('symbol', '?')} {s.get('side', '?')} "
                f"entry={s.get('entry_price', 0)} sl={s.get('stop_loss', 0)} "
                f"tp1={s.get('take_profit_1', 0)} "
                f"[{s.get('parse_quality', 0):.0%}] "
                f"verdict={s.get('llm_verdict', 'pending')} "
                f"({ago}s ago)"
            )
        return "\n".join(lines)

    def _cmd_analyze(self, args: str) -> str:
        """Manually submit a signal for analysis. Usage: /analyze LONG BTC 97500 SL 96000 TP 100000"""
        args = args.strip()
        if not args:
            return (
                "Usage: /analyze <signal text>\n"
                "Example: /analyze LONG BTC 97500 SL 96000 TP 100000"
            )
        from signals.telegram_ingest import parse_signal
        from signals.llm_analyzer import analyze_signal, format_analysis_for_telegram
        from llm.knowledge_roadmap import get_roadmap_state

        signal = parse_signal(args)
        if not signal:
            return f"Could not parse signal from: {args}"

        # Get roadmap state for context
        state = get_roadmap_state()
        from llm.knowledge_roadmap import PHASE_CONFIGS
        config = PHASE_CONFIGS.get(state.current_phase, {})

        # Get knowledge context
        try:
            from llm.knowledge_seed import get_course_summary_for_prompt
            from llm.self_teaching import get_teaching_engine
            engine = get_teaching_engine()
            knowledge = (
                get_course_summary_for_prompt(signal.symbol, "") + "\n" +
                engine.get_knowledge_for_prompt(signal.symbol, "")
            )
        except Exception:
            knowledge = ""

        from dataclasses import asdict
        analysis = analyze_signal(
            signal_data=asdict(signal),
            knowledge_context=knowledge,
            curriculum_level=config.get("curriculum_level", 1),
            learning_phase=config.get("learning_phase", "ABSORB"),
        )

        if analysis:
            return format_analysis_for_telegram(analysis)
        return "Analysis failed (LLM error or timeout)"

    def _cmd_accuracy(self) -> str:
        from signals.llm_analyzer import get_analysis_accuracy
        acc = get_analysis_accuracy()
        if acc["total_analyses"] == 0:
            return "No signal analyses recorded yet."
        return (
            f"*Signal Analysis Accuracy*\n"
            f"Total analyses: {acc['total_analyses']}\n"
            f"Outcomes tracked: {acc['outcomes_tracked']}\n"
            f"Overall accuracy: {acc['overall_accuracy']:.0%}\n"
            f"TAKE accuracy: {acc['take_accuracy']:.0%} ({acc['take_total']} signals)\n"
            f"SKIP accuracy: {acc['skip_accuracy']:.0%} ({acc['skip_total']} signals)"
        )

    def _cmd_intel(self) -> str:
        """Trigger quant brain market intel immediately."""
        if self.bot is None:
            return "Bot not connected"
        try:
            self.bot._send_quant_intel()
            return "Market intel sent."
        except Exception as e:
            return f"Intel error: {e}"

    def _cmd_siminject(self, args: str) -> str:
        """Inject a hypothetical trade into the sim for manual exploration.

        Usage: /siminject SYMBOL SIDE PRICE LEVx QTY [SL] [TP]
        Example: /siminject SOL SELL 87.50 15x 0.3 89.20 84.50

        The sim equity is SEPARATE from the bot's live equity. This lets
        you test high-leverage ideas (your 7-20x zone) without touching
        real positions. 2026-04-16 addition.
        """
        try:
            parts = args.strip().split()
            if len(parts) < 5:
                return (
                    "Usage: `/siminject SYMBOL SIDE PRICE LEVx QTY [SL] [TP]`\n"
                    "Examples:\n"
                    "  `/siminject SOL SELL 87.50 15x 0.3`\n"
                    "  `/siminject HYPE BUY 44.5 10x 2.0 43.90 46.0`\n\n"
                    "SL/TP optional — defaults to 1%/2% of entry.\n"
                    "Sim equity is independent from bot equity."
                )
            symbol = parts[0].upper()
            side = parts[1].upper()
            if side not in ("BUY", "SELL", "LONG", "SHORT"):
                return f"Invalid side: {side}. Use BUY/SELL or LONG/SHORT."
            entry_price = float(parts[2])
            lev_str = parts[3].lower().rstrip("x")
            leverage = float(lev_str)
            qty = float(parts[4])
            sl = float(parts[5]) if len(parts) > 5 else None
            tp = float(parts[6]) if len(parts) > 6 else None

            # Grab the simulator from the bot
            sim = getattr(self.bot, "_manual_sim", None) or getattr(self.bot, "_manual_simulator", None)
            if sim is None:
                return (
                    "Simulator not available.\n"
                    "Enable with `MANUAL_SIMULATOR_ENABLED=true` in .env and restart."
                )

            pos = sim.inject_manual_trade(
                symbol=symbol, side=side,
                entry_price=entry_price, leverage=leverage, qty=qty,
                sl=sl, tp_scalp=tp, tp_swing=None,
                tier="MANUAL_INJECTION",
                notes=f"User injected via /siminject",
            )
            if pos is None:
                return f"⚠️ Could not inject — see logs (duplicate position or invalid input?)"

            eff_side = "LONG" if pos.side == "BUY" else "SHORT"
            dir_emoji = "🟢" if pos.side == "BUY" else "🔴"
            stop_pct = abs(pos.entry - pos.sl) / pos.entry * 100
            tp_pct = abs(pos.tp_scalp - pos.entry) / pos.entry * 100
            risk_dollar = pos.risk_amount

            return (
                f"🧪 *SIM INJECTION* {dir_emoji} {eff_side} {pos.symbol}\n"
                f"Entry: ${pos.entry:.4g}  Lev: {pos.leverage:.1f}x  Qty: {pos.qty:.4f}\n"
                f"SL: ${pos.sl:.4g} ({stop_pct:.2f}% away)\n"
                f"TP1: ${pos.tp_scalp:.4g} ({tp_pct:.2f}% away)\n"
                f"Risk if SL: ${risk_dollar:.2f}\n"
                f"Notional: ${pos.position_size_usd:,.2f}\n"
                f"Trade ID: `{pos.trade_id}`\n\n"
                f"Sim equity (independent from bot): ${sim._equity:,.2f}\n"
                f"Use `/simstatus` to see all sim positions + PnL."
            )
        except ValueError as ve:
            return f"Parse error: {ve}\nUsage: `/siminject SYMBOL SIDE PRICE LEVx QTY [SL] [TP]`"
        except Exception as e:
            return f"Injection failed: {e}"

    def _cmd_simstatus(self) -> str:
        """Show the manual simulator's current state (positions, equity, stats)."""
        try:
            sim = getattr(self.bot, "_manual_sim", None) or getattr(self.bot, "_manual_simulator", None)
            if sim is None:
                return "Simulator not available."
            s = sim.get_status()
            equity = s.get("equity", 0)
            starting = s.get("starting_equity", 100)
            pct = ((equity / starting) - 1) * 100 if starting > 0 else 0
            open_count = len(s.get("open_positions", []))
            closed_count = s.get("total_closed", 0)
            wr = s.get("win_rate_pct", 0)
            pf = s.get("profit_factor", 0)
            lines = [
                "🧪 *SIM STATUS*",
                f"Equity: ${equity:,.2f}  (started ${starting:,.2f}, {pct:+.1f}%)",
                f"Open: {open_count}  |  Closed: {closed_count}",
                f"WR: {wr:.1f}%  |  PF: {pf:.2f}",
                "",
            ]
            if open_count > 0:
                lines.append("*Open positions*:")
                for p in s.get("open_positions", [])[:10]:
                    side = p.get("side", "?")
                    side_emoji = "🟢" if side in ("BUY", "LONG") else "🔴"
                    lines.append(
                        f"  {side_emoji} {p.get('symbol','?')} {side} @ "
                        f"${p.get('entry',0):.4g}  {p.get('leverage',0):.1f}x  "
                        f"(${p.get('position_size_usd',0):,.0f} notional)"
                    )
            lines.append("")
            lines.append("Use `/siminject` to add a new hypothetical trade.")
            return "\n".join(lines)
        except Exception as e:
            return f"Sim status error: {e}"

    def _cmd_watch(self) -> str:
        """Show current anticipatory watchlist and WATCH-alert queue.

        Shows (a) anticipatory engine pre-stages that have fired recent
        WATCH alerts and (b) current open positions the user should be
        aware of. Built 2026-04-16 as part of the premium alert system.
        """
        from datetime import datetime, timezone
        try:
            from alerts.premium_filter import _last_watch_alert, _WATCH_ALERT_COOLDOWN_S
        except Exception:
            _last_watch_alert = {}
            _WATCH_ALERT_COOLDOWN_S = 1800

        lines = ["🔔 *Watch List*", ""]

        # Anticipatory engine pre-stages
        ant = getattr(self.bot, "_anticipation_engine", None)
        if ant and hasattr(ant, "_pending"):
            pending = [p for p in ant._pending if not getattr(p, "resolved", False)]
            if pending:
                lines.append(f"📡 *Anticipatory pre-stages* ({len(pending)}):")
                for p in pending[:10]:
                    side_emoji = "🟢" if getattr(p, "side", "") == "BUY" else "🔴"
                    lines.append(
                        f"  {side_emoji} {p.symbol} {p.side} target ${p.target_price:.4g} "
                        f"({p.setup_type})"
                    )
                lines.append("")
            else:
                lines.append("📡 No anticipatory pre-stages active\n")

        # Recent WATCH alerts (last 30 min)
        now = __import__("time").time()
        recent = [
            (k, t) for k, t in _last_watch_alert.items()
            if (now - t) < _WATCH_ALERT_COOLDOWN_S
        ]
        if recent:
            lines.append(f"📨 *Recent WATCH alerts* ({len(recent)} in last 30m):")
            for (sym, side, strat), t in sorted(recent, key=lambda x: -x[1])[:10]:
                mins_ago = (now - t) / 60
                side_emoji = "🟢" if side in ("BUY", "LONG") else "🔴"
                lines.append(f"  {side_emoji} {sym} {side} via {strat} ({mins_ago:.0f}m ago)")
            lines.append("")
        else:
            lines.append("📨 No recent WATCH alerts\n")

        # Open positions the user should be tracking
        try:
            open_count = self.bot.pos_mgr.get_open_count() if self.bot else 0
            if open_count > 0 and self.bot and hasattr(self.bot.pos_mgr, "positions"):
                lines.append(f"💼 *Open positions* ({open_count}):")
                for sym, pos in self.bot.pos_mgr.positions.items():
                    if pos.qty <= 0:
                        continue
                    side_emoji = "🟢" if pos.side == "LONG" else "🔴"
                    lines.append(
                        f"  {side_emoji} {sym} {pos.side} @ ${pos.entry:.4g} "
                        f"(state: {pos.state})"
                    )
        except Exception:
            pass

        lines.append("")
        lines.append("💡 Want an EXECUTE alert? Wait for the full setup. 3-8 WATCHes/day expected.")
        return "\n".join(lines)

    def _cmd_alerts(self) -> str:
        """Show alert system status and recent filter activity."""
        import os
        enabled = os.environ.get("PREMIUM_ALERTS_ENABLED", "true").lower() in ("1", "true", "yes")

        lines = [
            f"📢 *Premium Alert System*",
            f"",
            f"Status: {'✅ ENABLED' if enabled else '⚠️ DISABLED (noise mode)'}",
            f"",
            f"*How it works:*",
            f"• Every ensemble signal passes through premium_filter",
            f"• Only shadow-ledger-verified setups fire to your phone",
            f"• 2 tiers: 🎯 EXECUTE (take action) | 🔔 WATCH (get ready)",
            f"",
            f"*Expected volume:*",
            f"• EXECUTE alerts: 1-3/day",
            f"• WATCH alerts: 3-8/day",
            f"• Filter target: ~170 raw → 4-11 actionable",
            f"",
            f"*Tune it:*",
            f"• Set `PREMIUM_ALERTS_ENABLED=false` in .env to revert to raw firehose",
            f"• See /edges for the verified setups",
            f"• See /watch for current pre-stages",
        ]
        return "\n".join(lines)

    def _cmd_edges(self) -> str:
        """Show the shadow-ledger-verified edges and blocks."""
        try:
            from alerts.premium_filter import _SHADOW_EDGES, _SHADOW_BLOCKS, _ADVERSE_REGIMES
        except Exception as e:
            return f"Edge table not loaded: {e}"

        lines = ["📊 *Shadow-Ledger Edges*", ""]

        lines.append("✅ *Verified edges (EXECUTE candidates)*:")
        for (sym, side, strat), data in sorted(
            _SHADOW_EDGES.items(), key=lambda x: -float(x[1]["wr"])
        ):
            wr = float(data["wr"]) * 100
            n = int(data["n"])
            grade = data["grade"]
            side_emoji = "🟢" if side == "BUY" else "🔴"
            lines.append(
                f"  {side_emoji} {sym} {side} via {strat}: {wr:.0f}% WR on {n} ({grade})"
            )

        lines.append("")
        lines.append("🚫 *Blocked (verified money losers)*:")
        for (sym, side, strat) in sorted(_SHADOW_BLOCKS):
            side_emoji = "🟢" if side == "BUY" else "🔴"
            lines.append(f"  {side_emoji} {sym} {side} via {strat}")

        if _ADVERSE_REGIMES:
            lines.append("")
            lines.append("⚠️ *Regime-adverse combos*:")
            for (sym, side), regimes in _ADVERSE_REGIMES.items():
                lines.append(f"  {sym} {side} avoided in: {', '.join(sorted(regimes))}")

        lines.append("")
        lines.append("💡 Rebuilt from 3,835 shadow ledger entries. See /alerts for filter status.")
        return "\n".join(lines)

    def _cmd_briefing(self) -> str:
        """Morning briefing — everything you need to know in one screen.

        Built 2026-04-16 per user's ask: "I want a visually appealing
        easy-to-scan one-screen morning view when I wake up."

        Updated 2026-04-16 to show BOTH windows — today (since UTC
        midnight, matches circuit breaker daily_pnl) AND last 7 days.
        The single daily_pnl number was confusing when big wins landed
        just before UTC midnight.
        """
        from datetime import datetime, timezone, timedelta
        import csv
        now = datetime.now(timezone.utc)
        lines = ["☀️ *Morning Briefing*", f"_{now.strftime('%Y-%m-%d %H:%M UTC')}_", ""]

        # Read trades.csv once, compute multiple windows.
        trades_today = []      # since UTC midnight (matches daily_pnl)
        trades_24h = []        # rolling last 24h
        trades_7d = []         # rolling last 7 days
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)
        try:
            with open("bot/data/trades.csv", "r", encoding="utf-8") as f:
                r = csv.reader(f)
                next(r)
                today_str = now.strftime("%Y-%m-%d")
                for row in r:
                    try:
                        ts = row[0]
                        pnl = float(row[10])
                        tdt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if tdt.tzinfo is None:
                            tdt = tdt.replace(tzinfo=timezone.utc)
                        if ts.startswith(today_str):
                            trades_today.append(pnl)
                        if tdt >= cutoff_24h:
                            trades_24h.append(pnl)
                        if tdt >= cutoff_7d:
                            trades_7d.append(pnl)
                    except Exception:
                        continue
        except Exception:
            pass

        def _winline(emoji_pfx, label, trades):
            if not trades:
                return f"{emoji_pfx} *{label}*: no trades"
            n = len(trades)
            wins = sum(1 for p in trades if p > 0)
            net = sum(trades)
            emoji = "📈" if net > 0 else ("📉" if net < 0 else "➡️")
            return f"{emoji} *{label}*: {n} trades, {wins}W/{n-wins}L, net ${net:+.2f}"

        # Equity + multiple PnL windows
        try:
            equity = self.bot.risk_mgr.equity if self.bot else 0
            lines.append(f"💰 *Equity*: ${equity:,.2f}")
            lines.append(_winline("  ", "Today (since UTC 00:00)", trades_today))
            lines.append(_winline("  ", "Last 24h rolling", trades_24h))
            lines.append(_winline("  ", "Last 7d rolling", trades_7d))
            lines.append("")
        except Exception:
            lines.append("📊 Equity: unavailable")

        # Open positions
        try:
            if self.bot and hasattr(self.bot.pos_mgr, "positions"):
                open_pos = [
                    p for p in self.bot.pos_mgr.positions.values() if p.qty > 0
                ]
                lines.append(f"💼 *Open*: {len(open_pos)} position{'s' if len(open_pos) != 1 else ''}")
                for p in open_pos[:5]:
                    side_emoji = "🟢" if p.side == "LONG" else "🔴"
                    lines.append(
                        f"  {side_emoji} {p.symbol} {p.side} @ ${p.entry:.4g} ({p.state})"
                    )
                if not open_pos:
                    lines.append("  (flat — scanning)")
        except Exception:
            pass

        # Recent WATCH alerts
        try:
            from alerts.premium_filter import _last_watch_alert, _WATCH_ALERT_COOLDOWN_S
            import time as _t
            now_ts = _t.time()
            recent = [k for k, t in _last_watch_alert.items() if (now_ts - t) < _WATCH_ALERT_COOLDOWN_S]
            if recent:
                lines.append("")
                lines.append(f"🔔 *Watching* ({len(recent)} setups forming) — use /watch for details")
        except Exception:
            pass

        lines.append("")
        lines.append("*Quick actions:*")
        lines.append("/snapshot • /positions • /watch • /edges • /ask <q>")
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return (
            "*WAGMI Bot Commands*\n\n"
            "*🌅 Morning:*\n"
            "/briefing - One-screen morning overview\n"
            "/snapshot - Detailed status\n"
            "\n"
            "*🔔 Premium Alerts:*\n"
            "/alerts - Alert system status\n"
            "/watch - Current watchlist + pre-stages\n"
            "/edges - Shadow-ledger-verified edges\n"
            "\n"
            "*Quick Access:*\n"
            "/ask <question> - Ask the AI brain\n"
            "/copilot <idea> - AI trade plan\n"
            "/costs - LLM spend today\n\n"
            "*Trading:*\n"
            "/status - Equity, positions, PnL\n"
            "/positions - Open position details\n"
            "/close <SYM> - Force close position\n"
            "/closeall - Close all positions\n"
            "/pause / /resume - Trading control\n\n"
            "*Intelligence:*\n"
            "/llm - Brain status\n"
            "/mode <0-5> - LLM mode\n"
            "/performance - Win rate metrics\n"
            "/growth - Learning dashboard\n"
            "/intel - Market intel\n"
            "/edge <setup> - Edge analysis\n\n"
            "*Notifications:*\n"
            "/quiet / /loud - Minimal vs full alerts\n"
            "/digest / /live - Batched vs real-time\n\n"
            "*System:*\n"
            "/health - System health\n"
            "/kill / /unkill - Emergency controls\n"
            "/ops - Safety guard status"
        )

    def _cmd_growth(self) -> str:
        """Growth intelligence dashboard — hypotheses, recommendations, self-improvement."""
        if not self.bot:
            return "Bot not connected"
        try:
            return self.bot.growth.format_telegram_dashboard()
        except Exception as e:
            return f"Growth dashboard error: {e}"

    def _cmd_risk(self) -> str:
        """Self-Tuning Risk Engine status."""
        try:
            from risk.self_tuning import format_risk_status
            return format_risk_status()
        except Exception as e:
            return f"Risk engine: {e}"

    def _cmd_survival(self) -> str:
        """Survival pressure dashboard — accountability metrics."""
        try:
            from llm.survival_pressure import get_survival_report
            report = get_survival_report()
            score = report.get("survival_score", 50)
            trend = report.get("improvement_trend", "neutral")
            net_pnl = report.get("net_pnl_after_funding", 0)
            trades = report.get("total_trades", 0)
            wr = report.get("win_rate", 0)
            streak = report.get("current_streak", 0)
            lines = [
                "*Survival Pressure*",
                f"Score: {score:.0f}/100 ({trend})",
                f"Net PnL (after funding): ${net_pnl:+,.2f}",
                f"Trades: {trades} | WR: {wr:.0%}",
                f"Streak: {streak:+d}",
            ]
            warnings = report.get("warnings", [])
            if warnings:
                lines.append(f"Warnings: {', '.join(warnings[-3:])}")
            return "\n".join(lines)
        except Exception as e:
            return f"Survival pressure: {e}"

    def _cmd_learn(self) -> str:
        """Learning mode status — phase, progress, counterfactual accuracy."""
        try:
            from llm.learning_mode import get_learning_report
            report = get_learning_report()
            phase = report.get("phase", "UNKNOWN")
            graduated = report.get("graduated", False)
            signals = report.get("signals_observed", 0)
            trades = report.get("trades_observed", 0)
            cf_acc = report.get("counterfactual_accuracy", 0)
            cf_total = report.get("counterfactual_total", 0)
            lines = [
                "*Learning Mode*",
                f"Phase: {phase}" + (" (GRADUATED)" if graduated else ""),
                f"Signals observed: {signals}",
                f"Trades observed: {trades}",
                f"Counterfactual accuracy: {cf_acc:.0%} ({cf_total} samples)",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Learning mode: {e}"

    def _cmd_edge(self, args: str = "") -> str:
        """Show setup profitability from trade history.

        Usage: /edge [setup_type] [symbol] [regime]
        Examples: /edge, /edge mean_reversion, /edge trend_follow BTC
        """
        try:
            import json
            from pathlib import Path

            # Load trade DNA
            dna_path = Path("data/llm/deep_memory/trade_dna.json")
            if not dna_path.exists():
                # Fall back to trade outcomes
                outcomes_path = Path("data/analysis/trade_outcomes.csv")
                if not outcomes_path.exists():
                    return "No trade data found. Run some trades first."
                import csv
                trades = []
                with open(outcomes_path) as f:
                    for row in csv.DictReader(f):
                        trades.append(row)
            else:
                with open(dna_path) as f:
                    data = json.load(f)
                trades = data.get("trades", [])

            if not trades:
                return "No trade history available."

            # Parse filter args
            parts = args.strip().split() if args else []
            filter_setup = parts[0] if len(parts) > 0 else None
            filter_symbol = parts[1].upper() if len(parts) > 1 else None
            filter_regime = parts[2] if len(parts) > 2 else None

            # Group by setup type (or entry_type as fallback)
            from collections import defaultdict
            setups: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
            for t in trades:
                setup = t.get("setup_type") or t.get("entry_type", "unknown")
                sym = t.get("symbol", "")
                regime = t.get("regime", "")
                if filter_setup and setup != filter_setup:
                    continue
                if filter_symbol and filter_symbol not in sym:
                    continue
                if filter_regime and regime != filter_regime:
                    continue
                s = setups[setup]
                s["trades"] += 1
                outcome = t.get("outcome", "")
                pnl = float(t.get("pnl", 0) or 0)
                if outcome == "WIN" or pnl > 0:
                    s["wins"] += 1
                s["pnl"] += pnl

            if not setups:
                return f"No trades match filters: setup={filter_setup} symbol={filter_symbol} regime={filter_regime}"

            lines = ["*Edge Map*"]
            if filter_symbol:
                lines.append(f"Symbol: {filter_symbol}")
            if filter_regime:
                lines.append(f"Regime: {filter_regime}")
            lines.append("")

            for setup in sorted(setups.keys(), key=lambda k: -setups[k]["pnl"]):
                s = setups[setup]
                t = s["trades"]
                wr = s["wins"] / t * 100 if t > 0 else 0
                pnl = s["pnl"]
                verdict = "EDGE" if pnl > 0 and wr > 50 else "AVOID" if pnl < 0 else "NEUTRAL"
                lines.append(
                    f"{setup}: {wr:.0f}% WR ({t} trades) ${pnl:+,.0f} [{verdict}]"
                )

            return "\n".join(lines)
        except Exception as e:
            return f"Edge analysis error: {e}"

    def _cmd_thesis(self) -> str:
        """Show recent thesis predictions with outcome tracking."""
        try:
            from llm.thesis_tracker import get_thesis_tracker
            tracker = get_thesis_tracker()
            summary = tracker.get_accuracy_summary()
            recent = tracker.get_recent(limit=5)

            lines = ["*Thesis Tracking*"]
            total = summary.get("total", 0)
            if total > 0:
                correct = summary.get("correct", 0)
                acc = correct / total * 100
                lines.append(f"Accuracy: {acc:.0f}% ({correct}/{total})")
                lines.append(f"Avg confidence: {summary.get('avg_confidence', 0):.0%}")
                lines.append(f"By regime: {summary.get('by_regime', {})}")
            else:
                lines.append("No theses tracked yet. Enable LLM_MODE >= 2.")

            if recent:
                lines.append("\n*Recent Theses:*")
                for t in recent[:5]:
                    status = "CORRECT" if t.get("correct") else "WRONG" if t.get("resolved") else "PENDING"
                    lines.append(
                        f"  {t.get('symbol', '?')} {t.get('side', '?')} "
                        f"conf={t.get('confidence', 0):.0%} [{status}]"
                    )
                    if t.get("thesis"):
                        lines.append(f"    {t['thesis'][:80]}")

            return "\n".join(lines)
        except Exception as e:
            return f"Thesis tracking: {e}"

    def _cmd_submit_signal(self, args: str = "") -> str:
        """Submit a manual trade signal for risk-gated execution.

        Usage: /signal BTC LONG 85000 SL 84000 TP 87000 [TP2 89000]
        The signal goes through the same RiskFilterChain as automated signals.
        """
        if not args or not args.strip():
            return (
                "*Manual Signal Submission*\n\n"
                "Usage: /signal SYMBOL SIDE ENTRY SL STOP TP TARGET [TP2 TARGET2]\n"
                "Example: /signal BTC LONG 85000 SL 84000 TP 87000\n"
                "Example: /signal SOL SHORT 145 SL 148 TP 138 TP2 132\n\n"
                "Signal goes through all risk gates before execution."
            )

        try:
            parts = args.strip().upper().split()
            if len(parts) < 6:
                return "Need at least: SYMBOL SIDE ENTRY SL price TP price"

            symbol = parts[0]
            side = parts[1]
            if side not in ("LONG", "SHORT", "BUY", "SELL"):
                return f"Invalid side: {side}. Use LONG/SHORT or BUY/SELL."
            # Normalize
            if side == "LONG":
                side = "BUY"
            elif side == "SHORT":
                side = "SELL"

            entry = float(parts[2])

            # Parse SL and TP
            sl = tp1 = tp2 = 0
            i = 3
            while i < len(parts):
                if parts[i] == "SL" and i + 1 < len(parts):
                    sl = float(parts[i + 1])
                    i += 2
                elif parts[i] == "TP" and i + 1 < len(parts):
                    tp1 = float(parts[i + 1])
                    i += 2
                elif parts[i] == "TP2" and i + 1 < len(parts):
                    tp2 = float(parts[i + 1])
                    i += 2
                else:
                    i += 1

            if sl == 0 or tp1 == 0:
                return "Missing SL or TP. Use: /signal BTC LONG 85000 SL 84000 TP 87000"
            if tp2 == 0:
                # Auto-compute TP2 at 2x the TP1 distance
                tp2 = entry + 2 * (tp1 - entry)

            # Validate direction
            if side == "BUY" and sl >= entry:
                return f"SL ({sl}) must be below entry ({entry}) for LONG"
            if side == "SELL" and sl <= entry:
                return f"SL ({sl}) must be above entry ({entry}) for SHORT"

            risk = abs(entry - sl)
            reward1 = abs(tp1 - entry)
            rr = reward1 / risk if risk > 0 else 0

            lines = [
                "*Manual Signal Received*",
                f"Symbol: {symbol} {side}",
                f"Entry: ${entry:,.2f}",
                f"SL: ${sl:,.2f} (risk: ${risk:,.2f})",
                f"TP1: ${tp1:,.2f} (R:R {rr:.1f}x)",
                f"TP2: ${tp2:,.2f}",
                "",
                "Status: QUEUED for risk gate evaluation",
                "The bot will evaluate this signal on the next scan cycle.",
            ]

            # Store the manual signal for the main loop to pick up
            try:
                import json
                from pathlib import Path
                queue_file = Path("data/manual_signals.json")
                queue_file.parent.mkdir(parents=True, exist_ok=True)
                queue = []
                if queue_file.exists():
                    with open(queue_file) as f:
                        queue = json.load(f)
                queue.append({
                    "symbol": symbol,
                    "side": side,
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "confidence": 70.0,  # Manual signals get moderate confidence
                    "source": "telegram_manual",
                    "timestamp": __import__("time").time(),
                })
                with open(queue_file, "w") as f:
                    json.dump(queue, f, indent=2)
                lines.append(f"Queued successfully. R:R = {rr:.1f}x")
            except Exception as e:
                lines.append(f"Warning: queue write failed: {e}")

            return "\n".join(lines)
        except ValueError as e:
            return f"Parse error: {e}. Use numbers for prices."
        except Exception as e:
            return f"Signal submission error: {e}"

    def _cmd_rl(self) -> str:
        """RL system status: buffer stats + policy state."""
        try:
            from rl.buffer import get_buffer_stats
            from rl.apply_policy import is_rl_enabled
            stats = get_buffer_stats()
            lines = [
                "*RL System*",
                f"Policy enabled: {is_rl_enabled()}",
                f"Buffer transitions: {stats.get('total', 0)}",
            ]
            if stats.get("total", 0) > 0:
                lines.append(f"Avg reward: {stats.get('avg_reward', 0):.4f}")
                lines.append(f"Win rate: {stats.get('win_rate', 0):.1%}")
            return "\n".join(lines)
        except Exception as e:
            return f"RL system: {e}"

    # ── Manual Trade Journal Commands ─────────────

    def _cmd_trade(self, args: str) -> str:
        """Log a manual trade entry.

        Usage: /trade HYPE BUY 40.50 25x 10
               /trade SYMBOL SIDE PRICE LEVERAGEx QTY
        """
        if not args or not args.strip():
            return (
                "*Manual Trade Entry*\n\n"
                "Usage: /trade SYMBOL SIDE PRICE LEVERAGEx QTY\n"
                "Example: /trade HYPE BUY 40.50 25x 10\n"
                "Example: /trade SOL SELL 145.20 20x 5\n\n"
                "SIDE: BUY/SELL or LONG/SHORT\n"
                "QTY: asset quantity (number of coins)"
            )

        try:
            parts = args.strip().split()
            if len(parts) < 5:
                return "Need: SYMBOL SIDE PRICE LEVERAGEx QTY\nExample: /trade HYPE BUY 40.50 25x 10"

            symbol = parts[0].upper()
            side = parts[1].upper()
            entry_price = float(parts[2])

            # Parse leverage (accept "25x" or "25")
            lev_str = parts[3].lower().rstrip("x")
            leverage = float(lev_str)

            qty = float(parts[4])

            if leverage <= 0 or leverage > 100:
                return f"Invalid leverage: {leverage}. Must be 1-100."
            if entry_price <= 0:
                return f"Invalid price: {entry_price}"
            if qty <= 0:
                return f"Invalid qty: {qty}"

            from manual.trade_journal import get_trade_journal
            journal = get_trade_journal()
            entry = journal.log_entry(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                leverage=leverage,
                qty=qty,
            )

            position_value = entry_price * qty
            margin = position_value / leverage

            return (
                f"*Trade Logged*\n\n"
                f"ID: `{entry.trade_id}`\n"
                f"{symbol} {side} @ ${entry_price:,.4f}\n"
                f"Leverage: {leverage:.0f}x\n"
                f"Qty: {qty}\n"
                f"Position: ${position_value:,.2f}\n"
                f"Margin: ${margin:,.2f}\n\n"
                f"Equity: ${journal.current_equity:,.2f}\n"
                f"Use /exit {symbol} PRICE REASON to close"
            )
        except ValueError as e:
            return f"Parse error: {e}\nUsage: /trade SYMBOL SIDE PRICE LEVx QTY"
        except Exception as e:
            return f"Trade entry error: {e}"

    def _cmd_exit(self, args: str) -> str:
        """Log a trade exit.

        Usage: /exit HYPE 42.00 TP
               /exit SYMBOL PRICE [REASON]
        """
        if not args or not args.strip():
            return (
                "*Manual Trade Exit*\n\n"
                "Usage: /exit SYMBOL PRICE [REASON]\n"
                "Example: /exit HYPE 42.00 TP\n"
                "Example: /exit SOL 138.50 SL\n"
                "Example: /exit MJ-A1B2C3D4 42.00 MANUAL\n\n"
                "REASON: TP, SL, MANUAL, BREAKEVEN (default: MANUAL)"
            )

        try:
            parts = args.strip().split()
            if len(parts) < 2:
                return "Need at least: SYMBOL PRICE\nExample: /exit HYPE 42.00 TP"

            trade_id_or_symbol = parts[0].upper()
            exit_price = float(parts[1])
            reason = parts[2].upper() if len(parts) > 2 else "MANUAL"

            from manual.trade_journal import get_trade_journal
            journal = get_trade_journal()
            trade = journal.log_exit(
                trade_id_or_symbol=trade_id_or_symbol,
                exit_price=exit_price,
                reason=reason,
            )

            if not trade:
                open_trades = journal.get_open_trades()
                if open_trades:
                    syms = ", ".join(t.symbol for t in open_trades)
                    return f"No open trade for '{trade_id_or_symbol}'\nOpen trades: {syms}"
                return f"No open trade for '{trade_id_or_symbol}'. No open trades."

            pnl = trade.pnl or 0
            pnl_pct = trade.pnl_pct or 0
            emoji = "+" if pnl >= 0 else ""

            return (
                f"*Trade Closed*\n\n"
                f"ID: `{trade.trade_id}`\n"
                f"{trade.symbol} {trade.side} — {reason}\n"
                f"Entry: ${trade.entry_price:,.4f}\n"
                f"Exit: ${exit_price:,.4f}\n"
                f"PnL: ${pnl:+,.2f} ({pnl_pct:+.1f}% on margin)\n"
                f"Hold: {trade.hold_time_hours:.1f}h\n\n"
                f"Equity: ${journal.current_equity:,.2f}"
            )
        except ValueError as e:
            return f"Parse error: {e}\nUsage: /exit SYMBOL PRICE [REASON]"
        except Exception as e:
            return f"Trade exit error: {e}"

    def _cmd_journal(self) -> str:
        """Show recent trades and stats."""
        try:
            from manual.trade_journal import get_trade_journal
            journal = get_trade_journal()
            stats = journal.get_stats()
            recent = journal.get_recent_trades(5)
            open_trades = journal.get_open_trades()

            lines = [
                "=" * 28,
                "  TRADE JOURNAL",
                "=" * 28,
            ]

            # Open positions
            if open_trades:
                lines.append(f"\n*Open Positions ({len(open_trades)}):*")
                for t in open_trades:
                    lines.append(
                        f"  `{t.trade_id}` {t.symbol} {t.side} "
                        f"@ ${t.entry_price:,.4f} {t.leverage:.0f}x"
                    )

            # Stats
            if stats["total_trades"] > 0:
                lines.extend([
                    f"\n*Stats ({stats['total_trades']} trades):*",
                    f"  WR: {stats['win_rate']:.0%} ({stats.get('wins', 0)}W/{stats.get('losses', 0)}L)",
                    f"  PF: {stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else f"  PF: INF",
                    f"  PnL: ${stats['total_pnl']:+,.2f}",
                    f"  Best: ${stats['best_trade']:+,.2f}",
                    f"  Worst: ${stats['worst_trade']:+,.2f}",
                    f"  Avg hold: {stats['avg_hold_hours']:.1f}h",
                ])

            # Recent closed trades
            closed_recent = [t for t in recent if t.status == "CLOSED"]
            if closed_recent:
                lines.append(f"\n*Recent Trades:*")
                for t in closed_recent[-5:]:
                    pnl = t.pnl or 0
                    lines.append(
                        f"  {t.symbol} {t.side} ${pnl:+,.2f} "
                        f"({t.exit_reason or '?'}) {t.hold_time_hours:.1f}h"
                    )

            lines.extend([
                f"\n*Equity: ${journal.current_equity:,.2f}*",
                "=" * 28,
            ])

            return "\n".join(lines)
        except Exception as e:
            return f"Journal error: {e}"

    def _cmd_equity(self) -> str:
        """Show account growth and compounding progress."""
        try:
            from manual.trade_journal import get_trade_journal
            journal = get_trade_journal()
            report = journal.get_compounding_report()
            stats = journal.get_stats()

            progress = report["progress_pct"]
            bar_len = 20
            filled = int(progress / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)

            lines = [
                "=" * 30,
                "  EQUITY & COMPOUNDING",
                "=" * 30,
                "",
                f"Starting:  ${report['starting_equity']:,.2f}",
                f"Current:   ${report['current_equity']:,.2f}",
                f"Return:    ${report['total_return']:+,.2f} ({report['total_return_pct']:+.1f}%)",
                "",
                f"Days Trading: {report['days_elapsed']:.1f}",
                f"Trades/Day:   {report['trades_per_day']:.1f}",
                f"Daily Growth: {report['daily_compound_rate_pct']:+.2f}%/day",
                "",
                f"Target: $1,000",
                f"[{bar}] {progress:.1f}%",
            ]

            if report["days_to_target"] is not None:
                if report["days_to_target"] == 0:
                    lines.append("TARGET REACHED!")
                else:
                    lines.append(f"ETA: {report['days_to_target']:.0f} days ({report['projected_target_date']})")

            # Projections
            proj = report["projections"]
            if proj:
                lines.append(f"\n*Projections (at current rate):*")
                for period, value in proj.items():
                    lines.append(f"  {period}: ${value:,.2f}")

            # Streaks
            if stats["total_trades"] > 0:
                lines.extend([
                    "",
                    f"Win Streak: {stats.get('longest_win_streak', 0)}",
                    f"Loss Streak: {stats.get('longest_loss_streak', 0)}",
                    f"Return: {stats['total_return_pct']:+.1f}%",
                ])

            lines.append("=" * 30)
            return "\n".join(lines)
        except Exception as e:
            return f"Equity report error: {e}"

    def _cmd_perf(self) -> str:
        """Show performance analysis vs signals."""
        try:
            from manual.performance import PerformanceAnalyzer
            analyzer = PerformanceAnalyzer()
            return analyzer.format_performance_report()
        except Exception as e:
            return f"Performance error: {e}"

    def _cmd_tracker(self) -> str:
        """Daily P&L tracker for the $100 sniper account."""
        try:
            from manual.daily_tracker import DailyTracker, format_daily_dashboard
            tracker = DailyTracker()
            return format_daily_dashboard(tracker)
        except Exception as e:
            return f"Tracker error: {e}"

    def _cmd_optimize(self) -> str:
        """Sniper optimizer — signal quality, leverage efficiency, recommendations."""
        try:
            from manual.optimizer import SniperOptimizer
            opt = SniperOptimizer()
            return opt.format_telegram_summary()
        except Exception as e:
            return f"Optimizer error: {e}"

    def _cmd_manage(self, args: str) -> str:
        """Position management advice: /manage HYPE 40.50 [SELL] [15x] [PREMIUM]"""
        try:
            from datetime import datetime, timezone, timedelta
            from manual.position_rules import format_position_update
            from manual.config import ManualSniperConfig

            parts = args.strip().split()
            if len(parts) < 2:
                return (
                    "Usage: /manage SYMBOL ENTRY_PRICE [SIDE] [LEVx] [TIER]\n"
                    "Example: /manage HYPE 25.50\n"
                    "Example: /manage HYPE 25.50 BUY 25x SNIPER"
                )

            symbol = parts[0].upper()
            entry = float(parts[1])

            # Optional args
            side = "BUY"
            leverage = 25.0
            tier = "SNIPER"
            for p in parts[2:]:
                pu = p.upper()
                if pu in ("BUY", "SELL"):
                    side = pu
                elif pu.endswith("X") and pu[:-1].replace(".", "").isdigit():
                    leverage = float(pu[:-1])
                elif pu in ("SNIPER", "PREMIUM", "STANDARD"):
                    tier = pu

            # Derive SL/TP from entry using standard 2% stop width
            stop_pct = 0.02
            risk = entry * stop_pct
            if side == "BUY":
                sl = entry - risk
                tp_scalp = entry + risk * 1.5
                tp_swing = entry + risk * 3.0
            else:
                sl = entry + risk
                tp_scalp = entry - risk * 1.5
                tp_swing = entry - risk * 3.0

            config = ManualSniperConfig()
            equity = config.equity

            # Get current price from exchange if available
            current_price = entry  # default to entry
            if self.bot:
                try:
                    ticker = self.bot.exchange.fetch_ticker(f"{symbol}/USDC:USDC")
                    current_price = ticker.get("last", entry)
                except Exception:
                    try:
                        ticker = self.bot.exchange.fetch_ticker(f"{symbol}/USDT:USDT")
                        current_price = ticker.get("last", entry)
                    except Exception:
                        pass

            # Assume entered recently (15 min ago as default)
            entry_time = datetime.now(timezone.utc) - timedelta(minutes=15)

            msg = format_position_update(
                symbol=symbol, side=side, entry=entry,
                current_price=current_price, leverage=leverage,
                tier=tier, equity=equity, sl=sl,
                tp_scalp=tp_scalp, tp_swing=tp_swing,
                entry_time=entry_time,
            )
            return msg
        except ValueError:
            return "Invalid price. Usage: /manage HYPE 25.50"
        except Exception as e:
            return f"Manage error: {e}"

    def _cmd_pause(self) -> str:
        self._paused = True
        return "Trading PAUSED. Signals still evaluated but no new positions will open."

    def _cmd_resume(self) -> str:
        self._paused = False
        return "Trading RESUMED."

    # ── New Copilot Commands (Blueprint Phase 2) ─────────────────

    def _cmd_ask(self, args: str) -> str:
        """Ask the AI brain a question. It has full market context."""
        question = args.strip()
        if not question:
            return "Usage: /ask <question>\nExample: /ask What do you think about BTC right now?"
        try:
            from llm.client import call_llm
            # Build lean context
            ctx_parts = [f"Question from trader: {question}"]
            if self.bot:
                eq = self.bot.risk_mgr.equity
                daily = self.bot.risk_mgr.circuit_breaker.daily_pnl
                n_pos = self.bot.pos_mgr.get_open_count()
                ctx_parts.append(f"Account: ${eq:,.2f} equity, ${daily:+,.2f} daily PnL, {n_pos} open positions")
                # Add open position details
                open_pos = self.bot.pos_mgr.get_open_positions()
                if open_pos:
                    pos_lines = []
                    for sym, pos in open_pos.items():
                        pos_lines.append(f"{sym} {pos.side} {pos.leverage:.0f}x entry={pos.entry} sl={pos.sl}")
                    ctx_parts.append("Open positions: " + "; ".join(pos_lines))
                # Add recent prices
                prices = {}
                for sym in ["BTC", "ETH", "SOL", "HYPE"]:
                    p = self.bot._last_prices.get(sym)
                    if p:
                        prices[sym] = p
                if prices:
                    ctx_parts.append("Prices: " + ", ".join(f"{s}=${p:,.2f}" for s, p in prices.items()))

            system_prompt = (
                "You are the WAGMI quant brain. Answer the trader's question concisely "
                "using the market context provided. Be direct and actionable. "
                "If they ask about a trade idea, give entry/SL/TP levels. "
                "Keep response under 200 words."
            )
            result, usage = call_llm(
                system_prompt=system_prompt,
                snapshot_json="\n".join(ctx_parts),
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                timeout=20.0,
            )
            if result:
                cost = (usage.get("input_tokens", 0) * 0.80 + usage.get("output_tokens", 0) * 4.0) / 1_000_000
                return f"*Brain says:*\n{result}\n\n_Cost: ${cost:.4f}_"
            return f"Brain unavailable: {usage.get('error', 'unknown')}"
        except Exception as e:
            return f"Ask error: {e}"

    def _cmd_snapshot(self) -> str:
        """Quick snapshot: equity, positions, PnL, API budget, bot status."""
        if not self.bot:
            return "Bot not connected"
        try:
            eq = self.bot.risk_mgr.equity
            daily = self.bot.risk_mgr.circuit_breaker.daily_pnl
            n_pos = self.bot.pos_mgr.get_open_count()
            paused = "PAUSED" if self._paused else "ACTIVE"
            mode = getattr(self.bot, 'llm_mode', 0)

            # LLM budget
            budget_line = ""
            try:
                from llm.cost_tracker import get_cost_tracker
                ct = get_cost_tracker()
                pct = ct.get_budget_used_pct()
                spent = pct * float(os.environ.get("LLM_DAILY_BUDGET_USD", "5"))
                cap = float(os.environ.get("LLM_DAILY_BUDGET_USD", "5"))
                budget_line = f"API: ${spent:.2f}/${cap:.2f} ({pct:.0%})"
            except Exception:
                budget_line = "API: N/A"

            # Open positions summary
            pos_lines = []
            open_pos = self.bot.pos_mgr.get_open_positions()
            total_unreal = 0.0
            for sym, pos in open_pos.items():
                price = self.bot._last_prices.get(sym, pos.entry)
                if pos.side == "LONG":
                    unreal = (price - pos.entry) * pos.qty * pos.leverage
                else:
                    unreal = (pos.entry - price) * pos.qty * pos.leverage
                total_unreal += unreal
                pos_lines.append(f"  {sym} {pos.side} {pos.leverage:.0f}x {unreal:+.2f}")

            msg = (
                f"*WAGMI Snapshot*\n"
                f"Status: {paused} | Mode: {mode}\n"
                f"Equity: ${eq:,.2f} | Daily: ${daily:+,.2f}\n"
                f"Positions: {n_pos} | Unrealized: ${total_unreal:+,.2f}\n"
                f"{budget_line}\n"
                f"Tick: {self.bot._tick}"
            )
            if pos_lines:
                msg += "\n\n*Open:*\n" + "\n".join(pos_lines)
            return msg
        except Exception as e:
            return f"Snapshot error: {e}"

    def _cmd_costs(self) -> str:
        """LLM API cost tracking: today's spend, budget, calls by model."""
        try:
            from llm.cost_tracker import get_cost_tracker
            ct = get_cost_tracker()
            pct = ct.get_budget_used_pct()
            cap = float(os.environ.get("LLM_DAILY_BUDGET_USD", "5"))
            spent = pct * cap

            # Get call counts from client stats
            from llm.client import get_usage_stats
            stats = get_usage_stats()

            return (
                f"*LLM Costs Today*\n"
                f"Spent: ${spent:.3f} / ${cap:.2f} ({pct:.0%})\n"
                f"Calls: {stats.get('total_calls', 0)} ({stats.get('total_failures', 0)} failed)\n"
                f"Tokens: {stats.get('total_input_tokens', 0):,} in / {stats.get('total_output_tokens', 0):,} out\n"
                f"Estimated cost: ${stats.get('estimated_cost_usd', 0):.4f}\n\n"
                f"_Budget resets at midnight UTC_"
            )
        except Exception as e:
            return f"Cost tracking error: {e}"

    def _cmd_copilot_trade(self, args: str) -> str:
        """AI-powered trade copilot. Describe what you want, get a full play."""
        idea = args.strip()
        if not idea:
            return (
                "Usage: /copilot <trade idea>\n"
                "Examples:\n"
                "  /copilot I want to short BTC 20x\n"
                "  /copilot ETH looks bullish, what's the play?\n"
                "  /copilot Is SOL a good short here?"
            )
        try:
            from llm.client import call_llm
            # Build rich context
            ctx_parts = [f"Trader's idea: {idea}"]
            if self.bot:
                eq = self.bot.risk_mgr.equity
                ctx_parts.append(f"Account equity: ${eq:,.2f}")
                # Current prices
                prices = {}
                for sym in ["BTC", "ETH", "SOL", "HYPE"]:
                    p = self.bot._last_prices.get(sym)
                    if p:
                        prices[sym] = p
                if prices:
                    ctx_parts.append("Current prices: " + ", ".join(f"{s}=${p:,.2f}" for s, p in prices.items()))
                # Open positions
                open_pos = self.bot.pos_mgr.get_open_positions()
                if open_pos:
                    pos_lines = [f"{sym} {pos.side} {pos.leverage:.0f}x" for sym, pos in open_pos.items()]
                    ctx_parts.append("Already open: " + ", ".join(pos_lines))

            system_prompt = (
                "You are the WAGMI quant brain copilot. The trader described a trade idea. "
                "Deliver the FULL PLAY:\n"
                "1. Entry: market or limit + price level\n"
                "2. Stop Loss: price + reasoning\n"
                "3. Take Profit 1 & 2: prices + R:R ratios\n"
                "4. Recommended leverage (data says 1.5-3x = optimal, 6x+ loses money)\n"
                "5. Thesis: 1-2 sentences\n"
                "6. Risk assessment: what could go wrong\n"
                "7. Confidence: 0-100%\n\n"
                "GROUND TRUTH: ETH=47% WR (best), HYPE=24% (worst). "
                "Trending regime=56% WR, ranging=19%. "
                "Low leverage (1.5-3x)=+$6.59 avg, high (6-15x)=-$6.33.\n"
                "Be direct. Use numbers. Keep under 250 words."
            )
            result, usage = call_llm(
                system_prompt=system_prompt,
                snapshot_json="\n".join(ctx_parts),
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                timeout=25.0,
            )
            if result:
                cost = (usage.get("input_tokens", 0) * 0.80 + usage.get("output_tokens", 0) * 4.0) / 1_000_000
                return f"*Trade Copilot:*\n\n{result}\n\n_Cost: ${cost:.4f} | To execute, use /close or manual entry_"
            return f"Copilot unavailable: {usage.get('error', 'unknown')}"
        except Exception as e:
            return f"Copilot error: {e}"

    def _cmd_quiet(self) -> str:
        """Enable quiet mode: only circuit breakers + daily summary."""
        self._quiet_mode = True
        return "Quiet mode ON. You'll only see circuit breakers and daily summaries.\n/loud to restore."

    def _cmd_loud(self) -> str:
        """Disable quiet mode: all notifications."""
        self._quiet_mode = False
        return "Loud mode ON. All notifications restored."

    def _cmd_digest(self) -> str:
        """Enable digest mode: batch updates every 30 min."""
        self._digest_mode = True
        self._digest_buffer = []
        return "Digest mode ON. Updates batched every 30 min.\n/live to restore real-time."

    def _cmd_live(self) -> str:
        """Disable digest mode: real-time notifications."""
        self._digest_mode = False
        # Flush any buffered messages
        if self._digest_buffer:
            flushed = len(self._digest_buffer)
            self._digest_buffer = []
            return f"Live mode ON. Flushed {flushed} buffered messages."
        return "Live mode ON. Real-time notifications restored."
