"""
data_ingestion — OHLCV buffers, external feeds, and market basket ingestion
===========================================================================

**Spec references:**
  - Doc-3 §1 (data model — OHLCV_Bar, ExternalFeedState, MarketBasket)
  - Resolution III-6 (IndicatorState.ema_50_buffer updated on D1 close)
  - Resolution III-8 (oi_hourly feed structure for compute_oi_decline_pct)

Responsibilities
----------------
- Maintain rolling OHLCV deques per (asset, timeframe).
- Receive and normalise raw tick / bar data from exchange adapters.
- Update ``ExternalFeedState`` with OI, funding-rate, and liquidation streams.
- Publish bar-close events that trigger the indicator and context update chain.

Sub-modules (to be implemented)
--------------------------------
  ohlcv_buffer.py     — rolling deque management, bar-close detection
  exchange_adapter.py — exchange-specific WebSocket / REST normaliser
  feed_manager.py     — OI, funding, liquidation feed routing
  market_basket.py    — BTC+ETH 24h change aggregation (Resolution I-8 / II-16)
"""
