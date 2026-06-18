"""
writer.py — Journal write functions
=====================================

**Spec reference:** Doc-3 §5.x; Resolution I-8, II-4.

Public API
----------
log_trade_closed(trade, portfolio, exit_price, exit_timestamp, journal) -> TradeJournalEntry
    Build and persist a TradeJournalEntry.
    Populates cdc_qualifies_zero_tolerance for CDC/PATTERN_FAILURE setups (II-4).

log_skipped_setup(candidate, reason, journal, now) -> SkippedSetupLogEntry
    Build and persist a SkippedSetupLogEntry.
    reason examples: "RELATIVE_STRENGTH_FILTER" (I-8), "HEAT_CAP", "LOW_CONVICTION".

log_event(event_type, payload, journal, trade, now) -> None
    Append an interim lifecycle event to the audit trail.

All three functions write to a caller-supplied ``journal`` list (an in-memory
audit log). Callers can persist the list to disk/DB externally.
The functions also emit structured log records at INFO level.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bot.structs import (
    TradeState, PortfolioState, SetupCandidate,
    TradeJournalEntry, SkippedSetupLogEntry, EventType,
    SetupType, DrawdownTier,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_CDC_TYPES = {SetupType.CDC, SetupType.PATTERN_FAILURE}

def _cdc_zero_tolerance(trade: TradeState) -> Optional[bool]:
    """
    Resolution II-4: True if the CDC/PF entry had no wick contact with the level
    (i.e. the entry candle body respected the level with zero tolerance).
    We check whether the candidate's cdc_qualifies_zero_tolerance flag was set.
    For non-CDC setups, returns None.
    """
    if trade.setup_type not in _CDC_TYPES:
        return None
    # The flag was stored on the SetupCandidate; TradeState copies it at build time
    # if the field was added. Fall back to None (unknown) if missing.
    return getattr(trade, "cdc_qualifies_zero_tolerance", None)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def log_trade_closed(
    trade: TradeState,
    portfolio: PortfolioState,
    exit_price: float,
    exit_timestamp: datetime,
    journal: List[TradeJournalEntry],
) -> TradeJournalEntry:
    """
    Build and append a TradeJournalEntry when a trade fully closes.
    Populates cdc_qualifies_zero_tolerance for CDC/PATTERN_FAILURE setups (II-4).
    """
    entry = TradeJournalEntry(
        trade_id=trade.id,
        asset=trade.asset,
        timeframe=trade.timeframe or "",
        setup_type=trade.setup_type,
        setup_class=trade.setup_class,
        direction=trade.direction,
        management_mode=trade.management_mode,
        conviction_score=getattr(trade, "conviction_score", 0),
        entry_price=trade.entry_price,
        entry_timestamp=trade.entry_timestamp or exit_timestamp,
        exit_price=exit_price,
        exit_timestamp=exit_timestamp,
        initial_risk_usd=trade.initial_risk_usd,
        realized_r=trade.realized_r,
        partial_exits=list(trade.partials_taken),
        drawdown_tier_at_entry=portfolio.drawdown_tier,
        cdc_qualifies_zero_tolerance=_cdc_zero_tolerance(trade),
    )
    journal.append(entry)
    logger.info(
        "TRADE_CLOSED trade_id=%s asset=%s setup=%s dir=%s R=%.2f exit=%.4f tier=%s cdc_zt=%s",
        trade.id, trade.asset, trade.setup_type, trade.direction,
        trade.realized_r, exit_price, portfolio.drawdown_tier.name,
        entry.cdc_qualifies_zero_tolerance,
    )
    return entry


def log_skipped_setup(
    candidate: SetupCandidate,
    reason: str,
    journal: List[SkippedSetupLogEntry],
    now: Optional[datetime] = None,
) -> SkippedSetupLogEntry:
    """
    Build and append a SkippedSetupLogEntry when a candidate is explicitly rejected.

    reason examples:
      "RELATIVE_STRENGTH_FILTER" (I-8)
      "HEAT_CAP" (heat ceiling breached)
      "LOW_CONVICTION" (below direct-entry threshold, awaiting FTA)
      "ZERO_POSITION_SIZE"
      "DRAWDOWN_HALT" (TIER_2 / TIER_3)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    cdc_zt = candidate.cdc_qualifies_zero_tolerance \
        if candidate.setup_type in _CDC_TYPES else None

    entry = SkippedSetupLogEntry(
        candidate_id=candidate.id,
        asset=candidate.asset,
        timeframe=candidate.timeframe or "",
        setup_type=candidate.setup_type,
        direction=candidate.direction,
        rejected_at=now,
        reason=reason,
        conviction_score=candidate.conviction_score,
        cdc_qualifies_zero_tolerance=cdc_zt,
    )
    journal.append(entry)
    logger.info(
        "SETUP_SKIPPED asset=%s type=%s dir=%s reason=%s conviction=%d cdc_zt=%s",
        candidate.asset, candidate.setup_type, candidate.direction,
        reason, candidate.conviction_score, cdc_zt,
    )
    return entry


def log_event(
    event_type: EventType,
    payload: Dict,
    journal: List[Dict],
    trade: Optional[TradeState] = None,
    now: Optional[datetime] = None,
) -> None:
    """
    Append an interim lifecycle or system event to the audit trail.

    Used for state transitions:
      - EventType.STOP_MOVED       — dynamic R tightening, expiry_tightened
      - EventType.PARTIAL_EXIT     — stalling cut, scheduled partial
      - EventType.COMPOUNDED       — FTA break compound
      - EventType.STALLING_FLAG    — stall_band_counter reached threshold
      - EventType.EXPIRY_CLOSE     — time expiry close
      - EventType.FTA_BREAK_COMPOUND
      - EventType.FTA_REJECT_CLOSE
      - EventType.SKIPPED          — portfolio-level events (tier change, tranche)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    record = {
        "timestamp": now.isoformat(),
        "event_type": event_type.name,
        "trade_id": trade.id if trade else None,
        "asset": trade.asset if trade else payload.get("asset"),
        **payload,
    }
    journal.append(record)
    logger.info(
        "EVENT %s trade=%s payload=%s",
        event_type.name,
        trade.id if trade else None,
        payload,
    )
