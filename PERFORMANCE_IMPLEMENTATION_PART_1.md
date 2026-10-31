# Performance Implementation — Part 1 of 3

## Scope

Implement the workflow-control improvements:

1. resume `process.sh` without reprocessing valid reports;
2. generate neutral reports for unresolved submissions without invoking Codex;
3. expose Codex reasoning effort through `activate_assignment.sh`.

Do not implement assignment-requirement extraction, similarity candidates, or
concurrent student processing in this part. Those are covered by Parts 2 and 3.

This part must be completed, documented, and tested before starting Part 2.

## Required reading

Read these files completely before editing:

- `AGENTS.md`
- `activate_assignment.sh`
- `slaif_defense_grading/cli.py`
- `slaif_defense_grading/prepare.py`
- `slaif_defense_grading/process_script.py`
- `slaif_defense_grading/finalize.py`
- `templates/process.sh.tpl`
- `templates/workspace/AGENTS.md`
- `templates/workspace/report_template.json`
- `README.md`
- `QUICKSTART.md`
- relevant tests, especially `tests/test_prepare.py`

Use only synthetic test data. Preserve the repository privacy boundary: real
names, emails, student IDs, LMS identifiers, and original LMS folder names must
never enter a generated agent workspace.

## 1. Shared report validation

Create a single authoritative structural validation contract for
`report.json`. Both resume checks and `finalize` must use the same rules, either
through shared code or a generated standalone validator derived from the same
contract.

Validation must check at least:

- valid JSON;
- exact or required top-level keys from `report_template.json`;
- `pseudonym` equals the expected target;
- documented scalar and list types;
- allowed values for `all_tasks_implemented`;
- allowed values for `looks_llm_generated`;
- required fields and types in every `task_details` entry; and
- required fields and types in every `code_copy_indications` entry.

Do not treat a report as complete merely because the file exists. Preserve
compatibility with valid reports produced by existing workspaces.

If `process.sh` needs a validator inside a standalone generated workspace, add a
pseudonym-safe generated helper rather than depending on the source repository
being importable at runtime. Include that helper in privacy leak checks.

## 2. Resume valid completed reports

Before invoking Codex for a matched student, `process.sh` must validate
`<pseudonym>/report.json`.

- Skip Codex when the existing report is valid.
- Reprocess when it is missing, malformed, structurally invalid, or belongs to
  another pseudonym.
- Make resumability the default.
- Support an explicit `./process.sh --force` option that regenerates reports.
- An invalid report may be atomically replaced by the new result.
- A failure for one student must not stop later students from being attempted.
- After all planned students have been handled, return nonzero if any attempted
  agent invocation failed.
- Retain the latest atomically written statistics after interruption or failure.

Keep `process.sh` valid Bash with `set -euo pipefail`, deterministic processing
order, and one deterministic processing command per pseudonymized student.

## 3. Generate unresolved reports without Codex

`prepare` already marks students with no associated files as `unresolved` in
`associations.csv`. For those students, create the report deterministically and
make no Codex call.

Use exactly the normal report schema with these values:

```json
{
  "pseudonym": "<target pseudonym>",
  "assignment_submitted": false,
  "all_tasks_implemented": "unknown",
  "task_details": [],
  "looks_llm_generated": "uncertain",
  "llm_generation_indicators": [],
  "code_copy_indications": [],
  "notes": "No submission material was associated with this pseudonymized student, so no implementation or authorship indicators could be assessed."
}
```

The note may be adjusted, but it must remain neutral and must not imply
misconduct. This is a local workflow fact, not an automatic grading decision.

- Write the report atomically.
- Validate it with the shared report validator.
- A valid existing unresolved report may be skipped during resume.
- An invalid unresolved report must be regenerated locally.
- `--force` may regenerate it but must never invoke Codex.

## 4. Processing statistics

Extend `processing_stats.json` to distinguish outcomes such as:

- `agent_success`
- `agent_failed`
- `skipped_valid_report`
- `generated_unresolved`

Add aggregate skipped and locally generated counts while retaining existing
summary information. Keep duration and exit-code semantics meaningful. Version
the statistics schema if semantics change, and make `finalize` accept both the
old and new versions.

A resumed run must clearly describe work performed in that invocation rather
than presenting skipped reports as newly produced.

## 5. Expose reasoning effort in the wrapper

Make the wrapper accept an optional third argument while preserving existing
two-argument calls:

```text
./activate_assignment.sh <codex-profile> <assignment-directory> [reasoning-effort]
```

Requirements:

- Default to the current Python CLI default, `medium`, when omitted.
- Accept `none`, causing the generated Codex command to omit the override.
- Pass the selected value to `prepare` through
  `--codex-reasoning-effort <value>`.
- Reject extra arguments and update usage text.
- Print the selected effort in the startup summary.
- Do not maintain a separate hard-coded list of model-specific effort values in
  Bash unless validation is centralized with the Python CLI.

Update `README.md` and `QUICKSTART.md` to match.

## Required tests

Add synthetic tests proving that:

- a valid report results in no fake `codex` invocation;
- malformed and structurally invalid reports are reprocessed;
- a report with the wrong pseudonym is reprocessed;
- `--force` reprocesses a valid matched report;
- one failed student does not prevent later students from running;
- the final exit status is nonzero if any attempted agent invocation failed;
- statistics distinguish processed, skipped, locally generated, and failed
  students;
- statistics remain valid on failure paths;
- unresolved students never call fake Codex;
- unresolved reports pass validation and finalize successfully;
- generated helpers and reports contain no known synthetic private identifiers;
- wrapper calls with omitted, `low`, and `none` effort behave correctly; and
- CLI help still exposes only `prepare` and `finalize`.

Run the complete suite:

```bash
pytest
```

Also run a generated synthetic workspace's `process.sh` with a fake Codex
executable and inspect `processing_stats.json`.

## Definition of done

Part 1 is complete only when:

- all tests pass;
- rerunning `process.sh` makes zero Codex calls for valid reports;
- unresolved students receive valid neutral reports with zero Codex calls;
- individual failures no longer stop later students;
- old and new processing-statistics files remain finalizable;
- existing two-argument wrapper usage still works;
- documentation describes actual behavior;
- generated `process.sh` is executable and contains no real identifiers; and
- no generated workspace or private data is committed.
