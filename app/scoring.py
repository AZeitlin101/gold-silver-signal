"""Combine technical, macro, and news scores into a single composite signal."""


def compute_composite(technical_score: float, macro_score: float, news_score: float,
                       weights: dict) -> dict:
    composite = (
        technical_score * weights["technical"]
        + macro_score * weights["macro"]
        + news_score * weights["news"]
    )
    composite = round(max(0.0, min(100.0, composite)), 1)

    if composite >= 65:
        direction = "bullish"
    elif composite <= 35:
        direction = "bearish"
    else:
        direction = "neutral"

    distance_from_neutral = abs(composite - 50)
    if distance_from_neutral >= 25:
        conviction = "high"
    elif distance_from_neutral >= 12:
        conviction = "medium"
    else:
        conviction = "low"

    return {
        "composite_score": composite,
        "direction": direction,
        "conviction": conviction,
    }
