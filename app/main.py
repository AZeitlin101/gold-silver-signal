"""FastAPI entry point for the gold trading signal app."""

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path

from fastapi import FastAPI
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

app = FastAPI(title="Gold Signal API")

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
    sample_prices = [100, 102, 101, 104, 103, 106, 108, 107, 110, 112, 109, 113]
    return run_backtest(sample_prices, weights={"technical": 0.35, "macro": 0.30, "news": 0.35})


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
        demo_signal["suggestions"] = build_suggestions(demo_signal)
        demo_signal["settings"] = metal_settings
        if should_alert(demo_signal, metal_settings["thresholds"]):
            demo_signal["alert"] = build_alert_message(demo_signal, metal_settings["thresholds"])
        demo_signal = _attach_trade_plan(demo_signal, target_metal)
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
    except Exception:
        fallback = _build_demo_signal(target_metal)
        fallback["settings"] = metal_settings
        if should_alert(fallback, metal_settings["thresholds"]):
            fallback["alert"] = build_alert_message(fallback, metal_settings["thresholds"])
        fallback = _attach_trade_plan(fallback, target_metal)
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
    if should_alert(signal_payload, metal_settings["thresholds"]):
        signal_payload["alert"] = build_alert_message(signal_payload, metal_settings["thresholds"])
    signal_payload["suggestions"] = build_suggestions(signal_payload)
    signal_payload = _attach_trade_plan(signal_payload, target_metal)
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


@app.get("/calendar")
def get_calendar(metal: str = "gold"):
    target_metal = _normalize_metal(metal)
    return {"metal": target_metal, "economic_calendar": _build_economic_calendar(target_metal)}


@app.post("/settings")
def update_settings(payload: dict, metal: str = "gold"):
    """Update the dashboard weights and alert thresholds."""
    target_metal = _normalize_metal(metal)
    metal_settings = _get_metal_settings(target_metal)

    if "weights" in payload:
        metal_settings["weights"] = payload["weights"]
    if "thresholds" in payload:
        metal_settings["thresholds"] = payload["thresholds"]

    SETTINGS_BY_METAL[target_metal] = metal_settings
    save_settings(SETTINGS_BY_METAL)
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
