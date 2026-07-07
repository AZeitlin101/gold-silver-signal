"""Fetch macro indicators from FRED and turn them into a gold bias score."""

import requests

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "real_yield_10y": "DFII10",
    "dollar_index": "DTWEXBGS",
    "cpi": "CPIAUCSL",
}


def _fetch_series(series_id: str, api_key: str, limit: int = 2) -> list:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    resp = requests.get(FRED_BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    return [o for o in obs if o["value"] != "."]


def get_macro_snapshot(api_key: str) -> dict:
    real_yield_obs = _fetch_series(SERIES["real_yield_10y"], api_key)
    dxy_obs = _fetch_series(SERIES["dollar_index"], api_key)
    cpi_obs = _fetch_series(SERIES["cpi"], api_key, limit=13)

    score = 50.0
    details = {}

    if len(real_yield_obs) >= 2:
        latest = float(real_yield_obs[0]["value"])
        prev = float(real_yield_obs[1]["value"])
        change = latest - prev
        details["real_yield_10y"] = latest
        details["real_yield_change"] = round(change, 3)
        score -= change * 20

    if len(dxy_obs) >= 2:
        latest = float(dxy_obs[0]["value"])
        prev = float(dxy_obs[1]["value"])
        pct_change = (latest - prev) / prev * 100
        details["dollar_index"] = latest
        details["dollar_index_pct_change"] = round(pct_change, 3)
        score -= pct_change * 3

    if len(cpi_obs) >= 13:
        latest = float(cpi_obs[0]["value"])
        year_ago = float(cpi_obs[12]["value"])
        yoy = (latest - year_ago) / year_ago * 100
        details["cpi_yoy_pct"] = round(yoy, 2)
        score += (yoy - 2.0) * 5

    score = max(0.0, min(100.0, score))

    return {**details, "macro_score": round(score, 1)}
