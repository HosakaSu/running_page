import datetime as dt
import json
import sqlite3

import pytest

from run_page.restore_activity_database import (
    get_database_activity_ids,
    parse_duration,
    restore_database_from_json,
)


def activity(run_id=123):
    return {
        "run_id": run_id,
        "name": "Morning Run",
        "distance": 5000.5,
        "moving_time": "1:02:03.500000",
        "type": "Run",
        "subtype": "",
        "start_date": "2026-08-12 00:00:00",
        "start_date_local": "2026-08-12 08:00:00",
        "location_country": "Singapore",
        "summary_polyline": "encoded",
        "average_heartrate": 150,
        "average_speed": 1.34,
        "elevation_gain": 12.5,
        "streak": 5,
    }


def test_parse_duration_supports_timedelta_output():
    assert parse_duration("1:02:03.500000") == dt.timedelta(
        hours=1, minutes=2, seconds=3.5
    )
    assert parse_duration("2 days, 3:04:05") == dt.timedelta(
        days=2, hours=3, minutes=4, seconds=5
    )


def test_restore_empty_database_from_activities_json(tmp_path):
    database = tmp_path / "data.db"
    activities_json = tmp_path / "activities.json"
    activities_json.write_text(json.dumps([activity()]), encoding="utf-8")

    assert restore_database_from_json(database, activities_json) == 1
    assert get_database_activity_ids(database) == {"123"}

    connection = sqlite3.connect(database)
    restored = connection.execute(
        "SELECT name, moving_time, elapsed_time, summary_polyline FROM activities"
    ).fetchone()
    connection.close()
    assert restored == (
        "Morning Run",
        "1970-01-01 01:02:03.500000",
        "1970-01-01 01:02:03.500000",
        "encoded",
    )


def test_existing_database_is_never_overwritten(tmp_path):
    database = tmp_path / "data.db"
    activities_json = tmp_path / "activities.json"
    activities_json.write_text(json.dumps([activity(456)]), encoding="utf-8")
    assert restore_database_from_json(database, activities_json) == 1
    activities_json.write_text(json.dumps([activity(999)]), encoding="utf-8")

    assert restore_database_from_json(database, activities_json) == 0
    assert get_database_activity_ids(database) == {"456"}


def test_duplicate_run_ids_are_rejected_without_partial_rows(tmp_path):
    database = tmp_path / "data.db"
    activities_json = tmp_path / "activities.json"
    activities_json.write_text(
        json.dumps([activity(), activity()]), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="duplicate run_id"):
        restore_database_from_json(database, activities_json)

    assert get_database_activity_ids(database) == set()
