"""Extended signal helpers for gold trading."""

from typing import Dict, Any


def build_extended_signal(base_signal: Dict[str, Any], market_context: Dict[str, Any]) -> Dict[str, Any]:
    score = float(base_signal.get("composite_score", 50.0))

    # Extra signal contributors
    if market_context.get("volatility_up"):
        score += 4
    if market_context.get("yield_falling"):
        score += 5
    if market_context.get("dollar_weaker"):
        score += 5
    if market_context.get("inflation_rising"):
        score += 4
    if market_context.get("risk_off"):
        score += 4
    if market_context.get("equity_rally"):
        score -= 3

    score = max(0.0, min(100.0, round(score, 1)))

    if score >= 65:
        direction = "bullish"
    elif score <= 35:
        direction = "bearish"
    else:
        direction = "neutral"

    distance = abs(score - 50)
    conviction = "high" if distance >= 25 else "medium" if distance >= 12 else "low"

    return {
        **base_signal,
        "composite_score": score,
        "direction": direction,
        "conviction": conviction,
        "market_context": market_context,
    }
