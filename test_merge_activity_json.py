import json

import pytest

from run_page.merge_activity_json import merge_preserving_existing


def record(run_id, start_date_local, *, streak, name="Run"):
    return {
        "run_id": run_id,
        "name": name,
        "start_date_local": start_date_local,
        "streak": streak,
    }


def test_existing_records_win_and_new_records_are_added_in_date_order(tmp_path):
    activities_json = tmp_path / "activities.json"
    existing = [record(1, "2026-08-10 08:00:00", streak=9, name="Reviewed")]
    generated = [
        record(2, "2026-08-12 08:00:00", streak=2, name="New Garmin"),
        record(1, "2026-08-10 08:00:00", streak=1, name="Regenerated"),
    ]
    activities_json.write_text(json.dumps(generated), encoding="utf-8")

    assert merge_preserving_existing(activities_json, existing) == 1
    assert json.loads(activities_json.read_text(encoding="utf-8")) == [
        existing[0],
        generated[0],
    ]


def test_missing_historical_record_is_rejected(tmp_path):
    activities_json = tmp_path / "activities.json"
    activities_json.write_text(
        json.dumps([record(2, "2026-08-12 08:00:00", streak=1)]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lost 1 historical records"):
        merge_preserving_existing(
            activities_json,
            [record(1, "2026-08-10 08:00:00", streak=9)],
        )
