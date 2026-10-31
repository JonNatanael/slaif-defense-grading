"""Deterministic local text extraction from the canonical assignment file.

The instructor assignment is copied into the workspace untouched as the
canonical ``task.*``. In addition, ``prepare`` writes ``task_extracted.txt``,
a plain-text version of the assignment used by the one-time assignment
requirements analysis, so every student agent does not repeatedly parse and
reinterpret the canonical assignment.

Extraction is local and deterministic:

- formats already treated as readable text are decoded with the repository's
  existing BOM-aware, loss-tolerant decoding and line endings are normalized;
- PDFs are extracted with the ``pypdf`` library when importable, otherwise
  with a locally detected ``pdftotext`` (poppler-utils) executable;
- no remote service is ever contacted and no OCR is performed.

Empty or implausibly small PDF results are treated as failed extraction: a
warning is recorded and the original ``task.*`` remains the assignment source.
A misleading empty ``task_extracted.txt`` is never written.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .io_utils import detect_bom_encoding
from .models import READABLE_SUFFIXES

WORKSPACE_EXTRACTED_NAME = "task_extracted.txt"

# Below this stripped length a PDF text extraction result is considered
# implausibly small (scanned/image-only or text-less PDFs typically yield
# nothing or a stray fragment).
MIN_EXTRACTED_CHARS = 32


@dataclass(frozen=True)
class TaskExtractionResult:
    """Outcome of extracting the assignment text.

    ``method`` is one of: ``text`` (readable format decoded directly),
    ``pdf:pypdf``, ``pdf:pdftotext``, or ``not-extracted``.
    """

    written: bool
    method: str
    warnings: Tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.written and not self.warnings


def normalize_line_endings(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp_path, path)


def _extract_pdf_with_pypdf(source: Path) -> Optional[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(source))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _extract_pdf_with_pdftotext(source: Path) -> Tuple[Optional[str], Optional[str]]:
    """Returns (text, problem); exactly one of the two is set."""
    executable = shutil.which("pdftotext")
    if executable is None:
        return None, "pdftotext executable not found"
    with tempfile.TemporaryDirectory(prefix="slaif-defense-grading_pdftotext_") as tmp:
        output_path = Path(tmp) / "extracted.txt"
        proc = subprocess.run(
            [executable, str(source), str(output_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            return None, f"pdftotext exited with status {proc.returncode}" + (f": {detail}" if detail else "")
        return output_path.read_text(encoding="utf-8", errors="replace"), None


def _extract_pdf_text(source: Path) -> Tuple[Optional[str], str, List[str]]:
    """Extract PDF text deterministically: pypdf first, then pdftotext."""
    warnings: List[str] = []
    try:
        text = _extract_pdf_with_pypdf(source)
        return text, "pdf:pypdf", warnings
    except ImportError:
        warnings.append("pypdf is not installed; falling back to the local pdftotext executable.")
    except Exception as exc:  # noqa: BLE001 - pypdf raises many file-specific types
        warnings.append(f"pypdf extraction failed ({exc.__class__.__name__}: {exc}); falling back to pdftotext.")

    text, problem = _extract_pdf_with_pdftotext(source)
    if problem is not None:
        if problem == "pdftotext executable not found":
            return (
                None,
                "not-extracted",
                warnings
                + [
                    "No local PDF text extractor is available (install 'pypdf' or poppler-utils); "
                    "the original PDF is retained as the assignment source."
                ],
            )
        return None, "not-extracted", warnings + [f"{problem}; the original PDF is retained as the assignment source."]
    return text, "pdf:pdftotext", warnings


def extract_task_text(source: Path, dest: Path) -> TaskExtractionResult:
    """Extract plain text from the assignment file and write it atomically.

    ``dest`` is written only when a usable extraction result exists; otherwise
    ``written`` is False and the warnings explain the fallback to the original
    ``task.*`` file.
    """
    suffix = source.suffix.lower()

    if suffix in READABLE_SUFFIXES:
        raw = source.read_bytes()
        encoding = detect_bom_encoding(raw[:4])
        try:
            text = normalize_line_endings(raw.decode(encoding))
        except (UnicodeError, LookupError) as exc:
            return TaskExtractionResult(
                False,
                "not-extracted",
                (f"Assignment text could not be decoded ({exc.__class__.__name__}: {exc}); the original file is retained as the assignment source.",),
            )
        write_text_atomic(dest, text)
        return TaskExtractionResult(True, "text", ())

    if suffix == ".pdf":
        text, method, warnings = _extract_pdf_text(source)
        if text is None:
            return TaskExtractionResult(False, "not-extracted", warnings)
        if len(text.strip()) < MIN_EXTRACTED_CHARS:
            return TaskExtractionResult(
                False,
                method,
                warnings
                + [
                    "PDF text extraction produced empty or implausibly small output "
                    "(possibly a scanned/image-only or text-less PDF); no OCR is performed, "
                    "and the original PDF is retained as the assignment source."
                ],
            )
        write_text_atomic(dest, normalize_line_endings(text))
        return TaskExtractionResult(True, method, tuple(warnings))

    return TaskExtractionResult(
        False,
        "not-extracted",
        (
            f"No local text extractor is available for the assignment format '{source.suffix or '(none)'}'; "
            "the original file is retained as the assignment source."
        ),
    )
