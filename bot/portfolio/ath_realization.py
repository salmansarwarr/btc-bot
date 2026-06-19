"""
ath_realization.py — Portfolio ATH profit realization
======================================================

**Spec reference:** Doc-1 §8.x; Doc-3 check_ath_realization pseudocode.
Resolution II-10: backstop only fires when equity >= ATH × (1 - ATH_BACKSTOP_PROXIMITY_PCT).
"""
from __future__ import annotations
import logging
from datetime import datetime

from bot.structs import PortfolioState
from bot.config import (
    ATH_GAIN_PCT_30D,
    ATH_REALIZATION_PCT,
    ATH_BACKSTOP_DAYS,
    ATH_BACKSTOP_PCT,
    ATH_BACKSTOP_PROXIMITY_PCT
)

logger = logging.getLogger(__name__)

def check_ath_realization(portfolio: PortfolioState, equity_30d_ago: float, now: datetime) -> None:
    """
    Primary trigger: 30-day gain >= ATH_GAIN_PCT_30D → realize ATH_REALIZATION_PCT of equity.
    Backstop trigger (II-10):
      days_since(last_realization_date) >= ATH_BACKSTOP_DAYS
      AND equity >= portfolio.equity_ath × (1 - ATH_BACKSTOP_PROXIMITY_PCT)
      → realize ATH_BACKSTOP_PCT of equity to capitulation_reserve.
    """
    if portfolio.equity <= 0:
        return

    # Update ATH
    if portfolio.equity > portfolio.equity_ath:
        portfolio.equity_ath = portfolio.equity

    # Initialize last_realization_date if not set
    if portfolio.last_realization_date is None:
        portfolio.last_realization_date = now

    now_ms = now.timestamp() * 1000 if isinstance(now, datetime) else now
    last_ms = portfolio.last_realization_date.timestamp() * 1000 if isinstance(portfolio.last_realization_date, datetime) else portfolio.last_realization_date
    days_since_last = (now_ms - last_ms) / (86400 * 1000.0)

    # 1. Primary Trigger
    if equity_30d_ago > 0:
        gain_30d = (portfolio.equity - equity_30d_ago) / equity_30d_ago
        if gain_30d >= ATH_GAIN_PCT_30D:
            amount_to_realize = portfolio.equity * ATH_REALIZATION_PCT
            portfolio.fund_balances["capitulation_reserve"] = portfolio.fund_balances.get("capitulation_reserve", 0.0) + amount_to_realize
            portfolio.equity -= amount_to_realize
            portfolio.equity_ath = portfolio.equity  # Drop ATH proportionally so it doesn't trigger drawdown
            portfolio.last_realization_date = now
            logger.info(
                "Primary ATH Realization: 30d gain %.2f%% >= %.2f%%. Realized $%.2f to reserve. New Equity: $%.2f",
                gain_30d * 100, ATH_GAIN_PCT_30D * 100, amount_to_realize, portfolio.equity
            )
            return

    # 2. Backstop Trigger
    if days_since_last >= ATH_BACKSTOP_DAYS:
        proximity_threshold = portfolio.equity_ath * (1.0 - ATH_BACKSTOP_PROXIMITY_PCT)
        if portfolio.equity >= proximity_threshold:
            amount_to_realize = portfolio.equity * ATH_BACKSTOP_PCT
            portfolio.fund_balances["capitulation_reserve"] = portfolio.fund_balances.get("capitulation_reserve", 0.0) + amount_to_realize
            portfolio.equity -= amount_to_realize
            portfolio.equity_ath = portfolio.equity  # Drop ATH proportionally
            portfolio.last_realization_date = now
            logger.info(
                "Backstop ATH Realization: %d days since last, equity $%.2f >= threshold $%.2f. Realized $%.2f. New Equity: $%.2f",
                days_since_last, portfolio.equity, proximity_threshold, amount_to_realize, portfolio.equity
            )
