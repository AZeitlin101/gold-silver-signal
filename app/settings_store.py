"""Simple JSON-backed settings persistence for the gold dashboard."""

import json
from pathlib import Path
from typing import Any, Dict

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings(defaults: Dict[str, Any]) -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {**defaults, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def save_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
