import subprocess
import sys
from pathlib import Path


def test_empty_sync_does_not_overwrite_existing_json(tmp_path):
    repository = Path(__file__).resolve().parent
    gpx_directory = tmp_path / "GPX_OUT"
    gpx_directory.mkdir()
    database = tmp_path / "data.db"
    activities_json = tmp_path / "activities.json"
    original = '[{"sentinel": true}]'
    activities_json.write_text(original, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repository / "run_page" / "gpx_sync.py"),
            "--gpx-dir",
            str(gpx_directory),
            "--sql-file",
            str(database),
            "--json-file",
            str(activities_json),
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "nothing to sync" in result.stdout
    assert activities_json.read_text(encoding="utf-8") == original
    assert not database.exists()
