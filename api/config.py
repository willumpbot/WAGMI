import os

COINS = {
    "BTC": {"id": "BTCUSDT", "risk": "low"},
    "SOL": {"id": "SOLUSDT", "risk": "medium"},
    "HYPE": {"id": "HYPEUSDT", "risk": "high"},
}

VS_CURRENCY = "usd"
RISK_K = {"low": (1.0, 1.8), "medium": (1.3, 2.2), "high": (1.6, 2.8)}

CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "60"))
DISABLE_SIGNALS = int(os.getenv("DISABLE_SIGNALS", "0"))
API_ORIGINS = os.getenv("API_ORIGINS", "").split(",") if os.getenv("API_ORIGINS") else ["*"]
