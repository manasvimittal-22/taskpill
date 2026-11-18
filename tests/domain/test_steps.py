import pytest

from taskpill.domain.steps import MAX_STEP, describe_permission, describe_step


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Edit", {"file_path": "C:\\code\\taskpill\\app.py"}, "Editing app.py"),
        ("MultiEdit", {"file_path": "/home/m/src/x.ts"}, "Editing x.ts"),
        ("Write", {"file_path": "README.md"}, "Writing README.md"),
        ("Read", {"file_path": "/a/b/notes.txt"}, "Reading notes.txt"),
        ("Edit", {}, "Editing"),
        ("Bash", {"command": "npm install\nnpm test"}, "Running npm install"),
        ("Bash", {}, "Running a command"),
        ("PowerShell", {"command": "Get-ChildItem"}, "Running Get-ChildItem"),
        ("WebFetch", {"url": "https://docs.python.org/3/"}, "Reading docs.python.org"),
        ("WebFetch", {"url": "not a url"}, "Reading a web page"),
        ("Grep", {"pattern": "x"}, "Searching code"),
        ("Glob", {}, "Finding files"),
        ("WebSearch", {}, "Searching the web"),
        ("Task", {}, "Running a subagent"),
        ("TodoWrite", {}, "Updating the to-do list"),
        ("mcp__github__create_issue", {}, "Using github"),
        ("mcp__claude_ai_Claude_Docs__batch", {}, "Using claude_ai_Claude_Docs"),
        ("SomeNewTool", {}, "Using SomeNewTool"),
        ("", {}, "Working"),
    ],
)
def test_describes_tools(tool, tool_input, expected):
    assert describe_step(tool, tool_input) == expected


def test_long_steps_are_cut():
    step = describe_step("Bash", {"command": "echo " + "a" * 500})
    assert len(step) == MAX_STEP
    assert step.endswith("…")


def test_whitespace_is_collapsed():
    assert describe_step("Bash", {"command": "git   status\t  -s"}) == "Running git status -s"


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Bash", {"command": "npm install\nnpm test"}, "Needs permission to run npm install"),
        ("Bash", {}, "Needs permission to run a command"),
        ("Edit", {"file_path": "C:\\x\\app.py"}, "Needs permission to edit app.py"),
        ("Write", {}, "Needs permission to write"),
        ("WebFetch", {"url": "https://example.com/a"}, "Needs permission to open example.com"),
        ("mcp__github__create_issue", {}, "Needs permission to use github"),
        ("Grep", {}, "Needs permission to use Grep"),
        ("", {}, "Needs your permission"),
    ],
)
def test_describes_permissions(tool, tool_input, expected):
    assert describe_permission(tool, tool_input) == expected
