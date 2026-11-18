from pathlib import Path

from taskpill.adapters.hook_command import resolve_hook_command

REPO = Path("C:/code/taskpill")


def test_installed_app_on_windows():
    cmd = resolve_hook_command(frozen=True, executable="C:/Program Files/TaskPill/TaskPill.exe",
                               platform="win32", repo_root=REPO)
    assert Path(cmd.command) == Path("C:/Program Files/TaskPill/taskpill-hook.exe")
    assert cmd.args[0] == "--app"
    assert Path(cmd.args[1]) == Path("C:/Program Files/TaskPill/TaskPill.exe")


def test_installed_app_on_macos_points_at_the_bundle():
    cmd = resolve_hook_command(
        frozen=True, executable="/Applications/TaskPill.app/Contents/MacOS/TaskPill",
        platform="darwin", repo_root=REPO,
    )
    assert Path(cmd.command) == Path("/Applications/TaskPill.app/Contents/MacOS/taskpill-hook")
    assert Path(cmd.args[1]) == Path("/Applications/TaskPill.app")


def test_from_source_on_windows_runs_the_script_and_starts_the_app_windowless():
    cmd = resolve_hook_command(frozen=False, executable="C:/code/taskpill/.venv/Scripts/python.exe",
                               platform="win32", repo_root=REPO)
    # windowless, so no console can flash on each hook event (it reads fd 0 itself)
    assert Path(cmd.command).name == "pythonw.exe"
    args = list(cmd.args)
    assert args[0] == "-I"
    assert Path(args[1]) == REPO / "hook" / "taskpill_hook.py"
    assert Path(args[args.index("--app") + 1]).name == "pythonw.exe"
    assert args[-4:] == ["--app-arg", "-m", "--app-arg", "taskpill.main"]


def test_from_source_when_running_under_pythonw_hooks_with_pythonw_too():
    cmd = resolve_hook_command(frozen=False, executable="C:/v/Scripts/pythonw.exe",
                               platform="win32", repo_root=REPO)
    assert Path(cmd.command).name == "pythonw.exe"
