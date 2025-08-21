# engine/trader.py

from typing import Tuple, Dict, Any
from engine.session import SessionManager, TradeResult
from engine.risk import RiskManager, RiskError

def compute_qty_with_caps(session: SessionManager, entry: float) -> float:
    """Stake-based qty from ladder plan."""
    return session.planned_qty(entry)

def preflight(session: SessionManager) -> Tuple[bool, str]:
    if not session.can_trade_now():
        return False, "window_closed"
    return True, "ok"

def run_one_round(
    session: SessionManager,
    risk: RiskManager,
    *,
    symbol: str,
    side: str,                 # "long" or "short"
    entry_price: float,
    stop_price: float | None,  # None → ATR-based in RiskManager
    rr: float | None = None,   # None → use cfg.tp_rr
    ohlc=None                  # iterable of (high, low, close) if stop_price is None
) -> Dict[str, Any]:
    """
    Draft a trade idea with RiskManager, cap by ladder stake, then simulate or place live.
    """
    ok, reason = preflight(session)
    if not ok:
        return {"status": "skipped", "reason": reason, "snapshot": session.snapshot()}

    session.start_round()

    # TEMPORARILY apply per-round leverage by adjusting the cap
    prev_max_lev = risk.cfg.max_leverage
    per_round_lev = session.get_leverage()
    risk.cfg.max_leverage = per_round_lev

    try:
        # Ask RiskManager for idea (will raise RiskError if rr < min_rrr)
        idea = risk.suggest_trade(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            ohlc=ohlc,
            rr=rr
        )

        # Ladder stake qty vs risk-sized qty
        qty_stake = compute_qty_with_caps(session, entry_price)
        qty_final = min(qty_stake, idea["qty"])

        if qty_final <= 0:
            return {"status": "skipped", "reason": "qty_zero_after_caps", "snapshot": session.snapshot()}

        # --------- EXECUTION PATHS ----------
        if session.dry_run:
            # simulate a take-profit hit for illustration
            fill = TradeResult(
                filled_qty=qty_final,
                entry_price=entry_price,
                exit_price=idea["take_profit"],
                fees=0.0
            )
            session.on_win(fill)
            return {
                "status": "simulated_win",
                "qty": qty_final,
                "idea": idea,
                "snapshot": session.snapshot(),
            }
        else:
            session.require_safe()
            # TODO: send live order(s) with your broker client here (OCO: TP + SL)
            # On exit, compute PnL & fees then call:
            # session.on_win(fill)  or  session.on_loss(fill)
            return {"status": "live_trade_sent", "qty": qty_final, "idea": idea, "snapshot": session.snapshot()}
    except RiskError as e:
        return {"status": "skipped", "reason": f"risk_error:{e}", "snapshot": session.snapshot()}
    finally:
        # restore original leverage cap
        risk.cfg.max_leverage = prev_max_lev
