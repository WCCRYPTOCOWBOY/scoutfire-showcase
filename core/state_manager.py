class StateManager:
    def __init__(self):
        self.trades_today = 0
        self.daily_loss_pct = 0.0
        self.locked_out = False

    def record_trade(self):
        """Increment trade count by 1"""
        self.trades_today += 1

    def update_loss(self, pct):
        """Adjust daily loss percentage by the given value"""
        self.daily_loss_pct += pct

    def check_lockout(self, max_trades, max_loss_pct):
        """Lock out trading if max trades or loss limit reached"""
        if self.trades_today >= max_trades or self.daily_loss_pct <= -max_loss_pct:
            self.locked_out = True
            print("🚫 Trading locked due to risk controls.")

    def reset_day(self):
        """Reset daily counters"""
        self.trades_today = 0
        self.daily_loss_pct = 0.0
        self.locked_out = False