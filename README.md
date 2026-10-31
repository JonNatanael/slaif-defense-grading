<div style="text-align: center;">
  <a href="https://www.slaif.si">
    <img src="docs/assets/slaif-logo.svg" width="400" height="400">
  </a>
</div>

# SLAIF Defense Grading

A local-first workflow for preparing oral-defense questions for student work completed outside direct supervision.

The tool prepares a pseudonymized workspace for an AI coding agent, runs no grading decisions itself, and then maps the agent's pseudonymized reports back to private instructor-facing outputs.

It is designed for instructors who need targeted questions about submitted code, reports, notebooks, graphs, parameters, explanations, or other artifacts. This can support ordinary oral defenses as well as cases where the instructor needs to probe possible plagiarism, unauthorized collaboration, or improper AI-tool use.

The tool does not automatically prove misconduct. It helps prepare concrete, submission-specific questions so the instructor can verify whether the student understands the work they submitted.

For a complete step-by-step run, see [QUICKSTART.md](QUICKSTART.md).

## One-command Assignment Activation

For the usual local layout, run the complete workflow with only a Codex profile
and the assignment directory:

```bash
./activate_assignment.sh early-beta data_UZ/assignment_1
```

The optional third argument selects the Codex reasoning effort
(`none`, `low`, `medium`, `high`, or `xhigh`); it defaults to `medium`, and
`none` omits the override so the profile/CLI default applies:

```bash
./activate_assignment.sh early-beta data_UZ/assignment_1 low
```

The assignment directory must contain exactly one instructor instruction file
and one or more submission ZIPs. Its parent directory must contain exactly one
private roster matching `students*.csv` (for example,
`data_UZ/students_UZ.csv`). The script creates a fresh, private timestamped run
under `data_UZ/assignment_1/.slaif-defense-grading/runs/`, then performs
`prepare`, `process.sh`, and non-strict `finalize`. The final instructor files
are in that run's `final/` directory; the pseudonym map remains in its sibling
`private/` directory, outside `agent-workspace/`.

Before preparation, the script privately normalizes common UTF-8/UTF-16
comma-, semicolon-, and tab-separated roster exports. It recognizes separate
name/surname columns and LMS-style combined `Priimek, Ime` (surname, name)
columns, retaining recognized email and student-ID fields. The normalized CSV
is stored only in the run's `private/` directory.

If the parent data directory also contains a `student_order.txt` file,
students are processed in the order that file lists (one student ID per line,
headerless; IDs not listed keep their relative roster order and follow the
listed ones). Without the file, roster order is used.

If an agent invocation fails, the script still finalizes completed reports and
the partial `processing_stats.json`, then exits with the process failure code.
It rejects ambiguous roster or instruction-file discovery rather than guessing.

## What Problem This Solves

Many lab assignments are completed outside direct supervision. Written submissions alone do not always show whether a student understands the work they submitted, and generic oral-defense questions are weak because they are not tied to the actual artifacts.

This workflow creates targeted oral-verification questions from the submitted material. It can help reveal cases where a student cannot explain their own code, report, notebook, graph, parameter choices, or conclusions. That signal may be relevant to plagiarism, unauthorized collaboration, or improper AI-tool use, but it is not automatic proof. Final judgment remains a human instructor decision.

## Current Workflow

The supported workflow is:

1. `prepare`: run local preprocessing and create a pseudonymized agent workspace.
2. Run `process.sh`: first ensure the one-time shared `task_requirements.json` assignment analysis exists (reusing it when valid, invoking the assignment-analysis agent at most once), then ask the agent to write one pseudonymized submission-assessment report (`report.json`) per student, skipping students that already have a valid report and generating neutral local reports for students without submissions.
3. `finalize`: locally map pseudonymized reports back to private named instructor outputs, rendering a human-readable `report.pdf` next to the machine-readable `report.json`, plus a single-table `final_report.pdf` overview of all students.

Prepare the pseudonymized workspace:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file assignment.pdf \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private
```

Multiple ZIP exports are supported with one `--input-file` argument followed by one or more ZIP paths:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file export1.zip export2.zip \
  --students-csv students.csv \
  --task-file assignment.pdf \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private
```

`prepare` currently:

- reads the private real `students.csv` locally;
- optionally prioritizes students from a private ordered-ID file;
- assigns deterministic pseudonyms in the resulting processing order, such as `Student 0001`;
- processes Moodle/Canvas-style ZIP exports with safe ZIP extraction;
- creates a pseudonymized agent workspace;
- writes private `pseudonym_map.csv` outside the workspace;
- writes private `preprocessing_report.md` outside the workspace;
- copies the assignment into the workspace with a canonical `task.*` filename, such as `task.tex` or `task.pdf`;
- extracts the assignment text locally and deterministically into `task_extracted.txt` (readable formats are decoded directly; PDFs via the `pypdf` dependency or a local `pdftotext` executable; no remote service, no OCR), preserving the canonical `task.*` untouched;
- copies the standalone `task_requirements_validator.py` helper into the workspace so `process.sh` can validate the shared requirements file without the source repository;
- generates pseudonymized `students.csv`;
- generates pseudonymized `associations.csv`;
- copies `templates/workspace/AGENTS.md` into the workspace as `AGENTS.md`;
- copies `templates/workspace/report_template.json` (the mandatory report schema) into the workspace;
- copies the standalone `report_validator.py` helper into the workspace so `process.sh` can validate reports without the source repository;
- renders executable `process.sh` (including the one-time assignment-analysis step);
- writes pseudonymized student-output copies for instructor/student review;
- writes private `student_outputs_index.csv`;
- excludes opaque documents by default.

Later ZIPs override earlier submissions for duplicate LMS student folders.

### Prioritize The Processing Order

By default, pseudonyms and `process.sh` commands follow `students.csv` order. To process selected students first, create a private, headerless text file with one exact `student_id` per line:

```text
63240017
63240003
63240041
```

Then pass it to `prepare`:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --student-order-file student-order.txt \
  --task-file assignment.pdf \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private
```

Listed students are moved to the front in file order and receive the first pseudonyms. Students omitted from the order file follow in their original CSV order. This option requires a `student_id` column in `students.csv`. The order file must be outside the workspace, is used locally, and is never copied into the pseudonymized workspace. Preparation fails if a listed ID is unknown, repeated in the order file, or non-unique in `students.csv`.

## Generated Outputs

Agent-facing workspace:

```text
lab-agent/
  AGENTS.md
  Student_0001.txt
  Student_0002.txt
  associations.csv
  process.sh
  processing_stats.json  # created and updated when process.sh runs
  report_template.json
  report_validator.py
  students.csv
  task.pdf
  task_extracted.txt        # local text extraction of the assignment (when extraction succeeds)
  task_requirements.json    # created by process.sh's one-time assignment analysis
```

Private instructor-only output:

```text
lab-private/
  preprocessing_report.md
  pseudonym_map.csv
  student_outputs/
    Student_0001.txt
    Student_0002.txt
  student_outputs_index.csv
```

The workspace `students.csv` contains only pseudonym data:

```csv
name,surname,full_name
Student,0001,Student 0001
Student,0002,Student 0002
```

`associations.csv` is generated locally by `prepare`. It maps each pseudonymized student to pseudonymized workspace filenames and never contains real names, emails, student IDs, or original LMS folder names.

The instructor assignment file is copied under a canonical non-private workspace name. For example, `assignment.pdf` becomes `task.pdf`, `task.tex` remains `task.tex`, and other suffixes become `task<suffix>`. The original assignment basename is not preserved.

In addition, `prepare` writes `task_extracted.txt`, a plain-text version of the assignment extracted locally and deterministically during preprocessing. Readable text formats are decoded with the repository's existing safe text decoding and line-ending normalization. PDFs are extracted with the `pypdf` dependency (or, if it is unavailable, with a locally detected `pdftotext` executable from poppler-utils). No remote service is contacted and no OCR is performed, so a scanned or image-only PDF cannot be extracted: in that case no `task_extracted.txt` is written, a warning is recorded in the private `preprocessing_report.md` (under "Assignment Extraction") and in the rendered `process.sh` statistics flag, and the canonical `task.*` file remains the assignment source. An empty or implausibly small PDF extraction is treated the same way - the tool never writes a misleading empty extraction artifact. Extraction is only a convenience for the agent: it does not grade anything and does not change what the human instructor must review.

`report_template.json` is the mandatory schema for every generated `report.json`. Each report assesses, for one student: whether the assignment was submitted, whether all required tasks are implemented (by what they do, not by function names), whether the code looks LLM-generated, and whether there are indications of copying code from another student (with the other student's pseudonym and line numbers in both submissions). The generated workspace `AGENTS.md` instructs the later assessment agent to follow this schema exactly.

`student_outputs/` contains pseudonymized copies of the same concatenated `Student_XXXX.txt` files that the agent sees. These files are intended as per-student review material that an instructor can retrieve and show individually. The private `student_outputs_index.csv` and `pseudonym_map.csv` identify which file belongs to which real student and must not be shared wholesale with students.

## Running The Agent Workflow

### What To Inspect Before Running The Agent

Before running `process.sh`, inspect:

- `workspace/lab-agent/` and confirm generated filenames are pseudonymized;
- `workspace/lab-agent/students.csv` and `workspace/lab-agent/associations.csv`;
- `workspace/lab-agent/report_template.json`;
- `workspace/lab-agent/task_extracted.txt`, when present;
- `workspace/lab-private/preprocessing_report.md`.

The agent-facing workspace should contain no real names, emails, student IDs, or original LMS folder names. The private report may contain real matching details and must remain local.

After `prepare` completes, run the generated script from inside the pseudonymized workspace:

```bash
cd workspace/lab-agent
./process.sh
```

`process.sh` detaches from the interactive terminal (`exec < /dev/null`), so each `codex exec` run exits on its own and the next student starts automatically. It runs one deterministic command per pseudonymized student in pseudonym order (the ordered-ID priority described above, then remaining CSV order):

```bash
run_planned_student "Student 0001" resolved codex -p qwen-neumann --ask-for-approval never -s workspace-write exec --skip-git-repo-check "Run submission assessment for Student 0001"
```

### Resumable Processing

Resumability is the default. Before invoking Codex for a student with associated submissions, `process.sh` validates the existing `<pseudonym>/report.json` with the workspace `report_validator.py` helper (the same structural contract `finalize` uses). A valid report is skipped without any Codex call; a report that is missing, malformed, structurally invalid, or belongs to another pseudonym is reprocessed. Students with no associated submissions are marked `unresolved` in `associations.csv` and receive a deterministic, neutral local report generated by `process.sh` itself, with no Codex call and no implication of misconduct. Rerunning `./process.sh` after a partial or failed run therefore only redoes the students that still lack a valid report.

Run `./process.sh --force` to regenerate reports even when a valid one already exists. `--force` also regenerates the shared `task_requirements.json` file even when a valid one already exists, and still never invokes Codex for unresolved students.

One failing student does not stop the later students: every planned student is attempted in order, and `process.sh` exits nonzero only after all planned students have been handled, if any attempted agent invocation failed.

Before any student that needs an agent invocation is processed, `process.sh` validates the shared `task_requirements.json` requirements file with the workspace `task_requirements_validator.py` helper. If the file is valid it is reused (`reused`); if it is missing or invalid, `process.sh` invokes Codex exactly once with the assignment-analysis command (`Analyze assignment requirements`), which reads only the assignment files, writes only `task_requirements.json`, and is validated before any student is processed (`generated`). The analysis is skipped entirely (`skipped`) when no student needs an agent invocation - for example when every student is unresolved or every student already has a valid report - so resumed runs never repeat it. If the analysis fails or produces invalid output, matched students without a valid report are recorded as `skipped_prerequisite_failed` and are not processed without the shared prerequisite; already valid student reports are preserved, unresolved students still receive their neutral local reports, and `process.sh` exits nonzero. The student assessment agents use `task_requirements.json` as their normal requirements source, consult the canonical `task.*` only when the structured artifact is ambiguous, and never treat the shared artifacts as submissions or modify them.

`process.sh` records its work in `processing_stats.json` (schema version 2), creating it at the start of each run and updating it atomically after every handled student, so a failed or interrupted run retains the latest completed update. It records only pseudonyms, per-student outcome (`agent_success`, `agent_failed`, `skipped_valid_report`, `generated_unresolved`, or `skipped_prerequisite_failed`), elapsed seconds and exit codes, plus planned/processed/success/failed counts, aggregate skipped and locally-generated counts, run status, total elapsed time, and average time per processed student. The one-time assignment analysis is recorded separately in an `assignment_analysis` block with its outcome (`reused`, `generated`, `failed`, or `skipped`), duration and exit code when an agent was invoked, and whether local extraction warnings were present. A resumed run describes the work performed in that invocation: reused reports are counted as skipped, not as newly produced. `finalize` accepts statistics from both the current version 2 and the earlier version 1 format, with or without the `assignment_analysis` block.

### Model Selection

The model used for submission analysis is not configured in this repository; it is whatever the Codex CLI runs with the profile rendered into `process.sh`. `prepare` renders the profile from `--codex-profile` (default `qwen-neumann`, the local Qwen 3.8 27B profile on Neumann) as `-p <profile>` in every Codex command. A profile is a `$CODEX_HOME/<profile>.config.toml` file (normally `~/.codex/<profile>.config.toml`); it is never copied into the generated workspace. Pass `--codex-profile none` to omit the flag and let Codex use its own default model, or `--codex-profile <other>` for a different local profile.

The reasoning effort is rendered the same way, from `--codex-reasoning-effort` as `-c model_reasoning_effort=<effort>` in every Codex command. The qwen-neumann model supports `low`, `medium`, and `xhigh`; higher values are more thorough but much slower per student, which matters when `process.sh` runs ~100 students. The default is `medium`; use `low` for the fastest full pass or `xhigh` for harder runs. Pass `--codex-reasoning-effort none` to omit the flag and fall back to the profile/CLI default. The one-command wrapper passes its optional third argument straight through to this option, e.g. `./activate_assignment.sh early-beta data_UZ/assignment_1 low`.

There is no agent-run Phase 1. Association generation is local preprocessing and is already complete before `process.sh` runs.

## Finalize Named Local Outputs

After the agent writes reports such as `Student 0001/report.json`, run:

```bash
python3 slaif-defense-grading.py finalize \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private \
  --output workspace/final
```

You can run `finalize` before `process.sh` has finished. Without `--strict`, it produces partial instructor outputs for valid reports already present, records unfinished students in `missing_reports.csv`, and shows `Unknown`/`No report` for them in the overview. It is safe to run the same command again later to refresh the output as more reports arrive. Do not use `--strict` for a partial run.

When `processing_stats.json` is available, the private `final_report.pdf` and `finalize_report.md` include its run status, the one-time assignment-analysis outcome when recorded, total and average times, per-student outcomes (version 2 statistics), and a per-student timing list resolved to private student names. Statistics from both the current version 2 and the earlier version 1 format are accepted; missing or malformed statistics are reported as unavailable and do not prevent finalization.

Final output is private/local and may contain real student identities:

```text
final/
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

`finalize` validates each `report.json` against the schema, maps pseudonymized reports and student-output text files back to real roster rows using the private maps, and renders the human-readable `report.pdf` (cross-referenced students are resolved to their real names in the private PDF). It does not modify the pseudonymized workspace. Use `--strict` if missing agent reports should make finalization fail. PDF rendering requires `fpdf2` (`pip install fpdf2`); without it the JSON output is still produced and the missing PDF is listed under "PDF Rendering Warnings" in `finalize_report.md`.

`finalize` also renders the final report: a single-table overview (`final_report.pdf`, machine-readable `final_report.csv`) with one row per roster student showing whether all tasks are implemented, whether there are reasonably strong indications of copying (with the cross-referenced student resolved to their real name; only the most obviously copied code is listed - very generic code such as imports, boilerplate, or standard display code never counts), whether there are reasonably strong indications of LLM use, and short paragraph notes. It is a fast reference for the teaching assistant when evaluating submissions in person with the student. Students without a valid agent report show `Unknown` and the note `No report`.

The same overview is also written as `final_report.html`: a self-contained local HTML viewer (open it in any browser, no server or network needed) built post festum solely from the final outputs. Besides the overview table it links to each student's full report (`report.pdf`/`report.json`) and to the exact lines of the source code referenced in the reports: own-submission lines, the other student's lines for suspected copying, and lines mentioned in notes, task evidence, or LLM indicators (each LLM indicator that references lines also gets its own code chip). Hovering over any code chip or line reference shows a small popup with the code at those lines. The highlighted lines are colored by which kind of link you opened them (own-submission copy link, other-student copy link, or note/reference link).

## What Can Be Shown To Students

`final/student_outputs/<Name>.txt` is the pseudonymized concatenated submission text that the agent saw. It may be shown individually to the corresponding student when useful for review.

`final/instructor_reports/<Name>/report.pdf` and `report.json` are instructor-facing. They contain assessments, indicators, and line-number evidence for human review, and should not be sent wholesale to students.

Do not share `pseudonym_map.csv`, `student_outputs_index.csv`, `final_index.csv`, or the final report (`final_report.pdf`/`final_report.csv`/`final_report.html`) wholesale with students.

## AGENTS.md Roles

There are two different `AGENTS.md` files:

- Root `AGENTS.md` is for coding agents modifying this repository.
- Generated workspace `AGENTS.md` is copied from `templates/workspace/AGENTS.md` and is for the later oral-verification/grading agent inside the pseudonymized workspace.

Preprocessing is not an agent task. The later agent should use `students.csv`, `associations.csv`, the generated assignment file (`task.tex`, `task.pdf`, or another `task.*`), and the shared `task_extracted.txt` and `task_requirements.json` artifacts, and should treat only files listed in `associations.csv` as student submissions.

There is no `.slaif_prompts/` directory.

## Privacy Model

The default workspace is pseudonymized text-only material.

- Real student identities may be used only during local preprocessing.
- The real input roster is never copied into the agent workspace.
- The private pseudonym map stays outside the workspace.
- Unmatched LMS folders are not copied into the workspace and appear only in the private report.
- Generated filenames, CSVs, shell scripts, `AGENTS.md`, and text/source/notebook files are leak-checked for known roster identifiers.
- `report_template.json` is copied into the workspace and included in the same text leak-check boundary.
- Known full names, emails, and `student_id` values are scrubbed from generated text outputs before the workspace leak check runs.
- Private `student_outputs/` files are pseudonymized copies of the generated agent input text files and must not contain real names, emails, student IDs, or LMS folder names.

Matching is conservative. LMS folders are matched to roster rows by exact normalized `name surname` from the folder prefix before the first Moodle underscore:

```text
Ana Novak_12345_assignsubmission_file -> Ana Novak
```

If the name prefix does not match, `prepare` falls back to explicit `=value` identifier tokens embedded in the LMS folder name, as produced by some LMS student-list exports:

```text
Ana Novak=ana.novak@example.invalid=63240001_92312_ab_cd
```

- `=value` tokens containing `@` are matched by exact email against the roster `email` column;
- leading digit runs of the remaining `=value` tokens are matched by exact `student_id` against the roster `student_id` column.

Identifier matching only succeeds when the identifier exists exactly once in the official roster and the email and id evidence agree; otherwise the folder stays unmatched and appears only in the private preprocessing report. Roster CSV files may be UTF-8 or UTF-16 (with or without BOM); a raw tab-separated LMS student list still needs to be converted to a comma-separated `name,surname,...` roster first (local instructor-side preprocessing).

## Opaque Documents

Opaque document files are excluded by default:

```text
.pdf
.docx
.doc
.odt
.rtf
```

They are excluded because this lightweight tool does not redact internal document content or metadata. Their existence is recorded in `private-output/preprocessing_report.md`.

This default exclusion applies to student-submitted opaque documents. The instructor-provided assignment may still be a PDF and is copied as `task.pdf`.

To explicitly include opaque documents under pseudonymized filenames:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file assignment.pdf \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private \
  --include-opaque-documents
```

This weakens the privacy guarantee. Copied opaque document filenames are pseudonymized, but PDF/DOCX/etc. internal content and metadata are not inspected or redacted.

## Testing And Audit Coverage

Tests use only synthetic data.

The end-to-end messy fixture covers:

- 5-student roster;
- nested ZIP submission;
- direct-folder submission;
- missing roster students;
- unmatched LMS folder;
- notebook JSON treated as text;
- Markdown, TeX, and source files;
- weird/non-ASCII filename;
- fake real identifiers requiring scrubbing;
- default-excluded opaque PDF;
- opt-in opaque document behavior;
- local deterministic assignment extraction (`task_extracted.txt`) with honest failure for text-less PDFs;
- one-time shared `task_requirements.json` analysis (validation, reuse, exactly-once generation, failure isolation, skip on resumed/unresolved-only runs).

Run tests with:

```bash
pytest
```

## Repository Structure

```text
README.md
AGENTS.md
QUICKSTART.md
requirements.txt
slaif-defense-grading.py

slaif_defense_grading/
  __init__.py
  cli.py
  core.py
  finalize.py
  io_utils.py
  models.py
  prepare.py
  process_script.py
  task_extract.py
  task_requirements.py

templates/
  process.sh.tpl
  workspace/
    AGENTS.md
    report_template.json

tests/
```

Install the minimal dependency set:

```bash
pip install -r requirements.txt
```

## Maintainer

Janez Perš  
Faculty of Electrical Engineering, University of Ljubljana  
Laboratory for Machine Intelligence (LMI)  
Email: janez.pers@fe.uni-lj.si  

- Profile: https://lmi.fe.uni-lj.si/en/janez-pers-2/
- Laboratory: https://lmi.fe.uni-lj.si/en

## Security Contact

For responsible disclosure of vulnerabilities, please contact:  
janez.pers@fe.uni-lj.si

## Acknowledgement

We acknowledge the support of the EC/EuroHPC JU and the Slovenian Ministry of HESI via the project SLAIF (grant number 101254461).

Project website: https://www.slaif.si
