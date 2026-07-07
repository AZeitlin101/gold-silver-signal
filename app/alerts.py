"""Simple alert helpers for gold signal crossings."""

from typing import Dict, Any


def should_alert(signal: Dict[str, Any], thresholds: Dict[str, float]) -> bool:
    score = float(signal.get("composite_score", 50.0))
    bullish = float(thresholds.get("bullish", 65))
    bearish = float(thresholds.get("bearish", 35))
    return score >= bullish or score <= bearish


def build_alert_message(signal: Dict[str, Any], thresholds: Dict[str, float]) -> str:
    score = float(signal.get("composite_score", 50.0))
    direction = signal.get("direction", "neutral")
    if score >= float(thresholds.get("bullish", 65)):
        return f"Gold signal triggered bullish at {score}"
    if score <= float(thresholds.get("bearish", 35)):
        return f"Gold signal triggered bearish at {score}"
    return f"Gold signal is {direction} at {score}"
