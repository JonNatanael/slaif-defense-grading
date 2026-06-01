# slaif-defense-grading

`slaif-defense-grading` is a local command-line preprocessing tool for preparing lab-submission material for later human-led oral defense grading.

SLAIF stands for Slovenian AI Factory.

This repository is for local instructor-side preprocessing. It is not an automatic grading system, not an AI detector, not a plagiarism accusation tool, and not a fully automatic decision-maker.

## Privacy Boundary

The core safety boundary is local pseudonymization.

- Real student identities may be used only during local preprocessing.
- The later agent-facing workspace must contain only pseudonymized data.
- The private mapping from real identities to pseudonyms must stay outside the agent workspace.
- `process.sh` is rendered locally from `templates/process.sh.tpl`; the later agent does not create it.
- Do not commit real student rosters, submission ZIPs, generated outputs, or private mappings.

## Prepare Command

The primary workflow is:

```bash
python slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-03-agent \
  --private-output workspace/lab-03-private
```

Multiple input ZIPs are supported:

```bash
python slaif-defense-grading.py prepare \
  --input-file export1.zip export2.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-03-agent \
  --private-output workspace/lab-03-private
```

Later ZIPs override earlier submissions for duplicate LMS student folders, matching the retained legacy merge behavior.

The input `students.csv` must contain at least:

```csv
name,surname
Ana,Novak
Boris,Kovac
```

Optional columns such as `email` and `student_id` are preserved in the private pseudonym map. The real input roster is not copied into the agent workspace.

## Generated Outputs

Agent-facing workspace:

```text
workspace/lab-03-agent/
  students.csv
  task.tex
  process.sh
  Student_0001.txt
  Student_0001__document_001.pdf
```

Private instructor-only output:

```text
workspace/lab-03-private/
  pseudonym_map.csv
  preprocessing_report.md
```

The workspace `students.csv` contains only pseudonym data:

```csv
name,surname,full_name
Student,0001,Student 0001
Student,0002,Student 0002
```

`process.sh` contains one Phase 1 command and one Phase 2 command per pseudonymized student, in roster order.

## Matching And Privacy Checks

`prepare` matches LMS folders to roster rows by exact normalized `name surname` from the folder prefix before the first Moodle underscore. For example:

```text
Ana Novak_12345_assignsubmission_file -> Ana Novak
```

Unmatched LMS folders are not copied into the workspace. They are listed in the private `preprocessing_report.md`.

Text/source files are concatenated into pseudonymized files such as `Student_0001.txt`. Known roster full names, emails, and `student_id` values are scrubbed from generated text outputs before privacy checks run.

Before finishing, the command checks generated workspace filenames and generated text files for real full names, emails, and student IDs from the roster. If a leak is found, the command fails.

Binary document files such as `.pdf`, `.docx`, `.doc`, `.odt`, and `.rtf` may be copied with pseudonymized filenames. Their internal content is not inspected or redacted in this PR, so the private report includes a warning when documents are copied.

## Legacy Command

The previous ZIP concatenation flow is still available:

```bash
python slaif-defense-grading.py legacy \
  --input-file <MASTER1.zip> [<MASTER2.zip> ...] \
  (--output-file <OUTPUT.txt> | --output-directory <OUTPUT_DIR>) \
  [--similarity-check]
```

For compatibility, the legacy arguments also still work without the `legacy` subcommand:

```bash
python slaif-defense-grading.py \
  --input-file work/inputs/lab-05-export.zip \
  --output-file work/outputs/lab-05.txt
```

Legacy mode may derive labels from LMS folder names. Use `prepare` for the pseudonymized workspace workflow.

## Lightweight Repository Structure

```text
README.md
AGENTS.md
requirements.txt
slaif-defense-grading.py

slaif_defense_grading/
  __init__.py
  cli.py
  core.py
  io_utils.py
  models.py
  prepare.py
  process_script.py

templates/
  process.sh.tpl

tests/
```

No generated workspace `AGENTS.md` is used or documented.

## Development

Install the minimal development dependency set:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```
