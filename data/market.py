# scoutfire/data/market.py
import logging
import math
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

class MarketData:
    """Fetch OHLCV candles. Tries a public endpoint; falls back to synthetic data for dev speed."""

    @staticmethod
    def fetch(pair: str, interval: str, lookback_days: int) -> pd.DataFrame:
        try:
            df = MarketData._fetch_public_klines(pair, interval, lookback_days)
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            log.warning(f"Public fetch failed: {e}")
        log.info("Using synthetic price data fallback.")
        return MarketData.synthetic(lookback_days, interval)

    @staticmethod
    def _fetch_public_klines(pair: str, interval: str, lookback_days: int) -> Optional[pd.DataFrame]:
        # Simple Binance-style public endpoint (pair like BTCUSDT)
        symbol = pair.replace("/", "")
        interval_map = {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d"}
        iv = interval_map.get(interval, "1h")
        limit = min(1500, lookback_days * (24 if "h" in iv else 1))
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={iv}&limit={limit}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        raw = r.json()
        cols = ["open_time","open","high","low","close","volume","close_time","qav","n","tbbav","tbqav","ignore"]
        df = pd.DataFrame(raw, columns=cols)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        df = df[["open_time","open","high","low","close","volume","close_time"]]
        df.rename(columns={"open_time":"time"}, inplace=True)
        return df

    @staticmethod
    def synthetic(lookback_days: int, interval: str) -> pd.DataFrame:
        steps_per_day = {"1m":1440, "5m":288, "15m":96, "1h":24, "4h":6, "1d":1}.get(interval, 24)
        n = max(steps_per_day, lookback_days * steps_per_day)
        t0 = datetime.utcnow() - timedelta(days=lookback_days)
        price = 30_000.0
        rows: List[Dict] = []
        step_minutes = 1440 // max(1, steps_per_day)
        for i in range(n):
            drift = 0.0001
            shock = random.gauss(0, 0.01)
            price *= math.exp(drift + shock)
            open_ = price * (1 - random.random()*0.003)
            close = price * (1 + random.random()*0.003)
            high = max(open_, close) * (1 + random.random()*0.002)
            low  = min(open_, close) * (1 - random.random()*0.002)
            vol  = abs(random.gauss(15, 5))
            rows.append({
                "time": t0 + timedelta(minutes=i * step_minutes),
                "open": open_, "high": high, "low": low, "close": close, "volume": vol
            })
        return pd.DataFrame(rows)
