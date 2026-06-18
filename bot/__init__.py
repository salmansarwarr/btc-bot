"""
Automated Trading System
========================
Root package for the crypto trading bot defined in the Consolidated Build Specification.

Package layout
--------------
bot/
  config.py            – Canonical CONFIG dict  (Spec Part IV)
  structs.py           – All shared dataclass definitions  (Spec Part VI + Doc-3 structs)
  data_ingestion/      – OHLCV buffers, external feeds, market basket
  indicators/          – EMA, ATR, RSI, ADX, Efficiency Ratio computation
  market_context/      – HTF bias, trend classification, pivot registry
  setup_detection/     – CDC, SFP, MSB, consolidation, divergence detectors
  entry_risk/          – Entry evaluation, conviction scoring, stop placement
  trade_management/    – Active-trade lifecycle: stalling, expiry, partials, FTA
  portfolio/           – Heat enforcement, drawdown tiers, ATH realization
  journaling/          – Trade & skipped-setup logging, journal queries
  backtesting/         – Event-replay engine, performance metrics
"""
