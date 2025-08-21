# engine/risk.py
from dataclasses import dataclass

@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01       # 1% of balance
    max_daily_loss: float = 0.05       # 5% of balance
    max_positions: int = 3
    min_rrr: float = 1.5               # Reject if reward/risk < 1.5

class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.daily_loss = 0.0
        self.daily_start_balance = None

    def reset_daily(self, balance: float):
        self.daily_start_balance = balance
        self.daily_loss = 0.0

    def check_daily_limit(self, balance: float) -> bool:
        """Stop trading if daily losses exceed threshold."""
        if self.daily_start_balance is None:
            self.reset_daily(balance)
        allowed_loss = self.config.max_daily_loss * self.daily_start_balance
        current_loss = self.daily_start_balance - balance
        return current_loss <= allowed_loss

    def compute_position(
        self,
        balance: float,
        entry: float,
        stop: float,
        take_profit: float,
        side: str = "long",
        leverage: int = 1
    ):
        """
        Returns position size & trade plan, or None if invalid.
        Supports leverage.
        """
        if stop <= 0 or entry <= 0 or take_profit <= 0:
            return None

        # Risk per trade in $ terms
        capital_at_risk = balance * self.config.risk_per_trade

        # Price risk
        if side == "long":
            risk_per_unit = entry - stop
            reward_per_unit = take_profit - entry
        else:  # short
            risk_per_unit = stop - entry
            reward_per_unit = entry - take_profit

        if risk_per_unit <= 0 or reward_per_unit <= 0:
            return None

        # RRR check
        rrr = reward_per_unit / risk_per_unit
        if rrr < self.config.min_rrr:
            return None

        # Adjust size for leverage
        effective_risk = risk_per_unit / entry
        size = (capital_at_risk * leverage) / (entry * effective_risk)

        target_price = take_profit

        return {
            "side": side,
            "entry": entry,
            "stop": stop,
            "target": target_price,
            "size": size,
            "leverage": leverage,
            "rrr": rrr
        }
