"""
correlation.py — Correlation bucket lookup
===========================================

**Spec reference:** Resolution III-2.
CONFIG["CORRELATION_BUCKETS"]: {asset: bucket_label} set at bot init time.
Default mapping:
  BTC, ETH, BNB, SOL → "BTC_CORE"
  LINK, UNI, AAVE, CRV → "DEFI"
  Others → "OTHER" (each asset in its own implicit bucket)

Stub — implementation pending.

Public API:
    def correlation_bucket(asset: str) -> str:
        Return the bucket label for the given asset symbol.
        Assets not in CORRELATION_BUCKETS default to "OTHER".
        The MAX_CORRELATED_HEAT_PCT cap applies per bucket; assets in "OTHER"
        are treated as their own bucket (cap applies only if multiple assets share
        an explicit bucket label).
"""
from __future__ import annotations
from bot.config import CORRELATION_BUCKETS

DEFAULT_CORRELATION_BUCKETS: dict = {
    "BTC": "BTC_CORE", "ETH": "BTC_CORE", "BNB": "BTC_CORE", "SOL": "BTC_CORE",
    "LINK": "DEFI", "UNI": "DEFI", "AAVE": "DEFI", "CRV": "DEFI",
}


def correlation_bucket(asset: str) -> str:
    """
    Return bucket label for asset.  Uses CORRELATION_BUCKETS from CONFIG first
    (set at bot init), falls back to DEFAULT_CORRELATION_BUCKETS, then "OTHER".
    Resolution III-2.
    """
    return CORRELATION_BUCKETS.get(asset) or DEFAULT_CORRELATION_BUCKETS.get(asset, "OTHER")
