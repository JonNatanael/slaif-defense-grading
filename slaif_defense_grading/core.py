from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .io_utils import copy_file_preserving_uniqueness, eprint, safe_extract_zip


def infer_student_label_from_folder(folder_name: str) -> str:
    return folder_name.split("_", 1)[0].strip() or folder_name.strip() or "UNKNOWN"


def explicit_folder_identifiers(folder_name: str) -> tuple[List[str], List[str]]:
    """Extract explicit `=value` identifier tokens from an LMS folder name.

    Some LMS exports name student folders like ``Name Surname=email=student_id_...``
    instead of the Moodle ``Name Surname_id_...`` style. Returns ``(email_candidates,
    id_candidates)`` where email candidates are `=value` tokens containing ``@`` and
    id candidates are the leading digit runs of the other `=value` tokens.
    """
    email_candidates: List[str] = []
    id_candidates: List[str] = []
    for token in folder_name.split("=")[1:]:
        token = token.strip()
        if not token:
            continue
        if "@" in token:
            email_candidates.append(token.casefold())
        else:
            match = re.match(r"^\d+", token)
            if match:
                id_candidates.append(match.group(0))
    return email_candidates, id_candidates


def merge_master_inputs(input_zips: Sequence[Path], merged_root: Path) -> None:
    merged_root.mkdir(parents=True, exist_ok=True)
    students_by_label: Dict[str, Path] = {}

    for idx, input_zip in enumerate(input_zips, start=1):
        source_root = merged_root.parent / f"outer_extracted_{idx}"
        source_root.mkdir(parents=True, exist_ok=True)

        eprint(f"[slaif-defense-grading] Extracting master ZIP #{idx} -> {source_root}")
        safe_extract_zip(input_zip, source_root)

        student_paths = [p for p in source_root.iterdir() if p.is_dir()]
        if len(student_paths) == 1:
            container = student_paths[0]
            subdirs = [p for p in container.iterdir() if p.is_dir()]
            if len(subdirs) >= 2:
                eprint(
                    f"[slaif-defense-grading] Master ZIP #{idx} contains a single top-level folder "
                    f"'{container.name}' with {len(subdirs)} subfolders; unwrapping it and treating the subfolders as student folders"
                )
                student_paths = subdirs

        for student_path in sorted(student_paths, key=lambda p: p.as_posix().casefold()):
            label = infer_student_label_from_folder(student_path.name).casefold()

            existing = students_by_label.get(label)
            if existing is not None and existing.exists():
                shutil.rmtree(existing)

            target = merged_root / student_path.name
            if target.exists():
                shutil.rmtree(target)

            shutil.copytree(student_path, target)
            students_by_label[label] = target


def iter_nested_zips(root_dir: Path) -> Iterable[Path]:
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(".zip"):
                yield Path(dirpath) / fn


def iter_submission_dirs(student_folder: Path) -> List[Path]:
    subdirs = [p for p in student_folder.iterdir() if p.is_dir()]
    if subdirs:
        return sorted(subdirs, key=lambda p: p.as_posix().casefold())

    has_files = any(p.is_file() for p in student_folder.iterdir())
    if has_files:
        return [student_folder]

    return []


def stage_zip_with_sibling_files(zip_path: Path, outer_root: Path, unzipped_root: Path) -> Path:
    rel = zip_path.relative_to(outer_root)
    zip_base = zip_path.stem

    staged_dir = unzipped_root / rel.parent / zip_base
    staged_dir.mkdir(parents=True, exist_ok=True)
    safe_extract_zip(zip_path, staged_dir)

    student_root = outer_root / rel.parts[0]
    outside_dir = staged_dir / "__outside_zip__"

    for p in sorted(student_root.rglob("*"), key=lambda x: x.as_posix().casefold()):
        if not p.is_file():
            continue
        if p == zip_path:
            continue
        if p.suffix.lower() == ".zip":
            continue

        rel_outside = p.relative_to(student_root)
        copy_file_preserving_uniqueness(p, outside_dir / rel_outside)

    return staged_dir
