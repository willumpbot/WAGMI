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
            # No user ID configured - accept this user and log a setup hint
            logger.warning(
                f"TELEGRAM_ALLOWED_USER_ID not set! "
                f"Add TELEGRAM_ALLOWED_USER_ID={user_id} to your .env file "
                f"to authorize this user and silence this warning."
            )
            # Auto-authorize so the bot works during initial setup
            self.allowed_user_id = user_id
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
            "/help": self._cmd_help,
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

    def _cmd_help(self) -> str:
        return (
            "*nunuIRL Bot Commands*\n\n"
            "*Trading:*\n"
            "/status - Equity, positions, PnL\n"
            "/positions - Open position details\n"
            "/close <SYM> - Force close position\n"
            "/closeall - Close all positions\n"
            "/pause - Pause trading\n"
            "/resume - Resume trading\n\n"
            "*LLM & Learning:*\n"
            "/llm - LLM meta-brain status\n"
            "/mode <0-5> - View/change LLM mode\n"
            "/roadmap - Knowledge roadmap status & gates\n"
            "/promote - Advance to next roadmap phase\n"
            "/demote <phase> - Demote to lower phase\n"
            "/curriculum - Curriculum level & stats\n"
            "/knowledge - Browse knowledge base\n"
            "/progression - Mode promotion readiness\n\n"
            "*Signals:*\n"
            "/signals - Recent ingested signals\n"
            "/analyze <text> - Analyze a signal with LLM\n"
            "/accuracy - Signal analysis accuracy\n\n"
            "*System:*\n"
            "/health - System health check\n"
            "/ml - ML learner stats\n"
            "/performance - Win rate and metrics\n"
            "/uplift - LLM uplift analytics\n"
            "/copytrades - Human copy-tradable signals\n"
            "/telemetry - Execution quality metrics\n"
            "/proposals - Strategy discovery proposals\n"
            "/kill [reason] - Emergency kill switch\n"
            "/unkill - Deactivate kill switch\n"
            "/ops - Ops guard status"
        )

    def _cmd_pause(self) -> str:
        self._paused = True
        return "Trading PAUSED. Signals still evaluated but no new positions will open."

    def _cmd_resume(self) -> str:
        self._paused = False
        return "Trading RESUMED."
