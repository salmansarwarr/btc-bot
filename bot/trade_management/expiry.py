"""
expiry.py — Time-expiry checks
================================

**Spec reference:** Doc-1 §6.x; Doc-3 check_time_expiry pseudocode.
Resolution I-5: HTF_SWING branch uses EXPIRY_HTF_BASE_BARS × EXPIRY_HTF_MULTIPLIER (8×8=64 bars).
Resolution I-6: expiry_tightened flag prevents double-tightening.
Resolution III-5: approaching_target used to suppress HTF_SWING expiry close.
"""
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime

from bot.structs import TradeState, SetupClass, Direction, EventType
from bot.config import (
    EXPIRY_TRAP_BARS,
    EXPIRY_TRAP_ATR_MULT,
    EXPIRY_CONTINUATION_BARS,
    EXPIRY_CONTINUATION_ATR_MULT,
    EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT,
    EXPIRY_HTF_BASE_BARS,
    EXPIRY_HTF_MULTIPLIER,
    APPROACHING_TARGET_THRESHOLD,
)
from bot.trade_management.actions import close_trade

logger = logging.getLogger(__name__)

def approaching_target(trade: TradeState, current_price: float) -> bool:
    """Check if price is >= 60% of the way to the final target."""
    if not trade.targets:
        return False
        
    final_target = trade.targets[-1]
    total_dist = abs(final_target - trade.entry_price)
    if total_dist == 0:
        return False
        
    covered_dist = 0.0
    if trade.direction == Direction.UP:
        if current_price < trade.entry_price:
            return False
        covered_dist = current_price - trade.entry_price
    else:
        if current_price > trade.entry_price:
            return False
        covered_dist = trade.entry_price - current_price
        
    return (covered_dist / total_dist) >= APPROACHING_TARGET_THRESHOLD


def check_time_expiry(
    trade: TradeState,
    current_price: float,
    current_bar_index: int,
    atr: float,
    now: Optional[datetime] = None,
    journal: Optional[list] = None,
) -> None:
    if not trade.is_open:
        return
        
    bars = trade.bars_in_trade
    
    if trade.setup_class == SetupClass.TRAP:
        if bars >= EXPIRY_TRAP_BARS:
            dist_moved = abs(current_price - trade.entry_price)
            if dist_moved < EXPIRY_TRAP_ATR_MULT * atr:
                logger.info("Trade %s expired (TRAP). Closing.", trade.id)
                close_trade(trade, current_price, now)
                if journal is not None:
                    from bot.journaling.writer import log_event
                    log_event(EventType.EXPIRY_CLOSE, {"reason": "TRAP_no_movement", "bars": bars}, journal, trade, now)
                
    elif trade.setup_class == SetupClass.CONTINUATION:
        dist_moved = abs(current_price - trade.entry_price)
        is_stalling = dist_moved < EXPIRY_CONTINUATION_ATR_MULT * atr
        
        if bars >= EXPIRY_CONTINUATION_BARS and is_stalling:
            if not trade.expiry_tightened:
                # Issue warning and tighten
                offset = EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT * atr
                if trade.direction == Direction.UP:
                    new_stop = trade.entry_price - offset
                    trade.stop_price = max(trade.stop_price, new_stop)
                else:
                    new_stop = trade.entry_price + offset
                    trade.stop_price = min(trade.stop_price, new_stop)
                trade.expiry_tightened = True
                logger.info("Trade %s expiry tightened (CONTINUATION).", trade.id)
                if journal is not None:
                    from bot.journaling.writer import log_event
                    log_event(EventType.STOP_MOVED, {"reason": "expiry_tightened", "new_stop": trade.stop_price, "bars": bars}, journal, trade, now)
            else:
                # Already tightened in a prior bar, and still stalling -> close
                logger.info("Trade %s expired (CONTINUATION). Closing.", trade.id)
                close_trade(trade, current_price, now)
                if journal is not None:
                    from bot.journaling.writer import log_event
                    log_event(EventType.EXPIRY_CLOSE, {"reason": "CONTINUATION_stall", "bars": bars}, journal, trade, now)
                
    elif trade.setup_class == SetupClass.HTF_SWING:
        max_bars = EXPIRY_HTF_BASE_BARS * EXPIRY_HTF_MULTIPLIER
        if bars >= max_bars:
            if not approaching_target(trade, current_price):
                logger.info("Trade %s expired (HTF_SWING). Closing.", trade.id)
                close_trade(trade, current_price, now)
                if journal is not None:
                    from bot.journaling.writer import log_event
                    log_event(EventType.EXPIRY_CLOSE, {"reason": "HTF_SWING_max_bars", "bars": bars}, journal, trade, now)
