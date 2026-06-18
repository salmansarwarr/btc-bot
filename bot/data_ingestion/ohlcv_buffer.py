"""
ohlcv_buffer.py — Rolling OHLCV deque management
=================================================

Maintains rolling buffers of OHLCV_Bar objects per (asset, timeframe).
Exposes an exchange-fetching helper to seed the buffer incrementally.

Spec reference: Doc-3 §1 (data model).
"""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Deque, List

import ccxt
from bot.structs import OHLCV_Bar
from bot.indicators import registry

# Global OHLCV buffer registry
# buffer[asset][timeframe] -> deque
buffer: Dict[str, Dict[str, Deque[OHLCV_Bar]]] = {}

# Keep up to 500 bars in memory per timeframe
_MAX_BUFFER_LEN = 500


def _ensure_buffer(asset: str, timeframe: str) -> None:
    if asset not in buffer:
        buffer[asset] = {}
    if timeframe not in buffer[asset]:
        buffer[asset][timeframe] = deque(maxlen=_MAX_BUFFER_LEN)


def on_bar_close(bar: OHLCV_Bar) -> None:
    """
    Ingest a newly closed bar.
    1. Appends to the global OHLCV deque.
    2. Pushes the bar to the indicators registry to update state.
    """
    _ensure_buffer(bar.asset, bar.timeframe)
    buffer[bar.asset][bar.timeframe].append(bar)
    
    # Notify indicator registry to compute new values
    registry.on_bar_close(bar)


def get_bars(asset: str, timeframe: str, n: int) -> List[OHLCV_Bar]:
    """
    Return the n most-recent bars for the asset/timeframe (newest last).
    """
    _ensure_buffer(asset, timeframe)
    q = buffer[asset][timeframe]
    if n >= len(q):
        return list(q)
    
    # Convert deque to list and slice
    lst = list(q)
    return lst[-n:]


def fetch_historical_bars(
    exchange_id: str, 
    symbol: str, 
    timeframe: str, 
    since: int | None = None, 
    limit: int = 1000
) -> List[OHLCV_Bar]:
    """
    Utility to fetch historical OHLCV data using ccxt.
    symbol should be in exchange format (e.g., 'BTC/USDT').
    Returns a list of OHLCV_Bar objects.
    """
    # Instantiate the exchange dynamically
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({'enableRateLimit': True})
    
    # Fetch data
    raw_ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    
    bars = []
    for row in raw_ohlcv:
        ts = row[0]
        # ccxt returns timestamp in milliseconds
        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        
        # Determine our internal asset name (e.g. BTC/USDT -> BTC)
        asset = symbol.split('/')[0] if '/' in symbol else symbol
        
        # Normalize ccxt timeframe ('1d' -> 'D1', '1h' -> 'H1')
        internal_tf = timeframe.upper()
        if internal_tf == "1D":
            internal_tf = "D1"
        elif internal_tf == "1H":
            internal_tf = "H1"
        elif internal_tf == "1W":
            internal_tf = "W1"
            
        bar = OHLCV_Bar(
            timestamp=dt,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            timeframe=internal_tf,
            asset=asset
        )
        bars.append(bar)
        
    return bars
