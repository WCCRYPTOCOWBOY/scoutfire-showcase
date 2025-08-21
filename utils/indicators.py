# utils/indicators.py
# Core technical indicators for Scoutfire.
# NumPy only. All outputs are np.ndarray and align 1:1 with input length,
# using NaNs during warm-up so downstream logic can safely gate on np.isnan.

from __future__ import annotations
import numpy as np


# ---------- helpers ----------

def _as_1d_float(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        a = a.reshape(-1)
    return a


# ---------- moving averages ----------

def sma(prices, period: int) -> np.ndarray:
    """Simple Moving Average (SMA)."""
    p = _as_1d_float(prices)
    n = len(p)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period:
        return out
    csum = np.cumsum(p, dtype=float)
    out[period - 1] = csum[period - 1] / period
    for i in range(period, n):
        out[i] = (csum[i] - csum[i - period]) / period
    return out


def ema(prices, period: int) -> np.ndarray:
    """Exponential Moving Average (EMA), seeded with SMA."""
    p = _as_1d_float(prices)
    n = len(p)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    # seed with SMA
    seed = np.mean(p[:period])
    out[period - 1] = seed
    for i in range(period, n):
        out[i] = alpha * p[i] + (1.0 - alpha) * out[i - 1]
    return out


# ---------- volatility & ranges ----------

def atr(high, low, close, period: int = 14) -> np.ndarray:
    """
    Wilder's Average True Range (ATR).
    TR = max( high-low, |high-prev_close|, |low-prev_close| )
    Returns NaNs until enough data to seed smoothing.
    """
    h = _as_1d_float(high)
    l = _as_1d_float(low)
    c = _as_1d_float(close)
    n = len(c)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period + 1:
        return out

    tr = np.full(n, np.nan, dtype=float)
    for i in range(1, n):
        hl = h[i] - l[i]
        hc = abs(h[i] - c[i - 1])
        lc = abs(l[i] - c[i - 1])
        tr[i] = max(hl, hc, lc)

    # seed with simple mean of the first 'period' TRs
    out[period] = np.nanmean(tr[1:period + 1])
    # Wilder smoothing
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def rolling_std_returns(prices, window: int = 20) -> np.ndarray:
    """
    Rolling std-dev of simple returns r_t = (p_t - p_{t-1}) / p_{t-1}.
    Aligned to price index; first window entries are NaN.
    """
    p = _as_1d_float(prices)
    n = len(p)
    out = np.full(n, np.nan, dtype=float)
    if window <= 1 or n < window + 1:
        return out
    rets = np.diff(p) / p[:-1]
    # align: std at index i uses returns up to i-1
    for i in range(window, n):
        out[i] = np.std(rets[i - window:i], ddof=1)
    return out


# ---------- oscillators ----------

def rsi(prices, period: int = 14) -> np.ndarray:
    """
    Wilder's RSI. Returns 0..100 with NaNs during warm-up.
    """
    p = _as_1d_float(prices)
    n = len(p)
    out = np.full(n, np.nan, dtype=float)
    if period <= 0 or n < period + 1:
        return out

    deltas = np.diff(p)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.full(n, np.nan, dtype=float)
    avg_loss = np.full(n, np.nan, dtype=float)

    # seed averages with simple means over first 'period'
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    # Wilder smoothing
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    rs = avg_gain / np.where(avg_loss == 0.0, np.nan, avg_loss)
    rsi_vals = 100.0 - (100.0 / (1.0 + rs))
    rsi_vals[:period] = np.nan
    return rsi_vals


# ---------- bands & quantiles ----------

def rolling_quantiles(series, window: int = 100, low_q: float = 0.2, high_q: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """
    Rolling lower/upper quantiles (e.g., for dynamic RSI bands).
    Returns two arrays aligned with input (NaNs until warm-up).
    """
    x = _as_1d_float(series)
    n = len(x)
    ql = np.full(n, np.nan, dtype=float)
    qh = np.full(n, np.nan, dtype=float)
    if window <= 1 or n < window:
        return ql, qh
    for i in range(window, n):
        w = x[i - window:i]
        ql[i] = np.nanquantile(w, low_q)
        qh[i] = np.nanquantile(w, high_q)
    return ql, qh


def bollinger_bands(prices, period: int = 20, num_std: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Classic Bollinger Bands using SMA ± num_std * rolling std-dev.
    Returns (mid, upper, lower), all aligned with input (NaNs during warm-up).
    """
    p = _as_1d_float(prices)
    n = len(p)
    mid = sma(p, period)
    up = np.full(n, np.nan, dtype=float)
    lo = np.full(n, np.nan, dtype=float)
    if period <= 1 or n < period:
        return mid, up, lo

    # rolling std
    # compute via cumulative sums for speed would require squares; keep simple/clear:
    for i in range(period - 1, n):
        w = p[i - period + 1:i + 1]
        sd = np.std(w, ddof=1)
        up[i] = mid[i] + num_std * sd
        lo[i] = mid[i] - num_std * sd
    return mid, up, lo
