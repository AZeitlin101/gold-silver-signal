"""Generate simple historical time-series data for the dashboard chart."""

from typing import List


def get_sample_history() -> List[float]:
    """Return a realistic 200+ day price history for EMA crossover demonstration."""
    # Generate 220 data points showing realistic gold price movement with EMAs
    # This includes an uptrend, correction, and potential crossover scenarios
    base_price = 2250
    history = []
    
    # Days 1-50: Downtrend (200 EMA higher than 50 EMA - bearish)
    for i in range(50):
        trend = -0.5 + (i * 0.3)  # Gradual recovery
        noise = (i % 7 - 3.5) * 0.2
        price = base_price + trend + noise
        history.append(price)
    
    # Days 51-100: Consolidation (EMAs converging)
    for i in range(50):
        trend = -5 + (i * 0.2)
        noise = (i % 11 - 5.5) * 0.25
        price = history[-1] + trend + noise
        history.append(price)
    
    # Days 101-150: Uptrend begins (50 EMA crossing above 200 EMA - GOLDEN CROSS area)
    for i in range(50):
        trend = 1 + (i * 0.5)  # Strong uptrend
        noise = (i % 13 - 6.5) * 0.3
        price = history[-1] + trend + noise
        history.append(price)
    
    # Days 151-200: Strong uptrend continuation (50 EMA well above 200 EMA - bullish)
    for i in range(50):
        trend = 2 + (i * 0.6)
        noise = (i % 9 - 4.5) * 0.25
        price = history[-1] + trend + noise
        history.append(price)
    
    # Days 201-220: Potential pullback/correction (EMAs may converge again)
    for i in range(20):
        trend = -1 + (i * 0.15)  # Slight pullback
        noise = (i % 5 - 2.5) * 0.3
        price = history[-1] + trend + noise
        history.append(price)
    
    return history
