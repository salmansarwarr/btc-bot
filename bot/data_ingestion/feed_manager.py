"""
feed_manager.py — OI, funding-rate, and liquidation feed routing
================================================================

**Spec reference:** Doc-3 §1 (ExternalFeedState); Resolution II-8 (OI/liq feeds
for liquidation proxy method selection); Resolution III-8 (oi_hourly structure).

Public API:
    feeds: Dict[str, ExternalFeedState]
        Global registry: feeds[asset] → ExternalFeedState.

    def update_oi(asset: str, oi_value: float) -> None:
        Append latest OI datapoint; maintain rolling history.

    def update_liquidations(asset: str, liq_notional: float) -> None:
        Append latest liquidation notional; maintain rolling history.
"""
from __future__ import annotations
from typing import Dict
from bot.structs import ExternalFeedState

feeds: Dict[str, ExternalFeedState] = {}

# Max length for hourly rolling history (e.g. 90 days = 2160 hours)
_MAX_HISTORY = 2160


def _ensure_feed(asset: str) -> ExternalFeedState:
    if asset not in feeds:
        feeds[asset] = ExternalFeedState(asset=asset)
    return feeds[asset]


def update_oi(asset: str, oi_value: float) -> None:
    """Append the latest hourly Open Interest value."""
    feed = _ensure_feed(asset)
    feed.oi_hourly.append(oi_value)
    
    if len(feed.oi_hourly) > _MAX_HISTORY:
        feed.oi_hourly = feed.oi_hourly[-_MAX_HISTORY:]
    
    # Update days of history available (assuming 1 data point per hour)
    feed.oi_history_days = len(feed.oi_hourly) // 24


def update_liquidations(asset: str, liq_notional: float) -> None:
    """Append the latest hourly Liquidation Notional value."""
    feed = _ensure_feed(asset)
    feed.liq_hourly.append(liq_notional)
    
    if len(feed.liq_hourly) > _MAX_HISTORY:
        feed.liq_hourly = feed.liq_hourly[-_MAX_HISTORY:]
        
    feed.liq_history_days = len(feed.liq_hourly) // 24


def update_funding_rate(asset: str, funding_rate: float) -> None:
    """Append the latest funding rate reading."""
    feed = _ensure_feed(asset)
    feed.funding_rate_history.append(funding_rate)
    
    if len(feed.funding_rate_history) > _MAX_HISTORY:
        feed.funding_rate_history = feed.funding_rate_history[-_MAX_HISTORY:]
