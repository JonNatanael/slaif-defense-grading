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

## Prepare Pseudonymized Workspace

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file assignment.pdf \
  --workspace work/lab-agent \
  --private-output work/lab-private
```

The assignment is copied into the workspace under a canonical name such as `task.pdf` or `task.tex`; the original basename is not preserved.

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

The workspace should contain the generated assignment file, usually `task.pdf` or `task.tex`, and `report_template.json`, which is the mandatory schema for every generated `report.json` (submission, task implementation, LLM-generation indicators, copying indications with line numbers).

## Run Agent

```bash
cd work/lab-agent
./process.sh
cd -
```

`process.sh` runs one Codex command per pseudonymized student in priority order (ordered-ID file first, then remaining CSV order), using the configured Codex profile with a `medium` reasoning effort by default (`--codex-profile` and `--codex-reasoning-effort` at prepare time select another profile/effort or `none` to fall back to the Codex CLI default). It does not run Phase 1; `associations.csv` was generated locally by `prepare`.

While it runs, the script atomically updates `work/lab-agent/processing_stats.json` after each attempted student. The JSON contains pseudonymized per-student durations and exit codes, total elapsed time, average time, counts, and run status. Rerunning the whole script starts a fresh statistics file.

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

If processing statistics are available, their summary and per-student times appear in `work/final/finalize_report.md`. Missing or invalid statistics do not block finalization.

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

- Missing reports after agent run: check `work/final/missing_reports.csv` and rerun `./process.sh` or the specific missing student command in `work/lab-agent`.
- Roster encoding error (`'utf-8' codec can't decode byte 0xff`): the roster was saved as UTF-16 (common for LMS/Excel exports). `prepare` now auto-detects UTF-8/UTF-16 BOMs; for any other encoding, re-export as UTF-8, e.g. `iconv -f UTF-16LE -t UTF-8 izvoz.csv > students.csv`.
- `missing required column(s): name, surname`: you passed a raw LMS student-list export; convert it to a comma-separated `name,surname,email,student_id` roster locally first.
- Unmatched LMS folders: inspect `work/lab-private/preprocessing_report.md`; unmatched folders are intentionally not copied into the agent workspace.
- Missing submissions: students with no matched submission are marked `unresolved` in `associations.csv`.
- Real identifiers detected in workspace: `prepare` fails before completion; inspect the error and source data locally.
- Permission issue on `process.sh`: run `chmod +x work/lab-agent/process.sh`.
