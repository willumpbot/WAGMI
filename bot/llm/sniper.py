"""
LLM Sniper Engine: evaluates single-strategy signals rejected by ensemble.

When the ensemble needs MIN_VOTES=2+ strategies to agree and only 1 fires,
the rejected signal is routed here. The LLM evaluates whether this is a
high-conviction sniper entry worth queuing for manual review.

Sniper characteristics vs normal trades:
- Tighter SL (0.5x ATR vs normal 1-2x) — sniper precision
- Higher leverage (5-12x based on LLM confidence) — capture the move
- Conservative size fraction (0.5x) — tight stop controls dollar risk
- Manual approval required — build track record before auto-execution

Lifecycle:
  1. Ensemble rejects single-strategy signal (insufficient_votes)
  2. Sniper callback fires (non-blocking, background thread)
  3. LLM evaluates: proceed or skip
  4. If proceed + confidence >= 0.65: SniperProposal saved to sniper_queue
  5. Dashboard shows pending proposals for manual review
  6. Operator approves/rejects via UI

Enable: LLM_SNIPER_ENABLED=true (requires ANTHROPIC_API_KEY)
Model override: LLM_SNIPER_MODEL=claude-haiku-4-5-20251001 (default)
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger("bot.llm.sniper")

# ── Tunable constants ──────────────────────────────────────────────────────
# Leverage tiers by LLM confidence: (min_confidence, leverage_multiple)
_LEVERAGE_TIERS = [
    (0.85, 12.0),  # very high conviction → 12x
    (0.75, 8.0),   # high conviction     → 8x
    (0.65, 5.0),   # moderate conviction → 5x
]
_MIN_CONFIDENCE = 0.65          # LLM must be at least this confident
_SL_ATR_MULT = 0.5              # tight stop: 0.5x ATR (vs normal 1-2x)
_TP1_R = 1.5                    # TP1 at 1.5R from tight stop
_TP2_R = 3.0                    # TP2 at 3.0R from tight stop
_SIZE_FRACTION = 0.5            # 50% of normal position size
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


# ── Data types ─────────────────────────────────────────────────────────────

@dataclass
class SniperProposal:
    """A proposed sniper trade waiting for manual approval."""
    id: str
    symbol: str
    side: str           # BUY or SELL
    entry: float
    sl: float           # tight stop (0.5x ATR from entry)
    tp1: float          # 1.5R target
    tp2: float          # 3.0R target
    atr: float
    leverage: float     # aggressive leverage (5-12x based on LLM conf)
    confidence: float   # LLM confidence 0.0-1.0
    strategy_source: str        # which 1 strategy triggered this
    llm_regime: str             # LLM's regime classification
    llm_reasoning: str          # brief 1-sentence thesis
    created_at: str             # ISO timestamp
    status: str = "pending"     # pending / approved / rejected / executed
    size_fraction: float = _SIZE_FRACTION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "entry": self.entry,
            "sl": self.sl,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "atr": self.atr,
            "leverage": self.leverage,
            "confidence": self.confidence,
            "strategy_source": self.strategy_source,
            "llm_regime": self.llm_regime,
            "llm_reasoning": self.llm_reasoning,
            "created_at": self.created_at,
            "status": self.status,
            "size_fraction": self.size_fraction,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

def _sniper_enabled() -> bool:
    return os.getenv("LLM_SNIPER_ENABLED", "").lower() in ("1", "true", "yes")


def _get_leverage(confidence: float, max_leverage: float = 25.0) -> float:
    """Map LLM confidence → sniper leverage tier."""
    for threshold, lev in _LEVERAGE_TIERS:
        if confidence >= threshold:
            return min(lev, max_leverage)
    return min(5.0, max_leverage)


def _build_prompt(signal) -> str:
    """Build a focused sniper evaluation prompt for the LLM."""
    return (
        f"Evaluate this single-strategy crypto signal for a sniper entry.\n\n"
        f"Strategy: {signal.strategy}\n"
        f"Symbol: {signal.symbol}\n"
        f"Direction: {signal.side}\n"
        f"Confidence: {signal.confidence:.1f}%\n"
        f"Entry: {signal.entry}\n"
        f"Strategy SL: {signal.sl}\n"
        f"ATR: {signal.atr}\n"
        f"Context: {signal.signal_context or 'none'}\n\n"
        f"Return JSON only:\n"
        f'{{"action":"proceed" or "skip", '
        f'"confidence":0.0-1.0, '
        f'"regime":"trend|range|panic|high_volatility|unknown", '
        f'"reasoning":"brief 1-sentence thesis"}}\n\n'
        f'Only return "proceed" if you have strong conviction this move will follow through. '
        f'This is a single-strategy signal (normally needs 2+), so be selective.'
    )


# ── Engine ─────────────────────────────────────────────────────────────────

class LLMSniperEngine:
    """
    Evaluates ensemble-rejected single-strategy signals via LLM.

    Non-blocking: all LLM calls run in daemon background threads so the
    main scan loop is never delayed. Per-symbol deduplication prevents
    queuing the same symbol twice while an evaluation is in progress.
    """

    def __init__(self, max_leverage: float = 25.0):
        self.max_leverage = max_leverage
        self._lock = threading.Lock()
        self._in_flight: set = set()  # symbols with active evaluations

    # ── Public API ─────────────────────────────────────────────────────────

    def evaluate_candidate(self, signal, symbol: str) -> None:
        """
        Non-blocking entry point called from ensemble rejection hook.

        Args:
            signal: The single Signal object that triggered (strategies.base.Signal)
            symbol: Trading pair string (e.g. "BTC")
        """
        if not _sniper_enabled():
            return

        # Deduplicate: only one evaluation per symbol at a time
        with self._lock:
            if symbol in self._in_flight:
                logger.debug(f"[SNIPER] {symbol} evaluation already in flight — skipping")
                return
            self._in_flight.add(symbol)

        threading.Thread(
            target=self._evaluate_sync,
            args=(signal, symbol),
            daemon=True,
            name=f"sniper-{symbol}",
        ).start()

    # ── Internal ───────────────────────────────────────────────────────────

    def _evaluate_sync(self, signal, symbol: str) -> None:
        try:
            self._do_evaluate(signal, symbol)
        except Exception as e:
            logger.warning(f"[SNIPER] Unhandled error evaluating {symbol}: {e}", exc_info=True)
        finally:
            with self._lock:
                self._in_flight.discard(symbol)

    def _do_evaluate(self, signal, symbol: str) -> None:
        """Call LLM, parse response, and persist proposal if approved."""
        try:
            from llm.client import call_llm
        except ImportError:
            logger.warning("[SNIPER] llm.client not available — skipping evaluation")
            return

        system_prompt = (
            "You are a sniper entry specialist for crypto futures trading. "
            "Your job is to identify single-strategy signals that have strong directional conviction. "
            "This signal was rejected by the ensemble because only 1 of 2+ required strategies agreed. "
            "Evaluate whether the move is likely to follow through anyway. "
            "Be highly selective — false snipers lose money. "
            "Return valid JSON only, no other text."
        )

        model = os.getenv("LLM_SNIPER_MODEL", _DEFAULT_MODEL)

        raw, _usage = call_llm(
            system_prompt=system_prompt,
            snapshot_json=_build_prompt(signal),
            model=model,
            max_tokens=256,
            max_retries=1,
            timeout=15.0,
        )

        if not raw:
            logger.debug(f"[SNIPER] No LLM response for {symbol}")
            return

        # Parse JSON — strip markdown fences if model added them
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                clean = parts[1] if len(parts) > 1 else clean
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[SNIPER] JSON parse failed for {symbol}: {e} | raw={raw[:120]}")
            return

        action = str(result.get("action", "skip")).lower()
        confidence = float(result.get("confidence", 0.0))
        regime = str(result.get("regime", "unknown"))
        reasoning = str(result.get("reasoning", ""))

        if action != "proceed" or confidence < _MIN_CONFIDENCE:
            logger.info(
                f"[SNIPER] {symbol} {signal.side} → LLM skip "
                f"(action={action}, conf={confidence:.2f})"
            )
            return

        proposal = self._build_proposal(signal, confidence, regime, reasoning)
        if proposal is None:
            return

        # Persist
        try:
            from data import db as _db
            _db.insert_sniper_proposal(proposal.to_dict())
            logger.info(
                f"[SNIPER] ✓ {symbol} {signal.side} QUEUED — "
                f"conf={confidence:.2f} lev={proposal.leverage:.0f}x "
                f"entry={proposal.entry:.4f} sl={proposal.sl:.4f} tp1={proposal.tp1:.4f} "
                f"| {reasoning}"
            )
        except Exception as e:
            logger.warning(f"[SNIPER] Failed to persist proposal for {symbol}: {e}")

    def _build_proposal(
        self,
        signal,
        confidence: float,
        regime: str,
        reasoning: str,
    ) -> Optional[SniperProposal]:
        """Build a SniperProposal with tight SL/TP from the strategy signal."""
        atr = getattr(signal, "atr", 0.0)
        if atr <= 0:
            # Fallback: estimate ATR from original stop width
            atr = abs(signal.entry - signal.sl)
        if atr <= 0:
            logger.warning(f"[SNIPER] Cannot compute SL — ATR=0 for {signal.symbol}")
            return None

        entry = signal.entry
        sl_dist = _SL_ATR_MULT * atr   # tight stop distance

        if signal.side == "BUY":
            sl = entry - sl_dist
            tp1 = entry + sl_dist * _TP1_R
            tp2 = entry + sl_dist * _TP2_R
        else:  # SELL
            sl = entry + sl_dist
            tp1 = entry - sl_dist * _TP1_R
            tp2 = entry - sl_dist * _TP2_R

        leverage = _get_leverage(confidence, self.max_leverage)

        return SniperProposal(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.side,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            leverage=leverage,
            confidence=confidence,
            strategy_source=signal.strategy,
            llm_regime=regime,
            llm_reasoning=reasoning,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
            size_fraction=_SIZE_FRACTION,
        )
