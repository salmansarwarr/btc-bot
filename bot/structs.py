"""
structs.py — Shared dataclass and enum definitions
===================================================

**Spec references:**
  - Part VI  — Additional State / Struct Additions Required
  - Doc-3    — Original struct definitions (TradeState, PortfolioState, etc.)
  - I-6      — stall_band_counter, expiry_tightened added to TradeState
  - II-2     — first_reaction_confirmed added to PivotFlag
  - II-4     — cdc_qualifies_zero_tolerance added to TradeJournalEntry
  - II-6     — deep_pullback_consolidation_confluence added to SetupCandidate
  - II-7     — trap_moved_away added to TradeState
  - II-8     — liquidation_proxy_method added to AssetConfig
  - II-11    — effective_max_heat added to PortfolioState
  - III-3    — capitulation_tranches_deployed added to PortfolioState
  - III-6    — ema_50_buffer added to IndicatorState

All fields are type-annotated; default values are set where the spec defines
them.  No business logic lives here — this file is pure data definitions.

Import convention:
    from bot.structs import (
        Direction, SetupClass, SetupType, BiasState, TrendClass,
        PivotStrength, ManagementMode, LiquidationProxyMethod,
        OHLCV_Bar, PivotFlag, SetupCandidate, TradeState,
        PortfolioState, MarketBasket, IndicatorState,
        AssetConfig, ExternalFeedState,
        TradeJournalEntry, SkippedSetupLogEntry,
        PendingFTAConfirmation,
    )
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Deque, Dict, List, Optional
import random, string


# ============================================================================
# Enumerations
# ============================================================================


class Direction(Enum):
    """
    Market or trade direction.

    Spec §1.x / Doc-3 §1.
    """
    UP = auto()
    DOWN = auto()
    NEUTRAL = auto()


class BiasState(Enum):
    """
    HTF directional bias produced by ``update_htf_bias``.

    Spec §1.3; Resolution I-1 (lookback-gated NEUTRAL).
    """
    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()       # no factual MSB within N_HTF_BIAS_LOOKBACK bars


class TrendClass(Enum):
    """
    Trend classification applied to a timeframe.

    Spec §1.2; Doc-2 §1 (Proxy A+B combined gate).
    """
    RANGING = auto()
    TRENDING = auto()
    LOCKOUT_TREND = auto()  # strong trend — restricted setup menu applies


class PivotStrength(Enum):
    """
    Relative importance of a detected pivot.

    Spec §2.x; Doc-2 §3 (major via N-fractal + percentile at scoring time).
    """
    MAJOR = auto()
    MINOR = auto()


class SetupClass(Enum):
    """
    High-level setup family.  Used in trade management logic (e.g. stalling
    re-entry detection applies only to TRAP class — Resolution II-7).
    """
    TRAP = auto()           # SFP, CDC, Pattern Failure
    CONTINUATION = auto()   # MSB-pullback, shallow/deep retracement
    HTF_SWING = auto()      # higher-timeframe swing entries
    REVERSAL = auto()       # momentum divergence, liquidation flush


class SetupType(Enum):
    """
    Granular setup identifier.  Matches the detection function one-to-one.

    Spec §2.x; Resolution I-7 (CDC and PatternFailure share detect_cdc logic).
    """
    SFP = auto()                # Swing Failure Pattern
    CDC = auto()                # Clean-Break, Drift, Close — no-interaction
    PATTERN_FAILURE = auto()    # CDC viewed from the failure side (I-7)
    MSB_SHALLOW = auto()        # MSB + shallow pullback (0.236–0.382)
    MSB_DEEP = auto()           # MSB + deep pullback (0.55–0.85)
    OPEN_DRIVE = auto()         # Candle Open Drive
    CONSOLIDATION_ENTRY = auto()  # Consolidation breakout entry
    MOMENTUM_DIVERGENCE = auto()  # RSI divergence setup
    LIQUIDATION_FLUSH = auto()    # post-liquidation flush entry
    SR_FLIP = auto()              # Support/Resistance Flip


class ManagementMode(Enum):
    """
    Trade management style assigned by conviction score.

    Spec §5.1; Resolution I-3 (aggressive = trading frequency, not confidence).
    Note from I-3: aggressive mode means both faster exits (FTA reject → close)
    and faster adds (FTA break → compound).  The label refers to activity level,
    not directional conviction strength.
    """
    AGGRESSIVE = auto()    # conviction score ≤ 2
    CONSERVATIVE = auto()  # conviction score = 3


class LiquidationProxyMethod(Enum):
    """
    Per-asset liquidation-spike detection method.

    Resolution II-8: hierarchy is C (OI_PCT) → B (PERCENTILE) → A (ZSCORE).
    Assigned in AssetConfig at bot initialisation time based on data quality.
    """
    ZSCORE = auto()      # Proxy A — 20-day z-score (fallback)
    PERCENTILE = auto()  # Proxy B — 90-day percentile (requires ≥90 days history)
    OI_PCT = auto()      # Proxy C — liquidation notional / OI at window start (preferred)


class DrawdownTier(Enum):
    """
    Portfolio drawdown protection tier.

    Spec §8.4; Resolution I-10 (intermediate recovery step); Doc-2 §16.
    """
    TIER_0 = 0  # normal trading
    TIER_1 = 1  # risk halved (drawdown ≥ DRAWDOWN_TIER_1_PCT = 10%)
    TIER_2 = 2  # trading halted (drawdown ≥ DRAWDOWN_TIER_2_PCT = 20%)
    TIER_3 = 3  # emergency mode (drawdown ≥ DRAWDOWN_TIER_3_PCT = 30%)


class EventType(Enum):
    """
    Trade lifecycle event types recorded in the journal.

    Doc-3 §3.x (log_event call sites).
    """
    ENTRY = auto()
    PARTIAL_EXIT = auto()
    FULL_EXIT = auto()
    STOP_MOVED = auto()
    COMPOUNDED = auto()
    STALLING_FLAG = auto()
    EXPIRY_CLOSE = auto()
    FTA_BREAK_COMPOUND = auto()
    FTA_REJECT_CLOSE = auto()
    SKIPPED = auto()


# ============================================================================
# Core market-data primitives
# ============================================================================


@dataclass
class OHLCV_Bar:
    """
    A single OHLCV candlestick bar.

    Used in ``buffer[asset][timeframe]`` rolling deques.
    Doc-3 §1 (data model).
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str          # e.g. "H1", "D1", "W1"
    asset: str


@dataclass
class MarketBasket:
    """
    Broad-market reference data used by the relative-strength filter.

    Spec §2.11; Resolution I-8; Doc-2 Additional item C (Proxy A — BTC+ETH).
    ``btc_eth_avg_24h_change`` is the operative field; ``top20_avg_24h_change``
    is stored for future backtest comparison but is not consumed in any logic.
    """
    btc_eth_avg_24h_change: float = 0.0    # primary filter field (Proxy A)
    top20_avg_24h_change: float = 0.0      # unused in logic; retained for analysis
    last_updated: Optional[datetime] = None


@dataclass
class IndicatorState:
    """
    Current-bar indicator values for one (asset, timeframe) pair.

    Doc-3 §1 (Indicators registry).
    Resolution III-6: ``ema_50_buffer`` is a 15-value rolling deque so that
    ``ema_50_at_lag(n)`` can be serviced without re-scanning the OHLCV buffer.
    """
    asset: str
    timeframe: str

    # Trend / bias indicators
    adx: float = 0.0
    efficiency_ratio: float = 0.0       # Kaufman Efficiency Ratio
    ema_50: float = 0.0
    ema_50_buffer: Deque[float] = field(
        default_factory=lambda: deque(maxlen=15)
    )                                   # NEW III-6: rolling 15-bar EMA-50 history

    # Volatility
    atr_14: float = 0.0                 # ATR(14) — used throughout as the volatility unit

    # Momentum
    rsi_14: float = 0.0

    # Raw price data reference (pointer into OHLCV buffer — not duplicated)
    last_bar_timestamp: Optional[datetime] = None


@dataclass
class ExternalFeedState:
    """
    External data feeds for one asset: open interest, funding rate, liquidations.

    Resolution II-8 (liquidation proxy selection), III-8 (OI decline calculation).
    """
    asset: str
    oi_hourly: List[float] = field(default_factory=list)        # open interest timeseries (newest last)
    liq_hourly: List[float] = field(default_factory=list)       # liquidation notional timeseries
    funding_rate_history: List[float] = field(default_factory=list)
    liq_history_days: int = 0                                   # how many days of liquidation history available
    oi_history_days: int = 0                                    # how many days of OI history available


@dataclass
class AssetConfig:
    """
    Per-asset configuration set at bot initialisation.

    Resolution II-8: ``liquidation_proxy_method`` varies by data quality.
    Resolution III-2: correlation bucket assigned here.
    """
    symbol: str
    correlation_bucket: str = "OTHER"   # III-2: maps asset to heat-cap bucket
    liquidation_proxy_method: LiquidationProxyMethod = LiquidationProxyMethod.ZSCORE  # II-8
    active_timeframes: List[str] = field(default_factory=lambda: ["H1", "D1"])


# ============================================================================
# Setup detection structs
# ============================================================================


@dataclass
class PivotFlag:
    """
    A detected swing pivot with metadata used in setup detection and scoring.

    Doc-3 §1 (pivot registry).
    Part VI (II-2): ``first_reaction_confirmed`` added.
    """
    asset: str
    timeframe: str
    price: float
    direction: Direction            # UP = swing high, DOWN = swing low
    strength: PivotStrength
    bar_index: int                  # bar number at time of detection
    timestamp: datetime

    # Doc-2 §4 (Proxy B) / Resolution II-2
    first_reaction_confirmed: bool = False
    """
    Set to True when price approaches this (MINOR) pivot and reverses by at
    least 0.25 × ATR(14) on first contact.  Contributes MINOR_PIVOT_RESPECTED_BONUS
    to conviction score.  See Resolution II-2.
    """


@dataclass
class SetupCandidate:
    """
    A detected setup awaiting entry evaluation.

    Doc-3 §2 / §3.x (detect_* return values fed to evaluate_entry).
    Part VI (II-6): ``deep_pullback_consolidation_confluence`` added.
    """
    id: str = field(default_factory=lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=32)))
    asset: str = ""
    timeframe: str = ""
    setup_type: Optional[SetupType] = None
    setup_class: Optional[SetupClass] = None
    direction: Optional[Direction] = None
    trigger_pivot: Optional[PivotFlag] = None
    detected_at: Optional[datetime] = None
    detected_bar_index: int = 0
    
    # Eventual entry and stop references proposed by the setup logic
    trigger_price: float = 0.0
    stop_price: float = 0.0

    # Conviction inputs (populated by compute_conviction_score)
    conviction_score: int = 0
    management_mode: Optional[ManagementMode] = None

    # CDC-specific: when include_pattern_failure=True, direction/type are inverted
    # Resolution I-7: detect_cdc handles both CDC and PATTERN_FAILURE via this flag.
    is_pattern_failure_mode: bool = False

    # Doc-2 §8 / Resolution II-6
    deep_pullback_consolidation_confluence: bool = False
    """
    True when a DEEP pullback (MSB_DEEP setup) also re-enters the prior
    consolidation range.  Adds DEEP_PULLBACK_CONFLUENCE_BONUS to conviction
    score.  See Resolution II-6.
    """

    # Doc-2 §6 / Resolution II-4 (populated at entry-log time)
    cdc_qualifies_zero_tolerance: Optional[bool] = None
    """
    For CDC / PATTERN_FAILURE setups: True if no wick touched the level at all
    (Proxy B — zero-touch).  Populated at log time for post-hoc journal analysis.
    No operational effect.  See Resolution II-4.
    """


@dataclass
class PendingFTAConfirmation:
    """
    A setup candidate waiting for FTA (First Target Area) confirmation before
    entry is triggered.

    Doc-3 ``check_pending_fta_confirmations``; Resolution III-1.
    """
    candidate: SetupCandidate = field(default_factory=SetupCandidate)
    created_bar_index: int = 0      # idea-timeframe bar index at creation
    created_at: Optional[datetime] = None
    fta_price: float = 0.0


# ============================================================================
# Trade state
# ============================================================================


@dataclass
class PartialExitRecord:
    """
    Records a single partial exit event on a trade.

    Doc-3 ``compute_realized_r`` / ``check_fta_interaction``.
    Resolution III-7: signed_pnl helper uses (direction, entry_price, exit_price).
    """
    bar_index: int
    timestamp: datetime
    price: float
    fraction: float     # fraction of original position closed (e.g. 0.33)
    r_realized: float   # realised R-multiple for this tranche


@dataclass
class TradeState:
    """
    Full mutable state of one active trade position.

    Doc-3 §3.x (primary trade state machine).
    Part VI / Resolution I-6:  ``stall_band_counter``, ``expiry_tightened`` added.
    Part VI / Resolution II-7: ``trap_moved_away`` added.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    asset: str = ""
    timeframe: str = ""                         # idea timeframe
    setup_type: Optional[SetupType] = None
    setup_class: Optional[SetupClass] = None
    direction: Optional[Direction] = None
    management_mode: Optional[ManagementMode] = None

    # Entry & sizing
    entry_price: float = 0.0
    entry_bar_index: int = 0
    entry_timestamp: Optional[datetime] = None
    position_size: float = 0.0                  # current (post-partial) size in base units
    initial_position_size: float = 0.0          # original full size
    initial_risk_usd: float = 0.0               # dollar risk at entry (for R calculation)
    _heat_risk_usd: float = 0.0                 # unscaled risk reserved for heat accounting only (Change 10 v3)
    conviction_score: int = 0

    # Stop & target
    stop_price: float = 0.0
    targets: List[float] = field(default_factory=list)     # FTA levels in order
    current_target_index: int = 0                           # next target not yet taken

    # Pivot used to generate the setup (for stalling / re-entry detection)
    pivot_used: Optional[PivotFlag] = None

    # Partial exits taken
    partials_taken: List[PartialExitRecord] = field(default_factory=list)
    partials_scheduled: List[float] = field(default_factory=list)   # remaining PARTIAL_SCHEDULE fractions

    # Active-trade counters & flags
    bars_in_trade: int = 0

    stall_band_counter: int = 0
    """
    NEW (I-6): consecutive bar count where price has remained within
    STALL_ATR_MULT × ATR(14) of the stall reference price.
    Incremented by check_stalling; reset when price exits the band.
    """

    expiry_tightened: bool = False
    """
    NEW (I-6): True once the stop has been tightened by the time-expiry
    logic (check_time_expiry).  Prevents double-tightening.
    """

    trap_moved_away: bool = False
    """
    NEW (II-7): For TRAP-class setups — True once price has moved at least
    STALL_ATR_MULT × ATR(14) away from entry, enabling re-entry detection.
    See Resolution II-7 and check_stalling.
    """

    stalling_flag: bool = False                 # set when stalling is confirmed

    # Realised P&L tracking
    realized_r: float = 0.0
    exit_price: float = 0.0     # NEW: stamped by close_trade, read by log_trade_closed
    is_open: bool = True


# ============================================================================
# Portfolio state
# ============================================================================


@dataclass
class PortfolioState:
    """
    Singleton mutable state for the entire portfolio.

    Doc-3 §4.x (portfolio-level logic).
    Part VI / Resolution II-11: ``effective_max_heat`` added.
    Part VI / Resolution III-3: ``capitulation_tranches_deployed`` added.
    """
    equity: float = 0.0
    equity_ath: float = 0.0                     # all-time-high equity level
    fund_balances: Dict[str, float] = field(
        default_factory=lambda: {"active": 0.0, "capitulation_reserve": 0.0}
    )

    # Open-trade registry
    open_trades: Dict[str, TradeState] = field(default_factory=dict)   # trade_id → TradeState

    # Heat tracking (Resolution II-11)
    effective_max_heat: float = 0.0
    """
    NEW (II-11): Current operative heat ceiling, kept in sync by
    update_heat_cooloff.  Normally equals CONFIG["MAX_HEAT_PCT"] (6%).
    Reduced during consecutive-loss streaks by HEAT_COOLOFF_REDUCTION.
    enforce_portfolio_heat must reference THIS field, not CONFIG["MAX_HEAT_PCT"]
    directly — that was the bug described in II-11.
    """

    # Drawdown protection
    drawdown_tier: DrawdownTier = DrawdownTier.TIER_0

    # Loss-streak tracking (feeds heat cooloff and drawdown early-warning)
    consecutive_losses: int = 0
    last_realization_date: Optional[datetime] = None

    # Capitulation reserve deployment tracking (Resolution III-3)
    capitulation_tranches_deployed: Dict[str, int] = field(default_factory=dict)
    """
    NEW (III-3): {asset_symbol: number_of_tranches_already_deployed}.
    deploy_capitulation_reserve_tranche uses this to avoid re-deploying
    tranches on subsequent calls.  See Resolution III-3 and Spec §8.3.
    """

    capitulation_detected_date: Optional[datetime] = None  # III-3: date of first capitulation signal


# ============================================================================
# Journaling structs
# ============================================================================


@dataclass
class TradeJournalEntry:
    """
    Immutable record written to the trade journal when a trade is closed.

    Doc-3 §5.x (journaling).
    Part VI / Resolution II-4: ``cdc_qualifies_zero_tolerance`` added.
    """
    trade_id: str
    asset: str
    timeframe: str
    setup_type: Optional[SetupType]
    setup_class: Optional[SetupClass]
    direction: Optional[Direction]
    management_mode: Optional[ManagementMode]
    conviction_score: int

    entry_price: float
    entry_timestamp: datetime
    exit_price: float
    exit_timestamp: datetime

    initial_risk_usd: float
    realized_r: float
    partial_exits: List[PartialExitRecord] = field(default_factory=list)

    drawdown_tier_at_entry: DrawdownTier = DrawdownTier.TIER_0
    htf_bias_at_entry: Optional[BiasState] = None
    trend_class_at_entry: Optional[TrendClass] = None

    # Resolution II-4 (CDC / PATTERN_FAILURE setups only)
    cdc_qualifies_zero_tolerance: Optional[bool] = None
    """
    NEW (II-4): For CDC and PATTERN_FAILURE setups — True if the entry would
    also qualify under Proxy B (no wick contact at all with the level).
    Populated at close time for post-hoc frequency/quality analysis.
    No operational effect on trade management.
    """

    notes: str = ""


@dataclass
class SkippedSetupLogEntry:
    """
    Record written when a detected setup is explicitly rejected.

    Doc-3 §3.x (log_skipped_setup call sites); Resolution I-8 (RELATIVE_STRENGTH_FILTER reason).
    """
    candidate_id: str
    asset: str
    timeframe: str
    setup_type: Optional[SetupType]
    direction: Optional[Direction]
    rejected_at: datetime
    reason: str                 # e.g. "RELATIVE_STRENGTH_FILTER", "HEAT_CAP", "LOW_CONVICTION"
    conviction_score: int = 0

    # Passive dual-classification logging (Resolution II-4)
    cdc_qualifies_zero_tolerance: Optional[bool] = None
