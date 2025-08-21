# strategy/ema_atr_trend_mtf.py
from typing import Sequence, Mapping, Any
import numpy as np
from strategy.base import Strategy
from strategy.ema_atr_trend import EmaAtrTrend
from utils.indicators import ema

class EmaAtrTrendMTF(Strategy):
    """
    5m EMA+ATR+RSI entries, only allowed if 20m regime filter passes.
    Forwards all settings (including leverage schedule) to the core strategy.
    """

    def __init__(self, settings: Mapping[str, Any] | None = None):
        s = settings or {}
        self.core = EmaAtrTrend(s)  # forwards EMA/ATR/RSI + leverage config
        self.htf_ema = int(s.get("htf_ema", 200))
        self.htf_bias = str(s.get("htf_bias", "follow")).lower()

    def _htf_allows(self, htf_closes: Sequence[float], side: str) -> bool:
        if self.htf_bias == "long_only":
            return side == "long"
        if self.htf_bias == "short_only":
            return side == "short"

        h = np.asarray(htf_closes, dtype=float)
        if len(h) < self.htf_ema + 1:
            return False
        e = ema(h, self.htf_ema)
        if np.isnan(e[-1]):
            return False
        return (h[-1] > e[-1]) if side == "long" else (h[-1] < e[-1])

    def generate_signal(
        self,
        ltf_closes: Sequence[float],
        highs: Sequence[float] | None = None,
        lows:  Sequence[float] | None = None,
        htf_closes: Sequence[float] | None = None,
        **kwargs
    ) -> str:
        if not htf_closes:
            return "hold"

        sig = self.core.generate_signal(ltf_closes, highs=highs, lows=lows)
        if sig == "buy":
            return "buy" if self._htf_allows(htf_closes, "long") else "hold"
        if sig == "sell":
            return "sell" if self._htf_allows(htf_closes, "short") else "hold"
        return "hold"

    # pass-through info your runner may use
    @property
    def position(self): return self.core.position
    @property
    def stop(self):     return self.core.stop
    @property
    def take(self):     return self.core.take
    @property
    def last_leverage(self): return self.core.last_leverage
    @property
    def trade_count(self):   return self.core.trade_count
