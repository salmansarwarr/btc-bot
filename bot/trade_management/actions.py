"""
actions.py — Helpers for mutating TradeState during active management.
"""
from datetime import datetime, timezone
from typing import Optional

from bot.structs import TradeState, PartialExitRecord

def close_trade(trade: TradeState, exit_price: float, now: Optional[datetime] = None) -> None:
    """Close the trade entirely."""
    if not trade.is_open:
        return
    trade.is_open = False
    trade.exit_price = exit_price  # stamp for journaling

    if trade.initial_risk_usd > 0 and trade.position_size > 0:
        if trade.direction and trade.direction.name == "UP":
            r_val = ((exit_price - trade.entry_price) * trade.position_size) / trade.initial_risk_usd
        else:
            r_val = ((trade.entry_price - exit_price) * trade.position_size) / trade.initial_risk_usd
        trade.realized_r += r_val

    trade.position_size = 0.0

def reduce_position(trade: TradeState, exit_price: float, fraction: float, now: Optional[datetime] = None) -> None:
    """Reduce position by a specific fraction of the *original* size."""
    if not trade.is_open or trade.position_size <= 0:
        return
        
    if now is None:
        now = datetime.now(timezone.utc)
        
    amount_to_close = trade.initial_position_size * fraction
    # Cap at remaining size
    amount_to_close = min(amount_to_close, trade.position_size)
    
    if amount_to_close <= 0:
        return
        
    r_val = 0.0
    if trade.initial_risk_usd > 0:
        if trade.direction and trade.direction.name == "UP":
            r_val = ((exit_price - trade.entry_price) * amount_to_close) / trade.initial_risk_usd
        else:
            r_val = ((trade.entry_price - exit_price) * amount_to_close) / trade.initial_risk_usd
            
    trade.position_size -= amount_to_close
    trade.realized_r += r_val
    
    trade.partials_taken.append(
        PartialExitRecord(
            bar_index=trade.bars_in_trade,
            timestamp=now,
            price=exit_price,
            fraction=fraction,
            r_realized=r_val
        )
    )
    
    if trade.position_size <= 1e-8:
        trade.is_open = False

def take_scheduled_partial(trade: TradeState, exit_price: float, now: Optional[datetime] = None) -> None:
    """Take the next scheduled partial exit."""
    if not trade.partials_scheduled:
        return
    
    fraction = trade.partials_scheduled.pop(0)
    reduce_position(trade, exit_price, fraction, now)

def compound_position(trade: TradeState) -> None:
    """
    Compound the position on FTA clean break.
    Per spec: Adds risk back to the position (dummy implementation here just logs or increases size).
    For now, we'll double the remaining position size to simulate compounding.
    """
    if not trade.is_open:
        return
    trade.position_size *= 1.5  # Simple compounding simulation
