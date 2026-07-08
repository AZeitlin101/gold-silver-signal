"""Fetches gold price data and computes a lightweight technical signal."""

import requests
import numpy as np
from collections import deque
from datetime import datetime, timezone

GOLD_API_URL = "https://www.goldapi.io/api/XAU/USD"
SILVER_API_URL = "https://www.goldapi.io/api/XAG/USD"
YAHOO_SYMBOLS = {
    "gold": "GC=F",
    "silver": "SI=F",
}
_price_history_by_metal = {
    "gold": deque(maxlen=200),
    "silver": deque(maxlen=200),
}


def _normalize_metal(metal: str) -> str:
    return "silver" if str(metal).strip().lower() == "silver" else "gold"


def get_price_history(metal: str = "gold") -> list:
    """Return the recent cached price history for the selected metal."""
    target = _normalize_metal(metal)
    return [float(price) for price in _price_history_by_metal[target] if price is not None]


def fetch_current_price(api_key: str, metal: str = "gold") -> dict:
    """Fetch the current metal price in USD using Yahoo Finance when possible."""
    target = _normalize_metal(metal)
    symbol = YAHOO_SYMBOLS[target]
    yahoo_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    history = _price_history_by_metal[target]

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(yahoo_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = (data.get("chart") or {}).get("result") or []
        if result:
            meta = result[0].get("meta", {})
            quote = (result[0].get("indicators") or {}).get("quote", [{}])[0]
            price = meta.get("regularMarketPrice") or (quote.get("close") or [None])[-1]
            if price is not None:
                price_point = {
                    "price": float(price),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "open": (quote.get("open") or [None])[-1],
                    "high": (quote.get("high") or [None])[-1],
                    "low": (quote.get("low") or [None])[-1],
                    "prev_close": meta.get("chartPreviousClose"),
                    "metal": target,
                    "source": "yahoo",
                }
                history.append(price_point["price"])
                return price_point
    except Exception:
        pass

    if api_key:
        try:
            api_url = SILVER_API_URL if target == "silver" else GOLD_API_URL
            headers = {"x-access-token": api_key, "Content-Type": "application/json"}
            resp = requests.get(api_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            price_point = {
                "price": data.get("price"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "open": data.get("open_price"),
                "high": data.get("high_price"),
                "low": data.get("low_price"),
                "prev_close": data.get("prev_close_price"),
                "metal": target,
                "source": "goldapi",
            }
            history.append(price_point["price"])
            return price_point
        except Exception:
            pass

    fallback_map = {
        "gold": {"price": 2330.0, "open": 2328.0, "high": 2335.0, "low": 2324.0, "prev_close": 2329.0},
        "silver": {"price": 45.2, "open": 44.9, "high": 45.5, "low": 44.6, "prev_close": 45.0},
    }
    fallback = fallback_map[target]
    price_point = {
        "price": fallback["price"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "open": fallback["open"],
        "high": fallback["high"],
        "low": fallback["low"],
        "prev_close": fallback["prev_close"],
        "metal": target,
        "source": "fallback",
    }
    history.append(price_point["price"])
    return price_point


def _rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0

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


def get_technical_snapshot(api_key: str, metal: str = "gold") -> dict:
    """Return a technical score from current price and recent history."""
    target = _normalize_metal(metal)
    current = fetch_current_price(api_key, target)
    prices = list(_price_history_by_metal[target])

    rsi = _rsi(prices)
    ma_short = _moving_average(prices, 10)
    ma_long = _moving_average(prices, 50)

    score = 50.0
    if rsi < 30:
        score += 15
    elif rsi > 70:
        score -= 15
    else:
        score += (50 - rsi) * 0.2

    if ma_short and ma_long:
        if current["price"] > ma_short > ma_long:
            score += 15
        elif current["price"] < ma_short < ma_long:
            score -= 15

    score = max(0.0, min(100.0, score))

    return {
        "metal": target,
        "current_price": current["price"],
        "open": current.get("open"),
        "high": current.get("high"),
        "low": current.get("low"),
        "prev_close": current.get("prev_close"),
        "rsi": rsi,
        "ma_short": ma_short,
        "ma_long": ma_long,
        "technical_score": round(score, 1),
        "history_length": len(prices),
    }
