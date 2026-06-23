"""
Exit-Regret Engine: ADDITIVE, execution-safe exit counterfactual measurement.

For every full close recorded in data/logs/exit_closes.jsonl (stamped by
execution.position_manager._close_position — covers BOTH mechanical SL/TP/trailing
AND LLM force-closes), this engine asks:

    "Did the cut position RECOVER at +1h / +2h / +4h?"

It fetches historical close prices from a FREE source (CCXT primary, CoinGecko
fallback via data.fetcher.DataFetcher) and computes a signed `regret`:

    side_sign = +1 for LONG, -1 for SHORT
    regret_pct@h = side_sign * (price_at_h - exit_price) / exit_price * 100

  * regret > 0  => price moved in the position's favor AFTER we exited
                   (we cut a recovering trade — exit was too eager)
  * regret < 0  => price moved against the position after exit
                   (the exit dodged further adverse move — exit justified)

Results are partitioned by (symbol, side, regime, exit_type) so we can answer
"which exit_type on which symbol/regime systematically cuts winners early?".

THIS MODULE IS MEASUREMENT-ONLY. It NEVER imports PositionManager / ExitEngine /
order_executor and NEVER changes any exit or execution decision. It is safe to
run on a timer, from a script, or ad hoc.

Usage:
    from analytics.exit_regret import get_exit_regret_engine
    eng = get_exit_regret_engine()
    n = eng.resolve_pending()          # backfill prices + score matured closes
    print(eng.get_report())            # human-readable partitioned summary
    agg = eng.get_aggregates()         # dict for LLM-context / dashboards
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("bot.analytics.exit_regret")

_LOG_DIR = os.path.join("data", "logs")
_CLOSES_FILE = os.path.join(_LOG_DIR, "exit_closes.jsonl")
_SCORES_FILE = os.path.join(_LOG_DIR, "exit_regret_scores.jsonl")

# Horizons (hours) at which we measure recovery.
_HORIZONS_H = (1, 2, 4)
# A close is only resolvable once enough wall-clock time has passed that the
# +4h candle exists. Small slack added for candle close + fetch latency.
_MATURITY_SLACK_MIN = 15


class ExitRegretEngine:
    """Reads exit_closes.jsonl, backfills future prices, scores regret."""

    def __init__(
        self,
        closes_file: str = _CLOSES_FILE,
        scores_file: str = _SCORES_FILE,
        price_fetcher: Optional[Any] = None,
    ):
        self._closes_file = closes_file
        self._scores_file = scores_file
        self._lock = threading.Lock()
        self._fetcher = price_fetcher  # injectable for tests; lazily built otherwise
        os.makedirs(os.path.dirname(scores_file) or ".", exist_ok=True)

    # ------------------------------------------------------------------
    # Price source (free: CCXT primary, CoinGecko fallback)
    # ------------------------------------------------------------------
    def _get_fetcher(self):
        if self._fetcher is None:
            from data.fetcher import DataFetcher  # local import: avoid load-time deps
            self._fetcher = DataFetcher()
        return self._fetcher

    def _coin_id(self, symbol: str) -> str:
        """CoinGecko id for fallback fetch; safe default to lowercase symbol."""
        try:
            from trading_config import DEFAULT_SYMBOLS
            cfg = DEFAULT_SYMBOLS.get(symbol)
            if cfg is not None:
                return cfg.coingecko_id
        except Exception:
            pass
        return symbol.lower()

    def _price_at(self, symbol: str, target: datetime) -> Optional[float]:
        """Return the 1h-candle close at-or-before `target`, or None.

        Uses the 1h timeframe so +1h/+2h/+4h all resolve from one fetch. The
        fetcher returns a DataFrame with columns 'time' (UTC) and 'close'.
        """
        try:
            import pandas as pd
            df = self._get_fetcher().fetch_ohlcv(symbol, self._coin_id(symbol), "1h")
            if df is None or getattr(df, "empty", True) or "time" not in df.columns:
                return None
            times = pd.to_datetime(df["time"], utc=True)
            tgt = pd.Timestamp(target).tz_convert("UTC") if pd.Timestamp(target).tzinfo else pd.Timestamp(target, tz="UTC")
            mask = times <= tgt
            if not mask.any():
                return None
            idx = times[mask].index[-1]
            val = df.loc[idx, "close"]
            return float(val) if val and val > 0 else None
        except Exception as e:
            logger.debug("[EXIT-REGRET] price_at(%s,%s) failed: %s", symbol, target, e)
            return None

    # ------------------------------------------------------------------
    # IO helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_ts(ts: str) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat(ts)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _read_closes(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self._closes_file):
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with open(self._closes_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("[EXIT-REGRET] read closes failed: %s", e)
        return rows

    def _scored_ids(self) -> set:
        ids = set()
        if not os.path.exists(self._scores_file):
            return ids
        try:
            with open(self._scores_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ids.add(json.loads(line).get("decision_id"))
                    except Exception:
                        continue
        except Exception:
            pass
        return ids

    def _read_scores(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not os.path.exists(self._scores_file):
            return rows
        try:
            with open(self._scores_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        return rows

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------
    def _score_close(self, row: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
        """Compute the regret score for one close row, or None if not mature/usable."""
        decision_id = row.get("decision_id")
        ts = self._parse_ts(row.get("ts", ""))
        exit_price = row.get("exit_price")
        side = (row.get("side") or "").upper()
        if not decision_id or ts is None or not exit_price or exit_price <= 0:
            return None
        if side not in ("LONG", "SHORT"):
            return None

        # Maturity gate: need the +max-horizon candle to exist.
        max_h = max(_HORIZONS_H)
        if now < ts + timedelta(hours=max_h, minutes=_MATURITY_SLACK_MIN):
            return None

        side_sign = 1.0 if side == "LONG" else -1.0
        regrets: Dict[str, Optional[float]] = {}
        prices: Dict[str, Optional[float]] = {}
        for h in _HORIZONS_H:
            p = self._price_at(row["symbol"], ts + timedelta(hours=h))
            prices[f"price_{h}h"] = p
            if p is not None:
                regrets[f"regret_{h}h_pct"] = round(side_sign * (p - exit_price) / exit_price * 100.0, 4)
            else:
                regrets[f"regret_{h}h_pct"] = None

        # Need at least one resolved horizon to be useful.
        if all(v is None for v in regrets.values()):
            return None

        resolved = [v for v in regrets.values() if v is not None]
        recovered = any(v > 0.05 for v in resolved)  # >5bps favorable = recovered

        return {
            "decision_id": decision_id,
            "scored_at": now.isoformat(),
            "close_ts": row.get("ts"),
            "symbol": row.get("symbol"),
            "side": side,
            "regime": row.get("regime", "unknown") or "unknown",
            "exit_type": row.get("exit_type", "unknown"),
            "exit_price": exit_price,
            "entry": row.get("entry"),
            "pnl": row.get("pnl"),
            **prices,
            **regrets,
            "recovered": recovered,
        }

    def resolve_pending(self) -> int:
        """Score every mature, not-yet-scored close. Returns count newly scored."""
        now = datetime.now(timezone.utc)
        with self._lock:
            already = self._scored_ids()
            new_scores: List[Dict[str, Any]] = []
            for row in self._read_closes():
                did = row.get("decision_id")
                if not did or did in already:
                    continue
                score = self._score_close(row, now)
                if score is not None:
                    new_scores.append(score)
                    already.add(did)
            if new_scores:
                try:
                    with open(self._scores_file, "a") as f:
                        for s in new_scores:
                            f.write(json.dumps(s) + "\n")
                except Exception as e:
                    logger.warning("[EXIT-REGRET] write scores failed: %s", e)
                    return 0
        if new_scores:
            logger.info("[EXIT-REGRET] scored %d new closes", len(new_scores))
        return len(new_scores)

    # ------------------------------------------------------------------
    # Aggregation / reporting
    # ------------------------------------------------------------------
    def get_aggregates(self) -> Dict[str, Any]:
        """Aggregate scored regret by (symbol, side, regime, exit_type).

        Uses the +4h regret when available, else the longest resolved horizon.
        """
        scores = self._read_scores()
        buckets: Dict[Tuple[str, str, str, str], List[float]] = {}
        recov: Dict[Tuple[str, str, str, str], List[bool]] = {}
        for s in scores:
            key = (
                s.get("symbol", "?"), s.get("side", "?"),
                s.get("regime", "?"), s.get("exit_type", "?"),
            )
            r = None
            for h in sorted(_HORIZONS_H, reverse=True):
                v = s.get(f"regret_{h}h_pct")
                if v is not None:
                    r = v
                    break
            if r is None:
                continue
            buckets.setdefault(key, []).append(r)
            recov.setdefault(key, []).append(bool(s.get("recovered")))

        out: Dict[str, Any] = {"total_scored": len(scores), "partitions": []}
        for key, vals in sorted(buckets.items(), key=lambda kv: -sum(kv[1]) / max(len(kv[1]), 1)):
            sym, side, regime, etype = key
            n = len(vals)
            out["partitions"].append({
                "symbol": sym, "side": side, "regime": regime, "exit_type": etype,
                "n": n,
                "avg_regret_pct": round(sum(vals) / n, 4),
                "recover_rate": round(sum(recov[key]) / n, 3),
                "worst_regret_pct": round(max(vals), 4),
            })
        return out

    def get_report(self) -> str:
        agg = self.get_aggregates()
        lines = ["=" * 72, "  EXIT-REGRET REPORT (measurement-only)", "=" * 72,
                 f"  Total scored closes: {agg['total_scored']}",
                 "  (avg_regret_pct > 0 => exit cut a recovering position; < 0 => exit justified)",
                 ""]
        if not agg["partitions"]:
            lines.append("  No matured scored closes yet.")
        else:
            lines.append(f"  {'SYMBOL':<8}{'SIDE':<6}{'REGIME':<14}{'EXIT_TYPE':<18}{'N':>4}{'AVG_REGRET%':>13}{'RECOVER':>9}")
            lines.append("  " + "-" * 70)
            for p in agg["partitions"]:
                lines.append(
                    f"  {p['symbol']:<8}{p['side']:<6}{p['regime']:<14}{p['exit_type']:<18}"
                    f"{p['n']:>4}{p['avg_regret_pct']:>13.3f}{p['recover_rate']*100:>8.0f}%"
                )
        lines.append("=" * 72)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
_engine: Optional[ExitRegretEngine] = None
_engine_lock = threading.Lock()


def get_exit_regret_engine() -> ExitRegretEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = ExitRegretEngine()
    return _engine


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    eng = get_exit_regret_engine()
    print(f"Newly scored: {eng.resolve_pending()}")
    print(eng.get_report())
