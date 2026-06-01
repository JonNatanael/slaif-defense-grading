# AGENTS.md

This file is for coding agents working on the `slaif-defense-grading` repository.

It is not for the later student-submission processing workspace.

Do not create or maintain a second `AGENTS.md` for generated workspaces unless explicitly requested by the repository owner.

Preprocessing is run locally by the instructor from the command line.

---

## Project purpose

`slaif-defense-grading` prepares pseudonymized lab-submission workspaces for later AI-assisted oral defense grading.

The project’s job is local preparation:

- read the real student roster locally;
- assign pseudonyms;
- extract and normalize submission files;
- create a pseudonymized workspace;
- create a private pseudonym map outside that workspace;
- render a ready-to-run `process.sh` from a template.

The project is not an automatic grading system and not an AI-use detector.

---

## Non-negotiable privacy boundary

Real student identities must not enter the generated agent workspace.

The local input roster may contain real names, emails, IDs, and LMS identifiers.

The generated workspace must contain only pseudonyms such as:

```text
Student 0001
Student 0002
S0001
S0002
```

The private mapping from real identities to pseudonyms must be written outside the agent workspace.

Do not add features that require the later agent to see real names.

Do not add examples, tests, fixtures, screenshots, or documentation containing real student data.

---

## No workspace AGENTS.md

The repository-level `AGENTS.md` is only for coding agents modifying this repository.

Do not add this structure:

```text
templates/agent-workspace/AGENTS.md
```

The generated workspace should be driven by:

```text
process.sh
students.csv
task.tex
pseudonymized submission files
```

The shell script should be rendered locally by the preprocessing command.

The agent should not be responsible for writing a new batch script.

---

## Entry point cleanup

Do not keep duplicate top-level scripts.

The old prototype had both:

```text
preprocess-labs.py
preprocesslabs.py
```

They should be replaced by one canonical entrypoint:

```text
slaif-defense-grading.py
```

The implementation should live in an importable package:

```text
slaif_defense_grading/
```

Avoid imports such as:

```python
from src.preprocesslabs.cli import main
```

Use a normal package import from the cleaned-up package.

---

## Target repository structure

Aim for this lightweight structure:

```text
README.md
AGENTS.md
requirements.txt
slaif-defense-grading.py

slaif_defense_grading/
  __init__.py
  cli.py
  lms.py
  pseudonymize.py
  workspace.py
  process_script.py
  files.py
  models.py

templates/
  process.sh.tpl

tests/
```

Keep the project small.

A `requirements.txt` file is sufficient for now.

Do not add a full packaging setup unless explicitly requested.

---

## Command-line behavior

The main command should prepare a pseudonymized workspace.

Target shape:

```bash
python slaif-defense-grading.py prepare \
  --input-file moodle_export.zip \
  --students-csv students.csv \
  --task-file task.tex \
  --workspace workspace/lab-03-agent \
  --private-output workspace/lab-03-private
```

The command should write:

```text
workspace/lab-03-agent/
  students.csv
  task.tex
  process.sh
  Student_0001.txt
  Student_0001__report.pdf
  ...

workspace/lab-03-private/
  pseudonym_map.csv
  preprocessing_report.md
```

The real input `students.csv` must not be copied into the workspace.

The workspace `students.csv` must be pseudonymized.

---

## Process script rule

`process.sh` must be rendered from `templates/process.sh.tpl`.

The generated script should:

- be valid Bash;
- use `set -euo pipefail`;
- run the later agent commands in deterministic order;
- preserve the order of the pseudonymized `students.csv`;
- contain only pseudonymized student names;
- not require real identity data.

Do not reintroduce a workflow where the agent writes `process.sh`.

---

## Pseudonymization requirements

Use deterministic pseudonyms for a single run.

Recommended format:

```text
Student 0001
Student 0002
Student 0003
```

The generated workspace `students.csv` should contain only pseudonym data.

Example:

```csv
name,surname,full_name
Student,0001,Student 0001
Student,0002,Student 0002
```

The private map should contain the real identity and pseudonym.

Example private map:

```csv
pseudonym,name,surname,email,student_id
Student 0001,Ana,Novak,ana.novak@example.invalid,63240001
Student 0002,Blaž,Kovač,blaz.kovac@example.invalid,63240002
```

The private map must be written outside the agent workspace.

---

## File handling rules

Operate only on explicit input files and explicit output directories.

Use safe ZIP extraction with path-traversal protection.

Be conservative with filename-based identity matching.

Prefer the official `students.csv` over heuristics.

Do not silently invent student identities.

Do not recursively delete anything outside controlled temporary or output directories.

Readable source files should include common lab formats such as:

```text
.txt
.py
.m
.c
.h
.cpp
.hpp
.ipynb
.md
.tex
```

Student-linked document files should be preserved and copied under pseudonymized names when relevant:

```text
.pdf
.docx
.doc
.odt
.rtf
```

Binary files should not be concatenated as text.

---

## Determinism

Behavior should be deterministic.

Use stable sorting for:

- students;
- files;
- ZIP entries;
- generated filenames;
- generated process-script commands.

Generated pseudonyms should follow the input CSV order unless an explicit option says otherwise.

---

## Testing requirements

Use only synthetic data.

Important tests:

- duplicate old entrypoints are removed or intentionally handled;
- CLI help works;
- safe extraction rejects path traversal;
- Moodle-style folders are parsed correctly;
- direct submission folders work;
- nested ZIP submissions work;
- multiple input ZIPs work;
- pseudonyms follow CSV order;
- private pseudonym map is written outside the workspace;
- real names do not appear in workspace filenames;
- real names do not appear in workspace `students.csv`;
- real names do not appear in generated `process.sh`;
- document files are copied under pseudonymized names;
- binary files are skipped;
- generated `process.sh` is executable or clearly documented as needing `chmod +x`.

Tests should run with:

```bash
pytest
```

---

## Documentation rules

Keep `README.md` aligned with actual behavior.

If a command is not implemented yet, mark it as intended or planned.

When changing output layout, update:

```text
README.md
templates/process.sh.tpl
tests/
```

Do not document a generated workspace `AGENTS.md`.

Do not imply that preprocessing is agent-run.

---

## Git hygiene

Do not commit generated workspaces, private mappings, real rosters, or submission ZIPs.

Recommended ignored paths:

```text
work/
workspace/
private/
*.zip
pseudonym_map.csv
preprocessing_report.md
```

Synthetic fixtures are allowed under `tests/fixtures/`.

Real student material is not.

---

## Wording

Use language that reflects human oversight.

Prefer:

- “oral-verification questions”
- “instructor-facing report”
- “pseudonymized workspace”
- “local preprocessing”
- “human review”

Avoid:

- “AI detector”
- “cheating detector”
- “automatic conviction”
- “fully automatic grading decision”

---

## Pull request style

Keep cleanup changes focused.

A good first cleanup PR would:

1. rename the project in README;
2. add this repository-level `AGENTS.md`;
3. remove the duplicate entrypoint;
4. introduce the new package name;
5. add `templates/process.sh.tpl`;
6. add or update `.gitignore`;
7. add synthetic tests for the privacy boundary.

Do not combine a large behavior change with unrelated formatting churn.
