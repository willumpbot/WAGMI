"""
Cross-Asset Correlation Boost — Adjusts signal win probability when
multiple symbols move in the same direction.

Evidence from paper trading session 2026-03-23:
When BTC, SOL, and HYPE all sell off together, SELL signals have higher
true win probability than the formula predicts. The EV formula treats each
symbol independently, ignoring correlated market-wide moves.

2026-07-15 LIVING VALUES fix: the 2026-03-23 evidence was SELL-only, but the
boost was applied direction-symmetrically (same 1.08/1.04 for BUY and SELL).
The bot's own ledger (paper_trades/trades_*.csv) shows LONG is a realized net
loser (n=99, avg net -$8.17/tr) while SHORT is a realized net winner (n=166,
avg net +$9.10/tr) — the frozen multipliers were inflating win_prob for the
losing side. Boost magnitudes are now computed live per side from closed
trades (see refresh_from_ledger()); a side only earns a boost once its own
data (n>=13) proves a positive edge. Under-sampled or net-losing sides get a
neutral 1.0 — never a hidden penalty, but never an unearned boost either.

This component tracks recent price direction across all symbols and provides
a win_prob multiplier boost when the signal direction aligns with broad
market momentum.

Wiring:
    # In ensemble.py, before EV calculation:
    corr_boost = self._correlation_boost.get_boost(symbol, side)
    win_prob = raw_win_prob * deflation * corr_boost
"""

import csv
import logging
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from core.close_taxonomy import is_close_action

logger = logging.getLogger("bot.feedback.correlation_boost")


class CrossAssetCorrelationBoost:
    """Detects correlated cross-asset moves and boosts aligned signals.

    Maintains a rolling price history and computes directional agreement
    across tracked symbols. When 75%+ of symbols move in the same direction
    as the signal, apply a confidence boost.
    """

    # Ledger 'side' values (LONG/SHORT) map to signal-side vocabulary (BUY/SELL).
    _SIDE_MAP = {"LONG": "BUY", "SHORT": "SELL"}
    # Synthetic/test-fixture prices that must never contaminate live stats.
    _TEST_PRICE_MARKERS = {100.0, 150.0, 50000.0}
    # A side needs at least this many closed trades before it can earn a boost.
    MIN_SAMPLES = 13
    # Boost is capped here regardless of how strong the realized edge is.
    MAX_BOOST = 1.10

    def __init__(
        self,
        symbols: list = None,
        lookback_minutes: int = 60,
        min_move_pct: float = 0.3,
        strong_boost: float = 1.08,
        moderate_boost: float = 1.04,
        ledger_dir: str = None,
        refresh_interval_s: float = 86400.0,
    ):
        self.symbols = symbols or ["BTC", "SOL", "HYPE"]
        self.lookback_minutes = lookback_minutes
        self.min_move_pct = min_move_pct
        # 2026-07-15: strong_boost/moderate_boost are now only the bootstrap
        # values used if the ledger cannot be read at all on first refresh
        # (e.g. missing directory). Once refresh_from_ledger() runs, actual
        # boosts come from self._side_boost, computed live per side, and
        # default to neutral 1.0 for any side without a proven edge — they
        # are NOT used as a per-side n<13 fallback (see refresh_from_ledger).
        self.strong_boost = strong_boost
        self.moderate_boost = moderate_boost

        # Rolling price history: {symbol: deque of (timestamp, price)}
        self._prices: Dict[str, deque] = {
            sym: deque(maxlen=500) for sym in self.symbols
        }

        # Ledger location for live boost computation.
        self.ledger_dir = Path(ledger_dir) if ledger_dir else (
            Path(__file__).resolve().parent.parent / "paper_trades"
        )
        self.refresh_interval_s = refresh_interval_s
        self._last_refresh_ts = 0.0

        # Live per-side boost multipliers. Neutral (1.0) until the ledger
        # proves an edge — a losing or under-sampled side is never boosted.
        self._side_boost: Dict[str, Dict[str, float]] = {
            "BUY": {"strong": 1.0, "moderate": 1.0},
            "SELL": {"strong": 1.0, "moderate": 1.0},
        }
        self._side_stats: Dict[str, Dict[str, float]] = {}

        logger.info(
            f"[CORR-BOOST] Initialized: {len(self.symbols)} symbols, "
            f"lookback={lookback_minutes}min, ledger_dir={self.ledger_dir}"
        )
        self.refresh_from_ledger()

    def update_price(self, symbol: str, price: float, timestamp: float = None) -> None:
        """Record a price observation."""
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=500)
        ts = timestamp or time.time()
        self._prices[symbol].append((ts, price))

    def update_prices(self, prices: Dict[str, float], timestamp: float = None) -> None:
        """Bulk update prices for all symbols."""
        ts = timestamp or time.time()
        for sym, price in prices.items():
            if price and price > 0:
                self.update_price(sym, price, ts)

    def _load_ledger_rows(self) -> List[Dict]:
        """Load closed-trade rows from paper_trades/trades_*.csv.

        Excludes test-fixture rows (TEST symbols, synthetic marker prices)
        and non-close actions. Returns dicts with side ('BUY'/'SELL') and
        net_pnl (pnl - fee) per closed trade.
        """
        rows: List[Dict] = []
        if not self.ledger_dir.exists():
            return rows

        for csv_path in sorted(self.ledger_dir.glob("trades_*.csv")):
            try:
                with open(csv_path, "r", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        symbol = (row.get("symbol") or "").strip()
                        if not symbol or "TEST" in symbol.upper():
                            continue

                        action = (row.get("action") or "").strip().upper()
                        # CLOSE_TAXONOMY_FIX: blocklist (anything that isn't
                        # OPEN) instead of a hardcoded close-action allowlist,
                        # which silently dropped legs closed for reasons never
                        # added to the tuple (e.g. TELEGRAM_CLOSE,
                        # LIQUIDATION_PROXIMITY, MFE_TAKE_PROFIT, ...).
                        if not is_close_action(action):
                            continue

                        raw_side = (row.get("side") or "").strip().upper()
                        side = self._SIDE_MAP.get(raw_side)
                        if side is None:
                            continue

                        try:
                            price = float(row.get("price") or 0)
                            pnl = float(row.get("pnl") or 0)
                            fee = float(row.get("fee") or 0)
                        except (TypeError, ValueError):
                            continue

                        if price in self._TEST_PRICE_MARKERS:
                            continue

                        rows.append({"symbol": symbol, "side": side, "net_pnl": pnl - fee})
            except Exception as e:
                logger.debug(f"[CORR-BOOST] skipping unreadable ledger file {csv_path}: {e}")
                continue

        return rows

    def refresh_from_ledger(self) -> None:
        """Recompute per-side boost multipliers from realized paper_trades closes.

        A side (BUY/SELL) only earns a boost once its own realized data
        (n >= MIN_SAMPLES closed trades) shows a positive average net PnL.
        The boost magnitude is the side's win-rate uplift over the overall
        win rate, clamped to [1.0, MAX_BOOST] — never a static snapshot.
        Under-sampled or net-losing sides get a neutral 1.0 (no boost, and
        never a penalty). Call on init and periodically (get_boost() also
        triggers this automatically every refresh_interval_s).
        """
        self._last_refresh_ts = time.time()

        try:
            rows = self._load_ledger_rows()
        except Exception as e:
            logger.warning(f"[CORR-BOOST] refresh_from_ledger failed: {e}")
            return

        if not rows:
            logger.info("[CORR-BOOST] refresh_from_ledger: no closed trades yet, boosts remain neutral")
            return

        total_n = len(rows)
        overall_wr = sum(1 for r in rows if r["net_pnl"] > 0) / total_n

        by_side: Dict[str, List[Dict]] = {"BUY": [], "SELL": []}
        for r in rows:
            by_side.setdefault(r["side"], []).append(r)

        new_boosts = {
            "BUY": {"strong": 1.0, "moderate": 1.0},
            "SELL": {"strong": 1.0, "moderate": 1.0},
        }
        stats: Dict[str, Dict[str, float]] = {}

        for side, side_rows in by_side.items():
            n = len(side_rows)
            if n == 0:
                continue
            wins = sum(1 for r in side_rows if r["net_pnl"] > 0)
            win_rate = wins / n
            avg_net_pnl = sum(r["net_pnl"] for r in side_rows) / n
            stats[side] = {"n": n, "win_rate": win_rate, "avg_net_pnl": avg_net_pnl}

            if n >= self.MIN_SAMPLES and avg_net_pnl > 0:
                strong = min(max(1.0 + max(0.0, win_rate - overall_wr), 1.0), self.MAX_BOOST)
                moderate = 1.0 + (strong - 1.0) / 2.0
                new_boosts[side] = {"strong": strong, "moderate": moderate}
            # else: n < MIN_SAMPLES or net-losing side -> stays neutral 1.0/1.0

        self._side_boost = new_boosts
        self._side_stats = stats
        logger.info(
            f"[CORR-BOOST] refresh_from_ledger: n={total_n} overall_WR={overall_wr:.2%} "
            f"stats={stats} -> boosts={self._side_boost}"
        )

    def get_boost(self, symbol: str, side: str) -> float:
        """Calculate win_prob boost based on cross-asset directional agreement.

        Args:
            symbol: The symbol being traded
            side: "BUY" or "SELL"

        Returns:
            Multiplier (1.0 = no boost, up to MAX_BOOST for strong agreement
            on a side with a proven live edge; always 1.0 for a side that
            hasn't earned one yet).
        """
        # Periodic live refresh (daily by default) so boosts track the
        # ledger instead of a one-time snapshot from init.
        if time.time() - self._last_refresh_ts > self.refresh_interval_s:
            self.refresh_from_ledger()

        now = time.time()
        cutoff = now - self.lookback_minutes * 60

        # Calculate direction for each symbol over lookback
        directions = {}
        for sym, history in self._prices.items():
            if len(history) < 2:
                continue

            # Find oldest price within lookback
            oldest_price = None
            for ts, price in history:
                if ts >= cutoff:
                    if oldest_price is None:
                        oldest_price = price
                    break
            if oldest_price is None and history:
                oldest_price = history[0][1]

            latest_price = history[-1][1] if history else None

            if oldest_price and latest_price and oldest_price > 0:
                change_pct = (latest_price - oldest_price) / oldest_price * 100
                if change_pct > self.min_move_pct:
                    directions[sym] = "UP"
                elif change_pct < -self.min_move_pct:
                    directions[sym] = "DOWN"
                else:
                    directions[sym] = "FLAT"

        if len(directions) < 2:
            return 1.0  # Not enough data

        # Count how many symbols agree with the signal direction
        expected_dir = "DOWN" if side == "SELL" else "UP"
        agreeing = sum(1 for d in directions.values() if d == expected_dir)
        total = len(directions)
        agreement_ratio = agreeing / total

        # agreement_ratio tiers (0.75/0.50) are slice keys for bucketing
        # strength, not guarantees of a boost — the actual multiplier comes
        # from the side's own live-computed edge (see refresh_from_ledger).
        side_key = (side or "").strip().upper()
        boosts = self._side_boost.get(side_key, {"strong": 1.0, "moderate": 1.0})

        if agreement_ratio >= 0.75:
            boost = boosts["strong"]
            logger.debug(
                f"[CORR-BOOST] {symbol} {side}: strong boost {boost:.4f} "
                f"({agreeing}/{total} symbols agree, live side stats={self._side_stats.get(side_key)})"
            )
            return boost
        elif agreement_ratio >= 0.50:
            boost = boosts["moderate"]
            logger.debug(
                f"[CORR-BOOST] {symbol} {side}: moderate boost {boost:.4f} "
                f"({agreeing}/{total} symbols agree, live side stats={self._side_stats.get(side_key)})"
            )
            return boost
        else:
            return 1.0

    def get_agreement_ratio(self, side: str) -> Optional[float]:
        """Return the current cross-asset agreement_ratio for a side, or None
        if there isn't enough price history yet.

        Exposed so callers can log agreement_ratio into the trade record at
        entry (e.g. via trade_logger.py) — once enough closed trades carry
        this field, a future version can condition boosts on the properly
        joined (side, agreement-tier) slice instead of side alone. Not yet
        wired into the entry-logging path (out of scope for this file).
        """
        now = time.time()
        cutoff = now - self.lookback_minutes * 60

        directions = {}
        for sym, history in self._prices.items():
            if len(history) < 2:
                continue
            oldest_price = None
            for ts, price in history:
                if ts >= cutoff:
                    if oldest_price is None:
                        oldest_price = price
                    break
            if oldest_price is None and history:
                oldest_price = history[0][1]
            latest_price = history[-1][1] if history else None
            if oldest_price and latest_price and oldest_price > 0:
                change_pct = (latest_price - oldest_price) / oldest_price * 100
                if change_pct > self.min_move_pct:
                    directions[sym] = "UP"
                elif change_pct < -self.min_move_pct:
                    directions[sym] = "DOWN"
                else:
                    directions[sym] = "FLAT"

        if len(directions) < 2:
            return None

        expected_dir = "DOWN" if side == "SELL" else "UP"
        agreeing = sum(1 for d in directions.values() if d == expected_dir)
        return agreeing / len(directions)

    def get_market_direction(self) -> Dict[str, str]:
        """Get current direction assessment for all symbols."""
        now = time.time()
        cutoff = now - self.lookback_minutes * 60
        result = {}

        for sym, history in self._prices.items():
            if len(history) < 2:
                result[sym] = "UNKNOWN"
                continue

            oldest_price = None
            for ts, price in history:
                if ts >= cutoff:
                    if oldest_price is None:
                        oldest_price = price
                    break
            if oldest_price is None and history:
                oldest_price = history[0][1]

            latest_price = history[-1][1] if history else None

            if oldest_price and latest_price and oldest_price > 0:
                change_pct = (latest_price - oldest_price) / oldest_price * 100
                if change_pct > self.min_move_pct:
                    result[sym] = f"UP ({change_pct:+.2f}%)"
                elif change_pct < -self.min_move_pct:
                    result[sym] = f"DOWN ({change_pct:+.2f}%)"
                else:
                    result[sym] = f"FLAT ({change_pct:+.2f}%)"
            else:
                result[sym] = "UNKNOWN"

        return result
