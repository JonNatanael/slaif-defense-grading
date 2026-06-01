from __future__ import annotations

import csv
import stat
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


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


def run_prepare(tmp_path: Path, include_opaque_documents: bool = False) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    students_csv = tmp_path / "students.csv"
    task_file = tmp_path / "task.tex"
    input_zip = tmp_path / "moodle_export.zip"
    workspace = tmp_path / "workspace" / "lab-agent"
    private_output = tmp_path / "workspace" / "lab-private"

    write_text(
        students_csv,
        "name,surname,email,student_id\n"
        "Ana,Novak,ana.novak@example.invalid,63240001\n"
        "Boris,Kovac,boris.kovac@example.invalid,63240002\n",
    )
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
    assert "--private-output" in result.stdout
    assert "--include-opaque-documents" in result.stdout


def test_prepare_creates_pseudonymized_workspace_and_private_outputs(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (workspace / "students.csv").read_text(encoding="utf-8") == (
        "name,surname,full_name\n"
        "Student,0001,Student 0001\n"
        "Student,0002,Student 0002\n"
    )
    assert (workspace / "task.tex").read_text(encoding="utf-8") == "\\section{Synthetic Task}\n"

    process_sh = workspace / "process.sh"
    process_text = process_sh.read_text(encoding="utf-8")
    assert process_sh.stat().st_mode & stat.S_IXUSR
    assert '"Phase 1"' in process_text
    assert process_text.index("Phase 2 Student 0001") < process_text.index("Phase 2 Student 0002")
    assert "Ana Novak" not in process_text
    assert "Boris Kovac" not in process_text

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


def test_workspace_generated_text_and_filenames_do_not_contain_real_identifiers(tmp_path: Path) -> None:
    workspace, _private_output, result = run_prepare(tmp_path)

    assert result.returncode == 0, result.stderr
    forbidden = [
        "Ana Novak",
        "Boris Kovac",
        "ana.novak@example.invalid",
        "boris.kovac@example.invalid",
        "63240001",
        "63240002",
    ]
    for path in workspace.rglob("*"):
        rel = path.relative_to(workspace).as_posix()
        for value in forbidden:
            assert value not in rel
        if path.is_file() and path.suffix in {".txt", ".csv", ".sh", ".tex", ".md", ".py", ".m", ".c", ".h", ".cpp", ".hpp", ".ipynb"}:
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                assert value not in text
