from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_import_slaif_defense_grading() -> None:
    module = importlib.import_module("slaif_defense_grading")
    assert module.main is not None
