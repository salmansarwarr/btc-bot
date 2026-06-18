"""
market_basket.py — BTC+ETH 24-hour change aggregation
======================================================

**Spec reference:** Doc-1 §2.11; Resolution I-8 (relative-strength filter);
Doc-2 Additional item C (Proxy A — BTC+ETH average chosen over top-20 basket).

Public API:
    basket: MarketBasket
        Singleton updated on each BTC and ETH price tick.

    def update_basket(btc_24h: float, eth_24h: float) -> None:
        Recompute btc_eth_avg_24h_change = (btc_24h + eth_24h) / 2.
        top20_avg_24h_change is kept for future analysis but not computed here.

    def get_24h_change(asset: str) -> float:
        Return the most-recent 24-hour price-change percentage for a given asset.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict

from bot.structs import MarketBasket
from bot.data_ingestion import ohlcv_buffer

basket = MarketBasket()

# Keep track of the latest 24h change per asset
_asset_24h_changes: Dict[str, float] = {}


def update_basket(btc_24h: float, eth_24h: float) -> None:
    """Update the global basket metrics."""
    basket.btc_eth_avg_24h_change = (btc_24h + eth_24h) / 2.0
    basket.last_updated = datetime.now(timezone.utc)
    
    _asset_24h_changes["BTC"] = btc_24h
    _asset_24h_changes["ETH"] = eth_24h


def set_asset_24h_change(asset: str, pct_change: float) -> None:
    """Explicitly set an asset's 24h change."""
    _asset_24h_changes[asset] = pct_change


def get_24h_change(asset: str) -> float:
    """
    Return the most-recent 24-hour price-change percentage for a given asset.
    If explicitly tracked, return that.
    Otherwise, approximate from the OHLCV buffer (if D1 bars available).
    """
    if asset in _asset_24h_changes:
        return _asset_24h_changes[asset]
        
    # Attempt to approximate from D1 buffer if available
    d1_bars = ohlcv_buffer.get_bars(asset, "D1", 2)
    if len(d1_bars) == 2:
        current_close = d1_bars[-1].close
        prev_close = d1_bars[-2].close
        if prev_close > 0:
            return (current_close - prev_close) / prev_close
            
    return 0.0
