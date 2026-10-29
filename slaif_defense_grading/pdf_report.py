from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Candidate directories for a Unicode TTF pair (Slovenian diacritics support).
_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/usr/share/fonts/truetype",
    "/usr/local/share/fonts",
    "/System/Library/Fonts",
    os.path.expanduser("~/.fonts"),
)

# Minimal transliteration fallback when no Unicode TTF is available (core
# PDF fonts only support cp1252/WinAnsi).
_TRANSLIT_PAIRS = (
    ("č", "c"), ("ć", "c"), ("đ", "d"), ("ě", "e"), ("ĺ", "l"), ("ň", "n"), ("ő", "o"),
    ("ś", "s"), ("ť", "t"), ("ů", "u"), ("ű", "u"), ("š", "s"), ("ž", "z"), ("ǎ", "a"),
    ("ǐ", "i"), ("ę", "e"), ("į", "i"),
    ("Č", "C"), ("Ć", "C"), ("Đ", "D"), ("Ě", "E"), ("Ĺ", "L"), ("Ň", "N"), ("Ő", "O"),
    ("Ś", "S"), ("Ť", "T"), ("Ů", "U"), ("Ű", "U"), ("Š", "S"), ("Ž", "Z"), ("Ę", "E"),
    ("Į", "I"),
)
_TRANSLITERATION = str.maketrans(dict(_TRANSLIT_PAIRS))


def find_font_pair() -> Optional[Tuple[Path, Path]]:
    """Locate a (regular, bold) TTF pair; returns None when no Unicode font exists."""
    override_dir = os.environ.get("SLAIF_FONT_DIR")
    dirs = [override_dir] if override_dir else list(_FONT_DIRS)
    for directory in dirs:
        if not directory:
            continue
        base = Path(directory)
        if not base.is_dir():
            continue
        regular = base / "DejaVuSans.ttf"
        bold = base / "DejaVuSans-Bold.ttf"
        if regular.is_file() and bold.is_file():
            return regular, bold
    return None


def _cp1252_safe(text: str) -> str:
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return text.translate(_TRANSLITERATION)


def _bullet_lines(items: Sequence[str]) -> List[str]:
    lines: List[str] = []
    for item in items:
        item = (item or "").strip()
        if item:
            lines.append(f"- {item}")
    return lines


def assessment_lines(
    report: Dict[str, object],
    full_name: str,
    pseudonym: str,
    other_student_names: Dict[str, str],
) -> List[Tuple[str, str]]:
    """Return the human-readable report as (style, text) pairs.

    Styles: h1, h2, meta, body, bullet, footer.
    """
    def yes_no(value: object) -> str:
        return "Yes" if value is True else "No"

    lines: List[Tuple[str, str]] = [
        ("h1", f"Submission assessment - {full_name}"),
        ("meta", f"Pseudonym: {pseudonym}"),
        ("h2", "1. Was the assignment submitted?"),
        ("body", yes_no(report.get("assignment_submitted"))),
        ("h2", "2. Are all the tasks implemented?"),
        ("body", yes_no(report.get("all_tasks_implemented")) if report.get("all_tasks_implemented") in (True, False) else str(report.get("all_tasks_implemented", "unknown"))),
    ]
    task_details = report.get("task_details") or []
    if isinstance(task_details, list):
        for detail in task_details:
            if not isinstance(detail, dict):
                continue
            task = str(detail.get("task") or "").strip()
            implemented = detail.get("implemented")
            evidence = str(detail.get("evidence") or "").strip()
            state = "implemented" if implemented is True else ("not implemented" if implemented is False else "unknown")
            if task:
                lines.append(("bullet", f"{task}: {state}"))
            if evidence:
                lines.append(("bullet", f"    evidence: {evidence}"))

    llm = str(report.get("looks_llm_generated") or "uncertain")
    lines.append(("h2", "3. Does the code look LLM-generated?"))
    lines.append(("body", llm.capitalize()))
    for indicator in _bullet_lines(report.get("llm_generation_indicators") or [] if isinstance(report.get("llm_generation_indicators"), list) else []):
        lines.append(("bullet", indicator))

    lines.append(("h2", "4. Indications of copying code from another student?"))
    copies = report.get("code_copy_indications") or []
    if isinstance(copies, list) and copies:
        for copy in copies:
            if not isinstance(copy, dict):
                continue
            other_pseudonym = str(copy.get("other_student_pseudonym") or "").strip()
            other_name = other_student_names.get(other_pseudonym)
            other_label = f"{other_pseudonym}" + (f" ({other_name})" if other_name else "")
            this_file = str(copy.get("this_file") or "").strip()
            this_lines = str(copy.get("this_lines") or "").strip()
            other_file = str(copy.get("other_file") or "").strip()
            other_lines = str(copy.get("other_lines") or "").strip()
            lines.append(("bullet", f"From {other_label}"))
            if this_file:
                lines.append(("bullet", f"    this submission: {this_file}" + (f", lines {this_lines}" if this_lines else "")))
            if other_file:
                lines.append(("bullet", f"    other submission: {other_file}" + (f", lines {other_lines}" if other_lines else "")))
            evidence = str(copy.get("evidence") or "").strip()
            if evidence:
                lines.append(("bullet", f"    evidence: {evidence}"))
    else:
        lines.append(("body", "None."))

    notes = str(report.get("notes") or "").strip()
    if notes:
        lines.append(("h2", "Notes"))
        lines.append(("body", notes))

    lines.append(
        (
            "footer",
            "Evidence-based assessment for instructor review (oral verification / human review). "
            "It does not prove plagiarism, unauthorized collaboration, or improper AI-tool use.",
        )
    )
    return lines


def render_assessment_pdf(
    report: Dict[str, object],
    full_name: str,
    pseudonym: str,
    other_student_names: Dict[str, str],
    output_path: Path,
) -> Path:
    """Render the human-readable instructor-facing PDF for one student."""
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "rendering the PDF report requires the 'fpdf2' package (pip install fpdf2)"
        ) from exc

    lines = assessment_lines(report, full_name, pseudonym, other_student_names)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fonts = find_font_pair()
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_compression(False)  # keep text extractable/greppable in the small report
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if fonts:
        pdf.add_font("Assess", "", str(fonts[0]))
        pdf.add_font("Assess", "B", str(fonts[1]))
        font_family = "Assess"
    else:
        font_family = "helvetica"

    for style, text in lines:
        text = _cp1252_safe(text) if font_family == "helvetica" else text
        # fpdf2 leaves the cursor at the right margin after multi_cell; reset it.
        kwargs = {"new_x": "LMARGIN", "new_y": "NEXT"}
        if style == "h1":
            pdf.set_font(font_family, "B", 15)
            pdf.multi_cell(0, 7, text, **kwargs)
            pdf.ln(2)
        elif style == "h2":
            pdf.set_font(font_family, "B", 12)
            pdf.ln(1)
            pdf.multi_cell(0, 6, text, **kwargs)
        elif style == "meta":
            pdf.set_font(font_family, "", 10)
            pdf.multi_cell(0, 5, text, **kwargs)
            pdf.ln(1)
        elif style == "body":
            pdf.set_font(font_family, "", 11)
            pdf.multi_cell(0, 5.5, text, **kwargs)
        elif style == "bullet":
            pdf.set_font(font_family, "", 10.5)
            pdf.multi_cell(0, 5.5, text, **kwargs)
        elif style == "footer":
            pdf.ln(3)
            pdf.set_font(font_family, "", 9)
            pdf.multi_cell(0, 4.5, text, **kwargs)

    pdf.output(str(output_path))
    return output_path


FINAL_REPORT_CSV_COLUMNS = (
    "full_name",
    "all_tasks_implemented",
    "copying_indications",
    "llm_indications",
    "notes",
)

FINAL_REPORT_PDF_COLUMNS = (
    "Student",
    "All tasks implemented",
    "Reasonably strong copying indications",
    "Reasonably strong LLM-use indications",
    "Notes",
)

# Notes get the widest column; even long notes must keep a row far below one
# page so fpdf2 can render the whole table (fractions of the page width).
FINAL_REPORT_COLUMN_WIDTHS = (0.20, 0.12, 0.22, 0.16, 0.30)

# Defense in depth: no single cell may make a row taller than one page.
MAX_FINAL_REPORT_CELL_CHARS = 300


def _clip_cell(text: str, limit: int = MAX_FINAL_REPORT_CELL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def render_final_report_pdf(rows: Sequence[Dict[str, str]], output_path: Path) -> Path:
    """Render the single-table final overview PDF: one row per roster student.

    Each row is keyed by FINAL_REPORT_CSV_COLUMNS and holds short cells
    (Yes/No/Unknown, "Yes (with <name>)", Likely/Unlikely/Uncertain, notes).
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "rendering the final report requires the 'fpdf2' package (pip install fpdf2)"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fonts = find_font_pair()
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_compression(False)  # keep text extractable/greppable in the overview
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if fonts:
        pdf.add_font("Assess", "", str(fonts[0]))
        pdf.add_font("Assess", "B", str(fonts[1]))
        font_family = "Assess"
    else:
        font_family = "helvetica"

    def safe(text: str) -> str:
        return _cp1252_safe(text) if font_family == "helvetica" else text

    pdf.set_font(font_family, "B", 15)
    pdf.multi_cell(0, 7, safe("Final overview - all submissions"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_family, "", 10)
    pdf.multi_cell(
        0,
        5,
        safe("Quick overview for the teaching assistant during in-person oral verification."),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    data: List[List[str]] = [list(FINAL_REPORT_PDF_COLUMNS)]
    for row in rows:
        data.append([safe(_clip_cell(str(row.get(col) or ""))) for col in FINAL_REPORT_CSV_COLUMNS])

    with pdf.table(
        rows=data,
        text_align="LEFT",
        line_height=pdf.font_size * 1.5,
        col_widths=FINAL_REPORT_COLUMN_WIDTHS,
    ):
        pass

    pdf.ln(3)
    pdf.set_font(font_family, "", 9)
    pdf.multi_cell(
        0,
        4.5,
        safe(
            "Evidence-based indicators for human review (oral verification). "
            "They do not prove plagiarism, unauthorized collaboration, or improper AI-tool use."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.output(str(output_path))
    return output_path
