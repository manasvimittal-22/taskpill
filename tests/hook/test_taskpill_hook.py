import ast
import io
import json
import os
import subprocess
import sys
import time

import pytest

from taskpill.adapters.event_server import EventServer
from taskpill.adapters.runtime_file import RuntimeInfo, write_runtime
from tests.helpers import REPO_ROOT, load_hook_helper

hook = load_hook_helper()
HOOK_FILE = REPO_ROOT / "hook" / "taskpill_hook.py"
TOKEN = "hook-test-token-0123456789"  # publish-scan: ok (a fake test token)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKPILL_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def app(isolated_config):
    """A real event server with runtime.json written, like the running app."""
    received = []
    server = EventServer(sink=received.append, token=TOKEN)
    port = server.start()
    write_runtime(isolated_config / "runtime.json", RuntimeInfo(port, TOKEN, os.getpid(), "t"))
    yield received
    server.stop()


def run(payload, argv=()):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return hook.main(list(argv), io.BytesIO(data))


# ---- the hard rules -----------------------------------------------------------------
def test_uses_only_the_standard_library():
    tree = ast.parse(HOOK_FILE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    names.discard("__future__")
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


@pytest.mark.parametrize(
    "stdin",
    [b"", b"not json", b"[]", b'{"session_id": 5}', b"x" * (2 * 1024 * 1024), b"\xff\xfe"],
)
def test_always_exits_zero_and_prints_nothing(capsys, stdin):
    assert run(stdin) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_exits_zero_when_the_app_is_not_running(capsys):
    assert run({"session_id": "a", "hook_event_name": "Stop"}) == 0
    assert capsys.readouterr().out == ""


def test_script_run_for_real_prints_nothing(isolated_config):
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK_FILE), "--taskpill-hook"],
        input=json.dumps({"session_id": "a", "hook_event_name": "Stop"}).encode(),
        capture_output=True,
        timeout=20,
        env={**os.environ, "TASKPILL_CONFIG_DIR": str(isolated_config)},
    )
    assert result.returncode == 0
    assert result.stdout == b""


# ---- delivery ---------------------------------------------------------------------
def test_delivers_events_to_the_app(app, capsys):
    run({"session_id": "a", "hook_event_name": "UserPromptSubmit", "prompt": "fix it"})
    assert len(app) == 1
    assert app[0].prompt == "fix it"
    assert capsys.readouterr().out == ""


def test_adds_pid_chain_on_session_start(app):
    run({"session_id": "a", "hook_event_name": "SessionStart"})
    chain = app[0].pid_chain
    assert chain and chain[0] == os.getppid()


def test_every_event_carries_the_pid_chain(app):
    """Bug (Manasvi, 2026-11-17): after the app restarted mid-session, the session
    came back from tool events alone, with no chain, so a click focused nothing."""
    run({"session_id": "a", "hook_event_name": "PreToolUse", "tool_name": "Bash"})
    run({"session_id": "a", "hook_event_name": "PermissionRequest", "tool_name": "Bash"})
    assert all(e.pid_chain and e.pid_chain[0] == os.getppid() for e in app)


def test_wrong_token_is_not_delivered(isolated_config, app):
    info = json.loads((isolated_config / "runtime.json").read_text(encoding="utf-8"))
    info["token"] = "nope-nope-nope-nope"
    (isolated_config / "runtime.json").write_text(json.dumps(info), encoding="utf-8")
    assert run({"session_id": "a", "hook_event_name": "Stop"}) == 0
    assert app == []


# ---- what leaves the machine's Claude Code process --------------------------------------
def test_slim_drops_big_and_private_fields():
    payload = {
        "session_id": "a",
        "hook_event_name": "PostToolUse",
        "transcript_path": "/secret/transcript.jsonl",
        "tool_name": "Write",
        "tool_input": {"file_path": "a.py", "content": "print('lots of code')" * 1000},
        "tool_response": {"output": "huge"},
    }
    out = hook.slim(payload)
    assert out == {
        "session_id": "a",
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "a.py"},
    }


def test_slim_cuts_long_commands():
    out = hook.slim(
        {
            "session_id": "a",
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": "x" * 5000},
        }
    )
    assert len(out["tool_input"]["command"]) == hook.MAX_COMMAND


def test_slim_keeps_the_failure_reason_for_stop_failure_only():
    failure = {
        "session_id": "a",
        "hook_event_name": "StopFailure",
        "error": "rate_limit",
        "error_details": "429 Too Many Requests",
        "last_assistant_message": "API Error: Rate limit reached" + "!" * 1000,
        "transcript_path": "/secret/transcript.jsonl",
    }
    out = hook.slim(failure)
    assert out["error"] == "rate_limit" and out["error_details"] == "429 Too Many Requests"
    assert out["last_assistant_message"].startswith("API Error: Rate limit reached")
    assert len(out["last_assistant_message"]) == hook.MAX_FAILURE_TEXT
    assert "transcript_path" not in out
    # On Stop, last_assistant_message is Claude's reply: it never leaves.
    stop = hook.slim({**failure, "hook_event_name": "Stop",
                      "last_assistant_message": "Here is the secret plan…"})
    assert not set(hook.FAILURE_FIELDS) & set(stop)


@pytest.mark.parametrize("payload", [None, [], {"session_id": "a"}, {"hook_event_name": "Stop"}])
def test_slim_rejects_unusable_payloads(payload):
    assert hook.slim(payload) is None


# ---- launching the app ------------------------------------------------------------------
def test_parse_args():
    argv = ["--app", "TaskPill.exe", "--app-arg", "-m", "--app-arg", "x", "--taskpill-hook"]
    args = hook.parse_args(argv)
    assert args == {"app": "TaskPill.exe", "app_args": ["-m", "x"]}
    assert hook.parse_args(["--app"]) == {"app": None, "app_args": []}


def test_launches_the_app_only_for_session_start_and_prompts(monkeypatch):
    launched = []
    monkeypatch.setattr(hook, "launch", lambda app, args: launched.append(app) or False)
    for event in ["PreToolUse", "Stop", "Notification", "SessionEnd"]:
        run({"session_id": "a", "hook_event_name": event}, ["--app", "TaskPill.exe"])
    assert launched == []
    run({"session_id": "a", "hook_event_name": "UserPromptSubmit"}, ["--app", "TaskPill.exe"])
    assert launched == ["TaskPill.exe"]


def test_no_launch_without_app_argument(monkeypatch):
    launched = []
    monkeypatch.setattr(hook, "launch", lambda app, args: launched.append(app) or False)
    run({"session_id": "a", "hook_event_name": "SessionStart"})
    assert launched == []


def test_launch_cooldown_prevents_a_storm(monkeypatch, isolated_config):
    started = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert hook.launch("TaskPill.exe", [])
    assert hook.launch("TaskPill.exe", [])  # within the cooldown: no second start
    assert len(started) == 1
    stamp = isolated_config / "launch.stamp"
    old = time.time() - hook.LAUNCH_COOLDOWN - 1
    os.utime(stamp, (old, old))
    hook.launch("TaskPill.exe", [])
    assert len(started) == 2


def test_hook_launch_is_marked_background(monkeypatch, isolated_config):
    started = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    hook.launch("TaskPill.exe", ["-m", "x"])
    assert started[0][-1] == "--background"


def test_errors_are_logged_not_raised(monkeypatch, isolated_config):
    def boom(_payload):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(hook, "send", boom)
    assert run({"session_id": "a", "hook_event_name": "Stop"}) == 0
    log = (isolated_config / "hook.log").read_text(encoding="utf-8")
    assert "kaboom" in log


def test_pid_chain_is_a_list_of_parents():
    chain = hook.pid_chain()
    assert isinstance(chain, list)
    assert chain and chain[0] == os.getppid()
    assert len(chain) == len(set(chain))
