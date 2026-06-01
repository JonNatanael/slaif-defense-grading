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
