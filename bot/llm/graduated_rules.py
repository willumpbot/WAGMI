"""
Graduated Rules Engine — Converts validated hypotheses into executable trading rules.

When a hypothesis reaches 'validated' status (10+ evidence, 70%+ ratio),
it graduates into a codified rule that actively influences signal processing.

Rule types: VETO (block), BOOST (increase confidence), PENALIZE (decrease),
SIZE_ADJUST (modify sizing). Rules auto-retire if accuracy drops below 35%.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict, fields as dc_fields
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.graduated_rules")

_RULES_FILE = os.path.join("data", "llm", "graduated_rules.json")
# Captured at import so the pytest write-guard in _save() can distinguish the
# production path from a test-monkeypatched _RULES_FILE.
_DEFAULT_RULES_FILE = _RULES_FILE


def _canon_side(s: str) -> str:
    """Canonicalize side vocabulary so the engine matches regardless of caller.

    evaluate_signal() is called from the ensemble with BUY/SELL, but record_outcome()
    is called at close with event.side = SHORT/LONG. Without this, every side-conditioned
    rule (e.g. side="SELL") could never match at close ("SHORT" != "SELL") and so could
    never accrue times_correct — the structural 0-numerator bug. Map both vocabularies to
    one canonical form before comparison.
    """
    s = (s or "").upper()
    if s in ("BUY", "LONG"):
        return "LONG"
    if s in ("SELL", "SHORT"):
        return "SHORT"
    return s


@dataclass
class GraduatedRule:
    rule_id: str = ""
    hypothesis_statement: str = ""
    action: str = "penalize"  # veto, boost, penalize, size_adjust
    conditions: Dict[str, Any] = field(default_factory=dict)
    adjustment: float = 0.0
    confidence: float = 0.0
    evidence_ratio: float = 0.0
    total_evidence: int = 0
    created_at: float = 0.0
    last_applied: float = 0.0
    times_applied: int = 0
    times_correct: int = 0
    # Overridden = veto rule WOULD have fired but LLM_FIRST_MODE let the trade flow.
    # These never touch accuracy (the trade was NOT blocked), tracked separately for audit.
    times_overridden: int = 0
    overridden_correct: int = 0
    # PnL-weighted veto scoring (master plan P2, 2026-07-01): hit-RATE alone
    # retired vetoes that blocked a few small winners while saving big losses
    # (killed the vindicated hype_long_veto). Units: hypothetical_pnl_pct of the
    # blocked trade, accumulated at counterfactual resolution.
    # pnl_saved  = sum(|pnl_pct|) of blocked would-be LOSERS (veto correct)
    # pnl_missed = sum(pnl_pct)  of blocked would-be WINNERS (veto wrong)
    pnl_saved: float = 0.0
    pnl_missed: float = 0.0
    active: bool = True

    @property
    def accuracy(self) -> float:
        # Clamp to [0,1]: live data has corrupt counters (correct>applied → impossible >100%
        # ratios were being injected verbatim into LLM prompts, e.g. 8050%). 0.5 = unmeasured.
        if self.times_applied <= 0:
            return 0.5
        return max(0.0, min(1.0, self.times_correct / self.times_applied))

    @property
    def net_pnl_saved(self) -> float:
        """Dollar-aware veto value: pct-loss avoided minus pct-gain foregone."""
        return self.pnl_saved - self.pnl_missed

    def matches(self, symbol="", regime="", side="", strategy="",
                setup_type="", num_agree=0, confidence=0.0, hour_utc=-1,
                strategies_active=None) -> bool:
        if not self.active:
            return False
        c = self.conditions
        if c.get("symbol") and symbol.upper() != c["symbol"].upper():
            return False
        if c.get("regime"):
            # Canonicalize both sides for comparison — "trending_bull", "trending_bear",
            # "trending", "trend" all compare equal to a rule condition of "trending" or "trend"
            try:
                from llm.regime_canonical import canonicalize_regime
                _rule_rg = canonicalize_regime(c["regime"].lower())
                _in_rg = canonicalize_regime(regime.lower())
                # Also allow direct match on pre-canonicalization form
                if _rule_rg != _in_rg and c["regime"].lower() != regime.lower():
                    return False
            except Exception:
                if regime.lower() != c["regime"].lower():
                    return False
        if c.get("side") and _canon_side(side) != _canon_side(c["side"]):
            return False
        if c.get("strategy") and strategy != c["strategy"]:
            return False
        if c.get("strategies_include"):
            # Check that ALL listed strategies are present in the active strategies list.
            # Enables rules like "when bollinger_squeeze fires" on ensemble signals where
            # strategy="ensemble" but metadata["strategies_agree"] has the individual names.
            _active = set(strategies_active or [])
            if not all(s in _active for s in c["strategies_include"]):
                return False
        if c.get("strategies_exclude"):
            # Block match if any of these strategies are active (anti-pattern detection).
            _active = set(strategies_active or [])
            if any(s in _active for s in c["strategies_exclude"]):
                return False
        if c.get("setup_type") and setup_type != c["setup_type"]:
            return False
        if c.get("min_agree") and num_agree < c["min_agree"]:
            return False
        if "confidence_min" in c and confidence < c["confidence_min"]:
            return False
        if "confidence_max" in c and confidence > c["confidence_max"]:
            return False
        if "hour_utc_min" in c or "hour_utc_max" in c:
            if hour_utc < 0:
                return False  # can't evaluate hour condition without entry hour — skip rather than false-match
            if "hour_utc_min" in c and hour_utc < c["hour_utc_min"]:
                return False
            if "hour_utc_max" in c and hour_utc >= c["hour_utc_max"]:
                return False
        return True


class GraduatedRulesEngine:
    def __init__(self):
        self._rules: List[GraduatedRule] = []
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            os.makedirs(os.path.dirname(_RULES_FILE), exist_ok=True)
            if os.path.exists(_RULES_FILE):
                with open(_RULES_FILE, "r") as f:
                    data = json.load(f)
                _known = {f.name for f in dc_fields(GraduatedRule)}
                _loaded_rules: List[GraduatedRule] = []
                for _r in data.get("rules", []):
                    try:
                        _loaded_rules.append(GraduatedRule(**{k: v for k, v in _r.items() if k in _known}))
                    except Exception as _re:
                        logger.warning(f"[GRAD-RULES] Skip malformed rule {_r.get('rule_id', '?')}: {_re}")
                self._rules = _loaded_rules
                logger.info(f"[GRAD-RULES] Loaded {len(self._rules)} rules ({sum(1 for r in self._rules if r.active)} active)")
        except Exception as e:
            logger.warning(f"[GRAD-RULES] Load error: {e}")

    def _save(self):
        # Test-pollution guard (2026-07-02): a pytest run's engine._save() to the
        # production path wiped all 32 historical rules (incl. hype_long_veto_v1,
        # sol_long_veto_v1) at 2026-07-01 22:03Z, replacing them with the test's
        # rule set. Tests that monkeypatch _RULES_FILE to a tmp path still save.
        if os.getenv("PYTEST_CURRENT_TEST") and _RULES_FILE == _DEFAULT_RULES_FILE:
            return
        try:
            os.makedirs(os.path.dirname(_RULES_FILE), exist_ok=True)
            with open(_RULES_FILE, "w") as f:
                json.dump({"rules": [asdict(r) for r in self._rules]}, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"[GRAD-RULES] Save error: {e}")

    def graduate_hypothesis(self, hypothesis) -> Optional[GraduatedRule]:
        """Convert a validated hypothesis into an executable rule."""
        self._ensure_loaded()

        for r in self._rules:
            if r.hypothesis_statement == hypothesis.statement:
                return None  # Already graduated

        conditions, action, adjustment = self._parse_hypothesis(hypothesis)
        if not conditions:
            return None

        rule = GraduatedRule(
            rule_id=f"rule_{int(time.time())}_{len(self._rules)}",
            hypothesis_statement=hypothesis.statement,
            action=action, conditions=conditions, adjustment=adjustment,
            confidence=hypothesis.confidence, evidence_ratio=hypothesis.evidence_ratio,
            total_evidence=hypothesis.total_evidence, created_at=time.time(),
        )
        self._rules.append(rule)
        self._save()
        logger.info(f"[GRAD-RULES] Graduated: {rule.action} when {conditions}")
        # Persist into knowledge_base.json so prompt_enricher injects into agent prompts
        self._write_to_knowledge_base(rule, hypothesis)
        return rule

    def _write_to_knowledge_base(self, rule: "GraduatedRule", hypothesis: Any) -> None:
        """Persist a graduated rule into knowledge_base.json for agent prompt injection."""
        _kb_path = os.path.join("data", "llm", "teaching", "knowledge_base.json")
        try:
            os.makedirs(os.path.dirname(_kb_path), exist_ok=True)
            if os.path.exists(_kb_path):
                with open(_kb_path, "r") as _f:
                    _kb = json.load(_f)
            else:
                _kb = {"entries": []}
            # Deduplicate by hypothesis statement
            for _e in _kb.get("entries", []):
                if _e.get("content", "").endswith(hypothesis.statement):
                    return
            _conds = rule.conditions
            _cat = "regime" if _conds.get("regime") else "symbol" if _conds.get("symbol") else "strategy"
            _prefix = {"veto": "AVOID", "boost": "EDGE", "penalize": "CAUTION", "size_adjust": "SIZE"}.get(rule.action, "RULE")
            _kb.setdefault("entries", []).append({
                "knowledge_type": "graduated_rule",
                "content": f"[{_prefix}] {hypothesis.statement}",
                "confidence": round(rule.confidence, 3),
                "evidence_count": rule.total_evidence,
                "evidence_ratio": round(rule.evidence_ratio, 3),
                "category": _cat,
                "tags": list(_conds.keys()),
                "source": "hypothesis_graduation",
                "rule_id": rule.rule_id,
                "action": rule.action,
                "conditions": _conds,
                "created_at": rule.created_at,
                "last_validated": rule.created_at,
                "validation_count": rule.total_evidence,
                "invalidation_count": 0,
            })
            with open(_kb_path, "w") as _f:
                json.dump(_kb, _f, indent=2, default=str)
            logger.info(f"[GRAD-RULES→KB] [{_prefix}] {hypothesis.statement[:60]}")
        except Exception as _e:
            logger.debug(f"[GRAD-RULES→KB] Write error: {_e}")

    def _parse_hypothesis(self, hypothesis) -> tuple:
        stmt = hypothesis.statement.lower()
        conditions: Dict[str, Any] = {}

        # Extract symbol
        for sym in ["btc", "eth", "sol", "hype", "doge", "pepe", "fartcoin", "sui", "avax"]:
            if sym in stmt:
                conditions["symbol"] = sym.upper()
                break

        # Extract regime
        for rg in ["trend", "range", "panic", "volatile", "high_volatility", "consolidation"]:
            if rg in stmt:
                conditions["regime"] = rg
                break

        # Extract side
        if any(w in stmt for w in ["short", "sell"]):
            conditions["side"] = "SELL"
        elif any(w in stmt for w in ["long", "buy"]):
            conditions["side"] = "BUY"

        # Extract strategy
        for strat in ["regime_trend", "confidence_scorer", "multi_tier_quality", "monte_carlo_zones",
                       "bollinger_squeeze", "funding_rate", "lead_lag", "liquidation_cascade",
                       "oi_delta", "probability_engine", "vmc_cipher"]:
            if strat.replace("_", " ") in stmt or strat in stmt:
                conditions["strategy"] = strat
                break

        # Extract agreement level
        m = re.search(r"(\d+)[- ]agree", stmt)
        if m:
            conditions["min_agree"] = int(m.group(1))

        # Determine action
        if any(w in stmt for w in ["strong", "outperform", "reliable", "profitable", "edge"]):
            action = "boost"
            adjustment = 12.0 if hypothesis.evidence_ratio >= 0.8 else 8.0
        elif any(w in stmt for w in ["weak", "unreliable", "underperform", "poor", "avoid"]):
            action = "penalize"
            adjustment = -15.0 if hypothesis.evidence_ratio <= 0.3 else -10.0
        elif any(w in stmt for w in ["never", "block", "veto", "skip"]):
            action = "veto"
            adjustment = 0.0
        else:
            action = "penalize"
            adjustment = -10.0

        if len(conditions) < 1:
            return {}, "", 0.0
        return conditions, action, adjustment

    def evaluate_signal(self, symbol="", regime="", side="", strategy="",
                        setup_type="", num_agree=0, confidence=0.0, hour_utc=-1,
                        strategies_active=None, veto_only=False) -> tuple:
        """Returns (should_veto, adjusted_confidence, applied_rules_summary, applied_veto_rule_ids).

        applied_veto_rule_ids: list of rule_id strings for the VETO rules that fired
        on this signal. Callers stamp these into the counterfactual record at veto
        time so the outcome resolves against the SAME rule population that fired
        (no lossy re-matching at resolution time).

        DENOMINATOR-LEAK FIX (2026-06): times_applied for VETO rules is NO LONGER
        incremented here. A veto fire that is not paired with a recorded outcome is
        simply UNMEASURED (acceptable under-sampling) — it can never inflate the
        denominator. record_veto_outcome() is the SOLE writer of veto times_applied
        AND times_correct, so the two counters always describe the SAME population by
        construction, regardless of how many code paths call evaluate_signal (incl.
        ensemble.evaluate_raw and any future caller). BOOST/PENALIZE counting is
        unchanged: their times_applied is still incremented here (numerator credited
        later by record_outcome() on trade close).

        strategies_active: list of individual strategy names that fired (e.g.
        ["bollinger_squeeze", "multi_tier_quality"]). Enables rules that condition
        on which strategies contributed — needed because ensemble signals always
        have strategy="ensemble" while individual names live in metadata.
        veto_only: if True, only check VETO rules (no times_applied increment for
        BOOST/PENALIZE). Used by the pre-LLM filter to avoid double-counting when
        the signal later flows through the full pipeline evaluation.
        """
        self._ensure_loaded()
        vetoed, conf_delta, applied = False, 0.0, []
        applied_veto_rule_ids: List[str] = []

        for rule in self._rules:
            if not rule.active or not rule.matches(symbol=symbol, regime=regime, side=side,
                                                    strategy=strategy, setup_type=setup_type,
                                                    num_agree=num_agree, confidence=confidence,
                                                    hour_utc=hour_utc,
                                                    strategies_active=strategies_active):
                continue
            if veto_only and rule.action != "veto":
                continue
            rule.last_applied = time.time()

            if rule.action == "veto":
                # NOTE: times_applied is intentionally NOT bumped here. The veto
                # denominator is owned exclusively by record_veto_outcome() so the
                # applied/correct populations can never diverge across call sites
                # (see method docstring — denominator-leak fix).
                vetoed = True
                applied.append(f"VETO:{rule.hypothesis_statement[:40]}")
                applied_veto_rule_ids.append(rule.rule_id)
            elif rule.action == "boost":
                # NOTE: times_applied is intentionally NOT bumped here. Doing so on every
                # scan made the denominator a scan-count while times_correct is a close-count
                # (two different populations -> meaningless accuracy, e.g. rule_10 3328/0).
                # The denominator is now owned exclusively by record_outcome() so applied &
                # correct share one population (mirrors the veto paired-increment fix).
                conf_delta += rule.adjustment
                applied.append(f"BOOST+{rule.adjustment}:{rule.hypothesis_statement[:30]}")
            elif rule.action == "penalize":
                # See boost note above — denominator owned by record_outcome().
                conf_delta += rule.adjustment
                applied.append(f"PEN{rule.adjustment}:{rule.hypothesis_statement[:30]}")

        # boost/penalize no longer mutate persistent counters here (only conf_delta, which
        # is transient), so evaluate_signal does not need to save — matches the veto path.

        return vetoed, max(0, min(100, confidence + conf_delta)), "; ".join(applied), applied_veto_rule_ids

    def record_outcome(self, symbol="", regime="", side="", won=False, hour_utc: int = -1,
                       strategies_active=None, num_agree: int = 0, confidence: float = 0.0):
        """Track rule accuracy after trade closes.

        VETO rules are skipped here — their accuracy is tracked by
        counterfactual_learner.py which has the blocked-trade context.
        hour_utc: entry UTC hour (0-23). Pass -1 to skip hour-conditioned matching
        (rules with hour conditions will then be skipped rather than incorrectly matched).
        strategies_active: list of strategy names that agreed on this signal at entry.
        num_agree: number of agreeing strategies.
        confidence: signal confidence at entry (0-100).
        """
        self._ensure_loaded()

        # DEBUG: Log incoming trade context
        logger.debug(f"[GRAD-RULES-DEBUG] record_outcome called: symbol={symbol} regime={regime} side={side} won={won} hour={hour_utc} strats={strategies_active} conf={confidence:.1f}")

        matched_count = 0
        for rule in self._rules:
            if not rule.active:
                continue
            if rule.action == "veto":
                continue  # handled by counterfactual_learner.py

            # DEBUG: Check each rule's match status
            match_result = rule.matches(symbol=symbol, regime=regime, side=side, hour_utc=hour_utc,
                                strategies_active=strategies_active, num_agree=num_agree,
                                confidence=confidence)
            if not match_result:
                # Log why this rule didn't match (detailed diagnosis)
                logger.debug(f"[GRAD-RULES-DEBUG] Rule NO MATCH: {rule.rule_id} | sym={rule.conditions.get('symbol','*')} vs {symbol} | regime={rule.conditions.get('regime','*')} vs {regime} | side={rule.conditions.get('side','*')} vs {side} | active={rule.active}")
                continue

            # Rule matched
            matched_count += 1
            logger.info(f"[GRAD-RULES-MATCH] {rule.rule_id}: {rule.hypothesis_statement[:60]} (action={rule.action})")

            # Denominator increment lives HERE (paired with the numerator below), NOT in
            # evaluate_signal — guarantees applied & correct share one population (the set of
            # closed trades this rule influenced), so accuracy = correct/applied is meaningful.
            rule.times_applied += 1

            if rule.action == "boost":
                if won:
                    rule.times_correct += 1
                    logger.info(f"[GRAD-RULES] BOOST +correct: {rule.rule_id} won trade (times_correct now={rule.times_correct}, times_applied={rule.times_applied})")
                else:
                    logger.debug(f"[GRAD-RULES] BOOST not incr: trade lost (correct only on wins)")
            elif rule.action == "penalize":
                if not won:
                    rule.times_correct += 1
                    logger.info(f"[GRAD-RULES] PENALIZE +correct: {rule.rule_id} lost trade (times_correct now={rule.times_correct}, times_applied={rule.times_applied})")
                else:
                    logger.debug(f"[GRAD-RULES] PENALIZE not incr: trade won (correct only on losses)")

            if rule.times_applied >= 10 and rule.accuracy < 0.35:
                rule.active = False
                logger.info(f"[GRAD-RULES] Auto-retired: {rule.hypothesis_statement[:50]} (acc={rule.accuracy:.0%})")

        if matched_count == 0:
            logger.debug(f"[GRAD-RULES-DEBUG] NO RULES MATCHED for {symbol} {side} in {regime} (checked {len([r for r in self._rules if r.active and r.action != 'veto'])} active non-veto rules)")

        self._save()

    def record_veto_outcome(self, rule_ids: List[str], won: Optional[bool],
                            hypothetical_pnl_pct: Optional[float] = None) -> None:
        """Credit VETO-rule accuracy by rule_id — the SOLE writer of veto counters.

        This is the ONLY place veto times_applied AND times_correct are mutated. By
        owning BOTH counters in one paired call, the applied (denominator) and correct
        (numerator) populations are identical BY CONSTRUCTION — no call site of
        evaluate_signal can inflate the denominator without a matching outcome record
        (denominator-leak fix). Called from counterfactual_learner.update_with_price
        when a stamped veto counterfactual resolves, using the exact rule_ids captured
        at veto time (no re-matching, no lossy condition drift).

        won: True  = the blocked trade WOULD have won  -> veto WRONG  -> applied +1
             False = the blocked trade WOULD have lost -> veto CORRECT -> applied +1, correct +1
             None  = unscored stub (e.g. site-4 missing SL/TP, no forward-track
                     possible) -> UNMEASURED: touches NEITHER applied nor correct.
                     The rule_id stamp is retained purely for audit. (Counting a
                     denominator with no possible numerator would itself be a leak.)

        hypothetical_pnl_pct: the counterfactual $ move of the blocked trade
        (already known at resolution). Accumulated into pnl_saved / pnl_missed
        so retirement is dollar-aware, not hit-rate-only (master plan P2 —
        rate-only scoring retired the vindicated hype_long_veto: 88.9% TRUE
        blocked-loser rate measured at 52.6% by the biased estimator).
        """
        self._ensure_loaded()
        if not rule_ids:
            return
        if won is None:
            # Unscored: do not enter the measured population at all.
            return
        _ids = set(rule_ids)
        changed = False
        for rule in self._rules:
            if rule.rule_id not in _ids or rule.action != "veto":
                continue
            changed = True
            # Denominator increment lives here (paired with the numerator), NOT in
            # evaluate_signal — guarantees applied & correct share one population.
            rule.times_applied += 1
            _pnl = abs(hypothetical_pnl_pct) if hypothetical_pnl_pct is not None else 0.0
            if won is False:
                rule.times_correct += 1
                rule.pnl_saved += _pnl
                logger.info(
                    f"[GRAD-RULES] VETO +correct: {rule.rule_id} blocked a loser "
                    f"(times_correct now={rule.times_correct}, times_applied={rule.times_applied}, "
                    f"pnl_saved={rule.pnl_saved:.2f}%)"
                )
            else:  # won is True
                rule.pnl_missed += _pnl
                logger.info(
                    f"[GRAD-RULES] VETO applied (wrong): {rule.rule_id} blocked a would-be winner "
                    f"(times_correct={rule.times_correct}, times_applied now={rule.times_applied}, "
                    f"pnl_missed={rule.pnl_missed:.2f}%)"
                )

            # Vetoes self-retire only when BOTH the hit rate is bad AND the rule
            # is not net-saving money — a veto that misses often but saves more
            # in avoided losses than it forgoes in winners stays active.
            if (rule.times_applied >= 10 and rule.accuracy < 0.35
                    and rule.net_pnl_saved <= 0):
                rule.active = False
                logger.info(
                    f"[GRAD-RULES] Auto-retired VETO: {rule.hypothesis_statement[:50]} "
                    f"(acc={rule.accuracy:.0%}, net_pnl_saved={rule.net_pnl_saved:.2f}%)"
                )
        if changed:
            self._save()

    def record_veto_overridden(self, rule_ids: List[str], won: Optional[bool]) -> None:
        """Track LLM_FIRST_MODE veto overrides separately (never touches accuracy).

        The trade was NOT blocked (it flowed through), so it must NOT enter the veto
        denominator. won=True means the overridden (taken) trade won -> the override
        was right to let it through.
        """
        self._ensure_loaded()
        if not rule_ids:
            return
        _ids = set(rule_ids)
        changed = False
        for rule in self._rules:
            if rule.rule_id not in _ids or rule.action != "veto":
                continue
            changed = True
            rule.times_overridden += 1
            if won is True:
                rule.overridden_correct += 1
        if changed:
            self._save()

    def get_active_rules_summary(self) -> str:
        self._ensure_loaded()
        active = [r for r in self._rules if r.active]
        if not active:
            return ""
        lines = []
        for r in active[:10]:
            # Veto correctness is now self-measuring via record_veto_outcome (resolved
            # counterfactuals credit times_correct by rule_id). Show real accuracy once
            # at least one outcome has resolved; 'unmeasured' only while times_correct
            # is still structurally 0 (no resolved counterfactual yet).
            if r.action == "veto":
                acc = f"{r.accuracy:.0%}" if (r.times_applied >= 3 and r.times_correct > 0) else "unmeasured"
            else:
                acc = f"{r.accuracy:.0%}" if r.times_applied >= 3 else "new"
            lines.append(f"  {r.action.upper()}: {r.hypothesis_statement[:50]} (acc={acc}, n={r.times_applied})")
        return "GRADUATED RULES:\n" + "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        self._ensure_loaded()
        active = [r for r in self._rules if r.active]
        return {
            "total_rules": len(self._rules), "active_rules": len(active),
            "total_applied": sum(r.times_applied for r in self._rules),
            "avg_accuracy": sum(r.accuracy for r in active) / len(active) if active else 0,
        }


_engine: Optional[GraduatedRulesEngine] = None


def get_graduated_rules_engine() -> GraduatedRulesEngine:
    global _engine
    if _engine is None:
        _engine = GraduatedRulesEngine()
    return _engine
