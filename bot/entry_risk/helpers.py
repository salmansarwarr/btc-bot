"""
helpers.py — Shared entry/risk utility functions
=================================================

**Spec references:**
  - Resolution I-8   (passes_relative_strength_filter)
  - Resolution III-4 (lock_in_1R_stop)
  - Resolution III-5 (compute_progress_to_target / approaching_target)
  - Resolution III-7 (signed_pnl)

Stub — implementation pending.

Public API:
    signed_pnl(direction, entry_price, exit_price) -> float
        Per-unit P&L respecting direction.  UP → exit-entry; DOWN → entry-exit.

    lock_in_1R_stop(trade, current_price) -> float
        Stop that locks in 1R protection; only moves in the favourable direction.
        Resolution III-4.

    compute_progress_to_target(trade, current_price) -> float
        Fraction of distance covered from entry to final target (0.0–1.0+).

    approaching_target(trade, current_price) -> bool
        True when progress >= CONFIG["APPROACHING_TARGET_THRESHOLD"] (0.6).
        Resolution III-5.

    passes_relative_strength_filter(candidate, asset) -> bool
        Relative-strength gate; active only for LOCKOUT_TREND + UP on a red
        market day.  Resolution I-8.
"""
from __future__ import annotations
from bot.structs import Direction, TradeState, SetupCandidate  # noqa: F401


def signed_pnl(direction: Direction, entry_price: float, exit_price: float) -> float:
    """Stub — Resolution III-7."""
    raise NotImplementedError


def lock_in_1R_stop(trade: TradeState, current_price: float) -> float:
    """Stub — Resolution III-4."""
    raise NotImplementedError


def compute_progress_to_target(trade: TradeState, current_price: float) -> float:
    """Stub — Resolution III-5."""
    raise NotImplementedError


def approaching_target(trade: TradeState, current_price: float) -> bool:
    """Stub — Resolution III-5."""
    raise NotImplementedError


def passes_relative_strength_filter(candidate: SetupCandidate, asset: str) -> bool:
    """Stub — Resolution I-8."""
    raise NotImplementedError
