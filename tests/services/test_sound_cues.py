"""Sounds (Manasvi, 2026-11-17): a subtle chime when a session needs you or is done,
each can be turned off in Settings."""

import wave

from taskpill.adapters.sound import SOUND_DIR, SilentPlayer, WinSoundPlayer
from taskpill.services.sound_cues import MIN_GAP, Cue, SoundCues
from tests.conftest import FakeClock


class Recorder:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


def test_each_cue_plays_its_sound():
    rec = Recorder()
    clock = FakeClock()
    cues = SoundCues(rec, clock)
    assert cues.cue(Cue.NEEDS_YOU)
    clock.t += MIN_GAP
    assert cues.cue(Cue.DONE)
    assert rec.played == ["needs_you", "done"]


def test_each_cue_can_be_turned_off():
    rec = Recorder()
    clock = FakeClock()
    cues = SoundCues(rec, clock)
    cues.set_enabled(needs_you=False, done=True)
    assert not cues.cue(Cue.NEEDS_YOU)
    assert cues.cue(Cue.DONE)
    clock.t += MIN_GAP
    cues.set_enabled(needs_you=True, done=False)
    assert not cues.cue(Cue.DONE)
    assert rec.played == ["done"]


def test_a_burst_plays_once():
    rec = Recorder()
    clock = FakeClock()
    cues = SoundCues(rec, clock)
    cues.cue(Cue.DONE)
    clock.t += 0.3
    cues.cue(Cue.DONE)  # a second session finished right after
    cues.cue(Cue.NEEDS_YOU)
    assert rec.played == ["done"]
    clock.t += MIN_GAP
    assert cues.cue(Cue.NEEDS_YOU)


def test_the_sound_files_exist_and_are_short_and_quiet():
    for name in ("needs_you", "done"):
        with wave.open(str(SOUND_DIR / f"{name}.wav")) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2
            seconds = w.getnframes() / w.getframerate()
            assert 0.2 < seconds < 1.0
            frames = w.readframes(w.getnframes())
        loudest = max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True))
                      for i in range(0, len(frames), 2))
        assert loudest < 0.3 * 32767  # subtle: well below full scale


def test_players_never_raise(tmp_path):
    SilentPlayer().play("done")
    WinSoundPlayer(tmp_path).play("missing")  # no file: quietly nothing
