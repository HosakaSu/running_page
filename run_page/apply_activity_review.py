"""Apply human-reviewed activity types while preserving source data.

The GPX files are never modified. Confirmed cycling records remain in SQLite as
``cycling`` and can optionally be omitted from the Running Page JSON output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ALLOWED_DECISIONS = {"cycling", "keep_running", "unsure"}


@dataclass(frozen=True)
class ReviewSummary:
    total: int
    cycling: int
    keep_running: int
    unsure: int
    json_before: int
    json_after: int
    backup_dir: Path


def load_review(path: Path) -> dict[int, str]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, dict):
        raise ValueError("Review file must contain a decisions object")

    decisions: dict[int, str] = {}
    for raw_run_id, raw_decision in raw_decisions.items():
        try:
            run_id = int(raw_run_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid run_id: {raw_run_id!r}") from error
        decision = str(raw_decision)
        if run_id <= 0 or decision not in ALLOWED_DECISIONS:
            raise ValueError(f"Invalid review decision: {raw_run_id}={decision!r}")
        decisions[run_id] = decision
    if not decisions:
        raise ValueError("Review file has no decisions")
    return decisions


def _backup_files(
    database: Path, activities_json: Path, review_file: Path, backup_root: Path
) -> Path:
    timestamp = dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_root / f"activity-review-{timestamp}"
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(database, destination / database.name)
    shutil.copy2(activities_json, destination / activities_json.name)
    shutil.copy2(review_file, destination / review_file.name)
    return destination


def apply_review(
    database: Path,
    activities_json: Path,
    review_file: Path,
    *,
    running_only_output: bool,
    backup_root: Path,
) -> ReviewSummary:
    decisions = load_review(review_file)
    with activities_json.open(encoding="utf-8") as stream:
        activities = json.load(stream)
    if not isinstance(activities, list):
        raise ValueError("Activities JSON must contain a list")

    json_ids = {int(activity["run_id"]) for activity in activities}
    connection = sqlite3.connect(database)
    try:
        db_ids = {row[0] for row in connection.execute("SELECT run_id FROM activities")}
        missing_db = sorted(set(decisions) - db_ids)
        required_json_ids = {
            run_id
            for run_id, decision in decisions.items()
            if not running_only_output or decision != "cycling"
        }
        missing_json = sorted(required_json_ids - json_ids)
        if missing_db or missing_json:
            raise ValueError(
                "Review records are missing from current data: "
                f"database={missing_db[:5]}, json={missing_json[:5]}"
            )

        rewritten = []
        for activity in activities:
            run_id = int(activity["run_id"])
            decision = decisions.get(run_id)
            if decision == "cycling":
                activity["type"] = "cycling"
                if running_only_output:
                    continue
            elif decision == "keep_running":
                activity["type"] = "Run"
            rewritten.append(activity)

        backup_dir = _backup_files(database, activities_json, review_file, backup_root)
        temporary_json = activities_json.with_suffix(".json.tmp")
        temporary_json.write_text(
            json.dumps(rewritten, ensure_ascii=False), encoding="utf-8"
        )

        updates = [
            ("cycling" if decision == "cycling" else "Run", run_id)
            for run_id, decision in decisions.items()
            if decision != "unsure"
        ]
        connection.executemany(
            "UPDATE activities SET type = ? WHERE run_id = ?", updates
        )
        connection.commit()
        os.replace(temporary_json, activities_json)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    counts = {
        decision: sum(value == decision for value in decisions.values())
        for decision in ALLOWED_DECISIONS
    }
    return ReviewSummary(
        total=len(decisions),
        cycling=counts["cycling"],
        keep_running=counts["keep_running"],
        unsure=counts["unsure"],
        json_before=len(activities),
        json_after=len(rewritten),
        backup_dir=backup_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_file", type=Path)
    parser.add_argument("--database", type=Path, default=Path("run_page/data.db"))
    parser.add_argument(
        "--activities-json",
        type=Path,
        default=Path("src/static/activities.json"),
    )
    parser.add_argument("--backup-root", type=Path, default=Path("reports/backups"))
    parser.add_argument(
        "--running-only-output",
        action="store_true",
        help="Keep cycling records in SQLite but omit them from activities JSON.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = apply_review(
        args.database,
        args.activities_json,
        args.review_file,
        running_only_output=args.running_only_output,
        backup_root=args.backup_root,
    )
    print(
        f"Applied {summary.total} decisions: cycling={summary.cycling}, "
        f"keep_running={summary.keep_running}, unsure={summary.unsure}"
    )
    print(
        f"Activities JSON: {summary.json_before} -> {summary.json_after}; "
        f"backup: {summary.backup_dir}"
    )


if __name__ == "__main__":
    main()
