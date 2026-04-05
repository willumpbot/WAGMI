"""
Background thinking system for the LLM agent network.

Runs periodic rule-based analysis between signals. Zero API calls --
pure computation and pattern matching. Output feeds into LLM agents
as enriched context for better decisions.

Usage:
    thinker = BackgroundThinker(interval_seconds=300)
    if thinker.should_think():
        obs = thinker.think(market_data, positions, recent_trades, feedback_state)
    context = thinker.get_journal_for_agents(last_n=5)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.background_thinker")

PRIORITY_CRITICAL = 3  # Position thesis invalid, repeated pattern
PRIORITY_HIGH = 2      # Regime shift, key level approach
PRIORITY_NORMAL = 1    # Routine observation
PRIORITY_LOW = 0       # Minor note
_EXPIRY = {PRIORITY_CRITICAL: 120, PRIORITY_HIGH: 60, PRIORITY_NORMAL: 30, PRIORITY_LOW: 15}


def _gf(data: Dict, key: str) -> Optional[float]:
    """Safely extract float from dict."""
    v = data.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _trade_pnl(t) -> Optional[float]:
    """Extract PnL from trade dict or object."""
    keys = ("pnl", "realized_pnl", "pnl_pct", "profit")
    for k in keys:
        v = t.get(k) if isinstance(t, dict) else getattr(t, k, None)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _tf(t, field: str, default=""):
    """Extract string field from trade dict or object."""
    return str(t.get(field, default) if isinstance(t, dict) else getattr(t, field, default))


def _tff(t, field: str) -> Optional[float]:
    """Extract float field from trade dict or object."""
    v = t.get(field) if isinstance(t, dict) else getattr(t, field, None)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


class ThoughtEntry:
    """Single journal entry with priority and expiry."""
    __slots__ = ("text", "priority", "timestamp", "category")

    def __init__(self, text: str, priority: int = PRIORITY_NORMAL, category: str = "general"):
        self.text = text
        self.priority = priority
        self.timestamp = time.time()
        self.category = category

    def age_minutes(self) -> float:
        return (time.time() - self.timestamp) / 60

    def is_expired(self) -> bool:
        return self.age_minutes() > _EXPIRY.get(self.priority, 30)


class BackgroundThinker:
    """
    Lightweight background analysis engine. No LLM calls.
    Detects market changes, reviews position theses, scans for
    opportunities, identifies repeated mistakes. Writes compact
    observations to a thought journal consumed by the agent pipeline.
    """

    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self.last_think_time: float = 0
        self.thought_journal: List[ThoughtEntry] = []
        self.max_journal_size = 20
        self._prev_prices: Dict[str, float] = {}
        self._prev_regimes: Dict[str, str] = {}
        self._prev_funding: Dict[str, float] = {}
        self._prev_oi: Dict[str, float] = {}
        self._cycle_count = 0

    def should_think(self) -> bool:
        return time.time() - self.last_think_time > self.interval

    def think(self, market_data: Dict, positions: Dict,
              recent_trades: List, feedback_state: Dict) -> Dict:
        """Run one thinking cycle. Returns observations dict."""
        self.last_think_time = time.time()
        self._cycle_count += 1
        obs = {
            "market_changes": self._detect_market_changes(market_data),
            "position_reviews": self._review_positions(positions, market_data),
            "opportunities": self._scan_opportunities(market_data),
            "patterns": self._detect_patterns(recent_trades),
            "cycle": self._cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._update_journal(obs)
        self._store_state(market_data)
        logger.info(
            f"Think #{self._cycle_count}: {len(obs['market_changes'])} changes, "
            f"{len(obs['position_reviews'])} reviews, {len(obs['opportunities'])} opps, "
            f"{len(obs['patterns'])} patterns"
        )
        return obs

    def get_journal_for_agents(self, last_n: int = 5) -> str:
        """Recent observations formatted for agent context injection."""
        self._prune_journal()
        if not self.thought_journal:
            return ""
        entries = sorted(self.thought_journal,
                         key=lambda e: (e.priority, -e.age_minutes()), reverse=True)[:last_n]
        entries.sort(key=lambda e: e.timestamp)
        lines = ["BACKGROUND OBSERVATIONS (continuous monitoring):"]
        for e in entries:
            age = e.age_minutes()
            tag = "just now" if age < 1 else f"{int(age)}m ago" if age < 60 else f"{int(age/60)}h ago"
            lines.append(f"  [{tag}] {e.text}")
        return "\n".join(lines)

    # ── 1. Market State Changes ─────────────────────────────────

    def _detect_market_changes(self, md: Dict) -> List[str]:
        out: List[str] = []
        if not md:
            return out
        for sym, d in md.items():
            if not isinstance(d, dict):
                continue
            price = _gf(d, "price")
            if not price:
                continue
            prev = self._prev_prices.get(sym)

            # Price move
            if prev and prev > 0:
                pct = (price - prev) / prev * 100
                if abs(pct) >= 0.5:
                    out.append(f"{sym} {'UP' if pct>0 else 'DOWN'} {abs(pct):.1f}% "
                               f"(${prev:.2f}->${price:.2f})")

            # Regime shift
            regime = d.get("regime", "")
            prev_r = self._prev_regimes.get(sym, "")
            if regime and prev_r and regime != prev_r:
                out.append(f"{sym} regime shift: {prev_r} -> {regime}")

            # EMA20 cross
            ema = _gf(d, "ema20")
            if ema and prev:
                if prev > ema and price < ema:
                    out.append(f"{sym} broke BELOW EMA20 (${ema:.2f})")
                elif prev < ema and price > ema:
                    out.append(f"{sym} broke ABOVE EMA20 (${ema:.2f})")

            # Funding flip
            fr = _gf(d, "funding_rate")
            pfr = self._prev_funding.get(sym)
            if fr is not None and pfr is not None:
                if pfr >= 0 and fr < 0:
                    out.append(f"{sym} funding flipped NEGATIVE ({fr:.5f}) -- squeeze building")
                elif pfr <= 0 and fr > 0:
                    out.append(f"{sym} funding flipped POSITIVE ({fr:.5f}) -- contrarian SHORT edge")

            # OI jump
            oi = _gf(d, "oi") or _gf(d, "open_interest")
            poi = self._prev_oi.get(sym)
            if oi and poi and poi > 0:
                chg = (oi - poi) / poi * 100
                if abs(chg) >= 3:
                    out.append(f"{sym} OI {'jumped' if chg>0 else 'dropped'} {abs(chg):.1f}% "
                               f"-- {'new money entering' if chg>0 else 'positions closing'}")

            # Volume anomaly
            vol, avgvol = _gf(d, "volume"), _gf(d, "avg_volume")
            if vol and avgvol and avgvol > 0:
                r = vol / avgvol
                if r < 0.3:
                    out.append(f"{sym} volume dying ({r:.1f}x avg) -- squeeze/breakout incoming")
                elif r > 3.0:
                    out.append(f"{sym} volume spike ({r:.1f}x avg) -- institutional activity")
        return out

    # ── 2. Position Thesis Review ───────────────────────────────

    def _review_positions(self, positions: Dict, md: Dict) -> List[Dict]:
        reviews: List[Dict] = []
        if not positions:
            return reviews
        for sym, pos in positions.items():
            if not hasattr(pos, "side") or not hasattr(pos, "entry"):
                continue
            if getattr(pos, "state", "CLOSED") == "CLOSED":
                continue
            data = md.get(sym, {})
            price = _gf(data, "price") or getattr(pos, "entry", 0)
            entry = getattr(pos, "entry", 0)
            side = getattr(pos, "side", "").upper()
            sl = getattr(pos, "sl", 0)
            if not entry or not price:
                continue

            pnl_pct = ((price - entry) / entry * 100) if side == "LONG" \
                else ((entry - price) / entry * 100)
            concerns: List[str] = []

            # Stale thesis: held long, no movement
            opened_at = getattr(pos, "open_time", None)
            if opened_at:
                try:
                    if opened_at.tzinfo is None:
                        opened_at = opened_at.replace(tzinfo=timezone.utc)
                    hrs = (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600
                    if hrs > 6 and abs(pnl_pct) < 0.5:
                        concerns.append(f"Held {hrs:.0f}h with {pnl_pct:+.1f}% -- thesis may be stale")
                except (TypeError, AttributeError):
                    pass

            # Regime mismatch
            regime = data.get("regime", "")
            if side == "LONG" and regime in ("panic", "high_volatility"):
                concerns.append(f"LONG in {regime} regime -- thesis weakening")
            elif side == "SHORT" and regime == "trend":
                ema = _gf(data, "ema20")
                if ema and price > ema:
                    concerns.append("SHORT in uptrend (price > EMA20) -- counter-trend risk")

            # Near stop loss
            if sl and price:
                dist = ((price - sl) / price * 100) if side == "LONG" else ((sl - price) / price * 100)
                if 0 < dist < 0.5:
                    concerns.append(f"Only {dist:.2f}% from SL -- consider early exit")

            # Adverse funding
            fr = _gf(data, "funding_rate")
            if fr is not None:
                if (side == "LONG" and fr > 0.0001) or (side == "SHORT" and fr < -0.0001):
                    concerns.append(f"Paying {abs(fr)*24*365*100:.0f}% ann. funding -- bleeding")

            # Underwater
            if pnl_pct < -1.0:
                concerns.append(f"Underwater {pnl_pct:.1f}% -- thesis not confirmed")

            reviews.append({"symbol": sym, "pnl_pct": round(pnl_pct, 2), "concerns": concerns})
        return reviews

    # ── 3. Opportunity Scan ─────────────────────────────────────

    def _scan_opportunities(self, md: Dict) -> List[str]:
        opps: List[str] = []
        if not md:
            return opps
        for sym, d in md.items():
            if not isinstance(d, dict):
                continue
            price = _gf(d, "price")
            if not price:
                continue

            # Liquidation cluster proximity
            for liq_key, label in [("nearest_long_liq", "long"), ("nearest_short_liq", "short")]:
                liq = _gf(d, liq_key)
                if liq and price > 0:
                    dist = abs(price - liq) / price * 100
                    if dist < 3.0:
                        opps.append(f"{sym} near {label}-liq cluster ${liq:.2f} "
                                    f"({dist:.1f}% away) -- magnetic target")

            # Volume + volatility compression
            vol, avgvol = _gf(d, "volume"), _gf(d, "avg_volume")
            atr, avgatr = _gf(d, "atr"), _gf(d, "avg_atr")
            if vol and avgvol and avgvol > 0 and vol/avgvol < 0.4:
                if atr and avgatr and avgatr > 0 and atr/avgatr < 0.6:
                    opps.append(f"{sym} vol+ATR compression -- breakout setup forming")

            # Extreme funding = contrarian
            fr = _gf(d, "funding_rate")
            if fr is not None and abs(fr) > 0.0003:
                opps.append(f"{sym} extreme funding ({fr:.5f}) -- "
                            f"contrarian {'SHORT' if fr>0 else 'LONG'} building")
        return opps

    # ── 4. Pattern Detection ────────────────────────────────────

    def _detect_patterns(self, recent_trades: List) -> List[str]:
        pats: List[str] = []
        if not recent_trades or len(recent_trades) < 3:
            return pats
        trades = recent_trades[-10:]

        # Consecutive losses
        streak = 0
        for t in reversed(trades):
            p = _trade_pnl(t)
            if p is not None and p < 0:
                streak += 1
            else:
                break
        if streak >= 3:
            pats.append(f"{streak} consecutive losses -- review strategy, possible regime mismatch")

        # Same symbol+side losses
        combos: Dict[str, int] = {}
        for t in trades:
            if (_trade_pnl(t) or 0) < 0:
                combos[f"{_tf(t,'symbol','?')}_{_tf(t,'side','?')}"] = \
                    combos.get(f"{_tf(t,'symbol','?')}_{_tf(t,'side','?')}", 0) + 1
        for combo, n in combos.items():
            if n >= 3:
                s, side = combo.rsplit("_", 1)
                pats.append(f"{n}/{len(trades)} trades were {s} {side} losses "
                            f"-- STOP {s} {side}s in current regime")

        # Repeated stop-out levels
        sl_hits: Dict[str, List[float]] = {}
        for t in trades:
            outcome = _tf(t, "outcome", "")
            if "SL" in outcome.upper() or "STOP" in outcome.upper():
                slp = _tff(t, "sl")
                if slp:
                    sl_hits.setdefault(_tf(t, "symbol", "?"), []).append(slp)
        for s, levels in sl_hits.items():
            if len(levels) >= 2:
                avg = sum(levels) / len(levels)
                if avg > 0 and (max(levels) - min(levels)) / avg < 0.02:
                    pats.append(f"{s} stopped {len(levels)}x near ${avg:.2f} -- widen stops")
        return pats

    # ── Journal Management ──────────────────────────────────────

    def _update_journal(self, obs: Dict) -> None:
        add = self.thought_journal.append
        for c in obs.get("market_changes", []):
            pri = PRIORITY_HIGH if ("regime shift" in c.lower() or "broke" in c.lower()) else PRIORITY_NORMAL
            add(ThoughtEntry(c, pri, "market"))
        for r in obs.get("position_reviews", []):
            for c in r.get("concerns", []):
                add(ThoughtEntry(f"[{r.get('symbol','?')}] {c}", PRIORITY_CRITICAL, "position"))
        for o in obs.get("opportunities", []):
            pri = PRIORITY_HIGH if ("magnetic" in o or "extreme" in o) else PRIORITY_NORMAL
            add(ThoughtEntry(o, pri, "opportunity"))
        for p in obs.get("patterns", []):
            add(ThoughtEntry(p, PRIORITY_CRITICAL, "pattern"))
        self._prune_journal()

    def _prune_journal(self) -> None:
        self.thought_journal = [e for e in self.thought_journal if not e.is_expired()]
        if len(self.thought_journal) > self.max_journal_size:
            self.thought_journal.sort(key=lambda e: (e.priority, -e.age_minutes()))
            self.thought_journal = self.thought_journal[-self.max_journal_size:]

    def _store_state(self, md: Dict) -> None:
        for sym, d in md.items():
            if not isinstance(d, dict):
                continue
            p = _gf(d, "price")
            if p:
                self._prev_prices[sym] = p
            r = d.get("regime")
            if r:
                self._prev_regimes[sym] = r
            f = _gf(d, "funding_rate")
            if f is not None:
                self._prev_funding[sym] = f
            oi = _gf(d, "oi") or _gf(d, "open_interest")
            if oi:
                self._prev_oi[sym] = oi
