<div style="text-align: center;">
  <a href="https://www.slaif.si">
    <img src="https://slaif.si/img/logos/SLAIF_logo_ANG_barve.svg" width="400" height="400">
  </a>
</div>

# SLAIF Defense Grading

`slaif-defense-grading` is a local command-line preprocessing tool for preparing pseudonymized lab-submission workspaces for later human-led oral defense grading.

SLAIF stands for Slovenian AI Factory.

This project is not an automatic grading system, not an AI detector, not a plagiarism accusation tool, and not a fully automatic decision-maker.

For a complete step-by-step run, see [QUICKSTART.md](QUICKSTART.md).

## Current Workflow

Preprocessing is run locally by the instructor:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private
```

Multiple ZIP exports are supported with one `--input-file` argument followed by one or more ZIP paths:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file export1.zip export2.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private
```

`prepare` currently:

- reads the private real `students.csv` locally;
- assigns deterministic pseudonyms in CSV order, such as `Student 0001`;
- processes Moodle/Canvas-style ZIP exports with safe ZIP extraction;
- creates a pseudonymized agent workspace;
- writes private `pseudonym_map.csv` outside the workspace;
- writes private `preprocessing_report.md` outside the workspace;
- copies `task.tex` into the workspace;
- generates pseudonymized `students.csv`;
- generates pseudonymized `associations.csv`;
- copies `templates/workspace/AGENTS.md` into the workspace as `AGENTS.md`;
- copies `templates/workspace/report_aspects_template.md` into the workspace;
- renders executable `process.sh`;
- writes pseudonymized student-output copies for instructor/student review;
- writes private `student_outputs_index.csv`;
- excludes opaque documents by default.

Later ZIPs override earlier submissions for duplicate LMS student folders.

## Generated Outputs

Agent-facing workspace:

```text
lab-agent/
  AGENTS.md
  Student_0001.txt
  Student_0002.txt
  associations.csv
  process.sh
  report_aspects_template.md
  students.csv
  task.tex
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

`report_aspects_template.md` defines the mandatory structure for every generated `report_aspects.md`. The generated workspace `AGENTS.md` instructs the later grading agent to follow this template and preserve its headings.

`student_outputs/` contains pseudonymized copies of the same concatenated `Student_XXXX.txt` files that the agent sees. These files are intended as per-student review material that an instructor can retrieve and show individually. The private `student_outputs_index.csv` and `pseudonym_map.csv` identify which file belongs to which real student and must not be shared wholesale with students.

## Running The Agent Workflow

After `prepare` completes, run the generated script from inside the pseudonymized workspace:

```bash
cd workspace/lab-agent
./process.sh
```

`process.sh` runs one Codex command per pseudonymized student in roster order:

```bash
codex --ask-for-approval never --full-auto exec --skip-git-repo-check "Run oral-verification report for Student 0001"
```

There is no agent-run Phase 1. Association generation is local preprocessing and is already complete before `process.sh` runs.

## Finalize Named Local Outputs

After the agent writes reports such as `Student 0001/report_aspects.md`, run:

```bash
python3 slaif-defense-grading.py finalize \
  --workspace workspace/lab-agent \
  --private-output workspace/lab-private \
  --output workspace/final
```

Final output is private/local and may contain real student identities:

```text
final/
  final_index.csv
  finalize_report.md
  missing_reports.csv
  instructor_reports/
    Mila_Kranjc/
      report_aspects.md
  student_outputs/
    Mila_Kranjc.txt
```

`finalize` maps pseudonymized reports and student-output text files back to real roster rows using the private maps. It does not modify the pseudonymized workspace. Use `--strict` if missing agent reports should make finalization fail.

## AGENTS.md Roles

There are two different `AGENTS.md` files:

- Root `AGENTS.md` is for coding agents modifying this repository.
- Generated workspace `AGENTS.md` is copied from `templates/workspace/AGENTS.md` and is for the later oral-verification/grading agent inside the pseudonymized workspace.

Preprocessing is not an agent task. The later agent should use `students.csv`, `associations.csv`, and `task.tex`, and should treat only files listed in `associations.csv` as student submissions.

There is no `.slaif_prompts/` directory.

## Privacy Model

The default workspace is pseudonymized text-only material.

- Real student identities may be used only during local preprocessing.
- The real input roster is never copied into the agent workspace.
- The private pseudonym map stays outside the workspace.
- Unmatched LMS folders are not copied into the workspace and appear only in the private report.
- Generated filenames, CSVs, shell scripts, `AGENTS.md`, and text/source/notebook files are leak-checked for known roster identifiers.
- `report_aspects_template.md` is copied into the workspace and included in the same text leak-check boundary.
- Known full names, emails, and `student_id` values are scrubbed from generated text outputs before the workspace leak check runs.
- Private `student_outputs/` files are pseudonymized copies of the generated agent input text files and must not contain real names, emails, student IDs, or LMS folder names.

Matching is conservative. LMS folders are matched to roster rows by exact normalized `name surname` from the folder prefix before the first Moodle underscore:

```text
Ana Novak_12345_assignsubmission_file -> Ana Novak
```

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

To explicitly include opaque documents under pseudonymized filenames:

```bash
python3 slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file task.tex \
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
- opt-in opaque document behavior.

Run tests with:

```bash
pytest
```

## Legacy Command

The previous ZIP concatenation flow is still available:

```bash
python3 slaif-defense-grading.py legacy \
  --input-file <MASTER1.zip> [<MASTER2.zip> ...] \
  (--output-file <OUTPUT.txt> | --output-directory <OUTPUT_DIR>) \
  [--similarity-check]
```

For compatibility, the legacy arguments also still work without the `legacy` subcommand:

```bash
python3 slaif-defense-grading.py \
  --input-file work/inputs/lab-05-export.zip \
  --output-file work/outputs/lab-05.txt
```

Legacy mode may derive labels from LMS folder names. Use `prepare` for the pseudonymized workspace workflow.

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

templates/
  process.sh.tpl
  workspace/
    AGENTS.md
    report_aspects_template.md

tests/
```

Install the minimal dependency set:

```bash
pip install -r requirements.txt
```
