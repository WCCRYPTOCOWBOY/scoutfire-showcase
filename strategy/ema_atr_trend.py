# strategy/ema_atr_trend.py
from typing import Sequence, Mapping, Any, List
import numpy as np
from strategy.base import Strategy
from utils.indicators import ema, atr, rsi


class EmaAtrTrend(Strategy):
    """
    EMA cross entries gated by ATR (vol) and filtered by RSI.
    Includes a leverage schedule for successive entries.

    Returns: "buy" | "sell" | "hold"

    Settings (all optional):
      fast=9, slow=21
      atr_period=14
      atr_min=0.002            # skip if ATR% < atr_min (too quiet)
      risk_atr=1.5             # stop distance in ATR units
      take_atr=2.0             # take-profit distance in ATR units (0 disables TP)
      direction="both"         # "long" | "short" | "both"

      rsi_period=14
      rsi_overbought=70.0      # block new longs if RSI >= this (minus buffer)
      rsi_oversold=30.0        # block new shorts if RSI <= this (plus buffer)
      rsi_buffer=1.0           # cushion to avoid flicker at thresholds

      leverage_schedule="10,10,8,7"   # first entries use these; sticks to last thereafter
      leverage_default=7.0            # fallback if schedule exhausted/invalid
      trade_count_start=0             # resume index for schedule
    """

    def __init__(self, settings: Mapping[str, Any] | None = None):
        s = settings or {}
        # ---- EMAs ----
        self.fast = int(s.get("fast", 9))
        self.slow = int(s.get("slow", 21))

        # ---- ATR / risk ----
        self.atr_period = int(s.get("atr_period", 14))
        self.atr_min = float(s.get("atr_min", 0.002))
        self.risk_atr = float(s.get("risk_atr", 1.5))
        self.take_atr = float(s.get("take_atr", 2.0))
        self.direction = str(s.get("direction", "both")).lower()

        # ---- RSI ----
        self.rsi_period = int(s.get("rsi_period", 14))
        self.rsi_overbought = float(s.get("rsi_overbought", 70.0))
        self.rsi_oversold   = float(s.get("rsi_oversold", 30.0))
        self.rsi_buffer     = float(s.get("rsi_buffer", 1.0))

        # ---- Leverage schedule ----
        raw_sched = s.get("leverage_schedule", "10,10,8,7")
        if isinstance(raw_sched, str):
            parts = [p.strip() for p in raw_sched.split(",") if p.strip()]
            try:
                self.leverage_schedule: List[float] = [float(p) for p in parts] if parts else [10, 10, 8, 7]
            except Exception:
                self.leverage_schedule = [10, 10, 8, 7]
        elif isinstance(raw_sched, (list, tuple)):
            try:
                self.leverage_schedule = [float(x) for x in raw_sched]
            except Exception:
                self.leverage_schedule = [10, 10, 8, 7]
        else:
            self.leverage_schedule = [10, 10, 8, 7]

        self.leverage_default = float(
            s.get("leverage_default", self.leverage_schedule[-1] if self.leverage_schedule else 7.0)
        )
        self.trade_count = int(s.get("trade_count_start", 0))
        self.last_leverage: float | None = None

        # ---- Position state (optional) ----
        self.position: str | None = None  # "long" | "short" | None
        self.entry: float | None = None
        self.stop:  float | None = None
        self.take:  float | None = None

    # ================== helpers ==================
    def _next_leverage(self) -> float:
        if self.leverage_schedule:
            idx = min(self.trade_count, len(self.leverage_schedule) - 1)
            return self.leverage_schedule[idx]
        return self.leverage_default

    def _reset_pos(self):
        self.position = None
        self.entry = None
        self.stop = None
        self.take = None

    def _enter_long(self, price: float, atr_now: float):
        self.last_leverage = self._next_leverage()
        self.trade_count += 1
        self.position = "long"
        self.entry = price
        self.stop = price - self.risk_atr * atr_now
        self.take = price + self.take_atr * atr_now if self.take_atr > 0 else None

    def _enter_short(self, price: float, atr_now: float):
        self.last_leverage = self._next_leverage()
        self.trade_count += 1
        self.position = "short"
        self.entry = price
        self.stop = price + self.risk_atr * atr_now
        self.take = price - self.take_atr * atr_now if self.take_atr > 0 else None

    # ================== main ==================
    def generate_signal(
        self,
        closes: Sequence[float],
        highs:  Sequence[float] | None = None,
        lows:   Sequence[float] | None = None,
        **kwargs
    ) -> str:
        c = np.asarray(closes, dtype=float)
        n = len(c)
        if n < max(self.slow, self.atr_period, self.rsi_period) + 2:
            return "hold"

        # EMAs
        ef = ema(c, self.fast)
        es = ema(c, self.slow)
        ef_now, ef_prev = ef[-1], ef[-2]
        es_now, es_prev = es[-1], es[-2]
        if np.isnan([ef_now, ef_prev, es_now, es_prev]).any():
            return "hold"

        # ATR (use close for H/L if not supplied)
        if highs is None or lows is None:
            h = c
            l = c
        else:
            h = np.asarray(highs, dtype=float)
            l = np.asarray(lows,  dtype=float)

        a = atr(h, l, c, self.atr_period)
        atr_now = a[-1]
        if np.isnan(atr_now) or c[-1] <= 0:
            return "hold"

        # Skip dead markets
        atr_pct = atr_now / c[-1]
        if atr_pct < self.atr_min:
            return "hold"

        # RSI filter
        r_now = rsi(c, self.rsi_period)[-1]
        if np.isnan(r_now):
            return "hold"
        ob = self.rsi_overbought - self.rsi_buffer
        os = self.rsi_oversold   + self.rsi_buffer

        # Cross logic
        cross_up   = (ef_prev <= es_prev) and (ef_now > es_now)
        cross_down = (ef_prev >= es_prev) and (ef_now < es_now)

        # Exits for open positions
        if self.position == "long":
            if c[-1] <= self.stop or (self.take and c[-1] >= self.take):
                self._reset_pos()
        elif self.position == "short":
            if c[-1] >= self.stop or (self.take and c[-1] <= self.take):
                self._reset_pos()

        # Entries with RSI guardrails + direction
        if cross_up and self.direction in ("long", "both") and r_now < ob:
            self._enter_long(c[-1], atr_now)
            return "buy"

        if cross_down and self.direction in ("short", "both") and r_now > os:
            self._enter_short(c[-1], atr_now)
            return "sell"

        return "hold"
