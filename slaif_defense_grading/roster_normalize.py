"""Normalize common LMS roster exports into the private prepare CSV format."""

from __future__ import annotations

import argparse
import csv
import io
import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, Sequence

from .io_utils import detect_bom_encoding


def _header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


NAME_HEADERS = {"name", "first name", "given name", "ime"}
SURNAME_HEADERS = {"surname", "last name", "family name", "priimek"}
COMBINED_NAME_HEADERS = {"full name", "name surname", "surname name", "priimek ime"}
EMAIL_HEADERS = {"email", "e mail", "email address", "e posta"}
STUDENT_ID_HEADERS = {"student id", "student number", "student identifier", "vpisna stevilka", "enrollment number"}


def _choose_delimiter(lines: Iterable[str]) -> str:
    candidates = ("\t", ";", ",")
    counts = {delimiter: max((line.count(delimiter) for line in lines), default=0) for delimiter in candidates}
    delimiter, count = max(counts.items(), key=lambda item: item[1])
    if count == 0:
        raise ValueError("roster export does not appear to be comma-, semicolon-, or tab-separated")
    return delimiter


def _find_header(rows: Sequence[Sequence[str]]) -> tuple[int, Dict[str, int]]:
    for row_index, row in enumerate(rows):
        columns = {_header_key(value): index for index, value in enumerate(row) if _header_key(value)}
        name = next((columns[key] for key in NAME_HEADERS if key in columns), None)
        surname = next((columns[key] for key in SURNAME_HEADERS if key in columns), None)
        combined = next((columns[key] for key in COMBINED_NAME_HEADERS if key in columns), None)
        if name is not None and surname is not None:
            return row_index, {"name": name, "surname": surname, **_optional_columns(columns)}
        if combined is not None:
            return row_index, {"combined_name": combined, **_optional_columns(columns)}
    raise ValueError(
        "could not find roster name columns; expected name/surname or a combined full-name column "
        "such as 'Priimek, Ime'"
    )


def _optional_columns(columns: Dict[str, int]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for canonical, candidates in (("email", EMAIL_HEADERS), ("student_id", STUDENT_ID_HEADERS)):
        found = next((columns[key] for key in candidates if key in columns), None)
        if found is not None:
            result[canonical] = found
    return result


def _value(row: Sequence[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _split_combined_name(value: str, row_number: int) -> tuple[str, str]:
    # LMS exports commonly label and encode this as "Surname, Name". Reject
    # other combined layouts rather than guessing an identity split.
    surname, separator, name = value.partition(",")
    if not separator or not surname.strip() or not name.strip():
        raise ValueError(
            f"roster row {row_number} has a combined name that is not 'Surname, Name': {value!r}"
        )
    return name.strip(), surname.strip()


def normalize_roster(source: Path, output: Path) -> int:
    """Write canonical private name,surname[,email,student_id] CSV and return its row count."""
    raw = source.read_bytes()
    try:
        text = raw.decode(detect_bom_encoding(raw[:4]))
    except UnicodeError as exc:
        raise ValueError(f"roster could not be decoded as UTF-8 or UTF-16: {exc}") from exc

    lines = text.lstrip("\ufeff").splitlines()
    delimiter = _choose_delimiter(lines)
    rows = list(csv.reader(io.StringIO("\n".join(lines), newline=""), delimiter=delimiter))
    header_row, columns = _find_header(rows)
    fieldnames = ["name", "surname"]
    fieldnames.extend(field for field in ("email", "student_id") if field in columns)

    normalized_rows = []
    for row_number, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
        if not any(cell.strip() for cell in row):
            continue
        if "combined_name" in columns:
            name, surname = _split_combined_name(_value(row, columns["combined_name"]), row_number)
        else:
            name, surname = _value(row, columns["name"]), _value(row, columns["surname"])
            if not name or not surname:
                raise ValueError(f"roster row {row_number} has an empty name or surname")
        normalized = {"name": name, "surname": surname}
        for field in ("email", "student_id"):
            if field in columns:
                normalized[field] = _value(row, columns[field])
        normalized_rows.append(normalized)

    if not normalized_rows:
        raise ValueError("roster contains no student rows after its header")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(normalized_rows)
    return len(normalized_rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize a private LMS roster for slaif-defense-grading.")
    parser.add_argument("--input", required=True, help="Private LMS roster export")
    parser.add_argument("--output", required=True, help="Private canonical CSV output")
    args = parser.parse_args(argv)
    try:
        count = normalize_roster(Path(args.input), Path(args.output))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        parser.error(str(exc))
    print(f"[slaif-defense-grading] Normalized private roster ({count} students): {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
