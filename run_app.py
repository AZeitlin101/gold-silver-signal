import uvicorn
import os
from pathlib import Path

# Load .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

# Debug: print what was loaded
if os.getenv("GOLD_API_KEY"):
    print(f"✓ GOLD_API_KEY loaded ({len(os.getenv('GOLD_API_KEY', ''))} chars)")
if os.getenv("FRED_API_KEY"):
    print(f"✓ FRED_API_KEY loaded ({len(os.getenv('FRED_API_KEY', ''))} chars)")
if os.getenv("NEWS_API_KEY"):
    print(f"✓ NEWS_API_KEY loaded ({len(os.getenv('NEWS_API_KEY', ''))} chars)")
if os.getenv("ANTHROPIC_API_KEY"):
    print(f"✓ ANTHROPIC_API_KEY loaded ({len(os.getenv('ANTHROPIC_API_KEY', ''))} chars)")

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
