import json
import sqlite3

import pytest

from run_page.apply_activity_review import apply_review, load_review


def make_data(tmp_path):
    database = tmp_path / "data.db"
    activities_json = tmp_path / "activities.json"
    review_file = tmp_path / "review.json"

    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE activities (run_id INTEGER PRIMARY KEY, type TEXT)"
    )
    connection.executemany(
        "INSERT INTO activities VALUES (?, ?)",
        [(1, "Run"), (2, "Run"), (3, "Run")],
    )
    connection.commit()
    connection.close()
    activities_json.write_text(
        json.dumps(
            [
                {"run_id": 1, "type": "Run"},
                {"run_id": 2, "type": "Run"},
                {"run_id": 3, "type": "Run"},
            ]
        ),
        encoding="utf-8",
    )
    review_file.write_text(
        json.dumps(
            {
                "decisions": {
                    "1": "cycling",
                    "2": "keep_running",
                    "3": "unsure",
                }
            }
        ),
        encoding="utf-8",
    )
    return database, activities_json, review_file


def test_applies_types_and_omits_cycling_from_running_output(tmp_path):
    database, activities_json, review_file = make_data(tmp_path)

    summary = apply_review(
        database,
        activities_json,
        review_file,
        running_only_output=True,
        backup_root=tmp_path / "backups",
    )

    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT run_id, type FROM activities ORDER BY run_id"
    ).fetchall() == [(1, "cycling"), (2, "Run"), (3, "Run")]
    connection.close()
    assert json.loads(activities_json.read_text(encoding="utf-8")) == [
        {"run_id": 2, "type": "Run"},
        {"run_id": 3, "type": "Run"},
    ]
    assert summary.cycling == 1
    assert summary.keep_running == 1
    assert summary.unsure == 1
    assert summary.json_before == 3
    assert summary.json_after == 2
    assert (summary.backup_dir / "data.db").exists()
    assert (summary.backup_dir / "activities.json").exists()
    assert (summary.backup_dir / "review.json").exists()


def test_rejects_review_missing_from_current_data_before_writing(tmp_path):
    database, activities_json, review_file = make_data(tmp_path)
    original_database = database.read_bytes()
    original_json = activities_json.read_bytes()
    review_file.write_text(
        json.dumps({"decisions": {"99": "cycling"}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="missing from current data"):
        apply_review(
            database,
            activities_json,
            review_file,
            running_only_output=True,
            backup_root=tmp_path / "backups",
        )

    assert database.read_bytes() == original_database
    assert activities_json.read_bytes() == original_json


def test_running_only_review_can_be_reapplied(tmp_path):
    database, activities_json, review_file = make_data(tmp_path)
    backup_root = tmp_path / "backups"
    apply_review(
        database,
        activities_json,
        review_file,
        running_only_output=True,
        backup_root=backup_root,
    )

    summary = apply_review(
        database,
        activities_json,
        review_file,
        running_only_output=True,
        backup_root=backup_root,
    )

    assert summary.json_before == 2
    assert summary.json_after == 2
    assert len(list(backup_root.iterdir())) == 2


def test_rejects_unknown_decision(tmp_path):
    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps({"decisions": {"1": "delete"}}), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid review decision"):
        load_review(review_file)
