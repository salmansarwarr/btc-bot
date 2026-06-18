"""
entry_gate.py — Entry evaluation & TradeState initialisation
=============================================================

**Spec reference:**
  Doc-1 §3.x, §4.x;  Resolution I-3 (management mode), I-8 (rel. strength filter).

``evaluate_entry`` is the single public entry point.  Given a ``SetupCandidate``
and all runtime context it:

1. Computes the conviction score and assigns management_mode  (I-3).
2. Applies the relative-strength veto for LOCKOUT_TREND + UP candidates  (I-8).
3. Routes weak candidates (score < CONVICTION_DIRECT_ENTRY_THRESHOLD) to a
   ``PendingFTAConfirmation`` queue (caller responsible for storing them).
4. For a direct-entry approval, computes the stop (stop_calculator) and
   position size (sizer), then returns a fully-populated ``TradeState``.

Return type is ``EvaluateResult`` — a typed dataclass so callers can branch
cleanly without inspecting ``None`` fields.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from bot.config import (
    CONVICTION_DIRECT_ENTRY_THRESHOLD,
    PARTIAL_SCHEDULE,
)
from bot.entry_risk.conviction import compute_conviction_score
from bot.entry_risk.stop_calculator import compute_stop
from bot.entry_risk.sizer import compute_position_size
from bot.structs import (
    BiasState,
    Direction,
    DrawdownTier,
    MarketBasket,
    OHLCV_Bar,
    PendingFTAConfirmation,
    SetupCandidate,
    SkippedSetupLogEntry,
    TradeState,
    TrendClass,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class EvaluateResult:
    """
    Output of ``evaluate_entry``.

    Exactly one of ``trade``, ``pending``, or ``skipped`` is non-None;
    the others are None.  Callers should match on these to determine the
    routing outcome.
    """
    trade: Optional[TradeState] = None
    pending: Optional[PendingFTAConfirmation] = None
    skipped: Optional[SkippedSetupLogEntry] = None

    @property
    def approved(self) -> bool:
        """True when a fully-initialised TradeState was produced."""
        return self.trade is not None

    @property
    def needs_fta(self) -> bool:
        """True when the candidate is queued waiting for FTA confirmation."""
        return self.pending is not None

    @property
    def rejected(self) -> bool:
        """True when the candidate was vetoed and logged as skipped."""
        return self.skipped is not None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_skipped(
    candidate: SetupCandidate,
    reason: str,
    now: datetime,
) -> SkippedSetupLogEntry:
    """Create and log a SkippedSetupLogEntry."""
    entry = SkippedSetupLogEntry(
        candidate_id=candidate.id,
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        setup_type=candidate.setup_type,
        direction=candidate.direction,
        rejected_at=now,
        reason=reason,
        conviction_score=candidate.conviction_score,
        cdc_qualifies_zero_tolerance=candidate.cdc_qualifies_zero_tolerance,
    )
    logger.info(
        "setup skipped  asset=%s  type=%s  dir=%s  reason=%s  conviction=%d",
        candidate.asset,
        candidate.setup_type,
        candidate.direction,
        reason,
        candidate.conviction_score,
    )
    return entry


def _build_trade_state(
    candidate: SetupCandidate,
    stop: float,
    size: float,
    equity: float,
    bar_index: int,
    now: datetime,
) -> TradeState:
    """Assemble a fully-populated TradeState from a scored candidate."""
    initial_risk_usd = abs(candidate.trigger_price - stop) * size
    return TradeState(
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        setup_type=candidate.setup_type,
        setup_class=candidate.setup_class,
        direction=candidate.direction,
        management_mode=candidate.management_mode,
        conviction_score=candidate.conviction_score,
        entry_price=candidate.trigger_price,
        entry_bar_index=bar_index,
        entry_timestamp=now,
        position_size=size,
        initial_position_size=size,
        initial_risk_usd=initial_risk_usd,
        stop_price=stop,
        pivot_used=candidate.trigger_pivot,
        partials_scheduled=list(PARTIAL_SCHEDULE),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_entry(
    candidate: SetupCandidate,
    htf_bias: BiasState,
    trend_class: TrendClass,
    market_basket: MarketBasket,
    asset_24h_change: float,
    account_equity: float,
    atr: float,
    drawdown_tier: DrawdownTier = DrawdownTier.TIER_0,
    bars_for_percentile: Optional[List[OHLCV_Bar]] = None,
    bar_index: int = 0,
    now: Optional[datetime] = None,
) -> EvaluateResult:
    """
    Evaluate a ``SetupCandidate`` and produce a routing decision.

    Parameters
    ----------
    candidate:
        The detected setup to evaluate.  Its ``conviction_score`` and
        ``management_mode`` will be set in-place as a side effect.
    htf_bias:
        Higher-timeframe directional bias (BULLISH / BEARISH / NEUTRAL).
    trend_class:
        Current trend classification (RANGING / TRENDING / LOCKOUT_TREND).
    market_basket:
        Broad-market 24h change data used by the relative-strength filter.
    asset_24h_change:
        24h price change for this specific asset (fractional, e.g. -0.015).
    account_equity:
        Current account equity in the account's denomination currency.
    atr:
        Current ATR(14) value for stop computation.
    bars_for_percentile:
        Optional recent bars passed to the pivot-percentile conviction check.
    bar_index:
        Current bar index (written to TradeState.entry_bar_index).
    now:
        Evaluation timestamp; defaults to UTC now.

    Returns
    -------
    EvaluateResult
        ``trade``   — direct-entry approved; ``TradeState`` is fully populated.
        ``pending`` — below direct-entry threshold; queued for FTA confirmation.
        ``skipped`` — vetoed by a filter; ``SkippedSetupLogEntry`` is logged.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # --- Step 1: Conviction scoring (mutates candidate in-place) ----------------
    compute_conviction_score(candidate, htf_bias, bars_for_percentile)

    # --- Step 2: Relative-strength veto  (I-8) ----------------------------------
    # Applied ONLY when the market is in LOCKOUT_TREND and the candidate is long.
    if trend_class == TrendClass.LOCKOUT_TREND and candidate.direction == Direction.UP:
        if market_basket.btc_eth_avg_24h_change < 0:
            if asset_24h_change <= market_basket.btc_eth_avg_24h_change:
                return EvaluateResult(
                    skipped=_log_skipped(candidate, "RELATIVE_STRENGTH_FILTER", now)
                )

    # --- Step 3: Direct-entry threshold gate ------------------------------------
    if candidate.conviction_score < CONVICTION_DIRECT_ENTRY_THRESHOLD:
        pending = PendingFTAConfirmation(
            candidate=candidate,
            created_bar_index=bar_index,
            created_at=now,
            fta_price=0.0,          # caller fills FTA price from their FTA registry
        )
        logger.debug(
            "setup queued for FTA  asset=%s  type=%s  conviction=%d",
            candidate.asset, candidate.setup_type, candidate.conviction_score,
        )
        return EvaluateResult(pending=pending)

    # --- Step 4: Stop placement -------------------------------------------------
    stop = compute_stop(candidate, atr)
    candidate.stop_price = stop     # keep candidate in sync for downstream callers

    # --- Step 5: Position sizing ------------------------------------------------
    size = compute_position_size(candidate, account_equity, drawdown_tier)

    if size <= 0.0:
        # Zero size: drawdown halt vs genuine zero-size edge case
        reason = "DRAWDOWN_HALT" if drawdown_tier.value >= 2 else "ZERO_POSITION_SIZE"
        return EvaluateResult(
            skipped=_log_skipped(candidate, reason, now)
        )

    # --- Step 6: Build TradeState -----------------------------------------------
    trade = _build_trade_state(candidate, stop, size, account_equity, bar_index, now)
    logger.info(
        "entry approved  asset=%s  type=%s  dir=%s  size=%.4f  stop=%.4f  conviction=%d  mode=%s",
        candidate.asset, candidate.setup_type, candidate.direction,
        size, stop, candidate.conviction_score, candidate.management_mode,
    )
    return EvaluateResult(trade=trade)
