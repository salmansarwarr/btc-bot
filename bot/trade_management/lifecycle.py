"""
lifecycle.py — Per-bar trade update orchestrator
=================================================

**Spec reference:** Doc-3 main update loop.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional
from datetime import datetime

from bot.structs import TradeState, EventType
from bot.trade_management.stalling import check_stalling
from bot.trade_management.fta_handler import check_fta_interaction
from bot.trade_management.dynamic_r import check_dynamic_r
from bot.trade_management.expiry import check_time_expiry

logger = logging.getLogger(__name__)

# Map lifecycle action strings → EventType for journaling
_ACTION_TO_EVENT = {
    "PARTIAL":   EventType.PARTIAL_EXIT,
    "COMPOUND":  EventType.FTA_BREAK_COMPOUND,
    "TIGHTEN":   EventType.STOP_MOVED,
    "CLOSE":     EventType.FULL_EXIT,
}


def update_trade(
    trade: TradeState,
    current_price: float,
    current_bar_index: int,
    atr: float,
    now: Optional[datetime] = None,
    journal: Optional[List] = None,
    portfolio=None,          # PortfolioState — used by log_trade_closed on final close
    event_journal: Optional[List] = None,   # receives interim EventType records
) -> List[Dict[str, str]]:
    """
    Single entry point called once per bar for each open trade.
    Dispatches in order:
      0. Stop-loss check
      1. check_stalling
      2. check_fta_interaction
      3. check_dynamic_r
      4. check_time_expiry

    Returns a list of {action, reason} dicts.
    If journal/portfolio are supplied, emits log_trade_closed on final close
    and log_event for every intermediate action.
    """
    if not trade.is_open:
        return []

    events = []

    initial_open = trade.is_open
    initial_size = trade.position_size
    initial_stop = trade.stop_price

    # ── 0. Stop-loss ────────────────────────────────────────────────────────
    from bot.trade_management.actions import close_trade
    from bot.structs import Direction
    if trade.direction == Direction.UP and current_price <= trade.stop_price:
        close_trade(trade, trade.stop_price, now)
        events.append({"action": "CLOSE", "reason": "stop_loss"})
        trade.bars_in_trade += 1
        _flush_events(events, trade, journal, event_journal, portfolio, now)
        return events
    elif trade.direction == Direction.DOWN and current_price >= trade.stop_price:
        close_trade(trade, trade.stop_price, now)
        events.append({"action": "CLOSE", "reason": "stop_loss"})
        trade.bars_in_trade += 1
        _flush_events(events, trade, journal, event_journal, portfolio, now)
        return events

    # ── 1. Stalling ─────────────────────────────────────────────────────────
    check_stalling(trade, current_price, atr, now)
    if not trade.is_open and initial_open:
        events.append({"action": "CLOSE", "reason": "stalling_close"})
        trade.bars_in_trade += 1
        _flush_events(events, trade, journal, event_journal, portfolio, now)
        return events
    elif trade.position_size < initial_size:
        events.append({"action": "PARTIAL", "reason": "stalling_cut"})
        initial_size = trade.position_size

    # ── 2. FTA Interaction ──────────────────────────────────────────────────
    check_fta_interaction(trade, current_price, atr, now)
    if not trade.is_open and initial_open:
        events.append({"action": "CLOSE", "reason": "fta_rejection"})
        trade.bars_in_trade += 1
        _flush_events(events, trade, journal, event_journal, portfolio, now)
        return events
    elif trade.position_size > initial_size:
        events.append({"action": "COMPOUND", "reason": "fta_break"})
        initial_size = trade.position_size
    elif trade.position_size < initial_size:
        events.append({"action": "PARTIAL", "reason": "fta_partial"})
        initial_size = trade.position_size

    # ── 3. Dynamic R ────────────────────────────────────────────────────────
    check_dynamic_r(trade, current_price, atr)
    if trade.stop_price != initial_stop:
        events.append({"action": "TIGHTEN", "reason": "dynamic_r_lock"})
        initial_stop = trade.stop_price

    # ── 4. Time Expiry ──────────────────────────────────────────────────────
    check_time_expiry(trade, current_price, current_bar_index, atr, now, journal=event_journal)
    if not trade.is_open and initial_open:
        events.append({"action": "CLOSE", "reason": "time_expiry"})
        trade.bars_in_trade += 1
        _flush_events(events, trade, journal, event_journal, portfolio, now)
        return events
    elif trade.stop_price != initial_stop:
        events.append({"action": "TIGHTEN", "reason": "expiry_warning"})
        initial_stop = trade.stop_price

    # ── 5. Increment bar counter ────────────────────────────────────────────
    trade.bars_in_trade += 1

    if not events:
        events.append({"action": "HOLD", "reason": "no_trigger"})

    # Emit interim journal events (non-close actions)
    _flush_events(events, trade, journal, event_journal, portfolio, now)
    return events


# ─────────────────────────────────────────────────────────────────────────────

def _flush_events(
    events: List[Dict],
    trade: TradeState,
    journal: Optional[List],
    event_journal: Optional[List],
    portfolio,
    now: Optional[datetime],
) -> None:
    """
    After each dispatch round, write journal entries for each action.
    - CLOSE → log_trade_closed (final TradeJournalEntry)
    - Others → log_event (interim EventType record)
    """
    from bot.journaling.writer import log_event, log_trade_closed

    for ev in events:
        action = ev["action"]
        reason = ev["reason"]

        if action == "CLOSE" and journal is not None and portfolio is not None:
            exit_price = trade.exit_price if trade.exit_price != 0.0 else trade.entry_price
            log_trade_closed(trade, portfolio, exit_price, now or datetime.utcnow(), journal)
        elif action != "HOLD" and event_journal is not None:
            event_type = _ACTION_TO_EVENT.get(action, EventType.SKIPPED)
            log_event(
                event_type,
                {"reason": reason, "price": getattr(trade, "entry_price", 0)},
                event_journal,
                trade,
                now,
            )
