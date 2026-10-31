# AGENTS.md

This file is for the assessment agent working inside this generated pseudonymized workspace.

Your job is to generate a submission assessment per student that helps the instructor prepare oral-verification questions and judge the work during human review. You produce indicators and evidence for human review, not findings of misconduct. Do not accuse AI use, plagiarism, unauthorized collaboration, or cheating, and do not grade automatically.

Preprocessing, roster matching, pseudonym mapping, `associations.csv` generation, and `process.sh` generation were already done locally by the instructor-side `prepare` command. Do not redo preprocessing and do not modify any preprocessing files.

Operate only in the current pseudonymized workspace. Do not infer, request, or reconstruct real student identities.

## Inputs

Use these workspace files:

- `students.csv` contains the pseudonymized roster.
- `associations.csv` maps each pseudonymized student to pseudonymized submission filenames.
- `task.*` contains the canonical assignment, usually `task.tex` or `task.pdf`; it is the authoritative assignment source and must never be modified.
- `task_extracted.txt` is a plain-text version of the canonical assignment that `prepare` extracted deterministically and locally during preprocessing. Use it for fast, consistent reading of the assignment. It is a shared artifact, not a submission. If it is absent (for example for a scanned PDF), fall back to reading `task.*` directly.
- `task_requirements.json` is the one-time shared analysis of what the assignment requires. It is generated at most once per run by the assignment-analysis command (see Command Scope) and reused by every student assessment. It is a shared artifact, not a submission.
- `comparison_candidates.json` is the local, high-recall similarity shortlist generated during preprocessing. For your target student it lists candidate submissions that share meaningful near-contiguous source blocks, with the individual-file line ranges to start from. It is a shared artifact and a routing hint, not a submission and not evidence of copying or misconduct.
- `report_template.json` is the mandatory schema for the report you must produce.

The only student submission files are the files listed in `associations.csv`.

If the generated task file is `task.pdf`, read it as PDF. Use the generated task file only as the assignment context.

Do not treat these files or directories as submissions:

- `AGENTS.md`
- `students.csv`
- `associations.csv`
- `task.*`
- `task_extracted.txt`
- `task_requirements.json`
- `comparison_candidates.json`
- `report_template.json`
- `process.sh`
- `report_validator.py`
- `task_requirements_validator.py`
- `processing_stats.json` (when present; it is maintained by `process.sh`)
- already generated report folders

## Command Scope

### Student assessment

Run only for the pseudonymized student named in the user command, for example:

```text
Run submission assessment for Student 0001
```

If the command does not identify exactly one pseudonymized student from `students.csv`, refuse and ask for a precise pseudonymized full name.

A student assessment reads the target student's associated files plus the shared assignment artifacts, and writes exactly that one student's report. It never writes `task_extracted.txt` or `task_requirements.json`.

`process.sh` only invokes you for students with associated submissions. Students with no associated files are `unresolved` in `associations.csv`; their neutral reports are generated deterministically and locally by `process.sh` itself, without any agent invocation. If you are ever invoked directly for such a student, still create the neutral report described under Output.

### Assignment analysis

The user command may instead be exactly:

```text
Analyze assignment requirements
```

This command analyzes only the assignment; it has nothing to do with any individual student:

- Read `task_extracted.txt` and/or the canonical `task.*` (for example to disambiguate the extracted text).
- Write exactly one file: `task_requirements.json`, following the schema described below.
- Do not inspect, read, or reference any student submission files.
- Do not create or modify any student report.
- Do not modify `task.*`, `task_extracted.txt`, or any preprocessing file.
- Do not infer, request, or reference any student identities.
- Describe what the assignment requires by required behavior, not by prescribed function or file names where the assignment does not require them.
- Record ambiguity (for example extraction warnings or unclear requirement text) in `notes` instead of inventing requirements or references.

`process.sh` invokes this command at most once per run, before any student assessment, and reuses an already valid `task_requirements.json` instead of re-invoking it.

The structured format of `task_requirements.json` is:

```json
{
  "schema_version": 1,
  "requirements": [
    {
      "id": "task-001",
      "description": "What the assignment requires, expressed by behavior",
      "source_reference": "page, section, or extracted-text line reference"
    }
  ],
  "notes": ""
}
```

- `schema_version` must be `1`.
- `requirements` is a list; it must be nonempty when assignment requirements can be identified (an empty list is only acceptable with a `notes` value explaining why nothing could be identified).
- Every entry needs a nonempty string `id`, a nonempty string `description`, and a nonempty string `source_reference`.
- `id` values must be unique and deterministic within the file (for example `task-001`, `task-002`, in assignment order).
- `source_reference` points into the assignment itself (for example a `task_extracted.txt` line, a `task.tex` section, or a `task.pdf` page) so a student assessment can verify the requirement.
- `notes` is a string; use it for ambiguity or extraction warnings.

## Association Rules

For the target student:

- Find the matching row in `associations.csv`.
- Use only files listed in that row's `all_associated_files`.
- If `all_associated_files` is empty, still create the output file as described below.

For requirement identification:

- Use `task_requirements.json` as the normal source of what the assignment requires, and use its requirement descriptions to populate `task_details`.
- Consult the canonical `task.*` only when the structured artifact is ambiguous, missing, or lacks detail needed for the report.
- Never treat `task_extracted.txt` or `task_requirements.json` as a student submission, and never modify them during a student run.

For copying indications:

- Read only the target student's entries in `comparison_candidates.json`; do not compare the target against every other resolved submission.
- Inspect only the listed candidate submissions for copying indications, starting from the referenced matching blocks and reading enough surrounding context to judge whether the similarity is distinctive and non-generic.
- Candidate scores and matching blocks are routing hints from a local heuristic, not evidence: never copy a candidate score into `code_copy_indications`, and keep the existing high evidence bar before reporting an indication.
- If the target has no candidate entries, or no candidate survives detailed inspection, leave `code_copy_indications` empty. Do not fall back to scanning the entire cohort: the shortlist is a deliberate performance/recall tradeoff, and students who are not listed as candidates (including unresolved students) must not be inspected for copying.
- Use the generated assignment file, usually `task.tex` or `task.pdf`, so assignment-required overlap is not reported as distinctive or as copying (assignment-provided material is already filtered from the shortlist heuristically).

Line numbers always refer to the individual submission file (the path after `| submission |` in the `==== BEGIN ... ====` markers of the concatenated text file), counted from the first line of that file - not to the concatenated file itself.

## Output

Write exactly one file per run:

```text
<Full Name>/report.json
```

Here `<Full Name>` is the pseudonymized full name from `students.csv`, for example:

```text
Student 0001/report.json
```

`report_template.json` is the mandatory schema. Follow it exactly: the same top-level keys, the same types. Do not create PDF files or any other report files; the instructor's `finalize` step renders the human-readable per-student PDF locally, plus a single-table final overview PDF (`final_report.pdf`) summarizing all students for the teaching assistant.

Field meanings (every value is an instructor-facing indicator for human review, grounded in the associated files):

- `assignment_submitted` (true/false): whether the associated submission files contain a substantive attempt at the assignment.
- `all_tasks_implemented` (true/false/unknown): identify the required tasks from `task_requirements.json` (consult `task.*` only when the structured artifact is ambiguous or lacks detail) by what they ask for to be done; specific function naming does not matter, only what the code does. Set `false` if any required task is missing, `unknown` if you cannot tell (for example an unreadable or empty submission).
- `task_details`: one entry per required task (from `task_requirements.json`): what the task asks, whether it is implemented, and evidence (file and line reference).
- `looks_llm_generated` (likely/unlikely/uncertain) and `llm_generation_indicators`: concrete indicators (for example uniform style, generic or over-polished comments, structure and boilerplate, suspicious consistency) with file and line references. Mark it `likely` only when reasonably strong indicators are present; weak or isolated observations should stay `uncertain`. This is an assessment for the instructor, not an accusation.
- `code_copy_indications`: for each concrete indication that this submission shares code with another resolved submission, list `other_student_pseudonym` (the other student's pseudonym from `students.csv`), the file and 1-based line range in this submission, the file and 1-based line range in the other submission, and the evidence. The bar is deliberately high: only the most obviously copied code qualifies as a reasonably strong indication. List an indication only for a substantial, non-generic stretch of shared code - a contiguous block of non-trivial custom logic (roughly 10 or more consecutive lines) that two students would be unlikely to write independently, or a distinctive non-obvious implementation (unusual algorithm, distinctive structure, or identical variable names or comments on custom code). Never list very generic code, even when it is identical across several submissions: import statements; standard boilerplate and setup; standard display and plotting code (figure creation, `plt.show()`, `cv2.imshow()`, window creation, saving or showing images); code that the assignment itself mandates or provides (starter code, required function signatures, task-specified constants); similar standard library or framework API calls; common idioms. If the shared code is something any competent student could plausibly have written independently, do not list it. Use an empty list unless the shared code is obviously copied.
- `notes`: optional short instructor-facing note, written as a paragraph: a few connected sentences (not a list of fragments or one-line bullets) summarizing what matters most for the oral defense, such as the student's individual angle, the main observations behind the indicators above, and what to probe verbally.

Every claim must be grounded in the target student's associated files or in the other students' associated files listed in `associations.csv`. Do not invent evidence, line numbers, or indicators that are not grounded in the associated files.

If no submission files are associated, still create `<Full Name>/report.json` following the template with `assignment_submitted: false`, `all_tasks_implemented: "unknown"`, `looks_llm_generated: "uncertain"`, empty `llm_generation_indicators` and `code_copy_indications`, and a `notes` entry explaining that no submission material was found.

## Modification Rules

Do not modify preprocessing files:

- `AGENTS.md`
- `students.csv`
- `associations.csv`
- `task.*`
- `task_extracted.txt` (shared local extraction of the assignment; only `prepare` creates it)
- `task_requirements.json` (shared one-time assignment analysis; only the assignment-analysis command creates or replaces it, atomically)
- `comparison_candidates.json` (shared local similarity shortlist; only `prepare` creates it)
- `report_template.json`
- `process.sh`
- `report_validator.py`
- `task_requirements_validator.py`
- `processing_stats.json` (when present; it is maintained by `process.sh`)

Only create or update the target student's report folder and files needed for that report; the assignment-analysis command only creates or replaces `task_requirements.json`.
