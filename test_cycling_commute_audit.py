import datetime as dt

import pytest

from run_page.audit_cycling_commutes import (
    CommuteRoute,
    classify_route,
    percentile,
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
