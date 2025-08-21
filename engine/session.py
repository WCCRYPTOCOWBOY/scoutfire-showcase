# engine/session.py

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Dict, Any
import json
import time as _time

PHX = ZoneInfo("America/Phoenix")

@dataclass
class TradeResult:
    filled_qty: float
    entry_price: float
    exit_price: float
    fees: float = 0.0

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.filled_qty - self.fees


class SessionManager:
    """
    Ladder session controller:
      • Trade window: 06:00–14:00 (America/Phoenix)
      • Leverage schedule: [10, 10, 8, 7]
      • Profit siphon: on win >= siphon_amount → move to 'vault', roll remainder
      • Dry-run guard + persisted JSON state
      • Optional JSONL telemetry logging
      • Daily loss helpers + manual stake setter
    """
    def __init__(
        self,
        leverage_plan = [10, 10, 8, 7],
        siphon_amount: float = 500.0,
        max_rounds: int = 4,
        tz = PHX,
        window_start: time = time(6, 0),
        window_end: time = time(14, 0),
        state_path: str = "scoutfire_session.json",
        log_path: Optional[str] = "scoutfire_rounds.jsonl",
        dry_run: bool = True,
        starting_stake_margin: float = 100.0,   # first trade "stake" (margin dollars)
    ):
        self.leverage_plan = leverage_plan
        self.siphon_amount = siphon_amount
        self.max_rounds = max_rounds
        self.tz = tz
        self.window_start = window_start
        self.window_end = window_end
        self.state_path = Path(state_path)
        self.log_path = Path(log_path) if log_path else None
        self.dry_run = dry_run

        self.round_idx = 0
        self.vault_bank = 0.0
        self.ladder_bank = starting_stake_margin

        # Optional daily guardrails (set via set_daily_limit)
        self.daily_start_balance: Optional[float] = None
        self.daily_loss: float = 0.0
        self.max_daily_loss_pct: Optional[float] = None

        self._load_state()

    # ---------- persistence ----------
    def _load_state(self):
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                self.round_idx   = data.get("round_idx", self.round_idx)
                self.vault_bank  = data.get("vault_bank", self.vault_bank)
                self.ladder_bank = data.get("ladder_bank", self.ladder_bank)
                self.daily_start_balance = data.get("daily_start_balance", self.daily_start_balance)
                self.daily_loss = data.get("daily_loss", self.daily_loss)
                self.max_daily_loss_pct = data.get("max_daily_loss_pct", self.max_daily_loss_pct)
            except Exception:
                # ignore corrupt state; start fresh
                pass

    def _save_state(self):
        data = {
            "round_idx": self.round_idx,
            "vault_bank": self.vault_bank,
            "ladder_bank": self.ladder_bank,
            "daily_start_balance": self.daily_start_balance,
            "daily_loss": self.daily_loss,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "timestamp": datetime.now(self.tz).isoformat(),
        }
        self.state_path.write_text(json.dumps(data, indent=2))

    # ---------- logging ----------
    def _log_event(self, event: str, payload: Dict[str, Any]):
        if not self.log_path:
            return
        rec = {
            "ts": _time.time(),
            "event": event,
            **payload,
            "snapshot": self.snapshot(),
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    # ---------- guards ----------
    def can_trade_now(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(self.tz)
        return self.window_start <= now.time() <= self.window_end

    def get_leverage(self) -> float:
        return self.leverage_plan[min(self.round_idx, len(self.leverage_plan)-1)]

    def is_session_complete(self) -> bool:
        return self.round_idx >= self.max_rounds

    def require_safe(self):
        if self.dry_run:
            raise RuntimeError("DRY_RUN is enabled. Flip to live intentionally after tests.")

    # alias for clarity in callers
    def require_live(self):
        self.require_safe()

    # Daily loss helpers (optional)
    def set_daily_limit(self, start_balance: float, max_daily_loss_pct: float) -> None:
        self.daily_start_balance = start_balance
        self.max_daily_loss_pct = max_daily_loss_pct
        self.daily_loss = 0.0
        self._save_state()

    def daily_limit_ok(self, current_balance: float) -> bool:
        if self.daily_start_balance is None or self.max_daily_loss_pct is None:
            return True
        dd = self.daily_start_balance - current_balance
        return dd <= (self.max_daily_loss_pct * self.daily_start_balance)

    # ---------- sizing helpers ----------
    def planned_stake_margin(self) -> float:
        return max(0.0, self.ladder_bank)

    def planned_notional(self, entry_price: float) -> float:
        return self.planned_stake_margin() * self.get_leverage()

    def planned_qty(self, entry_price: float) -> float:
        return 0.0 if entry_price <= 0 else self.planned_notional(entry_price) / entry_price

    def set_stake(self, stake_margin: float) -> None:
        """Manually override the ladder stake (e.g., after a deposit/withdrawal)."""
        self.ladder_bank = max(0.0, float(stake_margin))
        self._save_state()
        self._log_event("stake_set", {"stake_margin": self.ladder_bank})

    # ---------- lifecycle ----------
    def start_round(self):
        if self.is_session_complete():
            raise RuntimeError("Session complete. Reset before starting a new round.")
        if not self.can_trade_now():
            raise RuntimeError("Outside of 06:00–14:00 America/Phoenix.")
        self._save_state()
        self._log_event("round_start", {"round": self.round_idx + 1})

    def on_win(self, result: TradeResult):
        pnl = result.pnl
        if pnl >= self.siphon_amount:
            self.vault_bank += self.siphon_amount
            self.ladder_bank += (pnl - self.siphon_amount)
        else:
            self.ladder_bank += pnl
        self.round_idx += 1
        self._save_state()
        self._log_event("win", {"pnl": pnl})

    def on_loss(self, result: TradeResult):
        pnl = result.pnl  # negative
        self.ladder_bank = max(0.0, self.ladder_bank + pnl)
        # optional daily tally (can be integrated with portfolio balance if you pass it separately)
        self.daily_loss += abs(min(0.0, pnl))
        self.round_idx += 1
        self._save_state()
        self._log_event("loss", {"pnl": pnl})

    def reset_session(self, keep_vault=True, new_starting_stake: Optional[float] = None):
        self.round_idx = 0
        if not keep_vault:
            self.vault_bank = 0.0
        if new_starting_stake is not None:
            self.ladder_bank = max(0.0, new_starting_stake)
        self._save_state()
        self._log_event("session_reset", {"keep_vault": keep_vault, "new_stake": new_starting_stake})

    # ---------- export ----------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "round": self.round_idx + 1,
            "max_rounds": self.max_rounds,
            "leverage": self.get_leverage(),
            "ladder_bank": round(self.ladder_bank, 2),
            "vault_bank": round(self.vault_bank, 2),
            "dry_run": self.dry_run,
            "window": f"{self.window_start.strftime('%H:%M')}–{self.window_end.strftime('%H:%M')} {self.tz}",
            "daily_start_balance": self.daily_start_balance,
            "daily_loss": round(self.daily_loss, 2),
        }
