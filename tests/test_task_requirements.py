"""Part 2 performance work: local assignment extraction and the one-time
shared assignment-requirement analysis.

Only synthetic data is used. PDF fixtures are generated with fpdf2; the fake
`codex` executable (shared with test_process_resume) writes a valid
task_requirements.json for the "Analyze assignment requirements" command and
valid student reports for the student assessment command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Sequence

import pytest

from test_prepare import (
    FORBIDDEN_IDENTIFIERS,
    MESSY_FORBIDDEN_IDENTIFIERS,
    build_synthetic_moodle_zip,
    run_messy_prepare,
    run_prepare,
    write_text,
)
from test_process_resume import (
    MATCHED_PSEUDONYMS,
    UNRESOLVED_PSEUDONYMS,
    install_fake_codex,
    outcomes_by_pseudonym,
    prewrite_report,
    read_log,
    read_stats,
    run_process,
    valid_report_text,
)
from slaif_defense_grading import task_requirements
from slaif_defense_grading.task_extract import (
    WORKSPACE_EXTRACTED_NAME,
    extract_task_text,
    normalize_line_endings,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_REQUIREMENTS_TEMPLATE = (
    '{"schema_version": 1, "requirements": [{"id": "task-001", "description": "%s", '
    '"source_reference": "task_extracted.txt line 1"}], "notes": ""}'
)


def build_pdf(path: Path, lines: Sequence[str]) -> None:
    """Generate a small synthetic PDF; an empty ``lines`` yields a text-less page."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in lines:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def run_prepare_custom_task(
    tmp_path: Path,
    task_file: Path,
    roster_text: str = (
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n"
    ),
    zip_builder=None,
) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    """Like run_prepare, but with a caller-supplied task file (and optional zip)."""
    students_csv = tmp_path / "students.csv"
    write_text(students_csv, roster_text)
    input_zip = tmp_path / "moodle_export.zip"
    if zip_builder is None:
        build_synthetic_moodle_zip(input_zip)
    else:
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


def valid_requirements_text(description: str = "Sentinel requirement reused without regeneration.") -> str:
    return VALID_REQUIREMENTS_TEMPLATE % description + "\n"


# ---------------------------------------------------------------------------
# Local deterministic extraction
# ---------------------------------------------------------------------------


def test_plain_text_extraction_normalizes_endings_and_preserves_canonical(tmp_path: Path) -> None:
    source = tmp_path / "assignment.tex"
    source.write_bytes("\\section{Synthetic Task}\r\nSolve the graph problem.\rCompare variants.\r".encode("utf-8"))
    dest = tmp_path / WORKSPACE_EXTRACTED_NAME

    result = extract_task_text(source, dest)

    assert result.written is True
    assert result.method == "text"
    assert result.warnings == ()
    assert dest.read_text(encoding="utf-8") == (
        "\\section{Synthetic Task}\nSolve the graph problem.\nCompare variants.\n"
    )
    # The canonical source file must remain byte-identical.
    assert source.read_bytes() == b"\\section{Synthetic Task}\r\nSolve the graph problem.\rCompare variants.\r"


def test_normalize_line_endings() -> None:
    assert normalize_line_endings("a\r\nb\rc") == "a\nb\nc\n"
    assert normalize_line_endings("") == ""


def test_extractable_pdf_is_extracted_and_canonical_preserved(tmp_path: Path) -> None:
    task_file = tmp_path / "assignment.pdf"
    build_pdf(
        task_file,
        [
            "Implement a shortest path algorithm for a directed weighted graph.",
            "Compare it against Dijkstra's method on two synthetic graphs.",
        ],
    )
    original_bytes = task_file.read_bytes()

    workspace, private_output, result = run_prepare_custom_task(tmp_path, task_file)
    assert result.returncode == 0, result.stderr

    # Canonical assignment preserved untouched.
    assert (workspace / "task.pdf").read_bytes() == original_bytes
    assert not (workspace / "task.tex").exists()

    extracted = workspace / WORKSPACE_EXTRACTED_NAME
    assert extracted.exists()
    extracted_text = extracted.read_text(encoding="utf-8")
    assert "shortest path algorithm" in extracted_text
    assert "Dijkstra" in extracted_text
    # No private identifiers may leak into the shared extraction artifact.
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in extracted_text

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "## Assignment Extraction" in report
    assert "pdf:pypdf" in report or "pdf:pdftotext" in report
    assert "task_extracted.txt" in report
    assert (workspace / "process.sh").read_text(encoding="utf-8").count("PROCESS_EXTRACTION_WARNINGS=false") == 1


def test_textless_pdf_is_not_extracted_and_warning_recorded(tmp_path: Path) -> None:
    task_file = tmp_path / "assignment.pdf"
    build_pdf(task_file, [])  # one page with no extractable text
    original_bytes = task_file.read_bytes()

    workspace, private_output, result = run_prepare_custom_task(tmp_path, task_file)
    assert result.returncode == 0, result.stderr
    assert "Warning:" in result.stderr

    # No misleading empty artifact; the canonical PDF is retained as fallback.
    assert not (workspace / WORKSPACE_EXTRACTED_NAME).exists()
    assert (workspace / "task.pdf").read_bytes() == original_bytes

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "## Assignment Extraction" in report
    assert "Warning:" in report
    assert "No usable local text extraction" in report
    assert (workspace / "process.sh").read_text(encoding="utf-8").count("PROCESS_EXTRACTION_WARNINGS=true") == 1


def test_preprocessing_report_documents_successful_text_extraction(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path)
    assert result.returncode == 0, result.stderr

    extracted = workspace / WORKSPACE_EXTRACTED_NAME
    assert extracted.exists()
    assert extracted.read_text(encoding="utf-8") == "\\section{Synthetic Task}\n"
    # Canonical task.tex is preserved untouched.
    assert (workspace / "task.tex").read_bytes() == b"\\section{Synthetic Task}\n"

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "## Assignment Extraction" in report
    assert "- Method: text" in report
    assert "preserved untouched" in report


def test_missing_extractor_reports_fallback_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "assignment.pdf"
    build_pdf(source, ["A synthetic assignment whose text is otherwise extractable."])
    dest = tmp_path / WORKSPACE_EXTRACTED_NAME

    # Simulate an environment without pypdf and without pdftotext.
    monkeypatch.setitem(sys.modules, "pypdf", None)
    monkeypatch.setattr("slaif_defense_grading.task_extract.shutil.which", lambda _name: None)

    result = extract_task_text(source, dest)

    assert result.written is False
    assert result.method == "not-extracted"
    assert not dest.exists()
    assert any("No local PDF text extractor is available" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Shared task-requirements schema and validator
# ---------------------------------------------------------------------------


def test_requirements_validator_accepts_valid_documents() -> None:
    data = json.loads(valid_requirements_text())
    assert task_requirements.validate_task_requirements_data(data) == []
    # An empty list is acceptable only with an explanatory note.
    data = {
        "schema_version": 1,
        "requirements": [],
        "notes": "The assignment text could not be identified from the extraction.",
    }
    assert task_requirements.validate_task_requirements_data(data) == []


def test_requirements_validator_rejects_invalid_documents() -> None:
    good = json.loads(valid_requirements_text())

    data = dict(good)
    data["schema_version"] = 2
    assert any("schema_version" in problem for problem in task_requirements.validate_task_requirements_data(data))

    data = json.loads(valid_requirements_text())
    data["requirements"] = [
        {"id": "task-001", "description": "a", "source_reference": "b"},
        {"id": "task-001", "description": "c", "source_reference": "d"},
    ]
    assert any("duplicate id" in problem for problem in task_requirements.validate_task_requirements_data(data))

    data = json.loads(valid_requirements_text())
    data["requirements"][0]["id"] = "   "
    assert any("nonempty string" in problem for problem in task_requirements.validate_task_requirements_data(data))

    data = json.loads(valid_requirements_text())
    del data["requirements"][0]["source_reference"]
    assert any("missing required field(s)" in problem for problem in task_requirements.validate_task_requirements_data(data))

    data = json.loads(valid_requirements_text())
    data["notes"] = 42
    assert any("notes" in problem for problem in task_requirements.validate_task_requirements_data(data))

    data = {"schema_version": 1, "requirements": [], "notes": ""}
    assert any("empty" in problem for problem in task_requirements.validate_task_requirements_data(data))

    assert task_requirements.validate_task_requirements_data("not a dict") == ["must contain a JSON object"]
    assert task_requirements.validate_task_requirements_text("not json")[1]


def test_requirements_validator_cli_exit_codes(tmp_path: Path) -> None:
    valid = tmp_path / "task_requirements.json"
    valid.write_text(valid_requirements_text(), encoding="utf-8", newline="\n")
    assert task_requirements.main([str(valid)]) == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version": 99}', encoding="utf-8", newline="\n")
    assert task_requirements.main([str(invalid)]) == 1
    assert task_requirements.main([]) == 2
    assert task_requirements.main([str(tmp_path / "missing.json")]) == 1


def test_workspace_requirements_validator_is_standalone_and_pseudonym_safe(tmp_path: Path) -> None:
    workspace, _private, result = run_prepare(tmp_path)
    assert result.returncode == 0, result.stderr

    helper = workspace / "task_requirements_validator.py"
    assert helper.exists()
    assert helper.read_text(encoding="utf-8") == (
        REPO_ROOT / "slaif_defense_grading" / "task_requirements.py"
    ).read_text(encoding="utf-8")

    source = helper.read_text(encoding="utf-8")
    assert "from . " not in source and "from .\n" not in source
    assert "import slaif_defense_grading" not in source
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in source


# ---------------------------------------------------------------------------
# process.sh integration with the fake Codex
# ---------------------------------------------------------------------------


def test_missing_requirements_are_generated_exactly_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    assert not (workspace / "task_requirements.json").exists()
    analysis_log = tmp_path / "analysis_invocations.log"
    monkeypatch.setenv("ANALYSIS_LOG", str(analysis_log))

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    # The analysis command runs at most once per run.
    assert read_log(analysis_log) == ["Analyze assignment requirements"]
    assert read_log(log) == MATCHED_PSEUDONYMS

    requirements_path = workspace / "task_requirements.json"
    assert task_requirements.validate_task_requirements_file(requirements_path) == []
    stats = read_stats(workspace)
    assert stats["assignment_analysis"]["outcome"] == "generated"
    assert stats["assignment_analysis"]["exit_code"] == 0
    assert stats["assignment_analysis"]["extraction_warnings"] is False
    assert stats["assignment_analysis"]["duration_seconds"] >= 0
    assert outcomes_by_pseudonym(stats)["Student 0001"] == "agent_success"


def test_valid_requirements_are_reused_without_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    write_text(workspace / "task_requirements.json", valid_requirements_text())
    analysis_log = tmp_path / "analysis_invocations.log"
    monkeypatch.setenv("ANALYSIS_LOG", str(analysis_log))

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert not analysis_log.exists()  # zero analysis agent invocations
    assert read_log(log) == MATCHED_PSEUDONYMS
    # The existing file is reused, not rewritten by the agent.
    assert (workspace / "task_requirements.json").read_text(encoding="utf-8") == valid_requirements_text()
    stats = read_stats(workspace)
    assert stats["assignment_analysis"]["outcome"] == "reused"
    assert stats["assignment_analysis"]["exit_code"] is None


def test_invalid_requirements_are_regenerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    write_text(workspace / "task_requirements.json", '{"schema_version": 1, "requirements": [], "notes": ""}')
    analysis_log = tmp_path / "analysis_invocations.log"
    monkeypatch.setenv("ANALYSIS_LOG", str(analysis_log))

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(analysis_log) == ["Analyze assignment requirements"]
    assert task_requirements.validate_task_requirements_file(workspace / "task_requirements.json") == []
    stats = read_stats(workspace)
    assert stats["assignment_analysis"]["outcome"] == "generated"


def test_failed_analysis_stops_matched_students_and_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    prewrite_report(workspace, "Student 0001", valid_report_text("Student 0001"))
    original_report = (workspace / "Student 0001" / "report.json").read_text(encoding="utf-8")
    monkeypatch.setenv("FAIL_ANALYSIS", "1")

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode != 0
    # No student agent invocation may happen without the shared prerequisite.
    assert read_log(log) == []
    stats = read_stats(workspace)
    assert stats["run_status"] == "failed"
    assert stats["assignment_analysis"]["outcome"] == "failed"
    assert stats["assignment_analysis"]["exit_code"] != 0
    assert outcomes_by_pseudonym(stats) == {
        "Student 0001": "skipped_valid_report",
        "Student 0002": "skipped_prerequisite_failed",
        "Student 0003": "generated_unresolved",
        "Student 0004": "skipped_prerequisite_failed",
        "Student 0005": "generated_unresolved",
    }
    # Already valid reports are preserved; no report is fabricated for the
    # matched students that were not processed.
    assert (workspace / "Student 0001" / "report.json").read_text(encoding="utf-8") == original_report
    for pseudonym in ("Student 0002", "Student 0004"):
        assert not (workspace / pseudonym / "report.json").exists()


def test_invalid_analysis_output_stops_matched_students(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    monkeypatch.setenv("BAD_ANALYSIS", "1")

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode != 0
    assert read_log(log) == []
    assert "missing or invalid" in result.stderr
    stats = read_stats(workspace)
    assert stats["assignment_analysis"]["outcome"] == "failed"
    assert stats["assignment_analysis"]["exit_code"] == 1
    for pseudonym in MATCHED_PSEUDONYMS:
        assert outcomes_by_pseudonym(stats)[pseudonym] == "skipped_prerequisite_failed"


def test_fully_resumed_run_skips_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    analysis_log = tmp_path / "analysis_invocations.log"
    monkeypatch.setenv("ANALYSIS_LOG", str(analysis_log))

    first = run_process(tmp_path, workspace, fake_bin, log)
    assert first.returncode == 0, first.stderr
    assert read_log(analysis_log) == ["Analyze assignment requirements"]

    second = run_process(tmp_path, workspace, fake_bin, log)
    assert second.returncode == 0, second.stderr
    stats = read_stats(workspace)
    assert stats["run_status"] == "completed"
    # Every student already has a valid report, so neither the assignment
    # analysis nor any student agent is invoked again.
    assert stats["assignment_analysis"]["outcome"] == "skipped"
    assert stats["assignment_analysis"]["exit_code"] is None
    assert set(outcomes_by_pseudonym(stats).values()) == {"skipped_valid_report"}


def test_force_regenerates_requirements_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    analysis_log = tmp_path / "analysis_invocations.log"
    monkeypatch.setenv("ANALYSIS_LOG", str(analysis_log))

    first = run_process(tmp_path, workspace, fake_bin, log)
    assert first.returncode == 0, first.stderr
    reused_sentinel = "FORCE_SENTINEL"
    write_text(workspace / "task_requirements.json", valid_requirements_text(reused_sentinel))

    result = run_process(tmp_path, workspace, fake_bin, log, args=["--force"])

    assert result.returncode == 0, result.stderr
    # --force regenerates the shared requirements file even though a valid one
    # exists, and re-runs every matched student.
    assert read_log(analysis_log) == ["Analyze assignment requirements", "Analyze assignment requirements"]
    assert read_log(log) == MATCHED_PSEUDONYMS
    assert reused_sentinel not in (workspace / "task_requirements.json").read_text(encoding="utf-8")
    stats = read_stats(workspace)
    assert stats["assignment_analysis"]["outcome"] == "generated"
    assert outcomes_by_pseudonym(stats)["Student 0001"] == "agent_success"


def test_unresolved_only_run_never_invokes_any_agent(tmp_path: Path) -> None:
    # A failing fake codex that records every invocation: the run must still
    # succeed, proving that no agent invocation (analysis or student) happens.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex = fake_bin / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"${!#}\" >> \"$CODEX_LOG\"\n"
        "exit 1\n",
        encoding="utf-8",
        newline="\n",
    )
    codex.chmod(0o755)
    invocation_log = tmp_path / "codex_calls.log"

    def only_unmatched_zip(path: Path) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Unmatched Q_777_assignsubmission_file/main.py", "print('hello')\n")

    task_file = tmp_path / "assignment.tex"
    write_text(task_file, "\\section{Synthetic Task}\n")
    workspace, _private, result = run_prepare_custom_task(
        tmp_path,
        task_file,
        roster_text="name,surname,email,student_id\nZed,Quill,zed.quill@example.invalid,77000001\n",
        zip_builder=only_unmatched_zip,
    )
    assert result.returncode == 0, result.stderr

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CODEX_LOG": str(invocation_log),
    }
    proc = subprocess.run(["bash", "process.sh"], cwd=workspace, env=env, capture_output=True, text=True, check=False)

    assert proc.returncode == 0, proc.stderr
    assert not invocation_log.exists() or invocation_log.read_text(encoding="utf-8").strip() == ""
    stats = json.loads((workspace / "processing_stats.json").read_text(encoding="utf-8"))
    assert stats["assignment_analysis"]["outcome"] == "skipped"
    assert stats["assignment_analysis"]["exit_code"] is None
    assert stats["run_status"] == "completed"
    assert stats["students"][0]["outcome"] == "generated_unresolved"


def test_shared_artifacts_contain_no_private_identifiers(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    result = run_process(tmp_path, workspace, fake_bin, log)
    assert result.returncode == 0, result.stderr

    for artifact in (WORKSPACE_EXTRACTED_NAME, "task_requirements.json"):
        text = (workspace / artifact).read_text(encoding="utf-8")
        for value in MESSY_FORBIDDEN_IDENTIFIERS:
            assert value not in text, f"{value!r} leaked in {artifact!r}"


def test_workspace_instructions_and_process_script_use_shared_artifacts(tmp_path: Path) -> None:
    workspace, _private, result = run_prepare(tmp_path)
    assert result.returncode == 0, result.stderr

    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    for needle in (
        "Analyze assignment requirements",
        "task_extracted.txt",
        "task_requirements.json",
        "task_requirements_validator.py",
        "schema_version",
        "source_reference",
        "Do not inspect, read, or reference any student submission files",
        "use `task_requirements.json` as the normal source".replace("use ", "Use "),
    ):
        assert needle in agents_text, needle

    process_text = (workspace / "process.sh").read_text(encoding="utf-8")
    assert process_text.count('"Analyze assignment requirements"') == 1
    assert 'ASSIGNMENT_REQUIREMENTS_FILE="task_requirements.json"' in process_text
    assert "run_assignment_analysis" in process_text
    assert process_text.index("run_assignment_analysis") < process_text.index("run_planned_student \"Student 0001\"")
    assert (workspace / "task_requirements_validator.py").exists()


def test_finalize_accepts_part_two_statistics(tmp_path: Path) -> None:
    workspace, private_output, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    result = run_process(tmp_path, workspace, fake_bin, log)
    assert result.returncode == 0, result.stderr

    output = tmp_path / "final"
    finalize = subprocess.run(
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
            "--strict",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finalize.returncode == 0, finalize.stderr

    finalize_report = (output / "finalize_report.md").read_text(encoding="utf-8")
    assert "Assignment analysis (one-time shared prerequisite): generated" in finalize_report
    assert "extraction warnings: no" in finalize_report
    # The workspace must remain untouched by finalize.
    assert (workspace / "task_requirements.json").exists()
