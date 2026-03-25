"""
Manual Sniper Signal Filter.

Evaluates bot-generated signals for manual scalp execution.
Two modes:
- AGGRESSIVE ($100 scaling): Only fires on absolute best signals.
  High leverage (10-25x), heavy sizing (5-10% risk), strict dedup.
  Goal: compound $100 → $1000+ with 1-2 sniper trades/day.
- STANDARD ($10k+): More signals, moderate leverage/sizing.

The math for aggressive mode on $100:
- SNIPER signal: 85%+ conf, 3 agree, HYPE BUY → 85% WR historically
- 25x leverage, 10% risk ($10), 2% stop width
- Win: +$10-15 per trade (10-15% account growth)
- Loss: -$10 per trade (10% drawdown, recoverable in 1 win)
- At 85% WR: EV = 0.85 * $12 - 0.15 * $10 = +$8.70/trade
- 1-2 trades/day → $100 → $200 in ~10 days

Never modifies the bot's signals or trading logic.
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List

from manual.config import ManualSniperConfig

logger = logging.getLogger("bot.manual.sniper")


@dataclass
class SniperSignal:
    """A filtered manual sniper signal ready for execution."""
    # Signal identity
    symbol: str
    side: str                   # BUY or SELL
    tier: str                   # STANDARD / PREMIUM / SNIPER

    # Entry/exit levels
    entry: float
    sl: float
    tp_scalp: float             # Quick scalp TP
    tp_swing: float             # Swing TP (hold longer)

    # Sizing
    leverage: float
    risk_pct: float             # % of equity risked
    risk_amount: float          # $ risked
    position_size_usd: float    # Total position value
    qty: float                  # Asset quantity
    margin_required: float      # Actual margin needed (position / leverage)

    # Expected outcomes
    pnl_scalp: float            # $ if scalp TP hit
    pnl_swing: float            # $ if swing TP hit
    loss_amount: float          # $ if SL hit
    rr_scalp: float
    rr_swing: float

    # Account context
    account_equity: float       # Current account size
    account_after_win: float    # Equity if scalp TP hit
    account_after_loss: float   # Equity if SL hit
    growth_pct: float           # % account growth on scalp win

    # Signal context
    confidence: float
    num_agree: int
    strategies: List[str]
    regime: str
    ev_per_dollar: float
    signal_context: str

    # Metadata
    timestamp: str
    daily_target_pct: float     # How much of daily target this covers
    hold_target_hours: str      # Suggested hold time

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ManualSniperFilter:
    """
    Filters bot signals for manual scalp execution.

    In aggressive mode ($100 account), only fires on the absolute best
    signals and sizes heavily. Strict dedup ensures you only get 1-3
    truly distinct, actionable alerts per day.
    """

    def __init__(self, config: Optional[ManualSniperConfig] = None):
        self.config = config or ManualSniperConfig()
        self._daily_signals: List[SniperSignal] = []
        self._daily_date: Optional[date] = None
        self._last_alert_ts: Dict[str, float] = {}
        # Dedup: track (symbol, side, conf_band) → timestamp
        self._dedup_cache: Dict[str, float] = {}
        # Running equity tracker for compound sizing
        self._running_equity: float = self.config.equity
        self._log_path = os.path.join("data", "manual", "sniper_signals.jsonl")
        self._rejection_log_path = os.path.join("data", "manual", "sniper_rejections.jsonl")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
        # Rejection stats (in-memory, for quick access)
        self._daily_rejections: Dict[str, int] = {}  # reason -> count

    def update_equity(self, new_equity: float) -> None:
        """Update running equity for compound sizing."""
        if new_equity > 0:
            self._running_equity = new_equity

    def evaluate(self, signal, equity: Optional[float] = None) -> Optional[SniperSignal]:
        """
        Evaluate a bot signal for manual sniper quality.

        Args:
            signal: strategies.base.Signal from ensemble
            equity: Override equity (otherwise uses running equity or config)

        Returns:
            SniperSignal if signal qualifies, None otherwise
        """
        if not self.config.enabled:
            return None

        # Use explicit equity if provided, otherwise running equity (compounds),
        # otherwise config default
        if equity is not None and not self.config.compound_sizing:
            acct_equity = equity
        else:
            acct_equity = self._running_equity if self.config.compound_sizing else self.config.equity

        # Guard: equity must be positive
        if acct_equity <= 0:
            logger.warning(f"[SNIPER] Invalid equity: ${acct_equity:.2f}, skipping")
            return None

        # Reset daily tracking
        today = date.today()
        if self._daily_date != today:
            self._daily_signals = []
            self._daily_date = today
            self._dedup_cache = {}  # Reset dedup daily

        # Reset daily rejection stats on new day
        if self._daily_date != today:
            self._daily_rejections = {}

        # Check daily signal limit
        if len(self._daily_signals) >= self.config.max_daily_signals:
            logger.debug("[SNIPER] Daily signal limit reached")
            self._log_rejection(signal, "daily_limit")
            return None

        # Extract metadata
        meta = getattr(signal, 'metadata', {}) or {}
        confidence = signal.confidence
        # Guard against NaN/None confidence
        if confidence is None or (isinstance(confidence, float) and math.isnan(confidence)):
            logger.debug("[SNIPER] NaN/None confidence, rejecting")
            return None
        num_agree = meta.get("num_agree", 1)
        strategies = meta.get("strategies_agree", [signal.strategy])
        if isinstance(strategies, str):
            strategies = [strategies]
        regime = meta.get("regime", "unknown")
        ev_per_dollar = meta.get("ev_per_dollar", 0)

        # ── Gate 1: SETUP FILTER (the real edge — from missed trade analysis) ──
        # Data proves: symbol+side IS the edge, not confidence.
        # HYPE BUY: 85% WR at ANY confidence. SOL SELL: 59% WR at ANY confidence.
        # Everything else is negative EV. Confidence adds nothing to prediction.
        # Additional filter: chop < 0.3 captures 90% of HYPE BUY edge (cleaner entries)
        setup_key = f"{signal.symbol}_{signal.side}"
        chop = meta.get("chop_score_smoothed", meta.get("chop_score", 0))
        # Guard against NaN chop — treat as unknown (pass through)
        if chop is None or (isinstance(chop, float) and math.isnan(chop)):
            chop = 0.0
        positive_ev_setups = {
            "HYPE_BUY": {"grade": "A+", "max_chop": 0.4},   # 85% WR, chop<0.3 is purest
            "SOL_SELL": {"grade": "B+", "max_chop": 0.5},    # 59% WR
        }

        # Expanded setups (paper-mode validation)
        # These are research-identified edges that need live validation
        if self.config.expanded_setups:
            positive_ev_setups.update({
                # BTC SHORT only at >=90% conf — 67% WR, PF 1.98
                # NEVER below 90%: 70-80% conf is a death trap (PF 0.31-0.79)
                "BTC_SELL": {"grade": "B+", "max_chop": 0.5, "min_confidence": 90},
                # BTC LONG only at 70-80% conf — 69% WR, PF 1.85
                # HARD CAP at 80%: above 85% it fails badly
                "BTC_BUY": {"grade": "B+", "max_chop": 0.5, "min_confidence": 70, "max_confidence": 80},
            })

        setup = positive_ev_setups.get(setup_key)
        if setup is not None:
            # Proven/expanded setup — filter on chop + optional confidence band
            max_chop = setup.get("max_chop", 0.5)
            if chop > max_chop:
                logger.debug(f"[SNIPER] {signal.symbol} {signal.side} rejected: chop {chop:.2f} > {max_chop}")
                self._log_rejection(signal, f"chop_too_high_{chop:.2f}")
                return None
            # Expanded setups may have confidence band requirements
            min_conf = setup.get("min_confidence")
            max_conf = setup.get("max_confidence")
            if min_conf is not None and confidence < min_conf:
                self._log_rejection(signal, f"setup_low_conf_{confidence:.0f}_need_{min_conf}")
                return None
            if max_conf is not None and confidence > max_conf:
                self._log_rejection(signal, f"setup_high_conf_{confidence:.0f}_max_{max_conf}")
                return None
        else:
            # Not a proven edge — apply confidence filter as discovery mechanism
            if confidence < self.config.min_confidence:
                self._log_rejection(signal, f"low_confidence_{confidence:.0f}")
                return None
            if num_agree < self.config.min_num_agree:
                self._log_rejection(signal, f"low_consensus_{num_agree}")
                return None

        # ── Gate 2: R:R floor (always check — prevents bad entries) ──
        risk = abs(signal.entry - signal.sl)
        if risk <= 0:
            self._log_rejection(signal, "zero_risk")
            return None
        reward1 = abs(signal.tp1 - signal.entry)
        rr = reward1 / risk if risk > 0 else 0
        if rr < self.config.min_rr:
            self._log_rejection(signal, f"low_rr_{rr:.2f}")
            return None

        # ── Gate 3: Regime filter (only for non-proven setups) ──
        regime_lower = regime.lower()
        if setup is None and regime_lower in [r.lower() for r in self.config.weak_regimes]:
            if confidence < 85:
                self._log_rejection(signal, f"weak_regime_{regime_lower}")
                return None

        # ── Gate 5: Dedup (symbol + side — one signal per symbol per window) ──
        now = time.time()
        # Include entry price rounded to prevent same-scan duplicates
        entry_rounded = round(signal.entry, 2)
        dedup_key = f"{signal.symbol}:{signal.side}:{entry_rounded}"
        last_dedup = self._dedup_cache.get(dedup_key, 0)
        if (now - last_dedup) < self.config.dedup_window_s:
            self._log_rejection(signal, "dedup")
            return None
        self._dedup_cache[dedup_key] = now

        # Also block any signal for this symbol within cooldown (broader than dedup)
        symbol_key = f"{signal.symbol}:any"
        last_symbol = self._dedup_cache.get(symbol_key, 0)
        if (now - last_symbol) < self.config.min_alert_gap_s:
            self._log_rejection(signal, "symbol_cooldown")
            return None
        self._dedup_cache[symbol_key] = now

        # ── Classify tier ──
        tier = self._classify_tier(confidence, num_agree, signal.symbol, regime_lower, signal.side)

        # ── In aggressive mode, skip STANDARD tier entirely ──
        if self.config.mode == "aggressive" and tier == "STANDARD":
            self._log_rejection(signal, "aggressive_standard_skip")
            return None

        # ── Dynamic leverage based on stop width + confidence ──
        # Tight stop = higher leverage (same $ risk, bigger position, bigger P&L)
        # Wide stop = lower leverage (keep risk manageable)
        stop_width = abs(signal.entry - signal.sl)
        stop_width_pct = stop_width / signal.entry if signal.entry > 0 else 0.01

        leverage = self._get_dynamic_leverage(tier, confidence, num_agree, stop_width_pct)

        # ── Risk sizing: target $20-50 P&L per winning trade ──
        # Work backwards from target P&L to find position size
        risk_pct = self._get_risk_pct(tier)
        risk_amount = acct_equity * risk_pct

        # Position size from risk: risk_amount / stop_width_pct
        position_size_usd = risk_amount / stop_width_pct if stop_width_pct > 0 else 0
        margin_required = position_size_usd / leverage if leverage > 0 else position_size_usd

        # ── Sanity check: margin can't exceed equity ──
        if margin_required > acct_equity * 0.95:
            # Scale down to fit within 95% of equity
            scale = (acct_equity * 0.95) / margin_required
            position_size_usd *= scale
            risk_amount *= scale
            margin_required = position_size_usd / leverage if leverage > 0 else position_size_usd

        qty = position_size_usd / signal.entry if signal.entry > 0 else 0

        # ── Calculate TPs ──
        # Scalp TP: 1.5x risk (quick capture, target $20-50 at leverage)
        # Swing TP: 3x risk (let it run for bigger win)
        scalp_target_pct = stop_width_pct * 1.5
        swing_target_pct = stop_width_pct * 3.0

        if signal.side == "BUY":
            tp_scalp = signal.entry * (1 + scalp_target_pct)
            tp_swing = signal.entry * (1 + swing_target_pct)
        else:
            tp_scalp = signal.entry * (1 - scalp_target_pct)
            tp_swing = signal.entry * (1 - swing_target_pct)

        # Use bot's TP1 as swing target if it's better
        bot_tp1_dist = abs(signal.tp1 - signal.entry)
        manual_swing_dist = abs(tp_swing - signal.entry)
        if bot_tp1_dist > manual_swing_dist:
            tp_swing = signal.tp1

        # ── Calculate expected P&L ──
        pnl_scalp = position_size_usd * scalp_target_pct
        pnl_swing = position_size_usd * swing_target_pct
        loss_amount = risk_amount

        rr_scalp = 1.5  # By construction
        rr_swing = (swing_target_pct / stop_width_pct) if stop_width_pct > 0 else 0

        # ── Account growth projection ──
        account_after_win = acct_equity + pnl_scalp
        account_after_loss = acct_equity - loss_amount
        growth_pct = (pnl_scalp / acct_equity * 100) if acct_equity > 0 else 0

        # Daily target coverage
        daily_target_pct = (pnl_scalp / self.config.daily_target * 100) if self.config.daily_target > 0 else 0

        # Hold time suggestion
        if tier == "SNIPER":
            hold_target = "1-4h (scalp)"
        elif tier == "PREMIUM":
            hold_target = "2-8h (swing)"
        else:
            hold_target = "4-12h (swing)"

        sniper = SniperSignal(
            symbol=signal.symbol,
            side=signal.side,
            tier=tier,
            entry=signal.entry,
            sl=signal.sl,
            tp_scalp=round(tp_scalp, 6),
            tp_swing=round(tp_swing, 6),
            leverage=leverage,
            risk_pct=risk_pct,
            risk_amount=round(risk_amount, 2),
            position_size_usd=round(position_size_usd, 2),
            qty=round(qty, 6),
            margin_required=round(margin_required, 2),
            pnl_scalp=round(pnl_scalp, 2),
            pnl_swing=round(pnl_swing, 2),
            loss_amount=round(loss_amount, 2),
            rr_scalp=round(rr_scalp, 2),
            rr_swing=round(rr_swing, 2),
            account_equity=round(acct_equity, 2),
            account_after_win=round(account_after_win, 2),
            account_after_loss=round(account_after_loss, 2),
            growth_pct=round(growth_pct, 1),
            confidence=confidence,
            num_agree=num_agree,
            strategies=strategies,
            regime=regime,
            ev_per_dollar=ev_per_dollar,
            signal_context=getattr(signal, 'signal_context', '') or '',
            timestamp=datetime.now(timezone.utc).isoformat(),
            daily_target_pct=round(daily_target_pct, 1),
            hold_target_hours=hold_target,
        )

        # Track
        self._daily_signals.append(sniper)
        self._last_alert_ts[signal.symbol] = now
        self._log_signal(sniper)

        logger.info(
            f"[SNIPER] {tier} | {signal.symbol} {signal.side} | "
            f"conf={confidence:.0f}% agree={num_agree} lev={leverage:.0f}x | "
            f"acct=${acct_equity:.0f} risk=${risk_amount:.2f} win=+${pnl_scalp:.2f} | "
            f"growth={growth_pct:.1f}%"
        )

        return sniper

    def _classify_tier(
        self, confidence: float, num_agree: int, symbol: str, regime: str,
        side: str = ""
    ) -> str:
        """Classify signal into STANDARD / PREMIUM / SNIPER tier.

        Setup-first: proven edges get automatic tier upgrades because
        the edge is the setup itself, not the confidence score.
        Data: HYPE BUY=85% WR, SOL SELL=59% WR at ANY confidence.
        """
        # Proven A+ setups — auto-promote
        if symbol == "HYPE" and side == "BUY":
            if num_agree >= 3 or confidence >= 80:
                return "SNIPER"
            return "PREMIUM"  # 85% WR even at low confidence

        if symbol == "SOL" and side == "SELL":
            if confidence >= 80 or num_agree >= 3:
                return "SNIPER"
            return "PREMIUM"  # 59% WR is still tradeable

        # Expanded setups — PREMIUM tier (lower edge, need validation)
        if self.config.expanded_setups:
            if symbol == "BTC" and side == "SELL" and confidence >= 90 and num_agree >= 3:
                return "PREMIUM"  # BTC SHORT >=90% — 67% WR, PF 1.98
            if symbol == "BTC" and side == "BUY" and 70 <= confidence <= 80 and num_agree >= 3:
                return "PREMIUM"  # BTC LONG 70-80% — 69% WR, PF 1.85

        # Everything else: confidence-based (discovery mode)
        if (confidence >= 85 and num_agree >= 3) or \
           (confidence >= 90 and num_agree >= 2):
            return "SNIPER"

        if confidence >= self.config.premium_min_confidence and num_agree >= 2:
            return "PREMIUM"

        return "STANDARD"

    def _get_dynamic_leverage(
        self, tier: str, confidence: float, num_agree: int, stop_width_pct: float
    ) -> float:
        """
        Dynamic leverage based on stop width + confidence + tier.

        The sweet spot: tighter stops allow higher leverage (same $ risk, bigger
        position). Wide stops force lower leverage to keep risk manageable.

        Stop width ranges we see:
        - Tight: 0.5-1.5% (scalp setups) → higher leverage
        - Medium: 1.5-3.0% (swing setups) → moderate leverage
        - Wide: 3.0%+ (trend setups) → lower leverage
        """
        c = self.config

        # Base leverage from tier + confidence
        if confidence >= 90 and num_agree >= 3:
            base_lev = c.leverage_tier_5   # 25x
        elif tier == "SNIPER":
            base_lev = c.leverage_tier_4   # 25x
        elif tier == "PREMIUM" and confidence >= 85:
            base_lev = c.leverage_tier_3   # 20x
        elif tier == "PREMIUM":
            base_lev = c.leverage_tier_2   # 15x
        else:
            base_lev = c.leverage_tier_1   # 10x

        # Stop width adjustment: tighter stop → leverage boost, wider → cut
        if stop_width_pct <= 0.01:  # <= 1% stop
            stop_mult = 1.25  # Boost 25% — tight stop = precise entry
        elif stop_width_pct <= 0.015:  # 1-1.5% stop
            stop_mult = 1.1   # Slight boost
        elif stop_width_pct <= 0.025:  # 1.5-2.5% stop
            stop_mult = 1.0   # Neutral
        elif stop_width_pct <= 0.035:  # 2.5-3.5% stop
            stop_mult = 0.8   # Cut 20%
        else:  # > 3.5% stop
            stop_mult = 0.6   # Cut 40% — wide stop needs less leverage

        adjusted = base_lev * stop_mult
        return min(round(adjusted, 1), c.max_leverage)

    def _get_leverage(self, tier: str, confidence: float, num_agree: int) -> float:
        """Fallback: fixed leverage from tier + confidence (used if stop width unknown)."""
        return self._get_dynamic_leverage(tier, confidence, num_agree, 0.02)

    def _get_risk_pct(self, tier: str) -> float:
        """Map tier → risk percentage of account."""
        if tier == "SNIPER":
            return self.config.risk_pct_sniper
        elif tier == "PREMIUM":
            return self.config.risk_pct_premium
        return self.config.risk_pct_standard

    def _log_signal(self, sniper: SniperSignal) -> None:
        """Append signal to JSONL log with flush for durability."""
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(sniper.to_dict()) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.warning(f"[SNIPER] Failed to log signal: {e}")

    def _log_rejection(self, signal, reason: str) -> None:
        """Log a filter rejection for analysis. Lightweight — no fsync."""
        self._daily_rejections[reason] = self._daily_rejections.get(reason, 0) + 1
        try:
            meta = getattr(signal, 'metadata', {}) or {}
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": getattr(signal, 'symbol', '?'),
                "side": getattr(signal, 'side', '?'),
                "confidence": getattr(signal, 'confidence', 0),
                "reason": reason,
                "num_agree": meta.get("num_agree", 0),
                "regime": meta.get("regime", "unknown"),
                "chop": meta.get("chop_score_smoothed", meta.get("chop_score", 0)),
            }
            with open(self._rejection_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Rejection logging is best-effort

    def get_rejection_stats(self) -> Dict[str, int]:
        """Get today's rejection counts by reason."""
        return dict(self._daily_rejections)

    def get_daily_summary(self) -> Dict[str, Any]:
        """Get today's manual signal summary."""
        signals = self._daily_signals
        total_potential_scalp = sum(s.pnl_scalp for s in signals)
        total_potential_swing = sum(s.pnl_swing for s in signals)
        total_risk = sum(s.risk_amount for s in signals)

        return {
            "date": str(self._daily_date or date.today()),
            "mode": self.config.mode,
            "account_equity": self._running_equity,
            "signals_sent": len(signals),
            "max_signals": self.config.max_daily_signals,
            "total_potential_scalp": round(total_potential_scalp, 2),
            "total_potential_swing": round(total_potential_swing, 2),
            "total_risk": round(total_risk, 2),
            "daily_target": self.config.daily_target,
            "target_coverage_scalp_pct": round(
                total_potential_scalp / self.config.daily_target * 100, 1
            ) if self.config.daily_target > 0 else 0,
            "by_tier": {
                "SNIPER": len([s for s in signals if s.tier == "SNIPER"]),
                "PREMIUM": len([s for s in signals if s.tier == "PREMIUM"]),
                "STANDARD": len([s for s in signals if s.tier == "STANDARD"]),
            },
            "rejections": dict(self._daily_rejections),
            "total_rejections": sum(self._daily_rejections.values()),
            "signals": [s.to_dict() for s in signals],
        }
