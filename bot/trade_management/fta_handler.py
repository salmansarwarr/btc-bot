"""
fta_handler.py — FTA interaction and pending confirmation expiry
================================================================

**Spec reference:** Doc-1 §5.x; Doc-3 check_fta_interaction,
                   check_pending_fta_confirmations pseudocode.
Resolution I-3: AGGRESSIVE mode clarification comment (frequency, not confidence).
Resolution II-12: FTA break → skip scheduled partial (already in Doc-3, no gap).
Resolution III-1: MAX_PENDING_AGE_BARS expiry for pending setups.
"""
from __future__ import annotations

import logging
from typing import List
from datetime import datetime

from bot.structs import TradeState, PendingFTAConfirmation, ManagementMode, Direction
from bot.config import BREAK_CLOSE_BEYOND_ATR_MULT, MAX_PENDING_AGE_BARS
from bot.trade_management.actions import close_trade, take_scheduled_partial, compound_position

logger = logging.getLogger(__name__)


def check_fta_interaction(trade: TradeState, current_price: float, atr: float, now: datetime = None) -> None:
    """
    Called each bar to handle interaction with the First Target Area (FTA).
    
    FTA reached:
      - Clean break → compound_position; skip scheduled partial for this FTA (II-12).
      - AGGRESSIVE + rejection → close trade (faster exit).
        NOTE (I-3): Aggressive refers to trading frequency — it triggers BOTH
        faster exits (FTA reject) AND faster adds (FTA break).
      - CONSERVATIVE + rejection → take scheduled partial only.
    """
    if not trade.is_open or not trade.targets:
        return
        
    if trade.current_target_index >= len(trade.targets):
        return
        
    target = trade.targets[trade.current_target_index]
    
    # Check if target is reached
    is_reached = False
    if trade.direction == Direction.UP and current_price >= target:
        is_reached = True
    elif trade.direction == Direction.DOWN and current_price <= target:
        is_reached = True
        
    if not is_reached:
        return

    # Determine if it's a clean break or a rejection
    offset = BREAK_CLOSE_BEYOND_ATR_MULT * atr
    is_clean_break = False
    
    if trade.direction == Direction.UP:
        if current_price >= target + offset:
            is_clean_break = True
    else:
        if current_price <= target - offset:
            is_clean_break = True
            
    if is_clean_break:
        logger.info("FTA cleanly broken for trade %s at %.2f", trade.id, current_price)
        
        # FTA cleanly broken → SKIP scheduled partial for this FTA (II-12)
        if trade.partials_scheduled:
            trade.partials_scheduled.pop(0)
            
        if trade.management_mode == ManagementMode.AGGRESSIVE:
            # Aggressive: faster adds
            compound_position(trade)
            
    else:
        logger.info("FTA rejected for trade %s at %.2f", trade.id, current_price)
        if trade.management_mode == ManagementMode.AGGRESSIVE:
            # Aggressive: faster exits
            close_trade(trade, current_price, now)
        else:
            # Conservative: take scheduled partial only
            take_scheduled_partial(trade, current_price, now)

    # Advance to the next target
    trade.current_target_index += 1


def check_pending_fta_confirmations(
    pending_list: List[PendingFTAConfirmation],
    current_bar_index: int,
) -> None:
    """
    Check pending FTA confirmations for timeouts.
    Resolution III-1: Expire after MAX_PENDING_AGE_BARS.
    """
    for pending in pending_list:
        if current_bar_index - pending.created_bar_index > MAX_PENDING_AGE_BARS:
            logger.info("Pending FTA confirmation expired for candidate %s", pending.candidate.id)
            # Mark as expired or remove (caller should filter these out)
