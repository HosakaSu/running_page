"""Durable incremental state for Garmin syncs on ephemeral runners."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_activity_ids(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()

    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, list):
        raise ValueError("Garmin sync state must contain a list")

    activity_ids = {str(value) for value in payload}
    if any(not value.isdigit() or int(value) <= 0 for value in activity_ids):
        raise ValueError("Garmin sync state contains an invalid activity ID")
    return activity_ids


def save_activity_ids(path: Path, activity_ids: set[str]) -> bool:
    """Atomically save IDs; return whether the tracked state changed."""

    path = Path(path)
    normalized = {str(value) for value in activity_ids}
    if any(not value.isdigit() or int(value) <= 0 for value in normalized):
        raise ValueError("Cannot save an invalid Garmin activity ID")
    if load_activity_ids(path) == normalized:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(sorted(normalized, key=int), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return True
