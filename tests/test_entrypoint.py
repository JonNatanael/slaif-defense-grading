from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_canonical_entrypoint_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "slaif-defense-grading.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "slaif-defense-grading.py" in result.stdout
    assert "prepare" in result.stdout
    assert "finalize" in result.stdout
    assert "legacy" not in result.stdout


def test_old_direct_invocation_no_longer_works() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "--input-file",
            "moodle_export.zip",
            "--output-file",
            "combined.txt",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr or "usage:" in result.stderr


def test_legacy_subcommand_no_longer_works() -> None:
    result = subprocess.run(
        [sys.executable, "slaif-defense-grading.py", "legacy", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_activation_script_runs_complete_workflow_with_only_profile_and_assignment_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_UZ"
    assignment_dir = data_dir / "assignment_1"
    assignment_dir.mkdir(parents=True)
    (data_dir / "students_UZ.csv").write_bytes(
        (
            "Artificial intelligence - student list\r\n"
            "Vpisna številka\tPriimek, Ime\tE-mail\r\n"
            "123\tNovak, Ana\tana@example.invalid\r\n"
        ).encode("utf-16")
    )
    (assignment_dir / "instructions.pdf").write_bytes(b"synthetic assignment")

    # Use a minimal Moodle-style export whose folder can be matched to the
    # synthetic roster. The fake Codex command writes a valid report.json.
    import zipfile

    with zipfile.ZipFile(assignment_dir / "submissions.zip", "w") as archive:
        archive.writestr("Ana Novak_123_assignsubmission_file/main.py", "print('hello')\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "student=${!#}\n"
        "student=${student#Run submission assessment for }\n"
        "mkdir -p \"$student\"\n"
        "printf '%s\\n' '{\"pseudonym\": \"Student 0001\", \"assignment_submitted\": true, \"all_tasks_implemented\": true, \"task_details\": [], \"looks_llm_generated\": \"uncertain\", \"llm_generation_indicators\": [], \"code_copy_indications\": [], \"notes\": \"\"}' > \"$student/report.json\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_codex.chmod(0o755)

    result = subprocess.run(
        [str(REPO_ROOT / "activate_assignment.sh"), "test-profile", str(assignment_dir)],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    runs = list((assignment_dir / ".slaif-defense-grading" / "runs").iterdir())
    assert len(runs) == 1
    run = runs[0]
    assert (run / "private" / "students_normalized.csv").read_text(encoding="utf-8").startswith("name,surname,email,student_id\n")
    assert (run / "agent-workspace" / "processing_stats.json").exists()
    assert (run / "private" / "pseudonym_map.csv").exists()
    assert (run / "final" / "final_report.csv").exists()
    assert (run / "final" / "finalize_report.md").exists()


def test_activation_script_honors_student_order_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_UZ"
    assignment_dir = data_dir / "assignment_1"
    assignment_dir.mkdir(parents=True)
    (data_dir / "students_UZ.csv").write_bytes(
        (
            "Artificial intelligence - student list\r\n"
            "Vpisna številka\tPriimek, Ime\tE-mail\r\n"
            "10000001\tAlpha, Alice\taal@example.invalid\r\n"
            "10000002\tBeta, Bob\tbb@example.invalid\r\n"
        ).encode("utf-16")
    )
    # Alternative order: Bob (10000002) first; unlisted Alice keeps roster order.
    (data_dir / "student_order.txt").write_bytes(b"10000002\r\n")
    (assignment_dir / "instructions.pdf").write_bytes(b"synthetic assignment")

    # Use a minimal Moodle-style export whose folders can be matched to the
    # synthetic roster. The fake Codex command writes a valid report.json for
    # the pseudonym it was invoked for.
    import zipfile

    with zipfile.ZipFile(assignment_dir / "submissions.zip", "w") as archive:
        archive.writestr("Alice Alpha_10000001_assignsubmission_file/main.py", "print('hello')\n")
        archive.writestr("Bob Beta_10000002_assignsubmission_file/main.py", "print('hello')\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "pseudonym=${!#}\n"
        "pseudonym=${pseudonym#Run submission assessment for }\n"
        "mkdir -p \"$pseudonym\"\n"
        "printf '%s\\n' \"{\\\"pseudonym\\\": \\\"$pseudonym\\\", \\\"assignment_submitted\\\": true, \\\"all_tasks_implemented\\\": true, \\\"task_details\\\": [], \\\"looks_llm_generated\\\": \\\"uncertain\\\", \\\"llm_generation_indicators\\\": [], \\\"code_copy_indications\\\": [], \\\"notes\\\": \\\"\\\"}\" > \"$pseudonym/report.json\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_codex.chmod(0o755)

    result = subprocess.run(
        [str(REPO_ROOT / "activate_assignment.sh"), "test-profile", str(assignment_dir)],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Student order" in result.stderr

    run = next(iter((assignment_dir / ".slaif-defense-grading" / "runs").iterdir()))
    map_lines = (run / "private" / "pseudonym_map.csv").read_text(encoding="utf-8").splitlines()
    assert map_lines[1].startswith("Student 0001,Bob,Beta")
    assert map_lines[1].endswith(",10000002")
    assert map_lines[2].startswith("Student 0002,Alice,Alpha")
    assert map_lines[2].endswith(",10000001")
    assert (run / "final" / "final_report.csv").exists()


def test_roster_normalizer_accepts_utf16_lms_export(tmp_path: Path) -> None:
    from slaif_defense_grading.roster_normalize import normalize_roster

    source = tmp_path / "students_UZ.csv"
    source.write_bytes(
        (
            "Artificial intelligence - student list\r\n"
            "Vpisna številka\tPriimek, Ime\tE-mail\tLetnik\r\n"
            "10000002\tBeta, Bob\tbb@example.invalid\t3\r\n"
        ).encode("utf-16")
    )
    output = tmp_path / "normalized.csv"

    assert normalize_roster(source, output) == 1
    assert output.read_text(encoding="utf-8") == (
        "name,surname,email,student_id\nBob,Beta,bb@example.invalid,10000002\n"
    )
