import datetime as dt
from types import SimpleNamespace

from run_page.gpxtrackposter.track import Track
from run_page.repair_gpx_timestamps import (
    parse_duration_seconds,
    repair_gpx_file,
    repair_timeline,
)


UTC = dt.timezone.utc


def test_repairs_joyrun_pause_offsets_and_backwards_end_time():
    start = dt.datetime(2020, 1, 1, tzinfo=UTC)
    timestamps = [
        start,
        start + dt.timedelta(seconds=5),
        start + dt.timedelta(seconds=100_009),
        start + dt.timedelta(seconds=100_014),
        start + dt.timedelta(seconds=19),
    ]

    repaired, events = repair_timeline(timestamps)

    assert repaired == [start + dt.timedelta(seconds=i) for i in (0, 5, 9, 14, 19)]
    assert [event.repaired_delta_seconds for event in events] == [4, 5]


def test_uses_sampling_interval_for_unrecoverable_backwards_final_point():
    start = dt.datetime(2020, 1, 1, tzinfo=UTC)
    timestamps = [
        start,
        start + dt.timedelta(seconds=5),
        start - dt.timedelta(seconds=61_844),
    ]

    repaired, events = repair_timeline(timestamps)

    assert repaired[-1] == start + dt.timedelta(seconds=10)
    assert events[-1].reason == "backwards_timestamp_fallback"


def test_preserves_a_long_pause_without_joyrun_offset_signature():
    start = dt.datetime(2020, 1, 1, tzinfo=UTC)
    timestamps = [start, start + dt.timedelta(seconds=4_089)]

    repaired, events = repair_timeline(timestamps)

    assert repaired == timestamps
    assert not events


def test_moving_time_is_local_to_each_segment_and_ignores_backwards_time():
    track = Track()
    track.start_time = dt.datetime(2020, 1, 1, tzinfo=UTC)
    segment_start = track.start_time + dt.timedelta(seconds=100_004)
    points = [
        SimpleNamespace(time=segment_start),
        SimpleNamespace(time=segment_start + dt.timedelta(seconds=5)),
        SimpleNamespace(time=segment_start - dt.timedelta(seconds=10)),
    ]

    assert track._calc_moving_time(points) == 5


def test_parses_historical_timedelta_strings():
    assert parse_duration_seconds("0:26:47") == 1_607
    assert parse_duration_seconds("1 day, 4:32:12") == 102_732


def test_restores_reference_metadata_without_modifying_source(tmp_path):
    source = tmp_path / "60855154.gpx"
    destination = tmp_path / "repaired" / source.name
    source.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <trk><name>gpx from joyrun 1468361126</name><trkseg>
    <trkpt lat="31.0" lon="118.0"><time>2020-01-01T00:00:00Z</time></trkpt>
    <trkpt lat="31.1" lon="118.1"><time>2020-01-01T00:00:05Z</time></trkpt>
  </trkseg></trk>
</gpx>""",
        encoding="utf-8",
    )
    original = source.read_bytes()

    repair = repair_gpx_file(
        source,
        destination,
        reference_activity={
            "distance": 5014.0,
            "moving_time": "0:26:47",
            "average_speed": 3.1201,
            "average_heartrate": None,
            "location_country": "南京市:江苏省",
        },
    )

    assert source.read_bytes() == original
    assert repair is not None
    assert set(repair.metadata_fields) == {
        "distance",
        "moving_time",
        "elapsed_time",
        "average_speed",
        "location_country",
    }
    repaired_xml = destination.read_text(encoding="utf-8")
    assert "<distance>5014.0</distance>" in repaired_xml
    assert "<moving_time>1607</moving_time>" in repaired_xml
    assert "<location_country>南京市:江苏省</location_country>" in repaired_xml
