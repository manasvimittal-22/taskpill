import json

from taskpill.adapters.duration_store import DurationStore


def test_missing_file_is_empty(tmp_path):
    assert DurationStore(tmp_path / "history.json").load() == []


def test_round_trip_and_numbers_only(tmp_path):
    path = tmp_path / "sub" / "history.json"
    store = DurationStore(path)
    store.save([12.5, 40.0])
    assert store.load() == [12.5, 40.0]
    assert set(json.loads(path.read_text())) == {"durations"}


def test_broken_files_load_as_empty(tmp_path):
    path = tmp_path / "history.json"
    for text in ("{not json", "[1, 2]", '{"durations": "x"}', ""):
        path.write_text(text)
        assert DurationStore(path).load() == []


def test_bad_values_are_dropped_one_by_one(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"durations": [10, "x", null, true, 20.5, NaN]}')
    assert DurationStore(path).load() == [10.0, 20.5]
