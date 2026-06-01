from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List

from .models import DOCUMENT_SUFFIXES, READABLE_FILENAMES, READABLE_SUFFIXES


def eprint(*args: object, **kwargs: object) -> None:
    print(*args, file=sys.stderr, **kwargs)


def _commonpath(a: Path, b: Path) -> Path:
    return Path(os.path.commonpath([str(a), str(b)]))


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename
            if not name:
                continue
            if name.startswith("/") or name.startswith("\\"):
                raise ValueError(f"Unsafe ZIP member (absolute path): {name}")
            target = (dest_dir / name).resolve()
            if _commonpath(dest_dir, target) != dest_dir:
                raise ValueError(f"Unsafe ZIP member (path traversal): {name}")
        zf.extractall(dest_dir)


def decode_text_file(path: Path) -> str:
    data = path.read_bytes()
    return data.decode("utf-8", errors="replace")


def is_probably_text(path: Path, sample_size: int = 32 * 1024) -> bool:
    data = path.read_bytes()[:sample_size]
    if not data:
        return True
    if b"\x00" in data:
        return False

    text_bytes = set(range(32, 127)) | {9, 10, 12, 13, 8}
    non_text = sum(byte not in text_bytes for byte in data)
    return (non_text / len(data)) <= 0.30


def list_readable_files(extracted_dir: Path) -> List[Path]:
    files: List[Path] = []
    for p in extracted_dir.rglob("*"):
        if not p.is_file():
            continue

        is_readable_kind = p.suffix.lower() in READABLE_SUFFIXES or p.name.lower() in READABLE_FILENAMES
        if is_readable_kind:
            if is_probably_text(p):
                files.append(p)
            else:
                eprint(f"Warning: skipping binary file {p}")

    files.sort(key=lambda x: x.as_posix().lower())
    return files


def list_document_files(extracted_dir: Path) -> List[Path]:
    documents = [p for p in extracted_dir.rglob("*") if p.is_file() and p.suffix.lower() in DOCUMENT_SUFFIXES]
    documents.sort(key=lambda x: x.as_posix().lower())
    return documents


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    n = 1
    while True:
        candidate = parent / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def copy_file_preserving_uniqueness(src: Path, dst: Path) -> None:
    target = unique_path(dst)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
