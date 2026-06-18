import pytest
from datetime import datetime, timezone
from bot.structs import PortfolioState
from bot.portfolio.capitulation import (
    compute_liquidation_zscore,
    compute_oi_decline_pct,
    compute_price_drawdown_pct,
    deploy_capitulation_reserve_tranche,
    check_capitulation,
)
from bot.config import (
    LIQ_SIGMA_THRESHOLD,
    OI_DECLINE_PCT_7D,
    MEGA_WIPE_PRICE_DRAWDOWN,
    CAPITULATION_TRANCHE_DROP_PCT,
    CAPITULATION_TRANCHE_SIZE,
    CAPITULATION_DRAWDOWN_LOOKBACK_BARS,
)

# ──────────────────────────────────────────────────────────────────
# Unit helpers
# ──────────────────────────────────────────────────────────────────

def _make_liq_series(window: int = 480, spike_multiplier: float = 1.0) -> list:
    """Baseline of 1.0 with a current bar at spike_multiplier × mean + 3σ (approximately)."""
    baseline = [1.0] * window
    # Std of a constant series is 0 → use a small jitter to get a real std
    import random
    random.seed(42)
    baseline = [1.0 + random.gauss(0, 0.1) for _ in range(window)]
    mean = sum(baseline) / len(baseline)
    std = (sum((x - mean) ** 2 for x in baseline) / len(baseline)) ** 0.5
    current = mean + spike_multiplier * std
    return baseline + [current]


def _make_oi_series(days: int = 7, decline: float = 0.0) -> list:
    """OI series: constant at 1000, then drops by decline fraction at the end."""
    prior_bars = days * 24
    oi_prior = 1000.0
    oi_now = oi_prior * (1.0 - decline)
    series = [oi_prior] * (prior_bars + 1)
    series[-1] = oi_now
    return series


# ──────────────────────────────────────────────────────────────────
# compute_liquidation_zscore
# ──────────────────────────────────────────────────────────────────

def test_zscore_returns_zero_for_insufficient_data():
    assert compute_liquidation_zscore([1.0, 2.0], window=480) == 0.0


def test_zscore_returns_high_on_spike():
    series = _make_liq_series(window=480, spike_multiplier=3.0)
    z = compute_liquidation_zscore(series, window=480)
    assert z >= LIQ_SIGMA_THRESHOLD   # >= 2.0


def test_zscore_returns_low_on_normal_bar():
    series = _make_liq_series(window=480, spike_multiplier=0.5)
    z = compute_liquidation_zscore(series, window=480)
    assert z < LIQ_SIGMA_THRESHOLD


# ──────────────────────────────────────────────────────────────────
# compute_oi_decline_pct
# ──────────────────────────────────────────────────────────────────

def test_oi_decline_zero_when_no_change():
    series = _make_oi_series(days=7, decline=0.0)
    assert compute_oi_decline_pct(series, days=7) == pytest.approx(0.0)


def test_oi_decline_correct_fraction():
    series = _make_oi_series(days=7, decline=0.30)
    result = compute_oi_decline_pct(series, days=7)
    assert result == pytest.approx(0.30, abs=1e-6)


# ──────────────────────────────────────────────────────────────────
# compute_price_drawdown_pct
# ──────────────────────────────────────────────────────────────────

def test_price_drawdown_zero_at_high():
    closes = [100.0] * CAPITULATION_DRAWDOWN_LOOKBACK_BARS
    assert compute_price_drawdown_pct(closes) == pytest.approx(0.0)


def test_price_drawdown_correct_calculation():
    # Recent high was 100, current close is 75 → 25% drawdown
    closes = [100.0] * (CAPITULATION_DRAWDOWN_LOOKBACK_BARS - 1) + [75.0]
    result = compute_price_drawdown_pct(closes)
    assert result == pytest.approx(0.25, abs=1e-6)


# ──────────────────────────────────────────────────────────────────
# deploy_capitulation_reserve_tranche
# ──────────────────────────────────────────────────────────────────

def test_tranches_deploy_per_drop_level():
    """Each 10% drop deploys 25% of reserve. No double-deploy."""
    portfolio = PortfolioState(equity=100000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 20000.0

    # 10% drawdown → 1 tranche
    deployed = deploy_capitulation_reserve_tranche("BTC", portfolio, 0.10)
    assert deployed == pytest.approx(20000.0 * CAPITULATION_TRANCHE_SIZE)
    assert portfolio.capitulation_tranches_deployed["BTC"] == 1
    reserve_after_first = portfolio.fund_balances["capitulation_reserve"]

    # Same drawdown level → no new tranche (no double-deploy)
    deployed2 = deploy_capitulation_reserve_tranche("BTC", portfolio, 0.10)
    assert deployed2 == 0.0
    assert portfolio.capitulation_tranches_deployed["BTC"] == 1

    # 20% drawdown → 2nd tranche fires
    deployed3 = deploy_capitulation_reserve_tranche("BTC", portfolio, 0.20)
    assert deployed3 == pytest.approx(reserve_after_first * CAPITULATION_TRANCHE_SIZE)
    assert portfolio.capitulation_tranches_deployed["BTC"] == 2


def test_tranches_independent_per_asset():
    """Tranches for BTC and ETH are tracked independently."""
    portfolio = PortfolioState(equity=100000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 40000.0

    deploy_capitulation_reserve_tranche("BTC", portfolio, 0.10)
    assert portfolio.capitulation_tranches_deployed.get("ETH", 0) == 0

    deploy_capitulation_reserve_tranche("ETH", portfolio, 0.10)
    assert portfolio.capitulation_tranches_deployed["BTC"] == 1
    assert portfolio.capitulation_tranches_deployed["ETH"] == 1


# ──────────────────────────────────────────────────────────────────
# check_capitulation (full gate)
# ──────────────────────────────────────────────────────────────────

def test_check_capitulation_all_gates_pass():
    portfolio = PortfolioState(equity=70000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 20000.0

    # Build series that satisfy all three gates
    liq = _make_liq_series(window=480, spike_multiplier=3.0)        # z >= 2.0
    oi = _make_oi_series(days=7, decline=0.30)                       # decline >= 25%
    closes = [100.0] * (CAPITULATION_DRAWDOWN_LOOKBACK_BARS - 1) + [75.0]  # 25% DD >= 20%

    now = datetime.now(timezone.utc)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)

    assert portfolio.capitulation_detected_date == now
    assert portfolio.capitulation_tranches_deployed.get("BTC", 0) >= 1
    assert portfolio.fund_balances["capitulation_reserve"] < 20000.0


def test_check_capitulation_blocked_by_low_zscore():
    portfolio = PortfolioState(equity=70000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 20000.0

    liq = _make_liq_series(window=480, spike_multiplier=0.5)         # z < 2.0  ← gate fails
    oi = _make_oi_series(days=7, decline=0.30)
    closes = [100.0] * (CAPITULATION_DRAWDOWN_LOOKBACK_BARS - 1) + [75.0]

    now = datetime.now(timezone.utc)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)

    assert portfolio.capitulation_detected_date is None
    assert portfolio.fund_balances["capitulation_reserve"] == 20000.0


def test_check_capitulation_blocked_by_insufficient_oi_decline():
    portfolio = PortfolioState(equity=70000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 20000.0

    liq = _make_liq_series(window=480, spike_multiplier=3.0)
    oi = _make_oi_series(days=7, decline=0.05)                       # decline < 25% ← gate fails
    closes = [100.0] * (CAPITULATION_DRAWDOWN_LOOKBACK_BARS - 1) + [75.0]

    now = datetime.now(timezone.utc)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)

    assert portfolio.capitulation_detected_date is None
    assert portfolio.fund_balances["capitulation_reserve"] == 20000.0


def test_check_capitulation_blocked_by_insufficient_price_drawdown():
    portfolio = PortfolioState(equity=90000.0, equity_ath=100000.0)
    portfolio.fund_balances["capitulation_reserve"] = 20000.0

    liq = _make_liq_series(window=480, spike_multiplier=3.0)
    oi = _make_oi_series(days=7, decline=0.30)
    # Only 10% drawdown, below MEGA_WIPE threshold of 20%
    closes = [100.0] * (CAPITULATION_DRAWDOWN_LOOKBACK_BARS - 1) + [90.0]

    now = datetime.now(timezone.utc)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)

    assert portfolio.capitulation_detected_date is None
    assert portfolio.fund_balances["capitulation_reserve"] == 20000.0
