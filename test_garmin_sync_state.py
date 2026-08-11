import json

import pytest

from run_page.garmin_sync_state import load_activity_ids, save_activity_ids


def test_missing_state_is_empty(tmp_path):
    assert load_activity_ids(tmp_path / "missing.json") == set()


def test_state_is_sorted_and_only_rewritten_when_changed(tmp_path):
    state = tmp_path / "state.json"

    assert save_activity_ids(state, {"20", "3"}) is True
    assert json.loads(state.read_text(encoding="utf-8")) == ["3", "20"]
    original = state.read_bytes()

    assert save_activity_ids(state, {"3", "20"}) is False
    assert state.read_bytes() == original
    assert load_activity_ids(state) == {"3", "20"}


@pytest.mark.parametrize("payload", [{"activity_ids": []}, ["0"], ["abc"]])
def test_invalid_state_is_rejected(tmp_path, payload):
    state = tmp_path / "state.json"
    state.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Garmin sync state"):
        load_activity_ids(state)
