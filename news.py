"""
Pulls recent headlines relevant to gold and uses the Claude API to turn them
into structured, scored events (bullish/bearish/neutral + conviction).

This is the piece that handles "world affairs and daily news" — geopolitical
tension, central bank moves, Fed commentary, etc. — things that don't show up
in price/technical data until after the fact.
"""

import json
import requests
from anthropic import Anthropic

NEWS_API_URL = "https://newsapi.org/v2/everything"

SCORING_SYSTEM_PROMPT = """You are a macro/gold-market analyst. You will be given \
a list of recent news headlines and short descriptions. For each one, assess its \
likely impact on the price of gold (XAU/USD).

Respond ONLY with a JSON array (no preamble, no markdown fences), where each \
element has this exact shape:
{
  "headline": "<original headline, shortened if needed>",
  "impact": "bullish" | "bearish" | "neutral",
  "conviction": "high" | "medium" | "low",
  "reason": "<one short phrase, e.g. 'flight to safety demand'>"
}

Guidelines:
- Geopolitical tension/war/crisis -> typically bullish (safe haven demand)
- Hawkish Fed / rising real rates -> typically bearish (higher opportunity cost)
- Dollar strength -> typically bearish; dollar weakness -> typically bullish
- Central bank gold buying/reserve diversification -> bullish
- Strong risk-on equity rallies with no inflation concern -> mildly bearish
- If a headline isn't clearly gold-relevant, mark it "neutral" / "low" conviction
- Be conservative with "high" conviction — reserve it for major, unambiguous events
"""


def fetch_headlines(api_key: str, keywords: list, lookback_hours: int, max_results: int) -> list:
    """Fetch recent headlines matching gold-relevant keywords."""
    query = " OR ".join(f'"{kw}"' for kw in keywords)
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_results,
        "apiKey": api_key,
    }
    resp = requests.get(NEWS_API_URL, params=params, timeout=10)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])

    return [
        {
            "headline": a.get("title", ""),
            "description": a.get("description", "") or "",
            "source": (a.get("source") or {}).get("name", ""),
            "published_at": a.get("publishedAt", ""),
        }
        for a in articles
    ]


def score_headlines(headlines: list, anthropic_api_key: str) -> list:
    """Send headlines to Claude for structured bullish/bearish/conviction scoring."""
    if not headlines:
        return []

    client = Anthropic(api_key=anthropic_api_key)

    formatted = "\n".join(
        f"- {h['headline']} — {h['description']} (source: {h['source']})"
        for h in headlines
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SCORING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Headlines:\n{formatted}"}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fail safe: return empty rather than crash the whole pipeline
        return []


def get_news_snapshot(news_api_key: str, anthropic_api_key: str, keywords: list,
                       lookback_hours: int = 24, max_headlines: int = 15) -> dict:
    """
    Returns scored news events plus an aggregate news_score (0-100, higher = more bullish).
    """
    headlines = fetch_headlines(news_api_key, keywords, lookback_hours, max_headlines)
    scored = score_headlines(headlines, anthropic_api_key)

    if not scored:
        return {"news_score": 50.0, "events": []}

    conviction_weight = {"high": 3, "medium": 2, "low": 1}
    impact_direction = {"bullish": 1, "bearish": -1, "neutral": 0}

    total_weight = 0
    weighted_sum = 0
    for event in scored:
        w = conviction_weight.get(event.get("conviction", "low"), 1)
        d = impact_direction.get(event.get("impact", "neutral"), 0)
        weighted_sum += w * d
        total_weight += w

    # Normalize to 0-100 scale (50 = neutral)
    if total_weight > 0:
        avg = weighted_sum / total_weight  # ranges -1 to 1
        news_score = 50 + (avg * 50)
    else:
        news_score = 50.0

    # Sort by conviction so the most important events surface first
    scored_sorted = sorted(
        scored,
        key=lambda e: conviction_weight.get(e.get("conviction", "low"), 1),
        reverse=True,
    )

    return {
        "news_score": round(max(0.0, min(100.0, news_score)), 1),
        "events": scored_sorted,
    }
