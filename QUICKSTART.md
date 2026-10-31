# Quickstart

This workflow prepares oral-defense questions for submissions completed outside direct supervision.

This guide runs the full local workflow:

1. prepare a pseudonymized workspace;
2. run the later oral-verification agent;
3. finalize named private instructor outputs.

## Inputs Needed

Prepare these local files:

- Moodle/Canvas export ZIP, for example `moodle_export.zip`;
- real local `students.csv` with at least `name,surname` (comma-separated; UTF-8 or UTF-16 with BOM both work). A raw tab-separated LMS student-list export is not a roster and must be converted to `name,surname,...` first;
- optional private student-order text file with one exact `student_id` per line and no header;
- assignment file, for example `assignment.pdf` or `task.tex`.

Do not commit real rosters, submission ZIPs, generated workspaces, private mappings, or final outputs.

## Install/Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## One-command Activation

When your files use the standard local layout below, the activation script is
the shortest complete workflow:

```text
data_UZ/
  students_UZ.csv
  assignment_1/
    assignment_instructions.pdf
    submissions.zip
```

```bash
./activate_assignment.sh early-beta data_UZ/assignment_1 [reasoning-effort]
```

It is the only command you need to provide inputs for: profile first, then the
assignment directory, and optionally the reasoning effort (`none`, `low`,
`medium`, `high`, or `xhigh`). The effort defaults to `medium` and `none`
omits the override; it is passed to `prepare` as `--codex-reasoning-effort`.
It discovers the parent `students*.csv` roster, the one
non-ZIP instruction file, and all ZIP submissions in the directory. It writes
a new private run under `.slaif-defense-grading/runs/` inside the assignment
directory, runs the agent, and finalizes completed reports. Ambiguous discovery
stops with an error rather than selecting a file by guesswork.

Optionally, add `student_order.txt` to the data directory (one student ID per
line, no header) to process students in that order; IDs not listed keep their
relative roster order and are processed after the listed ones.

The activation step privately converts common LMS roster exports (UTF-8 or
UTF-16; comma, semicolon, or tab-separated). It supports explicit name/surname
columns and `Priimek, Ime` (surname, name), retaining recognized email and
student-ID columns. The resulting canonical CSV remains only under the private
run directory.

## Prepare Pseudonymized Workspace

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file assignment.pdf \
  --workspace work/lab-agent \
  --private-output work/lab-private
```

The assignment is copied into the workspace under a canonical name such as `task.pdf` or `task.tex`; the original basename is not preserved. In addition, `prepare` extracts the assignment text locally and deterministically into `task_extracted.txt` so the agent does not repeatedly parse the canonical assignment: readable text formats are decoded directly, and PDFs are extracted with the `pypdf` dependency (or a locally detected `pdftotext` executable). No remote service is contacted and no OCR is performed, so a scanned or image-only PDF cannot be extracted; in that case no `task_extracted.txt` is written, the warning is recorded in the private `preprocessing_report.md` under "Assignment Extraction", and the canonical `task.*` file remains the assignment source.

To grade selected students first, add `--student-order-file student-order.txt`. This requires a `student_id` column in `students.csv`. Listed IDs are pseudonymized and processed first in file order; students not listed follow in their original CSV order. Keep the order file outside the workspace so it stays private/local. Unknown, duplicate, or non-unique listed IDs cause `prepare` to fail.

Default mode excludes opaque documents such as PDF/DOCX/DOC/ODT/RTF because their internal content and metadata are not redacted.

`--include-opaque-documents` exists, but it weakens privacy. It copies opaque documents under pseudonymized filenames only; internal document content and metadata may still contain real identifiers.

## Inspect Before Running Agent

Inspect:

```text
work/lab-agent/
work/lab-agent/report_template.json
work/lab-private/preprocessing_report.md
```

`work/lab-agent/` should contain no real names, emails, student IDs, or original LMS folder names. The private report may contain real matching details and must remain local.

The workspace should contain the generated assignment file, usually `task.pdf` or `task.tex`, `task_extracted.txt` when local extraction succeeded, and `report_template.json`, which is the mandatory schema for every generated `report.json` (submission, task implementation, LLM-generation indicators, copying indications with line numbers).

## Run Agent

```bash
cd work/lab-agent
./process.sh
cd -
```

`process.sh` runs one deterministic command per pseudonymized student in priority order (ordered-ID file first, then remaining CSV order), using the configured Codex profile with a `medium` reasoning effort by default (`--codex-profile` and `--codex-reasoning-effort` at prepare time select another profile/effort or `none` to fall back to the Codex CLI default). It does not run Phase 1; `associations.csv` was generated locally by `prepare`.

Before any student that needs an agent invocation, `process.sh` validates the shared `task_requirements.json` requirements file (generated once by the `Analyze assignment requirements` agent command and reused by every student run). If the file is valid it is reused; if it is missing or invalid, Codex is invoked exactly once to create it, and the result is validated before any student is processed. The analysis is skipped entirely when no student needs an agent invocation (for example when every student is unresolved or already has a valid report), so resumed runs do not repeat it. `./process.sh --force` regenerates the requirements file as well. If the analysis fails, matched students without a valid report are recorded as `skipped_prerequisite_failed` (already valid reports are preserved, unresolved students still get their neutral local reports), and `process.sh` exits nonzero.

Processing is resumable by default. Before invoking Codex, `process.sh` validates any existing `<pseudonym>/report.json` with the workspace `report_validator.py` helper: a valid report is skipped without a Codex call, while a missing, malformed, or wrong-pseudonym report is reprocessed. Students with no associated submissions get a neutral local report generated by `process.sh` itself, without any Codex call. Use `./process.sh --force` to regenerate reports even when a valid one exists (it still never calls Codex for unresolved students). One failing student does not stop the later ones; the script exits nonzero only after all planned students were attempted, if any agent invocation failed.

While it runs, the script atomically updates `work/lab-agent/processing_stats.json` after each handled student. The JSON (schema version 2) contains pseudonymized per-student outcome, durations, and exit codes, plus planned/processed/successful/failed/skipped/generated counts, total time, average time, and run status, and a separate `assignment_analysis` block recording the one-time requirements analysis (outcome `reused`/`generated`/`failed`/`skipped`, duration and exit code when invoked, and whether local extraction warnings were present). A resumed run records skipped reports as skipped rather than as newly produced. `finalize` accepts statistics from both version 2 and the earlier version 1 format.

## Finalize Named Local Outputs

After the agent creates reports such as `Student 0001/report.json`, run:

```bash
python3 slaif-defense-grading.py finalize \
  --workspace work/lab-agent \
  --private-output work/lab-private \
  --output work/final
```

Use strict mode when every report is expected:

```bash
python3 slaif-defense-grading.py finalize \
  --workspace work/lab-agent \
  --private-output work/lab-private \
  --output work/final \
  --strict
```

For time-constrained partial results, run `finalize` without `--strict` while `process.sh` is still working. Completed valid reports are included, unfinished students are listed in `missing_reports.csv` and shown as `Unknown`/`No report`, and rerunning the command later refreshes the outputs. `--strict` intentionally returns an error if any report is missing.

If processing statistics are available, their summary (including the one-time assignment-analysis outcome when recorded) and per-student times appear in `work/final/final_report.pdf` and `work/final/finalize_report.md`. Missing or invalid statistics do not block finalization.

## Inspect Final Outputs

Expected shape:

```text
work/final/
  final_index.csv
  final_report.csv
  final_report.pdf
  final_report.html
  finalize_report.md
  missing_reports.csv
  instructor_reports/
    Mila_Kranjc/
      report.pdf
      report.json
  student_outputs/
    Mila_Kranjc.txt
```

`work/final/` is private/local and may contain real student identities.

`final_report.pdf` (and the machine-readable `final_report.csv`) is a single-table overview with one row per student: all tasks implemented, reasonably strong indications of copying, reasonably strong indications of LLM use, and notes. Use it as a fast reference when evaluating submissions in person with the student.

`final_report.html` is the same overview as a self-contained local HTML viewer (just open the file in a browser). It adds links to each student's full report and jumps directly to the exact code lines referenced in the reports (own code, the other student's code for suspected copying, or lines mentioned in notes), highlighting the target lines according to the kind of link used.

## What To Share With Students

`student_outputs/<Name>.txt` is the concatenated pseudonymized submission text that the agent saw. It can be shown individually to the corresponding student if appropriate.

`instructor_reports/<Name>/report.pdf` (human-readable) and `report.json` (machine-readable) are instructor-facing assessments for human review, including line-number evidence. Do not send them wholesale to students.

Do not share `pseudonym_map.csv`, `student_outputs_index.csv`, `final_index.csv`, or the final report (`final_report.pdf`/`final_report.csv`/`final_report.html`) wholesale with students.

## Troubleshooting

- Missing reports after agent run: check `work/final/missing_reports.csv` and rerun `./process.sh` (it only redoes students whose report is missing or invalid) or the specific missing student command in `work/lab-agent`.
- Partial agent failure: rerun `./process.sh` to retry only the failed students; `./process.sh --force` regenerates every matched student's report.
- Roster encoding error (`'utf-8' codec can't decode byte 0xff`): the roster was saved as UTF-16 (common for LMS/Excel exports). `prepare` now auto-detects UTF-8/UTF-16 BOMs; for any other encoding, re-export as UTF-8, e.g. `iconv -f UTF-16LE -t UTF-8 izvoz.csv > students.csv`.
- `missing required column(s): name, surname`: you passed a raw LMS student-list export; convert it to a comma-separated `name,surname,email,student_id` roster locally first.
- Unmatched LMS folders: inspect `work/lab-private/preprocessing_report.md`; unmatched folders are intentionally not copied into the agent workspace.
- Missing submissions: students with no matched submission are marked `unresolved` in `associations.csv`.
- No `task_extracted.txt` in the workspace: the assignment PDF likely has no extractable text (for example a scanned or image-only PDF). This is expected and not an error; the canonical `task.*` file remains the assignment source and the warning is in `preprocessing_report.md`. No OCR is performed.
- Assignment analysis failure: `processing_stats.json` records `assignment_analysis.outcome: failed` and matched students appear as `skipped_prerequisite_failed`. Fix the cause, then rerun `./process.sh` (already valid reports stay untouched).
- Real identifiers detected in workspace: `prepare` fails before completion; inspect the error and source data locally.
- Permission issue on `process.sh`: run `chmod +x work/lab-agent/process.sh`.
