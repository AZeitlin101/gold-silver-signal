"""Generate practical trading suggestions from a gold signal."""

from typing import Dict, Any, List


def build_suggestions(signal: Dict[str, Any]) -> List[Dict[str, Any]]:
    score = float(signal.get("composite_score", 50.0))
    direction = signal.get("direction", "neutral")

    suggestions = []

    if direction == "bullish":
        suggestions.append({
            "title": "Consider a long bias",
            "detail": "The combined signal is leaning bullish; consider adding exposure only if the setup remains supportive.",
            "priority": "high",
        })
        suggestions.append({
            "title": "Watch for pullbacks",
            "detail": "Use pullbacks as a chance to enter or add, but confirm the trend remains intact.",
            "priority": "medium",
        })
    elif direction == "bearish":
        suggestions.append({
            "title": "Stay cautious",
            "detail": "The model is leaning bearish; reduce risk and wait for confirmation before acting.",
            "priority": "high",
        })
        suggestions.append({
            "title": "Watch for downside breaks",
            "detail": "A breakdown below support would strengthen the bearish case.",
            "priority": "medium",
        })
    else:
        suggestions.append({
            "title": "Stay neutral",
            "detail": "The signal is mixed; avoid forcing a trade until one side becomes clearer.",
            "priority": "medium",
        })

    if score >= 80:
        suggestions.append({
            "title": "Risk management is important",
            "detail": "A very strong score can be crowded; consider tighter sizing and a stop-loss plan.",
            "priority": "high",
        })

    return suggestions
