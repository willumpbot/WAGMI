"""
Quant Data Provider — Central quantitative data backbone for the Quant Agent.

Computes REAL statistical data that the Quant Agent needs:
1. Kelly Fraction: Optimal position sizing per setup_type per regime
2. Conditional Edge: P(win | regime, confluence, volume, BTC alignment)
3. Fat-Tail Risk: 95th percentile adverse moves per regime
4. Avg Win/Loss: Per setup_type and regime for EV computation
5. Convergence Matrix: Strategy pair win rates
6. Bayesian Priors: Base rates for real-time updating

All data computed from TradeDNA records in deep_memory.
"""

import logging
import math
from collections import defaultdict
from typing import Dict, Any, Optional, List

logger = logging.getLogger("bot.llm.quant_data")


class QuantDataProvider:
    """Provides real quantitative data for the Quant Agent."""

    def __init__(self, trade_dna_store=None):
        self._dna = trade_dna_store

    def _get_trades(self) -> List[Dict]:
        if self._dna is None:
            try:
                from llm.deep_memory import get_deep_memory
                self._dna = get_deep_memory().trade_dna
            except Exception:
                return []
        self._dna._ensure_loaded()
        return self._dna._trades

    # ═══════════════════════════════════════════════════════════════
    # 1. Avg Win / Avg Loss per group
    # ═══════════════════════════════════════════════════════════════

    def get_avg_win_loss(self, group_by: str = "entry_type",
                         regime_filter: str = "") -> Dict[str, Dict]:
        trades = self._get_trades()
        groups: Dict[str, Dict[str, list]] = defaultdict(lambda: {"wins": [], "losses": []})

        for t in trades:
            if regime_filter and t.get("regime", "") != regime_filter:
                continue
            key = str(t.get(group_by, "unknown"))
            pnl_pct = t.get("pnl_pct", 0.0)
            if t.get("outcome") == "WIN":
                groups[key]["wins"].append(abs(pnl_pct))
            elif t.get("outcome") == "LOSS":
                groups[key]["losses"].append(abs(pnl_pct))

        result = {}
        for key, data in groups.items():
            nw, nl = len(data["wins"]), len(data["losses"])
            aw = sum(data["wins"]) / nw if nw else 0.0
            al = sum(data["losses"]) / nl if nl else 0.0
            result[key] = {
                "avg_win": round(aw, 4), "avg_loss": round(al, 4),
                "avg_win_ratio": round(aw / al, 3) if al > 0 else 0.0,
                "n_wins": nw, "n_losses": nl,
                "total_pnl": round(sum(data["wins"]) - sum(data["losses"]), 4),
            }
        return result

    # ═══════════════════════════════════════════════════════════════
    # 2. Kelly Fraction
    # ═══════════════════════════════════════════════════════════════

    def compute_kelly(self, setup_type: str = "", regime: str = "",
                      min_trades: int = 10) -> Dict[str, Any]:
        """Half-Kelly fraction for a given setup/regime."""
        trades = self._get_trades()
        filtered = [t for t in trades
                    if (not setup_type or t.get("entry_type", "") == setup_type)
                    and (not regime or t.get("regime", "") == regime)]

        n = len(filtered)
        if n < min_trades:
            return {"kelly_fraction": None, "half_kelly": None, "n_trades": n,
                    "sufficient_data": False, "reason": f"Only {n}/{min_trades} trades"}

        wins = [t for t in filtered if t.get("outcome") == "WIN"]
        losses = [t for t in filtered if t.get("outcome") == "LOSS"]
        wr = len(wins) / n if n else 0
        avg_win = sum(abs(t.get("pnl_pct", 0)) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(abs(t.get("pnl_pct", 0)) for t in losses) / len(losses) if losses else 0

        if avg_loss <= 0:
            return {"kelly_fraction": 0.0, "half_kelly": 0.0, "n_trades": n,
                    "sufficient_data": True, "reason": "No losses recorded"}

        ratio = avg_win / avg_loss
        kelly = (wr * ratio - (1 - wr)) / ratio
        half_kelly = max(0.0, kelly / 2.0)

        return {
            "kelly_fraction": round(kelly, 4), "half_kelly": round(half_kelly, 4),
            "win_rate": round(wr, 4), "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4), "avg_win_ratio": round(ratio, 3),
            "n_trades": n, "sufficient_data": True,
        }

    def compute_kelly_matrix(self, min_trades: int = 5) -> Dict[str, Dict]:
        """Kelly for every setup_type x regime combination."""
        trades = self._get_trades()
        setups = set(t.get("entry_type", "unknown") for t in trades)
        regimes = set(t.get("regime", "unknown") for t in trades)

        matrix = {}
        for st in setups:
            matrix[st] = {}
            for rg in regimes:
                k = self.compute_kelly(setup_type=st, regime=rg, min_trades=min_trades)
                if k.get("sufficient_data"):
                    matrix[st][rg] = {"hk": k["half_kelly"], "wr": k["win_rate"], "n": k["n_trades"]}
            k_all = self.compute_kelly(setup_type=st, min_trades=min_trades)
            if k_all.get("sufficient_data"):
                matrix[st]["_overall"] = {"hk": k_all["half_kelly"], "wr": k_all["win_rate"], "n": k_all["n_trades"]}
        return matrix

    # ═══════════════════════════════════════════════════════════════
    # 3. Conditional Edge
    # ═══════════════════════════════════════════════════════════════

    def compute_conditional_edge(self, regime: str = "", num_agree: int = 0,
                                  btc_aligned: Optional[bool] = None,
                                  volume_above_avg: Optional[bool] = None,
                                  min_trades: int = 5) -> Dict[str, Any]:
        trades = self._get_trades()
        base_wins = sum(1 for t in trades if t.get("outcome") == "WIN")
        base_wr = base_wins / len(trades) if trades else 0.5

        filtered, conditions = list(trades), []
        if regime:
            filtered = [t for t in filtered if t.get("regime") == regime]
            conditions.append(f"regime={regime}")
        if num_agree > 0:
            filtered = [t for t in filtered if t.get("num_agree", 0) >= num_agree]
            conditions.append(f"agree>={num_agree}")
        if btc_aligned is not None:
            filtered = [t for t in filtered if (t.get("btc_trend", "") in ("up", "bullish")) == btc_aligned]
            conditions.append(f"btc_aligned={btc_aligned}")
        if volume_above_avg is not None:
            filtered = [t for t in filtered if (t.get("volume_ratio", 1.0) > 1.0) == volume_above_avg]
            conditions.append(f"vol_above={volume_above_avg}")

        n = len(filtered)
        cond_str = " AND ".join(conditions) if conditions else "none"
        if n < min_trades:
            return {"base_wr": round(base_wr * 100, 1), "conditional_wr": None,
                    "n_similar": n, "edge_pct": None, "condition": cond_str, "sufficient_data": False}

        cond_wr = sum(1 for t in filtered if t.get("outcome") == "WIN") / n
        return {
            "base_wr": round(base_wr * 100, 1), "conditional_wr": round(cond_wr * 100, 1),
            "n_similar": n, "edge_pct": round((cond_wr - base_wr) * 100, 1),
            "condition": cond_str, "sufficient_data": True,
        }

    # ═══════════════════════════════════════════════════════════════
    # 4. Fat-Tail Risk
    # ═══════════════════════════════════════════════════════════════

    def compute_fat_tail_risk(self, regime: str = "") -> Dict[str, Any]:
        trades = self._get_trades()
        if regime:
            trades = [t for t in trades if t.get("regime") == regime]
        if len(trades) < 5:
            return {"fat_tail_risk": "unknown", "max_adverse_move_pct": None,
                    "p95_adverse": None, "n_trades": len(trades), "sufficient_data": False}

        adverse = []
        for t in trades:
            if t.get("outcome") == "LOSS":
                adverse.append(abs(t.get("pnl_pct", 0)))
            else:
                sl, entry = t.get("sl", 0), t.get("entry_price", 0)
                if sl > 0 and entry > 0:
                    adverse.append(abs(sl - entry) / entry * 100 * 0.5)

        if not adverse:
            return {"fat_tail_risk": "low", "max_adverse_move_pct": 0,
                    "p95_adverse": 0, "n_trades": len(trades), "sufficient_data": True}

        adverse.sort()
        n = len(adverse)
        p95 = adverse[min(int(n * 0.95), n - 1)]
        mean_a = sum(adverse) / n
        var = sum((x - mean_a) ** 2 for x in adverse) / n if n > 1 else 0
        kurt = (sum((x - mean_a) ** 4 for x in adverse) / (n * var ** 2) - 3.0) if var > 0 and n > 3 else 0.0

        risk = "high" if (p95 > 5.0 or kurt > 3.0) else ("medium" if (p95 > 2.5 or kurt > 1.0) else "low")
        if regime in ("panic", "high_volatility"):
            p95 *= 2.0
            risk = "high"

        return {
            "fat_tail_risk": risk, "max_adverse_move_pct": round(adverse[-1], 3),
            "p95_adverse": round(p95, 3), "mean_adverse": round(mean_a, 3),
            "excess_kurtosis": round(kurt, 2), "n_trades": len(trades), "sufficient_data": True,
        }

    # ═══════════════════════════════════════════════════════════════
    # 5. Strategy Convergence Matrix
    # ═══════════════════════════════════════════════════════════════

    def compute_convergence_matrix(self, min_trades: int = 3) -> Dict[str, Dict]:
        trades = self._get_trades()
        pair_stats: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        solo_stats: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0})

        for t in trades:
            strategies = sorted(t.get("strategies_agreed", []))
            won = t.get("outcome") == "WIN"
            pnl = t.get("pnl_pct", 0)
            for s in strategies:
                solo_stats[s]["total"] += 1
                if won:
                    solo_stats[s]["wins"] += 1
            for i in range(len(strategies)):
                for j in range(i + 1, len(strategies)):
                    pk = f"{strategies[i]}+{strategies[j]}"
                    pair_stats[pk]["total"] += 1
                    if won:
                        pair_stats[pk]["wins"] += 1
                    pair_stats[pk]["pnl"] += pnl

        result = {}
        for pk, st in pair_stats.items():
            if st["total"] < min_trades:
                continue
            wr = st["wins"] / st["total"]
            strats = pk.split("+")
            best_solo = max((solo_stats[s]["wins"] / solo_stats[s]["total"]
                             if solo_stats[s]["total"] > 0 else 0.5) for s in strats)
            result[pk] = {
                "wr": round(wr * 100, 1), "n": st["total"],
                "avg_pnl": round(st["pnl"] / st["total"], 4),
                "edge_vs_solo": round((wr - best_solo) * 100, 1),
                "convergent": wr > best_solo,
            }
        return result

    # ═══════════════════════════════════════════════════════════════
    # 6. Bayesian Priors
    # ═══════════════════════════════════════════════════════════════

    def compute_bayesian_priors(self) -> Dict[str, Any]:
        trades = self._get_trades()
        if not trades:
            return {"base": {"wr": 0.5, "n": 0}, "by_regime": {}, "by_btc": {}, "by_volume": {}}

        total = len(trades)
        wins = sum(1 for t in trades if t.get("outcome") == "WIN")
        priors: Dict[str, Any] = {"base": {"wr": round(wins / total, 3), "n": total}}

        # By regime
        rg_groups: Dict[str, list] = defaultdict(list)
        for t in trades:
            rg_groups[t.get("regime", "unknown")].append(t)
        priors["by_regime"] = {
            rg: {"wr": round(sum(1 for t in ts if t.get("outcome") == "WIN") / len(ts), 3), "n": len(ts)}
            for rg, ts in rg_groups.items() if len(ts) >= 3
        }

        # By BTC alignment
        btc_a = [t for t in trades if t.get("btc_trend", "") in ("up", "bullish")]
        btc_g = [t for t in trades if t.get("btc_trend", "") in ("down", "bearish")]
        priors["by_btc"] = {}
        if len(btc_a) >= 3:
            priors["by_btc"]["aligned"] = {"wr": round(sum(1 for t in btc_a if t.get("outcome") == "WIN") / len(btc_a), 3), "n": len(btc_a)}
        if len(btc_g) >= 3:
            priors["by_btc"]["against"] = {"wr": round(sum(1 for t in btc_g if t.get("outcome") == "WIN") / len(btc_g), 3), "n": len(btc_g)}

        # By volume
        hv = [t for t in trades if t.get("volume_ratio", 1.0) > 1.5]
        lv = [t for t in trades if t.get("volume_ratio", 1.0) < 0.8]
        priors["by_volume"] = {}
        if len(hv) >= 3:
            priors["by_volume"]["high"] = {"wr": round(sum(1 for t in hv if t.get("outcome") == "WIN") / len(hv), 3), "n": len(hv)}
        if len(lv) >= 3:
            priors["by_volume"]["low"] = {"wr": round(sum(1 for t in lv if t.get("outcome") == "WIN") / len(lv), 3), "n": len(lv)}

        return priors

    # ═══════════════════════════════════════════════════════════════
    # 7. Full Quant Package
    # ═══════════════════════════════════════════════════════════════

    def build_quant_package(self, regime: str = "", num_agree: int = 0,
                            setup_type: str = "") -> Dict[str, Any]:
        """Build complete quant data package for a single evaluation."""
        pkg: Dict[str, Any] = {}

        k = self.compute_kelly(setup_type=setup_type, regime=regime, min_trades=5)
        if k.get("sufficient_data"):
            pkg["kelly"] = {"hk": k["half_kelly"], "wr": k["win_rate"],
                            "aw": k["avg_win"], "al": k["avg_loss"], "r": k["avg_win_ratio"], "n": k["n_trades"]}

        e = self.compute_conditional_edge(regime=regime, num_agree=num_agree, min_trades=3)
        if e.get("sufficient_data"):
            pkg["edge"] = {"bwr": e["base_wr"], "cwr": e["conditional_wr"],
                           "delta": e["edge_pct"], "n": e["n_similar"], "cond": e["condition"]}

        ft = self.compute_fat_tail_risk(regime=regime)
        if ft.get("sufficient_data"):
            pkg["tail"] = {"risk": ft["fat_tail_risk"], "p95": ft["p95_adverse"],
                           "max": ft["max_adverse_move_pct"], "kurt": ft["excess_kurtosis"]}

        wl = self.get_avg_win_loss(group_by="entry_type", regime_filter=regime)
        compact_wl = {k: {"aw": v["avg_win"], "al": v["avg_loss"], "r": v["avg_win_ratio"],
                          "n": v["n_wins"] + v["n_losses"]}
                      for k, v in wl.items() if v["n_wins"] + v["n_losses"] >= 3}
        if compact_wl:
            pkg["win_loss"] = compact_wl

        p = self.compute_bayesian_priors()
        if p.get("base", {}).get("n", 0) >= 5:
            pkg["priors"] = p

        conv = self.compute_convergence_matrix(min_trades=3)
        if conv:
            top = sorted(conv.items(), key=lambda x: x[1]["n"], reverse=True)[:10]
            pkg["convergence"] = {k: {"wr": v["wr"], "n": v["n"], "conv": v["convergent"]} for k, v in top}

        return pkg


_quant_provider: Optional[QuantDataProvider] = None


def get_quant_provider() -> QuantDataProvider:
    global _quant_provider
    if _quant_provider is None:
        _quant_provider = QuantDataProvider()
    return _quant_provider
