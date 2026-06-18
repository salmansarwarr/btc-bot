"""
stalling.py — Stalling and re-entry detection
==============================================

**Spec reference:** Doc-1 §5.x; Doc-3 check_stalling pseudocode.
Resolution II-7: TRAP-class re-entry branch; trap_moved_away field; TRAP_REENTRY_ATR_MULT.
Resolution I-6: stall_band_counter maintained here.
"""
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime

from bot.structs import TradeState, SetupClass
from bot.config import STALL_ATR_MULT, TRAP_REENTRY_ATR_MULT, STALL_BARS
from bot.trade_management.actions import reduce_position

logger = logging.getLogger(__name__)


def check_stalling(trade: TradeState, current_price: float, atr: float, now: Optional[datetime] = None) -> None:
    """
    Check for stalling conditions and TRAP re-entry patterns.
    
    Proxy A (all setup classes):
      Increment trade.stall_band_counter if price within STALL_ATR_MULT × atr
      of the stall reference; reset to 0 if outside.
      When stall_band_counter >= STALL_BARS: set trade.stalling_flag = True,
      reduce position, log STALLING_FLAG event.

    Proxy C (TRAP class only — Resolution II-7):
      If distance_moved > STALL_ATR_MULT × atr: set trade.trap_moved_away = True.
      If trap_moved_away and price returns within TRAP_REENTRY_ATR_MULT × atr
      of pivot_used.price: reduce position 50%, set stalling_flag, log event.
    """
    if not trade.is_open:
        return
        
    # --- Proxy A: Stalling Band ------------------------------------------------
    # Stall reference is entry_price (as per general stalling rules)
    dist_from_entry = abs(current_price - trade.entry_price)
    
    if dist_from_entry <= STALL_ATR_MULT * atr:
        trade.stall_band_counter += 1
    else:
        trade.stall_band_counter = 0
        
    if trade.stall_band_counter >= STALL_BARS and not trade.stalling_flag:
        trade.stalling_flag = True
        logger.info("Trade %s stalled (Proxy A). Reducing position.", trade.id)
        # Assuming we reduce position by 50% on stall as per typical risk rules
        reduce_position(trade, current_price, fraction=0.5, now=now)
        
    # --- Proxy C: TRAP Re-entry (Resolution II-7) ------------------------------
    if trade.setup_class == SetupClass.TRAP and trade.pivot_used:
        was_moved_away = trade.trap_moved_away
        
        # Distance from entry
        if dist_from_entry > STALL_ATR_MULT * atr:
            trade.trap_moved_away = True
            
        if was_moved_away:
            dist_from_pivot = abs(current_price - trade.pivot_used.price)
            if dist_from_pivot <= TRAP_REENTRY_ATR_MULT * atr:
                if not trade.stalling_flag:
                    trade.stalling_flag = True
                    logger.info("TRAP trade %s re-entered trigger zone. Reducing position.", trade.id)
                    reduce_position(trade, current_price, fraction=0.5, now=now)
