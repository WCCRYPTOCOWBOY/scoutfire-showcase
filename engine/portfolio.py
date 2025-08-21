# scoutfire/engine/portfolio.py
from dataclasses import dataclass

@dataclass
class Portfolio:
    cash: float = 10_000.0          # starting cash (paper trading)
    position: float = 0.0           # units of the base asset (e.g., BTC)

    def value(self, price: float) -> float:
        """Total equity = cash + (position * current price)."""
        return self.cash + self.position * price
