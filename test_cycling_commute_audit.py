import datetime as dt
import json

import pytest

from run_page.audit_cycling_commutes import (
    CommuteRoute,
    classify_route,
    percentile,
    write_web_json,
)


HOME = (34.0, 119.0)
WORK = (34.02, 119.01)
ROUTES = (CommuteRoute("test_home", HOME, WORK),)


def test_known_evening_commute_is_confirmed():
    match = classify_route(
        dt.datetime(2023, 1, 2, 18, 0),
        WORK,
        HOME,
        ROUTES,
        frozenset({"2023-01-02 18:00:00"}),
    )

    assert match is not None
    assert match.confidence == "confirmed"
    assert match.direction == "work_to_home"


def test_weekday_morning_route_is_high_confidence():
    match = classify_route(dt.datetime(2023, 1, 4, 8), HOME, WORK, ROUTES)

    assert match is not None
    assert match.confidence == "high"
    assert match.direction == "home_to_work"


def test_weekend_route_requires_manual_review():
    match = classify_route(dt.datetime(2023, 1, 7, 8), HOME, WORK, ROUTES)

    assert match is not None
    assert match.confidence == "medium"


def test_unrelated_route_is_not_a_candidate():
    assert (
        classify_route(
            dt.datetime(2023, 1, 4, 8),
            (31.0, 118.0),
            (31.1, 118.1),
            ROUTES,
        )
        is None
    )


def test_percentile_interpolates_values():
    assert percentile([1.0, 2.0, 3.0], 0.75) == pytest.approx(2.5)


def test_web_review_data_omits_location_fields(tmp_path):
    output = tmp_path / "cycling-review.json"
    row = {
        "run_id": 1,
        "confidence": "high",
        "route_group": "test_home",
        "direction": "home_to_work",
        "start_date_local": "2023-01-02 08:00:00",
        "weekday": "Monday",
        "distance_km": "3.500",
        "moving_time": "00:15:00",
        "average_speed_mps": "3.889",
        "average_speed_kmh": "14.00",
        "endpoint_error_m": "10.0",
        "start_lat": "34.000000",
        "start_lon": "119.000000",
    }

    write_web_json([row], output)

    record = json.loads(output.read_text(encoding="utf-8"))["records"][0]
    assert record["run_id"] == 1
    assert "start_lat" not in record
    assert "start_lon" not in record
