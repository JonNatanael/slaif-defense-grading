# Performance Implementation — Part 2 of 3

## Scope

Implement shared assignment extraction and one-time assignment-requirement
analysis so every student agent does not repeatedly parse and reinterpret the
canonical assignment.

Part 1 must already be complete. Preserve its report validation, resume,
unresolved-report, statistics, and reasoning-effort behavior.

Do not implement similarity candidate generation or concurrent student
processing in this part. Similarity candidates are covered by Part 3.

## Required reading

Read these files completely before editing:

- `AGENTS.md`
- `PERFORMANCE_IMPLEMENTATION_PART_1.md`
- `slaif_defense_grading/prepare.py`
- `slaif_defense_grading/process_script.py`
- `slaif_defense_grading/finalize.py`
- `templates/process.sh.tpl`
- `templates/workspace/AGENTS.md`
- `README.md`
- `QUICKSTART.md`
- the report validator and generated-runtime helpers added in Part 1;
- relevant tests and dependency files.

Use only synthetic test data. Real roster identifiers and original LMS folder
names must not enter the workspace or the shared assignment artifacts.

## 1. Preserve the canonical assignment

The instructor-provided assignment must continue to be copied into the
workspace as canonical `task.*`. Do not replace or modify it.

Add a pseudonym-safe shared artifact:

```text
task_extracted.txt
```

It contains deterministic text extracted locally from the canonical assignment
where supported.

## 2. Deterministic local extraction

Implement extraction with these rules:

- For assignment formats already considered readable text, decode them with the
  repository's existing safe text-decoding behavior and normalize line endings.
- For PDF, use a documented and reproducible local extractor. Prefer a stable
  Python dependency if adding one is acceptable; otherwise explicitly detect a
  `pdftotext` executable and document the dependency.
- Do not use a remote service.
- Do not OCR unless a future explicit feature adds and tests local OCR.
- Do not claim successful extraction when PDF output is empty or implausibly
  small; record a warning and retain the original PDF as the fallback.
- Write extracted output atomically.
- Include extraction status and warnings in the private preprocessing report.
- Include `task_extracted.txt` in workspace privacy leak checks.
- The artifact must contain assignment content only, never roster data or
  private mappings.

If extraction fails, `prepare` should remain explicit about the fallback. Do not
silently create a misleading empty task artifact.

## 3. Shared structured requirements

Add a second shared artifact:

```text
task_requirements.json
```

It must be generated once by the assessment agent and reused by all student
runs. Define and validate a small versioned schema, for example:

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
  "notes": "Optional ambiguity or extraction warning"
}
```

Requirements:

- IDs must be unique and deterministic within the generated file.
- `requirements` must be a nonempty list when assignment requirements can be
  identified.
- Every entry must have nonempty `id`, `description`, and `source_reference`.
- `notes` must be a string.
- Add a dedicated validator; file existence alone is insufficient.
- Write the file atomically.

## 4. Add a separate assignment-analysis command

Update the generated workspace `AGENTS.md` to recognize a command such as:

```text
Analyze assignment requirements
```

Clearly separate its scope from student assessment:

- Assignment analysis reads `task_extracted.txt` and/or canonical `task.*`.
- It writes only `task_requirements.json`.
- It does not inspect student submissions.
- It does not create student reports.
- It does not infer or request real identities.
- It describes required behavior rather than relying on prescribed function
  names.
- It records ambiguity rather than inventing requirements or references.

The existing student command must still identify exactly one pseudonymized
student and write only that student's report.

## 5. Integrate with `process.sh`

Before processing any student that needs an agent invocation:

1. validate `task_requirements.json`;
2. reuse it if valid;
3. if missing or invalid, invoke Codex exactly once with the assignment-analysis
   command;
4. validate the result before continuing.

Resume behavior applies to this artifact. A normal resumed run must not repeat
assignment analysis when the file is valid. Define how `--force` behaves and
document it; either force regeneration or provide a separate explicit option,
but do not make the behavior ambiguous.

If requirement generation fails or produces invalid output:

- record a clear processing failure;
- do not silently process all remaining matched students without the shared
  prerequisite;
- preserve already valid student reports;
- allow the wrapper's existing non-strict finalize step to collect partial
  results; and
- exit nonzero.

Unresolved students from Part 1 do not require assignment analysis to generate
their neutral reports. Avoid launching the assignment-analysis agent when every
student is unresolved or already has a valid report.

## 6. Student-agent behavior

Per-student assessment agents must:

- use `task_requirements.json` as the normal requirements source;
- use its requirement descriptions to populate `task_details`;
- consult canonical `task.*` only when the structured artifact is ambiguous or
  lacks needed detail;
- retain evidence grounded in the target submission;
- never treat the shared requirements artifact as a student submission; and
- never modify `task_extracted.txt` or `task_requirements.json` during a student
  run.

Update the modification and excluded-input rules in the workspace instructions
accordingly.

## Processing statistics

Record the one-time assignment-analysis attempt separately from student
outcomes. At minimum capture:

- whether it was reused, generated successfully, or failed;
- duration and exit code when an agent was invoked; and
- whether extraction warnings were present.

Maintain compatibility with statistics produced before Part 2.

## Required tests

Add synthetic tests for:

- plain-text assignment extraction;
- an extractable synthetic PDF;
- an empty or image-only PDF extraction result;
- missing extractor/dependency behavior if applicable;
- canonical `task.*` preservation;
- preprocessing-report extraction status and warnings;
- no known synthetic private identifiers in either shared artifact;
- valid requirement-file reuse with no fake Codex call;
- missing requirement-file generation exactly once;
- invalid requirement-file regeneration;
- invalid agent output stopping matched-student processing with nonzero status;
- unresolved-only and fully-resumed runs avoiding unnecessary assignment
  analysis;
- student prompts/instructions using the shared artifact; and
- compatibility with Part 1 resume and finalization behavior.

Run:

```bash
pytest
```

Also generate a synthetic workspace and exercise `process.sh` with a fake Codex
that first writes requirements and then writes student reports.

## Documentation

Update `README.md` and `QUICKSTART.md` to explain:

- canonical versus extracted assignment files;
- the local extraction boundary;
- extraction limitations for scanned PDFs;
- the one-time agent-generated requirements artifact;
- resume behavior; and
- human oversight and the non-grading role of requirement extraction.

## Definition of done

Part 2 is complete only when:

- all tests pass;
- canonical assignments remain unchanged;
- deterministic extraction is local and honestly reports failure;
- valid requirements are generated at most once and reused;
- matched students are not processed after a failed shared prerequisite;
- unresolved and already-completed students do not trigger unnecessary work;
- shared artifacts contain no private identifiers;
- existing Part 1 behavior remains intact; and
- documentation and templates match actual behavior.
