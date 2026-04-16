"""
Sector/Thematic Exposure Limits — Prevents concentrated exposure to asset themes.

Pairwise correlation tracks symbol-to-symbol relationships but misses thematic risk.
If long BTC, HYPE, and SOL simultaneously, all three are L1/crypto-beta assets that
move together in risk-off events. This module caps exposure by sector.

Usage:
    from execution.sector_exposure import SectorExposure
    se = SectorExposure(total_equity=50000)
    result = se.check_new_position("HYPE", 8000, [("BTC", 15000), ("SOL", 12000)])
    if not result.allowed:
        print(f"Blocked by {result.limiting_sector} cap")
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.execution.sector_exposure")

# ── Sector definitions ─────────────────────────────────────────
# Update as new symbols are added to the universe.

SYMBOL_SECTORS: Dict[str, List[str]] = {
    "BTC":   ["l1", "crypto_beta", "store_of_value"],
    "ETH":   ["l1", "crypto_beta", "smart_contract"],
    "SOL":   ["l1", "crypto_beta", "smart_contract"],
    "HYPE":  ["l1", "crypto_beta", "perp_dex"],
    "AVAX":  ["l1", "crypto_beta", "smart_contract"],
    "ARB":   ["l2", "smart_contract"],
    "OP":    ["l2", "smart_contract"],
    "DOGE":  ["meme", "crypto_beta"],
    "PEPE":  ["meme"],
    "WIF":   ["meme"],
    "LINK":  ["oracle", "defi_infra"],
    "AAVE":  ["defi", "lending"],
    "UNI":   ["defi", "dex"],
    "DYDX":  ["defi", "perp_dex"],
    "INJ":   ["l1", "perp_dex"],
    "SUI":   ["l1", "smart_contract"],
    "SEI":   ["l1", "smart_contract"],
    "TIA":   ["l1", "modular"],
    "JUP":   ["defi", "dex"],
    "W":     ["defi", "bridge"],
}

# Maximum notional exposure per sector as fraction of total portfolio equity.
SECTOR_CAPS: Dict[str, float] = {
    # Caps scaled for full-Kelly sizing (8% risk × 5x leverage = 40% notional per position).
    # Previous caps assumed ~1% risk per trade and made the bot effectively single-position
    # when running Kelly sizing. Finding 17 (2026-04-15) from the autonomous session documents
    # the mismatch in detail. Raising l1 and crypto_beta allows 2-4 concurrent L1 positions.
    "crypto_beta":    1.60,  # max 160% in general crypto-correlated assets (4 positions @ 40%)
    "l1":             1.50,  # max 150% in L1 chains (3 positions @ 50% with headroom)
    "l2":             0.60,  # max 60% in L2s (was 30 — same 2x bump)
    "smart_contract": 1.00,  # max 100% in smart contract platforms (was 50)
    "perp_dex":       0.50,  # max 50% in perp DEX tokens (was 25)
    "store_of_value": 1.00,  # BTC-like assets (was 50)
    "meme":           0.40,  # max 40% in meme coins (was 20)
    "defi":           0.80,  # max 80% in DeFi (was 40)
    "defi_infra":     0.60,  # max 60% in DeFi infrastructure (was 30)
    "oracle":         0.40,  # max 40% in oracle tokens (was 20)
    "lending":        0.40,  # max 40% in lending protocols (was 20)
    "dex":            0.50,  # max 50% in DEX tokens (was 25)
    "bridge":         0.30,  # max 30% in bridge tokens (was 15)
    "modular":        0.40,  # max 40% in modular blockchain (was 20)
}


class SectorExposureResult:
    """Result of a sector exposure check."""

    __slots__ = ("allowed", "limiting_sector", "current_exposure", "cap", "size_multiplier")

    def __init__(
        self,
        allowed: bool,
        limiting_sector: Optional[str],
        current_exposure: float,
        cap: float,
        size_multiplier: float,
    ):
        self.allowed = allowed
        self.limiting_sector = limiting_sector
        self.current_exposure = current_exposure
        self.cap = cap
        self.size_multiplier = size_multiplier

    def __repr__(self) -> str:
        return (
            f"SectorExposureResult(allowed={self.allowed}, "
            f"limiting_sector={self.limiting_sector!r}, "
            f"multiplier={self.size_multiplier:.2f})"
        )


class SectorExposure:
    """Portfolio sector/thematic exposure gate.

    Args:
        total_equity: Current total portfolio equity in USD.
    """

    def __init__(self, total_equity: float):
        self.total_equity = max(total_equity, 1.0)  # Avoid division by zero

    def check_new_position(
        self,
        symbol: str,
        new_notional: float,
        open_positions: List[Tuple[str, float]],
    ) -> SectorExposureResult:
        """Check if adding a new position would breach any sector cap.

        Args:
            symbol: Symbol of the proposed new position.
            new_notional: Proposed notional exposure in USD.
            open_positions: List of (symbol, notional) tuples for existing positions.

        Returns:
            SectorExposureResult with allowed flag and sizing multiplier.
        """
        sectors = SYMBOL_SECTORS.get(symbol, [])
        if not sectors:
            # Unknown symbol — allow but log
            logger.debug(f"[SECTOR] {symbol} not in sector map — allowing full size")
            return SectorExposureResult(
                allowed=True, limiting_sector=None,
                current_exposure=0.0, cap=1.0, size_multiplier=1.0,
            )

        # Sum existing exposure by sector
        sector_exposure: Dict[str, float] = defaultdict(float)
        for pos_sym, pos_notional in open_positions:
            for sec in SYMBOL_SECTORS.get(pos_sym, []):
                sector_exposure[sec] += abs(pos_notional)

        # Check each sector cap with new position added
        tightest_multiplier = 1.0
        limiting_sector = None
        limiting_exposure = 0.0
        limiting_cap = 1.0

        for sec in sectors:
            cap = SECTOR_CAPS.get(sec, 1.0)
            cap_notional = cap * self.total_equity
            current = sector_exposure[sec]

            if current + new_notional > cap_notional:
                headroom = max(0.0, cap_notional - current)
                multiplier = headroom / new_notional if new_notional > 0 else 0.0
                multiplier = round(max(0.0, min(1.0, multiplier)), 2)

                if multiplier < tightest_multiplier:
                    tightest_multiplier = multiplier
                    limiting_sector = sec
                    limiting_exposure = current / self.total_equity
                    limiting_cap = cap

        # Dust-floor: reject tiny partial positions instead of opening them.
        # Previous threshold was 0.10 which allowed 12% "dust" positions that
        # occupied a slot, paid full fees, but contributed negligible PnL either
        # way. Finding 17 sub-finding: with full-Kelly sizing, anything under
        # 30% of target is not worth the fees and slot occupation.
        if tightest_multiplier < 0.3:
            # Less than 30% of requested size — effectively blocked (dust)
            logger.info(
                f"[SECTOR] {symbol} BLOCKED — {limiting_sector} at "
                f"{limiting_exposure:.1%} (cap {limiting_cap:.0%}), "
                f"size would be reduced to {tightest_multiplier:.0%} (below dust floor)"
            )
            return SectorExposureResult(
                allowed=False, limiting_sector=limiting_sector,
                current_exposure=limiting_exposure, cap=limiting_cap,
                size_multiplier=0.0,
            )

        if tightest_multiplier < 1.0:
            logger.info(
                f"[SECTOR] {symbol} reduced to {tightest_multiplier:.0%} — "
                f"{limiting_sector} approaching cap ({limiting_exposure:.1%}/{limiting_cap:.0%})"
            )

        return SectorExposureResult(
            allowed=True,
            limiting_sector=limiting_sector if tightest_multiplier < 1.0 else None,
            current_exposure=limiting_exposure,
            cap=limiting_cap,
            size_multiplier=tightest_multiplier,
        )

    def get_exposure_report(
        self, open_positions: List[Tuple[str, float]]
    ) -> Dict[str, Any]:
        """Get full sector exposure breakdown.

        Returns:
            Dict with per-sector exposure, cap, and headroom.
        """
        sector_exposure: Dict[str, float] = defaultdict(float)
        for pos_sym, pos_notional in open_positions:
            for sec in SYMBOL_SECTORS.get(pos_sym, []):
                sector_exposure[sec] += abs(pos_notional)

        report = {}
        for sec in sorted(set(list(sector_exposure.keys()) + list(SECTOR_CAPS.keys()))):
            current = sector_exposure.get(sec, 0.0)
            cap = SECTOR_CAPS.get(sec, 1.0)
            cap_notional = cap * self.total_equity
            report[sec] = {
                "current_notional": round(current, 2),
                "current_pct": round(current / self.total_equity * 100, 1),
                "cap_pct": round(cap * 100, 1),
                "cap_notional": round(cap_notional, 2),
                "headroom": round(max(0, cap_notional - current), 2),
                "utilized_pct": round(current / cap_notional * 100, 1) if cap_notional > 0 else 0.0,
            }

        return report
