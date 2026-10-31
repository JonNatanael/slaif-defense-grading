#!/usr/bin/env python3
"""Authoritative structural validation contract for ``report.json``.

This module is the single source of truth for validating pseudonymized
submission-assessment reports. The local ``finalize`` command imports it,
and ``prepare`` copies this file verbatim into every generated
pseudonymized workspace as ``report_validator.py`` so that ``process.sh``
can validate reports as a standalone helper without the source repository
being importable at runtime.

It must therefore stay self-contained:

- standard library only;
- no repository imports;
- no access to rosters, private maps, or any real student data.

A report is only "complete" when its content passes this structural check;
the mere existence of a ``report.json`` file is not sufficient.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Version of the report schema described by templates/workspace/report_template.json.
REPORT_SCHEMA_VERSION = 1

# Exact top-level keys from templates/workspace/report_template.json. All of them
# are required; additional keys are tolerated for forward compatibility with
# reports produced by existing workspaces.
REQUIRED_REPORT_KEYS = (
    "pseudonym",
    "assignment_submitted",
    "all_tasks_implemented",
    "task_details",
    "looks_llm_generated",
    "llm_generation_indicators",
    "code_copy_indications",
    "notes",
)

# Documented scalar values.
ALLOWED_ALL_TASKS_VALUES = (True, False, "unknown")
ALLOWED_LLM_ASSESSMENTS = ("likely", "unlikely", "uncertain")

# Required (key, type) pairs for every task_details entry.
TASK_DETAIL_REQUIRED_FIELDS = (
    ("task", str),
    ("implemented", bool),
    ("evidence", str),
)

# Required (key, type) pairs for every code_copy_indications entry.
CODE_COPY_REQUIRED_FIELDS = (
    ("other_student_pseudonym", str),
    ("this_file", str),
    ("this_lines", str),
    ("other_file", str),
    ("other_lines", str),
    ("evidence", str),
)


def _required_entry_problems(
    entries: List[Any],
    required_fields: Sequence[Tuple[str, type]],
    entry_label: str,
) -> List[str]:
    problems: List[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"{entry_label} {index} must be an object")
            continue
        missing = [key for key, _ in required_fields if key not in entry]
        if missing:
            problems.append(f"{entry_label} {index} is missing required field(s): {', '.join(missing)}")
        for key, kind in required_fields:
            if key in entry and not isinstance(entry[key], kind):
                kind_name = "a string" if kind is str else "a boolean"
                problems.append(f"{entry_label} {index} field '{key}' must be {kind_name}")
    return problems


def validate_report_data(data: Any, expected_pseudonym: str) -> List[str]:
    """Structurally validate decoded report data against the shared contract.

    Returns a list of human-readable problems; an empty list means valid.
    """
    if not isinstance(data, dict):
        return ["must contain a JSON object"]

    problems: List[str] = []

    missing = [key for key in REQUIRED_REPORT_KEYS if key not in data]
    if missing:
        problems.append(f"is missing required key(s): {', '.join(missing)}")

    if "pseudonym" in data:
        pseudonym = data.get("pseudonym")
        if not (isinstance(pseudonym, str) and pseudonym == expected_pseudonym):
            problems.append(f"field 'pseudonym' must equal the expected target {expected_pseudonym!r}")

    if "assignment_submitted" in data and not isinstance(data.get("assignment_submitted"), bool):
        problems.append("field 'assignment_submitted' must be a boolean")

    if "all_tasks_implemented" in data and data.get("all_tasks_implemented") not in ALLOWED_ALL_TASKS_VALUES:
        problems.append("field 'all_tasks_implemented' must be true, false or 'unknown'")

    if "task_details" in data:
        task_details = data.get("task_details")
        if not isinstance(task_details, list):
            problems.append("field 'task_details' must be a list")
        else:
            problems.extend(_required_entry_problems(task_details, TASK_DETAIL_REQUIRED_FIELDS, "task_details entry"))

    if "looks_llm_generated" in data and data.get("looks_llm_generated") not in ALLOWED_LLM_ASSESSMENTS:
        problems.append("field 'looks_llm_generated' must be 'likely', 'unlikely' or 'uncertain'")

    if "llm_generation_indicators" in data:
        indicators = data.get("llm_generation_indicators")
        if not isinstance(indicators, list) or not all(isinstance(item, str) for item in indicators):
            problems.append("field 'llm_generation_indicators' must be a list of strings")

    if "code_copy_indications" in data:
        copies = data.get("code_copy_indications")
        if not isinstance(copies, list):
            problems.append("field 'code_copy_indications' must be a list")
        else:
            problems.extend(_required_entry_problems(copies, CODE_COPY_REQUIRED_FIELDS, "code_copy_indications entry"))

    if "notes" in data and not isinstance(data.get("notes"), str):
        problems.append("field 'notes' must be a string")

    return problems


def validate_report_text(text: str, expected_pseudonym: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Parse and structurally validate raw report text.

    Returns ``(data, problems)``; ``data`` is ``None`` when the text is not
    valid JSON or not a JSON object.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"is not valid JSON: {exc}"]
    problems = validate_report_data(data, expected_pseudonym)
    return (data if isinstance(data, dict) else None), problems


def validate_report_file(path: Path, expected_pseudonym: str) -> List[str]:
    """Validate a report file on disk; returns problems (empty means valid)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not be read: {exc}"]
    return validate_report_text(text, expected_pseudonym)[1]


def build_unresolved_report(pseudonym: str) -> Dict[str, Any]:
    """Deterministic neutral report for a student with no associated submission.

    This records a local workflow fact only; it is not an automatic grading
    decision and does not imply any misconduct.
    """
    return {
        "pseudonym": pseudonym,
        "assignment_submitted": False,
        "all_tasks_implemented": "unknown",
        "task_details": [],
        "looks_llm_generated": "uncertain",
        "llm_generation_indicators": [],
        "code_copy_indications": [],
        "notes": (
            "No submission material was associated with this pseudonymized student, "
            "so no implementation or authorship indicators could be assessed."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone CLI used by generated ``process.sh``.

    Usage: ``report_validator.py <expected-pseudonym> <report.json>``.
    Exits 0 when the report is valid, 1 when it is not, 2 on usage errors.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: report_validator.py <expected-pseudonym> <report.json>", file=sys.stderr)
        return 2
    problems = validate_report_file(Path(args[1]), args[0])
    for problem in problems:
        print(f"invalid report: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
