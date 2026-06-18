"""
Integration tests for entry_gate.py — evaluate_entry.
"""
import pytest
from datetime import datetime, timezone

from bot.structs import (
    BiasState,
    Direction,
    ManagementMode,
    MarketBasket,
    SetupCandidate,
    SetupType,
    TradeState,
    TrendClass,
)
from bot.entry_risk.entry_gate import EvaluateResult, evaluate_entry
from bot.config import RISK_PCT_BY_CONVICTION, PARTIAL_SCHEDULE


# ── shared fixtures ──────────────────────────────────────────────────────────

def _make_candidate(
    direction=Direction.UP,
    setup_type=SetupType.SFP,
    trigger_price=100.0,
    stop_price=90.0,
    conviction_score=0,  # pre-scoring; evaluate_entry will overwrite
) -> SetupCandidate:
    return SetupCandidate(
        asset="BTC",
        timeframe="H1",
        setup_type=setup_type,
        direction=direction,
        trigger_price=trigger_price,
        stop_price=stop_price,
        conviction_score=conviction_score,
    )


def _red_market(avg=-0.02) -> MarketBasket:
    """BTC/ETH basket down 2%."""
    return MarketBasket(btc_eth_avg_24h_change=avg)


def _green_market(avg=0.015) -> MarketBasket:
    return MarketBasket(btc_eth_avg_24h_change=avg)


NOW = datetime(2026, 6, 13, 0, 0, 0, tzinfo=timezone.utc)
EQUITY = 10_000.0
ATR = 10.0


# ── (a) Relative-strength filter: LOCKOUT_TREND UP, red day, underperformer ─

class TestRelativeStrengthFilter:

    def test_lockout_trend_red_day_underperformer_is_rejected(self):
        """
        LOCKOUT_TREND + UP + market down -2% + asset down -3%  →  rejected.
        """
        cand = _make_candidate(direction=Direction.UP)
        market = _red_market(avg=-0.02)

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BULLISH,      # HTF bullish → +1 to conviction
            trend_class=TrendClass.LOCKOUT_TREND,
            market_basket=market,
            asset_24h_change=-0.03,          # worse than the -2% market
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        assert result.rejected, "Expected RELATIVE_STRENGTH_FILTER veto"
        assert result.skipped is not None
        assert result.skipped.reason == "RELATIVE_STRENGTH_FILTER"
        assert result.skipped.asset == "BTC"
        assert result.trade is None
        assert result.pending is None

    def test_lockout_trend_red_day_outperformer_passes(self):
        """
        LOCKOUT_TREND + UP + market down -2% + asset down only -0.5%  →  passes through.
        """
        cand = _make_candidate(direction=Direction.UP)
        market = _red_market(avg=-0.02)

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BULLISH,
            trend_class=TrendClass.LOCKOUT_TREND,
            market_basket=market,
            asset_24h_change=-0.005,         # outperforms the market basket
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        # Should NOT be skipped by RS filter; may be pending or approved
        assert not result.rejected

    def test_lockout_trend_green_day_always_passes(self):
        """
        On a green market day the filter is inactive regardless of asset change.
        """
        cand = _make_candidate(direction=Direction.UP)
        market = _green_market(avg=0.01)

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BULLISH,
            trend_class=TrendClass.LOCKOUT_TREND,
            market_basket=market,
            asset_24h_change=-0.10,          # very weak asset
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        assert not result.rejected, "Green market day must never trigger RS filter"

    def test_filter_does_not_apply_to_down_candidates(self):
        """RS filter must never veto SHORT setups."""
        cand = _make_candidate(direction=Direction.DOWN)
        market = _red_market(avg=-0.05)

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BEARISH,
            trend_class=TrendClass.LOCKOUT_TREND,
            market_basket=market,
            asset_24h_change=-0.10,
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        assert not result.rejected


# ── (b) Valid candidate → fully populated TradeState ─────────────────────────

class TestApprovedEntry:

    def test_fully_populated_trade_state(self):
        """
        A conviction-3 candidate in a trending market produces a fully populated
        TradeState with correct stop, size, and management_mode=CONSERVATIVE.

        Score breakdown:
          +1 base (always)
          +1 HTF BULLISH aligns with UP direction
          +1 confluence = MOMENTUM_DIVERGENCE
          = 3 → CONSERVATIVE
        """
        cand = _make_candidate(
            direction=Direction.UP,
            setup_type=SetupType.MOMENTUM_DIVERGENCE,
            trigger_price=100.0,
            stop_price=90.0,
        )

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BULLISH,
            trend_class=TrendClass.TRENDING,
            market_basket=_green_market(),
            asset_24h_change=0.02,
            account_equity=EQUITY,
            atr=ATR,
            bar_index=42,
            now=NOW,
        )

        assert result.approved, f"Expected approval, got: {result}"
        trade = result.trade
        assert isinstance(trade, TradeState)

        # Management mode
        assert trade.management_mode == ManagementMode.CONSERVATIVE
        assert cand.conviction_score == 3

        # Entry price preserved
        assert trade.entry_price == 100.0

        # Stop: MOMENTUM_DIVERGENCE uses fallback → entry - MIN_STOP_ATR_MULT * ATR
        from bot.config import MIN_STOP_ATR_MULT
        expected_stop = 100.0 - MIN_STOP_ATR_MULT * ATR
        assert trade.stop_price == pytest.approx(expected_stop, rel=1e-6)

        # Position size: (equity × risk_pct) / |entry - stop|
        risk_pct = RISK_PCT_BY_CONVICTION[3]
        expected_size = (EQUITY * risk_pct) / abs(trade.entry_price - trade.stop_price)
        assert trade.position_size == pytest.approx(expected_size, rel=1e-6)
        assert trade.initial_position_size == trade.position_size

        # Risk in USD
        expected_risk_usd = abs(trade.entry_price - trade.stop_price) * trade.position_size
        assert trade.initial_risk_usd == pytest.approx(expected_risk_usd, rel=1e-6)

        # Partial schedule seeded
        assert trade.partials_scheduled == list(PARTIAL_SCHEDULE)

        # Bar index and timestamp
        assert trade.entry_bar_index == 42
        assert trade.entry_timestamp == NOW

    def test_aggressive_mode_for_score_2(self):
        """
        Score 2 candidate → AGGRESSIVE mode.

        Score: +1 base + 1 HTF align + 0 confluence (SFP, no pivot) = 2.
        """
        cand = _make_candidate(
            direction=Direction.DOWN,
            setup_type=SetupType.SFP,
            trigger_price=100.0,
        )

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BEARISH,       # aligns with DOWN → +1
            trend_class=TrendClass.TRENDING,
            market_basket=_green_market(),
            asset_24h_change=0.0,
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        # Score = 2 → AGGRESSIVE + direct entry (threshold = 2)
        assert cand.conviction_score == 2
        assert result.approved
        assert result.trade.management_mode == ManagementMode.AGGRESSIVE

    def test_score_1_routed_to_pending(self):
        """
        Score 1 candidate is below CONVICTION_DIRECT_ENTRY_THRESHOLD → pending.
        Score: +1 base + 0 HTF misalign + 0 confluence = 1.
        """
        cand = _make_candidate(
            direction=Direction.UP,
            setup_type=SetupType.SFP,
        )

        result = evaluate_entry(
            candidate=cand,
            htf_bias=BiasState.BEARISH,      # opposes UP direction → no bias bonus
            trend_class=TrendClass.RANGING,
            market_basket=_green_market(),
            asset_24h_change=0.0,
            account_equity=EQUITY,
            atr=ATR,
            now=NOW,
        )

        assert result.needs_fta, f"Expected pending, got: {result}"
        assert cand.conviction_score == 1
        assert result.pending.candidate is cand
        assert result.pending.created_at == NOW
