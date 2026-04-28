"""
PHASE 7: Symbol-Side Optimization
==================================
Based on ACTUAL trade data, implement aggressive sizing for edges,
minimal sizing for leaks.

KEY FINDINGS:
- ETH_LONG: +$3.18/trade (BUY THIS)
- SOL_SHORT: +$0.49/trade (BUY THIS)
- ETH_SHORT: -$83.98/trade (KILL THIS)
- BTC_LONG: -$3.81/trade (MINIMIZE)
- HYPE_LONG: -$2.94/trade (MINIMIZE)
"""

import json
from dataclasses import dataclass, asdict

@dataclass
class SymbolSideConfig:
    """Position sizing rules for each symbol+side combo"""
    symbol_side: str
    wr: float  # win rate observed
    avg_pnl: float  # avg PnL per trade
    sample_size: int  # number of historical trades
    recommendation: str  # BUY, HOLD, MINIMIZE, KILL
    sizing_multiplier: float  # how much to size relative to normal
    rationale: str

def create_optimized_config():
    """Create optimized sizing config based on historical data"""

    # Data from PHASE7_DEEP_ANALYSIS output
    configs = [
        SymbolSideConfig(
            symbol_side="ETH_LONG",
            wr=0.381,
            avg_pnl=3.18,
            sample_size=21,
            recommendation="AGGRESSIVE_BUY",
            sizing_multiplier=1.5,
            rationale="Only profitable setup. 38% WR with +$3.18/trade. Increase size."
        ),
        SymbolSideConfig(
            symbol_side="SOL_SHORT",
            wr=0.382,
            avg_pnl=0.49,
            sample_size=34,
            recommendation="BUY",
            sizing_multiplier=1.0,
            rationale="Marginally profitable. 38% WR. Normal sizing."
        ),
        SymbolSideConfig(
            symbol_side="BTC_SHORT",
            wr=0.118,
            avg_pnl=-0.54,
            sample_size=34,
            recommendation="MINIMIZE",
            sizing_multiplier=0.5,
            rationale="Losing despite decent trades. 12% WR. Cut size in half."
        ),
        SymbolSideConfig(
            symbol_side="BTC_LONG",
            wr=0.263,
            avg_pnl=-3.81,
            sample_size=19,
            recommendation="MINIMIZE",
            sizing_multiplier=0.3,
            rationale="Significant losses per trade. Only take when high confidence."
        ),
        SymbolSideConfig(
            symbol_side="SOL_LONG",
            wr=0.320,
            avg_pnl=-1.78,
            sample_size=25,
            recommendation="MINIMIZE",
            sizing_multiplier=0.4,
            rationale="Steady losses. Structural issue with SOL LONG."
        ),
        SymbolSideConfig(
            symbol_side="HYPE_LONG",
            wr=0.211,
            avg_pnl=-2.94,
            sample_size=38,
            recommendation="MINIMIZE",
            sizing_multiplier=0.3,
            rationale="High loss rate. 21% WR on 38 trades. Avoid."
        ),
        SymbolSideConfig(
            symbol_side="HYPE_SHORT",
            wr=0.250,
            avg_pnl=-2.07,
            sample_size=8,
            recommendation="MINIMIZE",
            sizing_multiplier=0.5,
            rationale="Small sample but consistent losses. Reduce."
        ),
        SymbolSideConfig(
            symbol_side="ETH_SHORT",
            wr=0.269,
            avg_pnl=-83.98,
            sample_size=26,
            recommendation="KILL",
            sizing_multiplier=0.0,
            rationale="CRITICAL LEAK: -$2,183 on 26 trades. -$83.98/trade. DO NOT TRADE."
        ),
    ]

    return configs

def generate_trading_config_override():
    """Generate Python code to inject into trading_config.py"""
    configs = create_optimized_config()

    code = """
# === PHASE 7 SYMBOL-SIDE OPTIMIZATION ===
# Based on 205-trade historical analysis
# ETH_LONG is the ONLY profitable setup (+$3.18/trade)
# ETH_SHORT is a critical leak (-$83.98/trade, -$2,183 total)
# Sizing multipliers applied AFTER base risk calculation

PHASE7_SYMBOL_SIDE_OPTIMIZATION = {
"""
    for cfg in configs:
        code += f'''    ("{cfg.symbol_side.split('_')[0]}", "{cfg.symbol_side.split('_')[1]}"): {{
        "size_mult": {cfg.sizing_multiplier},
        "recommendation": "{cfg.recommendation}",
        "wr": {cfg.wr:.3f},
        "avg_pnl": {cfg.avg_pnl:.2f},
        "sample_size": {cfg.sample_size},
        "rationale": "{cfg.rationale}"
    }},
'''
    code += "}\n"
    return code

def generate_implementation_guide():
    """Generate implementation checklist"""
    configs = create_optimized_config()

    print("=" * 80)
    print("IMPLEMENTATION GUIDE: SYMBOL-SIDE OPTIMIZATION")
    print("=" * 80)

    print("\nIMMEDIATE ACTIONS (High Confidence):")
    print("-" * 80)

    for cfg in configs:
        if cfg.recommendation in ["AGGRESSIVE_BUY", "KILL"]:
            urgency = "CRITICAL" if cfg.recommendation == "KILL" else "HIGH"
            print(f"\n[{urgency}] {cfg.symbol_side}")
            print(f"     Action: {cfg.recommendation}")
            print(f"     Data: {cfg.wr:.1%} WR, ${cfg.avg_pnl:.2f}/trade (n={cfg.sample_size})")
            print(f"     Sizing: {cfg.sizing_multiplier}x")
            print(f"     {cfg.rationale}")

    print("\n\nMEDIUM-TERM ACTIONS (Next 4 hours):")
    print("-" * 80)

    for cfg in configs:
        if cfg.recommendation == "MINIMIZE":
            print(f"\n{cfg.symbol_side}")
            print(f"     Sizing: {cfg.sizing_multiplier}x")
            print(f"     {cfg.rationale}")

    print("\n\nWHY THIS MATTERS:")
    print("-" * 80)
    print(f"""
ETH_SHORT is losing $83.98 per trade. With 2.1% of signals executed (13/625),
that's ~3 ETH_SHORT trades per day = $252 daily leak.

Cutting ETH_SHORT size would save ~$200/day, or $6,000/month.

Maximizing ETH_LONG (only profitable setup) adds 50% more profitable trades.

Combined impact: $200-300/day improvement potential.
""")

def main():
    configs = create_optimized_config()

    # Print implementation guide
    generate_implementation_guide()

    # Generate config code
    print("\nGENERATED CODE SNIPPET:")
    print("-" * 80)
    print(generate_trading_config_override())

    # Summary table
    print("\nSUMMARY TABLE:")
    print("-" * 80)
    print(f"{'Setup':<15} {'WR':<8} {'$/trade':<12} {'n':<5} {'Mult':<8} {'Recommend':<15}")
    print("-" * 80)
    for cfg in sorted(configs, key=lambda x: x.avg_pnl, reverse=True):
        setup = cfg.symbol_side
        wr = f"{cfg.wr:.1%}"
        pnl = f"${cfg.avg_pnl:.2f}"
        print(f"{setup:<15} {wr:<8} {pnl:<12} {cfg.sample_size:<5} {cfg.sizing_multiplier:<8.1f}x {cfg.recommendation:<15}")

if __name__ == '__main__':
    main()
