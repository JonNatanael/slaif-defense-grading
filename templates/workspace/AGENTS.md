# AGENTS.md

Codex acts as a grading assistant over student submission files in the **current directory**.

Primary sources are:
- submission `.txt` files
- student-linked document files such as `.pdf`, `.docx`, `.doc`, `.odt`, `.rtf`, `.md`, `.tex`

A document file that clearly belongs to the same student must be treated as part of that student's submission, together with the `.txt` file if the `.txt` exists, or as the **only** submission material if no `.txt` exists.

The `.txt` files may be concatenated exports built from multiple source files and may contain explicit delimiters such as `==== BEGIN Name Surname | submission | path ====`, with embedded student/submission/path metadata. Use such metadata when present. Also use filename hints and explicit author statements inside files.

Keep the workflow compact, deterministic, and conservative:
- operate only in the current directory;
- prefer explicit evidence over heuristics;
- do not guess authorship when evidence is weak;
- for joint files, allow the same file to be associated with more than one student;
- treat all associated files for one student as one combined submission package.

Ignore these non-submission files when scanning candidate files:
- `students.csv`
- `associations.csv`
- `task.tex`
- `process.sh`
- `AGENTS.md`
- phase output files created by this workflow

---

## Inputs

Required:
- `students.csv` — canonical list of students
- `task.tex` — assignment text
- one or more submission files in the current directory

---

## Phase 1

### Trigger
Run when the user writes:

`Phase 1`

### Goal
Build a reliable mapping from students in `students.csv` to all submission files in the current directory that belong to them, including:
- `.txt` submissions
- student-linked `.pdf`, `.docx`, and similar document files

Also delete image files from the current directory before building the mapping.

### Required actions

1. **Delete image files in the current directory**
   Delete all image files in the current working directory:
   - `*.png`, `*.jpg`, `*.jpeg`, `*.webp`, `*.gif`, `*.bmp`, `*.tif`, `*.tiff`, `*.svg`
   Only delete files in the current directory itself, not recursively.

2. **Read `students.csv`**
   Extract the canonical list of students from `students.csv`.
   Treat each student as a distinct `(name, surname)` pair.

3. **Discover candidate submission files**
   Consider candidate files in the current directory with extensions:
   - `.txt`
   - `.pdf`
   - `.docx`
   - `.doc`
   - `.odt`
   - `.rtf`
   - `.md`
   - `.tex`

   Exclude workflow/generated files and global task files.

4. **Associate students to files**
   For each student, find all files that most likely belong to that student, using descending priority:
   - explicit author name inside the file,
   - explicit name in `.txt` BEGIN/END delimiter metadata,
   - explicit author hint in filename,
   - strong internal evidence of joint authorship,
   - weaker but still traceable textual/structural hints.

   Rules:
   - a student may be associated with multiple files;
   - the same file may be associated with multiple students if joint authorship is clear;
   - if a `.pdf`, `.docx`, or similar document clearly belongs to a student, include it as part of the submission package;
   - if no `.txt` exists but one or more document files clearly belong to the student, those documents still count as the student's submission material;
   - if evidence is insufficient, mark the association as unresolved instead of guessing.

5. **Write `associations.csv`**
   Create `associations.csv` with one row per student.

### Required columns in `associations.csv`

Use these columns exactly:
- `name`
- `surname`
- `full_name`
- `associated_txt_files`
- `associated_document_files`
- `all_associated_files`
- `status`
- `evidence`

Where:
- `associated_txt_files` is a semicolon-separated list of associated `.txt` files, or empty;
- `associated_document_files` is a semicolon-separated list of associated `.pdf` / `.docx` / similar document files, or empty;
- `all_associated_files` is the union of both lists, semicolon-separated, or empty;
- `status` is one of:
  - `matched`
  - `matched_joint`
  - `ambiguous`
  - `unresolved`
- `evidence` is a short plain-text justification naming the strongest evidence used.

### Constraints
- Do not modify submission files.
- Do not create per-student analysis yet.
- Do not invent associations when evidence is weak.

---

## Phase 2

### Trigger
Run only when the user explicitly provides the student's **name and surname**:

`Phase 2 <Name> <Surname>`

or another unambiguous command identifying exactly one student.

### Refusal rule
If the full student name is not given, refuse.
If the student cannot be identified uniquely in `students.csv`, refuse.
If `associations.csv` is missing, refuse.
If `task.tex` is missing, refuse.

### Goal
Identify three aspects of the target student's **solution/report content** that stand out compared with the solutions of other students, then generate three oral-verification questions and three expected answers.

This phase must use:
- the student's associated `.txt` file(s), if any;
- the student's associated `.pdf`, `.docx`, or similar document file(s), if any;
- `task.tex`, to understand what is expected from the assignment and to distinguish normal task-driven overlap from genuinely distinctive solution aspects.

### Inputs used by Phase 2

For the target student:
- `associations.csv`
- `task.tex`
- all files listed for that student in `all_associated_files`

For comparison:
- `task.tex`
- all associated files of all other students with resolved associations

Use the student's **entire associated submission package**, not only `.txt`.

### No-submission rule
If the target student has no associated files in `associations.csv`, do **not** refuse.
Instead:
- create a folder named exactly `<Name> <Surname>/`
- create `report_aspects.md`
- write clearly in Slovenian that no submission material was found for this student
- optionally write `phase2_notes.txt`

### Comparison logic
Read `task.tex` first and use it to understand the assignment requirements.

Then compare the target student's associated submission package against the associated submission packages of the other students.

The comparison must be semantic and content-based.
When judging distinctiveness, discount elements that are simply expected because they directly follow from `task.tex`.

Look for aspects that meaningfully stand out, such as:
- uniquely specific insight,
- distinctive commentary,
- unusually concrete interpretation,
- unusually strong explanation of method or result,
- characteristic limitation discussion,
- special narrative structure,
- especially informative comparison,
- a distinctive argument or conclusion.

If a `.txt` file and a document file both exist for the same student, treat them jointly as one submission.
If only document files exist, use those as the only submission material.

### Output
Create a folder named exactly:

`<Name> <Surname>/`

Inside it create:
- `report_aspects.md`
- optional `phase2_notes.txt`

### Required content of `report_aspects.md`
Write in **Slovenian**.
Create exactly **three numbered items** when enough evidence exists.

For each item include these subsections:
1. `Vidik poročila oziroma rešitve`
2. `Zakaj ta vidik izstopa`
3. `Vprašanje za študenta`
4. `Pričakovani odgovor`

### Rules for the three items

#### Vidik poročila oziroma rešitve
Name the distinctive aspect clearly and concretely.

#### Zakaj ta vidik izstopa
Explain specifically why it stands out relative to the associated submission packages of the other students, taking `task.tex` into account.

#### Vprašanje za študenta
Write a detailed Slovenian question about that aspect.
The question must target the student's own submitted material.
It may point to a passage, claim, argument, interpretation, comparison, limitation, conclusion, or other clearly present part of the student's associated files.

#### Pričakovani odgovor
Write the expected Slovenian answer for instructor use.
Ground it in the target student's actual associated submission files.
It should be detailed enough to let the instructor judge whether the student really understands what was submitted.

### Quality constraints
- Identify exactly three aspects if possible; if fewer are supportable, give the strongest available and explain the limitation in `phase2_notes.txt`.
- Compare against **all other available students** with resolved associations, not a small arbitrary subset.
- Use `task.tex` actively to avoid calling a merely assignment-mandated element "unique".
- Do not claim uniqueness without a comparison basis.
- Do not generate generic theory questions detached from the student's own files.
- Do not expose the expected answers to the student during questioning.
- Prefer conservative judgments over inflated distinctiveness.

### Summary
Phase 1 builds `associations.csv` over both `.txt` and student-linked document files.
Phase 2 uses `associations.csv`, `task.tex`, and the target student's full associated submission package, compares it to the other students' packages, and produces instructor-facing oral-verification material.

---

## Phase 3

### Trigger
Run when the user writes:

`Phase 3`

### Goal
Prepare and write a shell script `process.sh` that calls Codex once per student found in `students.csv`, always for **Phase 2**.

Phase 3 only **writes** the script.
It does **not** execute it.

### Required actions

1. Read `students.csv`.
2. Preserve the order of students from `students.csv`.
3. Create `process.sh` in the current directory.
4. Write one Codex command per student, in CSV order, using this exact form:

```bash
codex --ask-for-approval never --full-auto exec --skip-git-repo-check "Run Phase 2 for Name Surname"
```

where `Name Surname` is replaced with the student's actual full name.

5. The script must begin with:

```bash
#!/bin/bash
```

6. Make the file content valid shell script text.

### Notes
- Phase 3 does not decide whether a student submitted anything.
- It still writes a command for every student in `students.csv`.
- Missing submission handling is done later by Phase 2.

### Output
Create:

- `process.sh`

### Summary
Phase 3 generates a batch shell script that sequentially asks Codex to run Phase 2 for every student listed in `students.csv`.
