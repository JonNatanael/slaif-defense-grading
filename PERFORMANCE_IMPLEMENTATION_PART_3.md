# Performance Implementation — Part 3 of 3

## Scope

Implement deterministic local similarity candidate generation so each student
assessment agent inspects only a focused shortlist instead of comparing its
target against every resolved submission.

Parts 1 and 2 must already be complete. Preserve their validation, resume,
unresolved-report, shared-task, statistics, and wrapper behavior.

Do not add concurrent student processing in this part.

## Required reading

Read these files completely before editing:

- `AGENTS.md`
- `PERFORMANCE_IMPLEMENTATION_PART_1.md`
- `PERFORMANCE_IMPLEMENTATION_PART_2.md`
- `slaif_defense_grading/prepare.py`
- the submission concatenation and association code;
- `slaif_defense_grading/process_script.py`
- `templates/workspace/AGENTS.md`
- `README.md`
- `QUICKSTART.md`
- relevant tests and all generated-workspace leak checks.

Use only synthetic test data. Candidate artifacts must contain pseudonyms only,
never names, emails, student IDs, LMS identifiers, or original LMS folder names.

## 1. Purpose and terminology

Create a versioned pseudonymized workspace artifact, preferably:

```text
comparison_candidates.json
```

This is a high-recall shortlist for detailed agent inspection and later human
review. It is not evidence of copying and must never label a student as having
plagiarized, cheated, used AI, or committed misconduct.

Use neutral terms such as:

- candidate;
- similarity;
- shared fingerprint;
- matching block; and
- requires inspection.

Avoid field names such as `plagiarism`, `guilty`, or `copied` in the candidate
generator.

## 2. Parse submissions with source locations

Use the existing pseudonymized concatenated submission files. Parse their
`==== BEGIN ... ====` and `==== END ... ====` markers so every analyzed source
line retains:

- target pseudonym;
- pseudonymized original file path; and
- 1-based line number within that individual source file.

Do not use concatenated-file line numbers in evidence. Reject or safely skip
malformed marker regions and cover that behavior with tests.

Unresolved students and files not listed in `associations.csv` must not enter
the similarity index.

## 3. Deterministic candidate-generation algorithm

Implement a dependency-light, language-neutral baseline based on normalized
source lines, fixed-size shingles, and deterministic winnowed fingerprints.

Requirements:

- Ignore empty lines.
- Conservatively ignore highly generic lines such as imports, package
  declarations, braces-only lines, and common display/setup boilerplate.
- Normalize whitespace and superficial formatting.
- Retain identifiers, string literals, comments, and non-obvious structure that
  may be distinctive.
- Preserve mappings back to original file and line ranges.
- Build one inverted fingerprint index over all resolved submissions.
- Accumulate pair scores only for submissions sharing fingerprints; do not ask a
  model to perform an all-pairs corpus scan.
- Require a meaningful contiguous or near-contiguous block consistent with the
  existing guidance of roughly ten non-trivial consecutive lines.
- Do not shortlist pairs based only on a few generic lines.
- Use stable hashing, not Python's randomized `hash()`.
- Use deterministic sorting and pseudonym tie-breaking.
- Emit symmetric candidates so a pair is available when either student is the
  assessment target.

Make the following explicit named constants or CLI options and document them:

- normalized lines per shingle;
- winnowing window size;
- minimum shared block length;
- minimum candidate score;
- document-frequency cutoff for overly common fingerprints; and
- maximum candidates per target, if one is imposed.

Prefer high recall over an extremely short list. A false positive costs a focused
agent comparison; a false negative can hide relevant evidence. If a maximum is
used, choose a conservative default and test deterministic truncation.

## 4. Exclude assignment-provided material

Use the canonical or extracted assignment from Part 2 to suppress supplied
starter code and assignment-mandated text where it can be matched safely.

- Apply the same normalization and fingerprinting to readable assignment text.
- Remove or down-weight fingerprints present in supplied starter material.
- Do not discard a large distinctive student block merely because a few lines
  overlap with the task.
- Record the algorithm/version and filtering parameters in the artifact.

This filtering is heuristic and must be described as such.

## 5. Candidate artifact schema

Use a small versioned schema. A suitable shape is:

```json
{
  "schema_version": 1,
  "algorithm": {
    "name": "line-shingle-winnowing",
    "version": 1,
    "parameters": {}
  },
  "students": {
    "Student 0001": [
      {
        "candidate_pseudonym": "Student 0007",
        "score": 0.73,
        "matching_blocks": [
          {
            "target_file": "main.py",
            "target_lines": "12-26",
            "candidate_file": "solution.py",
            "candidate_lines": "8-22",
            "shared_fingerprint_count": 9
          }
        ]
      }
    ]
  }
}
```

The exact shape may change, but every candidate must include:

- target and candidate pseudonyms, directly or by containment;
- deterministic score and algorithm/version;
- target pseudonymized file and approximate 1-based line range;
- candidate pseudonymized file and approximate 1-based line range; and
- shared block/fingerprint count or length.

Prefer references and line ranges over copying source into the artifact. Write
the file atomically and include it in privacy leak checks.

## 6. Agent behavior

Replace the workspace instruction that every target be compared against every
other resolved submission.

For a student assessment, the agent must:

- analyze the target submission normally for task completion and LLM-style
  indicators;
- read only that target's entries in `comparison_candidates.json`;
- inspect only listed candidate submissions for copying indications;
- begin with referenced blocks and read enough surrounding context to judge
  whether similarity is distinctive and non-generic;
- treat candidate scores as routing hints, not evidence;
- never copy a candidate score directly into `code_copy_indications`;
- retain the existing high evidence threshold before reporting an indication;
  and
- use an empty `code_copy_indications` list when no candidate survives detailed
  inspection.

If a target has no candidates, the agent must not fall back to scanning the
entire cohort. Document this deliberate performance/recall tradeoff.

Add `comparison_candidates.json` to the list of preprocessing artifacts that
student agents must not modify.

## 7. Preparation and resume integration

Generate candidates locally during `prepare`, after pseudonymized readable
submission outputs exist and before rendering the final workspace instructions
and scripts.

- Candidate generation must make no model/API call.
- Its output must be reproducible from the prepared pseudonymized inputs.
- Candidate generation failure must produce a clear prepare error rather than
  silently restoring cohort-wide model comparison.
- Normal `process.sh` resume behavior reuses the prepared candidate artifact.
- `finalize` must not modify it.

Report aggregate, pseudonym-safe candidate statistics in the private
preprocessing report, such as number of indexed submissions and candidate pairs.
Do not place real names next to candidate information.

## Required tests

Use synthetic fixtures to prove:

- a distinctive shared block at or above the configured minimum creates a
  symmetric candidate pair;
- candidate records contain useful individual-file line ranges;
- imports and common boilerplate alone do not create a candidate;
- assignment-provided starter material is filtered;
- superficial whitespace changes still match;
- clearly unrelated submissions do not match;
- unresolved students do not enter the index;
- unassociated files are ignored;
- malformed concatenation markers are handled safely;
- results are identical across repeated runs and input orderings;
- maximum-candidate tie-breaking is deterministic, if applicable;
- candidate artifacts contain no known synthetic private identifiers;
- generated workspace instructions no longer require cohort-wide comparison;
- agents with no candidates are instructed to leave copying indications empty;
  and
- Parts 1 and 2 tests continue to pass.

Run:

```bash
pytest
```

Also inspect a generated synthetic `comparison_candidates.json` manually for
schema clarity, symmetry, line references, and privacy.

## Documentation

Update `README.md` and `QUICKSTART.md` to explain:

- local candidate generation;
- algorithm and configurable thresholds;
- that candidates are not findings or evidence by themselves;
- focused agent comparison behavior;
- the no-candidate behavior;
- human review requirements; and
- expected performance improvement from avoiding repeated cohort-wide scans.

Use the repository's preferred language: “oral-verification questions,”
“instructor-facing report,” “pseudonymized workspace,” “local preprocessing,”
and “human review.”

## Definition of done

Part 3 is complete only when:

- all tests pass;
- candidate generation is local, deterministic, and pseudonym-only;
- meaningful synthetic similarity is found with useful line references;
- generic and assignment-provided overlap is conservatively filtered;
- unresolved students are excluded;
- student agents no longer scan the entire resolved cohort;
- candidate scores are clearly non-evidentiary;
- Parts 1 and 2 behavior remains intact;
- documentation and templates describe actual behavior; and
- no generated workspace, private mapping, roster, ZIP, or final output is
  committed.
