from __future__ import annotations

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
