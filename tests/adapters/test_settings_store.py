import json

import pytest

from taskpill.adapters.settings_store import Settings, SettingsStore


def test_missing_file_gives_defaults(tmp_path):
    assert SettingsStore(tmp_path / "settings.json").load() == Settings()


def test_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "sub" / "settings.json")
    s = Settings(glow=False, accent="rose", auto_quit_minutes=30, connect_asked=True,
                 positions={"1536x960@1.25": [1200, 930]})
    store.save(s)
    assert store.load() == s


@pytest.mark.parametrize("content", ["", "not json", "[]", "42"])
def test_broken_file_gives_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def test_one_bad_value_only_resets_itself(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "glow": "yes",  # not a bool
        "dot": False,  # fine
        "accent": "neon",  # unknown
        "auto_quit_minutes": 7,  # not a choice
        "positions": {"a": [1, 2], "b": [1], "c": "x", "d": [True, 2]},
        "unknown_key": 1,
    }), encoding="utf-8")
    s = SettingsStore(path).load()
    assert s.glow is True
    assert s.dot is False
    assert s.accent == "violet"
    assert s.auto_quit_minutes == 10
    assert s.positions == {"a": [1, 2]}


def test_never_quit_is_allowed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"auto_quit_minutes": 0}', encoding="utf-8")
    assert SettingsStore(path).load().auto_quit_minutes == 0



def test_width_zero_means_the_systems_default(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    assert Settings().pill_width == 0
    store.save(Settings(pill_width=0))
    assert store.load().pill_width == 0
    store.save(Settings(pill_width=232))  # files from before keep their number
    assert store.load().pill_width == 232
