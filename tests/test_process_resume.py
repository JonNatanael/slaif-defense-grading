"""Part 1 performance work: resumable process.sh, local unresolved reports,
shared report validation, processing statistics v2, and wrapper effort passthrough.

Only synthetic data is used. The fake `codex` executable handles the
one-time "Analyze assignment requirements" command by writing a valid
task_requirements.json (unless $FAIL_ANALYSIS makes it exit nonzero or
$BAD_ANALYSIS makes it write invalid JSON). For student assessment commands
it records the invocation (to $CODEX_LOG) and writes a structurally valid
report for the target pseudonym unless its name is listed in $FAIL_FOR.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Sequence

import pytest

from test_prepare import (
    MESSY_FORBIDDEN_IDENTIFIERS,
    FORBIDDEN_IDENTIFIERS,
    run_messy_prepare,
    write_text,
)
from slaif_defense_grading import report_validation

REPO_ROOT = Path(__file__).resolve().parent.parent

MATCHED_PSEUDONYMS = ["Student 0001", "Student 0002", "Student 0004"]
UNRESOLVED_PSEUDONYMS = ["Student 0003", "Student 0005"]


def install_fake_codex(tmp_path: Path) -> tuple[Path, Path]:
    """Install a fake codex executable; returns (fake_bin, invocation_log)."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    log = tmp_path / "codex_invocations.log"
    codex = fake_bin / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        "prompt=${!#}\n"
        "case \"$prompt\" in\n"
        "  \"Analyze assignment requirements\")\n"
        "    if [[ -n \"${ANALYSIS_LOG:-}\" ]]; then printf '%s\\n' \"Analyze assignment requirements\" >> \"$ANALYSIS_LOG\"; fi\n"
        "    if [[ -n \"${FAIL_ANALYSIS:-}\" ]]; then exit 1; fi\n"
        "    if [[ -n \"${BAD_ANALYSIS:-}\" ]]; then printf 'not valid json\\n' > task_requirements.json; exit 0; fi\n"
        "    printf '%s\\n' '{\"schema_version\": 1, \"requirements\": [{\"id\": \"task-001\", \"description\": \"Implement the synthetic task by the behavior it asks for.\", \"source_reference\": \"task_extracted.txt line 1\"}], \"notes\": \"\"}' > task_requirements.json\n"
        "    exit 0 ;;\n"
        "esac\n"
        "student=${prompt#Run submission assessment for }\n"
        "printf '%s\\n' \"$student\" >> \"$CODEX_LOG\"\n"
        "case \" $FAIL_FOR \" in\n"
        "  *\" $student \"*) exit 1 ;;\n"
        "esac\n"
        "mkdir -p \"$student\"\n"
        "printf '%s\\n' \"{\\\"pseudonym\\\": \\\"$student\\\", \\\"assignment_submitted\\\": true, \\\"all_tasks_implemented\\\": true, \\\"task_details\\\": [], \\\"looks_llm_generated\\\": \\\"uncertain\\\", \\\"llm_generation_indicators\\\": [], \\\"code_copy_indications\\\": [], \\\"notes\\\": \\\"\\\"}\" > \"$student/report.json\"\n",
        encoding="utf-8",
        newline="\n",
    )
    codex.chmod(0o755)
    return fake_bin, log


def valid_report_text(pseudonym: str) -> str:
    return (
        json.dumps(
            {
                "pseudonym": pseudonym,
                "assignment_submitted": True,
                "all_tasks_implemented": True,
                "task_details": [],
                "looks_llm_generated": "uncertain",
                "llm_generation_indicators": [],
                "code_copy_indications": [],
                "notes": "",
            },
            indent=2,
        )
        + "\n"
    )


def neutral_report_text(pseudonym: str) -> str:
    return (
        json.dumps(report_validation.build_unresolved_report(pseudonym), indent=2, ensure_ascii=False)
        + "\n"
    )


def prewrite_report(workspace: Path, pseudonym: str, text: str) -> None:
    write_text(workspace / pseudonym / "report.json", text)


def run_process(
    tmp_path: Path,
    workspace: Path,
    fake_bin: Path,
    log: Path,
    fail_for: Sequence[str] = (),
    args: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CODEX_LOG": str(log),
        "FAIL_FOR": " ".join(fail_for),
    }
    return subprocess.run(
        ["bash", "process.sh", *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def read_stats(workspace: Path) -> dict:
    return json.loads((workspace / "processing_stats.json").read_text(encoding="utf-8"))


def outcomes_by_pseudonym(stats: dict) -> dict:
    return {row["pseudonym"]: row["outcome"] for row in stats["students"]}


def read_log(log: Path) -> List[str]:
    if not log.exists():
        return []
    return [line.strip() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Resume behavior for matched students
# ---------------------------------------------------------------------------


def test_valid_report_results_in_no_codex_invocation(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    prewrite_report(workspace, "Student 0001", valid_report_text("Student 0001"))
    original = (workspace / "Student 0001" / "report.json").read_text(encoding="utf-8")

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(log) == ["Student 0002", "Student 0004"]
    assert (workspace / "Student 0001" / "report.json").read_text(encoding="utf-8") == original
    stats = read_stats(workspace)
    assert stats["schema_version"] == 2
    assert stats["run_status"] == "completed"
    assert outcomes_by_pseudonym(stats) == {
        "Student 0001": "skipped_valid_report",
        "Student 0002": "agent_success",
        "Student 0003": "generated_unresolved",
        "Student 0004": "agent_success",
        "Student 0005": "generated_unresolved",
    }
    assert stats["skipped_students"] == 1
    assert stats["successful_students"] == 2
    assert stats["generated_unresolved_students"] == 2
    assert stats["failed_students"] == 0


def test_malformed_report_is_reprocessed(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    prewrite_report(workspace, "Student 0001", "{not valid json")

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(log) == ["Student 0001", "Student 0002", "Student 0004"]
    report = json.loads((workspace / "Student 0001" / "report.json").read_text(encoding="utf-8"))
    assert report["pseudonym"] == "Student 0001"
    stats = read_stats(workspace)
    assert outcomes_by_pseudonym(stats)["Student 0001"] == "agent_success"
    assert report_validation.validate_report_file(
        workspace / "Student 0001" / "report.json", "Student 0001"
    ) == []


def test_structurally_invalid_report_is_reprocessed(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    bad = json.loads(valid_report_text("Student 0001"))
    bad["looks_llm_generated"] = "maybe"
    bad["task_details"] = [{"task": "do the thing"}]  # missing implemented/evidence
    prewrite_report(workspace, "Student 0001", json.dumps(bad))

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(log) == ["Student 0001", "Student 0002", "Student 0004"]
    report = json.loads((workspace / "Student 0001" / "report.json").read_text(encoding="utf-8"))
    assert report["looks_llm_generated"] == "uncertain"
    assert report["pseudonym"] == "Student 0001"


def test_wrong_pseudonym_report_is_reprocessed(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    # A fully valid report, but for a different pseudonym.
    prewrite_report(workspace, "Student 0001", valid_report_text("Student 0002"))

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(log) == ["Student 0001", "Student 0002", "Student 0004"]
    report = json.loads((workspace / "Student 0001" / "report.json").read_text(encoding="utf-8"))
    assert report["pseudonym"] == "Student 0001"


def test_force_reprocesses_valid_matched_reports_but_never_invokes_codex_for_unresolved(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    for pseudonym in MATCHED_PSEUDONYMS:
        prewrite_report(workspace, pseudonym, valid_report_text(pseudonym))
    for pseudonym in UNRESOLVED_PSEUDONYMS:
        prewrite_report(workspace, pseudonym, neutral_report_text(pseudonym))

    result = run_process(tmp_path, workspace, fake_bin, log, args=["--force"])

    assert result.returncode == 0, result.stderr
    # --force regenerates every matched report through the agent, but still
    # never invokes Codex for unresolved students.
    assert read_log(log) == MATCHED_PSEUDONYMS
    stats = read_stats(workspace)
    assert outcomes_by_pseudonym(stats) == {
        "Student 0001": "agent_success",
        "Student 0002": "agent_success",
        "Student 0003": "generated_unresolved",
        "Student 0004": "agent_success",
        "Student 0005": "generated_unresolved",
    }
    assert stats["skipped_students"] == 0
    for pseudonym in UNRESOLVED_PSEUDONYMS:
        report = json.loads((workspace / pseudonym / "report.json").read_text(encoding="utf-8"))
        assert report["assignment_submitted"] is False
        assert report["all_tasks_implemented"] == "unknown"


def test_rerun_makes_zero_codex_calls_for_valid_reports(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)

    first = run_process(tmp_path, workspace, fake_bin, log)
    assert first.returncode == 0, first.stderr
    assert read_log(log) == MATCHED_PSEUDONYMS

    second = run_process(tmp_path, workspace, fake_bin, log)
    assert second.returncode == 0, second.stderr
    assert read_log(log) == []
    stats = read_stats(workspace)
    assert stats["run_status"] == "completed"
    assert stats["processed_students"] == 5
    assert stats["skipped_students"] == 5
    assert stats["successful_students"] == 0
    assert stats["generated_unresolved_students"] == 0
    assert set(outcomes_by_pseudonym(stats).values()) == {"skipped_valid_report"}


# ---------------------------------------------------------------------------
# Failure isolation and exit status
# ---------------------------------------------------------------------------


def test_failed_student_does_not_stop_later_students_and_exit_is_nonzero(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)

    result = run_process(tmp_path, workspace, fake_bin, log, fail_for=["Student 0001"])

    assert result.returncode != 0
    # The first student failed, but the later matched students were still attempted.
    assert read_log(log) == MATCHED_PSEUDONYMS
    stats = read_stats(workspace)
    assert stats["run_status"] == "failed"
    assert outcomes_by_pseudonym(stats) == {
        "Student 0001": "agent_failed",
        "Student 0002": "agent_success",
        "Student 0003": "generated_unresolved",
        "Student 0004": "agent_success",
        "Student 0005": "generated_unresolved",
    }
    assert stats["failed_students"] == 1
    assert stats["successful_students"] == 2
    assert stats["skipped_students"] == 0
    assert stats["generated_unresolved_students"] == 2
    failed_rows = [row for row in stats["students"] if row["pseudonym"] == "Student 0001"]
    assert failed_rows[0]["exit_code"] != 0


def test_stats_distinguish_all_outcomes_in_one_run(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    # One skipped, one failed, one successful, and two locally generated.
    prewrite_report(workspace, "Student 0001", valid_report_text("Student 0001"))

    result = run_process(tmp_path, workspace, fake_bin, log, fail_for=["Student 0002"])

    assert result.returncode != 0
    outcomes = outcomes_by_pseudonym(read_stats(workspace))
    assert set(outcomes.values()) == {"agent_success", "agent_failed", "skipped_valid_report", "generated_unresolved"}
    assert outcomes["Student 0001"] == "skipped_valid_report"
    assert outcomes["Student 0002"] == "agent_failed"
    assert outcomes["Student 0004"] == "agent_success"


def test_statistics_remain_valid_on_failure_path(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)

    result = run_process(tmp_path, workspace, fake_bin, log, fail_for=["Student 0001", "Student 0002"])

    assert result.returncode != 0
    stats = json.loads((workspace / "processing_stats.json").read_text(encoding="utf-8"))
    assert stats["schema_version"] == 2
    assert stats["run_status"] == "failed"
    assert stats["planned_students"] == 5
    assert stats["processed_students"] == 5
    assert stats["ended_at"] is not None
    assert stats["failed_students"] == 2
    assert stats["total_time_seconds"] >= 0
    assert stats["average_time_seconds"] >= 0
    assert len(stats["students"]) == 5
    for row in stats["students"]:
        assert row["outcome"] in {"agent_success", "agent_failed", "skipped_valid_report", "generated_unresolved"}
        assert isinstance(row["duration_seconds"], int)
        assert isinstance(row["exit_code"], int)


# ---------------------------------------------------------------------------
# Unresolved students: deterministic neutral reports, zero Codex calls
# ---------------------------------------------------------------------------


def test_unresolved_students_never_call_codex_and_reports_are_neutral(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)

    result = run_process(tmp_path, workspace, fake_bin, log)

    assert result.returncode == 0, result.stderr
    assert read_log(log) == MATCHED_PSEUDONYMS
    for pseudonym in UNRESOLVED_PSEUDONYMS:
        report = json.loads((workspace / pseudonym / "report.json").read_text(encoding="utf-8"))
        expected = report_validation.build_unresolved_report(pseudonym)
        assert report == expected
    stats = read_stats(workspace)
    assert outcomes_by_pseudonym(stats) == {
        "Student 0001": "agent_success",
        "Student 0002": "agent_success",
        "Student 0003": "generated_unresolved",
        "Student 0004": "agent_success",
        "Student 0005": "generated_unresolved",
    }


def test_unresolved_reports_pass_shared_validation_and_finalize(tmp_path: Path) -> None:
    workspace, private_output, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    result = run_process(tmp_path, workspace, fake_bin, log)
    assert result.returncode == 0, result.stderr

    for pseudonym in UNRESOLVED_PSEUDONYMS:
        assert report_validation.validate_report_file(workspace / pseudonym / "report.json", pseudonym) == []

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
    # Every planned student (agent reports plus locally generated neutral
    # reports) is valid, so strict finalization succeeds.
    assert finalize.returncode == 0, finalize.stderr

    nika_report = output / "instructor_reports" / "Nika_Zupan" / "report.json"
    assert nika_report.exists()
    nika = json.loads(nika_report.read_text(encoding="utf-8"))
    assert nika["assignment_submitted"] is False
    assert nika["all_tasks_implemented"] == "unknown"
    assert nika["looks_llm_generated"] == "uncertain"

    finalize_report = (output / "finalize_report.md").read_text(encoding="utf-8")
    assert "Locally generated unresolved reports (no agent call): 2" in finalize_report
    assert "Skipped students (valid existing report reused, no agent call): 0" in finalize_report
    assert "outcome: generated_unresolved" in finalize_report
    assert "outcome: agent_success" in finalize_report


def test_generated_helper_and_reports_contain_no_private_identifiers(tmp_path: Path) -> None:
    workspace, _private, prepare_result = run_messy_prepare(tmp_path)
    assert prepare_result.returncode == 0, prepare_result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    result = run_process(tmp_path, workspace, fake_bin, log)
    assert result.returncode == 0, result.stderr

    checked = [
        workspace / "report_validator.py",
        workspace / "process.sh",
        workspace / "processing_stats.json",
    ]
    checked.extend(sorted((workspace / "Student 0003").rglob("*")))
    checked.extend(sorted((workspace / "Student 0005").rglob("*")))
    for path in checked:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for value in MESSY_FORBIDDEN_IDENTIFIERS:
            assert value not in text, f"{value!r} leaked in {path.relative_to(workspace).as_posix()!r}"


# ---------------------------------------------------------------------------
# Shared validation contract
# ---------------------------------------------------------------------------


def test_shared_validator_rejects_structurally_invalid_reports() -> None:
    problems = report_validation.validate_report_file(
        Path(__file__).resolve().parent.parent / "templates" / "workspace" / "report_template.json",
        "Student 0001",
    )
    assert problems == []

    data = json.loads(valid_report_text("Student 0001"))
    data["notes"] = 42
    assert report_validation.validate_report_data(data, "Student 0001")

    data = json.loads(valid_report_text("Student 0001"))
    data["code_copy_indications"] = [
        {"other_student_pseudonym": "Student 0002", "this_file": "main.py"}
    ]
    problems = report_validation.validate_report_data(data, "Student 0001")
    assert any("missing required field(s)" in problem for problem in problems)

    data = json.loads(valid_report_text("Student 0001"))
    data["assignment_submitted"] = "yes"
    assert any("assignment_submitted" in problem for problem in report_validation.validate_report_data(data, "Student 0001"))


def test_workspace_validator_helper_is_standalone_and_pseudonym_safe() -> None:
    source = (REPO_ROOT / "slaif_defense_grading" / "report_validation.py").read_text(encoding="utf-8")
    assert "from . " not in source and "from .\n" not in source
    assert "import slaif_defense_grading" not in source
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in source


# ---------------------------------------------------------------------------
# activate_assignment.sh reasoning-effort passthrough
# ---------------------------------------------------------------------------


def build_activation_fixture(tmp_path: Path) -> tuple[Path, Path]:
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
    with zipfile.ZipFile(assignment_dir / "submissions.zip", "w") as archive:
        archive.writestr("Ana Novak_123_assignsubmission_file/main.py", "print('hello')\n")
    return data_dir, assignment_dir


def install_fake_codex_for_activation(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        "prompt=${!#}\n"
        "case \"$prompt\" in\n"
        "  \"Analyze assignment requirements\")\n"
        "    printf '%s\\n' '{\"schema_version\": 1, \"requirements\": [{\"id\": \"task-001\", \"description\": \"Implement the synthetic task by the behavior it asks for.\", \"source_reference\": \"task_extracted.txt line 1\"}], \"notes\": \"\"}' > task_requirements.json\n"
        "    exit 0 ;;\n"
        "esac\n"
        "pseudonym=${prompt#Run submission assessment for }\n"
        "mkdir -p \"$pseudonym\"\n"
        "printf '%s\\n' \"{\\\"pseudonym\\\": \\\"$pseudonym\\\", \\\"assignment_submitted\\\": true, \\\"all_tasks_implemented\\\": true, \\\"task_details\\\": [], \\\"looks_llm_generated\\\": \\\"uncertain\\\", \\\"llm_generation_indicators\\\": [], \\\"code_copy_indications\\\": [], \\\"notes\\\": \\\"\\\"}\" > \"$pseudonym/report.json\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake_codex.chmod(0o755)
    return fake_bin


def run_activation(tmp_path: Path, assignment_dir: Path, fake_bin: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(REPO_ROOT / "activate_assignment.sh"), "test-profile", str(assignment_dir), *extra_args],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def latest_process_sh(assignment_dir: Path) -> Path:
    runs = sorted((assignment_dir / ".slaif-defense-grading" / "runs").iterdir())
    return runs[-1] / "agent-workspace" / "process.sh"


def test_wrapper_omitted_effort_defaults_to_medium(tmp_path: Path) -> None:
    _data_dir, assignment_dir = build_activation_fixture(tmp_path)
    fake_bin = install_fake_codex_for_activation(tmp_path)

    result = run_activation(tmp_path, assignment_dir, fake_bin)

    assert "Reasoning effort: medium" in result.stderr
    process_text = latest_process_sh(assignment_dir).read_text(encoding="utf-8")
    assert "-c model_reasoning_effort=medium" in process_text


def test_wrapper_low_effort_is_passed_through(tmp_path: Path) -> None:
    _data_dir, assignment_dir = build_activation_fixture(tmp_path)
    fake_bin = install_fake_codex_for_activation(tmp_path)

    result = run_activation(tmp_path, assignment_dir, fake_bin, "low")

    assert "Reasoning effort: low" in result.stderr
    process_text = latest_process_sh(assignment_dir).read_text(encoding="utf-8")
    assert "-c model_reasoning_effort=low" in process_text
    assert "model_reasoning_effort=medium" not in process_text


def test_wrapper_none_effort_omits_the_override(tmp_path: Path) -> None:
    _data_dir, assignment_dir = build_activation_fixture(tmp_path)
    fake_bin = install_fake_codex_for_activation(tmp_path)

    result = run_activation(tmp_path, assignment_dir, fake_bin, "none")

    assert "Reasoning effort: none" in result.stderr
    process_text = latest_process_sh(assignment_dir).read_text(encoding="utf-8")
    assert "-c model_reasoning_effort" not in process_text


def test_wrapper_rejects_extra_arguments_and_invalid_effort(tmp_path: Path) -> None:
    _data_dir, assignment_dir = build_activation_fixture(tmp_path)
    fake_bin = install_fake_codex_for_activation(tmp_path)

    too_many = subprocess.run(
        [
            str(REPO_ROOT / "activate_assignment.sh"),
            "test-profile",
            str(assignment_dir),
            "medium",
            "surprise",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert too_many.returncode == 64
    assert "Usage:" in too_many.stderr

    # Effort value validation is centralized in the Python CLI (argparse choices).
    invalid = subprocess.run(
        [
            str(REPO_ROOT / "activate_assignment.sh"),
            "test-profile",
            str(assignment_dir),
            "not-an-effort",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "invalid choice" in invalid.stderr


def test_cli_help_still_exposes_only_prepare_and_finalize() -> None:
    result = subprocess.run(
        [sys.executable, "slaif-defense-grading.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "prepare" in result.stdout
    assert "finalize" in result.stdout
    assert "legacy" not in result.stdout
