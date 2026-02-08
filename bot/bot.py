import os
import time
import signal
import threading
import requests
from typing import Dict, Any
from datetime import datetime, timezone
import json
import random
import logging
import uuid

logger = logging.getLogger("bot")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def now_ms() -> int:
    return int(time.time() * 1000)


class NunuIRL:
    def __init__(self, base_url: str, api_key: str = None, timeout: float = 5.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        if api_key:
            self.s.headers.update({"Authorization": f"Bearer {api_key}"})

    def _post(self, path: str, payload: Dict[str, Any], max_retries: int = 5, idempotency_key: str = None):
        url = f"{self.base}{path}"
        attempt = 0
        while attempt < max_retries:
            start = time.time()
            # generate a request id per outbound HTTP request
            rid = str(uuid.uuid4())
            headers = {"X-Request-Id": rid}
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            # include existing session headers
            headers.update(self.s.headers)
            try:
                r = self.s.post(url, json=payload, timeout=self.timeout, headers=headers)
                latency = (time.time() - start) * 1000.0
                log_line = {"ts": datetime.utcnow().isoformat() + "Z", "event": "http_post", "path": path, "status": r.status_code, "latency_ms": latency, "request_id": rid}
                logger.info(json.dumps(log_line))
                # Do not retry on client errors (4xx) - return response so caller can inspect
                if 400 <= r.status_code < 500:
                    return r.json() if r.content else {"status": r.status_code}
                r.raise_for_status()
                return r.json()
            except Exception as e:
                latency = (time.time() - start) * 1000.0
                logger.warning(json.dumps({"ts": datetime.utcnow().isoformat() + "Z", "event": "http_error", "path": path, "error": str(e), "attempt": attempt, "latency_ms": latency, "request_id": rid}))
                attempt += 1
                # exponential backoff with jitter
                backoff = (2 ** attempt) + random.random()
                time.sleep(min(backoff, 30))
        raise Exception(f"Failed POST {url} after {max_retries} attempts")

    def trade(self, payload: Dict[str, Any], idempotency_key: str = None):
        return self._post("/v1/events/trade", payload, idempotency_key=idempotency_key)

    def pnl(self, payload: Dict[str, Any]):
        return self._post("/v1/events/pnl", payload)

    def position(self, payload: Dict[str, Any], idempotency_key: str = None):
        return self._post("/v1/events/position", payload, idempotency_key=idempotency_key)


def main():
    base_url = os.getenv("BASE_URL", "http://api:8000")
    strategy_id = os.getenv("STRATEGY_ID", "mtf-btc-1h-6h-16h")
    symbol = os.getenv("SYMBOL", "BTC-PERP")
    api_key = os.getenv("NUNUIRL_API_KEY", os.getenv("HEYANON_API_KEY", "dev_api_key_change_me"))

    client = NunuIRL(base_url=base_url, api_key=api_key)

    # Heartbeat thread: send heartbeat every 30 seconds
    def heartbeat_loop(stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                payload = {"strategyId": strategy_id, "ts": datetime.utcnow().isoformat() + "Z"}
                # best-effort; don't crash on failure
                client._post("/v1/events/heartbeat", payload, max_retries=2)
                logger.info(json.dumps({"ts": datetime.utcnow().isoformat() + "Z", "service": "bot", "event": "heartbeat", "strategyId": strategy_id}))
            except Exception:
                logger.warning(json.dumps({"ts": datetime.utcnow().isoformat() + "Z", "service": "bot", "event": "heartbeat_error", "strategyId": strategy_id}))
            stop_event.wait(30)

    hb_stop = threading.Event()
    hb_thread = threading.Thread(target=heartbeat_loop, args=(hb_stop,), daemon=True)
    hb_thread.start()

    # lightweight event logger to host-mounted /data
    def log_event(kind: str, payload: dict):
        try:
            os.makedirs("/data", exist_ok=True)
            with open("/data/bot_events.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {payload}\n")
        except Exception as e:
            print("log_event error:", repr(e))

    # OPTIONAL: send one test trade on start if SEND_TEST_TRADE=1
    if os.getenv("SEND_TEST_TRADE", "0") == "1":
        print("Sending test trade...")
        resp = client.trade({
            "strategyId": strategy_id,
            "symbol": symbol,
            "side": "buy",
            "qty": 0.001,
            "price": 61000.0,
            "ts": now_ms(),
            "tradeId": "boot-test-1",
        })
        print("Trade resp:", resp)

    # Import publishers unconditionally for trade/position posting
    from publishers import publish_trade, publish_position

    # Integrate external strategy module if present
    try:
        from best_1_6_16 import register_on_open, register_on_close, loop_once as strategy_loop_once, set_api_client
        
        # Inject API client so strategy can post its own evaluation logs
        set_api_client(client)

        def _on_open(pos):
            # pos is the dict created by strategy open_position
            try:
                # Normalize side to OPEN_LONG or OPEN_SHORT
                raw_side = pos.get("side", "BUY")
                if raw_side == "BUY":
                    normalized_side = "OPEN_LONG"
                elif raw_side == "SELL":
                    normalized_side = "OPEN_SHORT"
                else:
                    normalized_side = f"OPEN_{raw_side}"
                
                symbol = pos.get("symbol", "BTC-USD").replace("-USD", "USDT")
                
                # POST to production trades endpoint
                resp = client._post(f"/v1/strategies/{strategy_id}/trades", {
                    "order_id": f"strat-open-{int(time.time()*1000)}",
                    "side": normalized_side,
                    "symbol": symbol,
                    "fill_px": float(pos.get("entry", 0)),
                    "qty": float(pos.get("qty", 0)),
                    "status": "filled",
                    "ts": None,
                }, max_retries=1)
                print(f"✓ Trade posted: {normalized_side} {pos.get('qty')} {symbol} @ {pos.get('entry')}")
                
                # Also publish to old endpoint for backward compatibility
                try:
                    publish_trade(client, {
                        "strategy_id": strategy_id,
                        "trade_id": f"strat-open-{int(time.time())}",
                        "signal_id": pos.get("signal_id"),
                        "symbol": pos.get("symbol"),
                        "side": pos.get("side"),
                        "qty": pos.get("qty"),
                        "price": pos.get("entry"),
                        "ts": None,
                    })
                except Exception:
                    pass
                
            except Exception as e:
                print(f"Error posting trade: {e}")

        def _on_close(close_info):
            try:
                # Normalize side to CLOSE_LONG or CLOSE_SHORT
                raw_side = close_info.get("side", "BUY")
                if raw_side == "BUY":
                    normalized_side = "CLOSE_SHORT"  # Closing a short means buying
                elif raw_side == "SELL":
                    normalized_side = "CLOSE_LONG"  # Closing a long means selling
                else:
                    normalized_side = f"CLOSE_{raw_side}"
                
                symbol = close_info.get("symbol", "BTC-USD").replace("-USD", "USDT")
                
                # POST to production trades endpoint
                resp = client._post(f"/v1/strategies/{strategy_id}/trades", {
                    "order_id": f"strat-close-{int(time.time()*1000)}",
                    "side": normalized_side,
                    "symbol": symbol,
                    "fill_px": float(close_info.get("exit", 0)),
                    "qty": float(close_info.get("qty", 0)),
                    "status": "filled",
                    "ts": None,
                }, max_retries=1)
                print(f"✓ Trade posted: {normalized_side} {close_info.get('qty')} {symbol} @ {close_info.get('exit')} | PnL: ${close_info.get('pnl', 0):.2f}")
                
                # Also post PnL for backward compatibility
                try:
                    client.pnl({
                        "strategyId": strategy_id,
                        "ts": None,
                        "realizedPnL": float(close_info.get("pnl", 0.0)),
                        "unrealizedPnL": 0.0,
                        "fees": float(close_info.get("fee", 0.0)),
                    })
                except Exception:
                    pass
                
            except Exception as e:
                print(f"Error posting close trade: {e}")

        register_on_open(_on_open)
        register_on_close(_on_close)
    except Exception:
        # no external strategy module available, continue with built-in demo
        strategy_loop_once = None

    # Minimal loop: periodically send a position snapshot
    stop_event = threading.Event()

    def _signal_handler(signum, frame):
        print(f"Received signal {signum}, shutting down gracefully...")
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    while not stop_event.is_set():
        current_size = float(os.getenv("DEMO_POS_SIZE", "0.0"))
        avg_entry = float(os.getenv("DEMO_AVG_ENTRY", "0.0"))
        leverage = float(os.getenv("DEMO_LEVERAGE", "0.0"))
        u_pnl = float(os.getenv("DEMO_U_PNL", "0.0"))
        payload = {
            "strategy_id": strategy_id,
            "position_id": f"pos-{int(time.time())}",
            "symbol": symbol,
            "side": os.getenv("DEMO_SIDE", "LONG"),
            "qty": current_size,
            "avg_entry": avg_entry,
            "leverage": leverage,
            "upnl": u_pnl,
            "meta": {},
        }
        try:
            resp = publish_position(client, payload)
            print("Position resp:", resp)
            try:
                log_event("position", resp)
            except Exception:
                pass
            # Only log position changes to UI (not every empty snapshot)
            # Skip if qty==0 and we're already flat
            if current_size != 0 or getattr(publish_position, '_last_logged_qty', -1) != 0:
                try:
                    client._post(f"/v1/strategies/{strategy_id}/logs", {
                        "event": "position_change" if current_size != 0 else "position_flat",
                        "market": symbol,
                        "note": f"qty={current_size} avg={avg_entry} lev={leverage} upnl={u_pnl}",
                        "score": 0,
                    }, max_retries=1)
                    publish_position._last_logged_qty = current_size
                except Exception:
                    pass
        except Exception as e:
            print("Position post error:", repr(e))

        # also run strategy loop once per iteration if present
        try:
            if 'strategy_loop_once' in locals() and strategy_loop_once:
                strategy_loop_once()
        except Exception as e:
            print("strategy loop error:", e)
        
        # Post a strategy evaluation log showing current market assessment
        try:
            # Try to read the last printed BTC STATUS from recent logs for context
            import re
            # This is a best-effort parse; in production you'd have strategy expose this directly
            pass  # For now, just log that strategy evaluated
        except Exception:
            pass

        # Wait with wakeable sleep so SIGTERM can be handled promptly
        interval = float(os.getenv("SNAPSHOT_INTERVAL_SEC", "30"))
        waited = 0.0
        step = 0.5
        while waited < interval and not stop_event.is_set():
            time.sleep(min(step, interval - waited))
            waited += step

    print("Bot stopped")


if __name__ == "__main__":
    main()
