"""Build a local review list for Apple Health routes that resemble bike commutes.

Apple Health route GPX files do not carry the workout type.  This audit therefore
uses repeated route endpoints plus commute direction/time as evidence, and never
changes the activities database itself.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sqlite3
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GPX_DIR = ROOT / "GPX_OUT"
DEFAULT_DATABASE = ROOT / "run_page" / "data.db"
DEFAULT_OUTPUT = ROOT / "reports" / "suspected_cycling_commutes_2023_2025.csv"
DEFAULT_SUMMARY = ROOT / "reports" / "suspected_cycling_commutes_2023_2025.md"
DEFAULT_CONFIG = ROOT / "reports" / "commute_audit_config.json"
YEARS = {2023, 2024, 2025}
CORE_ENDPOINT_METRES = 500.0
REVIEW_ENDPOINT_METRES = 750.0


@dataclass(frozen=True)
class CommuteRoute:
    name: str
    home: tuple[float, float]
    work: tuple[float, float]


@dataclass(frozen=True)
class RouteMatch:
    route: str
    direction: str
    endpoint_error_metres: float
    confidence: str
    reason: str


def haversine_metres(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    """Return great-circle distance between two latitude/longitude points."""
    radius = 6_371_008.8
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def _direction_error(
    start: tuple[float, float],
    end: tuple[float, float],
    expected_start: tuple[float, float],
    expected_end: tuple[float, float],
) -> float:
    return max(
        haversine_metres(start, expected_start),
        haversine_metres(end, expected_end),
    )


def is_direction_time_aligned(local_time: dt.datetime, direction: str) -> bool:
    """Check the conservative weekday commute window for one direction."""
    if local_time.weekday() >= 5:
        return False
    if direction == "home_to_work":
        return dt.time(6, 0) <= local_time.time() < dt.time(11, 0)
    return dt.time(16, 0) <= local_time.time() < dt.time(22, 0)


def classify_route(
    local_time: dt.datetime,
    start: tuple[float, float],
    end: tuple[float, float],
    routes: tuple[CommuteRoute, ...],
    confirmed_rides: frozenset[str] = frozenset(),
) -> RouteMatch | None:
    """Classify a route without claiming that commute evidence proves cycling."""
    matches: list[tuple[float, CommuteRoute, str]] = []
    for route in routes:
        matches.extend(
            (
                (
                    _direction_error(start, end, route.home, route.work),
                    route,
                    "home_to_work",
                ),
                (
                    _direction_error(start, end, route.work, route.home),
                    route,
                    "work_to_home",
                ),
            )
        )

    error, route, direction = min(matches, key=lambda item: item[0])
    if error > REVIEW_ENDPOINT_METRES:
        return None

    local_text = local_time.strftime("%Y-%m-%d %H:%M:%S")
    if local_text in confirmed_rides:
        confidence = "confirmed"
        reason = "user_confirmed_bike_commute"
    elif error <= CORE_ENDPOINT_METRES and is_direction_time_aligned(
        local_time, direction
    ):
        confidence = "high"
        reason = "same_endpoints_and_weekday_direction_time"
    elif error <= CORE_ENDPOINT_METRES:
        confidence = "medium"
        reason = "same_endpoints_but_time_or_weekday_not_aligned"
    else:
        confidence = "review"
        reason = "near_commute_endpoints_boundary_match"

    return RouteMatch(route.name, direction, error, confidence, reason)


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (child for child in element.iter() if _local_name(child) == name)


def parse_apple_route(
    path: Path,
    routes: tuple[CommuteRoute, ...],
    confirmed_rides: frozenset[str],
) -> dict[str, object] | None:
    """Read only the evidence needed for the audit from an Apple route GPX."""
    root = ET.parse(path).getroot()
    if root.attrib.get("creator") != "Apple Health Export":
        return None

    track = next(_children(root, "trk"), None)
    if track is None:
        return None
    name_element = next(
        (child for child in track if _local_name(child) == "name"), None
    )
    points = list(_children(track, "trkpt"))
    if name_element is None or not name_element.text or not points:
        return None

    first_time = next(_children(points[0], "time"), None)
    if first_time is None or not first_time.text:
        return None
    start_utc = dt.datetime.fromisoformat(first_time.text.replace("Z", "+00:00"))
    start_local = start_utc.astimezone(dt.timezone(dt.timedelta(hours=8))).replace(
        tzinfo=None
    )
    if start_local.year not in YEARS:
        return None

    speeds = [
        float(speed.text)
        for speed in _children(track, "speed")
        if speed.text is not None
    ]
    start = (float(points[0].attrib["lat"]), float(points[0].attrib["lon"]))
    end = (float(points[-1].attrib["lat"]), float(points[-1].attrib["lon"]))
    match = classify_route(start_local, start, end, routes, confirmed_rides)
    if match is None:
        return None

    return {
        "name": name_element.text,
        "start_local_from_gpx": start_local.strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": str(path.relative_to(ROOT)),
        "start_lat": start[0],
        "start_lon": start[1],
        "end_lat": end[0],
        "end_lon": end[1],
        "gps_speed_p95_mps": percentile(speeds, 0.95),
        "gps_speed_max_mps": max(speeds) if speeds else None,
        "gps_speed_above_5_fraction": (
            sum(speed >= 5 for speed in speeds) / len(speeds) if speeds else None
        ),
        "match": match,
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    epoch = dt.datetime(1970, 1, 1)
    return round((parsed - epoch).total_seconds())


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def load_activities(database: Path) -> dict[tuple[str, str], sqlite3.Row]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT run_id, name, distance, moving_time, type, start_date_local,
                   average_speed
              FROM activities
             WHERE substr(start_date_local, 1, 4) IN ('2023', '2024', '2025')
            """
        ).fetchall()
    finally:
        connection.close()
    return {(row["name"], row["start_date_local"]): row for row in rows}


def load_config(
    path: Path,
) -> tuple[tuple[CommuteRoute, ...], frozenset[str]]:
    """Load sensitive endpoint anchors from a gitignored local file."""
    with path.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    work = tuple(map(float, raw["work"]))
    routes = tuple(
        CommuteRoute(
            name=str(route["name"]),
            home=tuple(map(float, route["home"])),
            work=work,
        )
        for route in raw["routes"]
    )
    return routes, frozenset(map(str, raw.get("confirmed_rides", ())))


def _number(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def build_rows(
    gpx_dir: Path,
    database: Path,
    routes: tuple[CommuteRoute, ...],
    confirmed_rides: frozenset[str],
) -> tuple[list[dict[str, object]], int]:
    activities = load_activities(database)
    rows: list[dict[str, object]] = []
    unmatched = 0
    for path in sorted(gpx_dir.glob("*.gpx")):
        route = parse_apple_route(path, routes, confirmed_rides)
        if route is None:
            continue
        key = (str(route["name"]), str(route["start_local_from_gpx"]))
        activity = activities.get(key)
        if activity is None:
            unmatched += 1
            continue

        local_time = dt.datetime.fromisoformat(activity["start_date_local"])
        match = route["match"]
        assert isinstance(match, RouteMatch)
        moving_seconds = duration_seconds(activity["moving_time"])
        rows.append(
            {
                "decision": "",
                "confidence": match.confidence,
                "route_group": match.route,
                "direction": match.direction,
                "start_date_local": activity["start_date_local"],
                "weekday": local_time.strftime("%A"),
                "distance_km": _number(activity["distance"] / 1000),
                "moving_time": format_duration(moving_seconds),
                "average_speed_mps": _number(activity["average_speed"]),
                "average_speed_kmh": _number(activity["average_speed"] * 3.6, 2),
                "gps_speed_p95_mps": _number(route["gps_speed_p95_mps"]),
                "gps_speed_max_mps": _number(route["gps_speed_max_mps"]),
                "gps_speed_above_5_fraction": _number(
                    route["gps_speed_above_5_fraction"]
                ),
                "endpoint_error_m": _number(match.endpoint_error_metres, 1),
                "run_id": activity["run_id"],
                "current_type": activity["type"],
                "name": activity["name"],
                "source_file": route["source_file"],
                "start_lat": _number(route["start_lat"], 6),
                "start_lon": _number(route["start_lon"], 6),
                "end_lat": _number(route["end_lat"], 6),
                "end_lon": _number(route["end_lon"], 6),
                "reason": match.reason,
                "notes": "",
            }
        )
    rows.sort(key=lambda row: str(row["start_date_local"]))
    return rows, unmatched


def write_csv(rows: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    rows: list[dict[str, object]], unmatched: int, output: Path, csv_path: Path
) -> None:
    confidence = Counter(str(row["confidence"]) for row in rows)
    years = Counter(str(row["start_date_local"])[:4] for row in rows)
    directions = Counter(str(row["direction"]) for row in rows)
    speed_values = [float(row["average_speed_mps"]) for row in rows]
    output.parent.mkdir(parents=True, exist_ok=True)
    text = f"""# 2023–2025 疑似骑行通勤复核

生成时间：{dt.datetime.now().astimezone().isoformat(timespec="seconds")}

Apple Health route GPX 不包含运动类型，只有轨迹点、时间、速度和精度等字段，因此本报告是基于重复端点、方向和时段的人工复核候选，不能单靠原始 GPX 证明一定是骑行。Garmin 的 2025 GPX 包含 `running` 类型，未列入候选。

## 候选数量

- 总计：{len(rows)}
- 已由用户确认：{confidence["confirmed"]}
- 高疑似（端点 500m 内，工作日且方向/时段吻合）：{confidence["high"]}
- 中等疑似（端点 500m 内，但日期或时段不吻合）：{confidence["medium"]}
- 边界复核（端点误差 500–750m）：{confidence["review"]}
- 年份：2023={years["2023"]}，2024={years["2024"]}，2025={years["2025"]}
- 方向：上班={directions["home_to_work"]}，下班={directions["work_to_home"]}
- 候选平均速度中位数：{statistics.median(speed_values):.3f} m/s（{statistics.median(speed_values) * 3.6:.2f} km/h）
- 有通勤端点特征但未匹配数据库：{unmatched}

## 如何复核

CSV：`{csv_path.relative_to(ROOT)}`

请在 `decision` 列填写：

- `cycling`：确认是骑行，之后可从跑步展示中排除或改类型；
- `keep_running`：确认是跑步，继续保留；
- `unsure`：暂时无法判断。

建议先筛选 `confidence=medium` 和 `confidence=review`，高疑似记录则可按日期抽查。`gps_speed_*` 来自原始 Apple GPX 的速度扩展字段；端点坐标和本报告均已在 `.gitignore` 中排除，避免误提交个人位置。
"""
    output.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpx-dir", type=Path, default=DEFAULT_GPX_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    routes, confirmed_rides = load_config(args.config)
    rows, unmatched = build_rows(
        args.gpx_dir, args.database, routes, confirmed_rides
    )
    if not rows:
        raise SystemExit("No suspected commute routes found")
    write_csv(rows, args.output)
    write_summary(rows, unmatched, args.summary, args.output)
    print(f"Wrote {len(rows)} candidates to {args.output}")
    print(f"Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
