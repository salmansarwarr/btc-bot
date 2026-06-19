"""
config.py — Canonical CONFIG for the Automated Trading System
=============================================================

**Spec reference:** Part IV — Resolved Full CONFIG (Canonical Reference)

This is the *single authoritative source* for every numeric threshold, multiplier,
and structural setting used across the bot.  Any constant that appears in the spec
is defined here, even if the consuming module has not been implemented yet.

Naming conventions
------------------
- All keys are UPPER_SNAKE_CASE strings (dict access style) mirrored as module-level
  Python constants below for IDE autocompletion / type-checking.
- New parameters introduced by the gap-resolution work are annotated with the
  originating section reference in a trailing comment.

Usage
-----
    from bot.config import CONFIG

    threshold = CONFIG["ADX_TREND_THRESHOLD"]   # 30
"""

from __future__ import annotations
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Master CONFIG dict — the single canonical reference
# (Spec Part IV, pp. 450-568)
# ---------------------------------------------------------------------------

CONFIG: Dict[str, Any] = {

    # ── Trend classification ─────────────────────────────────────────────────
    # Spec §1.2 / Doc-3 §1; Doc-2 §1 (Proxy A+B combined for lockout-trend gate)
    "ADX_TREND_THRESHOLD": 30,          # ADX value above which a trend is deemed LOCKOUT_TREND
    "ER_TREND_THRESHOLD": 0.6,          # Efficiency Ratio trigger that flips bias to trending
    "TREND_CONFIRM_BARS": 10,           # consecutive bars ER must stay above threshold to confirm

    # ── HTF Directional Bias ─────────────────────────────────────────────────
    # Spec §1.3; Resolution I-1 (lookback window), I-2 (EMA slope lag)
    "N_HTF_BIAS_LOOKBACK": 20,          # NEW (I-1, III-9): detect_factual_msb lookback window in HTF bars
    "EMA50_SLOPE_LAG_BARS": 10,         # NEW (I-2): bars ago used to compute EMA-50 slope for bias veto

    # ── Pivot definitions ────────────────────────────────────────────────────
    # Spec §2.x; Doc-2 §3 (Proxy A for detection, C for conviction scoring)
    "PIVOT_MAJOR_N": {"default": 2, "D1": 1, "W1": 1},  # N-candle fractal look-left/right per TF
    "PIVOT_MINOR_N": 1,                 # N-candle fractal for minor pivots
    "PIVOT_MAJOR_ATR_MULT": 0.25,       # minimum swing size (× ATR-14) to qualify as major pivot
    "PIVOT_MAJOR_PERCENTILE": 0.10,     # top/bottom percentile threshold for major-pivot classification
    "PIVOT_PERCENTILE_SCORING_ENABLED": True,   # NEW (II-1): apply percentile filter at conviction-scoring time
    "PIVOT_PERCENTILE_LOOKBACK": 50,            # NEW (II-1): trailing-bar window for percentile calculation
    "MINOR_PIVOT_RESPECTED_BONUS": 0.5,         # NEW (II-2): conviction bonus when a minor pivot was previously respected

    # ── Clean break ──────────────────────────────────────────────────────────
    # Spec §2.x; Doc-2 §5 (Proxy A+C composite — already in Doc-3, no gap)
    "BREAK_BODY_ATR_MULT": 1.0,         # candle body must span ≥ this × ATR(14) to qualify as clean break
    "BREAK_CLOSE_BEYOND_ATR_MULT": 0.15,  # close must be ≥ this × ATR(14) beyond the level
    "BREAK_WICK_RATIO_MAX": 0.25,       # rejection wick / total range must be ≤ this (Proxy C wick filter)

    # ── Stop placement / SR_FLIP ─────────────────────────────────────────────
    # Spec §4.2; Resolution I-4 (dedicated parameter for SR_FLIP stop)
    "SR_FLIP_STOP_ATR_MULT": 0.15,      # NEW (I-4): ATR offset below/above the flipped level for SR_FLIP stops
    "SR_FLIP_PULLBACK_ATR_TOL": 0.5,    # tolerance: price must return within this × ATR of the flip level to confirm retest
    "FLIP_CONFIRM_BARS": 1,             # number of bars to confirm bounce (currently just 1)
    "FLIP_ATR_MULT": 0.0,               # bounce candle body must be >= this × ATR
    "FLIP_BODY_RATIO_MIN": 0.50,        # bounce candle body/total-range ratio [Change 22: tightened from 0.0]
    "MIN_STOP_ATR_MULT": 1.2,           # floor: stop cannot be closer than this × ATR(14) to entry

    # ── CDC no-interaction buffer ────────────────────────────────────────────
    # Spec §2.4; Doc-2 §6 (Proxy A)
    "CDC_NO_INTERACTION_ATR_MULT": 0.05,  # max wick intrusion into level (× ATR) still classified as no-interaction

    # ── Pullback depth ───────────────────────────────────────────────────────
    # Spec §2.x; Doc-2 §7 (shallow) and §8 (deep)
    "SHALLOW_FIB_MIN": 0.30,            # minimum Fibonacci retracement for shallow-pullback classification  [Change 19: tightened from 0.236]
    "SHALLOW_FIB_MAX": 0.382,           # maximum Fibonacci retracement for shallow-pullback classification
    "SHALLOW_ATR_CAP_MULT": 2.0,        # ATR sanity cap: retracement > this × ATR(14) → NOT shallow (II-5 wiring)  [Change 19: tightened from 3.0]
    "DEEP_FIB_MIN": 0.55,               # minimum retracement ratio for deep-pullback (tolerance band)
    "DEEP_FIB_MAX": 0.85,               # maximum retracement ratio for deep-pullback (tolerance band)
    "DEEP_PULLBACK_CONFLUENCE_BONUS": 0.5,      # NEW (II-6): conviction bonus when deep pullback also re-enters consolidation zone

    # ── Candle Open Drive / SFP ──────────────────────────────────────────────
    # Spec §2.x; Doc-2 §9 (Proxy A)
    "DRIVE_ATR_MULT": 1.2,              # drive candle must move ≥ this × ATR(14) from open
    "DRIVE_BODY_RANGE_RATIO_MIN": 0.65,  # body/total-range ratio threshold for a valid drive candle
    "SFP_WICK_ATR_MULT": 1.5,           # NEW: minimum wick size (× ATR) for a valid SFP
    "ENABLE_SFP": False,                  # Change 9a: set False to disable SFP setup detection

    # ── Stalling / time expiry ───────────────────────────────────────────────
    # Spec §5.x, §6.x; Doc-2 §10 (Proxy A + C for traps)
    "STALL_ATR_MULT": 0.1,              # price band width (× ATR) used to detect stalling
    "STALL_BARS": 3,                    # consecutive bars within the band to trigger stalling flag
    "TRAP_REENTRY_ATR_MULT": 2.0,       # NEW (II-7): re-entry detection band around trigger level for TRAP setups (× ATR)
    "EXPIRY_TRAP_BARS": 4,              # max bars before a TRAP-class setup expires with no movement
    "EXPIRY_TRAP_ATR_MULT": 1.0,        # expected minimum movement (× ATR) before trap expiry
    "EXPIRY_CONTINUATION_BARS": 8,      # max bars before a CONTINUATION setup expires
    "EXPIRY_CONTINUATION_ATR_MULT": 0.5,        # stall threshold (× ATR) for continuation expiry
    "EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT": 0.1,  # tightened stop offset after expiry warning
    "EXPIRY_HTF_BASE_BARS": 8,          # NEW (I-5): base bars for HTF_SWING expiry (replaces reuse of EXPIRY_TRAP_BARS)
    "EXPIRY_HTF_MULTIPLIER": 8,         # CHANGED 10→8 (I-5): multiplier → 8×8 = 64 bars (midpoint of 40-80 range)

    # ── Momentum divergence ──────────────────────────────────────────────────
    # Spec §2.11; Doc-2 Additional item B (extreme-zone filter)
    "RSI_DIV_EXTREME_LOW": 35,          # NEW (II-15): RSI must be below this for bullish divergence (relaxed from 30)
    "RSI_DIV_EXTREME_HIGH": 65,         # NEW (II-15): RSI must be above this for bearish divergence (relaxed from 70)
    "MOMENTUM_DIVERGENCE_MIN_STRENGTH": 5.0,  # Soft filter: minimum RSI difference for a valid divergence
    "MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER": True,  # if True, skip MD entries with no same-direction peer within ±3 bars
    "CLUSTER_PNL_SCALING_MODE": "full",  # "off" | "cap2" | "full" — same-bar cluster P&L split (Change 12)
    # ── Consolidation detection ──────────────────────────────────────────────
    # Spec §2.11; Resolution III-10
    "CONSOLIDATION_MIN_BARS": 5,                # NEW (III-10): minimum consecutive bars to classify as consolidation
    "CONSOLIDATION_BAR_RANGE_ATR_MULT": 0.7,    # NEW (III-10): each bar's H-L range must be < this × ATR(14)
    "CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT": 1.5,  # NEW (III-10): total zone height must be < this × ATR(14)

    # ── Liquidation / OI thresholds ──────────────────────────────────────────
    # Spec §2.11; Doc-2 §11 (Proxy C→B→A hierarchy); Resolution I-9, II-8
    "LIQ_SIGMA_THRESHOLD": 2.0,         # Proxy A fallback: z-score threshold for liquidation spike (20-day window)
    "LIQ_PERCENTILE_THRESHOLD": 0.95,   # NEW (II-8): Proxy B — 90-day liquidation percentile cutoff
    "LIQ_OI_PCT_THRESHOLD": 0.02,       # NEW (II-8): Proxy C — liquidation notional / OI-at-window-start ratio
    "OI_DECLINE_PCT_7D": 0.25,          # OI must decline ≥ 25% over 7 days for Mega Wipe condition
    "MEGA_WIPE_PRICE_DRAWDOWN": 0.20,   # Price must have fallen ≥ 20% (Mega Wipe dual gate, II-9 — already implemented)
    "CAPITULATION_TRANCHE_DROP_PCT": 0.10,      # NEW (III-3): each additional -10% price drop earns one reserve tranche
    "CAPITULATION_TRANCHE_SIZE": 0.25,          # NEW (III-3): fraction of capitulation reserve deployed per tranche
    "CAPITULATION_DRAWDOWN_LOOKBACK_BARS": 30,  # NEW (III-8): D1 bar window for recent-high in drawdown calculation

    # ── Portfolio ATH realization ────────────────────────────────────────────
    # Spec §8.x; Doc-2 §13 (Proxy A primary + B backstop)
    "ATH_GAIN_PCT_30D": 0.30,           # 30-day portfolio gain threshold to trigger ATH realization
    "ATH_REALIZATION_PCT": 0.10,        # fraction of equity moved to cash on ATH realization
    "ATH_BACKSTOP_DAYS": 90,            # backstop fires if no realization within this many days
    "ATH_BACKSTOP_PCT": 0.05,           # fraction realized by backstop (smaller than primary trigger)
    "ATH_BACKSTOP_PROXIMITY_PCT": 0.01, # NEW (II-10): backstop only fires when equity ≥ ATH × (1 - this)

    # ── Portfolio heat ───────────────────────────────────────────────────────
    # Spec §8.x; Doc-2 §14 (Proxy A hard ceiling + C soft cooloff)
    "MAX_HEAT_PCT": 0.06,               # hard ceiling: total open risk may never exceed 12% of equity
    "MAX_CORRELATED_HEAT_PCT": 0.06,    # per-correlation-bucket cap: 8% of equity
    "HEAT_COOLOFF_LOSS_STREAK": 3,      # consecutive losses before soft cooloff activates (C early-warning, II-13)
    "HEAT_COOLOFF_REDUCTION": 0.25,     # effective_max_heat reduced by this fraction during loss streak
    "CORRELATION_BUCKETS": {},          # NEW (III-2): {asset_symbol: bucket_label}; set at bot config time

    # ── Risk per trade ───────────────────────────────────────────────────────
    # Spec §4.x; Doc-2 Additional item A (equal-weight conviction scoring retained)
    "RISK_PCT_BY_CONVICTION": {3: 0.03, 2: 0.02, 1: 0.01, 0: 0.0},  # conviction score → fraction of equity at risk

    # ── Partial exit schedule ────────────────────────────────────────────────
    # Spec §5.x; Doc-2 §15 (Proxy A — 33/33/34 at FTAs, with FTA-break override already implemented)
    "PARTIAL_SCHEDULE": [0.33, 0.33, 0.34],  # fractions of position closed at each FTA target

    # ── Drawdown tiers ───────────────────────────────────────────────────────
    # Spec §8.4; Resolution I-10 (intermediate recovery); Doc-2 §16 (A primary + C early-warning)
    "DRAWDOWN_TIER_1_PCT": 0.10,        # equity drawdown from ATH that triggers tier-1 (50% risk reduction)
    "DRAWDOWN_TIER_2_PCT": 0.20,        # equity drawdown that triggers tier-2 (full risk halt)
    "DRAWDOWN_TIER_3_PCT": 0.30,        # equity drawdown that triggers tier-3 (emergency mode)
    "DRAWDOWN_TIER_1_RISK_MULT": 0.5,   # risk multiplier applied in tier-1
    "DRAWDOWN_RECOVERY_HYSTERESIS": 0.5,  # NEW (I-10): tier-2→tier-1 step-down at 50% recovery toward tier-2 threshold

    # ── Conviction scoring ───────────────────────────────────────────────────
    # Spec §3.x; Doc-2 Additional item A (equal-weight 3-point scale retained)
    "CONVICTION_DIRECT_ENTRY_THRESHOLD": 2,  # score ≥ this allows direct entry without FTA confirmation

    # ── FTA confirmation ─────────────────────────────────────────────────────
    # Spec §3.x; Resolution III-1
    "MAX_PENDING_AGE_BARS": 20,         # NEW (III-1): setup pending FTA confirmation expires after this many idea-TF bars

    # ── Target proximity ─────────────────────────────────────────────────────
    # Resolution III-5 (approaching_target helper)
    "APPROACHING_TARGET_THRESHOLD": 0.6,  # NEW (III-5): progress fraction to target above which trade is "approaching target"

    # ── Relative strength filter ─────────────────────────────────────────────
    # Spec §2.11; Resolution I-8; Doc-2 Additional item C (Proxy A — BTC+ETH basket)
    # No numeric threshold: filter passes when asset_24h_change > btc_eth_avg_24h_change (outperform)
    # MarketBasket.btc_eth_avg_24h_change is the operative field; top20_avg_24h_change is stored but unused in logic.
}

# ---------------------------------------------------------------------------
# Module-level aliases for IDE autocompletion and static type checking
# These are kept in sync with the dict above — do not edit one without the other.
# ---------------------------------------------------------------------------

ADX_TREND_THRESHOLD: int                    = CONFIG["ADX_TREND_THRESHOLD"]
ER_TREND_THRESHOLD: float                   = CONFIG["ER_TREND_THRESHOLD"]
TREND_CONFIRM_BARS: int                     = CONFIG["TREND_CONFIRM_BARS"]

N_HTF_BIAS_LOOKBACK: int                    = CONFIG["N_HTF_BIAS_LOOKBACK"]
EMA50_SLOPE_LAG_BARS: int                   = CONFIG["EMA50_SLOPE_LAG_BARS"]

PIVOT_MAJOR_N: dict                         = CONFIG["PIVOT_MAJOR_N"]
PIVOT_MINOR_N: int                          = CONFIG["PIVOT_MINOR_N"]
PIVOT_MAJOR_ATR_MULT: float                 = CONFIG["PIVOT_MAJOR_ATR_MULT"]
PIVOT_MAJOR_PERCENTILE: float               = CONFIG["PIVOT_MAJOR_PERCENTILE"]
PIVOT_PERCENTILE_SCORING_ENABLED: bool      = CONFIG["PIVOT_PERCENTILE_SCORING_ENABLED"]
PIVOT_PERCENTILE_LOOKBACK: int              = CONFIG["PIVOT_PERCENTILE_LOOKBACK"]
MINOR_PIVOT_RESPECTED_BONUS: float          = CONFIG["MINOR_PIVOT_RESPECTED_BONUS"]

BREAK_BODY_ATR_MULT: float                  = CONFIG["BREAK_BODY_ATR_MULT"]
BREAK_CLOSE_BEYOND_ATR_MULT: float          = CONFIG["BREAK_CLOSE_BEYOND_ATR_MULT"]
BREAK_WICK_RATIO_MAX: float                 = CONFIG["BREAK_WICK_RATIO_MAX"]

SR_FLIP_STOP_ATR_MULT: float                = CONFIG["SR_FLIP_STOP_ATR_MULT"]
SR_FLIP_PULLBACK_ATR_TOL: float             = CONFIG["SR_FLIP_PULLBACK_ATR_TOL"]
FLIP_CONFIRM_BARS: int                      = CONFIG["FLIP_CONFIRM_BARS"]
FLIP_ATR_MULT: float                        = CONFIG["FLIP_ATR_MULT"]
FLIP_BODY_RATIO_MIN: float                  = CONFIG["FLIP_BODY_RATIO_MIN"]
MIN_STOP_ATR_MULT: float                    = CONFIG["MIN_STOP_ATR_MULT"]

CDC_NO_INTERACTION_ATR_MULT: float          = CONFIG["CDC_NO_INTERACTION_ATR_MULT"]

SHALLOW_FIB_MIN: float                      = CONFIG["SHALLOW_FIB_MIN"]      # 0.30  (Change 19)
SHALLOW_FIB_MAX: float                      = CONFIG["SHALLOW_FIB_MAX"]
SHALLOW_ATR_CAP_MULT: float                 = CONFIG["SHALLOW_ATR_CAP_MULT"]  # 2.0   (Change 19)
DEEP_FIB_MIN: float                         = CONFIG["DEEP_FIB_MIN"]
DEEP_FIB_MAX: float                         = CONFIG["DEEP_FIB_MAX"]
DEEP_PULLBACK_CONFLUENCE_BONUS: float       = CONFIG["DEEP_PULLBACK_CONFLUENCE_BONUS"]

DRIVE_ATR_MULT: float                       = CONFIG["DRIVE_ATR_MULT"]
DRIVE_BODY_RANGE_RATIO_MIN: float           = CONFIG["DRIVE_BODY_RANGE_RATIO_MIN"]
SFP_WICK_ATR_MULT: float                    = CONFIG["SFP_WICK_ATR_MULT"]
ENABLE_SFP: bool                            = CONFIG["ENABLE_SFP"]

STALL_ATR_MULT: float                       = CONFIG["STALL_ATR_MULT"]
STALL_BARS: int                             = CONFIG["STALL_BARS"]
TRAP_REENTRY_ATR_MULT: float                = CONFIG["TRAP_REENTRY_ATR_MULT"]
EXPIRY_TRAP_BARS: int                       = CONFIG["EXPIRY_TRAP_BARS"]
EXPIRY_TRAP_ATR_MULT: float                 = CONFIG["EXPIRY_TRAP_ATR_MULT"]
EXPIRY_CONTINUATION_BARS: int              = CONFIG["EXPIRY_CONTINUATION_BARS"]
EXPIRY_CONTINUATION_ATR_MULT: float        = CONFIG["EXPIRY_CONTINUATION_ATR_MULT"]
EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT: float = CONFIG["EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT"]
EXPIRY_HTF_BASE_BARS: int                   = CONFIG["EXPIRY_HTF_BASE_BARS"]
EXPIRY_HTF_MULTIPLIER: int                  = CONFIG["EXPIRY_HTF_MULTIPLIER"]

RSI_DIV_EXTREME_LOW: int                    = CONFIG["RSI_DIV_EXTREME_LOW"]
RSI_DIV_EXTREME_HIGH: int                   = CONFIG["RSI_DIV_EXTREME_HIGH"]
MOMENTUM_DIVERGENCE_MIN_STRENGTH: float     = CONFIG["MOMENTUM_DIVERGENCE_MIN_STRENGTH"]
MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER: bool   = CONFIG["MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER"]
CLUSTER_PNL_SCALING_MODE: str               = CONFIG["CLUSTER_PNL_SCALING_MODE"]

CONSOLIDATION_MIN_BARS: int                 = CONFIG["CONSOLIDATION_MIN_BARS"]
CONSOLIDATION_BAR_RANGE_ATR_MULT: float     = CONFIG["CONSOLIDATION_BAR_RANGE_ATR_MULT"]
CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT: float  = CONFIG["CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT"]

LIQ_SIGMA_THRESHOLD: float                  = CONFIG["LIQ_SIGMA_THRESHOLD"]
LIQ_PERCENTILE_THRESHOLD: float             = CONFIG["LIQ_PERCENTILE_THRESHOLD"]
LIQ_OI_PCT_THRESHOLD: float                 = CONFIG["LIQ_OI_PCT_THRESHOLD"]
OI_DECLINE_PCT_7D: float                    = CONFIG["OI_DECLINE_PCT_7D"]
MEGA_WIPE_PRICE_DRAWDOWN: float             = CONFIG["MEGA_WIPE_PRICE_DRAWDOWN"]
CAPITULATION_TRANCHE_DROP_PCT: float        = CONFIG["CAPITULATION_TRANCHE_DROP_PCT"]
CAPITULATION_TRANCHE_SIZE: float            = CONFIG["CAPITULATION_TRANCHE_SIZE"]
CAPITULATION_DRAWDOWN_LOOKBACK_BARS: int    = CONFIG["CAPITULATION_DRAWDOWN_LOOKBACK_BARS"]

ATH_GAIN_PCT_30D: float                     = CONFIG["ATH_GAIN_PCT_30D"]
ATH_REALIZATION_PCT: float                  = CONFIG["ATH_REALIZATION_PCT"]
ATH_BACKSTOP_DAYS: int                      = CONFIG["ATH_BACKSTOP_DAYS"]
ATH_BACKSTOP_PCT: float                     = CONFIG["ATH_BACKSTOP_PCT"]
ATH_BACKSTOP_PROXIMITY_PCT: float           = CONFIG["ATH_BACKSTOP_PROXIMITY_PCT"]

MAX_HEAT_PCT: float                         = CONFIG["MAX_HEAT_PCT"]
MAX_CORRELATED_HEAT_PCT: float              = CONFIG["MAX_CORRELATED_HEAT_PCT"]
HEAT_COOLOFF_LOSS_STREAK: int               = CONFIG["HEAT_COOLOFF_LOSS_STREAK"]
HEAT_COOLOFF_REDUCTION: float               = CONFIG["HEAT_COOLOFF_REDUCTION"]
CORRELATION_BUCKETS: dict                   = CONFIG["CORRELATION_BUCKETS"]

RISK_PCT_BY_CONVICTION: dict                = CONFIG["RISK_PCT_BY_CONVICTION"]
PARTIAL_SCHEDULE: list                      = CONFIG["PARTIAL_SCHEDULE"]

DRAWDOWN_TIER_1_PCT: float                  = CONFIG["DRAWDOWN_TIER_1_PCT"]
DRAWDOWN_TIER_2_PCT: float                  = CONFIG["DRAWDOWN_TIER_2_PCT"]
DRAWDOWN_TIER_3_PCT: float                  = CONFIG["DRAWDOWN_TIER_3_PCT"]
DRAWDOWN_TIER_1_RISK_MULT: float            = CONFIG["DRAWDOWN_TIER_1_RISK_MULT"]
DRAWDOWN_RECOVERY_HYSTERESIS: float         = CONFIG["DRAWDOWN_RECOVERY_HYSTERESIS"]

CONVICTION_DIRECT_ENTRY_THRESHOLD: int      = CONFIG["CONVICTION_DIRECT_ENTRY_THRESHOLD"]
MAX_PENDING_AGE_BARS: int                   = CONFIG["MAX_PENDING_AGE_BARS"]
APPROACHING_TARGET_THRESHOLD: float         = CONFIG["APPROACHING_TARGET_THRESHOLD"]
