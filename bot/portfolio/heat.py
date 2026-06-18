"""
heat.py — Portfolio heat enforcement and cooloff
=================================================

**Spec reference:** Doc-1 §8.x; Doc-3 enforce_portfolio_heat, update_heat_cooloff.
Resolution II-11 (BUG FIX): enforce_portfolio_heat must use
    PortfolioState.effective_max_heat  (not CONFIG["MAX_HEAT_PCT"] directly).
Resolution III-2: correlation_bucket(asset) from CORRELATION_BUCKETS config.
"""
from __future__ import annotations
import logging
from typing import List, Optional

from bot.structs import PortfolioState, TradeState
from bot.config import (
    MAX_HEAT_PCT,
    MAX_CORRELATED_HEAT_PCT,
    HEAT_COOLOFF_LOSS_STREAK,
    HEAT_COOLOFF_REDUCTION
)
from bot.portfolio.correlation import correlation_bucket

logger = logging.getLogger(__name__)


def _heat_accounting_usd(trade: TradeState) -> float:
    """Risk dollars reserved against heat caps (Change 10 v3 dual-field tracking)."""
    if trade._heat_risk_usd > 0.0:
        return trade._heat_risk_usd
    return trade.initial_risk_usd


def enforce_portfolio_heat(
    portfolio: PortfolioState,
    trade: TradeState,
    skipped_journal: Optional[list] = None,
    candidate=None,          # SetupCandidate — for log_skipped_setup; optional
    now=None,
    pending_trades: Optional[dict] = None,
) -> bool:
    """
    Return True if adding this trade would breach either:
      - PortfolioState.effective_max_heat (total open risk) — BUG FIX II-11
      - MAX_CORRELATED_HEAT_PCT for the trade's correlation bucket.
    Returns False (allowed) otherwise.
    """
    if portfolio.equity <= 0:
        return True
        
    # If effective_max_heat isn't initialized yet, assume standard max
    if portfolio.effective_max_heat == 0.0:
        portfolio.effective_max_heat = MAX_HEAT_PCT
        
    candidate_risk_pct = _heat_accounting_usd(trade) / portfolio.equity

    # 1. Total Portfolio Heat
    all_open = {**portfolio.open_trades, **(pending_trades or {})}
    total_open_risk_usd = sum(_heat_accounting_usd(t) for t in all_open.values())
    total_risk_pct = total_open_risk_usd / portfolio.equity
    
    if total_risk_pct + candidate_risk_pct > portfolio.effective_max_heat:
        logger.info(
            "Heat ceiling breached. Total %.4f + Candidate %.4f > Max %.4f",
            total_risk_pct, candidate_risk_pct, portfolio.effective_max_heat
        )
        if skipped_journal is not None and candidate is not None:
            from bot.journaling.writer import log_skipped_setup
            log_skipped_setup(candidate, "HEAT_CAP", skipped_journal, now)
        return True
        
    # 2. Correlated Bucket Heat
    bucket = correlation_bucket(trade.asset)
    bucket_open_risk_usd = sum(
        _heat_accounting_usd(t)
        for t in all_open.values()
        if correlation_bucket(t.asset) == bucket
    )
    bucket_risk_pct = bucket_open_risk_usd / portfolio.equity
    
    # Since MAX_CORRELATED_HEAT_PCT can theoretically be higher than MAX_HEAT_PCT in some configs,
    # or just to enforce bucket limits, we check it against the raw constant.
    if bucket_risk_pct + candidate_risk_pct > MAX_CORRELATED_HEAT_PCT:
        logger.info(
            "Correlated heat breached for bucket %s. Bucket %.4f + Candidate %.4f > Max %.4f",
            bucket, bucket_risk_pct, candidate_risk_pct, MAX_CORRELATED_HEAT_PCT
        )
        if skipped_journal is not None and candidate is not None:
            from bot.journaling.writer import log_skipped_setup
            log_skipped_setup(candidate, "CORRELATED_HEAT_CAP", skipped_journal, now)
        return True
        
    return False


def update_heat_cooloff(portfolio: PortfolioState, trade_closed_as_loss: bool) -> None:
    """
    Update portfolio.consecutive_losses and recompute effective_max_heat:
      win → reset consecutive_losses; effective_max_heat = CONFIG["MAX_HEAT_PCT"]
      loss streak >= HEAT_COOLOFF_LOSS_STREAK →
        effective_max_heat = CONFIG["MAX_HEAT_PCT"] × (1 - CONFIG["HEAT_COOLOFF_REDUCTION"])
    """
    if trade_closed_as_loss:
        portfolio.consecutive_losses += 1
    else:
        portfolio.consecutive_losses = 0

    if portfolio.consecutive_losses >= HEAT_COOLOFF_LOSS_STREAK:
        portfolio.effective_max_heat = MAX_HEAT_PCT * (1.0 - HEAT_COOLOFF_REDUCTION)
        logger.info(
            "Soft cooloff active (%d losses). effective_max_heat reduced to %.4f",
            portfolio.consecutive_losses, portfolio.effective_max_heat
        )
    else:
        portfolio.effective_max_heat = MAX_HEAT_PCT
