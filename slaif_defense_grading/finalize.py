from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .pdf_report import FINAL_REPORT_CSV_COLUMNS, render_assessment_pdf, render_final_report_pdf
from .html_report import FINAL_REPORT_HTML, render_final_report_html


@dataclass(frozen=True)
class FinalizeStudent:
    row: Dict[str, str]
    pseudonym: str
    name: str
    surname: str
    full_name: str

    @property
    def safe_name(self) -> str:
        return safe_filename(self.full_name)

    @property
    def pseudonym_filename_stem(self) -> str:
        return self.pseudonym.replace(" ", "_")


@dataclass(frozen=True)
class FinalizeResult:
    roster_count: int
    found_reports: int
    missing_reports: int
    copied_student_outputs: int
    final_report_pdf: str
    final_report_html: str
    output: Path


FINAL_INDEX_BASE_COLUMNS = [
    "pseudonym",
    "name",
    "surname",
    "full_name",
]
FINAL_INDEX_TRAILING_COLUMNS = [
    "report_status",
    "report_pdf_file",
    "report_json_file",
    "student_output_file",
]
MISSING_REPORT_COLUMNS = [
    "pseudonym",
    "name",
    "surname",
    "full_name",
    "expected_report_path",
    "reason",
]
FINAL_REPORT_CSV = "final_report.csv"
FINAL_REPORT_PDF = "final_report.pdf"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/]+", "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^\w.-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned or "UNKNOWN"


def unique_safe_names(students: Sequence[FinalizeStudent]) -> Dict[str, str]:
    """Return deterministic safe path names, avoiding overwrite on duplicate names."""
    used: Dict[str, int] = {}
    result: Dict[str, str] = {}
    for student in students:
        base = student.safe_name
        count = used.get(base, 0) + 1
        used[base] = count
        if count == 1:
            result[student.pseudonym] = base
        else:
            result[student.pseudonym] = f"{base}__{student.pseudonym_filename_stem}"
    return result


def read_csv_rows(path: Path) -> tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV is missing a header row: {path}")
        fieldnames = [field.strip() for field in reader.fieldnames]
        rows = [{field: (row.get(field) or "").strip() for field in fieldnames} for row in reader]
    return fieldnames, rows


def read_pseudonym_map(path: Path) -> tuple[List[str], List[FinalizeStudent]]:
    fieldnames, rows = read_csv_rows(path)
    required = ["pseudonym", "name", "surname", "full_name"]
    missing = [field for field in required if field not in fieldnames]
    if missing:
        raise ValueError(f"pseudonym map is missing required column(s): {', '.join(missing)}")

    students = [
        FinalizeStudent(
            row=row,
            pseudonym=row["pseudonym"],
            name=row["name"],
            surname=row["surname"],
            full_name=row["full_name"],
        )
        for row in rows
    ]
    return fieldnames, students


def read_student_outputs_index(path: Path) -> Dict[str, str]:
    fieldnames, rows = read_csv_rows(path)
    required = ["pseudonym", "student_output_file"]
    missing = [field for field in required if field not in fieldnames]
    if missing:
        raise ValueError(f"student outputs index is missing required column(s): {', '.join(missing)}")
    return {row["pseudonym"]: row["student_output_file"] for row in rows if row.get("student_output_file")}


REQUIRED_REPORT_KEYS = (
    "assignment_submitted",
    "all_tasks_implemented",
    "looks_llm_generated",
    "code_copy_indications",
)
ALLOWED_LLM_ASSESSMENTS = {"likely", "unlikely", "uncertain"}


# The final overview is a quick glance rendered as a single table, so keep
# notes short. The full notes remain in each student's named report.pdf /
# report.json under the private output directory.
MAX_FINAL_NOTE_CHARS = 240


def _clip_notes(notes: str) -> str:
    if len(notes) <= MAX_FINAL_NOTE_CHARS:
        return notes
    return notes[: MAX_FINAL_NOTE_CHARS - 3].rstrip() + "..."


def write_named_report_json(source: Path, target: Path) -> None:
    """Copy the machine-readable report verbatim (pseudonyms stay; the private maps resolve them)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _summary_cells(report_data: Dict[str, object], other_student_names: Dict[str, str]) -> Dict[str, str]:
    """Reduce one validated report.json to the single-table final overview cells.

    Notes are clipped to MAX_FINAL_NOTE_CHARS so the single-table overview
    stays renderable; the untruncated notes stay in the named student report.
    """
    tasks = report_data.get("all_tasks_implemented")
    tasks_cell = "Yes" if tasks is True else ("No" if tasks is False else "Unknown")

    other_names: List[str] = []
    copies = report_data.get("code_copy_indications")
    if isinstance(copies, list):
        for copy in copies:
            if not isinstance(copy, dict):
                continue
            other_pseudonym = str(copy.get("other_student_pseudonym") or "").strip()
            if not other_pseudonym:
                continue
            label = other_student_names.get(other_pseudonym) or other_pseudonym
            if label not in other_names:
                other_names.append(label)
    copying_cell = f"Yes (with {', '.join(other_names)})" if other_names else "No"

    llm_cell = {
        "likely": "Likely",
        "unlikely": "Unlikely",
        "uncertain": "Uncertain",
    }.get(str(report_data.get("looks_llm_generated") or "").casefold(), "Unknown")

    return {
        "all_tasks_implemented": tasks_cell,
        "copying_indications": copying_cell,
        "llm_indications": llm_cell,
        "notes": _clip_notes(str(report_data.get("notes") or "").strip()),
    }


def load_assessment_report(path: Path) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """Load and validate an agent-generated report.json; returns (data, problem)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"report.json could not be read: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"report.json is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "report.json must contain a JSON object"
    missing = [key for key in REQUIRED_REPORT_KEYS if key not in data]
    if missing:
        return None, f"report.json is missing required field(s): {', '.join(missing)}"
    if not isinstance(data.get("assignment_submitted"), bool):
        return None, "report.json field 'assignment_submitted' must be a boolean"
    if data.get("all_tasks_implemented") not in (True, False, "unknown"):
        return None, "report.json field 'all_tasks_implemented' must be true, false or 'unknown'"
    if str(data.get("looks_llm_generated") or "").casefold() not in ALLOWED_LLM_ASSESSMENTS:
        return None, "report.json field 'looks_llm_generated' must be 'likely', 'unlikely' or 'uncertain'"
    if not isinstance(data.get("code_copy_indications"), list):
        return None, "report.json field 'code_copy_indications' must be a list"
    return data, None


def write_named_student_output(source: Path, target: Path, student: FinalizeStudent) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = source.read_text(encoding="utf-8", errors="replace")
    header = (
        "This is the pseudonymized concatenated submission text that the agent saw.\n"
        f"Student: {student.full_name}\n"
        f"Pseudonym: {student.pseudonym}\n\n"
    )
    target.write_text(header + content, encoding="utf-8", newline="\n")


def write_finalize_report(
    output: Path,
    roster_count: int,
    found_reports: int,
    missing_report_rows: Sequence[Dict[str, str]],
    copied_student_outputs: int,
    missing_student_outputs: Sequence[FinalizeStudent],
    pdf_warnings: Sequence[str] = (),
    html_warnings: Sequence[str] = (),
    final_report_pdf: str = "",
    final_report_html: str = "",
) -> None:
    lines = [
        "# Finalize Report",
        "",
        f"- Roster students: {roster_count}",
        f"- Found reports: {found_reports}",
        f"- Missing reports: {len(missing_report_rows)}",
        f"- Copied student-output text files: {copied_student_outputs}",
        (
            f"- Final report (single-table overview): `{final_report_pdf}` and `{FINAL_REPORT_CSV}`"
            if final_report_pdf
            else f"- Final report (single-table overview): PDF unavailable (see PDF Rendering Warnings); table written to `{FINAL_REPORT_CSV}`"
        ),
        (
            f"- Final report (local HTML viewer): `{final_report_html}`"
            if final_report_html
            else "- Final report (local HTML viewer): HTML unavailable (see HTML Rendering Warnings)"
        ),
        "- Instructor reports directory: `instructor_reports/`",
        "- Student outputs directory: `student_outputs/`",
        "",
        "## Privacy Notes",
        "",
        "- This final output is private/local and may contain real student identities.",
        "- Instructor reports are assessments for human review and should not be shown wholesale to students.",
        "- `student_outputs/` contains the pseudonymized concatenated text that the agent saw; show files individually only when appropriate.",
        "- `final_report.pdf`/`final_report.csv` is the single-table overview with real names for the teaching assistant; keep it private.",
        "",
        "## Missing Reports",
        "",
    ]
    if missing_report_rows:
        lines.extend(f"- `{row['pseudonym']}` / {row['full_name']}: {row['reason']}" for row in missing_report_rows)
    else:
        lines.append("- None")

    lines.extend(["", "## PDF Rendering Warnings", ""])
    if pdf_warnings:
        lines.extend(f"- `{warning}`" for warning in pdf_warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## HTML Rendering Warnings", ""])
    if html_warnings:
        lines.extend(f"- `{warning}`" for warning in html_warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Missing Student Outputs", ""])
    if missing_student_outputs:
        lines.extend(f"- `{student.pseudonym}` / {student.full_name}" for student in missing_student_outputs)
    else:
        lines.append("- None")

    (output / "finalize_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize_outputs(workspace: Path, private_output: Path, output: Path, strict: bool = False) -> FinalizeResult:
    pseudonym_map = private_output / "pseudonym_map.csv"
    student_outputs_index = private_output / "student_outputs_index.csv"
    private_student_outputs = private_output / "student_outputs"
    workspace_students = workspace / "students.csv"
    workspace_associations = workspace / "associations.csv"

    for required_path in [pseudonym_map, student_outputs_index, workspace_students, workspace_associations]:
        if not required_path.exists():
            raise FileNotFoundError(f"required finalize input does not exist: {required_path}")
    if not private_student_outputs.exists():
        raise FileNotFoundError(f"required student outputs directory does not exist: {private_student_outputs}")

    map_fieldnames, students = read_pseudonym_map(pseudonym_map)
    student_output_files = read_student_outputs_index(student_outputs_index)
    safe_names = unique_safe_names(students)
    extra_fields = [field for field in map_fieldnames if field not in set(FINAL_INDEX_BASE_COLUMNS)]
    final_index_columns = [*FINAL_INDEX_BASE_COLUMNS, *extra_fields, *FINAL_INDEX_TRAILING_COLUMNS]

    instructor_reports_dir = output / "instructor_reports"
    final_student_outputs_dir = output / "student_outputs"
    output.mkdir(parents=True, exist_ok=True)
    instructor_reports_dir.mkdir(parents=True, exist_ok=True)
    final_student_outputs_dir.mkdir(parents=True, exist_ok=True)

    final_rows: List[Dict[str, str]] = []
    missing_report_rows: List[Dict[str, str]] = []
    missing_student_outputs: List[FinalizeStudent] = []
    overview_rows: List[Dict[str, str]] = []
    found_reports = 0
    copied_student_outputs = 0

    other_student_names = {student.pseudonym: student.full_name for student in students}
    pdf_warnings: List[str] = []

    for student in students:
        expected_report = workspace / student.pseudonym / "report.json"
        report_pdf_file = ""
        report_json_file = ""
        report_status = "missing"
        if expected_report.exists():
            report_data, problem = load_assessment_report(expected_report)
            if problem is None:
                json_target = instructor_reports_dir / safe_names[student.pseudonym] / "report.json"
                write_named_report_json(expected_report, json_target)
                report_json_file = json_target.relative_to(output).as_posix()
                try:
                    pdf_target = instructor_reports_dir / safe_names[student.pseudonym] / "report.pdf"
                    render_assessment_pdf(
                        report_data, student.full_name, student.pseudonym, other_student_names, pdf_target
                    )
                    report_pdf_file = pdf_target.relative_to(output).as_posix()
                except RuntimeError as exc:
                    pdf_warnings.append(f"{student.pseudonym} / {student.full_name}: {exc}")
                report_status = "found"
                found_reports += 1
            else:
                missing_report_rows.append(
                    {
                        "pseudonym": student.pseudonym,
                        "name": student.name,
                        "surname": student.surname,
                        "full_name": student.full_name,
                        "expected_report_path": expected_report.relative_to(workspace).as_posix(),
                        "reason": problem,
                    }
                )
        else:
                missing_report_rows.append(
                    {
                        "pseudonym": student.pseudonym,
                        "name": student.name,
                        "surname": student.surname,
                        "full_name": student.full_name,
                        "expected_report_path": expected_report.relative_to(workspace).as_posix(),
                        "reason": "report.json was not found in the pseudonymized workspace",
                    }
                )

        if report_status == "found":
            overview_row = {"full_name": student.full_name, **_summary_cells(report_data, other_student_names)}
        else:
            overview_row = {
                "full_name": student.full_name,
                "all_tasks_implemented": "Unknown",
                "copying_indications": "Unknown",
                "llm_indications": "Unknown",
                "notes": "No report",
            }
        overview_rows.append(overview_row)

        student_output_file = ""
        source_output_name = student_output_files.get(student.pseudonym)
        if source_output_name:
            source_output = private_student_outputs / source_output_name
            if source_output.exists():
                output_target = final_student_outputs_dir / f"{safe_names[student.pseudonym]}.txt"
                write_named_student_output(source_output, output_target, student)
                student_output_file = output_target.relative_to(output).as_posix()
                copied_student_outputs += 1
            else:
                missing_student_outputs.append(student)
        else:
            missing_student_outputs.append(student)

        row = {
            "pseudonym": student.pseudonym,
            "name": student.name,
            "surname": student.surname,
            "full_name": student.full_name,
            "report_status": report_status,
            "report_pdf_file": report_pdf_file,
            "report_json_file": report_json_file,
            "student_output_file": student_output_file,
        }
        for field in extra_fields:
            row[field] = student.row.get(field, "")
        final_rows.append(row)

    with (output / "final_index.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=final_index_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(final_rows)

    with (output / "missing_reports.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MISSING_REPORT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(missing_report_rows)

    with (output / FINAL_REPORT_CSV).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(FINAL_REPORT_CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(overview_rows)

    final_report_pdf = ""
    try:
        render_final_report_pdf(overview_rows, output / FINAL_REPORT_PDF)
        final_report_pdf = FINAL_REPORT_PDF
    except RuntimeError as exc:
        pdf_warnings.append(f"final report: {exc}")

    # Post festum: derive the local HTML viewer solely from the final outputs
    # (final index, overview CSV, missing-reports CSV, named reports, named
    # student outputs) that were just written under `output`.
    final_report_html = ""
    html_warnings: List[str] = []
    try:
        render_final_report_html(output)
        final_report_html = FINAL_REPORT_HTML
    except Exception as exc:  # noqa: BLE001 - keep finalize robust like the PDF path
        html_warnings = [f"final report: {exc}"]

    write_finalize_report(
        output=output,
        roster_count=len(students),
        found_reports=found_reports,
        missing_report_rows=missing_report_rows,
        copied_student_outputs=copied_student_outputs,
        missing_student_outputs=missing_student_outputs,
        pdf_warnings=pdf_warnings,
        html_warnings=html_warnings,
        final_report_pdf=final_report_pdf,
        final_report_html=final_report_html,
    )

    if strict and missing_report_rows:
        raise ValueError(f"missing {len(missing_report_rows)} expected report(s); see {output / 'missing_reports.csv'}")

    return FinalizeResult(
        roster_count=len(students),
        found_reports=found_reports,
        missing_reports=len(missing_report_rows),
        copied_student_outputs=copied_student_outputs,
        final_report_pdf=final_report_pdf,
        final_report_html=final_report_html,
        output=output,
    )
