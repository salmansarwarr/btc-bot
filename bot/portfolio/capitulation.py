"""
capitulation.py — Capitulation detection and reserve deployment
===============================================================

**Spec reference:** Doc-1 §8.3; Doc-3 check_capitulation pseudocode.
Resolution I-9:  portfolio-level liquidation z-score (compute_liquidation_zscore) is
    distinct from the per-asset setup trigger (compute_asset_liquidation_zscore).
    Same threshold (LIQ_SIGMA_THRESHOLD: 2.0) applies to both.
Resolution II-9: Mega Wipe dual gate — OI decline + price drawdown dual condition.
Resolution III-3: deploy_capitulation_reserve_tranche — tranche-based deployment
    using capitulation_tranches_deployed dict to avoid re-deploying.
Resolution III-8: compute_oi_decline_pct and compute_price_drawdown_pct definitions.

Public API
----------
compute_liquidation_zscore(liq_hourly, window) -> float
    Market-wide liquidation spike z-score (Proxy A). Used in check_capitulation.
    Per-asset version is compute_asset_liquidation_zscore in setup_detection.

compute_oi_decline_pct(oi_hourly, days) -> float
    (oi_prior - oi_now) / oi_prior over the given day window (24 bars per day).

compute_price_drawdown_pct(closes, lookback_bars) -> float
    (recent_high - current_close) / recent_high over CAPITULATION_DRAWDOWN_LOOKBACK_BARS.

check_capitulation(portfolio, asset, closes, liq_hourly, oi_hourly, now) -> None
    Mega Wipe dual gate:
        compute_liquidation_zscore >= LIQ_SIGMA_THRESHOLD
        AND oi_decline >= OI_DECLINE_PCT_7D
        AND price_drawdown >= MEGA_WIPE_PRICE_DRAWDOWN
    On trigger: set portfolio.capitulation_detected_date, call deploy_capitulation_reserve_tranche.

deploy_capitulation_reserve_tranche(asset, portfolio, current_price_drawdown_pct) -> float
    Resolution III-3: deploy CAPITULATION_TRANCHE_SIZE (25%) of capitulation_reserve per
    additional CAPITULATION_TRANCHE_DROP_PCT (10%) of drawdown. Uses
    portfolio.capitulation_tranches_deployed[asset] to avoid re-deploying the same tranche.
    Returns the USD amount deployed (0.0 if no new tranche is due).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import List, Optional

from bot.structs import PortfolioState
from bot.config import (
    LIQ_SIGMA_THRESHOLD,
    OI_DECLINE_PCT_7D,
    MEGA_WIPE_PRICE_DRAWDOWN,
    CAPITULATION_TRANCHE_DROP_PCT,
    CAPITULATION_TRANCHE_SIZE,
    CAPITULATION_DRAWDOWN_LOOKBACK_BARS,
)

logger = logging.getLogger(__name__)


def compute_liquidation_zscore(liq_hourly: List[float], window: int = 480) -> float:
    """
    Market-wide (portfolio-level) liquidation spike z-score (Proxy A).

    Parameters
    ----------
    liq_hourly:
        Liquidation notional timeseries, newest last.
    window:
        Look-back in bars (default 480 = 20 days × 24h). Uses most recent bar as
        the observation and the prior window bars as the baseline distribution.

    Returns
    -------
    float
        Z-score of the latest liquidation bar vs. the rolling window mean/std.
        Returns 0.0 if there is insufficient history.
    """
    if len(liq_hourly) < window + 1:
        return 0.0

    baseline = liq_hourly[-(window + 1):-1]  # window bars ending just before the latest
    current = liq_hourly[-1]

    mean = sum(baseline) / len(baseline)
    variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
    std = math.sqrt(variance)

    if std <= 0:
        return 0.0

    return (current - mean) / std


def compute_oi_decline_pct(oi_hourly: List[float], days: int = 7) -> float:
    """
    (oi_prior - oi_now) / oi_prior over the given day window.

    Parameters
    ----------
    oi_hourly:
        OI timeseries, newest last.
    days:
        Lookback days. Each day = 24 hourly bars.

    Returns
    -------
    float
        Fractional decline (positive means OI fell). 0.0 if insufficient data.
    """
    bars = days * 24
    if len(oi_hourly) < bars + 1:
        return 0.0

    oi_prior = oi_hourly[-(bars + 1)]
    oi_now = oi_hourly[-1]

    if oi_prior <= 0:
        return 0.0

    return (oi_prior - oi_now) / oi_prior


def compute_price_drawdown_pct(closes: List[float], lookback_bars: int = CAPITULATION_DRAWDOWN_LOOKBACK_BARS) -> float:
    """
    (recent_high - current_close) / recent_high over lookback_bars.

    Parameters
    ----------
    closes:
        Daily close prices, newest last.
    lookback_bars:
        Window for finding the recent high (CAPITULATION_DRAWDOWN_LOOKBACK_BARS).

    Returns
    -------
    float
        Fractional drawdown from recent high. 0.0 if insufficient data.
    """
    if len(closes) < lookback_bars:
        return 0.0

    window = closes[-lookback_bars:]
    recent_high = max(window)
    current_close = closes[-1]

    if recent_high <= 0:
        return 0.0

    return (recent_high - current_close) / recent_high


def deploy_capitulation_reserve_tranche(
    asset: str,
    portfolio: PortfolioState,
    current_price_drawdown_pct: float,
    journal: Optional[List] = None,
) -> float:
    """
    Deploy 25% of capitulation_reserve per additional 10% of price drawdown.
    Uses portfolio.capitulation_tranches_deployed[asset] to avoid re-deploying.

    Parameters
    ----------
    asset:
        Asset symbol.
    portfolio:
        Live portfolio state.
    current_price_drawdown_pct:
        Current price drawdown from recent high (fractional, e.g. 0.35 = 35% down).

    Returns
    -------
    float
        USD amount deployed (0.0 if no new tranche is due).
    """
    reserve = portfolio.fund_balances.get("capitulation_reserve", 0.0)
    if reserve <= 0:
        return 0.0

    # How many tranches does the current drawdown level entitle?
    tranches_earned = int(current_price_drawdown_pct / CAPITULATION_TRANCHE_DROP_PCT)
    tranches_deployed = portfolio.capitulation_tranches_deployed.get(asset, 0)

    new_tranches = tranches_earned - tranches_deployed
    if new_tranches <= 0:
        return 0.0

    amount = reserve * CAPITULATION_TRANCHE_SIZE * new_tranches
    # Cap at remaining reserve
    amount = min(amount, reserve)

    portfolio.fund_balances["capitulation_reserve"] = reserve - amount
    portfolio.fund_balances["active"] = portfolio.fund_balances.get("active", 0.0) + amount
    portfolio.capitulation_tranches_deployed[asset] = tranches_deployed + new_tranches

    logger.info(
        "Capitulation reserve: deployed $%.2f (%d new tranche(s)) for %s (total tranches: %d)",
        amount, new_tranches, asset, portfolio.capitulation_tranches_deployed[asset]
    )
    if journal is not None:
        from bot.journaling.writer import log_event
        from bot.structs import EventType
        log_event(
            EventType.SKIPPED,
            {
                "detail": "capitulation_tranche_deployed",
                "asset": asset,
                "amount_usd": round(amount, 2),
                "new_tranches": new_tranches,
                "total_tranches": portfolio.capitulation_tranches_deployed[asset],
                "price_drawdown_pct": round(current_price_drawdown_pct * 100, 2),
            },
            journal,
        )
    return amount


def check_capitulation(
    portfolio: PortfolioState,
    asset: str,
    closes: List[float],
    liq_hourly: List[float],
    oi_hourly: List[float],
    now: datetime,
    journal: Optional[List] = None,
) -> None:
    """
    Mega Wipe dual gate (II-9):
        compute_liquidation_zscore >= LIQ_SIGMA_THRESHOLD
        AND oi_decline_7d >= OI_DECLINE_PCT_7D
        AND price_drawdown_30d >= MEGA_WIPE_PRICE_DRAWDOWN

    On trigger: set capitulation_detected_date and deploy the appropriate tranche.
    """
    # Gate 1: Liquidation z-score
    liq_z = compute_liquidation_zscore(liq_hourly)
    if liq_z < LIQ_SIGMA_THRESHOLD:
        return

    # Gate 2: OI decline
    oi_decline = compute_oi_decline_pct(oi_hourly, days=7)
    if oi_decline < OI_DECLINE_PCT_7D:
        return

    # Gate 3: Price drawdown
    price_dd = compute_price_drawdown_pct(closes)
    if price_dd < MEGA_WIPE_PRICE_DRAWDOWN:
        return

    # All conditions met — capitulation confirmed
    if portfolio.capitulation_detected_date is None:
        portfolio.capitulation_detected_date = now
        logger.info(
            "Capitulation detected for %s at %s (liq_z=%.2f, oi_decline=%.2f%%, price_dd=%.2f%%)",
            asset, now, liq_z, oi_decline * 100, price_dd * 100
        )
        if journal is not None:
            from bot.journaling.writer import log_event
            from bot.structs import EventType
            log_event(
                EventType.SKIPPED,
                {
                    "detail": "capitulation_detected",
                    "asset": asset,
                    "liq_z": round(liq_z, 2),
                    "oi_decline_pct": round(oi_decline * 100, 2),
                    "price_dd_pct": round(price_dd * 100, 2),
                },
                journal,
            )

    deployed = deploy_capitulation_reserve_tranche(asset, portfolio, price_dd, journal)
    if deployed > 0:
        logger.info("Capitulation tranche deployed: $%.2f for %s", deployed, asset)
