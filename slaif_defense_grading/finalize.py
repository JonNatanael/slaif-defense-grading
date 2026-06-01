from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


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
    output: Path


FINAL_INDEX_BASE_COLUMNS = [
    "pseudonym",
    "name",
    "surname",
    "full_name",
]
FINAL_INDEX_TRAILING_COLUMNS = [
    "report_status",
    "report_file",
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


def replace_pseudonyms(text: str, student: FinalizeStudent) -> str:
    text = text.replace(student.pseudonym_filename_stem, student.safe_name)
    return text.replace(student.pseudonym, student.full_name)


def write_named_report(source: Path, target: Path, student: FinalizeStudent) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = source.read_text(encoding="utf-8", errors="replace")
    content = replace_pseudonyms(content, student)
    header = "<!-- Generated locally by slaif-defense-grading finalize. Private instructor-facing output. -->\n\n"
    target.write_text(header + content, encoding="utf-8", newline="\n")


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
) -> None:
    lines = [
        "# Finalize Report",
        "",
        f"- Roster students: {roster_count}",
        f"- Found reports: {found_reports}",
        f"- Missing reports: {len(missing_report_rows)}",
        f"- Copied student-output text files: {copied_student_outputs}",
        "- Instructor reports directory: `instructor_reports/`",
        "- Student outputs directory: `student_outputs/`",
        "",
        "## Privacy Notes",
        "",
        "- This final output is private/local and may contain real student identities.",
        "- Instructor reports contain expected answers and should not be shown wholesale to students.",
        "- `student_outputs/` contains the pseudonymized concatenated text that the agent saw; show files individually only when appropriate.",
        "",
        "## Missing Reports",
        "",
    ]
    if missing_report_rows:
        lines.extend(f"- `{row['pseudonym']}` / {row['full_name']}: {row['reason']}" for row in missing_report_rows)
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
    found_reports = 0
    copied_student_outputs = 0

    for student in students:
        expected_report = workspace / student.pseudonym / "report_aspects.md"
        report_file = ""
        report_status = "missing"
        if expected_report.exists():
            report_target = instructor_reports_dir / safe_names[student.pseudonym] / "report_aspects.md"
            write_named_report(expected_report, report_target, student)
            report_file = report_target.relative_to(output).as_posix()
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
                    "reason": "report_aspects.md was not found in the pseudonymized workspace",
                }
            )

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
            "report_file": report_file,
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

    write_finalize_report(
        output=output,
        roster_count=len(students),
        found_reports=found_reports,
        missing_report_rows=missing_report_rows,
        copied_student_outputs=copied_student_outputs,
        missing_student_outputs=missing_student_outputs,
    )

    if strict and missing_report_rows:
        raise ValueError(f"missing {len(missing_report_rows)} expected report(s); see {output / 'missing_reports.csv'}")

    return FinalizeResult(
        roster_count=len(students),
        found_reports=found_reports,
        missing_reports=len(missing_report_rows),
        copied_student_outputs=copied_student_outputs,
        output=output,
    )
