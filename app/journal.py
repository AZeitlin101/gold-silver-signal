"""Simple JSON-backed trading journal for logging trades and notes."""

import json
from pathlib import Path
from typing import Any, Dict, List

JOURNAL_PATH = Path(__file__).resolve().parent.parent / "journal.json"


def load_journal() -> List[Dict[str, Any]]:
    if JOURNAL_PATH.exists():
        try:
            with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_journal(entries: List[Dict[str, Any]]) -> None:
    JOURNAL_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def add_entry(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = load_journal()
    entries.append(entry)
    save_journal(entries)
    return entries
