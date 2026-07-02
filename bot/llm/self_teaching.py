"""
Self-Teaching Framework: The LLM's curriculum for continuous self-improvement.

This is the core intelligence growth engine. It provides a structured
framework for the LLM to:

1. STUDY: Analyze past trades to extract principles
2. HYPOTHESIZE: Form theories about what works and why
3. TEST: Validate hypotheses against incoming data
4. REFINE: Update beliefs based on evidence
5. TEACH: Codify learnings into reusable knowledge

The framework operates through "Learning Cycles" that run periodically
(not on every signal - that's too expensive). Each cycle:

  a) Reviews recent trade outcomes
  b) Identifies patterns (what worked, what failed)
  c) Updates the knowledge base
  d) Generates hypotheses for testing
  e) Validates or invalidates previous hypotheses
  f) Adjusts confidence in different strategies/setups

CURRICULUM LEVELS:

Level 1 - PATTERN RECOGNITION (Days 1-3)
  "What happened?"
  - Identify basic patterns: which symbols, sides, regimes win/lose
  - Map confidence levels to actual outcomes
  - Detect time-of-day and day-of-week patterns
  - Log all observations as raw data

Level 2 - CAUSAL ANALYSIS (Days 3-7)
  "Why did it happen?"
  - Link market conditions to outcomes (regime → result)
  - Identify strategy strengths/weaknesses per context
  - Analyze cross-market influences (BTC → alts)
  - Build initial "if X then Y" rules

Level 3 - PREDICTIVE MODELING (Days 7-14)
  "What will happen next?"
  - Use accumulated patterns to predict signal quality
  - Score signals before execution using learned heuristics
  - Track prediction accuracy (calibration)
  - Build confidence intervals around predictions

Level 4 - SNIPER REPLICATION (Days 14-30)
  "How do I recreate the best trades?"
  - Deep-study anatomy of top 10% trades
  - Identify common setup characteristics
  - Build "sniper profile" templates
  - Test if new signals match sniper profiles

Level 5 - STRATEGY SYNTHESIS (Day 30+)
  "Can I create new knowledge?"
  - Propose new trading rules based on observed patterns
  - Suggest strategy weight adjustments
  - Identify market regimes the system handles poorly
  - Generate novel insights from cross-pollinating data

KNOWLEDGE TYPES:

1. AXIOMS: Hard rules that never change
   "Never long alts into a BTC dump"
   "Funding extremes precede reversals"

2. PRINCIPLES: Strong beliefs backed by data
   "Regime trend strategy works best in trending markets"
   "3+ strategy agreement signals are 2x more profitable"

3. HYPOTHESES: Testable theories awaiting validation
   "SOL performs better in Asian trading hours"
   "High funding + declining OI = imminent squeeze"

4. OBSERVATIONS: Raw data points
   "BTC dropped 3% on 2x volume at 14:00 UTC"
   "Monte Carlo gave false signal in ranging market"

5. ANTI-PATTERNS: Things that DON'T work
   "Breakout longs in range regime fail 70% of time"
   "Low-confidence trades during high volatility lose money"
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("bot.llm.self_teaching")

_TEACH_DIR = os.path.join("data", "llm", "teaching")


def _ensure_dir():
    os.makedirs(_TEACH_DIR, exist_ok=True)


def _path(filename: str) -> str:
    return os.path.join(_TEACH_DIR, filename)


def _load_json(filename: str, default=None):
    _ensure_dir()
    filepath = _path(filename)
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[TEACH] Failed to load {filename}: {e}")
        # Preserve corrupt file for investigation
        if os.path.exists(filepath):
            try:
                os.rename(filepath, filepath + ".corrupt")
                logger.info(f"[TEACH] Renamed corrupt file to {filepath}.corrupt")
            except OSError:
                pass
        return default if default is not None else {}


def _save_json(filename: str, data):
    _ensure_dir()
    try:
        with open(_path(filename), "w") as f:
            json.dump(data, f, indent=2, default=str)
    except IOError as e:
        logger.warning(f"[TEACH] Failed to save {filename}: {e}")


# ═══════════════════════════════════════════════════════════════
# 1. Curriculum Level Tracking
# ═══════════════════════════════════════════════════════════════


class CurriculumLevel(IntEnum):
    PATTERN_RECOGNITION = 1
    CAUSAL_ANALYSIS = 2
    PREDICTIVE_MODELING = 3
    SNIPER_REPLICATION = 4
    STRATEGY_SYNTHESIS = 5


@dataclass
class CurriculumState:
    """Tracks the LLM's position in the learning curriculum."""
    current_level: int = 1
    level_started_at: float = 0.0
    started_at: float = 0.0
    trades_analyzed: int = 0
    hypotheses_total: int = 0
    hypotheses_validated: int = 0
    hypotheses_invalidated: int = 0
    predictions_made: int = 0
    predictions_correct: int = 0
    sniper_profiles_built: int = 0
    novel_rules_proposed: int = 0
    level_completions: List[Dict] = field(default_factory=list)

    @property
    def prediction_accuracy(self) -> float:
        if self.predictions_made == 0:
            return 0.0
        return self.predictions_correct / self.predictions_made

    @property
    def hypothesis_validation_rate(self) -> float:
        total = self.hypotheses_validated + self.hypotheses_invalidated
        if total == 0:
            return 0.0
        return self.hypotheses_validated / total

    @property
    def hours_at_level(self) -> float:
        if self.level_started_at == 0:
            return 0.0
        return (time.time() - self.level_started_at) / 3600

    @property
    def total_hours(self) -> float:
        if self.started_at == 0:
            return 0.0
        return (time.time() - self.started_at) / 3600


def _load_curriculum() -> CurriculumState:
    data = _load_json("curriculum_state.json", {})
    state = CurriculumState()
    for key, val in data.items():
        if hasattr(state, key):
            setattr(state, key, val)
    if state.started_at == 0:
        state.started_at = time.time()
        state.level_started_at = time.time()
    return state


def _save_curriculum(state: CurriculumState):
    data = {
        "current_level": state.current_level,
        "level_started_at": state.level_started_at,
        "started_at": state.started_at,
        "trades_analyzed": state.trades_analyzed,
        "hypotheses_total": state.hypotheses_total,
        "hypotheses_validated": state.hypotheses_validated,
        "hypotheses_invalidated": state.hypotheses_invalidated,
        "predictions_made": state.predictions_made,
        "predictions_correct": state.predictions_correct,
        "sniper_profiles_built": state.sniper_profiles_built,
        "novel_rules_proposed": state.novel_rules_proposed,
        "level_completions": state.level_completions[-20:],
    }
    _save_json("curriculum_state.json", data)


# ═══════════════════════════════════════════════════════════════
# 2. Knowledge Types
# ═══════════════════════════════════════════════════════════════


class KnowledgeType:
    AXIOM = "axiom"           # Hard rules that never change
    PRINCIPLE = "principle"   # Strong beliefs backed by data
    HYPOTHESIS = "hypothesis" # Testable theories
    OBSERVATION = "observation"  # Raw data points
    ANTI_PATTERN = "anti_pattern"  # Things that don't work
    SNIPER_PROFILE = "sniper_profile"  # Template for best trades
    RULE = "rule"             # Proposed trading rule


@dataclass
class KnowledgeEntry:
    """A single piece of knowledge in the system."""
    knowledge_type: str
    content: str
    confidence: float = 0.5     # How confident are we in this? (0-1)
    evidence_count: int = 0     # How many data points support this?
    supporting: List[str] = field(default_factory=list)  # Evidence for
    contradicting: List[str] = field(default_factory=list)  # Evidence against
    created_at: float = 0.0
    last_validated: float = 0.0
    validation_count: int = 0   # Times validated as correct
    invalidation_count: int = 0 # Times found incorrect
    category: str = ""          # symbol, regime, strategy, timing, risk, etc
    tags: List[str] = field(default_factory=list)
    source: str = "observation" # How was this generated?

    @property
    def net_validation(self) -> int:
        return self.validation_count - self.invalidation_count

    @property
    def is_reliable(self) -> bool:
        """Has this knowledge been validated enough to be trusted?"""
        return self.validation_count >= 3 and self.confidence >= 0.6

    @property
    def needs_testing(self) -> bool:
        """Does this hypothesis need more testing?"""
        return (
            self.knowledge_type == KnowledgeType.HYPOTHESIS
            and self.validation_count + self.invalidation_count < 5
        )


class KnowledgeBase:
    """Persistent, searchable knowledge base for the LLM."""

    def __init__(self):
        self._entries: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            data = _load_json("knowledge_base.json", {"entries": []})
            self._entries = data.get("entries", [])
            self._loaded = True

    def add(
        self,
        knowledge_type: str,
        content: str,
        confidence: float = 0.5,
        category: str = "",
        tags: List[str] = None,
        source: str = "observation",
        evidence: str = "",
    ) -> int:
        """Add new knowledge. Returns the index."""
        self._ensure_loaded()

        # Check for near-duplicate
        for i, e in enumerate(self._entries):
            if e["content"].lower().strip() == content.lower().strip():
                # Update existing instead of duplicating
                e["evidence_count"] = e.get("evidence_count", 0) + 1
                if evidence:
                    supporting = e.get("supporting", [])
                    supporting.append(evidence)
                    e["supporting"] = supporting[-20:]
                e["last_validated"] = time.time()
                self._save()
                return i

        entry = {
            "knowledge_type": knowledge_type,
            "content": content[:500],
            "confidence": confidence,
            "evidence_count": 1 if evidence else 0,
            "supporting": [evidence] if evidence else [],
            "contradicting": [],
            "created_at": time.time(),
            "last_validated": time.time(),
            "validation_count": 0,
            "invalidation_count": 0,
            "category": category,
            "tags": tags or [],
            "source": source,
        }
        self._entries.append(entry)

        # Cap size
        if len(self._entries) > 1000:
            self._compact()

        self._save()
        logger.info(f"[KNOWLEDGE] Added [{knowledge_type}]: {content[:80]}")
        return len(self._entries) - 1

    def validate(self, content: str, was_correct: bool, evidence: str = ""):
        """Validate or invalidate a piece of knowledge."""
        self._ensure_loaded()
        for e in self._entries:
            if e["content"].lower().strip() == content.lower().strip():
                if was_correct:
                    e["validation_count"] = e.get("validation_count", 0) + 1
                    e["confidence"] = min(0.95, e.get("confidence", 0.5) + 0.05)
                    if evidence:
                        e.setdefault("supporting", []).append(evidence)
                else:
                    e["invalidation_count"] = e.get("invalidation_count", 0) + 1
                    e["confidence"] = max(0.05, e.get("confidence", 0.5) - 0.1)
                    if evidence:
                        e.setdefault("contradicting", []).append(evidence)
                e["last_validated"] = time.time()
                self._save()
                return
        logger.debug(f"[KNOWLEDGE] Validation target not found: {content[:50]}")

    def search(
        self,
        knowledge_type: str = "",
        category: str = "",
        tag: str = "",
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> List[Dict]:
        """Search knowledge base with filters."""
        self._ensure_loaded()
        results = []
        for e in reversed(self._entries):
            if knowledge_type and e.get("knowledge_type") != knowledge_type:
                continue
            if category and e.get("category") != category:
                continue
            if tag and tag not in e.get("tags", []):
                continue
            if e.get("confidence", 0) < min_confidence:
                continue
            results.append(e)
            if len(results) >= limit:
                break
        return results

    def get_axioms(self) -> List[Dict]:
        """Get all axioms (hard rules)."""
        return self.search(knowledge_type=KnowledgeType.AXIOM, min_confidence=0.0)

    def get_principles(self, min_confidence: float = 0.5) -> List[Dict]:
        """Get validated principles."""
        return self.search(knowledge_type=KnowledgeType.PRINCIPLE, min_confidence=min_confidence)

    def get_active_hypotheses(self) -> List[Dict]:
        """Get hypotheses that still need testing."""
        self._ensure_loaded()
        return [
            e for e in self._entries
            if e.get("knowledge_type") == KnowledgeType.HYPOTHESIS
            and (e.get("validation_count", 0) + e.get("invalidation_count", 0)) < 10
        ]

    def get_anti_patterns(self) -> List[Dict]:
        """Get known anti-patterns (things to avoid)."""
        return self.search(knowledge_type=KnowledgeType.ANTI_PATTERN, min_confidence=0.3)

    def get_sniper_profiles(self) -> List[Dict]:
        """Get sniper trade profiles."""
        return self.search(knowledge_type=KnowledgeType.SNIPER_PROFILE)

    # Entries created before this instant predate the provenance standard
    # (THE_STANDARD 3b, 2026-07-02) and were mostly n=1 LLM self-labels on a
    # dirty ledger — quarantined from prompts until dollar re-scored.
    _PROVENANCE_EPOCH = 1782864000.0  # 2026-07-01T00:00:00Z

    @staticmethod
    def _prov_tag(e: Dict) -> str:
        """Serve-time provenance: [n, validated, era] (THE_STANDARD 3b —
        a stat/opinion without denominator+era is banned from prompts)."""
        vc = int(e.get("validation_count", 0) or 0)
        ic = int(e.get("invalidation_count", 0) or 0)
        try:
            era = time.strftime("%Y-%m", time.gmtime(float(e.get("created_at", 0) or 0)))
        except Exception:
            era = "?"
        return f" [n={vc + ic}, val={vc}, era={era}]"

    @staticmethod
    def _is_relevant(e: Dict, symbol: str, regime: str) -> bool:
        """Relevance filter. Fixed 2026-07-02 (FALLACY_AUDIT D6): the old
        expression contained `... or not regime or ...` — with regime unset
        every entry short-circuited to relevant, so all 237 principles
        qualified for every prompt. Empty filters no longer auto-qualify."""
        if not symbol and not regime:
            return True  # caller applied no filters
        content = e.get("content", "").lower()
        if symbol and symbol.lower() in content:
            return True
        if regime and regime.lower() in content:
            return True
        return e.get("category") in ("general", "")

    def get_for_llm_prompt(self, symbol: str = "", regime: str = "", max_items: int = 30) -> str:
        """Build a compact knowledge summary for LLM prompt injection.

        Prioritizes: axioms > principles > validated hypotheses > anti-patterns
        Filtered by relevance to current symbol/regime. Every served item
        carries [n, val, era] provenance (FALLACY_AUDIT D6/D12, 2026-07-02).
        """
        self._ensure_loaded()
        parts = []

        # Always include axioms
        axioms = self.get_axioms()
        if axioms:
            axiom_strs = [a["content"] + self._prov_tag(a) for a in axioms[:5]]
            parts.append("AXIOMS: " + " | ".join(axiom_strs))

        # Include relevant principles. Pre-2026-07 principles are quarantined:
        # 208/237 were created 2026-06 with val=0/inv=0 (naked n=1 opinions on
        # a dirty ledger) — they re-enter only via dollar re-score (D6).
        principles = self.get_principles(min_confidence=0.6)
        relevant_principles = []
        for p in principles:
            if float(p.get("created_at", 0) or 0) < self._PROVENANCE_EPOCH and \
                    int(p.get("validation_count", 0) or 0) < 3:
                continue  # quarantined: pre-standard era, never validated
            if self._is_relevant(p, symbol, regime):
                relevant_principles.append(p["content"] + self._prov_tag(p))
        if relevant_principles:
            parts.append("PRINCIPLES: " + " | ".join(relevant_principles[:8]))

        # Include anti-patterns
        anti = self.get_anti_patterns()
        relevant_anti = []
        for a in anti:
            if self._is_relevant(a, symbol, regime):
                relevant_anti.append(a["content"] + self._prov_tag(a))
        if relevant_anti:
            parts.append("AVOID: " + " | ".join(relevant_anti[:5]))

        # Include active hypotheses being tested (D12 fix: newest-first with a
        # 30-day max age — April volume-era hypotheses were served as current —
        # and near-dupe collapse on normalized content prefix).
        hypotheses = self.get_active_hypotheses()
        _max_age_s = 30 * 86400
        _now = time.time()
        hypotheses = [
            h for h in hypotheses
            if (_now - float(h.get("created_at", 0) or 0)) <= _max_age_s
        ]
        hypotheses.sort(key=lambda h: float(h.get("created_at", 0) or 0), reverse=True)
        hyp_strs, _seen_keys = [], set()
        for h in hypotheses:
            _key = " ".join(h.get("content", "").lower().split())[:60]
            if _key in _seen_keys:
                continue
            _seen_keys.add(_key)
            hyp_strs.append(h["content"] + self._prov_tag(h))
            if len(hyp_strs) >= 5:
                break
        if hyp_strs:
            parts.append("TESTING: " + " | ".join(hyp_strs))

        # Include sniper profiles
        snipers = self.get_sniper_profiles()
        if snipers:
            sniper_strs = [s["content"] + self._prov_tag(s) for s in snipers[:3]]
            parts.append("SNIPER PROFILES: " + " | ".join(sniper_strs))

        return "\n".join(parts)

    def _compact(self):
        """Remove low-confidence, unvalidated old entries."""
        now = time.time()
        # Keep: all axioms, all principles, recent entries, validated hypotheses
        kept = []
        for e in self._entries:
            kt = e.get("knowledge_type", "")
            if kt in (KnowledgeType.AXIOM, KnowledgeType.PRINCIPLE, KnowledgeType.SNIPER_PROFILE):
                kept.append(e)
            elif e.get("confidence", 0) >= 0.5:
                kept.append(e)
            elif now - e.get("created_at", 0) < 604800:  # < 7 days old
                kept.append(e)
            elif e.get("validation_count", 0) >= 2:
                kept.append(e)
        removed = len(self._entries) - len(kept)
        if removed > 0:
            logger.info(f"[KNOWLEDGE] Compacted: removed {removed} low-value entries")
        self._entries = kept

    def _save(self):
        _save_json("knowledge_base.json", {"entries": self._entries})

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics."""
        self._ensure_loaded()
        by_type = defaultdict(int)
        for e in self._entries:
            by_type[e.get("knowledge_type", "unknown")] += 1

        avg_conf = 0.0
        if self._entries:
            avg_conf = sum(e.get("confidence", 0) for e in self._entries) / len(self._entries)

        return {
            "total_entries": len(self._entries),
            "by_type": dict(by_type),
            "avg_confidence": round(avg_conf, 3),
            "validated_count": sum(1 for e in self._entries if e.get("validation_count", 0) >= 3),
        }


# ═══════════════════════════════════════════════════════════════
# 3. Learning Cycle Engine
# ═══════════════════════════════════════════════════════════════


class LearningCycleEngine:
    """Orchestrates periodic learning cycles.

    A learning cycle:
    1. Reviews recent trade outcomes (batch)
    2. Extracts patterns using heuristics
    3. Generates hypotheses
    4. Validates existing hypotheses
    5. Updates knowledge base
    6. Checks curriculum advancement

    Runs every N trades or every M minutes (whichever comes first).
    """

    def __init__(self):
        self.knowledge = KnowledgeBase()
        self.curriculum = _load_curriculum()
        self._last_cycle_time: float = 0
        self._trades_since_cycle: int = 0
        self._cycle_interval_s: float = 900   # 15 min for aggressive learning (was 30)
        self._trades_per_cycle: int = 5        # Learn faster (was 10)
        self._cycle_count: int = 0

        # Seed axioms on first run
        if not self.knowledge.get_axioms():
            self._seed_axioms()

    def _seed_axioms(self):
        """Seed the knowledge base with foundational trading axioms."""
        axioms = [
            ("Never long alts into a BTC dump - correlated selloff risk", "general"),
            ("Funding extremes precede reversals - crowded trades unwind", "general"),
            ("Volume without price movement signals accumulation/distribution", "general"),
            ("Price movement without volume is suspect - likely to reverse", "general"),
            ("3+ strategy agreement outperforms 2-strategy agreement historically", "strategy"),
            ("High-volatility regimes cap position sizing at 1x baseline", "risk"),
            ("Low-liquidity periods (weekends, off-hours) widen stops and reduce size", "timing"),
            ("Circuit breaker exists for a reason - override only for exceptional signals", "risk"),
            ("The trend is your friend until funding says otherwise", "general"),
            ("OI expanding + price rising = genuine trend. OI expanding + price flat = trap", "general"),
        ]
        for content, category in axioms:
            self.knowledge.add(
                knowledge_type=KnowledgeType.AXIOM,
                content=content,
                confidence=0.95,
                category=category,
                source="seed",
            )
        logger.info(f"[TEACH] Seeded {len(axioms)} foundational axioms")

    def should_run_cycle(self) -> bool:
        """Check if it's time for a learning cycle."""
        now = time.time()
        time_due = (now - self._last_cycle_time) >= self._cycle_interval_s
        trades_due = self._trades_since_cycle >= self._trades_per_cycle
        return time_due or trades_due

    def record_trade_for_learning(self, trade_data: Dict[str, Any]):
        """Record a trade for the next learning cycle."""
        self._trades_since_cycle += 1
        self.curriculum.trades_analyzed += 1

    def run_learning_cycle(
        self,
        recent_trades: List[Dict[str, Any]],
        market_state: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Run a complete learning cycle.

        Returns a report of what was learned.
        """
        self._cycle_count += 1
        self._last_cycle_time = time.time()
        self._trades_since_cycle = 0

        report = {
            "cycle_number": self._cycle_count,
            "curriculum_level": self.curriculum.current_level,
            "trades_analyzed": len(recent_trades),
            "patterns_found": [],
            "hypotheses_generated": [],
            "hypotheses_validated": [],
            "knowledge_added": [],
            "level_advanced": False,
        }

        if not recent_trades:
            return report

        level = CurriculumLevel(self.curriculum.current_level)

        # Level 1: Pattern Recognition
        if level >= CurriculumLevel.PATTERN_RECOGNITION:
            patterns = self._extract_patterns(recent_trades)
            report["patterns_found"] = patterns
            for p in patterns:
                self.knowledge.add(
                    knowledge_type=KnowledgeType.OBSERVATION,
                    content=p["description"],
                    confidence=p["confidence"],
                    category=p["category"],
                    tags=p.get("tags", []),
                    source="pattern_recognition",
                    evidence=p.get("evidence", ""),
                )
                report["knowledge_added"].append(p["description"])

        # Level 2: Causal Analysis
        if level >= CurriculumLevel.CAUSAL_ANALYSIS:
            hypotheses = self._generate_hypotheses(recent_trades)
            report["hypotheses_generated"] = hypotheses
            for h in hypotheses:
                self.knowledge.add(
                    knowledge_type=KnowledgeType.HYPOTHESIS,
                    content=h["hypothesis"],
                    confidence=h.get("confidence", 0.4),
                    category=h.get("category", ""),
                    tags=h.get("tags", []),
                    source="causal_analysis",
                )
                self.curriculum.hypotheses_total += 1

            # Validate existing hypotheses
            validated = self._validate_hypotheses(recent_trades)
            report["hypotheses_validated"] = validated

        # Level 3: Predictive Modeling
        if level >= CurriculumLevel.PREDICTIVE_MODELING:
            predictions = self._evaluate_predictions(recent_trades)
            report["prediction_accuracy"] = predictions.get("accuracy", 0)

        # Level 4: Sniper Replication
        if level >= CurriculumLevel.SNIPER_REPLICATION:
            snipers = self._analyze_sniper_candidates(recent_trades)
            report["sniper_candidates"] = snipers

        # Level 5: Strategy Synthesis
        if level >= CurriculumLevel.STRATEGY_SYNTHESIS:
            rules = self._propose_rules(recent_trades, market_state)
            report["rules_proposed"] = rules

        # Check curriculum advancement
        advanced = self._check_level_advancement()
        report["level_advanced"] = advanced

        # Cross-reference LLM decisions with outcomes (meta-learning)
        llm_insights = self._analyze_llm_decisions(recent_trades)
        if llm_insights:
            for insight in llm_insights:
                self.knowledge.add(
                    knowledge_type=KnowledgeType.OBSERVATION,
                    content=insight["content"],
                    confidence=insight.get("confidence", 0.7),
                    category=insight.get("category", "meta_learning"),
                    tags=["llm", "self_performance"],
                    source="llm_decision_analysis",
                )
                report["knowledge_added"].append(insight["content"])

        _save_curriculum(self.curriculum)

        logger.info(
            f"[TEACH] Cycle #{self._cycle_count}: Level {self.curriculum.current_level}, "
            f"{len(report['patterns_found'])} patterns, "
            f"{len(report['hypotheses_generated'])} hypotheses, "
            f"{len(report.get('knowledge_added', []))} knowledge items"
        )

        return report

    def _analyze_llm_decisions(self, recent_trades: List[Dict]) -> List[Dict]:
        """Cross-reference LLM decisions with trade outcomes for meta-learning.

        Checks:
        - Is the LLM overconfident in certain regimes?
        - Are flips working?
        - Is the LLM adding value vs baseline?
        - Are vetoes correctly filtering losers?
        """
        try:
            from llm.self_performance import get_performance_stats
            stats = get_performance_stats()
        except Exception:
            return []

        if not stats or stats.get("total_decisions", 0) < 10:
            return []

        insights = []

        # Check: Is LLM overconfident in certain regimes?
        for regime, acc in stats.get("regime_accuracy", {}).items():
            count = stats.get("regime_counts", {}).get(regime, 0)
            if acc < 0.40 and count >= 5:
                insights.append({
                    "type": "llm_weakness",
                    "content": (
                        f"LLM accuracy in {regime} regime is {acc:.0%} "
                        f"({count} decisions) — consider defaulting to skip"
                    ),
                    "category": "meta_learning",
                    "confidence": 0.7,
                })

        # Check: Are flips working?
        flip_sr = stats.get("flip_success_rate", 0.5)
        flip_count = stats.get("flip_count", 0)
        if flip_sr < 0.35 and flip_count >= 5:
            insights.append({
                "type": "llm_weakness",
                "content": (
                    f"LLM flips succeed only {flip_sr:.0%} — "
                    f"prefer skip over flip when uncertain"
                ),
                "category": "meta_learning",
                "confidence": 0.8,
            })

        # Check: Is LLM adding value vs baseline?
        accuracy = stats.get("accuracy", 0.5)
        total = stats.get("total_decisions", 0)
        if accuracy < 0.45 and total >= 20:
            insights.append({
                "type": "llm_performance",
                "content": (
                    f"LLM overall accuracy {accuracy:.0%} is below baseline — "
                    f"consider reducing autonomy level"
                ),
                "category": "operational",
                "confidence": 0.9,
            })

        # Check: Strong veto accuracy (positive feedback)
        veto_acc = stats.get("veto_accuracy", 0.5)
        skip_count = stats.get("skip_count", 0)
        if veto_acc > 0.75 and skip_count >= 10:
            insights.append({
                "type": "llm_strength",
                "content": (
                    f"LLM veto accuracy is strong ({veto_acc:.0%}) — "
                    f"vetoes are effectively filtering losers"
                ),
                "category": "meta_learning",
                "confidence": 0.7,
            })

        # Check: Calibration drift
        calibration = stats.get("calibration", 0.0)
        if abs(calibration) > 0.12 and total >= 15:
            direction = "overconfident" if calibration > 0 else "underconfident"
            insights.append({
                "type": "llm_calibration",
                "content": (
                    f"LLM is {direction} by {abs(calibration):.0%} — "
                    f"stated confidence {'exceeds' if calibration > 0 else 'trails'} "
                    f"actual win rate"
                ),
                "category": "meta_learning",
                "confidence": 0.8,
            })

        return insights

    def _extract_patterns(self, trades: List[Dict]) -> List[Dict]:
        """Level 1: Extract basic patterns from recent trades."""
        patterns = []

        if not trades:
            return patterns

        # Pattern: Win rate by symbol
        by_symbol = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in trades:
            sym = t.get("symbol", "unknown")
            by_symbol[sym]["total"] += 1
            if t.get("outcome") == "WIN":
                by_symbol[sym]["wins"] += 1
            by_symbol[sym]["pnl"] += t.get("pnl", 0)

        for sym, stats in by_symbol.items():
            if stats["total"] >= 3:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.7:
                    patterns.append({
                        "description": f"{sym} showing strong performance ({wr:.0%} WR, {stats['total']} trades, ${stats['pnl']:+.0f})",
                        "confidence": min(0.8, wr),
                        "category": "symbol",
                        "tags": [sym, "strong"],
                        "evidence": f"{stats['wins']}/{stats['total']} wins",
                    })
                elif wr <= 0.3:
                    patterns.append({
                        "description": f"{sym} performing poorly ({wr:.0%} WR, {stats['total']} trades, ${stats['pnl']:+.0f})",
                        "confidence": min(0.8, 1 - wr),
                        "category": "symbol",
                        "tags": [sym, "weak"],
                        "evidence": f"{stats['wins']}/{stats['total']} wins",
                    })

        # Pattern: Win rate by regime
        by_regime = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in trades:
            regime = t.get("regime", "unknown")
            by_regime[regime]["total"] += 1
            if t.get("outcome") == "WIN":
                by_regime[regime]["wins"] += 1

        for regime, stats in by_regime.items():
            if stats["total"] >= 3:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.65:
                    patterns.append({
                        "description": f"System performs well in {regime} regime ({wr:.0%} WR)",
                        "confidence": min(0.7, wr),
                        "category": "regime",
                        "tags": [regime, "favorable"],
                    })
                elif wr <= 0.35:
                    patterns.append({
                        "description": f"System struggles in {regime} regime ({wr:.0%} WR)",
                        "confidence": min(0.7, 1 - wr),
                        "category": "regime",
                        "tags": [regime, "unfavorable"],
                    })

        # Pattern: Confidence calibration
        well_calibrated = []
        poorly_calibrated = []
        for t in trades:
            conf = t.get("confidence", 0) / 100.0
            won = t.get("outcome") == "WIN"
            if conf >= 0.8 and not won:
                poorly_calibrated.append(t)
            elif conf < 0.65 and won:
                well_calibrated.append(t)

        if len(poorly_calibrated) >= 3:
            patterns.append({
                "description": f"Overconfidence detected: {len(poorly_calibrated)} high-conf trades lost",
                "confidence": 0.6,
                "category": "calibration",
                "tags": ["overconfident"],
                "evidence": f"{len(poorly_calibrated)} losses at >80% confidence",
            })

        # Pattern: Strategy agreement value
        by_agree = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in trades:
            n = t.get("num_agree", 0) or len(t.get("strategies_agreed", []))
            by_agree[n]["total"] += 1
            if t.get("outcome") == "WIN":
                by_agree[n]["wins"] += 1

        for n, stats in sorted(by_agree.items()):
            if stats["total"] >= 3:
                wr = stats["wins"] / stats["total"]
                patterns.append({
                    "description": f"{n}-strategy agreement: {wr:.0%} win rate ({stats['total']} trades)",
                    "confidence": 0.5 + (stats["total"] / 50),
                    "category": "strategy",
                    "tags": [f"agree_{n}"],
                })

        return patterns

    def _generate_hypotheses(self, trades: List[Dict]) -> List[Dict]:
        """Level 2: Generate testable hypotheses from trade data."""
        hypotheses = []

        if len(trades) < 5:
            return hypotheses

        # Hypothesis: Does hold time correlate with outcome?
        win_holds = [t.get("hold_time_s", 0) for t in trades if t.get("outcome") == "WIN"]
        loss_holds = [t.get("hold_time_s", 0) for t in trades if t.get("outcome") == "LOSS"]

        if win_holds and loss_holds:
            avg_win_hold = sum(win_holds) / len(win_holds)
            avg_loss_hold = sum(loss_holds) / len(loss_holds)

            if avg_win_hold < avg_loss_hold * 0.5:
                hypotheses.append({
                    "hypothesis": "Winning trades resolve faster than losing trades - consider tighter timeouts",
                    "confidence": 0.5,
                    "category": "timing",
                    "tags": ["hold_time", "timeout"],
                })

        # Hypothesis: Does side matter?
        long_wins = sum(1 for t in trades if t.get("side", "").upper() in ("BUY", "LONG") and t.get("outcome") == "WIN")
        long_total = sum(1 for t in trades if t.get("side", "").upper() in ("BUY", "LONG"))
        short_wins = sum(1 for t in trades if t.get("side", "").upper() in ("SELL", "SHORT") and t.get("outcome") == "WIN")
        short_total = sum(1 for t in trades if t.get("side", "").upper() in ("SELL", "SHORT"))

        if long_total >= 3 and short_total >= 3:
            long_wr = long_wins / long_total
            short_wr = short_wins / short_total
            if abs(long_wr - short_wr) >= 0.2:
                better = "longs" if long_wr > short_wr else "shorts"
                hypotheses.append({
                    "hypothesis": f"System currently favors {better} ({long_wr:.0%} long WR vs {short_wr:.0%} short WR)",
                    "confidence": 0.4,
                    "category": "direction",
                    "tags": ["side_bias"],
                })

        # Hypothesis: Is leverage correlated with poor outcomes?
        high_lev_losses = sum(1 for t in trades if t.get("leverage", 1) >= 5 and t.get("outcome") == "LOSS")
        high_lev_total = sum(1 for t in trades if t.get("leverage", 1) >= 5)
        if high_lev_total >= 3:
            high_lev_loss_rate = high_lev_losses / high_lev_total
            if high_lev_loss_rate >= 0.6:
                hypotheses.append({
                    "hypothesis": f"High leverage (5x+) trades losing at {high_lev_loss_rate:.0%} - consider capping leverage",
                    "confidence": 0.5,
                    "category": "risk",
                    "tags": ["leverage", "risk"],
                })

        return hypotheses

    def _validate_hypotheses(self, trades: List[Dict]) -> List[Dict]:
        """Level 2: Validate existing hypotheses against new data.

        FALLACY_AUDIT M10 (2026-07-02): the "edge" bar was hardcoded to 0.40
        anchored to a contaminated 35% baseline — BELOW the true mechanical
        baseline (~50-63%), so below-baseline sides "validated" directional
        bias into knowledge. Now: era-matched live baseline from
        get_system_baseline() (mechanical-only when USE_MECHANICAL_BASELINE),
        n>=13 windows, baseline logged in the evidence string.
        """
        validated = []
        active = self.knowledge.get_active_hypotheses()
        if not active:
            return validated

        # Live, era-matched baseline (THE_STANDARD 2b anchoring)
        baseline_wr = 0.50
        try:
            from llm.agents.dynamic_stats import get_system_baseline
            baseline_wr, _ = get_system_baseline()
        except Exception as _be:
            logger.debug(f"[TEACH] Baseline fetch failed, using 0.50: {_be}")
        edge_bar = baseline_wr + 0.05  # edge = meaningfully above live baseline

        for h in active:
            content = h.get("content", "").lower()

            # Check if any trade data supports or contradicts
            if "favors longs" in content:
                long_wr = self._calc_side_wr(trades, "long")
                if long_wr is not None:
                    correct = long_wr >= edge_bar
                    self.knowledge.validate(
                        h["content"], correct,
                        f"Long WR={long_wr:.0%} vs live baseline={baseline_wr:.0%} (bar={edge_bar:.0%})")
                    if correct:
                        self.curriculum.hypotheses_validated += 1
                    else:
                        self.curriculum.hypotheses_invalidated += 1
                    validated.append({"hypothesis": h["content"], "correct": correct})

            elif "favors shorts" in content:
                short_wr = self._calc_side_wr(trades, "short")
                if short_wr is not None:
                    correct = short_wr >= edge_bar
                    self.knowledge.validate(
                        h["content"], correct,
                        f"Short WR={short_wr:.0%} vs live baseline={baseline_wr:.0%} (bar={edge_bar:.0%})")
                    if correct:
                        self.curriculum.hypotheses_validated += 1
                    else:
                        self.curriculum.hypotheses_invalidated += 1
                    validated.append({"hypothesis": h["content"], "correct": correct})

        return validated

    def _calc_side_wr(self, trades: List[Dict], side: str) -> Optional[float]:
        """Calculate win rate for a specific side.

        n>=13 window (THE_STANDARD §1 small-n humility; was 3 — M10)."""
        matching = [t for t in trades if t.get("side", "").upper() in (side.upper(), "BUY" if side == "long" else "SELL")]
        if len(matching) < 13:
            return None
        wins = sum(1 for t in matching if t.get("outcome") == "WIN")
        return wins / len(matching)

    def _evaluate_predictions(self, trades: List[Dict]) -> Dict[str, Any]:
        """Level 3: Track prediction accuracy."""
        # This is tracked by the main system - we just report on it
        return {
            "accuracy": self.curriculum.prediction_accuracy,
            "total": self.curriculum.predictions_made,
        }

    def _analyze_sniper_candidates(self, trades: List[Dict]) -> List[Dict]:
        """Level 4: Identify and profile sniper-quality trades."""
        snipers = []
        for t in trades:
            if t.get("outcome") == "WIN" and t.get("pnl", 0) > 0:
                pnl_pct = t.get("pnl_pct", 0)
                if pnl_pct >= 3.0 or t.get("was_sniper"):
                    profile = (
                        f"Sniper: {t.get('symbol')} {t.get('side')} in {t.get('regime')} "
                        f"({t.get('confidence', 0):.0f}% conf, {t.get('num_agree', 0)} agree, "
                        f"+{pnl_pct:.1f}%, hold {t.get('hold_time_s', 0)/60:.0f}m)"
                    )
                    snipers.append({
                        "profile": profile,
                        "trade": t,
                    })
                    self.knowledge.add(
                        knowledge_type=KnowledgeType.SNIPER_PROFILE,
                        content=profile,
                        confidence=0.7,
                        category="sniper",
                        tags=[t.get("symbol", ""), t.get("regime", "")],
                        source="sniper_analysis",
                    )
                    self.curriculum.sniper_profiles_built += 1

        return snipers

    def _propose_rules(self, trades: List[Dict], market_state: Dict = None) -> List[Dict]:
        """Level 5: Propose new trading rules."""
        rules = []

        # Only propose rules with enough data
        if len(trades) < 20:
            return rules

        # Rule: If a symbol has > 70% win rate over 10+ trades, propose a principle
        by_sym = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in trades:
            sym = t.get("symbol", "")
            by_sym[sym]["total"] += 1
            if t.get("outcome") == "WIN":
                by_sym[sym]["wins"] += 1

        for sym, stats in by_sym.items():
            if stats["total"] >= 10:
                wr = stats["wins"] / stats["total"]
                if wr >= 0.70:
                    rule = f"Prioritize {sym} trades - consistently profitable ({wr:.0%} WR over {stats['total']} trades)"
                    rules.append({"rule": rule, "confidence": wr})
                    self.knowledge.add(
                        knowledge_type=KnowledgeType.PRINCIPLE,
                        content=rule,
                        confidence=wr,
                        category="symbol",
                        tags=[sym],
                        source="rule_synthesis",
                    )
                    self.curriculum.novel_rules_proposed += 1
                elif wr <= 0.30:
                    rule = f"Avoid {sym} trades - consistently losing ({wr:.0%} WR over {stats['total']} trades)"
                    rules.append({"rule": rule, "confidence": 1 - wr})
                    self.knowledge.add(
                        knowledge_type=KnowledgeType.ANTI_PATTERN,
                        content=rule,
                        confidence=1 - wr,
                        category="symbol",
                        tags=[sym],
                        source="rule_synthesis",
                    )
                    self.curriculum.novel_rules_proposed += 1

        return rules

    def _check_level_advancement(self) -> bool:
        """Check if the LLM should advance to the next curriculum level."""
        c = self.curriculum
        level = CurriculumLevel(c.current_level)

        if level == CurriculumLevel.PATTERN_RECOGNITION:
            # Accelerated: advance after 15+ trades and 24+ hours (was 20/72h)
            if c.trades_analyzed >= 15 and c.hours_at_level >= 24:
                return self._advance_level()

        elif level == CurriculumLevel.CAUSAL_ANALYSIS:
            # Accelerated: advance after generating and testing 7+ hypotheses (was 10/5/96h)
            if c.hypotheses_total >= 7 and (c.hypotheses_validated + c.hypotheses_invalidated) >= 3 and c.hours_at_level >= 48:
                return self._advance_level()

        elif level == CurriculumLevel.PREDICTIVE_MODELING:
            # Accelerated: 20+ predictions with > 52% accuracy (was 30/55%/168h)
            if c.predictions_made >= 20 and c.prediction_accuracy >= 0.52 and c.hours_at_level >= 72:
                return self._advance_level()

        elif level == CurriculumLevel.SNIPER_REPLICATION:
            # Accelerated: 3+ sniper profiles (was 5/336h)
            if c.sniper_profiles_built >= 3 and c.hours_at_level >= 168:
                return self._advance_level()

        # Level 5 is the final level - no advancement needed

        return False

    def _advance_level(self) -> bool:
        """Advance to the next curriculum level."""
        c = self.curriculum
        old_level = c.current_level
        if old_level >= CurriculumLevel.STRATEGY_SYNTHESIS:
            return False

        c.level_completions.append({
            "level": old_level,
            "completed_at": time.time(),
            "hours_spent": round(c.hours_at_level, 1),
            "trades_analyzed": c.trades_analyzed,
        })
        c.current_level = old_level + 1
        c.level_started_at = time.time()

        logger.info(
            f"[TEACH] LEVEL UP: {CurriculumLevel(old_level).name} -> "
            f"{CurriculumLevel(c.current_level).name} "
            f"(after {c.hours_at_level:.0f}h, {c.trades_analyzed} trades)"
        )
        _save_curriculum(c)
        return True

    def get_curriculum_report(self) -> Dict[str, Any]:
        """Get the full teaching report."""
        return {
            "curriculum": {
                "level": self.curriculum.current_level,
                "level_name": CurriculumLevel(self.curriculum.current_level).name,
                "hours_at_level": round(self.curriculum.hours_at_level, 1),
                "total_hours": round(self.curriculum.total_hours, 1),
                "trades_analyzed": self.curriculum.trades_analyzed,
                "hypotheses_total": self.curriculum.hypotheses_total,
                "hypotheses_validated": self.curriculum.hypotheses_validated,
                "hypotheses_invalidated": self.curriculum.hypotheses_invalidated,
                "prediction_accuracy": round(self.curriculum.prediction_accuracy, 3),
                "sniper_profiles": self.curriculum.sniper_profiles_built,
                "novel_rules": self.curriculum.novel_rules_proposed,
                "level_history": self.curriculum.level_completions,
            },
            "knowledge": self.knowledge.get_stats(),
            "cycle_count": self._cycle_count,
        }

    def get_knowledge_for_prompt(self, symbol: str = "", regime: str = "") -> str:
        """Get compact knowledge for LLM prompt injection."""
        return self.knowledge.get_for_llm_prompt(symbol, regime)


# ═══════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════

_engine: Optional[LearningCycleEngine] = None


def get_teaching_engine() -> LearningCycleEngine:
    """Get the singleton LearningCycleEngine."""
    global _engine
    if _engine is None:
        _engine = LearningCycleEngine()
    return _engine
