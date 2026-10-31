from __future__ import annotations

import csv
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Sequence

import pytest

from slaif_defense_grading.cli import DEFAULT_CODEX_PROFILE

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSOCIATION_COLUMNS = [
    "name",
    "surname",
    "full_name",
    "associated_txt_files",
    "associated_document_files",
    "all_associated_files",
    "status",
    "evidence",
]
FORBIDDEN_IDENTIFIERS = [
    "Ana Novak",
    "Boris Kovac",
    "ana.novak@example.invalid",
    "boris.kovac@example.invalid",
    "63240001",
    "63240002",
    "Ana Novak_12345_assignsubmission_file",
    "Unmatched Person_999_assignsubmission_file",
]
MESSY_FORBIDDEN_IDENTIFIERS = [
    "Mila Kranjc",
    "Luka Horvat",
    "Nika Zupan",
    "Taj Černe",
    "Zoja Žagar",
    "mila.kranjc@example.invalid",
    "luka.horvat@example.invalid",
    "nika.zupan@example.invalid",
    "taj.cerne@example.invalid",
    "zoja.zagar@example.invalid",
    "SID-0001",
    "SID-0002",
    "SID-0003",
    "SID-0004",
    "SID-0005",
    "Mila Kranjc_100_assignsubmission_file",
    "Luka Horvat_200_assignsubmission_file",
    "Taj Černe_400_assignsubmission_file",
    "Unlisted Person_999_assignsubmission_file",
]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def build_synthetic_moodle_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/main.py",
            'print("Ana Novak")\nprint("ana.novak@example.invalid")\nprint("63240001")\n',
        )
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/notes.md",
            "# Ana Novak\nEmail: ana.novak@example.invalid\nID: 63240001\n",
        )
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/Ana Novak report.pdf",
            b"%PDF-1.4 synthetic document with an internal name",
        )
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/Ana Novak worksheet.docx",
            b"synthetic docx with an internal name",
        )
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/Ana Novak notes.odt",
            b"synthetic odt with an internal name",
        )
        zf.writestr(
            "Ana Novak_12345_assignsubmission_file/Ana Novak comments.rtf",
            b"synthetic rtf with an internal name",
        )
        zf.writestr(
            "Unmatched Person_999_assignsubmission_file/main.py",
            'print("Unmatched Person")\n',
        )


def build_messy_synthetic_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    students_csv = tmp_path / "students.csv"
    task_file = tmp_path / "task.tex"
    input_zip = tmp_path / "messy_moodle_export.zip"

    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Mila,Kranjc,mila.kranjc@example.invalid,SID-0001\n"
        "Luka,Horvat,luka.horvat@example.invalid,SID-0002\n"
        "Nika,Zupan,nika.zupan@example.invalid,SID-0003\n"
        "Taj,Černe,taj.cerne@example.invalid,SID-0004\n"
        "Zoja,Žagar,zoja.zagar@example.invalid,SID-0005\n",
    )
    write_text(task_file, "\\section{Synthetic Messy Assignment}\nUse dynamic programming and compare variants.\n")

    nested_submission = tmp_path / "mila_submission.zip"
    with zipfile.ZipFile(nested_submission, "w") as zf:
        zf.writestr(
            "src/solution.py",
            'AUTHOR = "Mila Kranjc"\nEMAIL = "mila.kranjc@example.invalid"\nSTUDENT_ID = "SID-0001"\n',
        )
        zf.writestr(
            "notebooks/analysis.ipynb",
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "markdown",
                            "source": ["Mila Kranjc used SID-0001 in this fake notebook."],
                        }
                    ],
                    "metadata": {"author": "mila.kranjc@example.invalid"},
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            ),
        )

    with zipfile.ZipFile(input_zip, "w") as zf:
        zf.write(nested_submission, "Mila Kranjc_100_assignsubmission_file/submission.zip")
        zf.writestr("Mila Kranjc_100_assignsubmission_file/Mila Kranjc report.pdf", b"%PDF synthetic Mila Kranjc")
        zf.writestr(
            "Luka Horvat_200_assignsubmission_file/main.c",
            "/* Luka Horvat luka.horvat@example.invalid SID-0002 */\nint main(void) { return 0; }\n",
        )
        zf.writestr(
            "Luka Horvat_200_assignsubmission_file/README.md",
            "# Luka Horvat\nSynthetic notes for SID-0002.\n",
        )
        zf.writestr(
            "Taj Černe_400_assignsubmission_file/Taj Černe analiza final.tex",
            "\\section{Taj Černe}\nContact: taj.cerne@example.invalid\nID: SID-0004\n",
        )
        zf.writestr(
            "Taj Černe_400_assignsubmission_file/čuden file name s presledki.py",
            'print("Taj Černe")\n',
        )
        zf.writestr(
            "Unlisted Person_999_assignsubmission_file/main.py",
            'print("Unlisted Person should stay private")\n',
        )

    return input_zip, students_csv, task_file


def run_messy_prepare(
    tmp_path: Path, include_opaque_documents: bool = False
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    input_zip, students_csv, task_file = build_messy_synthetic_fixture(tmp_path)
    workspace = tmp_path / "lab-agent"
    private_output = tmp_path / "lab-private"
    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    if include_opaque_documents:
        command.append("--include-opaque-documents")

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return workspace, private_output, result


def relative_workspace_tree(workspace: Path) -> str:
    return "\n".join(
        path.relative_to(workspace).as_posix()
        for path in sorted((p for p in workspace.rglob("*") if p.is_file()), key=lambda p: p.as_posix().casefold())
    )


def run_prepare(
    tmp_path: Path,
    include_opaque_documents: bool = False,
    task_suffix: str = ".tex",
    extra_args: Sequence[str] = (),
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    students_csv = tmp_path / "students.csv"
    task_file = tmp_path / f"assignment{task_suffix}"
    input_zip = tmp_path / "moodle_export.zip"
    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"

    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n",
    )
    if task_suffix == ".pdf":
        write_bytes(task_file, b"%PDF-1.4 synthetic assignment\n")
    else:
        write_text(task_file, "\\section{Synthetic Task}\n")
    build_synthetic_moodle_zip(input_zip)

    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    if include_opaque_documents:
        command.append("--include-opaque-documents")
    command.extend(extra_args)

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return workspace, private_output, result


def test_prepare_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "slaif-defense-grading.py", "prepare", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--students-csv" in result.stdout
    assert "--student-order-file" in result.stdout
    assert "--private-output" in result.stdout
    assert "--include-opaque-documents" in result.stdout
    assert "--codex-profile" in result.stdout
    assert "qwen-neumann" in result.stdout
    assert "--codex-reasoning-effort" in result.stdout
    assert "low/medium/xhigh" in result.stdout
    assert "task.*" in result.stdout


def test_finalize_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "slaif-defense-grading.py", "finalize", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--workspace" in result.stdout
    assert "--private-output" in result.stdout
    assert "--output" in result.stdout
    assert "--strict" in result.stdout


def test_report_template_exists_and_readme_documents_pilot_outputs() -> None:
    template = REPO_ROOT / "templates" / "workspace" / "report_template.json"
    assert template.exists()
    schema = json.loads(template.read_text(encoding="utf-8"))
    required_keys = [
        "pseudonym",
        "assignment_submitted",
        "all_tasks_implemented",
        "task_details",
        "looks_llm_generated",
        "llm_generation_indicators",
        "code_copy_indications",
        "notes",
    ]
    for key in required_keys:
        assert key in schema
    for key in ("other_student_pseudonym", "this_file", "this_lines", "other_file", "other_lines", "evidence"):
        assert key in schema["code_copy_indications"][0]
    assert "task" in schema["task_details"][0] and "implemented" in schema["task_details"][0]

    agents_text = (REPO_ROOT / "templates" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    assert "report_template.json" in agents_text
    assert "report.json" in agents_text
    assert "Run submission assessment for Student 0001" in agents_text
    for key in ("assignment_submitted", "all_tasks_implemented", "looks_llm_generated", "code_copy_indications", "other_student_pseudonym"):
        assert key in agents_text
    assert "Do not accuse AI use" in agents_text

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith('<div style="text-align: center;">')
    assert "[QUICKSTART.md](QUICKSTART.md)" in readme
    assert "python3 slaif-defense-grading.py finalize" in readme
    assert "report_template.json" in readme
    assert "report.pdf" in readme
    assert "student_outputs/" in readme
    assert "student_outputs_index.csv" in readme
    assert "--include-opaque-documents" in readme
    assert "--task-file assignment.pdf" in readme
    assert "task.pdf" in readme
    assert "task.*" in readme
    assert "Legacy Command" not in readme
    assert "SLAIF stands for" not in readme
    assert "work completed outside direct supervision" in readme
    assert "plagiarism, unauthorized collaboration, or improper AI-tool use" in readme
    assert "does not automatically prove misconduct" in readme
    assert "What To Inspect" in readme
    assert "What Can Be Shown To Students" in readme


def test_quickstart_documents_complete_workflow() -> None:
    quickstart = REPO_ROOT / "QUICKSTART.md"
    assert quickstart.exists()
    text = quickstart.read_text(encoding="utf-8")
    assert "python3 slaif-defense-grading.py prepare" in text
    assert "./process.sh" in text
    assert "python3 slaif-defense-grading.py finalize" in text
    assert "student_outputs/<Name>.txt" in text
    assert "instructor_reports/<Name>/report.pdf" in text
    assert "report.json" in text
    assert "Do not send them wholesale to students" in text
    assert "--include-opaque-documents" in text
    assert "--task-file assignment.pdf" in text
    assert "task.pdf" in text
    assert "submissions completed outside direct supervision" in text
    assert "legacy" not in text.casefold()


def test_finalize_collects_named_outputs_and_missing_reports(tmp_path: Path) -> None:
    workspace, private_output, prepare_result = run_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr

    report_dir = workspace / "Student 0001"
    report_dir.mkdir()
    workspace_report = report_dir / "report.json"
    report = {
        "pseudonym": "Student 0001",
        "assignment_submitted": True,
        "all_tasks_implemented": False,
        "task_details": [
            {"task": "compute edit distance", "implemented": True, "evidence": "main.py lines 1-9"},
            {"task": "report the results", "implemented": False, "evidence": "not present"},
        ],
        "looks_llm_generated": "likely",
        "llm_generation_indicators": ["uniform comment style in main.py lines 1-9"],
        "code_copy_indications": [
            {
                "other_student_pseudonym": "Student 0002",
                "this_file": "main.py",
                "this_lines": "12-34",
                "other_file": "sol.py",
                "other_lines": "3-11",
                "evidence": "identical helper structure",
            }
        ],
        "notes": "Brez posebnih opomb.",
    }
    original_report = json.dumps(report, indent=2) + "\n"
    workspace_report.write_text(original_report, encoding="utf-8", newline="\n")
    (workspace / "processing_stats.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_status": "running",
                "started_at": "2026-01-01T12:00:00Z",
                "ended_at": None,
                "planned_students": 2,
                "processed_students": 1,
                "successful_students": 1,
                "failed_students": 0,
                "total_time_seconds": 12,
                "average_time_seconds": 12.0,
                "students": [{"pseudonym": "Student 0001", "duration_seconds": 12, "exit_code": 0}],
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    output = tmp_path / "final"
    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert workspace_report.read_text(encoding="utf-8") == original_report

    named_report_json = output / "instructor_reports" / "Ana_Novak" / "report.json"
    assert named_report_json.exists()
    assert json.loads(named_report_json.read_text(encoding="utf-8")) == report

    named_report_pdf = output / "instructor_reports" / "Ana_Novak" / "report.pdf"
    assert named_report_pdf.exists()
    pdf_bytes = named_report_pdf.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes[-32:]
    assert len(pdf_bytes) > 1000
    assert b"/Type /Page" in pdf_bytes

    named_student_output = output / "student_outputs" / "Ana_Novak.txt"
    assert named_student_output.exists()
    named_student_output_text = named_student_output.read_text(encoding="utf-8")
    assert "This is the pseudonymized concatenated submission text that the agent saw." in named_student_output_text
    assert "Student: Ana Novak" in named_student_output_text
    assert "Pseudonym: Student 0001" in named_student_output_text
    assert "Ana Novak" not in "\n".join(named_student_output_text.splitlines()[4:])
    assert "ana.novak@example.invalid" not in named_student_output_text
    assert "63240001" not in named_student_output_text
    assert (private_output / "student_outputs" / "Student_0001.txt").read_text(encoding="utf-8") == (
        workspace / "Student_0001.txt"
    ).read_text(encoding="utf-8")

    with (output / "final_index.csv").open("r", encoding="utf-8", newline="") as f:
        final_rows = list(csv.DictReader(f))
    assert [row["pseudonym"] for row in final_rows] == ["Student 0001", "Student 0002"]
    assert final_rows[0]["name"] == "Ana"
    assert final_rows[0]["surname"] == "Novak"
    assert final_rows[0]["full_name"] == "Ana Novak"
    assert final_rows[0]["email"] == "ana.novak@example.invalid"
    assert final_rows[0]["student_id"] == "63240001"
    assert final_rows[0]["report_status"] == "found"
    assert final_rows[0]["report_pdf_file"] == "instructor_reports/Ana_Novak/report.pdf"
    assert final_rows[0]["report_json_file"] == "instructor_reports/Ana_Novak/report.json"
    assert final_rows[0]["student_output_file"] == "student_outputs/Ana_Novak.txt"
    assert final_rows[1]["report_status"] == "missing"
    assert final_rows[1]["report_pdf_file"] == ""
    assert final_rows[1]["report_json_file"] == ""
    assert final_rows[1]["student_output_file"] == ""

    with (output / "missing_reports.csv").open("r", encoding="utf-8", newline="") as f:
        missing_rows = list(csv.DictReader(f))
    assert missing_rows == [
        {
            "pseudonym": "Student 0002",
            "name": "Boris",
            "surname": "Kovac",
            "full_name": "Boris Kovac",
            "expected_report_path": "Student 0002/report.json",
            "reason": "report.json was not found in the pseudonymized workspace",
        }
    ]

    finalize_report = (output / "finalize_report.md").read_text(encoding="utf-8")
    assert "Roster students: 2" in finalize_report
    assert "Found reports: 1" in finalize_report
    assert "Missing reports: 1" in finalize_report
    assert "Copied student-output text files: 1" in finalize_report
    assert "- Final report (single-table overview): `final_report.pdf` and `final_report.csv`" in finalize_report
    assert "`Student 0002` / Boris Kovac: report.json was not found in the pseudonymized workspace" in finalize_report
    assert "Instructor reports are assessments for human review" in finalize_report
    assert "## Processing Statistics" in finalize_report
    assert "Run status: running" in finalize_report
    assert "Total elapsed time: 12 seconds" in finalize_report
    assert "Average time per processed student: 12 seconds" in finalize_report
    assert "`Student 0001` / Ana Novak: 12 seconds (exit code 0)" in finalize_report
    assert "## PDF Rendering Warnings" in finalize_report

    final_report_pdf = output / "final_report.pdf"
    assert final_report_pdf.exists()
    final_pdf_bytes = final_report_pdf.read_bytes()
    assert final_pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in final_pdf_bytes[-32:]
    assert b"/Type /Page" in final_pdf_bytes
    # The statistics are rendered on their own page (text encoding varies
    # when a Unicode font is available, so content is asserted below with
    # deterministic core fonts).
    assert final_pdf_bytes.count(b"/Type /Page") >= 2

    with (output / "final_report.csv").open("r", encoding="utf-8", newline="") as f:
        final_report_rows = list(csv.DictReader(f))
    assert [row["full_name"] for row in final_report_rows] == ["Ana Novak", "Boris Kovac"]
    assert final_report_rows[0] == {
        "full_name": "Ana Novak",
        "all_tasks_implemented": "No",
        "copying_indications": "Yes (with Boris Kovac)",
        "llm_indications": "Likely",
        "notes": "Brez posebnih opomb.",
    }
    assert final_report_rows[1] == {
        "full_name": "Boris Kovac",
        "all_tasks_implemented": "Unknown",
        "copying_indications": "Unknown",
        "llm_indications": "Unknown",
        "notes": "No report",
    }

    workspace_text = (workspace / "students.csv").read_text(encoding="utf-8") + (workspace / "associations.csv").read_text(encoding="utf-8")
    assert "Ana Novak" not in workspace_text
    assert "Boris Kovac" not in workspace_text

    strict_output = tmp_path / "final-strict"
    strict_result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(strict_output),
            "--strict",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict_result.returncode == 2
    assert "missing 1 expected report" in strict_result.stderr


def test_finalize_invalid_report_json_listed_as_missing(tmp_path: Path) -> None:
    workspace, private_output, prepare_result = run_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr

    report_dir = workspace / "Student 0001"
    report_dir.mkdir()
    (report_dir / "report.json").write_text("{not valid json", encoding="utf-8", newline="\n")

    output = tmp_path / "final"
    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with (output / "missing_reports.csv").open("r", encoding="utf-8", newline="") as f:
        missing_rows = list(csv.DictReader(f))
    assert len(missing_rows) == 2
    by_pseudonym = {row["pseudonym"]: row for row in missing_rows}
    assert "report.json is not valid JSON" in by_pseudonym["Student 0001"]["reason"]
    assert by_pseudonym["Student 0002"]["reason"] == "report.json was not found in the pseudonymized workspace"
    assert not (output / "instructor_reports" / "Ana_Novak" / "report.pdf").exists()

    with (output / "final_report.csv").open("r", encoding="utf-8", newline="") as f:
        final_report_rows = list(csv.DictReader(f))
    assert len(final_report_rows) == 2
    for row in final_report_rows:
        assert row["all_tasks_implemented"] == "Unknown"
        assert row["copying_indications"] == "Unknown"
        assert row["llm_indications"] == "Unknown"
        assert row["notes"] == "No report"
    assert (output / "final_report.pdf").exists()


def test_finalize_long_notes_stay_on_one_page_in_final_report(tmp_path: Path) -> None:
    """Long agent notes must not make a final-report row taller than a page."""
    workspace, private_output, prepare_result = run_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr

    long_notes = "Uniform comments and identical helper structure across all files; "
    long_notes += "worth probing in oral verification on the edit-distance implementation. "
    long_notes *= 5  # ~1.6k characters: too tall for one table row when unclipped

    report = {
        "pseudonym": "Student 0001",
        "assignment_submitted": True,
        "all_tasks_implemented": True,
        "task_details": [
            {"task": "compute edit distance", "implemented": True, "evidence": "main.py lines 1-9"},
            {"task": "report the results", "implemented": True, "evidence": "main.py lines 20-31"},
        ],
        "looks_llm_generated": "likely",
        "llm_generation_indicators": ["uniform comment style in main.py lines 1-9"],
        "code_copy_indications": [],
        "notes": long_notes,
    }
    (workspace / "Student 0001").mkdir()
    (workspace / "Student 0001" / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    output = tmp_path / "final"
    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    final_report_pdf = output / "final_report.pdf"
    assert final_report_pdf.exists()
    assert final_report_pdf.read_bytes().startswith(b"%PDF-")

    with (output / "final_report.csv").open("r", encoding="utf-8", newline="") as f:
        final_rows = list(csv.DictReader(f))
    ana = next(row for row in final_rows if row["full_name"] == "Ana Novak")
    assert len(ana["notes"]) == 240
    assert ana["notes"].endswith("...")
    assert long_notes not in ana["notes"]

    # The untruncated notes stay in the named student report.
    named_report = json.loads((output / "instructor_reports" / "Ana_Novak" / "report.json").read_text(encoding="utf-8"))
    assert named_report["notes"] == long_notes


def test_html_report_loads_code_files_from_concatenated_output(tmp_path: Path) -> None:
    from slaif_defense_grading.html_report import load_code_files

    txt = tmp_path / "Student_0001.txt"
    txt.write_text(
        "header line that must be ignored\n"
        "==== BEGIN Student 0001 | submission | main.py ====\n"
        "line one\n"
        "line two\n"
        "==== END Student 0001 | submission | main.py ====\n"
        "==== BEGIN Student 0001 | submission | src/deep/file.py ====\n"
        "only line\n"
        "==== END Student 0001 | submission | src/deep/file.py ====\n"
        "trailing junk\n",
        encoding="utf-8",
        newline="\n",
    )
    files = load_code_files(txt)
    assert files == [
        {"file": "main.py", "lines": ["line one", "line two"]},
        {"file": "src/deep/file.py", "lines": ["only line"]},
    ]


def test_finalize_renders_html_viewer(tmp_path: Path) -> None:
    workspace, private_output, prepare_result = run_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr

    report = {
        "pseudonym": "Student 0001",
        "assignment_submitted": True,
        "all_tasks_implemented": True,
        "task_details": [
            {"task": "print the greeting", "implemented": True, "evidence": "main.py lines 1-2"},
        ],
        "looks_llm_generated": "likely",
        "llm_generation_indicators": ["uniform style in main.py lines 1-2"],
        "code_copy_indications": [
            {
                "other_student_pseudonym": "Student 0002",
                "this_file": "main.py",
                "this_lines": "1-2",
                "other_file": "sol.py",
                "other_lines": "1-1",
                "evidence": "identical print statement (main.py line 1 vs sol.py line 1)",
            }
        ],
        "notes": "Naming style visible in main.py lines 1-2.",
    }
    (workspace / "Student 0001").mkdir()
    (workspace / "Student 0001" / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    output = tmp_path / "final"
    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    html_path = output / "final_report.html"
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    for needle in (
        "Ana Novak",
        "Student 0001",
        "Boris Kovac",
        "final_report.pdf",
        "final_report.csv",
        "instructor_reports/Ana_Novak/report.pdf",
        "instructor_reports/Ana_Novak/report.json",
        "student_outputs/Ana_Novak.txt",
        "No report",
        'id="codetip"',
        "data-owner",
        "refChips",
        "codeTip",
        ".codelink.note",
    ):
        assert needle in html, needle

    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert match is not None
    data = json.loads(match.group(1).replace("<\\/", "</"))
    students = data["students"]
    ana = next(s for s in students if s["pseudonym"] == "Student 0001")
    boris = next(s for s in students if s["pseudonym"] == "Student 0002")
    assert ana["status"] == "found"
    assert ana["report"]["notes"] == "Naming style visible in main.py lines 1-2."
    ana_code = {f["file"]: f["lines"] for f in ana["code"]}
    # The named output carries the pseudonymized text the agent saw: roster
    # identifiers are scrubbed to the pseudonym before concatenation.
    assert ana_code["main.py"] == ['print("Student 0001")', 'print("Student 0001")', 'print("Student 0001")']
    assert "notes.md" in ana_code
    assert ana["overview"]["copying_indications"] == "Yes (with Boris Kovac)"
    assert boris["status"] == "missing"
    assert boris["report"] is None
    assert boris["code"] == []
    assert boris["overview"]["notes"] == "No report"

    finalize_report = (output / "finalize_report.md").read_text(encoding="utf-8")
    assert "- Final report (local HTML viewer): `final_report.html`" in finalize_report
    assert "## HTML Rendering Warnings" in finalize_report

    # The viewer is derived from the final outputs only; the workspace stays clean.
    assert not list(workspace.rglob("*.html"))


def test_html_viewer_embedded_script_is_valid_javascript(tmp_path: Path) -> None:
    """The embedded viewer script must stay valid JavaScript (checked via node when available)."""
    from slaif_defense_grading.html_report import _TEMPLATE

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available; skipping the embedded JS syntax check")
    match = re.search(r"<script>\n(.*?)\n</script>", _TEMPLATE, re.S)
    assert match is not None
    script_path = tmp_path / "viewer.js"
    script_path.write_text(match.group(1), encoding="utf-8")
    proc = subprocess.run([node, "--check", str(script_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_finalize_uses_deterministic_safe_paths_for_duplicate_names(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    private_output = tmp_path / "private"
    output = tmp_path / "final"
    workspace.mkdir()
    private_output.mkdir()
    (private_output / "student_outputs").mkdir()

    write_text(workspace / "students.csv", "name,surname,full_name\nStudent,0001,Student 0001\nStudent,0002,Student 0002\n")
    write_text(
        workspace / "associations.csv",
        "name,surname,full_name,associated_txt_files,associated_document_files,all_associated_files,status,evidence\n"
        "Student,0001,Student 0001,Student_0001.txt,,Student_0001.txt,matched,matched\n"
        "Student,0002,Student 0002,Student_0002.txt,,Student_0002.txt,matched,matched\n",
    )
    write_text(
        private_output / "pseudonym_map.csv",
        "pseudonym,name,surname,full_name,email,student_id\n"
        "Student 0001,Ana,Novak,Ana Novak,ana1@example.invalid,ID-1\n"
        "Student 0002,Ana,Novak,Ana Novak,ana2@example.invalid,ID-2\n",
    )
    write_text(
        private_output / "student_outputs_index.csv",
        "pseudonym,name,surname,full_name,student_output_file,email,student_id\n"
        "Student 0001,Ana,Novak,Ana Novak,Student_0001.txt,ana1@example.invalid,ID-1\n"
        "Student 0002,Ana,Novak,Ana Novak,Student_0002.txt,ana2@example.invalid,ID-2\n",
    )
    write_text(private_output / "student_outputs" / "Student_0001.txt", "Student 0001 content\n")
    write_text(private_output / "student_outputs" / "Student_0002.txt", "Student 0002 content\n")
    def valid_report_for(pseudonym: str) -> str:
        return json.dumps(
            {
                "pseudonym": pseudonym,
                "assignment_submitted": True,
                "all_tasks_implemented": True,
                "task_details": [],
                "looks_llm_generated": "uncertain",
                "llm_generation_indicators": [],
                "code_copy_indications": [],
                "notes": "",
            }
        )

    write_text(workspace / "Student 0001" / "report.json", valid_report_for("Student 0001"))
    write_text(workspace / "Student 0002" / "report.json", valid_report_for("Student 0002"))

    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (output / "instructor_reports" / "Ana_Novak" / "report.json").exists()
    assert (output / "instructor_reports" / "Ana_Novak" / "report.pdf").exists()
    assert (output / "instructor_reports" / "Ana_Novak__Student_0002" / "report.json").exists()
    assert (output / "instructor_reports" / "Ana_Novak__Student_0002" / "report.pdf").exists()
    assert (output / "student_outputs" / "Ana_Novak.txt").exists()
    assert (output / "student_outputs" / "Ana_Novak__Student_0002.txt").exists()

    with (output / "final_index.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["report_pdf_file"] == "instructor_reports/Ana_Novak/report.pdf"
    assert rows[0]["report_json_file"] == "instructor_reports/Ana_Novak/report.json"
    assert rows[1]["report_pdf_file"] == "instructor_reports/Ana_Novak__Student_0002/report.pdf"
    assert rows[1]["report_json_file"] == "instructor_reports/Ana_Novak__Student_0002/report.json"
    assert rows[0]["student_output_file"] == "student_outputs/Ana_Novak.txt"
    assert rows[1]["student_output_file"] == "student_outputs/Ana_Novak__Student_0002.txt"



def test_prepare_creates_pseudonymized_workspace_and_private_outputs(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (workspace / "students.csv").read_text(encoding="utf-8") == (
        "name,surname,full_name\n"
        "Student,0001,Student 0001\n"
        "Student,0002,Student 0002\n"
    )
    assert (workspace / "task.tex").read_text(encoding="utf-8") == "\\section{Synthetic Task}\n"
    assert not (workspace / "task.pdf").exists()

    process_sh = workspace / "process.sh"
    process_text = process_sh.read_text(encoding="utf-8")
    assert process_sh.stat().st_mode & stat.S_IXUSR
    assert "Phase 1" not in process_text
    assert "cat .slaif_prompts" not in process_text
    # The Codex command prefix appears exactly twice: once in the one-time
    # assignment-analysis command and once for the matched student. The
    # unmatched student is handled as an unresolved local neutral report.
    default_codex_command = (
        f"codex -p {DEFAULT_CODEX_PROFILE} -c model_reasoning_effort=medium --ask-for-approval never -s workspace-write exec --skip-git-repo-check"
    )
    assert process_text.count(default_codex_command) == 2
    assert 'ASSIGNMENT_AGENT_COMMAND=(codex -p ' in process_text
    assert '"Analyze assignment requirements"' in process_text
    assert 'PROCESS_RESOLVED_PSEUDONYMS=("Student 0001")' in process_text
    assert 'PROCESS_EXTRACTION_WARNINGS=false' in process_text
    assert 'run_planned_student "Student 0001" resolved codex' in process_text
    assert 'run_planned_student "Student 0002" unresolved' in process_text
    assert '"Run submission assessment for Student 0001"' in process_text
    assert "Run submission assessment for Student 0002" not in process_text
    assert "Ana Novak" not in process_text
    assert "Boris Kovac" not in process_text
    assert not (workspace / ".slaif_prompts").exists()

    validator_helper = workspace / "report_validator.py"
    assert validator_helper.exists()
    assert validator_helper.read_text(encoding="utf-8") == (
        REPO_ROOT / "slaif_defense_grading" / "report_validation.py"
    ).read_text(encoding="utf-8")

    agents_md = workspace / "AGENTS.md"
    assert agents_md.exists()
    assert agents_md.read_text(encoding="utf-8") == (REPO_ROOT / "templates" / "workspace" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    agents_text = agents_md.read_text(encoding="utf-8")
    assert "Run submission assessment for Student 0001" in agents_text
    assert "students.csv" in agents_text
    assert "associations.csv" in agents_text
    assert "task.*" in agents_text
    assert "task.pdf" in agents_text
    assert "report_template.json" in agents_text
    assert "`report_template.json` is the mandatory schema" in agents_text
    assert "assignment_submitted" in agents_text
    assert "all_tasks_implemented" in agents_text
    assert "looks_llm_generated" in agents_text
    assert "code_copy_indications" in agents_text
    assert "other_student_pseudonym" in agents_text
    assert "Do not invent evidence, line numbers, or indicators" in agents_text
    assert "preprocessing" in agents_text
    assert "already done locally" in agents_text
    assert "Do not redo preprocessing" in agents_text
    assert "`processing_stats.json` (when present; it is maintained by `process.sh`)" in agents_text
    assert "reasonably strong" in agents_text
    assert "most obviously copied" in agents_text
    assert "import statements" in agents_text
    assert "standard display and plotting code" in agents_text
    assert "similar standard library or framework API calls" in agents_text
    assert "written as a paragraph" in agents_text
    assert "single-table final overview PDF (`final_report.pdf`)" in agents_text
    assert "The only student submission files are the files listed in `associations.csv`." in agents_text
    assert "Do not accuse AI use" in agents_text
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in agents_text

    report_template = workspace / "report_template.json"
    assert report_template.exists()
    assert report_template.read_text(encoding="utf-8") == (
        REPO_ROOT / "templates" / "workspace" / "report_template.json"
    ).read_text(encoding="utf-8")
    json.loads(report_template.read_text(encoding="utf-8"))
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in report_template.read_text(encoding="utf-8")

    student_text = (workspace / "Student_0001.txt").read_text(encoding="utf-8")
    assert "==== BEGIN Student 0001 | submission | main.py ====" in student_text
    assert "Student 0001" in student_text
    assert "Ana Novak" not in student_text
    assert "ana.novak@example.invalid" not in student_text
    assert "63240001" not in student_text
    assert "==== BEGIN Student 0001 | submission | notes.md ====" in student_text
    assert not list(workspace.glob("*.pdf"))
    assert not list(workspace.glob("*.docx"))
    assert not list(workspace.glob("*.odt"))
    assert not list(workspace.glob("*.rtf"))
    assert not (workspace / "Unmatched_Person.txt").exists()

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        association_reader = csv.DictReader(f)
        association_rows = list(association_reader)
    assert association_reader.fieldnames == ASSOCIATION_COLUMNS
    assert [row["full_name"] for row in association_rows] == ["Student 0001", "Student 0002"]
    assert association_rows[0]["name"] == "Student"
    assert association_rows[0]["surname"] == "0001"
    assert association_rows[0]["associated_txt_files"] == "Student_0001.txt"
    assert association_rows[0]["associated_document_files"] == ""
    assert association_rows[0]["all_associated_files"] == "Student_0001.txt"
    assert association_rows[0]["status"] == "matched"
    assert association_rows[0]["evidence"] == "Generated pseudonymized submission package for Student 0001."
    assert association_rows[1]["associated_txt_files"] == ""
    assert association_rows[1]["associated_document_files"] == ""
    assert association_rows[1]["all_associated_files"] == ""
    assert association_rows[1]["status"] == "unresolved"
    assert association_rows[1]["evidence"] == "No matched pseudonymized submission files were generated."
    association_text = (workspace / "associations.csv").read_text(encoding="utf-8")
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in association_text

    map_path = private_output / "pseudonym_map.csv"
    assert map_path.exists()
    assert not (workspace / "pseudonym_map.csv").exists()
    with map_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["pseudonym"] == "Student 0001"
    assert rows[0]["name"] == "Ana"
    assert rows[0]["surname"] == "Novak"
    assert rows[0]["email"] == "ana.novak@example.invalid"
    assert rows[0]["student_id"] == "63240001"

    student_outputs = private_output / "student_outputs"
    assert student_outputs.exists()
    assert (student_outputs / "Student_0001.txt").read_text(encoding="utf-8") == (workspace / "Student_0001.txt").read_text(
        encoding="utf-8"
    )
    assert not (student_outputs / "Student_0002.txt").exists()
    student_output_text = (student_outputs / "Student_0001.txt").read_text(encoding="utf-8")
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in student_output_text

    index_path = private_output / "student_outputs_index.csv"
    assert index_path.exists()
    with index_path.open("r", encoding="utf-8", newline="") as f:
        index_rows = list(csv.DictReader(f))
    assert index_rows == [
        {
            "pseudonym": "Student 0001",
            "name": "Ana",
            "surname": "Novak",
            "full_name": "Ana Novak",
            "student_output_file": "Student_0001.txt",
            "email": "ana.novak@example.invalid",
            "student_id": "63240001",
        }
    ]

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Roster students: 2" in report
    assert "Matched students: 1" in report
    assert "Students without submissions: 1" in report
    assert "Unmatched Person_999_assignsubmission_file" in report
    assert "excluded from the workspace by default" in report
    assert "cannot safely pseudonymize their internal content or metadata" in report
    assert "Ana Novak report.pdf" in report
    assert "Ana Novak worksheet.docx" in report
    assert "Ana Novak notes.odt" in report
    assert "Ana Novak comments.rtf" in report
    assert "Original matched LMS folder: `Ana Novak_12345_assignsubmission_file`" in report
    assert "Workspace text output: `Student_0001.txt`" in report
    assert "Student-visible concatenated outputs were written to `student_outputs/`" in report
    assert "`student_outputs_index.csv` maps those pseudonymized files back to real roster rows" in report


def test_generated_process_script_writes_timing_statistics(tmp_path: Path) -> None:
    workspace, _private_output, prepare_result = run_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/bin/bash\n"
        "prompt=${!#}\n"
        "case \"$prompt\" in\n"
        "  \"Analyze assignment requirements\")\n"
        "    printf '%s\\n' '{\"schema_version\": 1, \"requirements\": [{\"id\": \"task-001\", \"description\": \"Implement the synthetic task by the behavior it asks for.\", \"source_reference\": \"task_extracted.txt line 1\"}], \"notes\": \"\"}' > task_requirements.json\n"
        "    exit 0 ;;\n"
        "esac\n"
        "student=${prompt#Run submission assessment for }\n"
        "sleep 1\n"
        "mkdir -p \"$student\"\n"
        "printf '%s\\n' \"{\\\"pseudonym\\\": \\\"$student\\\", \\\"assignment_submitted\\\": true, \\\"all_tasks_implemented\\\": true, \\\"task_details\\\": [], \\\"looks_llm_generated\\\": \\\"uncertain\\\", \\\"llm_generation_indicators\\\": [], \\\"code_copy_indications\\\": [], \\\"notes\\\": \\\"\\\"}\" > \"$student/report.json\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_codex.chmod(0o755)

    result = subprocess.run(
        ["bash", "process.sh"],
        cwd=workspace,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stats = json.loads((workspace / "processing_stats.json").read_text(encoding="utf-8"))
    assert stats["schema_version"] == 2
    assert stats["run_status"] == "completed"
    assert stats["planned_students"] == 2
    assert stats["processed_students"] == 2
    assert stats["successful_students"] == 1
    assert stats["failed_students"] == 0
    assert stats["skipped_students"] == 0
    assert stats["generated_unresolved_students"] == 1
    assert stats["total_time_seconds"] >= 1
    assert stats["average_time_seconds"] >= 0.5
    assert [(row["pseudonym"], row["outcome"]) for row in stats["students"]] == [
        ("Student 0001", "agent_success"),
        ("Student 0002", "generated_unresolved"),
    ]
    assert all(row["exit_code"] == 0 for row in stats["students"])


def test_workspace_text_redacts_identity_from_unlisted_lms_folder() -> None:
    from slaif_defense_grading.prepare import folder_private_identifiers, scrub_text

    identifiers = folder_private_identifiers("Bob Beta=bb123@example.invalid=10000002_1016174_assignsubmission_file")
    assert identifiers == ["Bob Beta", "bb123@example.invalid", "10000002"]
    assert scrub_text("# copied from Bob Beta\n", [], identifiers) == "# copied from [redacted private identifier]\n"


def test_prepare_prioritizes_student_ids_before_pseudonymization(tmp_path: Path) -> None:
    order_file = tmp_path / "student-order.txt"
    write_text(order_file, "63240002\n")

    workspace, private_output, result = run_prepare(
        tmp_path,
        extra_args=["--student-order-file", str(order_file)],
    )

    assert result.returncode == 0, result.stderr
    with (private_output / "pseudonym_map.csv").open("r", encoding="utf-8", newline="") as f:
        map_rows = list(csv.DictReader(f))
    assert [(row["pseudonym"], row["student_id"]) for row in map_rows] == [
        ("Student 0001", "63240002"),
        ("Student 0002", "63240001"),
    ]

    assert not (workspace / "Student_0001.txt").exists()
    assert (workspace / "Student_0002.txt").exists()
    student_text = (workspace / "Student_0002.txt").read_text(encoding="utf-8")
    assert "==== BEGIN Student 0002 | submission | main.py ====" in student_text
    assert "63240002" not in (workspace / "process.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("contents", "error"),
    [
        ("99999999\n", "not found in students CSV"),
        ("63240001\n63240001\n", "duplicate student ID"),
    ],
)
def test_prepare_rejects_invalid_student_order_file(tmp_path: Path, contents: str, error: str) -> None:
    order_file = tmp_path / "student-order.txt"
    write_text(order_file, contents)

    _workspace, _private_output, result = run_prepare(
        tmp_path,
        extra_args=["--student-order-file", str(order_file)],
    )

    assert result.returncode == 2
    assert error in result.stderr


def test_prepare_codex_profile_none_omits_profile_flag(tmp_path: Path) -> None:
    workspace, _private_output, result = run_prepare(
        tmp_path,
        extra_args=["--codex-profile", "none", "--codex-reasoning-effort", "none"],
    )

    assert result.returncode == 0, result.stderr
    process_text = (workspace / "process.sh").read_text(encoding="utf-8")
    assert "codex -p " not in process_text
    assert "-c model_reasoning_effort" not in process_text
    # The command appears for both the one-time assignment-analysis call and
    # the matched student assessment.
    assert process_text.count("codex --ask-for-approval never -s workspace-write exec --skip-git-repo-check") == 2
    assert "Ana Novak" not in process_text
    assert "Boris Kovac" not in process_text


def test_prepare_codex_reasoning_effort_low_is_rendered(tmp_path: Path) -> None:
    workspace, _private_output, result = run_prepare(
        tmp_path,
        extra_args=["--codex-reasoning-effort", "low"],
    )

    assert result.returncode == 0, result.stderr
    process_text = (workspace / "process.sh").read_text(encoding="utf-8")
    # The command appears for both the one-time assignment-analysis call and
    # the matched student assessment.
    assert process_text.count(
        f"codex -p {DEFAULT_CODEX_PROFILE} -c model_reasoning_effort=low --ask-for-approval never -s workspace-write exec --skip-git-repo-check"
    ) == 2
    assert "Ana Novak" not in process_text
    assert "Boris Kovac" not in process_text

def test_prepare_reads_utf16_bom_roster(tmp_path: Path) -> None:
    students_csv = tmp_path / "students.csv"
    roster = (
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n"
    )
    students_csv.write_bytes(roster.encode("utf-16"))  # UTF-16 LE with BOM, as some LMS/Excel exports produce

    task_file = tmp_path / "assignment.tex"
    write_text(task_file, "\\section{Synthetic Task}\n")
    input_zip = tmp_path / "moodle_export.zip"
    build_synthetic_moodle_zip(input_zip)

    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"
    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert (workspace / "students.csv").read_text(encoding="utf-8") == (
        "name,surname,full_name\n"
        "Student,0001,Student 0001\n"
        "Student,0002,Student 0002\n"
    )

    map_path = private_output / "pseudonym_map.csv"
    with map_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["pseudonym"] for row in rows] == ["Student 0001", "Student 0002"]
    assert rows[0]["name"] == "Ana"
    assert rows[0]["surname"] == "Novak"
    assert rows[1]["name"] == "Boris"
    assert rows[1]["surname"] == "Kovac"


def build_explicit_id_synthetic_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "Ana Novak=ana.novak@example.invalid=63240001_92312_ab_cd/main.py",
            'print("alpha bravo charlie")\n',
        )
        zf.writestr(
            "Boris Kovac=boris.kovac@example.invalid=63240002_92313_ef_gh/notes.md",
            "# delta echo foxtrot\n",
        )
        zf.writestr(
            "Nobody Here=ghost@example.invalid=99999999_1_ab_cd/main.py",
            "print('nobody here')\n",
        )


def build_conflicting_explicit_id_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        # email points at Boris Kovac while the student_id points at Ana Novak
        zf.writestr("Ana Novak=boris.kovac@example.invalid=63240001_1_ab_cd/main.py", "print('x')\n")


def run_explicit_id_prepare(tmp_path: Path, zip_builder) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    students_csv = tmp_path / "students.csv"
    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n",
    )
    task_file = tmp_path / "assignment.tex"
    write_text(task_file, "\\section{Synthetic Task}\n")
    input_zip = tmp_path / "moodle_export.zip"
    zip_builder(input_zip)

    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"
    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return workspace, private_output, result


def test_prepare_matches_folders_with_explicit_email_and_id(tmp_path: Path) -> None:
    workspace, private_output, result = run_explicit_id_prepare(tmp_path, build_explicit_id_synthetic_zip)

    assert result.returncode == 0, result.stderr

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["full_name"] for row in rows] == ["Student 0001", "Student 0002"]
    assert rows[0]["status"] == "matched"
    assert rows[1]["status"] == "matched"
    assert rows[0]["associated_txt_files"] == "Student_0001.txt"
    assert rows[1]["associated_txt_files"] == "Student_0002.txt"

    assert "alpha bravo charlie" in (workspace / "Student_0001.txt").read_text(encoding="utf-8")
    assert "delta echo foxtrot" in (workspace / "Student_0002.txt").read_text(encoding="utf-8")

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Matched students: 2" in report
    assert "Nobody Here=ghost@example.invalid=99999999_1_ab_cd" in report

    workspace_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in workspace.rglob("*") if path.is_file()
    )
    assert "Nobody Here" not in workspace_text
    assert "ghost@example.invalid" not in workspace_text
    assert "99999999" not in workspace_text


def test_prepare_explicit_identifier_conflict_stays_unmatched(tmp_path: Path) -> None:
    workspace, private_output, result = run_explicit_id_prepare(tmp_path, build_conflicting_explicit_id_zip)

    assert result.returncode == 0, result.stderr

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(row["status"] == "unresolved" for row in rows)

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Matched students: 0" in report
    assert "Ana Novak=boris.kovac@example.invalid=63240001_1_ab_cd" in report


def build_encrypted_zip(path: Path, entry_name: str = "secret.py", content: bytes = b"print('secret')\n", password: str = "secret") -> None:
    """Write a minimal ZIP using PKZIP traditional password encryption (stdlib cannot write these)."""
    import struct
    import zlib

    def update_keys(keys: tuple, byte: int) -> tuple:
        key0, key1, key2 = keys
        key0 = zlib.crc32(bytes([byte]), key0) & 0xFFFFFFFF
        key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
        key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
        key2 = zlib.crc32(bytes([(key1 >> 24) & 0xFF]), key2) & 0xFFFFFFFF
        return key0, key1, key2

    def prng_byte(keys: tuple) -> int:
        temp = (keys[2] | 2) & 0xFFFF
        return (temp * (temp ^ 1) >> 8) & 0xFF

    keys = (0x12345678, 0x5678ABCD, 0xBADCAFED)
    for byte in password.encode("latin-1"):
        keys = update_keys(keys, byte)

    header = bytes(prng_byte(keys) for _ in range(10))
    pwd = password.encode("latin-1")[0]
    header += bytes([pwd & 0xFF, (pwd >> 8) & 0xFF])

    encrypted = bytearray()
    for byte in content:
        encrypted.append(byte ^ prng_byte(keys))
        keys = update_keys(keys, byte)

    data = header + bytes(encrypted)
    name = entry_name.encode()
    crc = zlib.crc32(content) & 0xFFFFFFFF
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0001, 0, 0, 0, crc, len(data), len(content), len(name), 0) + name
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50, 20, 20, 0x0001, 0, 0, 0, crc, len(data), len(content), len(name), 0, 0, 0, 0, 0, 0,
    ) + name
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), 0, 0)
    path.write_bytes(local + central + eocd)


def test_prepare_skips_encrypted_nested_zip_and_reports_it(tmp_path: Path) -> None:
    students_csv = tmp_path / "students.csv"
    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n",
    )
    task_file = tmp_path / "assignment.tex"
    write_text(task_file, "\\section{Synthetic Task}\n")

    input_zip = tmp_path / "moodle_export.zip"
    with zipfile.ZipFile(input_zip, "w") as zf:
        encrypted = tmp_path / "submission.zip"
        build_encrypted_zip(encrypted)
        zf.write(encrypted, "Ana Novak_12345_assignsubmission_file/submission.zip")
        zf.writestr("Boris Kovac_67890_assignsubmission_file/main.py", "print('golf hotel juliet')\n")

    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"
    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # the only readable artifact is the "no submission" marker; the encrypted ZIP is reported privately
    assert rows[0]["status"] == "matched"
    assert "No matched submission was found for this roster student." in (workspace / "Student_0001.txt").read_text(encoding="utf-8")
    assert rows[1]["status"] == "matched"
    assert "golf hotel juliet" in (workspace / "Student_0002.txt").read_text(encoding="utf-8")

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "## Skipped Nested ZIPs" in report
    assert "Ana Novak_12345_assignsubmission_file/submission.zip" in report


def test_prepare_unwraps_single_top_level_container_folder(tmp_path: Path) -> None:
    students_csv = tmp_path / "students.csv"
    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n",
    )
    task_file = tmp_path / "assignment.tex"
    write_text(task_file, "\\section{Synthetic Task}\n")

    input_zip = tmp_path / "moodle_export.zip"
    with zipfile.ZipFile(input_zip, "w") as zf:
        zf.writestr("ass1/Ana Novak_12345_assignsubmission_file/main.py", "print('kilo lima mike')\n")
        zf.writestr("ass1/Boris Kovac_67890_assignsubmission_file/notes.md", "# november oscar papa\n")

    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"
    command = [
        sys.executable,
        "slaif-defense-grading.py",
        "prepare",
        "--input-file",
        str(input_zip),
        "--students-csv",
        str(students_csv),
        "--task-file",
        str(task_file),
        "--workspace",
        str(workspace),
        "--private-output",
        str(private_output),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(row["status"] == "matched" for row in rows)
    assert "kilo lima mike" in (workspace / "Student_0001.txt").read_text(encoding="utf-8")
    assert "november oscar papa" in (workspace / "Student_0002.txt").read_text(encoding="utf-8")


def test_prepare_can_explicitly_include_opaque_documents_with_warning(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path, include_opaque_documents=True)

    assert result.returncode == 0, result.stderr
    copied_names = sorted(path.name for path in workspace.iterdir() if path.suffix in {".pdf", ".docx", ".odt", ".rtf"})
    assert len(copied_names) == 4
    assert {Path(name).suffix for name in copied_names} == {".pdf", ".docx", ".odt", ".rtf"}
    for name in copied_names:
        assert name.startswith("Student_0001__document_")
        assert "Ana Novak" not in name

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Opaque document inclusion was explicitly enabled" in report
    assert "internal content and metadata were not inspected or redacted" in report
    assert "Student_0001__document_" in report
    assert "Excluded opaque documents: none" in report

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    copied_names = sorted(path.name for path in workspace.iterdir() if path.suffix in {".pdf", ".docx", ".odt", ".rtf"})
    assert rows[0]["associated_txt_files"] == "Student_0001.txt"
    assert rows[0]["associated_document_files"] == ";".join(copied_names)
    assert rows[0]["all_associated_files"] == ";".join(["Student_0001.txt", *copied_names])
    assert rows[0]["status"] == "matched"
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in (workspace / "associations.csv").read_text(encoding="utf-8")


def test_prepare_preserves_pdf_task_file_type_without_including_student_pdfs(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path, task_suffix=".pdf")

    assert result.returncode == 0, result.stderr
    assert (workspace / "task.pdf").read_bytes() == b"%PDF-1.4 synthetic assignment\n"
    assert not (workspace / "task.tex").exists()

    workspace_pdfs = sorted(path.name for path in workspace.glob("*.pdf"))
    assert workspace_pdfs == ["task.pdf"]
    assert not list(workspace.glob("*.docx"))
    assert not list(workspace.glob("*.odt"))
    assert not list(workspace.glob("*.rtf"))

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["associated_txt_files"] == "Student_0001.txt"
    assert rows[0]["associated_document_files"] == ""
    assert rows[0]["all_associated_files"] == "Student_0001.txt"

    associations_text = (workspace / "associations.csv").read_text(encoding="utf-8")
    assert "task.pdf" not in associations_text
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in associations_text

    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "task.*" in agents_text
    assert "task.pdf" in agents_text
    assert "read it as PDF" in agents_text
    assert "task.tex` contains the assignment" not in agents_text

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Ana Novak report.pdf" in report
    assert "excluded from the workspace by default" in report


def test_messy_prepare_default_mode_end_to_end_audit(tmp_path: Path) -> None:
    workspace, private_output, result = run_messy_prepare(tmp_path)
    tree = relative_workspace_tree(workspace)

    assert result.returncode == 0, result.stderr
    assert (workspace / "AGENTS.md").exists(), tree
    assert (workspace / "students.csv").exists(), tree
    assert (workspace / "associations.csv").exists(), tree
    assert (workspace / "task.tex").read_text(encoding="utf-8").startswith("\\section{Synthetic Messy Assignment}"), tree
    assert not (workspace / "task.pdf").exists(), tree
    assert (workspace / "report_template.json").exists(), tree
    assert (workspace / "process.sh").exists(), tree
    assert not (workspace / ".slaif_prompts").exists(), tree

    assert (workspace / "students.csv").read_text(encoding="utf-8") == (
        "name,surname,full_name\n"
        "Student,0001,Student 0001\n"
        "Student,0002,Student 0002\n"
        "Student,0003,Student 0003\n"
        "Student,0004,Student 0004\n"
        "Student,0005,Student 0005\n"
    )

    process_sh = workspace / "process.sh"
    process_text = process_sh.read_text(encoding="utf-8")
    assert process_sh.stat().st_mode & stat.S_IXUSR
    assert "Phase 1" not in process_text
    assert "cat .slaif_prompts" not in process_text
    assert process_text.count("Run submission assessment for Student ") == 3
    assert 'run_planned_student "Student 0001" resolved' in process_text
    assert 'run_planned_student "Student 0002" resolved' in process_text
    assert 'run_planned_student "Student 0003" unresolved' in process_text
    assert 'run_planned_student "Student 0004" resolved' in process_text
    assert 'run_planned_student "Student 0005" unresolved' in process_text
    assert process_text.index("Run submission assessment for Student 0001") < process_text.index(
        "Run submission assessment for Student 0002"
    )
    assert process_text.index("Run submission assessment for Student 0002") < process_text.index(
        "Run submission assessment for Student 0004"
    )

    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_text == (REPO_ROOT / "templates" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    assert "students.csv" in agents_text
    assert "associations.csv" in agents_text
    assert "task.*" in agents_text
    assert "task.pdf" in agents_text
    assert "report_template.json" in agents_text
    assert "The only student submission files are the files listed in `associations.csv`." in agents_text
    assert "<Full Name>/report.json" in agents_text
    assert "Do not infer, request, or reconstruct real student identities." in agents_text
    assert "Do not accuse AI use" in agents_text
    assert "Do not redo preprocessing" in agents_text
    assert "Run Phase 1" not in agents_text
    assert "Build associations" not in agents_text

    template_text = (workspace / "report_template.json").read_text(encoding="utf-8")
    template_schema = json.loads(template_text)
    assert "code_copy_indications" in template_schema
    assert "other_student_pseudonym" in template_schema["code_copy_indications"][0]
    for value in MESSY_FORBIDDEN_IDENTIFIERS:
        assert value not in template_text

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ASSOCIATION_COLUMNS
    assert [row["full_name"] for row in rows] == [
        "Student 0001",
        "Student 0002",
        "Student 0003",
        "Student 0004",
        "Student 0005",
    ]
    assert [row["status"] for row in rows] == ["matched", "matched", "unresolved", "matched", "unresolved"]
    assert rows[0]["associated_txt_files"] == "Student_0001.txt"
    assert rows[1]["associated_txt_files"] == "Student_0002.txt"
    assert rows[2]["all_associated_files"] == ""
    assert rows[3]["associated_txt_files"] == "Student_0004.txt"
    assert rows[4]["all_associated_files"] == ""
    assert all(row["associated_document_files"] == "" for row in rows)
    assert all("Mila Kranjc report.pdf" not in row["all_associated_files"] for row in rows)

    assert (workspace / "Student_0001.txt").exists(), tree
    assert (workspace / "Student_0002.txt").exists(), tree
    assert not (workspace / "Student_0003.txt").exists(), tree
    assert (workspace / "Student_0004.txt").exists(), tree
    assert not (workspace / "Student_0005.txt").exists(), tree
    assert not list(workspace.glob("*.pdf")), tree
    assert not any("Unlisted" in path.name for path in workspace.rglob("*")), tree

    student_0001 = (workspace / "Student_0001.txt").read_text(encoding="utf-8")
    assert "notebooks/analysis.ipynb" in student_0001
    assert "Student 0001" in student_0001
    assert "Mila Kranjc" not in student_0001
    assert "mila.kranjc@example.invalid" not in student_0001
    assert "SID-0001" not in student_0001

    student_0004 = (workspace / "Student_0004.txt").read_text(encoding="utf-8")
    assert "Student 0004 analiza final.tex" in student_0004
    assert "čuden file name s presledki.py" in student_0004
    assert "Taj Černe" not in student_0004
    assert "taj.cerne@example.invalid" not in student_0004
    assert "SID-0004" not in student_0004

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Roster students: 5" in report
    assert "Matched students: 3" in report
    assert "Students without submissions: 2" in report
    assert "Unlisted Person_999_assignsubmission_file" in report
    assert "Mila Kranjc_100_assignsubmission_file/" in report
    assert "Mila Kranjc report.pdf" in report
    assert "excluded from the workspace by default" in report
    assert "Original matched LMS folder: `Mila Kranjc_100_assignsubmission_file`" in report
    assert "Original matched LMS folder: `Luka Horvat_200_assignsubmission_file`" in report
    assert "Original matched LMS folder: `Taj Černe_400_assignsubmission_file`" in report
    assert "Student-visible concatenated outputs were written to `student_outputs/`" in report

    student_outputs = private_output / "student_outputs"
    assert sorted(path.name for path in student_outputs.glob("*.txt")) == [
        "Student_0001.txt",
        "Student_0002.txt",
        "Student_0004.txt",
    ]
    assert (student_outputs / "Student_0001.txt").read_text(encoding="utf-8") == (workspace / "Student_0001.txt").read_text(
        encoding="utf-8"
    )
    assert not (student_outputs / "Student_0003.txt").exists()
    assert not (student_outputs / "Student_0005.txt").exists()

    with (private_output / "student_outputs_index.csv").open("r", encoding="utf-8", newline="") as f:
        output_index_rows = list(csv.DictReader(f))
    assert [row["pseudonym"] for row in output_index_rows] == ["Student 0001", "Student 0002", "Student 0004"]
    assert output_index_rows[0]["name"] == "Mila"
    assert output_index_rows[0]["surname"] == "Kranjc"
    assert output_index_rows[0]["full_name"] == "Mila Kranjc"
    assert output_index_rows[0]["email"] == "mila.kranjc@example.invalid"
    assert output_index_rows[0]["student_id"] == "SID-0001"
    assert output_index_rows[0]["student_output_file"] == "Student_0001.txt"

    for output_file in student_outputs.glob("*.txt"):
        output_text = output_file.read_text(encoding="utf-8")
        for value in MESSY_FORBIDDEN_IDENTIFIERS:
            assert value not in output_text, f"{value!r} leaked in private student output {output_file.name!r}"

    for path in workspace.rglob("*"):
        rel = path.relative_to(workspace).as_posix()
        for value in MESSY_FORBIDDEN_IDENTIFIERS:
            assert value not in rel, f"{value!r} leaked in workspace path {rel!r}\n{tree}"
        if path.is_file() and path.suffix.lower() in {
            ".txt",
            ".csv",
            ".sh",
            ".tex",
            ".md",
            ".py",
            ".m",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".ipynb",
        }:
            text = path.read_text(encoding="utf-8")
            for value in MESSY_FORBIDDEN_IDENTIFIERS:
                assert value not in text, f"{value!r} leaked in workspace file {rel!r}\n{tree}"


def test_messy_prepare_opt_in_opaque_documents_are_pseudonymized(tmp_path: Path) -> None:
    workspace, private_output, result = run_messy_prepare(tmp_path, include_opaque_documents=True)
    tree = relative_workspace_tree(workspace)

    assert result.returncode == 0, result.stderr
    copied_documents = sorted(path.name for path in workspace.iterdir() if path.suffix.lower() in {".pdf", ".docx"})
    assert copied_documents == ["Student_0001__document_001.pdf"], tree
    assert "Mila Kranjc" not in copied_documents[0]

    with (workspace / "associations.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["associated_document_files"] == "Student_0001__document_001.pdf"
    assert rows[0]["all_associated_files"] == "Student_0001.txt;Student_0001__document_001.pdf"
    assert rows[1]["associated_document_files"] == ""

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Opaque document inclusion was explicitly enabled" in report
    assert "internal content and metadata were not inspected or redacted" in report
    assert "Student_0001__document_001.pdf" in report

    workspace_text = (workspace / "associations.csv").read_text(encoding="utf-8") + "\n" + (workspace / "process.sh").read_text(
        encoding="utf-8"
    )
    for value in MESSY_FORBIDDEN_IDENTIFIERS:
        assert value not in workspace_text


def test_workspace_generated_text_and_filenames_do_not_contain_real_identifiers(tmp_path: Path) -> None:
    workspace, _private_output, result = run_prepare(tmp_path)

    assert result.returncode == 0, result.stderr
    for path in workspace.rglob("*"):
        rel = path.relative_to(workspace).as_posix()
        for value in FORBIDDEN_IDENTIFIERS:
            assert value not in rel
        if path.is_file() and path.suffix in {".txt", ".csv", ".sh", ".tex", ".md", ".py", ".m", ".c", ".h", ".cpp", ".hpp", ".ipynb"}:
            text = path.read_text(encoding="utf-8")
            for value in FORBIDDEN_IDENTIFIERS:
                assert value not in text

def test_pdf_report_renders_with_core_fonts(tmp_path: Path, monkeypatch) -> None:
    import slaif_defense_grading.pdf_report as pdf_report

    monkeypatch.setattr(pdf_report, "find_font_pair", lambda: None)
    report = {
        "pseudonym": "Student 0001",
        "assignment_submitted": True,
        "all_tasks_implemented": False,
        "task_details": [
            {"task": "compute edit distance", "implemented": True, "evidence": "main.py lines 1-9"},
            {"task": "report the results", "implemented": False, "evidence": "not present"},
        ],
        "looks_llm_generated": "likely",
        "llm_generation_indicators": ["uniform comment style in main.py lines 1-9"],
        "code_copy_indications": [
            {
                "other_student_pseudonym": "Student 0002",
                "this_file": "main.py",
                "this_lines": "12-34",
                "other_file": "sol.py",
                "other_lines": "3-11",
                "evidence": "identical helper structure",
            }
        ],
        "notes": "Brez posebnih opomb.",
    }
    output_path = pdf_report.render_assessment_pdf(
        report, "Ana Novak", "Student 0001", {"Student 0002": "Boris Kovac"}, tmp_path / "report.pdf"
    )
    pdf_bytes = output_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes[-32:]
    assert b"Ana Novak" in pdf_bytes
    assert b"Boris Kovac" in pdf_bytes
    assert b"1. Was the assignment submitted?" in pdf_bytes
    assert b"2. Are all the tasks implemented?" in pdf_bytes
    assert b"3. Does the code look LLM-generated?" in pdf_bytes
    assert b"4. Indications of copying code from another student?" in pdf_bytes
    assert b"lines 12-34" in pdf_bytes
    assert b"lines 3-11" in pdf_bytes
    assert b"not a finding of misconduct" not in pdf_bytes or b"does not prove" in pdf_bytes

    final_output = pdf_report.render_final_report_pdf(
        [
            {
                "full_name": "Ana Novak",
                "all_tasks_implemented": "Yes",
                "copying_indications": "No",
                "llm_indications": "Uncertain",
                "notes": "None.",
            }
        ],
        tmp_path / "final_report.pdf",
        processing_stats={
            "run_status": "completed",
            "planned_students": 1,
            "processed_students": 1,
            "successful_students": 1,
            "failed_students": 0,
            "total_time_seconds": 12,
            "average_time_seconds": 12.0,
            "students": [{"pseudonym": "Student 0001", "duration_seconds": 12, "exit_code": 0}],
        },
        student_names={"Student 0001": "Ana Novak"},
    )
    final_pdf_bytes = final_output.read_bytes()
    assert b"Processing Statistics" in final_pdf_bytes
    assert b"Total elapsed time: 12 seconds" in final_pdf_bytes
    assert b"Average time per processed student: 12 seconds" in final_pdf_bytes
    # Newer fpdf2 releases escape parentheses in text show operators.
    assert b"Ana Novak (Student 0001)" in final_pdf_bytes or (
        b"Ana Novak \\(Student 0001\\)" in final_pdf_bytes
    )
