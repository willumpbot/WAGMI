"""Rank-7 follow-up: the funding/OI/divergence perception must cover EVERY configured
trading symbol. A hardcoded ["BTC","ETH","SOL","HYPE"] list silently dropped XRP from
the agent-facing context, so the bot collected XRP funding/OI but never reasoned over it.
DEFAULT_SYMBOLS now derives from trading_config so it auto-tracks symbol expansion."""
import llm.agents.external_data as ed
import trading_config as tc


def test_external_default_symbols_match_config():
    assert set(ed.DEFAULT_SYMBOLS) == set(tc.DEFAULT_SYMBOLS.keys()), (
        f"external_data DEFAULT_SYMBOLS {ed.DEFAULT_SYMBOLS} must match configured "
        f"symbols {list(tc.DEFAULT_SYMBOLS.keys())} so perception reaches every traded symbol")


def test_xrp_present():
    assert "XRP" in ed.DEFAULT_SYMBOLS
