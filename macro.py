"""
Pulls macro indicators most correlated with gold price moves, via the
FRED (Federal Reserve Economic Data) API — free, no scraping needed.

Key drivers of gold:
  - Real yields (10Y TIPS): gold is non-yielding, so falling real yields = bullish for gold
  - DXY (dollar index): gold priced in USD, so a weaker dollar = bullish for gold
  - CPI / inflation surprises: higher inflation = typically bullish for gold (inflation hedge)
"""

import requests

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series IDs
SERIES = {
    "real_yield_10y": "DFII10",     # 10-Year Treasury Inflation-Indexed Security
    "dollar_index": "DTWEXBGS",     # Trade Weighted U.S. Dollar Index: Broad, Goods and Services
    "cpi": "CPIAUCSL",              # Consumer Price Index for All Urban Consumers
}


def _fetch_series(series_id: str, api_key: str, limit: int = 2) -> list:
    """Fetch the most recent `limit` observations for a FRED series."""
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
    return [o for o in obs if o["value"] != "."]  # filter missing data points


def get_macro_snapshot(api_key: str) -> dict:
    """
    Returns latest macro readings plus a macro score (0-100, higher = more bullish for gold).
    """
    real_yield_obs = _fetch_series(SERIES["real_yield_10y"], api_key)
    dxy_obs = _fetch_series(SERIES["dollar_index"], api_key)
    cpi_obs = _fetch_series(SERIES["cpi"], api_key, limit=13)  # ~1yr for YoY calc

    score = 50.0
    details = {}

    # Real yield trend (falling yields -> bullish gold)
    if len(real_yield_obs) >= 2:
        latest = float(real_yield_obs[0]["value"])
        prev = float(real_yield_obs[1]["value"])
        change = latest - prev
        details["real_yield_10y"] = latest
        details["real_yield_change"] = round(change, 3)
        # falling yield -> add to score; rising -> subtract
        score -= change * 20  # scaling factor, tune via backtesting

    # Dollar index trend (weaker dollar -> bullish gold)
    if len(dxy_obs) >= 2:
        latest = float(dxy_obs[0]["value"])
        prev = float(dxy_obs[1]["value"])
        pct_change = (latest - prev) / prev * 100
        details["dollar_index"] = latest
        details["dollar_index_pct_change"] = round(pct_change, 3)
        score -= pct_change * 3  # weaker dollar (negative change) -> boosts score

    # CPI YoY (higher inflation -> bullish gold, inflation hedge narrative)
    if len(cpi_obs) >= 13:
        latest = float(cpi_obs[0]["value"])
        year_ago = float(cpi_obs[12]["value"])
        yoy = (latest - year_ago) / year_ago * 100
        details["cpi_yoy_pct"] = round(yoy, 2)
        # above ~2% Fed target adds bullish tilt, scaled
        score += (yoy - 2.0) * 5

    score = max(0.0, min(100.0, score))

    return {
        **details,
        "macro_score": round(score, 1),
    }
