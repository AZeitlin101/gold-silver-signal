"""A slightly more realistic signal strategy for the gold app."""

from typing import Dict, List, Any


def generate_signal(prices: List[float], weights: Dict[str, float], technical: Dict[str, Any] | None = None,
                   macro: Dict[str, Any] | None = None, news: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not prices:
        return {"composite_score": 50.0, "direction": "neutral", "conviction": "low"}

    latest = prices[-1]
    prev = prices[-2] if len(prices) > 1 else latest
    momentum = latest - prev

    short_ma = sum(prices[-3:]) / min(3, len(prices)) if len(prices) >= 1 else latest
    long_ma = sum(prices[-6:]) / min(6, len(prices)) if len(prices) >= 1 else latest

    tech_score = 50.0
    if momentum > 0:
        tech_score += 10
    if momentum < 0:
        tech_score -= 10
    if short_ma > long_ma:
        tech_score += 10
    if short_ma < long_ma:
        tech_score -= 10

    macro_score = 50.0
    if macro:
        macro_score = float(macro.get("macro_score", 50.0))

    news_score = 50.0
    if news:
        news_score = float(news.get("news_score", 50.0))

    composite = (
        tech_score * weights.get("technical", 0.35)
        + macro_score * weights.get("macro", 0.30)
        + news_score * weights.get("news", 0.35)
    )
    composite = round(max(0.0, min(100.0, composite)), 1)

    if composite >= 65:
        direction = "bullish"
    elif composite <= 35:
        direction = "bearish"
    else:
        direction = "neutral"

    distance = abs(composite - 50)
    conviction = "high" if distance >= 25 else "medium" if distance >= 12 else "low"

    return {
        "composite_score": composite,
        "direction": direction,
        "conviction": conviction,
        "technical_score": round(tech_score, 1),
        "macro_score": round(macro_score, 1),
        "news_score": round(news_score, 1),
    }
