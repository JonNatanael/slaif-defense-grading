# slaif-defense-grading

`slaif-defense-grading` is a local command-line preprocessing tool for preparing lab-submission material for later human-led oral defense grading.

SLAIF stands for Slovenian AI Factory.

This repository is for local instructor-side preprocessing. It is not an automatic grading system, not an AI detector, not a plagiarism accusation tool, and not a fully automatic decision-maker.

## Privacy boundary

The core safety boundary in this project is local pseudonymization.

- Real student identities may be used only during local preprocessing.
- The later agent-facing workspace must contain only pseudonymized data.
- The private mapping from real identities to pseudonyms must stay outside the agent workspace.
- Do not commit real student rosters, submission ZIPs, generated outputs, or private mappings to this repository.

The current prototype behavior retained in this cleanup PR still works on raw Moodle/Canvas-style exports and may derive labels from LMS folder names. That legacy behavior is preserved for continuity, but it is not the final privacy model.

## Current behavior

Today, the canonical entrypoint is:

```bash
python slaif-defense-grading.py --help
```

The current CLI preserves the existing preprocessing behavior:

- accepts one or more master ZIP exports;
- safely extracts ZIP contents with path-traversal protection;
- finds nested submission ZIPs or direct submission folders;
- collects readable source files;
- writes either one combined text output or one output per student;
- optionally groups near-identical submissions;
- copies PDFs alongside per-student outputs.

This is still the old preprocessing flow. It has been renamed and reorganized, but not yet replaced by the planned pseudonymized workspace generator.

## Planned direction

The intended next-step interface is planned, not implemented in this PR:

```bash
python slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-03-agent \
  --private-output workspace/lab-03-private
```

Target output shape:

```text
workspace/lab-03-agent/
  students.csv
  task.tex
  process.sh
  Student_0001.txt
  Student_0001__report.pdf

workspace/lab-03-private/
  pseudonym_map.csv
  preprocessing_report.md
```

That planned workflow will:

- keep the real `students.csv` local;
- generate a pseudonymized workspace for later agent use;
- render `process.sh` locally from a template;
- avoid exposing real names in workspace filenames or workspace metadata.

## Current command usage

```bash
python slaif-defense-grading.py \
  --input-file <MASTER1.zip> [<MASTER2.zip> ...] \
  (--output-file <OUTPUT.txt> | --output-directory <OUTPUT_DIR>) \
  [--similarity-check]
```

Arguments:

- `-i, --input-file`: one or more master ZIP files.
- `-o, --output-file`: write one combined output file.
- `-d, --output-directory`: write one output file per student.
- `--similarity-check`: group near-identical submissions before building a combined output file.

Examples:

```bash
mkdir -p work/outputs

python slaif-defense-grading.py \
  --input-file work/inputs/lab-05-export.zip \
  --output-file work/outputs/lab-05.txt
```

```bash
mkdir -p work/outputs/lab-05

python slaif-defense-grading.py \
  --input-file work/inputs/lab-05-export.zip \
  --output-directory work/outputs/lab-05
```

Recommended local layout:

```text
work/
  inputs/
    lab-05-export.zip
  outputs/
    lab-05.txt
```

Keep `work/` outside Git history.

## Lightweight repository structure

This cleanup PR moves the repository toward this small structure:

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

templates/
  process.sh.tpl

tests/
```

The current package still retains the legacy processing modules while the broader pseudonymized-workspace refactor is pending.

## Safety notes

- ZIP extraction is guarded against path traversal.
- Binary files are skipped from text concatenation.
- Current legacy outputs may still include LMS-derived student labels, so run the tool only on local instructor-controlled data.
- Use only synthetic data in tests and examples committed to this repository.

## Development

Install the minimal development dependency set:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```
