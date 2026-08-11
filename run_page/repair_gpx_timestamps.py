"""Repair timestamp corruption in GPX files exported from Joyrun.

Some Joyrun pause records use 100000 seconds as a segment marker.  The
exporter adds that value to following track points, then writes the API end
time unchanged for the final point.  The result contains large positive jumps
and, usually, a backwards final timestamp.

This module reconstructs a monotonic timeline without changing coordinates or
overwriting source files.  Unchanged files can either be copied or symlinked
into a separate output directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from lxml import etree


JOYRUN_PAUSE_OFFSET_SECONDS = 100_000
DEFAULT_SAMPLE_INTERVAL_SECONDS = 5
DEFAULT_MAX_REPAIRED_GAP_SECONDS = 3_600


@dataclass(frozen=True)
class RepairEvent:
    point_index: int
    original_previous: str
    original_current: str
    original_delta_seconds: int
    repaired_delta_seconds: int
    reason: str


@dataclass(frozen=True)
class FileRepair:
    file_name: str
    point_count: int
    sample_interval_seconds: int
    original_start: str
    original_end: str
    repaired_start: str
    repaired_end: str
    events: tuple[RepairEvent, ...]
    metadata_fields: tuple[str, ...]


def parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def format_timestamp(value: dt.datetime, original: str) -> str:
    if original.endswith("Z"):
        utc_value = value.astimezone(dt.timezone.utc)
        timespec = "microseconds" if "." in original else "seconds"
        return utc_value.isoformat(timespec=timespec).replace("+00:00", "Z")
    return value.isoformat(timespec="microseconds" if "." in original else "seconds")


def infer_sample_interval(timestamps: list[dt.datetime]) -> int:
    normal_deltas = [
        int((current - previous).total_seconds())
        for previous, current in zip(timestamps, timestamps[1:])
        if 0 < (current - previous).total_seconds() <= 60
    ]
    if not normal_deltas:
        return DEFAULT_SAMPLE_INTERVAL_SECONDS
    return max(1, int(median(normal_deltas)))


def _nearest_offset_count(delta_seconds: int, offset_seconds: int) -> int:
    ratio = delta_seconds / offset_seconds
    return math.floor(ratio + 0.5) if ratio >= 0 else math.ceil(ratio - 0.5)


def repair_timeline(
    timestamps: list[dt.datetime],
    *,
    pause_offset_seconds: int = JOYRUN_PAUSE_OFFSET_SECONDS,
    max_repaired_gap_seconds: int = DEFAULT_MAX_REPAIRED_GAP_SECONDS,
) -> tuple[list[dt.datetime], tuple[RepairEvent, ...]]:
    if len(timestamps) < 2:
        return timestamps.copy(), ()

    sample_interval = infer_sample_interval(timestamps)
    repaired = [timestamps[0]]
    events: list[RepairEvent] = []

    for point_index, (original_previous, original_current) in enumerate(
        zip(timestamps, timestamps[1:]), start=1
    ):
        original_delta = int((original_current - original_previous).total_seconds())
        repaired_delta = original_delta
        reason = ""

        if original_delta < 0 or original_delta >= pause_offset_seconds // 2:
            offset_count = _nearest_offset_count(
                original_delta, pause_offset_seconds
            )
            offset_candidate = original_delta - offset_count * pause_offset_seconds
            if (
                offset_count != 0
                and 0 <= offset_candidate <= max_repaired_gap_seconds
            ):
                repaired_delta = offset_candidate
                reason = "joyrun_pause_offset"
            elif original_delta < 0:
                repaired_delta = sample_interval
                reason = "backwards_timestamp_fallback"

        repaired.append(repaired[-1] + dt.timedelta(seconds=repaired_delta))
        if reason:
            events.append(
                RepairEvent(
                    point_index=point_index,
                    original_previous=original_previous.isoformat(),
                    original_current=original_current.isoformat(),
                    original_delta_seconds=original_delta,
                    repaired_delta_seconds=repaired_delta,
                    reason=reason,
                )
            )

    return repaired, tuple(events)


def _is_joyrun(tree: etree._ElementTree) -> bool:
    names = tree.xpath(
        "//*[local-name()='trk']/*[local-name()='name']/text()"
    )
    return any(str(name).lower().startswith("gpx from joyrun ") for name in names)


def parse_duration_seconds(value: str) -> int:
    day_seconds = 0
    time_value = value
    if ", " in value:
        day_value, time_value = value.split(", ", maxsplit=1)
        day_seconds = int(day_value.split()[0]) * 86_400
    hours, minutes, seconds = time_value.split(":")
    return day_seconds + int(hours) * 3_600 + int(minutes) * 60 + int(float(seconds))


def _set_root_extension(
    tree: etree._ElementTree, item_name: str, value: object
) -> None:
    root = tree.getroot()
    namespace = etree.QName(root).namespace
    extension_tag = f"{{{namespace}}}extensions" if namespace else "extensions"
    item_tag = f"{{{namespace}}}{item_name}" if namespace else item_name
    extensions = next(
        (
            child
            for child in root
            if etree.QName(child).localname == "extensions"
        ),
        None,
    )
    if extensions is None:
        extensions = etree.SubElement(root, extension_tag)
    item = next(
        (
            child
            for child in extensions
            if etree.QName(child).localname == item_name
        ),
        None,
    )
    if item is None:
        item = etree.SubElement(extensions, item_tag)
    item.text = str(value)


def _add_reference_metadata(
    tree: etree._ElementTree,
    reference_activity: dict,
    elapsed_time_seconds: int,
) -> tuple[str, ...]:
    metadata = {
        "distance": reference_activity.get("distance"),
        "moving_time": (
            parse_duration_seconds(reference_activity["moving_time"])
            if reference_activity.get("moving_time")
            else None
        ),
        "elapsed_time": elapsed_time_seconds,
        "average_speed": reference_activity.get("average_speed"),
        "average_hr": reference_activity.get("average_heartrate"),
        "location_country": reference_activity.get("location_country"),
    }
    restored_fields = []
    for item_name, value in metadata.items():
        if value is None or value == "":
            continue
        _set_root_extension(tree, item_name, value)
        restored_fields.append(item_name)
    return tuple(restored_fields)


def repair_gpx_file(
    source: Path,
    destination: Path | None = None,
    *,
    max_repaired_gap_seconds: int = DEFAULT_MAX_REPAIRED_GAP_SECONDS,
    reference_activity: dict | None = None,
) -> FileRepair | None:
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(source), parser)
    if not _is_joyrun(tree):
        return None

    time_elements = [
        element
        for element in tree.xpath(
            "//*[local-name()='trkpt']/*[local-name()='time']"
        )
        if element.text
    ]
    original_values = [element.text for element in time_elements]
    if not original_values:
        return None
    timestamps = [parse_timestamp(value) for value in original_values]
    repaired, events = repair_timeline(
        timestamps, max_repaired_gap_seconds=max_repaired_gap_seconds
    )
    metadata_fields: tuple[str, ...] = ()
    if reference_activity is not None:
        elapsed_time_seconds = max(
            0, int((repaired[-1] - repaired[0]).total_seconds())
        )
        metadata_fields = _add_reference_metadata(
            tree, reference_activity, elapsed_time_seconds
        )
    if not events and not metadata_fields:
        return None

    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        for element, original, repaired_timestamp in zip(
            time_elements, original_values, repaired
        ):
            element.text = format_timestamp(repaired_timestamp, original)
        tree.write(
            str(destination),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )

    return FileRepair(
        file_name=source.name,
        point_count=len(timestamps),
        sample_interval_seconds=infer_sample_interval(timestamps),
        original_start=timestamps[0].isoformat(),
        original_end=timestamps[-1].isoformat(),
        repaired_start=repaired[0].isoformat(),
        repaired_end=repaired[-1].isoformat(),
        events=events,
        metadata_fields=metadata_fields,
    )


def repair_directory(
    source_dir: Path,
    output_dir: Path | None,
    *,
    symlink_unchanged: bool = False,
    max_repaired_gap_seconds: int = DEFAULT_MAX_REPAIRED_GAP_SECONDS,
    reference_activities: dict[str, dict] | None = None,
) -> list[FileRepair]:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {source_dir}")
    if output_dir is not None:
        if output_dir.exists():
            raise ValueError(f"Output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True)

    repairs: list[FileRepair] = []
    for source in sorted(source_dir.glob("*.gpx")):
        destination = output_dir / source.name if output_dir is not None else None
        repair = repair_gpx_file(
            source,
            destination,
            max_repaired_gap_seconds=max_repaired_gap_seconds,
            reference_activity=(reference_activities or {}).get(source.stem),
        )
        if repair is not None:
            repairs.append(repair)
        elif destination is not None:
            if symlink_unchanged:
                destination.symlink_to(source)
            else:
                shutil.copy2(source, destination)

    if output_dir is not None:
        report_path = output_dir / "repair-report.json"
        report_path.write_text(
            json.dumps([asdict(repair) for repair in repairs], indent=2),
            encoding="utf-8",
        )
    return repairs


def load_reference_activities(source: str) -> dict[str, dict]:
    if source == "-":
        activities = json.load(sys.stdin)
    else:
        with Path(source).open(encoding="utf-8") as reference_file:
            activities = json.load(reference_file)
    return {
        str(activity["run_id"]): activity
        for activity in activities
        if activity.get("name") == "run from joyrun"
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair Joyrun timestamp offsets into a separate GPX directory."
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path, nargs="?")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Audit input files without writing an output directory.",
    )
    parser.add_argument(
        "--symlink-unchanged",
        action="store_true",
        help="Symlink unchanged GPX files instead of copying them.",
    )
    parser.add_argument(
        "--max-repaired-gap",
        type=int,
        default=DEFAULT_MAX_REPAIRED_GAP_SECONDS,
        help="Largest plausible gap after removing a 100000-second offset.",
    )
    parser.add_argument(
        "--reference-activities",
        help=(
            "Historical activities JSON used to restore Joyrun distance, time, "
            "speed and location metadata; use - to read stdin."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.report_only and args.output_dir is None:
        raise SystemExit("output_dir is required unless --report-only is used")
    output_dir = None if args.report_only else args.output_dir
    reference_activities = (
        load_reference_activities(args.reference_activities)
        if args.reference_activities
        else None
    )
    repairs = repair_directory(
        args.input_dir,
        output_dir,
        symlink_unchanged=args.symlink_unchanged,
        max_repaired_gap_seconds=args.max_repaired_gap,
        reference_activities=reference_activities,
    )
    timestamp_repairs = sum(bool(repair.events) for repair in repairs)
    metadata_repairs = sum(bool(repair.metadata_fields) for repair in repairs)
    print(f"Timestamp-repaired files: {timestamp_repairs}")
    print(f"Metadata-enriched files: {metadata_repairs}")
    for repair in repairs:
        if not repair.events:
            continue
        reasons = sorted({event.reason for event in repair.events})
        print(
            f"{repair.file_name}: {len(repair.events)} corrections, "
            f"{repair.original_end} -> {repair.repaired_end}, "
            f"reasons={','.join(reasons)}"
        )


if __name__ == "__main__":
    main()
