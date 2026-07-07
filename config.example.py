"""
Copy this file to config.py and fill in your own API keys.
config.py is gitignored so you never commit secrets.
Environment variables with the same names override these values in production.
"""

# --- API Keys ---
FRED_API_KEY = "your_fred_key_here"
NEWS_API_KEY = "your_newsapi_key_here"
GOLD_API_KEY = "your_goldapi_key_here"
ANTHROPIC_API_KEY = "your_anthropic_key_here"

# --- Signal weighting (must sum to 1.0) ---
# Tune these based on your own backtesting. This is just a reasonable starting point.
WEIGHTS = {
    "technical": 0.35,
    "macro": 0.30,
    "news": 0.35,
}

# --- Alert thresholds ---
# Composite score is 0-100. Above BULLISH_THRESHOLD -> bullish alert.
# Below BEARISH_THRESHOLD -> bearish alert.
BULLISH_THRESHOLD = 65
BEARISH_THRESHOLD = 35

# --- News settings ---
NEWS_LOOKBACK_HOURS = 24
NEWS_KEYWORDS = [
    "gold price", "Federal Reserve", "interest rates", "inflation",
    "geopolitical tension", "dollar index", "central bank gold",
]
MAX_HEADLINES_TO_SCORE = 15
