"""
If you do not want bind any account
Only the gpx files in GPX_OUT sync
"""

import argparse
import sqlite3
from pathlib import Path

from apply_activity_review import apply_review
from config import GPX_FOLDER, JSON_FILE, SQL_FILE

from utils import make_activities_file

DEFAULT_ACTIVITY_REVIEW_FILE = (
    Path(__file__).resolve().parents[1] / "activity_type_overrides.json"
)


def has_gpx_files(gpx_directory: Path) -> bool:
    directory = Path(gpx_directory)
    return directory.is_dir() and any(
        path.is_file() and path.suffix.lower() == ".gpx"
        for path in directory.rglob("*")
    )


def database_has_activities(database: Path) -> bool:
    database = Path(database)
    if not database.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            return (
                connection.execute("SELECT 1 FROM activities LIMIT 1").fetchone()
                is not None
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate running data from GPX files."
    )
    parser.add_argument("--gpx-dir", default=GPX_FOLDER)
    parser.add_argument("--sql-file", default=SQL_FILE)
    parser.add_argument("--json-file", default=JSON_FILE)
    parser.add_argument(
        "--ignore-synced",
        action="store_true",
        help="Process every GPX without reading or updating imported.json.",
    )
    parser.add_argument(
        "--activity-review-file",
        type=Path,
        default=(
            DEFAULT_ACTIVITY_REVIEW_FILE
            if DEFAULT_ACTIVITY_REVIEW_FILE.exists()
            else None
        ),
        help="Reapply reviewed cycling/running types after importing GPX files.",
    )
    parser.add_argument(
        "--include-reviewed-cycling",
        action="store_true",
        help="Include reviewed cycling in webpage JSON (default: running only).",
    )
    parser.add_argument(
        "--skip-activity-review",
        action="store_true",
        help="Do not apply the repository's activity type overrides.",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    print(f"sync gpx files from {args.gpx_dir}")
    if not has_gpx_files(Path(args.gpx_dir)) and not database_has_activities(
        Path(args.sql_file)
    ):
        print("No GPX files or existing activities database; nothing to sync.")
        raise SystemExit(0)

    make_activities_file(
        args.sql_file,
        args.gpx_dir,
        args.json_file,
        ignore_synced=args.ignore_synced,
    )
    if args.activity_review_file and not args.skip_activity_review:
        summary = apply_review(
            Path(args.sql_file),
            Path(args.json_file),
            args.activity_review_file,
            running_only_output=not args.include_reviewed_cycling,
            backup_root=Path("reports/backups"),
        )
        print(
            f"applied activity review: cycling={summary.cycling}, "
            f"keep_running={summary.keep_running}, unsure={summary.unsure}"
        )
