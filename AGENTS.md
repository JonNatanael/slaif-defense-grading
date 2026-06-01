# AGENTS.md

This file is for coding agents modifying the `slaif-defense-grading` repository.

It is separate from `templates/workspace/AGENTS.md`, which is copied into generated pseudonymized workspaces for the later oral-verification agent.

## Mission

`slaif-defense-grading` supports a local `prepare -> run agent -> finalize` workflow for oral defenses of student work completed outside direct supervision.

The repository code:

- reads private instructor inputs locally;
- creates a pseudonymized workspace for the later agent;
- generates `associations.csv`, `process.sh`, and report templates locally;
- keeps real identity maps outside the agent workspace;
- finalizes pseudonymized reports into private named instructor outputs.

The tool prepares evidence-grounded oral-verification material. It does not automatically prove plagiarism, unauthorized collaboration, improper AI-tool use, or any other misconduct.

## Privacy Boundary

Real student identities must not enter the generated agent workspace.

The local input roster may contain real names, emails, IDs, and LMS identifiers. The generated workspace must contain only pseudonyms such as:

```text
Student 0001
Student 0002
```

The private mapping from real identities to pseudonyms must be written outside the agent workspace. Final named outputs are private/local and may contain real identities.

Do not add examples, tests, fixtures, screenshots, or documentation containing real student data.

## Workflow Rules

Preprocessing is local instructor-side work. The later agent must not perform roster matching, pseudonym mapping, association generation, or script generation.

`process.sh` must be rendered from `templates/process.sh.tpl` and should:

- be valid Bash;
- use `set -euo pipefail`;
- run one deterministic command per pseudonymized student;
- contain only pseudonymized student names;
- not require real identity data.

The generated workspace `AGENTS.md` must stay agent-facing and must not contain real identities.

## File Handling

Operate only on explicit input files and explicit output directories.

Use safe ZIP extraction with path-traversal protection.

Be conservative with filename-based identity matching. Prefer the official `students.csv` over heuristics and do not invent identities.

Student-submitted opaque documents are excluded by default. Do not claim PDF/DOCX/etc. content is safely pseudonymized by renaming. The instructor-provided assignment file may be copied as canonical `task.*`.

## Testing

Use only synthetic data.

Important checks:

- CLI help exposes only `prepare` and `finalize`;
- safe extraction rejects path traversal;
- Moodle-style folders, direct folders, nested ZIPs, and multiple ZIPs work;
- pseudonyms follow CSV order;
- private maps are written outside the workspace;
- workspace filenames, CSVs, shell scripts, Markdown, source files, notebooks, and templates contain no known real identifiers;
- generated `process.sh` is executable;
- `finalize` creates private named outputs without modifying the pseudonymized workspace.

Run tests with:

```bash
pytest
```

## Documentation

Keep `README.md`, `QUICKSTART.md`, templates, and tests aligned with actual behavior.

Use language that reflects human oversight:

- “oral-verification questions”
- “instructor-facing report”
- “pseudonymized workspace”
- “local preprocessing”
- “human review”

Avoid implying automatic proof or automatic misconduct detection.

## Git Hygiene

Do not commit generated workspaces, private mappings, real rosters, submission ZIPs, or final outputs.

Synthetic fixtures generated inside tests are allowed. Real student material is not.
