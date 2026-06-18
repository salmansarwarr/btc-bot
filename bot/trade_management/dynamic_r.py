"""
dynamic_r.py — Dynamic R-locking
===================================

**Spec reference:** Doc-3 check_dynamic_r pseudocode; Resolution III-4.
"""
from __future__ import annotations

import logging
from bot.structs import TradeState, Direction

logger = logging.getLogger(__name__)

def check_dynamic_r(trade: TradeState, current_price: float, atr: float) -> None:
    """
    When trade progress reaches 2R+, apply lock_in_1R_stop logic
    to trail the stop 1R behind the current price.
    Resolution III-4.
    """
    if not trade.is_open or trade.initial_position_size <= 0:
        return
        
    # Accurately compute 1R distance from risk sizing
    r_distance = trade.initial_risk_usd / trade.initial_position_size
    if r_distance <= 0:
        return
        
    if trade.direction == Direction.UP:
        current_r = (current_price - trade.entry_price) / r_distance
    else:
        current_r = (trade.entry_price - current_price) / r_distance
        
    if current_r >= 2.0:
        # Apply lock_in_1R_stop logic inline: trail stop 1R behind current price
        if trade.direction == Direction.UP:
            computed_stop = current_price - r_distance
            if computed_stop > trade.stop_price:
                trade.stop_price = computed_stop
                logger.info("Dynamic R-lock: Trade %s stop updated to %.2f (Current R: %.2f)", trade.id, trade.stop_price, current_r)
        else:
            computed_stop = current_price + r_distance
            if computed_stop < trade.stop_price:
                trade.stop_price = computed_stop
                logger.info("Dynamic R-lock: Trade %s stop updated to %.2f (Current R: %.2f)", trade.id, trade.stop_price, current_r)
