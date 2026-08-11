"""Merge generated activities without rewriting reviewed historical records."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _index_activities(
    activities: list[dict[str, object]], source: str
) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for activity in activities:
        if not isinstance(activity, dict) or "run_id" not in activity:
            raise ValueError(f"{source} contains an invalid activity record")
        run_id = int(activity["run_id"])
        if run_id in indexed:
            raise ValueError(f"{source} contains duplicate run_id {run_id}")
        indexed[run_id] = activity
    return indexed


def merge_preserving_existing(
    activities_json: Path, existing_activities: list[dict[str, object]]
) -> int:
    """Keep existing JSON records byte-for-field and append generated records.

    The regenerated SQLite representation does not carry frontend-only fields
    such as the previously reviewed streak.  Existing records therefore win on
    matching IDs, while genuinely new Garmin activities come from the generator.
    """

    activities_json = Path(activities_json)
    with activities_json.open(encoding="utf-8") as stream:
        generated_activities = json.load(stream)
    if not isinstance(generated_activities, list):
        raise ValueError("Generated activities JSON must contain a list")

    existing = _index_activities(existing_activities, "Existing activities JSON")
    generated = _index_activities(generated_activities, "Generated activities JSON")
    missing = sorted(set(existing) - set(generated))
    if missing:
        raise ValueError(
            f"Generated activities lost {len(missing)} historical records: "
            f"{missing[:5]}"
        )

    merged = generated | existing
    ordered = sorted(
        merged.values(),
        key=lambda activity: (
            str(activity.get("start_date_local") or ""),
            int(activity["run_id"]),
        ),
    )
    temporary = activities_json.with_suffix(f"{activities_json.suffix}.tmp")
    temporary.write_text(
        json.dumps(ordered, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, activities_json)
    return len(ordered) - len(existing)
