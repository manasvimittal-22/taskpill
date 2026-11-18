"""Turn a tool call into a short, human step text, e.g. "Editing app.py"."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

MAX_STEP = 60

_FILE_VERBS = {
    "Edit": "Editing",
    "MultiEdit": "Editing",
    "Write": "Writing",
    "Read": "Reading",
    "NotebookEdit": "Editing",
}

_FIXED = {
    "Grep": "Searching code",
    "Glob": "Finding files",
    "WebSearch": "Searching the web",
    "Task": "Running a subagent",
    "Agent": "Running a subagent",
    "TodoWrite": "Updating the to-do list",
}


def describe_step(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    if not tool_name:
        return "Working"

    if tool_name in _FILE_VERBS:
        name = _basename(_first_str(tool_input, "file_path", "notebook_path", "path"))
        verb = _FILE_VERBS[tool_name]
        return _fit(f"{verb} {name}" if name else verb)

    if tool_name in ("Bash", "PowerShell"):
        command = _first_str(tool_input, "command")
        first_line = command.splitlines()[0].strip() if command else ""
        return _fit(f"Running {first_line}" if first_line else "Running a command")

    if tool_name == "WebFetch":
        host = urlparse(_first_str(tool_input, "url")).hostname or ""
        return _fit(f"Reading {host}" if host else "Reading a web page")

    if tool_name in _FIXED:
        return _FIXED[tool_name]

    match = re.fullmatch(r"mcp__([^_]+(?:_[^_]+)*?)__.+", tool_name)
    if match:
        return _fit(f"Using {match.group(1)}")

    return _fit(f"Using {tool_name}")


_PERMISSION_VERBS = {
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
    "Read": "read",
}

# Tools that put a question in front of the user.
ASKING_TOOLS = {
    "AskUserQuestion": "Has a question for you",
    "ExitPlanMode": "Plan ready for your review",
}


def describe_permission(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    """E.g. "Needs permission to run npm install"."""
    if tool_name in _PERMISSION_VERBS:
        name = _basename(_first_str(tool_input, "file_path", "notebook_path", "path"))
        action = f"{_PERMISSION_VERBS[tool_name]} {name}".strip()
    elif tool_name in ("Bash", "PowerShell"):
        command = _first_str(tool_input, "command")
        first_line = command.splitlines()[0].strip() if command else ""
        action = f"run {first_line}" if first_line else "run a command"
    elif tool_name == "WebFetch":
        host = urlparse(_first_str(tool_input, "url")).hostname or ""
        action = f"open {host}" if host else "open a web page"
    elif tool_name:
        match = re.fullmatch(r"mcp__([^_]+(?:_[^_]+)*?)__.+", tool_name)
        action = f"use {match.group(1) if match else tool_name}"
    else:
        return "Needs your permission"
    return _fit(f"Needs permission to {action}", limit=90)


def _first_str(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] if path else ""


def _fit(text: str, limit: int = MAX_STEP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
