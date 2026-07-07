"""Simple historical backtest for the gold signal engine."""

from typing import List, Dict, Any


def run_backtest(prices: List[float], weights: Dict[str, float]) -> Dict[str, Any]:
    """Simulate a naive strategy using rolling composite-like signals.

    The logic is intentionally simple and deterministic so it can run without
    external data or complex dependencies. It uses a 3-period moving average
    crossover and a simple directional bias based on recent price change.
    """
    if not prices:
        return {
            "total_return": 0.0,
            "win_rate": 0.0,
            "trades": 0,
            "equity_curve": [],
        }

    equity_curve: List[float] = []
    trades = 0
    wins = 0
    entry_price = None
    position = 0

    for i in range(1, len(prices)):
        prev = prices[i - 1]
        curr = prices[i]
        short_ma = sum(prices[max(0, i - 2):i + 1]) / min(3, i + 1)
        long_ma = sum(prices[max(0, i - 5):i + 1]) / min(6, i + 1)
        momentum = curr - prev

        signal = 50.0
        if short_ma > long_ma:
            signal += 15.0
        if momentum > 0:
            signal += 10.0
        if momentum < 0:
            signal -= 10.0

        if signal >= 60 and position == 0:
            entry_price = curr
            position = 1
            trades += 1
        elif signal <= 40 and position == 1:
            if entry_price is not None:
                pnl = (curr / entry_price) - 1
                if pnl > 0:
                    wins += 1
            entry_price = None
            position = 0

        equity_curve.append(curr if position == 0 else curr)

    total_return = 0.0
    if prices and len(prices) > 1:
        total_return = (prices[-1] / prices[0]) - 1

    win_rate = round(wins / trades, 2) if trades else 0.0

    return {
        "total_return": round(total_return, 4),
        "win_rate": win_rate,
        "trades": trades,
        "equity_curve": equity_curve,
    }
