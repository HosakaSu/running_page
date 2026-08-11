"""
If you do not want bind any account
Only the gpx files in GPX_OUT sync
"""

import argparse

from config import GPX_FOLDER, JSON_FILE, SQL_FILE

from utils import make_activities_file


def build_parser():
    parser = argparse.ArgumentParser(description="Generate running data from GPX files.")
    parser.add_argument("--gpx-dir", default=GPX_FOLDER)
    parser.add_argument("--sql-file", default=SQL_FILE)
    parser.add_argument("--json-file", default=JSON_FILE)
    parser.add_argument(
        "--ignore-synced",
        action="store_true",
        help="Process every GPX without reading or updating imported.json.",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    print(f"sync gpx files from {args.gpx_dir}")
    make_activities_file(
        args.sql_file,
        args.gpx_dir,
        args.json_file,
        ignore_synced=args.ignore_synced,
    )
