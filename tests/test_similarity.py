"""Part 3 performance work: deterministic local similarity candidate
generation (comparison_candidates.json).

Only synthetic data is used.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from test_prepare import (
    FORBIDDEN_IDENTIFIERS,
    MESSY_FORBIDDEN_IDENTIFIERS,
    run_messy_prepare,
    run_prepare,
)
from test_process_resume import (
    install_fake_codex,
    read_stats,
    run_process,
)
from slaif_defense_grading import similarity
from slaif_defense_grading.similarity import (
    CANDIDATES_FILE_NAME,
    DEFAULT_PARAMETERS,
    SimilarityParameters,
    SourceFile,
    candidate_pair_count,
    generate_candidate_artifact,
    parse_concatenated_submission,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# A distinctive 17-line block: non-trivial, non-generic source lines.
BLOCK = [
    "def solve_puzzle(grid, moves):",
    "    heap = [(0, 0, 0)]",
    "    seen = set()",
    "    best = None",
    "    while heap:",
    "        cost, x, y = heapq.heappop(heap)",
    "        if (x, y) in seen:",
    "            continue",
    "        seen.add((x, y))",
    "        if x == len(grid) - 1 and y == len(grid[0]) - 1:",
    "            best = cost",
    "            break",
    "        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):",
    "            nx, ny = x + dx, y + dy",
    "            if 0 <= nx < len(grid) and 0 <= ny < len(grid[0]):",
    "                heapq.heappush(heap, (cost + grid[nx][ny], nx, ny))",
    "    return best",
]

UNRELATED_A = [
    "def unrelated_alpha():",
    "    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]",
    "    total = 0",
    "    for v in values:",
    "        total += v * 3 - 1",
    "        if total > 50:",
    "            total = total // 2",
    "    return total * 7",
]

UNRELATED_B = [
    "class BetaCalculator:",
    "    def __init__(self, ratio):",
    "        self.ratio = ratio",
    "        self.cache = {}",
    "    def evaluate(self, inputs):",
    "        result = [value * self.ratio for value in inputs]",
    "        self.cache[len(inputs)] = sum(result)",
    "        return max(result) - min(result)",
]


def concat(pseudonym: str, files: dict) -> str:
    """Build a concatenated submission text with BEGIN/END markers."""
    parts = []
    for path, lines in files.items():
        parts.append(f"==== BEGIN {pseudonym} | submission | {path} ====\n")
        parts.append("\n".join(lines) + "\n")
        parts.append(f"==== END {pseudonym} | submission | {path} ====\n\n")
    return "".join(parts)


def write_concatenated(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def candidates_for(artifact: dict, pseudonym: str) -> list:
    return artifact["students"].get(pseudonym, [])


# ---------------------------------------------------------------------------
# Candidate generation algorithm
# ---------------------------------------------------------------------------


def test_distinctive_shared_block_creates_symmetric_candidate() -> None:
    submissions = [
        SourceFile("Student 0001", "main.py", ["import heapq", "import sys", "", ""] + BLOCK),
        SourceFile("Student 0002", "solution.py", ["import heapq", "import sys", "", ""] + BLOCK),
        SourceFile("Student 0003", "other.py", UNRELATED_A),
    ]
    artifact = generate_candidate_artifact(submissions)

    assert artifact["schema_version"] == 1
    assert artifact["algorithm"]["name"] == similarity.ALGORITHM_NAME
    assert artifact["algorithm"]["version"] == similarity.ALGORITHM_VERSION
    for key in (
        "shingle_size",
        "winnowing_window",
        "min_block_length",
        "min_block_fingerprints",
        "min_candidate_score",
        "max_documents_per_fingerprint",
        "position_gap",
        "max_candidates_per_target",
    ):
        assert key in artifact["algorithm"]["parameters"]

    record = candidates_for(artifact, "Student 0001")
    assert [r["candidate_pseudonym"] for r in record] == ["Student 0002"]
    back = candidates_for(artifact, "Student 0002")
    assert [r["candidate_pseudonym"] for r in back] == ["Student 0001"]
    # Symmetric: the same pair in both directions.
    assert candidate_pair_count(artifact) == 1
    # Unrelated student has an explicit empty entry, never a spurious pair.
    assert candidates_for(artifact, "Student 0003") == []


def test_candidate_records_contain_useful_line_ranges() -> None:
    submissions = [
        SourceFile("Student 0001", "main.py", ["import heapq", "import sys", "", ""] + BLOCK),
        SourceFile("Student 0002", "solution.py", ["import heapq", "import sys", "", ""] + BLOCK),
    ]
    record = candidates_for(generate_candidate_artifact(submissions), "Student 0001")[0]

    block = record["matching_blocks"][0]
    assert block["target_file"] == "main.py"
    assert block["candidate_file"] == "solution.py"
    assert block["shared_fingerprint_count"] >= DEFAULT_PARAMETERS.min_block_fingerprints
    for key in ("target_lines", "candidate_lines"):
        start, end = block[key].split("-")
        assert int(start) >= 1 and int(end) >= int(start)
    # The block actually starts at line 5 in each individual file; the
    # reported range must overlap it and be at least the configured minimum.
    target_start, target_end = (int(v) for v in record["matching_blocks"][0]["target_lines"].split("-"))
    assert target_start <= 5 <= target_end or target_start <= 21 and target_end >= 5
    assert target_end - target_start + 1 >= DEFAULT_PARAMETERS.min_block_length


def test_imports_and_boilerplate_alone_do_not_create_candidate() -> None:
    boilerplate_a = [
        "import numpy as np",
        "import matplotlib.pyplot as plt",
        "",
        "def main():",
        "    x = np.linspace(0, 1, 5)",
        "    y = x ** 2",
        "    plt.plot(x, y)",
        "    plt.title(\"t\")",
        "    plt.xlabel(\"x\")",
        "    plt.ylabel(\"y\")",
        "    plt.legend()",
        "    plt.grid()",
        "    plt.show()",
    ]
    boilerplate_b = [
        "import numpy as np",
        "import matplotlib.pyplot as plt",
        "",
        "def main():",
        "    x = np.linspace(0, 1, 5)",
        "    y = x ** 3",  # differs
        "    plt.plot(x, y)",
        "    plt.title(\"t\")",
        "    plt.xlabel(\"x\")",
        "    plt.ylabel(\"y\")",
        "    plt.legend()",
        "    plt.grid()",
        "    plt.show()",
    ]
    submissions = [
        SourceFile("Student 0001", "plot.py", boilerplate_a),
        SourceFile("Student 0002", "plot.py", boilerplate_b),
    ]
    artifact = generate_candidate_artifact(submissions)
    assert candidate_pair_count(artifact) == 0
    assert candidates_for(artifact, "Student 0001") == []


def test_assignment_provided_starter_material_is_filtered() -> None:
    starter = [
        "def transform(values, factor):",
        "    adjusted = [value * factor for value in values]",
        "    normalized = [value / max(adjusted) for value in adjusted]",
        "    ranked = sorted(enumerate(normalized), key=lambda item: -item[1])",
        "    top = [index for index, _ in ranked[:5]]",
        "    return top, normalized",
        "class Wrapper:",
        "    def run(self, values):",
        "        top, norm = transform(values, 2.0)",
        "        self.top = top",
        "        self.norm = norm",
        "    def describe(self):",
        "        return \",\".join(str(i) for i in self.top)",
    ]
    submissions = [
        SourceFile("Student 0001", "main.py", ["import sys"] + starter),
        SourceFile("Student 0002", "solution.py", ["import sys"] + starter),
    ]
    # Both students only share the assignment-provided starter code: filtered.
    artifact = generate_candidate_artifact(submissions, assignment_text="\n".join(["# Task instructions"] + starter))
    assert candidate_pair_count(artifact) == 0
    assert artifact["algorithm"]["parameters"]["filtered_assignment_fingerprints"] > 0

    # But a large distinctive block that merely contains a few
    # assignment-overlapping lines must survive the heuristic filter.
    distinctive = [
        "def process(data):",
        "    SCALE = 3.14",
    ] + [
        f"    step_{i} = {i} * data['x'] + {i + 1} * data['y'] - {i * 2}"
        for i in range(12)
    ] + [
        "    return sum(steps) if steps else None",
    ]
    submissions_b = [
        SourceFile("Student 0001", "main.py", distinctive),
        SourceFile("Student 0002", "solution.py", distinctive),
    ]
    artifact_b = generate_candidate_artifact(submissions_b, assignment_text="\n".join(distinctive[:2]))
    assert candidate_pair_count(artifact_b) == 1


def test_superficial_whitespace_changes_still_match() -> None:
    variant = [
        "    " + line if line.strip() else line for line in BLOCK
    ]
    submissions = [
        SourceFile("Student 0001", "main.py", ["import heapq"] + BLOCK),
        SourceFile("Student 0002", "solution.py", ["import heapq"] + variant),
    ]
    artifact = generate_candidate_artifact(submissions)
    assert candidate_pair_count(artifact) == 1
    assert candidates_for(artifact, "Student 0002")[0]["candidate_pseudonym"] == "Student 0001"


def test_unrelated_submissions_do_not_match() -> None:
    submissions = [
        SourceFile("Student 0001", "a.py", UNRELATED_A),
        SourceFile("Student 0002", "b.py", UNRELATED_B),
    ]
    artifact = generate_candidate_artifact(submissions)
    assert candidate_pair_count(artifact) == 0
    assert candidates_for(artifact, "Student 0001") == []
    assert candidates_for(artifact, "Student 0002") == []


def test_unresolved_and_unassociated_inputs_do_not_enter_the_index(tmp_path: Path) -> None:
    # Region-level filtering: an allowed_files list ignores unassociated
    # regions even when they contain an identical distinctive block.
    text = concat(
        "Student 0001",
        {
            "Student_0001.txt": ["x = 1"],
            "unassociated.py": BLOCK,
        },
    )
    parsed = parse_concatenated_submission(text, allowed_files={"Student_0001.txt"})
    assert [f.path for f in parsed] == ["Student_0001.txt"]

    # Without an allowed_files filter the parser still sees the region.
    parsed_all = parse_concatenated_submission(text)
    assert [f.path for f in parsed_all] == ["Student_0001.txt", "unassociated.py"]

    # Index-level filtering: generate_comparison_candidates reads only the
    # association's listed concatenated outputs, so unresolved students never
    # enter the index.
    from slaif_defense_grading.prepare import Association
    from slaif_defense_grading.similarity import generate_comparison_candidates

    class _Student:
        pseudonym = "Student 0001"

    resolved = Association(student=_Student(), txt_files=["Student_0001.txt"], document_files=[])
    unresolved = Association(student=_Student(), txt_files=[], document_files=[])
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        (workspace / "Student_0001.txt").write_text(concat("Student 0001", {"main.py": BLOCK}), encoding="utf-8")
        result = generate_comparison_candidates(workspace, [resolved, unresolved])
    assert list(result.artifact["students"]) == ["Student 0001"]


def test_malformed_concatenation_markers_are_handled_safely() -> None:
    unclosed = (
        "==== BEGIN Student 0001 | submission | lost.py ====\n"
        + "\n".join(BLOCK)
        + "\n"
        # no END marker, next BEGIN follows
        "==== BEGIN Student 0001 | submission | kept.py ====\n"
        "a = 1\nb = 2\nc = 3\n"
        "==== END Student 0001 | submission | kept.py ====\n"
    )
    parsed = parse_concatenated_submission(unclosed)
    assert [f.path for f in parsed] == ["kept.py"]
    assert parsed[0].lines == ["a = 1", "b = 2", "c = 3"]

    mismatched = (
        "==== BEGIN Student 0001 | submission | real.py ====\n"
        "a = 1\n"
        "==== END Student 0001 | submission | other.py ====\n"
    )
    assert parse_concatenated_submission(mismatched) == []

    stray_end = (
        "==== END Student 0001 | submission | nowhere.py ====\n"
        "plain line\n"
    )
    assert parse_concatenated_submission(stray_end) == []

    eof_unclosed = "==== BEGIN Student 0001 | submission | dangling.py ====\n" + "\n".join(BLOCK)
    assert parse_concatenated_submission(eof_unclosed) == []

    # Marker-less content is simply not source.
    assert parse_concatenated_submission("just text\nno markers\n") == []

    # Nothing crashes and no candidates come from skipped regions.
    artifact = generate_candidate_artifact(
        [SourceFile("Student 0001", "kept.py", ["a = 1", "b = 2", "c = 3"]),
         SourceFile("Student 0002", "kept.py", ["a = 1", "b = 2", "c = 3"])]
    )
    assert candidate_pair_count(artifact) == 0


def test_results_are_identical_across_repeated_runs_and_orderings() -> None:
    submissions = [
        SourceFile("Student 0001", "main.py", ["import heapq"] + BLOCK),
        SourceFile("Student 0002", "solution.py", ["import heapq", "# note"] + ["  " + l for l in BLOCK]),
        SourceFile("Student 0003", "other.py", UNRELATED_A),
    ]
    first = generate_candidate_artifact(submissions, assignment_text="def task(): pass")
    second = generate_candidate_artifact(submissions, assignment_text="def task(): pass")
    reversed_order = generate_candidate_artifact(list(reversed(submissions)), assignment_text="def task(): pass")
    shuffled = generate_candidate_artifact(
        [submissions[2], submissions[0], submissions[1]], assignment_text="def task(): pass"
    )
    assert first == second
    assert first == reversed_order
    assert first == shuffled


def test_max_candidate_tie_breaking_is_deterministic() -> None:
    params = SimilarityParameters(max_candidates_per_target=2, max_documents_per_fingerprint=10)
    submissions = [SourceFile("Student 0001", "target.py", BLOCK)]
    for index in range(2, 6):
        submissions.append(SourceFile(f"Student 000{index}", f"copy_{index}.py", BLOCK))

    first = generate_candidate_artifact(submissions, parameters=params)
    second = generate_candidate_artifact(submissions, parameters=params)
    assert first == second

    target = candidates_for(first, "Student 0001")
    # Four equally scored candidates, truncated deterministically to the two
    # lexicographically smallest pseudonyms.
    assert [r["candidate_pseudonym"] for r in target] == ["Student 0002", "Student 0003"]
    # Symmetry: each kept candidate lists the target back.
    assert candidates_for(first, "Student 0002")[0]["candidate_pseudonym"] == "Student 0001"
    # The truncated candidates are absent for the target.
    assert [r["candidate_pseudonym"] for r in candidates_for(first, "Student 0004")] == [
        "Student 0001", "Student 0002"
    ]


def test_common_fingerprint_document_frequency_cutoff() -> None:
    # The same block in four distinct submissions exceeds the default
    # max_documents_per_fingerprint (3) and is treated as overly common.
    submissions = [SourceFile(f"Student 000{i}", "f{i}.py", BLOCK) for i in range(1, 5)]
    assert candidate_pair_count(generate_candidate_artifact(submissions)) == 0
    # ...while the same block in three submissions is still reported.
    submissions_three = submissions[:3]
    artifact = generate_candidate_artifact(submissions_three)
    assert candidate_pair_count(artifact) == 3
    assert artifact["algorithm"]["parameters"]["filtered_common_fingerprints"] >= 0


# ---------------------------------------------------------------------------
# prepare integration and privacy
# ---------------------------------------------------------------------------


def test_prepare_generates_candidate_artifact_and_report(tmp_path: Path) -> None:
    workspace, private_output, result = run_prepare(tmp_path)
    assert result.returncode == 0, result.stderr

    artifact_path = workspace / CANDIDATES_FILE_NAME
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == 1
    assert artifact["algorithm"]["name"] == similarity.ALGORITHM_NAME
    # Only the resolved student is indexed; the unresolved one is absent.
    assert list(artifact["students"]) == ["Student 0001"]
    assert artifact["students"]["Student 0001"] == []
    for value in FORBIDDEN_IDENTIFIERS:
        assert value not in artifact_path.read_text(encoding="utf-8")

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "## Similarity Candidates" in report
    assert "Indexed submissions: 1" in report
    assert "Candidate pairs: 0" in report
    assert "not evidence of copying or misconduct" in report


def test_messy_prepare_candidate_artifact_is_pseudonym_only(tmp_path: Path) -> None:
    workspace, private_output, result = run_messy_prepare(tmp_path)
    assert result.returncode == 0, result.stderr

    artifact_path = workspace / CANDIDATES_FILE_NAME
    assert artifact_path.exists()
    text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(text)
    # Resolved students only: 0003 and 0005 are unresolved and must be absent.
    assert list(artifact["students"]) == ["Student 0001", "Student 0002", "Student 0004"]
    for value in MESSY_FORBIDDEN_IDENTIFIERS:
        assert value not in text, f"{value!r} leaked in {CANDIDATES_FILE_NAME!r}"

    report = (private_output / "preprocessing_report.md").read_text(encoding="utf-8")
    assert "Indexed submissions: 3" in report


def test_workspace_instructions_are_candidate_focused(tmp_path: Path) -> None:
    template = (REPO_ROOT / "templates" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Compare the target submission package against all other students" not in template
    for needle in (
        "comparison_candidates.json",
        "Read only the target student's entries in `comparison_candidates.json`",
        "routing hints",
        "never copy a candidate score into `code_copy_indications`",
        "If the target has no candidate entries, or no candidate survives detailed inspection, leave `code_copy_indications` empty",
        "Do not fall back to scanning the entire cohort",
        "deliberate performance/recall tradeoff",
        "only `prepare` creates it",
    ):
        assert needle in template, needle

    workspace, _private, result = run_prepare(tmp_path)
    assert result.returncode == 0, result.stderr
    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_text == template
    assert "comparison_candidates.json" in agents_text


def test_finalize_does_not_modify_candidate_artifact(tmp_path: Path) -> None:
    workspace, private_output, result = run_messy_prepare(tmp_path)
    assert result.returncode == 0, result.stderr
    fake_bin, log = install_fake_codex(tmp_path)
    process = run_process(tmp_path, workspace, fake_bin, log)
    assert process.returncode == 0, process.stderr
    before = (workspace / CANDIDATES_FILE_NAME).read_bytes()

    output = tmp_path / "final"
    finalize = subprocess_finalize(workspace, private_output, output)
    assert finalize.returncode == 0, finalize.stderr
    assert (workspace / CANDIDATES_FILE_NAME).read_bytes() == before
    # The run statistics are still readable alongside the candidates.
    assert read_stats(workspace)["schema_version"] == 2


def subprocess_finalize(workspace: Path, private_output: Path, output: Path):
    import subprocess

    return subprocess.run(
        [
            sys.executable,
            "slaif-defense-grading.py",
            "finalize",
            "--workspace",
            str(workspace),
            "--private-output",
            str(private_output),
            "--output",
            str(output),
            "--strict",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
