#!/usr/bin/env python3
"""Authoritative structural validation contract for ``task_requirements.json``.

This file is generated once by the assignment-analysis agent command
("Analyze assignment requirements") and reused by every student assessment
agent, so that no student agent repeatedly parses and reinterprets the
canonical assignment.

Like ``report_validation.py``, this module is the single source of truth for
its contract: ``prepare`` copies it verbatim into every generated
pseudonymized workspace as ``task_requirements_validator.py`` so the generated
``process.sh`` can validate the file standalone, without the source repository
being importable at runtime. It must therefore stay self-contained:

- standard library only;
- no repository imports;
- no access to rosters or any real student data.

A file is only "valid" when its content passes this structural check; mere
existence is not sufficient.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

TASK_REQUIREMENTS_SCHEMA_VERSION = 1

REQUIRED_FIELDS = ("id", "description", "source_reference")


def validate_task_requirements_data(data: Any) -> List[str]:
    """Structurally validate decoded task-requirements data.

    Returns a list of human-readable problems; an empty list means valid.
    """
    if not isinstance(data, dict):
        return ["must contain a JSON object"]

    problems: List[str] = []

    if "schema_version" not in data:
        problems.append("is missing required key(s): schema_version")
    elif data.get("schema_version") != TASK_REQUIREMENTS_SCHEMA_VERSION:
        problems.append(f"field 'schema_version' must be {TASK_REQUIREMENTS_SCHEMA_VERSION}")

    requirements = data.get("requirements")
    if "requirements" not in data:
        problems.append("is missing required key(s): requirements")
    elif not isinstance(requirements, list):
        problems.append("field 'requirements' must be a list")
    else:
        seen_ids: set = set()
        for index, entry in enumerate(requirements):
            if not isinstance(entry, dict):
                problems.append(f"requirements entry {index} must be an object")
                continue
            missing = [key for key in REQUIRED_FIELDS if key not in entry]
            if missing:
                problems.append(f"requirements entry {index} is missing required field(s): {', '.join(missing)}")
            for key in REQUIRED_FIELDS:
                value = entry.get(key)
                if key in entry and (not isinstance(value, str) or not value.strip()):
                    problems.append(f"requirements entry {index} field '{key}' must be a nonempty string")
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id.strip():
                if entry_id in seen_ids:
                    problems.append(f"requirements entry {index} has duplicate id {entry_id!r}")
                seen_ids.add(entry_id)

    notes = data.get("notes")
    if "notes" not in data:
        problems.append("is missing required key(s): notes")
    elif not isinstance(notes, str):
        problems.append("field 'notes' must be a string")

    # An empty requirements list is only acceptable when the analysis agent
    # explicitly explains why no requirements could be identified.
    if (
        isinstance(requirements, list)
        and not requirements
        and (not isinstance(notes, str) or not notes.strip())
    ):
        problems.append(
            "'requirements' is empty; 'notes' must explain why no assignment requirements could be identified"
        )

    return problems


def validate_task_requirements_text(text: str) -> Tuple[Optional[dict], List[str]]:
    """Parse and validate raw text; returns (data, problems)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"is not valid JSON: {exc}"]
    problems = validate_task_requirements_data(data)
    return (data if isinstance(data, dict) else None), problems


def validate_task_requirements_file(path: Path) -> List[str]:
    """Validate a file on disk; returns problems (empty means valid)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not be read: {exc}"]
    return validate_task_requirements_text(text)[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone CLI used by generated ``process.sh``.

    Usage: ``task_requirements_validator.py <task_requirements.json>``.
    Exits 0 when the file is valid, 1 when it is not, 2 on usage errors.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: task_requirements_validator.py <task_requirements.json>", file=sys.stderr)
        return 2
    problems = validate_task_requirements_file(Path(args[0]))
    for problem in problems:
        print(f"invalid task requirements: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
