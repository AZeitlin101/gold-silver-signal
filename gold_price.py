"""
Fetches gold spot/futures price data and computes basic technical indicators.

Uses GoldAPI.io for current price and a lightweight in-memory history buffer
for computing moving averages / RSI. For real historical backtesting you'd
want a proper OHLCV source (e.g. Alpha Vantage, Yahoo Finance via yfinance,
or a paid futures data feed).
"""

import requests
import numpy as np
from collections import deque
from datetime import datetime, timezone

GOLD_API_URL = "https://www.goldapi.io/api/XAU/USD"

# In-memory rolling price history (swap for a real DB/timeseries store in production)
_price_history = deque(maxlen=200)


def fetch_current_price(api_key: str) -> dict:
    """Fetch the current gold spot price in USD."""
    headers = {"x-access-token": api_key, "Content-Type": "application/json"}
    resp = requests.get(GOLD_API_URL, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    price_point = {
        "price": data.get("price"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "open": data.get("open_price"),
        "high": data.get("high_price"),
        "low": data.get("low_price"),
        "prev_close": data.get("prev_close_price"),
    }
    _price_history.append(price_point["price"])
    return price_point


def _rsi(prices: list, period: int = 14) -> float:
    """Compute RSI (Relative Strength Index) over the given period."""
    if len(prices) < period + 1:
        return 50.0  # neutral default until we have enough history

    deltas = np.diff(prices[-(period + 1):])
    gains = deltas[deltas > 0].sum() / period
    losses = -deltas[deltas < 0].sum() / period

    if losses == 0:
        return 100.0
    rs = gains / losses
    return round(100 - (100 / (1 + rs)), 2)


def _moving_average(prices: list, period: int) -> float:
    if len(prices) < period:
        return float(np.mean(prices)) if prices else 0.0
    return round(float(np.mean(prices[-period:])), 2)


def get_technical_snapshot(api_key: str) -> dict:
    """
    Returns current price plus a technical score (0-100, where higher = more bullish).

    Scoring logic (simple starting heuristic — tune based on backtesting):
      - RSI < 30 (oversold) -> bullish tilt
      - RSI > 70 (overbought) -> bearish tilt
      - Price above short MA and short MA above long MA -> bullish trend
    """
    current = fetch_current_price(api_key)
    prices = list(_price_history)

    rsi = _rsi(prices)
    ma_short = _moving_average(prices, 10)
    ma_long = _moving_average(prices, 50)

    score = 50.0  # start neutral

    # RSI contribution (mean-reversion signal)
    if rsi < 30:
        score += 15
    elif rsi > 70:
        score -= 15
    else:
        # scale linearly between neutral zones
        score += (50 - rsi) * 0.2

    # Trend contribution
    if ma_short and ma_long:
        if current["price"] > ma_short > ma_long:
            score += 15
        elif current["price"] < ma_short < ma_long:
            score -= 15

    score = max(0.0, min(100.0, score))

    return {
        "current_price": current["price"],
        "rsi": rsi,
        "ma_short": ma_short,
        "ma_long": ma_long,
        "technical_score": round(score, 1),
        "history_length": len(prices),
    }
