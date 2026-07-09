"""FastAPI entry point for the gold trading signal app."""

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path

from fastapi import FastAPI, Query, Body
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import scoring
from app.alerts import build_alert_message, should_alert
from app.backtest import run_backtest
from app.history import get_sample_history
from app.journal import add_entry, load_journal
from app.settings_store import load_settings, save_settings
from app.signals import build_extended_signal
from app.strategy import generate_signal
from app.suggestions import build_suggestions
from data_sources import gold_price, macro, news

try:
    import config  # type: ignore
except ImportError:  # pragma: no cover - fallback for local runs
    config = None

app = FastAPI(title="Gold Signal API", redirect_slashes=False)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
INDEX_HTML = TEMPLATE_DIR / "index.html"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DEFAULT_SETTINGS = {
    "weights": {"technical": 0.35, "macro": 0.30, "news": 0.35},
    "thresholds": {"bullish": 65, "bearish": 35},
}
DEFAULT_SETTINGS_BY_METAL = {
    "gold": {**DEFAULT_SETTINGS},
    "silver": {**DEFAULT_SETTINGS},
}


def _build_settings_store() -> dict:
    loaded = load_settings(DEFAULT_SETTINGS_BY_METAL)

    # Backward compatibility: migrate old single-settings shape into both metals.
    if isinstance(loaded, dict) and "weights" in loaded and "thresholds" in loaded:
        migrated = {
            "gold": {
                "weights": dict(loaded.get("weights", DEFAULT_SETTINGS["weights"])),
                "thresholds": dict(loaded.get("thresholds", DEFAULT_SETTINGS["thresholds"])),
            },
            "silver": {
                "weights": dict(loaded.get("weights", DEFAULT_SETTINGS["weights"])),
                "thresholds": dict(loaded.get("thresholds", DEFAULT_SETTINGS["thresholds"])),
            },
        }
        save_settings(migrated)
        return migrated

    gold_settings = loaded.get("gold", DEFAULT_SETTINGS)
    silver_settings = loaded.get("silver", DEFAULT_SETTINGS)
    normalized = {
        "gold": {
            "weights": dict(gold_settings.get("weights", DEFAULT_SETTINGS["weights"])),
            "thresholds": dict(gold_settings.get("thresholds", DEFAULT_SETTINGS["thresholds"])),
        },
        "silver": {
            "weights": dict(silver_settings.get("weights", DEFAULT_SETTINGS["weights"])),
            "thresholds": dict(silver_settings.get("thresholds", DEFAULT_SETTINGS["thresholds"])),
        },
    }
    return normalized


SETTINGS_BY_METAL = _build_settings_store()


def _normalize_metal(metal: str) -> str:
    return "silver" if str(metal).strip().lower() == "silver" else "gold"


def _get_metal_settings(metal: str) -> dict:
    target = _normalize_metal(metal)
    return SETTINGS_BY_METAL.get(target, DEFAULT_SETTINGS)


def _get_runtime_config():
    defaults = {
        "GOLD_API_KEY": "",
        "FRED_API_KEY": "",
        "NEWS_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "WEIGHTS": {"technical": 0.35, "macro": 0.30, "news": 0.35},
        "NEWS_KEYWORDS": [
            "gold price",
            "Federal Reserve",
            "interest rates",
            "inflation",
            "geopolitical tension",
            "dollar index",
            "central bank gold",
        ],
        "NEWS_LOOKBACK_HOURS": 24,
        "MAX_HEADLINES_TO_SCORE": 15,
    }
    if config is None:
        config_values = {}
    else:
        config_values = {
            "GOLD_API_KEY": getattr(config, "GOLD_API_KEY", defaults["GOLD_API_KEY"]),
            "FRED_API_KEY": getattr(config, "FRED_API_KEY", defaults["FRED_API_KEY"]),
            "NEWS_API_KEY": getattr(config, "NEWS_API_KEY", defaults["NEWS_API_KEY"]),
            "ANTHROPIC_API_KEY": getattr(config, "ANTHROPIC_API_KEY", defaults["ANTHROPIC_API_KEY"]),
            "WEIGHTS": getattr(config, "WEIGHTS", defaults["WEIGHTS"]),
            "NEWS_KEYWORDS": getattr(config, "NEWS_KEYWORDS", defaults["NEWS_KEYWORDS"]),
            "NEWS_LOOKBACK_HOURS": getattr(config, "NEWS_LOOKBACK_HOURS", defaults["NEWS_LOOKBACK_HOURS"]),
            "MAX_HEADLINES_TO_SCORE": getattr(config, "MAX_HEADLINES_TO_SCORE", defaults["MAX_HEADLINES_TO_SCORE"]),
        }

    def _pick(name: str):
        env_value = os.getenv(name)
        if env_value is not None and env_value != "":
            return env_value
        if name in config_values:
            return config_values[name]
        return defaults[name]

    weights_value = _pick("WEIGHTS")
    if isinstance(weights_value, str):
        try:
            parsed_weights = json.loads(weights_value)
            if isinstance(parsed_weights, dict):
                weights_value = parsed_weights
            else:
                weights_value = defaults["WEIGHTS"]
        except json.JSONDecodeError:
            weights_value = defaults["WEIGHTS"]

    keywords_value = _pick("NEWS_KEYWORDS")
    if isinstance(keywords_value, str):
        if keywords_value.strip().startswith("["):
            try:
                parsed_keywords = json.loads(keywords_value)
                if isinstance(parsed_keywords, list):
                    keywords_value = [str(item) for item in parsed_keywords]
                else:
                    keywords_value = defaults["NEWS_KEYWORDS"]
            except json.JSONDecodeError:
                keywords_value = defaults["NEWS_KEYWORDS"]
        else:
            keywords_value = [segment.strip() for segment in keywords_value.split(",") if segment.strip()]
            if not keywords_value:
                keywords_value = defaults["NEWS_KEYWORDS"]

    def _as_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    return {
        "GOLD_API_KEY": _pick("GOLD_API_KEY"),
        "FRED_API_KEY": _pick("FRED_API_KEY"),
        "NEWS_API_KEY": _pick("NEWS_API_KEY"),
        "ANTHROPIC_API_KEY": _pick("ANTHROPIC_API_KEY"),
        "WEIGHTS": weights_value,
        "NEWS_KEYWORDS": keywords_value,
        "NEWS_LOOKBACK_HOURS": _as_int(_pick("NEWS_LOOKBACK_HOURS"), defaults["NEWS_LOOKBACK_HOURS"]),
        "MAX_HEADLINES_TO_SCORE": _as_int(_pick("MAX_HEADLINES_TO_SCORE"), defaults["MAX_HEADLINES_TO_SCORE"]),
    }


# Signal history for momentum tracking
_SIGNAL_HISTORY = {"gold": [], "silver": []}
_LAST_SIGNAL = {"gold": None, "silver": None}


def _add_to_history(metal: str, score: float, timestamp: datetime = None):
    """Track signal scores for momentum calculation."""
    target = _normalize_metal(metal)
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    _SIGNAL_HISTORY[target].append({"score": score, "timestamp": timestamp})
    # Keep last 100 signals (roughly last few hours)
    if len(_SIGNAL_HISTORY[target]) > 100:
        _SIGNAL_HISTORY[target].pop(0)
    
    _LAST_SIGNAL[target] = score


def _calculate_confluence_score(technical: float, macro: float, news: float) -> dict:
    """Calculate how many signals agree (confluence)."""
    scores = [technical, macro, news]
    bullish_count = sum(1 for s in scores if s >= 60)
    bearish_count = sum(1 for s in scores if s <= 40)
    neutral_count = 3 - bullish_count - bearish_count
    
    return {
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
        "neutral_signals": neutral_count,
        "confluence": bullish_count if bullish_count > bearish_count else (-bearish_count if bearish_count > 0 else 0)
    }


def _calculate_signal_momentum(metal: str) -> dict:
    """Calculate if signal is strengthening, stable, or weakening."""
    target = _normalize_metal(metal)
    history = _SIGNAL_HISTORY[target]
    
    if len(history) < 2:
        return {"momentum": "unknown", "trend": 0, "direction": "neutral"}
    
    # Get recent trend (last 5 signals)
    recent = history[-5:]
    older = history[-10:-5] if len(history) >= 10 else history[:len(history)//2]
    
    if not older:
        return {"momentum": "unknown", "trend": 0, "direction": "neutral"}
    
    recent_avg = sum(s["score"] for s in recent) / len(recent)
    older_avg = sum(s["score"] for s in older) / len(older)
    trend = recent_avg - older_avg
    
    if trend > 2:
        momentum = "strengthening"
    elif trend < -2:
        momentum = "weakening"
    else:
        momentum = "stable"
    
    direction = "up" if trend > 0 else "down" if trend < 0 else "flat"
    
    return {
        "momentum": momentum,
        "trend": round(trend, 2),
        "direction": direction
    }


def _detect_divergences(technical: float, macro: float, news: float) -> dict:
    """Detect when signals significantly disagree."""
    divergences = []
    
    if technical >= 60 and macro <= 40:
        divergences.append("technical_bullish_vs_macro_bearish")
    if macro >= 60 and technical <= 40:
        divergences.append("macro_bullish_vs_technical_bearish")
    if news >= 60 and (technical <= 40 or macro <= 40):
        divergences.append("news_bullish_vs_others")
    if news <= 40 and (technical >= 60 or macro >= 60):
        divergences.append("news_bearish_vs_others")
    
    return {
        "has_divergence": len(divergences) > 0,
        "divergences": divergences,
        "caution_level": "high" if len(divergences) > 1 else "medium" if len(divergences) == 1 else "low"
    }


def _get_market_session() -> dict:
    """Determine current market session (Asian/London/NY)."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    
    # Markets close on weekends; trading is limited on Sundays
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    
    if weekday == 6:  # Sunday
        session = "overnight"
        active_markets = ["Asian"]
    elif 0 <= hour < 8:  # Before Asian close
        session = "asian"
        active_markets = ["Asian"]
    elif 8 <= hour < 17:  # London/European session
        session = "london"
        active_markets = ["Asian", "London"]
    elif 13 <= hour < 22:  # NY session starts at 1:30 ET (13:30 UTC), ends at 5:00 PM ET (21:00 UTC)
        session = "newyork"
        active_markets = ["London", "NY"]
    else:
        session = "overnight"
        active_markets = []
    
    volume_expected = "high" if len(active_markets) > 1 else "medium" if len(active_markets) == 1 else "low"
    
    return {
        "current_session": session,
        "active_markets": active_markets,
        "volume_expected": volume_expected,
        "time_utc": now.isoformat()
    }


def _fetch_economic_events() -> list:
    """Get upcoming economic events that might impact gold/silver."""
    # These are typical high-impact events for commodities
    # In production, you'd fetch from a calendar API
    events = [
        {
            "time": "Tomorrow 12:30 UTC",
            "event": "FOMC Meeting Minutes",
            "impact": "high",
            "metal": "gold"
        },
        {
            "time": "Today 18:00 UTC",
            "event": "Fed Chair Powell Speech",
            "impact": "high",
            "metal": "gold"
        },
        {
            "time": "Tomorrow 08:30 UTC",
            "event": "US Core CPI",
            "impact": "high",
            "metal": "gold"
        },
        {
            "time": "In 3 days 13:00 UTC",
            "event": "ECB Interest Rate Decision",
            "impact": "medium",
            "metal": "gold"
        },
        {
            "time": "In 5 days 20:00 UTC",
            "event": "US NFP (Job Report)",
            "impact": "high",
            "metal": "gold"
        }
    ]
    return events


def _calculate_risk_reward(entry: float, support: float, resistance: float) -> dict:
    """Calculate risk/reward ratio based on technical levels."""
    if entry <= support or entry >= resistance:
        return {"risk_reward": 0, "risk": 0, "reward": 0, "ratio": "Invalid"}
    
    risk = entry - support
    reward = resistance - entry
    ratio = reward / risk if risk > 0 else 0
    
    return {
        "entry": round(entry, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "ratio": round(ratio, 2),
        "acceptable": ratio >= 2.0  # Risk/reward should be at least 2:1
    }


def _correlate_metals(gold_signal: dict, silver_signal: dict) -> dict:
    """Calculate correlation between gold and silver signals."""
    gold_score = gold_signal.get("composite_score", 50)
    silver_score = silver_signal.get("composite_score", 50)
    
    diff = abs(gold_score - silver_score)
    
    if diff < 10:
        corr = "high_positive"
        strength = "strong"
    elif diff < 20:
        corr = "moderate_positive"
        strength = "moderate"
    else:
        corr = "diverging"
        strength = "weak"
    
    return {
        "correlation": corr,
        "strength": strength,
        "gold_score": round(gold_score, 1),
        "silver_score": round(silver_score, 1),
        "difference": round(diff, 1),
        "moving_together": diff < 15
    }


def _build_demo_signal(metal: str = "gold"):
    cfg = _get_runtime_config()
    target_metal = _normalize_metal(metal)
    price_snapshot = gold_price.fetch_current_price(cfg.get("GOLD_API_KEY", ""), target_metal)
    technical_seed = 59.0 if target_metal == "silver" else 61.0
    macro_seed = 57.0 if target_metal == "silver" else 58.0
    news_seed = 62.0 if target_metal == "silver" else 64.0
    composite = scoring.compute_composite(
        technical_score=technical_seed,
        macro_score=macro_seed,
        news_score=news_seed,
        weights=cfg["WEIGHTS"],
    )
    return {
        **composite,
        "metal": target_metal,
        "technical_score": technical_seed,
        "macro_score": macro_seed,
        "news_score": news_seed,
        "current_price": price_snapshot.get("price", 2330.0),
        "price_history": gold_price.get_price_history(target_metal) or [price_snapshot.get("price", 2330.0)],
        "source": f"demo:{price_snapshot.get('source', 'fallback')}",
        "technical_detail": {"current_price": price_snapshot.get("price", 2330.0), "rsi": 58.0, "ma_short": 2320.0, "ma_long": 2295.0},
        "macro_detail": {"macro_score": 58.0, "real_yield_change": -0.12, "dollar_index_pct_change": -0.4},
        "top_events": [
            {"headline": f"{target_metal.title()} remains supported by safe-haven demand", "impact": "bullish", "conviction": "medium"}
        ],
    }


def _build_economic_calendar(metal: str) -> dict:
    target_metal = _normalize_metal(metal)
    now = datetime.now(timezone.utc)

    event_templates = [
        {
            "name": "US CPI",
            "hours_ahead": 6,
            "importance": "high",
            "why": "Inflation surprises can move real yields and precious metals rapidly.",
        },
        {
            "name": "FOMC Minutes",
            "hours_ahead": 18,
            "importance": "high",
            "why": "Fed tone can shift rate expectations and USD direction.",
        },
        {
            "name": "US Nonfarm Payrolls",
            "hours_ahead": 30,
            "importance": "medium",
            "why": "Labor strength influences policy outlook and dollar momentum.",
        },
        {
            "name": "ISM Services PMI",
            "hours_ahead": 42,
            "importance": "medium",
            "why": "Growth and inflation mix may reprice treasury yields.",
        },
    ]

    events = []
    risk_points = 0
    for item in event_templates:
        scheduled_at = now + timedelta(hours=item["hours_ahead"])
        hours_to_event = max(0.0, (scheduled_at - now).total_seconds() / 3600)

        importance_score = 3 if item["importance"] == "high" else 2
        proximity_score = 2 if hours_to_event <= 12 else 1 if hours_to_event <= 24 else 0
        event_risk = importance_score + proximity_score
        risk_points += event_risk

        events.append(
            {
                "name": item["name"],
                "scheduled_at": scheduled_at.isoformat(),
                "hours_to_event": round(hours_to_event, 1),
                "importance": item["importance"],
                "risk_score": event_risk,
                "metal_focus": target_metal,
                "why_it_matters": item["why"],
            }
        )

    max_points = len(event_templates) * 5
    risk_pct = round((risk_points / max_points) * 100, 1) if max_points else 0.0
    if risk_pct >= 65:
        risk_level = "high"
    elif risk_pct >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "generated_at": now.isoformat(),
        "risk_score": risk_pct,
        "risk_level": risk_level,
        "events": events,
    }


def _attach_calendar(payload: dict, metal: str) -> dict:
    calendar = _build_economic_calendar(metal)
    payload["economic_calendar"] = calendar
    payload["event_risk_level"] = calendar.get("risk_level")
    payload["event_risk_score"] = calendar.get("risk_score")
    return payload


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = max(0, min(len(sorted_values) - 1, int((len(sorted_values) - 1) * ratio)))
    return float(sorted_values[idx])


def _build_trade_plan(payload: dict, metal: str) -> dict:
    history_raw = payload.get("price_history") or []
    history = [float(v) for v in history_raw if isinstance(v, (int, float))]
    current = float(payload.get("current_price") or (history[-1] if history else 0.0))
    direction = str(payload.get("direction") or "neutral").lower()

    if not history:
        history = [current]

    support = _percentile(history, 0.25)
    resistance = _percentile(history, 0.75)
    deltas = [abs(history[i] - history[i - 1]) for i in range(1, len(history))]
    atr_proxy = sum(deltas) / len(deltas) if deltas else max(current * 0.004, 0.01)
    min_buffer = 0.05 if metal == "silver" else 1.5
    stop_buffer = max(atr_proxy * 0.8, min_buffer)

    if direction == "bearish":
        entry_min = min(current, resistance)
        entry_max = max(current, resistance)
        entry_mid = (entry_min + entry_max) / 2.0
        stop_price = entry_max + stop_buffer
        risk_per_unit = max(stop_price - entry_mid, min_buffer)
        tp1 = entry_mid - risk_per_unit * 1.2
        tp2 = entry_mid - risk_per_unit * 2.0
        tp3 = entry_mid - risk_per_unit * 3.0
    else:
        entry_min = min(current, support)
        entry_max = max(current, support)
        entry_mid = (entry_min + entry_max) / 2.0
        stop_price = max(0.0, entry_min - stop_buffer)
        risk_per_unit = max(entry_mid - stop_price, min_buffer)
        tp1 = entry_mid + risk_per_unit * 1.2
        tp2 = entry_mid + risk_per_unit * 2.0
        tp3 = entry_mid + risk_per_unit * 3.0

    def _rr(target: float) -> float:
        reward = abs(target - entry_mid)
        return round(reward / risk_per_unit, 2) if risk_per_unit > 0 else 0.0

    return {
        "direction": direction,
        "entry_min": round(entry_min, 2),
        "entry_max": round(entry_max, 2),
        "entry_mid": round(entry_mid, 2),
        "stop_price": round(stop_price, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "tp3": round(tp3, 2),
        "risk_per_unit": round(risk_per_unit, 4),
        "rr_tp1": _rr(tp1),
        "rr_tp2": _rr(tp2),
        "rr_tp3": _rr(tp3),
        "atr_proxy": round(atr_proxy, 3),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
    }


def _build_position_sizing(trade_plan: dict, account_size: float = 10000.0, risk_pct: float = 1.0) -> dict:
    risk_capital = max(0.0, account_size) * max(0.0, risk_pct) / 100.0
    risk_per_unit = float(trade_plan.get("risk_per_unit") or 0.0)
    units = 0.0
    if risk_per_unit > 0:
        units = risk_capital / risk_per_unit

    return {
        "account_size": round(account_size, 2),
        "risk_pct": round(risk_pct, 2),
        "risk_capital": round(risk_capital, 2),
        "risk_per_unit": round(risk_per_unit, 4),
        "units": round(units, 2),
    }


def _attach_trade_plan(payload: dict, metal: str) -> dict:
    trade_plan = _build_trade_plan(payload, metal)
    payload["trade_plan"] = trade_plan
    payload["position_sizing"] = _build_position_sizing(trade_plan)
    return payload


def _attach_structure_signals(payload: dict, metal: str) -> dict:
    trade_plan = payload.get("trade_plan") or _build_trade_plan(payload, metal)
    current = float(payload.get("current_price") or trade_plan.get("entry_mid") or 0.0)
    support = float(trade_plan.get("support") or current)
    resistance = float(trade_plan.get("resistance") or current)
    atr_proxy = max(float(trade_plan.get("atr_proxy") or 0.01), 0.01)
    technical = float(payload.get("technical_score") or 50.0)
    macro_score = float(payload.get("macro_score") or 50.0)
    news_score = float(payload.get("news_score") or 50.0)
    event_risk = float(payload.get("event_risk_score") or 50.0)

    midpoint = (support + resistance) / 2.0 if resistance or support else current
    band = max(resistance - support, atr_proxy)
    range_position = 0.5 if band == 0 else max(0.0, min(1.0, (current - support) / band))
    distance_to_resistance_pct = ((resistance - current) / resistance * 100.0) if resistance else 0.0
    distance_to_support_pct = ((current - support) / support * 100.0) if support else 0.0

    history_raw = payload.get("price_history") or []
    history = [float(v) for v in history_raw if isinstance(v, (int, float))]
    resistance_touches = 0
    if history:
        touch_band = max(atr_proxy * 0.35, 0.03 if metal == "silver" else 0.75)
        resistance_touches = sum(1 for value in history[-20:] if abs(value - resistance) <= touch_band)

    if current >= resistance - atr_proxy * 0.25:
        resistance_state = "at_ceiling"
    elif distance_to_resistance_pct <= 0.45:
        resistance_state = "pressing"
    elif range_position < 0.35:
        resistance_state = "far_below"
    else:
        resistance_state = "inside_range"

    if resistance_touches >= 4:
        resistance_strength = "heavy"
    elif resistance_touches >= 2:
        resistance_strength = "moderate"
    else:
        resistance_strength = "light"

    driver_spread = max(technical, macro_score, news_score) - min(technical, macro_score, news_score)
    gamma_raw = 50.0
    gamma_raw += (12.0 if abs(current - midpoint) <= atr_proxy * 0.8 else -10.0)
    gamma_raw += (8.0 if driver_spread <= 10 else -8.0)
    gamma_raw += (7.0 if event_risk <= 45 else -9.0)
    gamma_raw += (6.0 if resistance_state == "inside_range" else -6.0 if resistance_state in {"pressing", "at_ceiling"} else 0.0)
    gamma_score = max(0.0, min(100.0, round(gamma_raw, 1)))

    if gamma_score >= 58:
        gamma_exposure = "positive"
        gamma_regime = "pinning"
        gamma_note = "Dealer hedging likely dampens moves and favors mean reversion inside the current range."
    elif gamma_score <= 42:
        gamma_exposure = "negative"
        gamma_regime = "expansion"
        gamma_note = "Dealer hedging may amplify directional breaks, especially if price leans on resistance."
    else:
        gamma_exposure = "neutral"
        gamma_regime = "balanced"
        gamma_note = "Gamma backdrop looks balanced, so macro/news drivers remain the main directional force."

    if gamma_score >= 80:
        gamma_rating = "A+"
    elif gamma_score >= 68:
        gamma_rating = "A"
    elif gamma_score >= 58:
        gamma_rating = "B"
    elif gamma_score >= 46:
        gamma_rating = "C"
    elif gamma_score >= 34:
        gamma_rating = "D"
    else:
        gamma_rating = "F"

    payload["gamma_signal"] = {
        "exposure": gamma_exposure,
        "regime": gamma_regime,
        "rating": gamma_rating,
        "score": gamma_score,
        "range_position": round(range_position * 100.0, 1),
        "note": gamma_note,
    }
    payload["gamma_exposure_rating"] = gamma_rating
    payload["resistance_signal"] = {
        "state": resistance_state,
        "strength": resistance_strength,
        "resistance": round(resistance, 2),
        "support": round(support, 2),
        "distance_to_resistance_pct": round(distance_to_resistance_pct, 2),
        "distance_to_support_pct": round(distance_to_support_pct, 2),
        "touches": resistance_touches,
    }

    market_context = dict(payload.get("market_context") or {})
    market_context["gamma_exposure"] = gamma_exposure
    market_context["gamma_regime"] = gamma_regime
    market_context["gamma_rating"] = gamma_rating
    market_context["resistance_state"] = resistance_state
    market_context["resistance_strength"] = resistance_strength
    payload["market_context"] = market_context
    return payload


@app.get("/", response_class=HTMLResponse)
def landing_page():
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/backtest")
def get_backtest():
    """Run a lightweight historical backtest on sample price data."""
    sample_prices = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0, 108.0, 107.0, 110.0, 112.0, 109.0, 113.0]
    return run_backtest(sample_prices, weights={"technical": 0.35, "macro": 0.30, "news": 0.35})


def _calculate_overall_confidence(technical: float, macro: float, news: float, confluence: dict, momentum: dict, divergences: dict) -> dict:
    """Calculate overall trade confidence score (0-100%)."""
    confidence = 50  # Start at neutral
    
    # Confluence contribution (±25 points max)
    confluence_alignment = confluence.get("bullish_signals", 0) + confluence.get("bearish_signals", 0)
    if confluence_alignment == 3:  # All signals agree
        confidence += 20
    elif confluence_alignment == 2:  # Two signals agree
        confidence += 10
    # else: neutral signals reduce confidence
    
    # Signal alignment (are we bullish or bearish?)
    avg_score = (technical + macro + news) / 3
    if avg_score > 65:
        confidence += 15  # Strong bullish
    elif avg_score > 60:
        confidence += 8   # Moderate bullish
    elif avg_score < 35:
        confidence += 15  # Strong bearish
    elif avg_score < 40:
        confidence += 8   # Moderate bearish
    # Neutral region: no bonus
    
    # Momentum contribution (±15 points)
    mom = momentum.get("momentum", "stable")
    trend = momentum.get("trend", 0)
    if mom == "strengthening" and trend > 0:
        confidence += 12
    elif mom == "weakening" and trend < 0:
        confidence += 8
    elif mom == "stable":
        confidence += 3
    else:
        confidence -= 5
    
    # Divergence penalty (−25 points max)
    caution = divergences.get("caution_level", "low")
    if caution == "high":
        confidence -= 20
    elif caution == "medium":
        confidence -= 10
    
    # Cap at 0-100
    confidence = max(0, min(100, confidence))
    
    # Determine zone
    if confidence >= 75:
        zone = "Strong"
        color = "bullish"
    elif confidence >= 60:
        zone = "Moderate"
        color = "bullish"
    elif confidence >= 50:
        zone = "Neutral"
        color = "neutral"
    elif confidence >= 35:
        zone = "Weak"
        color = "bearish"
    else:
        zone = "Poor"
        color = "bearish"
    
    return {
        "score": round(confidence, 1),
        "percentage": f"{round(confidence)}%",
        "zone": zone,
        "color": color,
        "reasoning": f"{zone} trade setup. All signals {'aligned' if confluence_alignment == 3 else 'mixed'}. Momentum {'strengthening' if mom == 'strengthening' else 'weakening' if mom == 'weakening' else 'stable'}."
    }


def _get_multi_timeframe_confirmation(metal: str, technical: float, macro: float, news: float) -> dict:
    """Simulate multi-timeframe analysis across 1h, 4h, and 1D."""
    # In production, you'd fetch actual OHLC data for each timeframe
    # For now, we simulate slight variations around current scores
    
    base_score = (technical + macro + news) / 3
    
    # Simulate different timeframes with realistic noise
    timeframes = {
        "1h": {
            "technical": max(0, min(100, technical + ((hash(f"{metal}_1h_tech") % 20) - 10))),
            "macro": macro,  # Macro doesn't change on short timeframes
            "news": news,    # News doesn't change on short timeframes
            "direction": "bullish" if technical > 55 else "bearish" if technical < 45 else "neutral"
        },
        "4h": {
            "technical": max(0, min(100, technical + ((hash(f"{metal}_4h_tech") % 15) - 7))),
            "macro": macro,
            "news": news,
            "direction": "bullish" if technical > 55 else "bearish" if technical < 45 else "neutral"
        },
        "1d": {
            "technical": technical,  # 1D is more stable
            "macro": macro,
            "news": news,
            "direction": "bullish" if base_score > 55 else "bearish" if base_score < 45 else "neutral"
        }
    }
    
    # Calculate alignment
    directions = [tf["direction"] for tf in timeframes.values()]
    aligned = directions.count(directions[0]) == len(directions)
    alignment_count = sum(1 for d in directions if d == directions[0])
    
    primary_trend = "bullish" if base_score > 55 else "bearish" if base_score < 45 else "neutral"
    
    return {
        "timeframes": timeframes,
        "aligned": aligned,
        "alignment_count": alignment_count,
        "alignment_percentage": round((alignment_count / 3) * 100),
        "primary_trend": primary_trend,
        "summary": f"{'✓ All timeframes aligned' if aligned else '⚠ Mixed timeframe signals'} - Primary trend is {primary_trend.upper()}"
    }


def _get_sentiment_gauge(technical: float, macro: float, news: float) -> dict:
    """Calculate real-time sentiment indicators (simulated)."""
    avg_score = (technical + macro + news) / 3
    
    # COT-like positioning (Commercials usually inverse to retail)
    # High avg_score suggests retail is bullish, so commercials are reducing longs
    cot_commercial_positioning = max(-100, min(100, (50 - avg_score) * 1.5))
    cot_status = "long" if cot_commercial_positioning > 10 else "short" if cot_commercial_positioning < -10 else "neutral"
    
    # Options flow simulation (call/put ratio)
    # Higher news score suggests more bullish sentiment = more call buying
    options_call_put_ratio = 1.0 + ((avg_score - 50) / 50) * 0.5  # Range ~0.5 to 1.5
    options_flow = "bullish" if options_call_put_ratio > 1.1 else "bearish" if options_call_put_ratio < 0.9 else "neutral"
    
    # Retail vs Institutional positioning
    # Simulate inverse of technical score (retail often lags institutions)
    retail_positioning = 50 + (technical - 50) * 0.7
    institutional_positioning = avg_score
    retail_status = "bullish" if retail_positioning > 55 else "bearish" if retail_positioning < 45 else "neutral"
    institutional_status = "bullish" if institutional_positioning > 55 else "bearish" if institutional_positioning < 45 else "neutral"
    retail_institutional_alignment = retail_status == institutional_status
    
    return {
        "cot_positioning": {
            "commercials": cot_status,
            "positioning_score": round(cot_commercial_positioning, 1),
            "description": f"Commercials are {'net long' if cot_status == 'long' else 'net short' if cot_status == 'short' else 'balanced'}"
        },
        "options_flow": {
            "call_put_ratio": round(options_call_put_ratio, 2),
            "bias": options_flow,
            "description": f"{'More call buying' if options_flow == 'bullish' else 'More put buying' if options_flow == 'bearish' else 'Balanced'} activity"
        },
        "retail_vs_institutional": {
            "retail": retail_status,
            "institutional": institutional_status,
            "aligned": retail_institutional_alignment,
            "retail_score": round(retail_positioning, 1),
            "institutional_score": round(institutional_positioning, 1),
            "description": f"Retail {'agrees' if retail_institutional_alignment else 'disagrees'} with institutions"
        },
        "overall_sentiment": "bullish" if avg_score > 55 else "bearish" if avg_score < 45 else "neutral",
        "smart_money_direction": "with_retail" if retail_institutional_alignment else "contrarian"
    }


@app.get("/signal")
def get_signal(metal: str = "gold"):
    """Return a composite metal signal built from technical, macro, and news inputs."""
    cfg = _get_runtime_config()
    target_metal = _normalize_metal(metal)
    metal_settings = _get_metal_settings(target_metal)
    news_keywords = cfg["NEWS_KEYWORDS"]
    if target_metal == "silver":
        news_keywords = [keyword.replace("gold", "silver") for keyword in cfg["NEWS_KEYWORDS"]]

    if not cfg.get("GOLD_API_KEY") or not cfg.get("FRED_API_KEY") or not cfg.get("NEWS_API_KEY"):
        sample_prices = get_sample_history()
        demo_signal = _build_demo_signal(target_metal)
        demo_signal.update(generate_signal(sample_prices, metal_settings["weights"], macro={"macro_score": 58}, news={"news_score": 64}))
        demo_signal = build_extended_signal(
            demo_signal,
            {
                "volatility_up": True,
                "yield_falling": True,
                "dollar_weaker": True,
                "inflation_rising": True,
                "risk_off": True,
                "equity_rally": False,
            },
        )
        
        # Add advanced features to demo signal too
        composite_score = demo_signal.get("composite_score", 50)
        _add_to_history(target_metal, composite_score)
        
        demo_signal["confluence"] = _calculate_confluence_score(
            demo_signal.get("technical_score", 50),
            demo_signal.get("macro_score", 50),
            demo_signal.get("news_score", 50)
        )
        demo_signal["momentum"] = _calculate_signal_momentum(target_metal)
        demo_signal["divergences"] = _detect_divergences(
            demo_signal.get("technical_score", 50),
            demo_signal.get("macro_score", 50),
            demo_signal.get("news_score", 50)
        )
        demo_signal["market_session"] = _get_market_session()
        demo_signal["economic_events"] = _fetch_economic_events()
        demo_signal["risk_reward"] = _calculate_risk_reward(2050, 2000, 2150)
        
        # Add new advanced features: confidence, multiframe, sentiment
        demo_signal["confidence_score"] = _calculate_overall_confidence(
            demo_signal.get("technical_score", 50),
            demo_signal.get("macro_score", 50),
            demo_signal.get("news_score", 50),
            demo_signal["confluence"],
            demo_signal["momentum"],
            demo_signal["divergences"]
        )
        demo_signal["multiframe_confirmation"] = _get_multi_timeframe_confirmation(
            target_metal,
            demo_signal.get("technical_score", 50),
            demo_signal.get("macro_score", 50),
            demo_signal.get("news_score", 50)
        )
        demo_signal["sentiment_gauge"] = _get_sentiment_gauge(
            demo_signal.get("technical_score", 50),
            demo_signal.get("macro_score", 50),
            demo_signal.get("news_score", 50)
        )
        
        score = demo_signal.get("composite_score", 50)
        if score >= 85:
            strength_level = "Extreme"
        elif score >= 70:
            strength_level = "Strong"
        elif score >= 60:
            strength_level = "Moderate"
        elif score >= 50:
            strength_level = "Weak Bullish"
        elif score >= 40:
            strength_level = "Weak Bearish"
        elif score >= 30:
            strength_level = "Moderate"
        else:
            strength_level = "Strong"
        
        demo_signal["signal_strength"] = {
            "score": round(score, 1),
            "level": strength_level,
            "gradient": max(0, min(100, score))
        }
        
        demo_signal["suggestions"] = build_suggestions(demo_signal)
        demo_signal["settings"] = metal_settings
        if should_alert(demo_signal, metal_settings["thresholds"]):
            demo_signal["alert"] = build_alert_message(demo_signal, metal_settings["thresholds"])
        demo_signal = _attach_trade_plan(demo_signal, target_metal)
        demo_signal = _attach_structure_signals(demo_signal, target_metal)
        return _attach_calendar(demo_signal, target_metal)

    try:
        technical = gold_price.get_technical_snapshot(cfg["GOLD_API_KEY"], target_metal)
        macro_data = macro.get_macro_snapshot(cfg["FRED_API_KEY"])
        news_data = news.get_news_snapshot(
            news_api_key=cfg["NEWS_API_KEY"],
            anthropic_api_key=cfg["ANTHROPIC_API_KEY"],
            keywords=news_keywords,
            lookback_hours=cfg["NEWS_LOOKBACK_HOURS"],
            max_headlines=cfg["MAX_HEADLINES_TO_SCORE"],
        )
    except Exception as e:
        print(f"[API Error] Failed to fetch live data: {type(e).__name__}: {str(e)[:100]}")
        fallback = _build_demo_signal(target_metal)
        fallback["settings"] = metal_settings
        if should_alert(fallback, metal_settings["thresholds"]):
            fallback["alert"] = build_alert_message(fallback, metal_settings["thresholds"])
        fallback = _attach_trade_plan(fallback, target_metal)
        fallback = _attach_structure_signals(fallback, target_metal)
        return _attach_calendar(fallback, target_metal)

    composite = scoring.compute_composite(
        technical_score=technical["technical_score"],
        macro_score=macro_data["macro_score"],
        news_score=news_data["news_score"],
        weights=metal_settings["weights"],
    )

    signal_payload = {
        **composite,
        "metal": target_metal,
        "technical_score": technical["technical_score"],
        "macro_score": macro_data["macro_score"],
        "news_score": news_data["news_score"],
        "current_price": technical.get("current_price"),
        "price_history": gold_price.get_price_history(target_metal) or [technical.get("current_price")],
        "source": "live",
        "technical_detail": technical,
        "macro_detail": macro_data,
        "top_events": news_data.get("events", [])[:5],
        "settings": metal_settings,
    }
    signal_payload = build_extended_signal(
        signal_payload,
        {
            "volatility_up": True,
            "yield_falling": macro_data.get("real_yield_change", 0) < 0,
            "dollar_weaker": macro_data.get("dollar_index_pct_change", 0) < 0,
            "inflation_rising": macro_data.get("cpi_yoy_pct", 0) > 2,
            "risk_off": news_data.get("news_score", 50) > 60,
            "equity_rally": False,
        },
    )
    
    # Add new advanced signal features
    composite_score = signal_payload.get("composite_score", 50)
    _add_to_history(target_metal, composite_score)
    
    signal_payload["confluence"] = _calculate_confluence_score(
        signal_payload.get("technical_score", 50),
        signal_payload.get("macro_score", 50),
        signal_payload.get("news_score", 50)
    )
    signal_payload["momentum"] = _calculate_signal_momentum(target_metal)
    signal_payload["divergences"] = _detect_divergences(
        signal_payload.get("technical_score", 50),
        signal_payload.get("macro_score", 50),
        signal_payload.get("news_score", 50)
    )
    signal_payload["market_session"] = _get_market_session()
    signal_payload["economic_events"] = _fetch_economic_events()
    
    # Risk/reward calculation - use technical support/resistance if available
    if "support_level" in technical and "resistance_level" in technical:
        signal_payload["risk_reward"] = _calculate_risk_reward(
            technical.get("current_price", 0),
            technical.get("support_level", 0),
            technical.get("resistance_level", 0)
        )
    else:
        # Fallback: estimate based on price changes
        price_range = 50  # Estimated range in $
        current = technical.get("current_price", 1000)
        signal_payload["risk_reward"] = _calculate_risk_reward(
            current,
            current - price_range,
            current + price_range * 2
        )
    
    # Signal strength gradient (0-100 scale with descriptors)
    score = signal_payload.get("composite_score", 50)
    if score >= 85:
        strength_level = "Extreme"
    elif score >= 70:
        strength_level = "Strong"
    elif score >= 60:
        strength_level = "Moderate"
    elif score >= 50:
        strength_level = "Weak Bullish"
    elif score >= 40:
        strength_level = "Weak Bearish"
    elif score >= 30:
        strength_level = "Moderate"
    else:
        strength_level = "Strong"
    
    signal_payload["signal_strength"] = {
        "score": round(score, 1),
        "level": strength_level,
        "gradient": max(0, min(100, score))
    }
    
    # Add new advanced features: confidence, multiframe, sentiment
    signal_payload["confidence_score"] = _calculate_overall_confidence(
        signal_payload.get("technical_score", 50),
        signal_payload.get("macro_score", 50),
        signal_payload.get("news_score", 50),
        signal_payload["confluence"],
        signal_payload["momentum"],
        signal_payload["divergences"]
    )
    signal_payload["multiframe_confirmation"] = _get_multi_timeframe_confirmation(
        target_metal,
        signal_payload.get("technical_score", 50),
        signal_payload.get("macro_score", 50),
        signal_payload.get("news_score", 50)
    )
    signal_payload["sentiment_gauge"] = _get_sentiment_gauge(
        signal_payload.get("technical_score", 50),
        signal_payload.get("macro_score", 50),
        signal_payload.get("news_score", 50)
    )
    
    if should_alert(signal_payload, metal_settings["thresholds"]):
        signal_payload["alert"] = build_alert_message(signal_payload, metal_settings["thresholds"])
    signal_payload["suggestions"] = build_suggestions(signal_payload)
    signal_payload = _attach_trade_plan(signal_payload, target_metal)
    signal_payload = _attach_structure_signals(signal_payload, target_metal)
    return _attach_calendar(signal_payload, target_metal)


@app.get("/position-size")
def get_position_size(metal: str = "gold", account_size: float = 10000, risk_pct: float = 1.0):
    signal_payload = get_signal(metal=metal)
    trade_plan = signal_payload.get("trade_plan") or _build_trade_plan(signal_payload, _normalize_metal(metal))
    sizing = _build_position_sizing(trade_plan, account_size=account_size, risk_pct=risk_pct)
    return {"metal": _normalize_metal(metal), "trade_plan": trade_plan, "position_sizing": sizing}


@app.get("/signal/{metal}")
def get_signal_by_path(metal: str):
    return get_signal(metal=metal)


@app.get("/correlation")
def get_correlation():
    """Get correlation analysis between gold and silver signals."""
    gold_signal = get_signal(metal="gold")
    silver_signal = get_signal(metal="silver")
    
    correlation = _correlate_metals(gold_signal, silver_signal)
    
    return {
        "ok": True,
        "correlation": correlation,
        "gold_summary": {
            "score": gold_signal.get("composite_score", 50),
            "direction": gold_signal.get("direction", "neutral"),
            "momentum": gold_signal.get("momentum", {}).get("momentum", "unknown"),
            "confluence": gold_signal.get("confluence", {}).get("confluence", 0)
        },
        "silver_summary": {
            "score": silver_signal.get("composite_score", 50),
            "direction": silver_signal.get("direction", "neutral"),
            "momentum": silver_signal.get("momentum", {}).get("momentum", "unknown"),
            "confluence": silver_signal.get("confluence", {}).get("confluence", 0)
        }
    }



@app.get("/calendar")
def get_calendar(metal: str = "gold"):
    target_metal = _normalize_metal(metal)
    return {"metal": target_metal, "economic_calendar": _build_economic_calendar(target_metal)}


@app.get("/settings")
def get_settings(metal: str = "gold"):
    """Get the current settings for a specific metal."""
    target_metal = _normalize_metal(metal)
    metal_settings = _get_metal_settings(target_metal)
    return {"ok": True, "metal": target_metal, "settings": metal_settings}


@app.post("/settings")
def post_settings(metal: str = "gold"):
    """Update the dashboard weights and alert thresholds - stub for testing."""
    # This is a temporary stub - body parsing needs testing
    target_metal = _normalize_metal(metal)
    metal_settings = _get_metal_settings(target_metal)
    return {"ok": True, "metal": target_metal, "settings": metal_settings}


@app.get("/journal")
def get_journal():
    return {"entries": load_journal()}


@app.post("/journal")
def post_journal(payload: dict):
    entry = {
        "timestamp": payload.get("timestamp"),
        "action": payload.get("action"),
        "reason": payload.get("reason"),
        "price": payload.get("price"),
    }
    return {"entries": add_entry(entry)}
