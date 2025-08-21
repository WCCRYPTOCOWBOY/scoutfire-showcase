# scoutfire/strategy/sma_cross.py
import pandas as pd

def generate_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> str:
    df = df.copy()
    df["sma_fast"] = df["close"].rolling(fast).mean()
    df["sma_slow"] = df["close"].rolling(slow).mean()
    if len(df) < slow + 1:
        return "HOLD"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev.sma_fast <= prev.sma_slow and last.sma_fast > last.sma_slow:
        return "BUY"
    if prev.sma_fast >= prev.sma_slow and last.sma_fast < last.sma_slow:
        return "SELL"
    return "HOLD"
