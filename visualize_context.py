"""
visualize_context.py — Generate an interactive chart for market context validation.
"""
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

from bot.data_ingestion import ohlcv_buffer
from bot.market_context import pivot_registry, htf_bias
from bot.indicators import registry
from bot.structs import PivotStrength, Direction, BiasState

def run_simulation(symbol="BTC/USDT", timeframe="1d", limit=400):
    print(f"Fetching {limit} bars for {symbol} on {timeframe}...")
    bars = ohlcv_buffer.fetch_historical_bars('binance', symbol, timeframe, limit=limit)
    
    dates = []
    opens, highs, lows, closes = [], [], [], []
    ema50 = []
    biases = []
    
    print("Running bot logic per bar...")
    for bar in bars:
        # 1. Ingest bar (updates indicators via registry)
        ohlcv_buffer.on_bar_close(bar)
        
        # 2. Update pivots
        pivot_registry.update_pivot_registry(bar.asset, bar.timeframe)
        
        # 3. Update HTF Bias
        htf_bias.update_htf_bias(bar.asset)
        
        # Capture state for plotting
        dates.append(bar.timestamp)
        opens.append(bar.open)
        highs.append(bar.high)
        lows.append(bar.low)
        closes.append(bar.close)
        
        ind_state = registry.get_or_create(bar.asset, bar.timeframe)
        ema50.append(ind_state.ema_50 if ind_state.ema_50 > 0 else None)
        
        # Bias is only updated on D1 close, we are running D1 so it's fine
        biases.append(htf_bias.htf_bias.get(bar.asset, BiasState.NEUTRAL))
        
    if bars:
        internal_tf = bars[0].timeframe
        pivots = pivot_registry.pivot_registry.get(bars[0].asset, {}).get(internal_tf, [])
    else:
        pivots = []
    
    print("Rendering chart...")
    fig = go.Figure()
    
    # 1. Background shading for Bias
    # We create a colored background using vrects where bias is consistent
    current_bias = biases[0]
    start_idx = 0
    
    def get_color(bias):
        if bias == BiasState.BULLISH: return "rgba(0, 255, 0, 0.1)"
        if bias == BiasState.BEARISH: return "rgba(255, 0, 0, 0.1)"
        return "rgba(128, 128, 128, 0.1)" # NEUTRAL
        
    for i in range(1, len(biases)):
        if biases[i] != current_bias or i == len(biases) - 1:
            fig.add_vrect(
                x0=dates[start_idx], x1=dates[i],
                fillcolor=get_color(current_bias),
                opacity=0.5,
                layer="below", line_width=0,
            )
            current_bias = biases[i]
            start_idx = i

    # 2. Candlesticks
    fig.add_trace(go.Candlestick(
        x=dates, open=opens, high=highs, low=lows, close=closes,
        name="Price", increasing_line_color='green', decreasing_line_color='red'
    ))
    
    # 3. EMA 50
    fig.add_trace(go.Scatter(
        x=dates, y=ema50, mode='lines', name='EMA 50', line=dict(color='orange', width=2)
    ))
    
    # 4. Major Pivots
    major_p_dates = []
    major_p_prices = []
    major_p_colors = []
    for p in pivots:
        if p.strength == PivotStrength.MAJOR:
            major_p_dates.append(p.timestamp)
            major_p_prices.append(p.price)
            major_p_colors.append('blue' if p.direction == Direction.UP else 'purple')
            
    fig.add_trace(go.Scatter(
        x=major_p_dates, y=major_p_prices, mode='markers',
        marker=dict(size=12, symbol='circle-open', color=major_p_colors, line=dict(width=2)),
        name='Major Pivots'
    ))
    
    fig.update_layout(
        title=f"Market Context Validation: {symbol} ({timeframe})<br><sup>Background: Green=Bullish, Red=Bearish, Grey=Neutral | Circles=Major Pivots</sup>",
        xaxis_title="Date",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=800
    )
    
    out_file = "market_context_chart.html"
    fig.write_html(out_file)
    print(f"Chart successfully saved to {out_file}")

if __name__ == "__main__":
    run_simulation()
