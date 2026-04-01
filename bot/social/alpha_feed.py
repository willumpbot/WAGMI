"""
Alpha Feed - reads REAL bot data and formats it as algorithm-optimized tweets.

This is NOT AI-generated fluff. This reads:
- trades.csv (actual entries, exits, PnL)
- trade_ledger.csv (detailed performance)
- paper_trading_intel.jsonl (signals, rejections, regime data)
- analysis/performance.json (stats)

And formats it into copy-paste-ready tweets that:
1. Show REAL alpha (actual trades, actual signals, actual data)
2. Are structured for maximum X algorithm reach
3. Make your timeline look like a legit caller with receipts
"""
import csv
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.alpha_feed")

BOT_DATA = Path(__file__).parent.parent / "data"


class AlphaFeed:
    """Extract real alpha from bot data and format for X algorithm."""

    def __init__(self):
        pass

    # ──────────────────────────────────────────────
    # TRADE ALERTS - the money content
    # ──────────────────────────────────────────────

    def get_latest_trades(self, hours: int = 24) -> list[dict]:
        """Read recent trades from trades.csv."""
        trades_file = BOT_DATA / "trades.csv"
        if not trades_file.exists():
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        trades = []
        try:
            with open(trades_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = datetime.fromisoformat(row.get("timestamp", ""))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= cutoff:
                            trades.append(row)
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.error(f"Error reading trades: {e}")
        return trades

    def format_trade_entry(self, trade: dict) -> str:
        """Format a trade entry as a tweet. The CALL tweet."""
        symbol = trade.get("symbol", "???")
        side = trade.get("side", "???")
        entry = float(trade.get("entry", 0))
        confidence = float(trade.get("confidence", 0))
        leverage = float(trade.get("leverage", 1))

        # Parse entry reasons for extra intel
        reasons = {}
        try:
            reasons = json.loads(trade.get("entry_reasons", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass

        num_agree = reasons.get("num_agree", 0)
        ev = reasons.get("ev_per_dollar", 0)
        rr1 = reasons.get("rr1", 0)
        regime = reasons.get("regime", trade.get("regime", ""))
        strategies = reasons.get("strategies_agree", [])

        # Build the tweet - specific, confident, data-backed
        direction = "LONG" if side.upper() == "BUY" else "SHORT"

        lines = [f"${symbol} {direction} @ {entry:,.1f}"]

        details = []
        if confidence > 0:
            details.append(f"{confidence:.0f}% confidence")
        if leverage > 1:
            details.append(f"{leverage:.1f}x")
        if num_agree >= 2:
            details.append(f"{num_agree} strategies aligned")
        if details:
            lines.append(" | ".join(details))

        if ev > 0:
            lines.append(f"EV: +{ev:.2f} per dollar risked")
        if rr1 > 0:
            lines.append(f"R:R {rr1:.1f}")
        if regime:
            lines.append(f"Regime: {regime}")

        lines.append("9-agent consensus")

        return "\n".join(lines)

    def format_trade_exit(self, trade: dict) -> str:
        """Format a trade exit as a tweet. The RECEIPT tweet."""
        symbol = trade.get("symbol", "???")
        side = trade.get("side", "???")
        entry = float(trade.get("entry", 0))
        exit_price = float(trade.get("exit", 0))
        pnl = float(trade.get("pnl", 0))
        outcome = trade.get("outcome", "")
        leverage = float(trade.get("leverage", 1))
        confidence = float(trade.get("confidence", 0))

        direction = "LONG" if side.upper() == "BUY" else "SHORT"
        pnl_str = f"+${pnl:.2f}" if pnl > 0 else f"-${abs(pnl):.2f}"
        pct_move = abs(exit_price - entry) / entry * 100 if entry > 0 else 0

        # Calculate R multiple if we have the data
        reasons = {}
        try:
            reasons = json.loads(trade.get("entry_reasons", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass

        lines = [f"${symbol} {direction} closed"]
        lines.append(f"{pnl_str} ({pct_move:.1f}% move, {leverage:.0f}x)")

        if pnl > 0:
            lines.append(f"Entry: {entry:,.1f} -> Exit: {exit_price:,.1f}")
            if outcome:
                outcome_clean = outcome.replace("_", " ").title()
                lines.append(outcome_clean)
        else:
            lines.append(f"Stopped out. Part of the game.")

        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # SIGNAL INTELLIGENCE - what the bot sees
    # ──────────────────────────────────────────────

    def get_recent_intel(self, hours: int = 4, limit: int = 20) -> list[dict]:
        """Read recent intelligence from paper_trading_intel.jsonl."""
        intel_file = BOT_DATA / "paper_trading_intel.jsonl"
        if not intel_file.exists():
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events = []
        try:
            with open(intel_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        ts = event.get("timestamp", "")
                        if ts:
                            dt = datetime.fromisoformat(ts)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            if dt >= cutoff:
                                events.append(event)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Error reading intel: {e}")

        return events[-limit:]

    def format_price_snapshot(self, event: dict) -> str:
        """Format a price snapshot as a market overview tweet."""
        data = event.get("data", {})
        lines = ["Market scan"]
        for symbol, info in data.items():
            if not isinstance(info, dict):
                continue
            price = info.get("price", 0)
            chg = info.get("chg_24h", 0)
            rsi = info.get("rsi", 0)
            ema_cross = info.get("ema_cross", "")

            direction = "+" if chg > 0 else ""
            parts = [f"${symbol} {price:,.0f} ({direction}{chg:.1f}%)"]
            if rsi:
                parts.append(f"RSI {rsi:.0f}")
            if ema_cross:
                parts.append(ema_cross)
            lines.append(" | ".join(parts))

        return "\n".join(lines)

    def format_momentum_alert(self, event: dict) -> str:
        """Format a momentum state as a tweet."""
        data = event.get("data", {})
        symbol = data.get("symbol", "???")
        adx = data.get("adx", 0)
        rsi = data.get("rsi", 0)
        trend = data.get("trend", "")

        strength = "strong" if adx > 40 else "moderate" if adx > 25 else "weak"

        lines = [f"${symbol} momentum update"]
        lines.append(f"ADX {adx:.0f} ({strength}) | RSI {rsi:.0f} | {trend}")

        if rsi > 70:
            lines.append("Overextended. Watching for pullback entry.")
        elif rsi < 30:
            lines.append("Oversold territory. Watching for reversal.")
        elif adx > 40 and trend == "BULLISH":
            lines.append("Strong trend. Looking for continuation.")

        return "\n".join(lines)

    def format_signal_rejection(self, event: dict) -> str:
        """Format a rejected signal - shows the bot is disciplined."""
        data = event.get("data", {})
        symbol = data.get("symbol", "???")
        side = data.get("side", "???")
        ev = data.get("ev", 0)
        win_prob = data.get("win_prob", 0)
        rr = data.get("rr", 0)

        direction = "LONG" if side.upper() == "BUY" else "SHORT"

        lines = [f"${symbol} {direction} signal - REJECTED"]
        lines.append(f"Win prob: {win_prob*100:.0f}% | EV: {ev:.3f} | R:R {rr:.1f}")
        lines.append("Didn't pass the filter. Discipline > FOMO.")

        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # PERFORMANCE STATS - the receipts
    # ──────────────────────────────────────────────

    def get_performance(self) -> dict:
        """Read performance stats."""
        perf_file = BOT_DATA / "analysis" / "performance.json"
        if perf_file.exists():
            try:
                return json.loads(perf_file.read_text())
            except Exception:
                pass
        return {}

    def format_performance_recap(self, perf: Optional[dict] = None) -> str:
        """Format performance stats as a recap tweet."""
        perf = perf or self.get_performance()
        if not perf:
            return ""

        total = perf.get("total_trades", 0)
        wr = perf.get("win_rate_20", 0)
        pnl = perf.get("total_pnl", 0)
        avg_rr = perf.get("avg_rr", 0)
        tp1_rate = perf.get("tp1_success_rate", 0)

        pnl_str = f"+${pnl:.0f}" if pnl > 0 else f"-${abs(pnl):.0f}"

        lines = ["Bot performance update"]
        lines.append(f"{total} trades | {wr*100:.0f}% win rate | {pnl_str}")
        if avg_rr > 0:
            lines.append(f"Avg R: {avg_rr:.2f} | TP1 hit rate: {tp1_rate*100:.0f}%")

        # Best regime
        by_regime = perf.get("by_regime", {})
        if by_regime:
            best = max(by_regime.items(), key=lambda x: x[1].get("total_pnl", 0))
            if best[1].get("total_pnl", 0) > 0:
                lines.append(f"Best regime: {best[0]} ({best[1].get('win_rate', 0)*100:.0f}% WR)")

        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # ALGORITHM SCORE - rate any tweet before posting
    # ──────────────────────────────────────────────

    def algo_score(self, text: str) -> dict:
        """
        Score a tweet for X algorithm optimization BEFORE posting.
        Returns score and specific recommendations.

        Based on:
        - Bookmark potential (20x): does it have save-worthy data/insight?
        - Reply potential (27x): does it invite conversation?
        - Retweet potential (40x): is it share-worthy?
        - Penalty checks: links, hashtags, engagement bait
        """
        import re

        score = 50  # Base score
        notes = []

        char_count = len(text)
        line_count = text.count("\n") + 1
        has_numbers = bool(re.search(r'\d+', text))
        has_question = "?" in text
        has_link = bool(re.search(r'https?://', text))
        hashtag_count = len(re.findall(r'#\w+', text))
        cashtag_count = len(re.findall(r'\$[A-Z]+', text))
        has_engagement_bait = any(
            phrase in text.lower()
            for phrase in ["like if", "rt if", "retweet if", "like and retweet", "share if"]
        )

        # ── Length optimization ──
        if 100 <= char_count <= 280:
            score += 10
            notes.append("Good length")
        elif char_count < 50:
            score -= 10
            notes.append("Too short - add substance")
        elif char_count > 280:
            score -= 20
            notes.append("Over 280 chars! Must shorten.")

        # ── Numbers = credibility ──
        if has_numbers:
            score += 15
            notes.append("Has specific numbers (builds trust)")
        else:
            score -= 10
            notes.append("Add specific numbers - '12%' beats 'a lot'")

        # ── Question = replies (27x) ──
        if has_question:
            score += 15
            notes.append("Ends with question (drives replies, 27x)")
        else:
            notes.append("Consider adding a question to drive replies")

        # ── Line breaks = readability ──
        if line_count >= 3:
            score += 10
            notes.append("Good formatting with line breaks")
        elif line_count == 1 and char_count > 100:
            score -= 5
            notes.append("Add line breaks for readability")

        # ── Cashtags ──
        if cashtag_count > 0:
            score += 5
            notes.append(f"Has {cashtag_count} cashtag(s)")

        # ── PENALTIES ──
        if has_link:
            score -= 30
            notes.append("LINK DETECTED: -30-50% reach. Move link to self-reply!")

        if hashtag_count >= 3:
            score -= 20
            notes.append(f"TOO MANY HASHTAGS ({hashtag_count}): -40% reach. Use max 1.")
        elif hashtag_count >= 1:
            score -= 5
            notes.append("Hashtag present - prefer $CASHTAGS over #hashtags")

        if has_engagement_bait:
            score -= 25
            notes.append("ENGAGEMENT BAIT DETECTED: algorithm penalizes this")

        # ── AI detection ──
        ai_phrases = [
            "let's dive in", "buckle up", "here's the thing",
            "game-changer", "revolutionary", "in this thread",
            "not financial advice", "DYOR", "key takeaways",
            "without further ado", "the reality is",
        ]
        ai_found = [p for p in ai_phrases if p.lower() in text.lower()]
        if ai_found:
            score -= 15
            notes.append(f"AI TELLS FOUND: {', '.join(ai_found)}. Remove these.")

        score = max(0, min(100, score))

        rating = "EXCELLENT" if score >= 80 else "GOOD" if score >= 60 else "NEEDS WORK" if score >= 40 else "FIX BEFORE POSTING"

        return {
            "score": score,
            "rating": rating,
            "char_count": char_count,
            "notes": notes,
        }

    # ──────────────────────────────────────────────
    # DAILY ALPHA DIGEST - everything in one shot
    # ──────────────────────────────────────────────

    def generate_alpha_digest(self, hours: int = 24) -> dict:
        """
        Pull all available alpha from the bot and format as ready-to-post tweets.
        This is the REAL content - actual data, actual trades, actual signals.
        """
        digest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trade_tweets": [],
            "signal_tweets": [],
            "stats_tweet": None,
            "market_tweet": None,
        }

        # 1. Recent trades → entry/exit tweets
        trades = self.get_latest_trades(hours=hours)
        for trade in trades:
            outcome = trade.get("outcome", "")
            if outcome and outcome != "OPEN":
                tweet = self.format_trade_exit(trade)
                if tweet:
                    scored = self.algo_score(tweet)
                    digest["trade_tweets"].append({
                        "text": tweet,
                        "type": "exit_receipt",
                        "algo_score": scored["score"],
                        "algo_notes": scored["notes"],
                    })
            else:
                tweet = self.format_trade_entry(trade)
                if tweet:
                    scored = self.algo_score(tweet)
                    digest["trade_tweets"].append({
                        "text": tweet,
                        "type": "entry_call",
                        "algo_score": scored["score"],
                        "algo_notes": scored["notes"],
                    })

        # 2. Signal intel → market awareness tweets
        intel = self.get_recent_intel(hours=4)
        for event in intel:
            cat = event.get("category", "")
            tweet = None
            if cat == "price_snapshot":
                tweet = self.format_price_snapshot(event)
            elif cat == "momentum_state":
                tweet = self.format_momentum_alert(event)
            elif cat == "signal_rejection":
                tweet = self.format_signal_rejection(event)

            if tweet:
                scored = self.algo_score(tweet)
                digest["signal_tweets"].append({
                    "text": tweet,
                    "type": cat,
                    "algo_score": scored["score"],
                    "algo_notes": scored["notes"],
                })

        # 3. Performance recap
        perf = self.get_performance()
        if perf and perf.get("total_trades", 0) > 0:
            recap = self.format_performance_recap(perf)
            if recap:
                scored = self.algo_score(recap)
                digest["stats_tweet"] = {
                    "text": recap,
                    "type": "performance",
                    "algo_score": scored["score"],
                    "algo_notes": scored["notes"],
                }

        # 4. Market snapshot (latest)
        snapshots = [e for e in intel if e.get("category") == "price_snapshot"]
        if snapshots:
            latest = snapshots[-1]
            tweet = self.format_price_snapshot(latest)
            if tweet:
                scored = self.algo_score(tweet)
                digest["market_tweet"] = {
                    "text": tweet,
                    "type": "market_scan",
                    "algo_score": scored["score"],
                    "algo_notes": scored["notes"],
                }

        # Save digest
        out_dir = BOT_DATA / "social"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "alpha_digest.json").write_text(json.dumps(digest, indent=2, default=str))

        return digest
