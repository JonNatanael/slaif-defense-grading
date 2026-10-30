# AGENTS.md

This file is for the assessment agent working inside this generated pseudonymized workspace.

Your job is to generate a submission assessment per student that helps the instructor prepare oral-verification questions and judge the work during human review. You produce indicators and evidence for human review, not findings of misconduct. Do not accuse AI use, plagiarism, unauthorized collaboration, or cheating, and do not grade automatically.

Preprocessing, roster matching, pseudonym mapping, `associations.csv` generation, and `process.sh` generation were already done locally by the instructor-side `prepare` command. Do not redo preprocessing and do not modify any preprocessing files.

Operate only in the current pseudonymized workspace. Do not infer, request, or reconstruct real student identities.

## Inputs

Use these workspace files:

- `students.csv` contains the pseudonymized roster.
- `associations.csv` maps each pseudonymized student to pseudonymized submission filenames.
- `task.*` contains the assignment, usually `task.tex` or `task.pdf`.
- `report_template.json` is the mandatory schema for the report you must produce.

The only student submission files are the files listed in `associations.csv`.

If the generated task file is `task.pdf`, read it as PDF. Use the generated task file only as the assignment context.

Do not treat these files or directories as submissions:

- `AGENTS.md`
- `students.csv`
- `associations.csv`
- `task.*`
- `report_template.json`
- `process.sh`
- `processing_stats.json` (when present; it is maintained by `process.sh`)
- already generated report folders

## Command Scope

Run only for the pseudonymized student named in the user command, for example:

```text
Run submission assessment for Student 0001
```

If the command does not identify exactly one pseudonymized student from `students.csv`, refuse and ask for a precise pseudonymized full name.

## Association Rules

For the target student:

- Find the matching row in `associations.csv`.
- Use only files listed in that row's `all_associated_files`.
- If `all_associated_files` is empty, still create the output file as described below.

For comparison:

- Compare the target submission package against all other students with resolved associations in `associations.csv`.
- Use all files listed for those other students.
- Use the generated assignment file, usually `task.tex` or `task.pdf`, so assignment-required overlap is not reported as distinctive or as copying.

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
- `all_tasks_implemented` (true/false/unknown): identify the required tasks from `task.*` by what they ask for to be done; specific function naming does not matter, only what the code does. Set `false` if any required task is missing, `unknown` if you cannot tell (for example an unreadable or empty submission).
- `task_details`: one entry per required task: what the task asks, whether it is implemented, and evidence (file and line reference).
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
- `report_template.json`
- `process.sh`
- `processing_stats.json` (when present; it is maintained by `process.sh`)

Only create or update the target student's report folder and files needed for that report.
