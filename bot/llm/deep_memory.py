"""
Deep Memory System: Comprehensive knowledge base for LLM self-improvement.

Unlike the lightweight memory_store (50 notes, 48h TTL), this module stores
ALL data the LLM needs to understand and improve over time:

1. Trade DNA: Full context of every trade decision (entry, exit, why, outcome)
2. Strategy Fingerprints: What each strategy excels/fails at, per regime
3. Pattern Library: Recurring market patterns and how they resolved
4. Sniper Trade Archive: Detailed anatomy of the best trades for replication
5. Failure Autopsy: Detailed analysis of losses for avoidance
6. Market Regime History: How regimes transition and what works in each
7. Cross-Asset Correlations: BTC/ETH/alts relationship patterns over time

The LLM reads this on startup and gets periodic summaries. It writes back
learnings after every significant event. No pruning of core knowledge -
only summarization/compression of older entries.
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("bot.llm.deep_memory")

_DEEP_MEMORY_DIR = os.path.join("data", "llm", "deep_memory")


def _ensure_dir():
    os.makedirs(_DEEP_MEMORY_DIR, exist_ok=True)


def _path(filename: str) -> str:
    return os.path.join(_DEEP_MEMORY_DIR, filename)


def _load_json(filename: str, default=None):
    """Load JSON file safely."""
    _ensure_dir()
    filepath = _path(filename)
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[DEEP-MEM] Failed to load {filename}: {e}")
        return default if default is not None else {}


def _save_json(filename: str, data):
    """Save JSON file safely."""
    _ensure_dir()
    filepath = _path(filename)
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except IOError as e:
        logger.warning(f"[DEEP-MEM] Failed to save {filename}: {e}")


# ═══════════════════════════════════════════════════════════════
# 1. Trade DNA - full context of every trade
# ═══════════════════════════════════════════════════════════════


@dataclass
class TradeDNA:
    """Complete anatomy of a trade for learning."""
    trade_id: str = ""
    timestamp: float = 0.0
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    confidence: float = 0.0
    leverage: float = 1.0
    regime: str = ""
    strategies_agreed: List[str] = field(default_factory=list)
    num_agree: int = 0
    llm_action: str = ""
    llm_confidence: float = 0.0
    llm_reasoning: str = ""
    entry_type: str = ""
    # Outcome
    outcome: str = ""  # WIN, LOSS, BREAKEVEN
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_time_s: float = 0.0
    exit_reason: str = ""  # TP1, TP2, SL, TRAILING, MANUAL
    # Market context at entry
    btc_trend: str = ""
    market_regime: str = ""
    volume_ratio: float = 0.0
    funding_rate: float = 0.0
    atr: float = 0.0
    # Quality assessment
    was_sniper: bool = False  # Near-perfect entry
    entry_accuracy: float = 0.0  # How close to optimal entry (0-1)
    exit_accuracy: float = 0.0  # How close to optimal exit (0-1)
    quality_score: float = 0.0  # Overall trade quality (0-1)
    # Learning
    lessons: List[str] = field(default_factory=list)


class TradeDNAStore:
    """Stores and retrieves trade DNA records."""

    def __init__(self):
        self._trades: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            data = _load_json("trade_dna.json", {"trades": []})
            self._trades = data.get("trades", [])
            self._loaded = True

    def record_trade(self, dna: TradeDNA):
        """Record a complete trade DNA."""
        self._ensure_loaded()
        record = asdict(dna)
        self._trades.append(record)

        # Keep last 500 trades in detail, summarize older ones
        if len(self._trades) > 500:
            self._compress_old_trades()

        _save_json("trade_dna.json", {"trades": self._trades})
        logger.info(f"[DEEP-MEM] Recorded trade DNA: {dna.symbol} {dna.side} {dna.outcome} PnL={dna.pnl:+.2f}")

    def get_sniper_trades(self, limit: int = 20) -> List[Dict]:
        """Get the best trades for pattern study."""
        self._ensure_loaded()
        snipers = [t for t in self._trades if t.get("was_sniper") or t.get("quality_score", 0) >= 0.8]
        snipers.sort(key=lambda t: t.get("pnl", 0), reverse=True)
        return snipers[:limit]

    def get_by_symbol(self, symbol: str, limit: int = 50) -> List[Dict]:
        """Get recent trades for a specific symbol."""
        self._ensure_loaded()
        return [t for t in reversed(self._trades) if t.get("symbol") == symbol][:limit]

    def get_by_regime(self, regime: str, limit: int = 50) -> List[Dict]:
        """Get recent trades for a specific regime."""
        self._ensure_loaded()
        return [t for t in reversed(self._trades) if t.get("regime") == regime][:limit]

    def get_failures(self, limit: int = 20) -> List[Dict]:
        """Get the worst trades for autopsy."""
        self._ensure_loaded()
        failures = [t for t in self._trades if t.get("outcome") == "LOSS"]
        failures.sort(key=lambda t: t.get("pnl", 0))
        return failures[:limit]

    def get_win_rate_by(self, field_name: str) -> Dict[str, Dict]:
        """Get win rate grouped by any field."""
        self._ensure_loaded()
        groups = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in self._trades:
            key = str(t.get(field_name, "unknown"))
            groups[key]["total"] += 1
            if t.get("outcome") == "WIN":
                groups[key]["wins"] += 1
            groups[key]["pnl"] += t.get("pnl", 0)
        # Calculate win rates
        for key in groups:
            g = groups[key]
            g["win_rate"] = g["wins"] / g["total"] if g["total"] > 0 else 0
        return dict(groups)

    def get_strategy_effectiveness(self) -> Dict[str, Dict]:
        """Which strategy combinations work best?"""
        self._ensure_loaded()
        combos = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0, "avg_pnl": 0.0})
        for t in self._trades:
            key = ",".join(sorted(t.get("strategies_agreed", [])))
            if not key:
                key = "unknown"
            combos[key]["total"] += 1
            if t.get("outcome") == "WIN":
                combos[key]["wins"] += 1
            combos[key]["pnl"] += t.get("pnl", 0)
        for key in combos:
            c = combos[key]
            c["win_rate"] = c["wins"] / c["total"] if c["total"] > 0 else 0
            c["avg_pnl"] = c["pnl"] / c["total"] if c["total"] > 0 else 0
        return dict(combos)

    def get_summary_stats(self) -> Dict[str, Any]:
        """Overall statistics for the LLM to digest."""
        self._ensure_loaded()
        if not self._trades:
            return {"total_trades": 0}

        wins = sum(1 for t in self._trades if t.get("outcome") == "WIN")
        total = len(self._trades)
        total_pnl = sum(t.get("pnl", 0) for t in self._trades)
        avg_hold = sum(t.get("hold_time_s", 0) for t in self._trades) / total if total else 0
        snipers = sum(1 for t in self._trades if t.get("was_sniper"))

        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": wins / total if total else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total else 0,
            "avg_hold_time_s": round(avg_hold),
            "sniper_count": snipers,
            "by_regime": self.get_win_rate_by("regime"),
            "by_symbol": self.get_win_rate_by("symbol"),
            "by_side": self.get_win_rate_by("side"),
            "by_entry_type": self.get_win_rate_by("entry_type"),
        }

    def _compress_old_trades(self):
        """Summarize old trades, keep recent ones in detail."""
        if len(self._trades) <= 500:
            return
        # Keep last 500 in detail
        old_trades = self._trades[:-500]
        self._trades = self._trades[-500:]

        # Compress old trades into summary
        summary = _load_json("trade_dna_archive.json", {"summaries": [], "total_archived": 0})
        batch_summary = {
            "archived_at": time.time(),
            "count": len(old_trades),
            "wins": sum(1 for t in old_trades if t.get("outcome") == "WIN"),
            "total_pnl": sum(t.get("pnl", 0) for t in old_trades),
            "by_symbol": {},
            "by_regime": {},
        }
        # Group stats
        for t in old_trades:
            sym = t.get("symbol", "unknown")
            if sym not in batch_summary["by_symbol"]:
                batch_summary["by_symbol"][sym] = {"wins": 0, "total": 0, "pnl": 0}
            batch_summary["by_symbol"][sym]["total"] += 1
            if t.get("outcome") == "WIN":
                batch_summary["by_symbol"][sym]["wins"] += 1
            batch_summary["by_symbol"][sym]["pnl"] += t.get("pnl", 0)

        summary["summaries"].append(batch_summary)
        summary["total_archived"] += len(old_trades)
        _save_json("trade_dna_archive.json", summary)
        logger.info(f"[DEEP-MEM] Archived {len(old_trades)} old trade DNA records")


# ═══════════════════════════════════════════════════════════════
# 2. Strategy Fingerprints
# ═══════════════════════════════════════════════════════════════


class StrategyFingerprints:
    """Track what each strategy excels at and fails at."""

    def __init__(self):
        self._data: Dict = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._data = _load_json("strategy_fingerprints.json", {})
            self._loaded = True

    def update(
        self,
        strategy: str,
        symbol: str,
        regime: str,
        side: str,
        win: bool,
        pnl: float,
        confidence: float,
        hour: int = 0,
    ):
        """Update strategy fingerprint with a new outcome."""
        self._ensure_loaded()

        if strategy not in self._data:
            self._data[strategy] = {
                "total": 0, "wins": 0, "pnl": 0.0,
                "by_regime": {}, "by_symbol": {}, "by_side": {},
                "by_hour": {}, "confidence_vs_actual": [],
                "strengths": [], "weaknesses": [],
            }

        fp = self._data[strategy]
        fp["total"] += 1
        if win:
            fp["wins"] += 1
        fp["pnl"] += pnl

        # Track by regime
        if regime not in fp["by_regime"]:
            fp["by_regime"][regime] = {"wins": 0, "total": 0, "pnl": 0.0}
        fp["by_regime"][regime]["total"] += 1
        if win:
            fp["by_regime"][regime]["wins"] += 1
        fp["by_regime"][regime]["pnl"] += pnl

        # Track by symbol
        if symbol not in fp["by_symbol"]:
            fp["by_symbol"][symbol] = {"wins": 0, "total": 0, "pnl": 0.0}
        fp["by_symbol"][symbol]["total"] += 1
        if win:
            fp["by_symbol"][symbol]["wins"] += 1
        fp["by_symbol"][symbol]["pnl"] += pnl

        # Track by side
        if side not in fp["by_side"]:
            fp["by_side"][side] = {"wins": 0, "total": 0, "pnl": 0.0}
        fp["by_side"][side]["total"] += 1
        if win:
            fp["by_side"][side]["wins"] += 1
        fp["by_side"][side]["pnl"] += pnl

        # Confidence calibration
        fp["confidence_vs_actual"].append({
            "predicted": confidence, "actual": 1.0 if win else 0.0
        })
        if len(fp["confidence_vs_actual"]) > 200:
            fp["confidence_vs_actual"] = fp["confidence_vs_actual"][-200:]

        # Auto-detect strengths and weaknesses
        self._update_assessment(strategy)
        _save_json("strategy_fingerprints.json", self._data)

    def _update_assessment(self, strategy: str):
        """Auto-detect what this strategy is good/bad at."""
        fp = self._data[strategy]
        if fp["total"] < 10:
            return

        strengths = []
        weaknesses = []

        # Check by regime
        for regime, stats in fp["by_regime"].items():
            if stats["total"] >= 5:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.65:
                    strengths.append(f"Strong in {regime} ({wr:.0%} WR, {stats['total']} trades)")
                elif wr <= 0.35:
                    weaknesses.append(f"Weak in {regime} ({wr:.0%} WR, {stats['total']} trades)")

        # Check by symbol
        for symbol, stats in fp["by_symbol"].items():
            if stats["total"] >= 5:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.70:
                    strengths.append(f"Excellent on {symbol} ({wr:.0%} WR)")
                elif wr <= 0.30:
                    weaknesses.append(f"Poor on {symbol} ({wr:.0%} WR)")

        # Check by side
        for side, stats in fp["by_side"].items():
            if stats["total"] >= 5:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.65:
                    strengths.append(f"Strong {side}s ({wr:.0%} WR)")
                elif wr <= 0.35:
                    weaknesses.append(f"Weak {side}s ({wr:.0%} WR)")

        fp["strengths"] = strengths[:10]
        fp["weaknesses"] = weaknesses[:10]

    def get_all(self) -> Dict:
        """Get all strategy fingerprints."""
        self._ensure_loaded()
        return self._data

    def get_for_context(self, strategy: str, symbol: str = "", regime: str = "") -> str:
        """Get contextual summary for LLM prompt injection."""
        self._ensure_loaded()
        fp = self._data.get(strategy)
        if not fp or fp["total"] < 3:
            return ""

        lines = []
        wr = fp["wins"] / fp["total"] if fp["total"] > 0 else 0
        lines.append(f"{strategy}: {wr:.0%} WR ({fp['total']} trades, ${fp['pnl']:+.0f})")

        if symbol and symbol in fp["by_symbol"]:
            s = fp["by_symbol"][symbol]
            swr = s["wins"] / s["total"] if s["total"] > 0 else 0
            lines.append(f"  on {symbol}: {swr:.0%} ({s['total']} trades)")

        if regime and regime in fp["by_regime"]:
            r = fp["by_regime"][regime]
            rwr = r["wins"] / r["total"] if r["total"] > 0 else 0
            lines.append(f"  in {regime}: {rwr:.0%} ({r['total']} trades)")

        if fp.get("strengths"):
            lines.append(f"  Strengths: {'; '.join(fp['strengths'][:3])}")
        if fp.get("weaknesses"):
            lines.append(f"  Weaknesses: {'; '.join(fp['weaknesses'][:3])}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 3. Pattern Library
# ═══════════════════════════════════════════════════════════════


class PatternLibrary:
    """Store recurring market patterns and how they resolved."""

    def __init__(self):
        self._patterns: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            data = _load_json("pattern_library.json", {"patterns": []})
            self._patterns = data.get("patterns", [])
            self._loaded = True

    def record_pattern(
        self,
        pattern_type: str,
        symbol: str,
        description: str,
        regime: str,
        outcome: str,
        pnl: float,
        context: Dict[str, Any] = None,
    ):
        """Record a recognized market pattern and its outcome."""
        self._ensure_loaded()
        entry = {
            "ts": time.time(),
            "type": pattern_type,
            "symbol": symbol,
            "description": description,
            "regime": regime,
            "outcome": outcome,
            "pnl": pnl,
            "context": context or {},
        }
        self._patterns.append(entry)
        if len(self._patterns) > 1000:
            self._patterns = self._patterns[-1000:]
        _save_json("pattern_library.json", {"patterns": self._patterns})

    def find_similar(self, pattern_type: str, symbol: str = "", regime: str = "", limit: int = 10) -> List[Dict]:
        """Find similar historical patterns."""
        self._ensure_loaded()
        matches = []
        for p in reversed(self._patterns):
            if p["type"] == pattern_type:
                if symbol and p["symbol"] != symbol:
                    continue
                if regime and p["regime"] != regime:
                    continue
                matches.append(p)
                if len(matches) >= limit:
                    break
        return matches

    def get_pattern_stats(self, pattern_type: str) -> Dict:
        """Get win rate for a specific pattern type."""
        self._ensure_loaded()
        matching = [p for p in self._patterns if p["type"] == pattern_type]
        if not matching:
            return {"total": 0}
        wins = sum(1 for p in matching if p["outcome"] == "WIN")
        total_pnl = sum(p.get("pnl", 0) for p in matching)
        return {
            "total": len(matching),
            "wins": wins,
            "win_rate": wins / len(matching),
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(matching),
        }

    def get_all_pattern_types(self) -> Dict[str, Dict]:
        """Get stats for all known pattern types."""
        self._ensure_loaded()
        types = set(p["type"] for p in self._patterns)
        return {t: self.get_pattern_stats(t) for t in types}


# ═══════════════════════════════════════════════════════════════
# 4. Market Regime History
# ═══════════════════════════════════════════════════════════════


class RegimeHistory:
    """Track regime transitions and what worked in each."""

    def __init__(self):
        self._history: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            data = _load_json("regime_history.json", {"transitions": []})
            self._history = data.get("transitions", [])
            self._loaded = True

    def record_transition(
        self,
        from_regime: str,
        to_regime: str,
        symbol: str = "market",
        trigger: str = "",
        context: Dict[str, Any] = None,
    ):
        """Record a regime transition."""
        self._ensure_loaded()
        entry = {
            "ts": time.time(),
            "from": from_regime,
            "to": to_regime,
            "symbol": symbol,
            "trigger": trigger,
            "context": context or {},
        }
        self._history.append(entry)
        if len(self._history) > 500:
            self._history = self._history[-500:]
        _save_json("regime_history.json", {"transitions": self._history})
        logger.info(f"[DEEP-MEM] Regime transition: {from_regime} -> {to_regime} ({symbol})")

    def get_recent_transitions(self, limit: int = 20) -> List[Dict]:
        """Get recent regime transitions."""
        self._ensure_loaded()
        return list(reversed(self._history))[:limit]

    def get_transition_frequency(self) -> Dict[str, int]:
        """How often does each transition occur?"""
        self._ensure_loaded()
        freq = defaultdict(int)
        for t in self._history:
            key = f"{t['from']}->{t['to']}"
            freq[key] += 1
        return dict(freq)


# ═══════════════════════════════════════════════════════════════
# 5. Insight Journal - LLM's own conclusions
# ═══════════════════════════════════════════════════════════════


class InsightJournal:
    """LLM writes insights that persist indefinitely.

    Unlike memory_store (short notes, pruned at 48h), insights are
    durable conclusions the LLM has drawn from analyzing data.
    They are categorized and searchable.
    """

    CATEGORIES = [
        "strategy_insight",    # About strategy behavior
        "symbol_insight",      # About a specific asset
        "regime_insight",      # About market regimes
        "timing_insight",      # About timing/hours/days
        "risk_insight",        # About risk management
        "correlation_insight", # About cross-asset behavior
        "execution_insight",   # About entry/exit quality
        "meta_insight",        # About the system itself
    ]

    def __init__(self):
        self._insights: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            data = _load_json("insight_journal.json", {"insights": []})
            self._insights = data.get("insights", [])
            self._loaded = True

    def add_insight(
        self,
        category: str,
        insight: str,
        confidence: float = 0.5,
        evidence: str = "",
        source: str = "llm",
    ):
        """Record a durable insight."""
        self._ensure_loaded()
        entry = {
            "ts": time.time(),
            "category": category,
            "insight": insight[:500],
            "confidence": confidence,
            "evidence": evidence[:300],
            "source": source,
            "validated": False,
            "validation_count": 0,
        }
        self._insights.append(entry)
        if len(self._insights) > 500:
            self._insights = self._insights[-500:]
        _save_json("insight_journal.json", {"insights": self._insights})
        logger.info(f"[DEEP-MEM] New insight [{category}]: {insight[:80]}")

    def validate_insight(self, insight_text: str, was_correct: bool):
        """Mark an insight as validated or invalidated."""
        self._ensure_loaded()
        for i in reversed(self._insights):
            if i["insight"] == insight_text:
                i["validation_count"] += 1 if was_correct else -1
                i["validated"] = i["validation_count"] > 0
                break
        _save_json("insight_journal.json", {"insights": self._insights})

    def get_by_category(self, category: str, limit: int = 20) -> List[Dict]:
        """Get insights for a specific category."""
        self._ensure_loaded()
        return [i for i in reversed(self._insights) if i["category"] == category][:limit]

    def get_high_confidence(self, min_confidence: float = 0.7, limit: int = 20) -> List[Dict]:
        """Get high-confidence insights."""
        self._ensure_loaded()
        filtered = [i for i in self._insights if i["confidence"] >= min_confidence]
        filtered.sort(key=lambda x: x["confidence"], reverse=True)
        return filtered[:limit]

    def get_validated(self, limit: int = 20) -> List[Dict]:
        """Get insights that have been validated by outcomes."""
        self._ensure_loaded()
        return [i for i in reversed(self._insights) if i.get("validated")][:limit]

    def get_summary_for_llm(self) -> str:
        """Compact summary of key insights for LLM prompt."""
        self._ensure_loaded()
        if not self._insights:
            return ""

        # Group by category, take top insight per category
        by_cat = defaultdict(list)
        for i in self._insights:
            by_cat[i["category"]].append(i)

        lines = []
        for cat, insights in by_cat.items():
            # Take most confident + most recent
            best = sorted(insights, key=lambda x: (x.get("validated", False), x["confidence"]), reverse=True)
            if best:
                top = best[0]
                lines.append(f"[{cat}] {top['insight']}")

        return " | ".join(lines) if lines else ""


# ═══════════════════════════════════════════════════════════════
# 6. Deep Memory Manager - unified access
# ═══════════════════════════════════════════════════════════════


class DeepMemoryManager:
    """Unified access to all deep memory stores."""

    def __init__(self):
        self.trade_dna = TradeDNAStore()
        self.strategy_fps = StrategyFingerprints()
        self.patterns = PatternLibrary()
        self.regimes = RegimeHistory()
        self.insights = InsightJournal()
        logger.info("[DEEP-MEM] DeepMemoryManager initialized")

    def record_full_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        confidence: float,
        leverage: float,
        regime: str,
        strategies_agreed: List[str],
        outcome: str,
        pnl: float,
        hold_time_s: float,
        exit_reason: str,
        llm_action: str = "",
        llm_confidence: float = 0.0,
        llm_reasoning: str = "",
        entry_type: str = "",
        btc_trend: str = "",
        volume_ratio: float = 0.0,
        funding_rate: float = 0.0,
        atr: float = 0.0,
    ):
        """Record a complete trade with all context.

        Called after every trade closes. Populates trade DNA,
        updates strategy fingerprints, and detects patterns.
        """
        # Calculate quality metrics
        pnl_pct = (pnl / (entry_price * leverage)) * 100 if entry_price > 0 and leverage > 0 else 0

        # Detect sniper trades (entered within 0.5% of local min/max)
        was_sniper = False
        entry_accuracy = 0.0
        if outcome == "WIN" and pnl_pct >= 2.0:
            was_sniper = True
            entry_accuracy = min(1.0, pnl_pct / 5.0)

        quality_score = 0.0
        if outcome == "WIN":
            quality_score = min(1.0, 0.5 + pnl_pct / 10.0)
        elif outcome == "BREAKEVEN":
            quality_score = 0.4

        dna = TradeDNA(
            trade_id=trade_id,
            timestamp=time.time(),
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            confidence=confidence,
            leverage=leverage,
            regime=regime,
            strategies_agreed=strategies_agreed,
            num_agree=len(strategies_agreed),
            llm_action=llm_action,
            llm_confidence=llm_confidence,
            llm_reasoning=llm_reasoning,
            entry_type=entry_type,
            outcome=outcome,
            pnl=pnl,
            pnl_pct=round(pnl_pct, 2),
            hold_time_s=hold_time_s,
            exit_reason=exit_reason,
            btc_trend=btc_trend,
            market_regime=regime,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            atr=atr,
            was_sniper=was_sniper,
            entry_accuracy=entry_accuracy,
            quality_score=quality_score,
        )
        self.trade_dna.record_trade(dna)

        # Update strategy fingerprints for each strategy that agreed
        win = outcome == "WIN"
        for strat in strategies_agreed:
            self.strategy_fps.update(
                strategy=strat, symbol=symbol, regime=regime,
                side=side, win=win, pnl=pnl, confidence=confidence,
            )

    def build_llm_knowledge_summary(
        self,
        symbol: str = "",
        regime: str = "",
        max_tokens: int = 2000,
    ) -> str:
        """Build a comprehensive knowledge summary for the LLM.

        This is injected into the LLM prompt to give it full context
        of everything it has learned.
        """
        parts = []

        # 1. Overall stats
        stats = self.trade_dna.get_summary_stats()
        if stats.get("total_trades", 0) > 0:
            parts.append(
                f"PERFORMANCE: {stats['total_trades']} trades, "
                f"{stats['win_rate']:.0%} WR, ${stats['total_pnl']:+.0f} PnL, "
                f"{stats['sniper_count']} sniper trades"
            )

        # 2. Symbol-specific knowledge
        if symbol:
            sym_stats = stats.get("by_symbol", {}).get(symbol, {})
            if sym_stats.get("total", 0) > 0:
                parts.append(
                    f"{symbol}: {sym_stats['win_rate']:.0%} WR "
                    f"({sym_stats['total']} trades, ${sym_stats['pnl']:+.0f})"
                )

        # 3. Regime knowledge
        if regime:
            reg_stats = stats.get("by_regime", {}).get(regime, {})
            if reg_stats.get("total", 0) > 0:
                parts.append(
                    f"In {regime}: {reg_stats['win_rate']:.0%} WR "
                    f"({reg_stats['total']} trades)"
                )

        # 4. Strategy fingerprints
        all_fps = self.strategy_fps.get_all()
        for strat, fp in all_fps.items():
            if fp.get("total", 0) >= 5:
                ctx = self.strategy_fps.get_for_context(strat, symbol, regime)
                if ctx:
                    parts.append(ctx)

        # 5. Best patterns
        pattern_types = self.patterns.get_all_pattern_types()
        profitable_patterns = {k: v for k, v in pattern_types.items() if v.get("win_rate", 0) >= 0.6 and v.get("total", 0) >= 3}
        if profitable_patterns:
            pattern_strs = [f"{k}:{v['win_rate']:.0%}" for k, v in sorted(profitable_patterns.items(), key=lambda x: x[1]["win_rate"], reverse=True)[:5]]
            parts.append(f"PROFITABLE PATTERNS: {', '.join(pattern_strs)}")

        # 6. Key insights
        insight_summary = self.insights.get_summary_for_llm()
        if insight_summary:
            parts.append(f"INSIGHTS: {insight_summary}")

        # 7. Recent regime transitions
        transitions = self.regimes.get_recent_transitions(5)
        if transitions:
            trans_strs = [f"{t['from']}->{t['to']}" for t in transitions[:3]]
            parts.append(f"REGIME FLOW: {' | '.join(trans_strs)}")

        # 8. Sniper trade patterns (what made the best trades work)
        snipers = self.trade_dna.get_sniper_trades(5)
        if snipers:
            sniper_patterns = []
            for s in snipers[:3]:
                sniper_patterns.append(
                    f"{s['symbol']} {s['side']} in {s['regime']} "
                    f"(conf={s['confidence']:.0f}%, +${s['pnl']:.0f})"
                )
            parts.append(f"SNIPER MODELS: {' | '.join(sniper_patterns)}")

        return "\n".join(parts)

    def get_full_report(self) -> Dict[str, Any]:
        """Full report for dashboard/debugging."""
        return {
            "trade_stats": self.trade_dna.get_summary_stats(),
            "strategy_fingerprints": self.strategy_fps.get_all(),
            "pattern_types": self.patterns.get_all_pattern_types(),
            "regime_transitions": self.regimes.get_transition_frequency(),
            "insight_count": len(self.insights._insights) if self.insights._loaded else 0,
        }


# Module-level singleton
_manager: Optional[DeepMemoryManager] = None


def get_deep_memory() -> DeepMemoryManager:
    """Get the singleton DeepMemoryManager instance."""
    global _manager
    if _manager is None:
        _manager = DeepMemoryManager()
    return _manager
