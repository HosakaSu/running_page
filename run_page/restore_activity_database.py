"""Restore the generated SQLite database from the tracked activities JSON.

GitHub-hosted runners start without ``run_page/data.db`` because that file
contains generated personal data and is intentionally ignored by Git.  The
tracked JSON is therefore the durable baseline for scheduled incremental syncs.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

_DURATION_PATTERN = re.compile(
    r"^(?:(?P<days>-?\d+) days?, )?"
    r"(?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>\d{2}(?:\.\d+)?)$"
)

_CREATE_ACTIVITIES_TABLE = """
CREATE TABLE IF NOT EXISTS activities (
    run_id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR,
    distance FLOAT,
    moving_time DATETIME,
    elapsed_time DATETIME,
    type VARCHAR,
    subtype VARCHAR,
    start_date VARCHAR,
    start_date_local VARCHAR,
    location_country VARCHAR,
    summary_polyline VARCHAR,
    average_heartrate FLOAT,
    average_speed FLOAT,
    elevation_gain FLOAT
)
"""

_INSERT_ACTIVITY = """
INSERT INTO activities (
    run_id, name, distance, moving_time, elapsed_time, type, subtype,
    start_date, start_date_local, location_country, summary_polyline,
    average_heartrate, average_speed, elevation_gain
) VALUES (
    :run_id, :name, :distance, :moving_time, :elapsed_time, :type, :subtype,
    :start_date, :start_date_local, :location_country, :summary_polyline,
    :average_heartrate, :average_speed, :elevation_gain
)
"""


def parse_duration(value: object) -> dt.timedelta:
    """Parse the string representation emitted by ``datetime.timedelta``."""

    if isinstance(value, dt.timedelta):
        return value
    if value is None or value == "":
        return dt.timedelta(0)

    match = _DURATION_PATTERN.fullmatch(str(value))
    if not match:
        raise ValueError(f"Invalid activity duration: {value!r}")

    minutes = int(match.group("minutes"))
    seconds = float(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid activity duration: {value!r}")

    return dt.timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours")),
        minutes=minutes,
        seconds=seconds,
    )


def _activity_mapping(record: dict[str, object]) -> dict[str, object]:
    try:
        run_id = int(record["run_id"])
        moving_time = parse_duration(record.get("moving_time"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid activity record: {record!r}") from error

    if run_id <= 0:
        raise ValueError(f"Invalid activity run_id: {run_id}")

    # SQLAlchemy's SQLite Interval type stores timedeltas as a datetime offset
    # from the Unix epoch.  Match that representation so the normal generator
    # can read the restored database without knowing it was reconstructed.
    encoded_moving_time = (dt.datetime(1970, 1, 1) + moving_time).isoformat(" ")

    return {
        "run_id": run_id,
        "name": record.get("name", ""),
        "distance": float(record.get("distance") or 0),
        "moving_time": encoded_moving_time,
        # elapsed_time is not exposed in activities.json.  Moving time is the
        # safest lossless fallback for poster generation and future imports.
        "elapsed_time": encoded_moving_time,
        "type": record.get("type", "Run"),
        "subtype": record.get("subtype", ""),
        "start_date": record.get("start_date", ""),
        "start_date_local": record.get("start_date_local", ""),
        "location_country": record.get("location_country", ""),
        "summary_polyline": record.get("summary_polyline", ""),
        "average_heartrate": record.get("average_heartrate"),
        "average_speed": float(record.get("average_speed") or 0),
        "elevation_gain": float(record.get("elevation_gain") or 0),
    }


def restore_database_from_json(database: Path, activities_json: Path) -> int:
    """Seed an empty database from activities JSON and return rows restored.

    An existing non-empty database is never changed.  This makes the function
    safe for local use while allowing an ephemeral GitHub runner to recover the
    complete historical running baseline before adding new Garmin activities.
    """

    database = Path(database)
    activities_json = Path(activities_json)
    if not activities_json.is_file():
        raise FileNotFoundError(f"Activities JSON not found: {activities_json}")

    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(_CREATE_ACTIVITIES_TABLE)
        if connection.execute("SELECT 1 FROM activities LIMIT 1").fetchone():
            return 0

        with activities_json.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, list):
            raise ValueError("Activities JSON must contain a list")

        mappings = [_activity_mapping(record) for record in payload]
        run_ids = [mapping["run_id"] for mapping in mappings]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("Activities JSON contains duplicate run_id values")

        if mappings:
            connection.executemany(_INSERT_ACTIVITY, mappings)
            connection.commit()
        return len(mappings)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_database_activity_ids(database: Path) -> set[str]:
    """Return activity IDs already represented in the generated database."""

    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(_CREATE_ACTIVITIES_TABLE)
        return {
            str(run_id)
            for (run_id,) in connection.execute("SELECT run_id FROM activities")
        }
    finally:
        connection.close()
