from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_legacy_src_preprocesslabs_imports_remain() -> None:
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if ".git" in path.parts or ".codex" in path.parts:
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "src.preprocesslabs" not in text


def test_legacy_entrypoints_removed() -> None:
    assert not (REPO_ROOT / "preprocess-labs.py").exists()
    assert not (REPO_ROOT / "preprocesslabs.py").exists()
