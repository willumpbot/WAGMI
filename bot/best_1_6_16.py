# Cleaned and packaged from Colab notebook best_1_6_16.py
# - removed notebook magics
# - DISCORD_WEBHOOK read from env
# - exposes generate_signal, loop_once and maintains open_positions/trade_log
# - supports registering callbacks for open/close events

import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

# ===== CONFIG =====
SYMBOLS = {
    "BTC": "BTC-USD",
    "SOL": "SOL-USD",
    "PUMP": "BTC-USD",  # Using BTC as proxy until PUMP data available
}

RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.015"))
STARTING_EQUITY = float(os.getenv("STARTING_EQUITY", "10000.0"))
TAKER_FEE_BPS = int(os.getenv("TAKER_FEE_BPS", "5"))
SCAN_INTERVAL_S = int(os.getenv("SCAN_INTERVAL_S", "60"))
VERBOSE = os.getenv("VERBOSE", "1") not in ("0", "False", "false")

# Regime TFs
HTF_HOURS = int(os.getenv("HTF_HOURS", "16"))

# Discord webhook optionally provided via env
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

# ===== STATE =====
equity = STARTING_EQUITY
open_positions: dict = {}
trade_log: list = []

# Callbacks
on_open_callback = None
on_close_callback = None
api_client = None  # Will be injected by bot.py for posting strategy logs

def register_on_open(cb):
    global on_open_callback
    on_open_callback = cb

def register_on_close(cb):
    global on_close_callback
    on_close_callback = cb

def set_api_client(client):
    """Inject the NunuIRL client so strategy can post its own logs"""
    global api_client
    api_client = client

# ===== UTIL =====
def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK:
        if VERBOSE:
            print("[WARN] No DISCORD_WEBHOOK set. Message:", message)
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        if r.status_code not in (200, 204):
            print(f"[WARN] Discord {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[WARN] Discord send failed: {e}")

def log(msg: str) -> None:
    print(datetime.now(timezone.utc).isoformat(), msg)

# ===== DATA FETCH + INDICATORS =====
ALLOWED_MINUTES = [1, 5, 15, 60, 360, 1440]

def snap_minutes(minutes: int) -> int:
    return min(ALLOWED_MINUTES, key=lambda x: abs(x - minutes))

def _fetch_coinbase_window(symbol: str, gran_s: int, start_ts: int, end_ts: int) -> pd.DataFrame:
    params = {
        "start": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "granularity": gran_s,
    }
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
    except requests.HTTPError:
        try:
            print(f"[{symbol}] Coinbase HTTPError {r.status_code}: {r.text} params={params}")
        except Exception:
            print(f"[{symbol}] Coinbase HTTPError: params={params}")
        return pd.DataFrame()
    except Exception as e:
        print(f"[{symbol}] Coinbase fetch failed: {e}")
        return pd.DataFrame()

    data = r.json() or []
    if not isinstance(data, list) or len(data) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()

def fetch_coinbase_paged(symbol: str, minutes: int, need_bars: int = 1000) -> pd.DataFrame:
    minutes = snap_minutes(int(minutes))
    gran = minutes * 60
    end = int(time.time() // gran * gran)
    out = []
    remaining = max(int(need_bars), 1)
    while remaining > 0:
        chunk_bars = min(300, remaining)
        start = end - chunk_bars * gran
        df = _fetch_coinbase_window(symbol, gran, start, end)
        if df.empty:
            break
        out.append(df)
        remaining -= len(df)
        end = int(df["time"].min().timestamp()) - gran
        if len(df) < 10:
            break
    if not out:
        return pd.DataFrame()
    df_all = pd.concat(out, ignore_index=True)
    df_all = df_all.sort_values("time").reset_index(drop=True)
    df_all = df_all.drop_duplicates(subset=["time"])
    return df_all

def fetch_coinbase(symbol: str, minutes: int, need_bars: int = 500) -> pd.DataFrame:
    minutes = snap_minutes(int(minutes))
    return fetch_coinbase_paged(symbol, minutes, need_bars=max(need_bars, 1))

def resample_ohlcv_1h(df1h: pd.DataFrame, hours: int) -> pd.DataFrame:
    if df1h.empty:
        return df1h
    d = df1h.copy().set_index("time")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = d.resample(f"{hours}h").agg(agg).dropna().reset_index()
    return out

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def macd(close):
    m = ema(close, 12) - ema(close, 26)
    sg = ema(m, 9)
    return m, sg, m - sg

def mfi_like(df, period=60):
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    up = (tp > tp.shift(1)).astype(float)
    dn = (tp < tp.shift(1)).astype(float)
    pos = mf.mul(up).rolling(period, min_periods=1).mean()
    neg = mf.mul(dn).rolling(period, min_periods=1).mean().replace(0, 1e-12)
    ratio = pos / neg
    return 100.0 - (100.0 / (1.0 + ratio))

def wavetrend(src):
    esa = src.ewm(span=9, adjust=False).mean()
    de = (src - esa).abs().ewm(span=9, adjust=False).mean().replace(0, 1e-12)
    ci = (src - esa) / (0.015 * de)
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(3, min_periods=1).mean()
    return wt1, wt2

def atr(df, n=14):
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()

def fee_amount(price, qty, bps=TAKER_FEE_BPS):
    return price * qty * (bps / 10000.0)

def _secs_to_next_hour() -> str:
    now = datetime.now(timezone.utc)
    nxt = (now.replace(minute=0, second=0, microsecond=0) + pd.Timedelta(hours=1))
    delta = (nxt - now).total_seconds()
    m, s = divmod(int(delta), 60)
    return f"{m}m {s}s"

# ===== CTR + ENGINE =====
def generate_signal(symbol: str, prod: str):
    df1h = fetch_coinbase(prod, 60, need_bars=2000)
    df6h = fetch_coinbase(prod, 360, need_bars=400)

    if df1h.empty or df6h.empty:
        if VERBOSE:
            log(f"[{symbol}] missing data (1h/6h)")
        return None

    dfHTF = resample_ohlcv_1h(df1h, HTF_HOURS)
    if dfHTF.empty or len(dfHTF) < 5:
        if VERBOSE:
            log(f"[{symbol}] missing HTF ({HTF_HOURS}h) from 1h resample")
        return None

    src1h = (df1h["high"] + df1h["low"] + df1h["close"]) / 3.0
    wt1, wt2 = wavetrend(src1h)
    mfi1 = mfi_like(df1h, 60)
    crossUp = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    crossDn = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
    mfi1g = (mfi1 > 50)

    _, _, h6 = macd(df6h["close"])
    mfi6 = mfi_like(df6h, 60)
    ok6 = bool(h6.iloc[-1] > 0 and mfi6.iloc[-1] > 50)

    _, _, hHTF = macd(dfHTF["close"])
    mfiHTF = mfi_like(dfHTF, 60)
    okHTF = bool(hHTF.iloc[-1] > 0 and mfiHTF.iloc[-1] > 50)

    multiBull = ok6 and okHTF
    multiBear = (not ok6) and (not okHTF)

    c = float(df1h["close"].iloc[-1])
    A = float(atr(df1h, 14).iloc[-1])
    R = 1.5 * A
    slBuy, tp1Buy, tp2Buy = c - R, c + 1.0 * R, c + 2.0 * R
    slSell, tp1Sell, tp2Sell = c + R, c - 1.0 * R, c - 2.0 * R

    wt1v = float(wt1.iloc[-1])
    wt2v = float(wt2.iloc[-1])
    mfi1v = float(mfi1.iloc[-1])
    mfi6v = float(mfi6.iloc[-1])
    mfiHTFv = float(mfiHTF.iloc[-1])
    h6v = float(h6.iloc[-1])
    hHTFv = float(hHTF.iloc[-1])
    cu = bool(crossUp.iloc[-1])
    cd = bool(crossDn.iloc[-1])

    alignLong = int(cu) + int(mfi1v > 50) + int(ok6) + int(okHTF)
    alignShort = int(cd) + int(mfi1v < 50) + int((not ok6)) + int((not okHTF))

    blockedLong = []
    if not cu:
        blockedLong.append("no_fresh_WT_up")
    if not (mfi1v > 50):
        blockedLong.append("MFI1h<=50")
    if not ok6:
        blockedLong.append("6h_regime_false")
    if not okHTF:
        blockedLong.append(f"{HTF_HOURS}h_regime_false")

    blockedShort = []
    if not cd:
        blockedShort.append("no_fresh_WT_dn")
    if not (mfi1v < 50):
        blockedShort.append("MFI1h>=50")
    if ok6:
        blockedShort.append("6h_regime_true")
    if okHTF:
        blockedShort.append(f"{HTF_HOURS}h_regime_true")

    try:
        last_up_idx = crossUp[::-1].idxmax() if crossUp.any() else None
        last_dn_idx = crossDn[::-1].idxmax() if crossDn.any() else None
        barsSinceUp = (len(crossUp) - 1 - last_up_idx) if last_up_idx is not None else None
        barsSinceDn = (len(crossDn) - 1 - last_dn_idx) if last_dn_idx is not None else None
    except Exception:
        barsSinceUp = None
        barsSinceDn = None

    if VERBOSE:
        log(
            "\n".join([
                f"[{symbol} STATUS]",
                f"  price={c:.2f}  next1hClose={_secs_to_next_hour()}  ATR1h={A:.2f}",
                f"  1h: WT1={wt1v:.2f} WT2={wt2v:.2f} cross={'up' if cu else ('down' if cd else 'none')}  MFI={mfi1v:.1f}",
                f"      lastCrossBarsAgo: up={barsSinceUp if barsSinceUp is not None else 'n/a'}, dn={barsSinceDn if barsSinceDn is not None else 'n/a'}",
                f"  6h: MACDh={h6v:.5f} MFI={mfi6v:.1f} OK={ok6}",
                f"{HTF_HOURS}h: MACDh={hHTFv:.5f} MFI={mfiHTFv:.1f} OK={okHTF}",
                f"  alignLong={alignLong}/4 blockedLong={blockedLong}",
                f"  alignShort={alignShort}/4 blockedShort={blockedShort}",
            ])
        )
        log(
            f"[{symbol}] c={c:.2f} | L:{alignLong}/4 S:{alignShort}/4 | "
            f"1h:WT_up={cu} WT_dn={cd} MFI={mfi1v:.1f} | 6hOK={ok6} {HTF_HOURS}hOK={okHTF}"
        )

    buy = cu and (mfi1v > 50) and multiBull
    sell = cd and (mfi1v < 50) and multiBear

    # Post rich evaluation log to API for UI visibility (production-quality)
    if api_client:
        try:
            strategy_id = os.getenv("STRATEGY_ID", "swing-perp-16h")
            event_type = "signal_long" if buy else ("signal_short" if sell else "evaluation")
            score = (alignLong * 25) if buy else ((alignShort * 25) if sell else max(alignLong, alignShort) * 20)
            
            # Determine label based on score and market conditions
            if buy:
                label = "Aggressive Accumulation"
            elif sell:
                label = "Aggressive Distribution"
            elif alignLong >= 3:
                label = "Accumulation"
            elif alignShort >= 3:
                label = "Distribution"
            else:
                label = "Observation"
            
            # Build compact note showing filters and blockers
            note_parts = [f"score {int(score)} • label {label}"]
            if buy:
                note_parts.append(f"✓ {alignLong}/4 long filters")
            elif sell:
                note_parts.append(f"✓ {alignShort}/4 short filters")
            else:
                filters_info = f"{alignLong}/4 long"
                if blockedLong:
                    filters_info += f" (blocked: {','.join(blockedLong[:2])})"
                note_parts.append(filters_info)
            
            # POST to canonical endpoint
            api_client._post(f"/v1/strategies/{strategy_id}/logs", {
                "event": event_type,
                "market": symbol.replace("-USD", "USDT"),  # Normalize to BTCUSDT format
                "note": " • ".join(note_parts),
                "score": int(score),
                "label": label,
                "price": round(c, 2),
            }, max_retries=1)
        except Exception as e:
            log(f"Failed to post evaluation log: {e}")

    if buy:
        log(f"[{symbol}] → BUY setup confirmed (alignLong={alignLong}/4). SL={slBuy:.2f} TP1={tp1Buy:.2f} TP2={tp2Buy:.2f}")
        return {"symbol": symbol, "side": "BUY", "entry": float(c), "sl": float(slBuy), "tp1": float(tp1Buy), "tp2": float(tp2Buy)}
    if sell:
        log(f"[{symbol}] → SELL setup confirmed (alignShort={alignShort}/4). SL={slSell:.2f} TP1={tp1Sell:.2f} TP2={tp2Sell:.2f}")
        return {"symbol": symbol, "side": "SELL", "entry": float(c), "sl": float(slSell), "tp1": float(tp1Sell), "tp2": float(tp2Sell)}

    return None

def open_position(signal: dict):
    global equity, open_positions, trade_log
    sym = signal["symbol"]
    side = signal["side"]
    entry = signal["entry"]
    sl = signal["sl"]
    tp1 = signal["tp1"]
    tp2 = signal["tp2"]
    stop_width = abs(entry - sl)
    if stop_width <= 0:
        log(f"[{sym}] skip: zero stop width")
        return
    risk_usd = equity * RISK_PER_TRADE
    qty = risk_usd / stop_width
    fee = fee_amount(entry, qty)
    pos = {
        "symbol": sym,
        "side": side,
        "entry": entry,
        "qty": qty,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "open_time": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "filled_tp1": False,
    }
    open_positions[sym] = pos
    trade_log.append({"symbol": sym, "action": "OPEN_" + side, "price": entry, "qty": qty, "fee": fee, "time": datetime.now(timezone.utc).isoformat()})
    msg = f"[{sym}] OPEN {side} @ {entry:.2f} qty={qty:.6f} SL={sl:.2f} TP1={tp1:.2f} TP2={tp2:.2f}"
    log(msg)
    send_discord(msg)
    if on_open_callback:
        try:
            on_open_callback(pos)
        except Exception as e:
            log(f"on_open_callback error: {e}")

def process_tp_sl(symbol: str, last_price: float):
    global equity, open_positions, trade_log
    if symbol not in open_positions:
        return
    p = open_positions[symbol]
    if p["status"] != "open":
        return

    side = p["side"]
    qty = p["qty"]
    entry = p["entry"]
    sl = p["sl"]
    tp1 = p["tp1"]
    tp2 = p["tp2"]

    hit_sl = (last_price <= sl) if side == "BUY" else (last_price >= sl)
    if hit_sl:
        fee = fee_amount(last_price, qty)
        pnl = (last_price - entry) * qty if side == "BUY" else (entry - last_price) * qty
        equity += (pnl - fee)
        trade_log.append({"symbol": symbol, "action": "CLOSE_SL", "price": last_price, "qty": qty, "fee": fee, "pnl": pnl, "time": datetime.now(timezone.utc).isoformat()})
        p["status"] = "closed"
        msg = f"[{symbol}] SL HIT @ {last_price:.2f} PnL={pnl:.2f} eq={equity:.2f}"
        log(msg)
        send_discord(msg)
        if on_close_callback:
            try:
                on_close_callback({"action": "CLOSE_SL", "symbol": symbol, "price": last_price, "qty": qty, "fee": fee, "pnl": pnl})
            except Exception as e:
                log(f"on_close_callback error: {e}")
        return

    if not p.get("filled_tp1", False):
        hit_tp1 = (last_price >= tp1) if side == "BUY" else (last_price <= tp1)
        if hit_tp1:
            qty1 = qty * 0.4
            fee = fee_amount(last_price, qty1)
            pnl = (last_price - entry) * qty1 if side == "BUY" else (entry - last_price) * qty1
            equity += (pnl - fee)
            trade_log.append({"symbol": symbol, "action": "TP1", "price": last_price, "qty": qty1, "fee": fee, "pnl": pnl, "time": datetime.now(timezone.utc).isoformat()})
            p["qty"] = qty * 0.6
            p["filled_tp1"] = True
            p["sl"] = entry
            msg = f"[{symbol}] TP1 @ {last_price:.2f} partial PnL={pnl:.2f}; SL->BE; rem qty={p['qty']:.6f}"
            log(msg)
            send_discord(msg)
            if on_close_callback:
                try:
                    on_close_callback({"action": "TP1", "symbol": symbol, "price": last_price, "qty": qty1, "fee": fee, "pnl": pnl})
                except Exception as e:
                    log(f"on_close_callback error: {e}")
            return

    hit_tp2 = (last_price >= tp2) if side == "BUY" else (last_price <= tp2)
    if hit_tp2:
        qty2 = p["qty"]
        fee = fee_amount(last_price, qty2)
        pnl = (last_price - entry) * qty2 if side == "BUY" else (entry - last_price) * qty2
        equity += (pnl - fee)
        trade_log.append({"symbol": symbol, "action": "TP2", "price": last_price, "qty": qty2, "fee": fee, "pnl": pnl, "time": datetime.now(timezone.utc).isoformat()})
        p["status"] = "closed"
        msg = f"[{symbol}] TP2 @ {last_price:.2f} PnL={pnl:.2f} eq={equity:.2f}"
        log(msg)
        send_discord(msg)
        if on_close_callback:
            try:
                on_close_callback({"action": "TP2", "symbol": symbol, "price": last_price, "qty": qty2, "fee": fee, "pnl": pnl})
            except Exception as e:
                log(f"on_close_callback error: {e}")

def latest_close(prod: str) -> Optional[float]:
    df1 = _fetch_coinbase_window(prod, 60, int(time.time()) - 90 * 60, int(time.time()))
    if df1.empty:
        return None
    return float(df1.sort_values("time")["close"].iloc[-1])

def loop_once():
    for sym, prod in SYMBOLS.items():
        try:
            if sym not in open_positions or open_positions[sym]["status"] != "open":
                sig = generate_signal(sym, prod)
                if sig:
                    open_position(sig)

            lp = latest_close(prod)
            if lp is not None:
                process_tp_sl(sym, lp)

        except Exception as e:
            log(f"[{sym}] ERROR: {e}")
            continue

    open_count = sum(1 for v in open_positions.values() if isinstance(v, dict) and v.get("status") == "open")
    log(f"[HEARTBEAT] equity={equity:.2f} open_positions={open_count}")

if __name__ == "__main__":
    try:
        while True:
            loop_once()
            time.sleep(SCAN_INTERVAL_S)
    except KeyboardInterrupt:
        log("Shutting down gracefully (KeyboardInterrupt).")
        pass
