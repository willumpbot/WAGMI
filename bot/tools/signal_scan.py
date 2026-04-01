"""Scan current market for strategy signals — what are we seeing right now?"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.fetcher import DataFetcher
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.bollinger_squeeze import BollingerSqueezeStrategy
from strategies.vmc_cipher import VMCCipherStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.probability_engine import ProbabilityEngineStrategy

COIN_IDS = {"HYPE": "hyperliquid", "SOL": "solana", "BTC": "bitcoin", "DOGE": "dogecoin"}
TIMEFRAMES = ["5m", "1h", "6h", "daily"]

# Dummy symbols config needed by strategy constructors
SYMBOLS_CONFIG = {
    "HYPE": {"coin_id": "hyperliquid"},
    "SOL": {"coin_id": "solana"},
    "BTC": {"coin_id": "bitcoin"},
    "DOGE": {"coin_id": "dogecoin"},
}


def main():
    fetcher = DataFetcher()

    strategies = [
        ("regime_trend", RegimeTrendStrategy(SYMBOLS_CONFIG)),
        ("monte_carlo_zones", MonteCarloZonesStrategy(SYMBOLS_CONFIG)),
        ("confidence_scorer", ConfidenceScorerStrategy(SYMBOLS_CONFIG)),
        ("multi_tier_quality", MultiTierQualityStrategy(SYMBOLS_CONFIG)),
        ("bollinger_squeeze", BollingerSqueezeStrategy(SYMBOLS_CONFIG)),
        ("vmc_cipher", VMCCipherStrategy(SYMBOLS_CONFIG)),
        ("mean_reversion", MeanReversionStrategy(SYMBOLS_CONFIG)),
        ("probability_engine", ProbabilityEngineStrategy(SYMBOLS_CONFIG)),
    ]

    for sym in ["HYPE", "SOL", "BTC", "DOGE"]:
        print(f"\n{'='*50}")
        print(f"  {sym} SIGNAL SCAN")
        print(f"{'='*50}")

        # Fetch data
        data = {}
        for tf in TIMEFRAMES:
            df = fetcher.fetch_ohlcv(sym, COIN_IDS[sym], tf)
            if df is not None and not df.empty:
                data[tf] = df

        if not data:
            print("  No data available")
            continue

        if "1h" in data:
            price = data["1h"]["close"].iloc[-1]
            print(f"  Current price: ${price:.4f}")

        # Run each strategy
        signal_count = 0
        for name, strat in strategies:
            try:
                sig = strat.evaluate(sym, data)
                if sig:
                    signal_count += 1
                    valid = sig.is_valid if hasattr(sig, "is_valid") else "?"
                    print(f"  [{name}] {sig.side} conf={sig.confidence:.0f}% "
                          f"entry=${sig.entry:.4f} sl=${sig.sl:.4f} tp1=${sig.tp1:.4f} "
                          f"valid={valid}")
                else:
                    print(f"  [{name}] -- no signal")
            except Exception as e:
                err_str = str(e)[:80]
                print(f"  [{name}] ERROR: {err_str}")

        if signal_count == 0:
            print(f"  >>> NO signals from any strategy — ensemble would return None")
        elif signal_count == 1:
            print(f"  >>> 1 signal only — ensemble would REJECT (needs 2+)")
            print(f"  >>> BUT with solo-signal fix, sniper would still see it!")
        else:
            print(f"  >>> {signal_count} signals — ensemble would evaluate")

    print(f"\n{'='*50}")
    print("SUMMARY: If only 1 strategy fires per symbol, the solo-signal")
    print("callback routes to sniper. This is the EXPECTED state in choppy markets.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
