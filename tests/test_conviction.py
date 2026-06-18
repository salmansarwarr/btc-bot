import pytest
from datetime import datetime, timezone
from bot.structs import SetupCandidate, BiasState, Direction, PivotFlag, PivotStrength, SetupType, ManagementMode, OHLCV_Bar
from bot.entry_risk.conviction import compute_conviction_score

def test_conviction_score_1():
    # Base score = 1.
    # HTF Bias = NEUTRAL (0 bonus)
    # No trigger_pivot, no divergence (0 bonus)
    # Total = 1
    cand = SetupCandidate(direction=Direction.UP)
    compute_conviction_score(cand, BiasState.NEUTRAL)
    
    assert cand.conviction_score == 1
    assert cand.management_mode == ManagementMode.AGGRESSIVE

def test_conviction_score_2_bias():
    # Base = 1
    # HTF Bias = BULLISH, dir = UP (+1)
    # No confluence (+0)
    # Total = 2
    cand = SetupCandidate(direction=Direction.UP)
    compute_conviction_score(cand, BiasState.BULLISH)
    
    assert cand.conviction_score == 2
    assert cand.management_mode == ManagementMode.AGGRESSIVE

def test_conviction_score_2_confluence_divergence():
    # Base = 1
    # HTF Bias = BEARISH, dir = UP (+0)
    # Confluence = MOMENTUM_DIVERGENCE (+1)
    # Total = 2
    cand = SetupCandidate(direction=Direction.UP, setup_type=SetupType.MOMENTUM_DIVERGENCE)
    compute_conviction_score(cand, BiasState.BEARISH)
    
    assert cand.conviction_score == 2
    assert cand.management_mode == ManagementMode.AGGRESSIVE

def test_conviction_score_3_bias_and_major_pivot():
    # Base = 1
    # HTF Bias = DOWN (+1)
    # Confluence = MAJOR Pivot in percentile (+1)
    # Total = 3
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 50000.0, Direction.UP, PivotStrength.MAJOR, 0, t0)
    cand = SetupCandidate(direction=Direction.DOWN, trigger_pivot=pivot)
    
    # Create bars for percentile
    # To pass the Resistance (UP) pivot percentile check, price >= highest - (range * 0.10)
    # Highest = 50000, Lowest = 40000, range = 10000. 10% = 1000. Threshold = 49000.
    # Pivot is 50000, so it passes.
    bars = [
        OHLCV_Bar(t0, 40000, 40000, 40000, 40000, 100, "H1", "BTC"),
        OHLCV_Bar(t0, 50000, 50000, 50000, 50000, 100, "H1", "BTC")
    ]
    
    compute_conviction_score(cand, BiasState.BEARISH, bars)
    
    assert cand.conviction_score == 3
    assert cand.management_mode == ManagementMode.CONSERVATIVE

def test_conviction_score_2_major_pivot_fails_percentile():
    # Base = 1
    # HTF Bias = DOWN (+1)
    # Confluence = MAJOR Pivot but FAILS percentile (+0)
    # Total = 2
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 45000.0, Direction.UP, PivotStrength.MAJOR, 0, t0) # Pivot at 45000
    cand = SetupCandidate(direction=Direction.DOWN, trigger_pivot=pivot)
    
    bars = [
        OHLCV_Bar(t0, 40000, 40000, 40000, 40000, 100, "H1", "BTC"),
        OHLCV_Bar(t0, 50000, 50000, 50000, 50000, 100, "H1", "BTC") # Range 40k-50k. Top 10% is > 49k. 45k fails.
    ]
    
    compute_conviction_score(cand, BiasState.BEARISH, bars)
    
    assert cand.conviction_score == 2
    assert cand.management_mode == ManagementMode.AGGRESSIVE

def test_conviction_score_fractional_bonuses():
    # Base = 1
    # HTF Bias = NEUTRAL (+0)
    # Confluence = MINOR pivot + first reaction (+0.5), Deep Pullback (+0.5)
    # Total = 1 + 0.5 + 0.5 = 2.0
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 45000.0, Direction.UP, PivotStrength.MINOR, 0, t0, first_reaction_confirmed=True)
    cand = SetupCandidate(direction=Direction.DOWN, trigger_pivot=pivot, deep_pullback_consolidation_confluence=True)
    
    compute_conviction_score(cand, BiasState.NEUTRAL)
    
    assert cand.conviction_score == 2
    assert cand.management_mode == ManagementMode.AGGRESSIVE
    
def test_conviction_score_fractional_rounding():
    # Base = 1
    # HTF Bias = DOWN (+1)
    # Confluence = MINOR pivot + first reaction (+0.5) -> total = 2.5
    # Should round up to 3!
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 45000.0, Direction.UP, PivotStrength.MINOR, 0, t0, first_reaction_confirmed=True)
    cand = SetupCandidate(direction=Direction.DOWN, trigger_pivot=pivot)
    
    compute_conviction_score(cand, BiasState.BEARISH)
    
    assert cand.conviction_score == 3
    assert cand.management_mode == ManagementMode.CONSERVATIVE
