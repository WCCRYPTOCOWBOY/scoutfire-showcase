# scoutfire.py
# Scoutfire runner: loads .env, builds strategy, fetches candles, prints signals.
# Uses Coinbase public REST for candles (no keys needed). Execution is disabled by default.

from __future__ import annotations
import os, time, json, math, sys
import logging
from typing import List, Dict
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from dotenv import load_dotenv
import numpy as np

# --- Strategy selection ---
from strategy.ema_atr_trend import EmaAtrTrend
from strategy.ema_atr_trend_mtf import EmaAtrTrendMTF

# --------------------------------------------------------------------------------------
# Utils
# --------------------------------------------------------------------------------------
def getenv_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "1" if default else "0").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")

def http_get_json(url: str, params: Dict | None = None, headers: Dict | None = None):
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers=headers or {"User-Agent": "scoutfire/1.0"})
    with urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw)
    except Exception:
        # Some Coinbase endpoints return CSV-ish arrays; bubble up raw
        return raw

def coinbase_fetch_candles(product: str, granularity_sec: int) -> List[Dict]:
    """
    Coinbase Exchange public REST.
    Endpoint format: https://api.exchange.coinbase.com/products/{product}/candles
    Returns arrays of [time, low, high, open, close, volume] DESC by time.
    We'll convert to ASC list of dicts: {"t","o","h","l","c","v"}.
    """
    base = "https://api.exchange.coinbase.com"
    path = f"/products/{product}/candles"
    # Without start/end, Coinbase returns the latest ~300 bars by default.
    data = http_get_json(base + path, params={"granularity": granularity_sec})
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected candles response: {str(data)[:120]}")
    # Convert & sort ASC by time
    out = []
    for row in data:
        # Coinbase: [ time, low, high, open, close, volume ]
        t, low, high, open_, close, vol = row
        out.append({"t": int(t), "o": float(open_), "h": float(high), "l": float(low), "c": float(close), "v": float(vol)})
    out.sort(key=lambda x: x["t"])
    return out

def resample_5m_to_20m(c5: List[Dict]) -> List[Dict]:
    out = []
    n = len(c5)
    # Merge groups of 4 consecutive 5m candles -> one 20m
    for i in range(0, n - (n % 4), 4):
        a, b, c, d = c5[i:i+4]
        out.append({
            "t": d["t"],
            "o": a["o"],
            "h": max(a["h"], b["h"], c["h"], d["h"]),
            "l": min(a["l"], b["l"], c["l"], d["l"]),
            "c": d["c"],
            "v": a["v"] + b["v"] + c["v"] + d["v"],
        })
    return out

def latest_closed_t(candles: List[Dict]) -> int | None:
    return candles[-1]["t"] if candles else None

def fmt(x, nd=2):
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)

# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main():
    load_dotenv()

    # --- General env ---
    PRODUCT   = os.getenv("PRODUCT", "BTC-USD")
    STRATNAME = os.getenv("STRATEGY", "ema_atr_trend_mtf").lower()  # "ema_atr_trend" | "ema_atr_trend_mtf"
    CONFIRM   = getenv_bool("CONFIRM_ON_CLOSE", True)
    COOLDOWN  = int(os.getenv("COOLDOWN_BARS", "3"))
    TRADING_ENABLED = getenv_bool("SCOUTFIRE_TRADING_ENABLED", False)

    # --- Strategy params (EMA/ATR/RSI + leverage + MTF gate) ---
    settings = {
        # EMA/ATR
        "fast": int(os.getenv("EMA_FAST", "9")),
        "slow": int(os.getenv("EMA_SLOW", "21")),
        "atr_period": int(os.getenv("ATR_PERIOD", "14")),
        "atr_min": float(os.getenv("ATR_MIN", "0.002")),
        "risk_atr": float(os.getenv("RISK_ATR", "1.5")),
        "take_atr": float(os.getenv("TAKE_ATR", "2.0")),
        "direction": os.getenv("DIRECTION", "both"),
        # RSI
        "rsi_period": int(os.getenv("RSI_PERIOD", "14")),
        "rsi_overbought": float(os.getenv("RSI_OVERBOUGHT", "70")),
        "rsi_oversold": float(os.getenv("RSI_OVERSOLD", "30")),
        "rsi_buffer": float(os.getenv("RSI_BUFFER", "1.0")),
        # Leverage schedule
        "leverage_schedule": os.getenv("LEVERAGE_SCHEDULE", "10,10,8,7"),
        "leverage_default": float(os.getenv("LEVERAGE_DEFAULT", "7")),
        "trade_count_start": int(os.getenv("TRADE_COUNT_START", "0")),
        # 20m regime
        "htf_ema": int(os.getenv("HTF_EMA", "200")),
        "htf_bias": os.getenv("HTF_BIAS", "follow"),
    }

    # Choose strategy class
    if STRATNAME == "ema_atr_trend":
        strat = EmaAtrTrend(settings)
        use_mtf = False
    elif STRATNAME == "ema_atr_trend_mtf":
        strat = EmaAtrTrendMTF(settings)
        use_mtf = True
    else:
        print(f"Unknown STRATEGY={STRATNAME}; use ema_atr_trend or ema_atr_trend_mtf")
        sys.exit(1)

    print(f"🐺 Scoutfire started | Product={PRODUCT} | Strategy={STRATNAME} | Trading={'ON' if TRADING_ENABLED else 'OFF'}")
    print(f"EMA({settings['fast']},{settings['slow']}) ATR(p={settings['atr_period']} min={settings['atr_min']}) "
          f"RSI(p={settings['rsi_period']} ob={settings['rsi_overbought']} os={settings['rsi_oversold']})")
    print(f"Leverage schedule={settings['leverage_schedule']} default={settings['leverage_default']}")
    if use_mtf:
        print(f"MTF gate: 5m trigger with 20m EMA-{settings['htf_ema']} bias={settings['htf_bias']}")

    last_t = None
    cooldown_left = 0

    while True:
        try:
            # --- Fetch 5m candles (ASC) ---
            c5 = coinbase_fetch_candles(PRODUCT, granularity_sec=300)
            if not c5 or len(c5) < 60:
                time.sleep(1.0); continue

            # Confirm-on-close: act only once per new 5m bar
            t = latest_closed_t(c5)
            if CONFIRM and last_t == t:
                time.sleep(0.5); continue

            # Optional cooldown bars after each trade signal
            if cooldown_left > 0:
                cooldown_left -= 1
                last_t = t
                time.sleep(0.5); continue

            closes5 = [x["c"] for x in c5]
            highs5  = [x["h"] for x in c5]
            lows5   = [x["l"] for x in c5]

            if use_mtf:
                c20 = resample_5m_to_20m(c5)
                closes20 = [x["c"] for x in c20]
                sig = strat.generate_signal(closes5, highs5, lows5, htf_closes=closes20)
            else:
                sig = strat.generate_signal(closes5, highs5, lows5)

            px = closes5[-1]
            lev = getattr(strat, "last_leverage", None)
            stop = getattr(strat, "stop", None)
            take = getattr(strat, "take", None)

            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts} | {PRODUCT} | sig={sig:>4} | px={fmt(px)} | lev={lev}x | stop={fmt(stop)} | take={fmt(take)}")

            if sig in ("buy", "sell"):
                cooldown_left = int(os.getenv("COOLDOWN_BARS", "3"))
                if TRADING_ENABLED:
                    # >>> PLACE ORDER HERE <<<
                    # NOTE: Coinbase spot doesn't support leverage. If you trade futures/margin,
                    # use the venue's API and pass `lev` to the order params accordingly.
                    print(f"EXECUTE: {sig.upper()} {PRODUCT} @ {fmt(px)} | lev={lev}x | stop={fmt(stop)} | take={fmt(take)}")
                else:
                    print("DRY-RUN: trading disabled (SCOUTFIRE_TRADING_ENABLED=0)")

            last_t = t
            time.sleep(0.8)

        except (HTTPError, URLError) as e:
            print("HTTP error:", e)
            time.sleep(2.0)
        except KeyboardInterrupt:
            print("\nStopping…")
            break
        except Exception as e:
            print("Loop error:", repr(e))
            time.sleep(1.0)


if __name__ == "__main__":
    main()
