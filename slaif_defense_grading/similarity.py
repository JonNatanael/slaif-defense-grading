"""Deterministic local similarity candidate generation (Part 3).

This module builds ``comparison_candidates.json``, a high-recall,
pseudonym-only shortlist of submission pairs that share meaningful
near-contiguous source blocks. It is local preprocessing: no model or API
call is made, and the output is reproducible from the prepared
pseudonymized inputs.

The shortlist is a routing hint for the per-student assessment agent and for
later human review. It is not evidence of copying, plagiarism, unauthorized
collaboration, AI use, or any other misconduct, and it must never label a
student as having done anything wrong.

Algorithm (``line-shingle-winnowing``):

- each parsed source line is normalized (whitespace collapsed);
- empty lines and conservatively generic lines (imports, braces-only lines,
  common display/setup boilerplate) are ignored, while identifiers, string
  literals, comments, and non-obvious structure are retained;
- fixed-size shingles of consecutive normalized lines are hashed with a
  stable digest (never Python's randomized ``hash()``);
- winnowing selects a deterministic fingerprint per sliding window so the
  fingerprint count stays proportional to the submission size;
- an inverted fingerprint index over all resolved submissions is used to
  accumulate pair scores only for submissions that share fingerprints, so no
  all-pairs corpus scan by a model is needed;
- fingerprints that also appear in the assignment (starter code or
  task-mandated text, heuristic) and fingerprints present in more than
  ``max_documents_per_fingerprint`` distinct submissions are removed as
  overly common;
- shared fingerprints are merged into contiguous or near-contiguous matching
  blocks, and only blocks of at least ``min_block_length`` source lines with
  at least ``min_block_fingerprints`` shared fingerprints are reported.

Determinism: all iteration orders are sorted, hashes are stable, ties are
broken by pseudonym, and pairs are emitted symmetrically.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .task_extract import write_text_atomic

CANDIDATES_FILE_NAME = "comparison_candidates.json"

SCHEMA_VERSION = 1
ALGORITHM_NAME = "line-shingle-winnowing"
ALGORITHM_VERSION = 1

#: Pseudonym-safe marker regions that never contain submission source.
_NON_SOURCE_REGIONS = {"no_readable_files_found", "no_submission_found"}

_BEGIN_RE = re.compile(r"^==== BEGIN (.+?) \| submission \| (.+?) ====\s*$")
_END_RE = re.compile(r"^==== END (.+?) \| submission \| (.+?) ====\s*$")

_WHITESPACE_RE = re.compile(r"\s+")

#: Conservatively generic lines that must never drive a candidate on their
#: own. Intentionally narrow: when in doubt, keep the line.
_GENERIC_LINE_PATTERNS: Tuple[re.Pattern, ...] = (
    # empty / whitespace-only
    re.compile(r"^\s*$"),
    # imports and package/namespace declarations
    re.compile(r"^\s*(import|from)\s+[\w.*\s,()]+$"),
    re.compile(r"^\s*#\s*include\s+.*$"),
    re.compile(r"^\s*using\s+(namespace\s+)?[\w:]+\s*;\s*$"),
    re.compile(r"^\s*(package|module|namespace)\s+[\w.]+\s*;?\s*$"),
    re.compile(r"^\s*#?\s*pragma\s+.*$"),
    # braces/brackets/punctuation only
    re.compile(r"^[{}();,\[\]]+$"),
    # trivial returns
    re.compile(r"^\s*return\s*(0|1|true|false|none|null|nil)?\s*;?\s*$", re.IGNORECASE),
    # the assignment entry-point guard
    re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*$"),
    # common display/setup boilerplate (figure creation, showing/saving
    # images, labels, legends) as listed in the workspace instructions
    re.compile(r"^\s*plt\.(show|figure|subplot|subplots|savefig|title|xlabel|ylabel|legend|grid|close|clf|ioff|pause)\(.*\)\s*$"),
    re.compile(r"^\s*(fig|axes?|ax|line|lines|img|canvas|window)\s*(,\s*(ax|axes|line|img|window))?\s*=\s*(plt\.)?(subplots?|figure|Figure|gca|imshow|imread)\(.*\)\s*$"),
    re.compile(r"^\s*cv2\.(imshow|imwrite|waitKey|namedWindow|destroyAllWindows|startWindowThread|setWindowTitle)\(.*\)\s*$"),
)


@dataclass(frozen=True)
class SimilarityParameters:
    """Explicit, documented thresholds for candidate generation."""

    #: normalized lines per shingle
    shingle_size: int = 3
    #: winnowing window size (consecutive shingles)
    winnowing_window: int = 4
    #: minimum shared block length, in source lines of the individual file
    min_block_length: int = 10
    #: minimum shared fingerprints inside one matching block
    min_block_fingerprints: int = 2
    #: deterministic pair score below which a pair is not shortlisted
    min_candidate_score: float = 0.05
    #: fingerprints present in more than this many distinct submissions are
    #: treated as overly common and removed
    max_documents_per_fingerprint: int = 3
    #: maximum shingle-position gap still considered near-contiguous. Must
    #: bridge the gaps that winnowing itself can leave in identical content
    #: (bounded by the winnowing window size) as well as single-line edits.
    position_gap: int = 4
    #: maximum candidates emitted per target (conservative; recall-first)
    max_candidates_per_target: int = 10


DEFAULT_PARAMETERS = SimilarityParameters()


@dataclass
class SourceFile:
    """One pseudonymized individual source file parsed from a concatenated
    submission file: a pseudonym, the file path, a region index (for files
    that appear more than once), and raw source lines."""

    pseudonym: str
    path: str
    lines: List[str]
    region: int = 0


@dataclass
class _LineRef:
    line_no: int  # 1-based line number within the individual source file
    text: str  # normalized line


@dataclass
class _Shingle:
    pos: int  # index of the first kept line in the shingle
    digest: int
    start_line: int
    end_line: int


@dataclass
class _Occurrence:
    pseudonym: str
    file: str
    region: int
    pos: int
    start_line: int
    end_line: int


@dataclass
class _MatchingBlock:
    target_file: str
    target_start: int
    target_end: int
    candidate_file: str
    candidate_start: int
    candidate_end: int
    shared_fingerprint_count: int


@dataclass(frozen=True)
class CandidateGenerationResult:
    """Artifact plus aggregate, pseudonym-safe statistics for the report."""

    artifact: dict
    #: resolved students that contributed at least one parsed source file
    indexed_submissions: int
    #: parsed individual source files across all resolved submissions
    indexed_files: int


def parse_concatenated_submission(
    text: str,
    allowed_files: Optional[Sequence[str]] = None,
) -> List[SourceFile]:
    """Parse ``==== BEGIN/END ... ====`` regions into individual source files.

    Malformed regions (BEGIN without END, stray END, BEGIN/END path mismatch,
    unclosed region at EOF) are safely skipped. Regions for special
    non-source markers, and files not present in ``allowed_files`` (when
    given), are ignored.
    """
    files: List[SourceFile] = []
    current: Optional[Tuple[str, str, int, List[str]]] = None  # pseudo, path, region, lines
    region_counter: Dict[str, int] = {}

    for line in text.splitlines():
        begin = _BEGIN_RE.match(line)
        if begin is not None:
            if current is not None:
                # Previous region was never closed: malformed, skip it.
                current = None
            pseudonym, path = begin.group(1), begin.group(2)
            if path in _NON_SOURCE_REGIONS:
                current = None
                continue
            if allowed_files is not None and path not in allowed_files:
                current = None
                continue
            region = region_counter.get(path, 0)
            region_counter[path] = region + 1
            current = (pseudonym, path, region, [])
            continue
        end = _END_RE.match(line)
        if end is not None:
            if current is not None:
                pseudonym, path, region, lines = current
                if (pseudonym, path) == (end.group(1), end.group(2)):
                    files.append(SourceFile(pseudonym, path, lines, region))
                # Mismatched END marker: region is malformed and skipped.
            current = None
            continue
        if current is not None:
            current[3].append(line)
    # A region still open at EOF is malformed and skipped.
    return files


def normalize_line(line: str) -> str:
    return _WHITESPACE_RE.sub(" ", line).strip()


def is_generic_line(normalized: str) -> bool:
    return any(pattern.match(normalized) for pattern in _GENERIC_LINE_PATTERNS)


def _kept_lines(source_file: SourceFile) -> List[_LineRef]:
    refs: List[_LineRef] = []
    for index, line in enumerate(source_file.lines, start=1):
        normalized = normalize_line(line)
        if not normalized or is_generic_line(normalized):
            continue
        refs.append(_LineRef(index, normalized))
    return refs


def _stable_digest(parts: Sequence[str]) -> int:
    return int.from_bytes(
        hashlib.blake2b("|".join(parts).encode("utf-8"), digest_size=16).digest(), "big"
    )


def _winnowed_shingles(source_file: SourceFile, parameters: SimilarityParameters) -> List[_Shingle]:
    """Build winnowed fingerprints for one individual source file.

    Returns the shingles that survived winnowing, each mapped back to the
    1-based line range of the individual file it covers.
    """
    kept = _kept_lines(source_file)
    size = parameters.shingle_size
    shingles: List[_Shingle] = []
    for i in range(len(kept) - size + 1):
        window = kept[i : i + size]
        shingles.append(
            _Shingle(
                pos=i,
                digest=_stable_digest(tuple(ref.text for ref in window)),
                start_line=window[0].line_no,
                end_line=window[-1].line_no,
            )
        )
    if not shingles:
        return []

    win = parameters.winnowing_window
    selected: Dict[int, _Shingle] = {}
    for j in range(max(1, len(shingles) - win + 1)):
        window_shingles = shingles[j : j + win]
        best = min(window_shingles, key=lambda s: (s.digest, s.pos))
        selected[best.pos] = best
    return [selected[pos] for pos in sorted(selected)]


def _assignment_fingerprints(assignment_text: str, parameters: SimilarityParameters) -> set:
    """Fingerprints of the readable assignment text (heuristic starter-code
    and task-mandated-text filter)."""
    if not assignment_text.strip():
        return set()
    source_file = SourceFile(pseudonym="<assignment>", path="task", lines=assignment_text.splitlines())
    return {shingle.digest for shingle in _winnowed_shingles(source_file, parameters)}


def _line_range(start: int, end: int) -> str:
    return f"{start}-{end}"


def generate_candidate_artifact(
    submissions: Sequence[SourceFile],
    assignment_text: str = "",
    parameters: SimilarityParameters = DEFAULT_PARAMETERS,
) -> dict:
    """Generate the versioned ``comparison_candidates.json`` artifact.

    ``submissions`` are the parsed individual source files of all resolved
    students only (unresolved students and unassociated files must not be
    passed in). The result is deterministic for the same input regardless of
    the order the submissions are provided in.
    """
    kept_counts: Dict[str, int] = {}
    index: Dict[int, List[_Occurrence]] = {}
    indexed_submissions: set = set()

    ordered_files = sorted(
        submissions, key=lambda f: (f.pseudonym, f.path, f.region)
    )
    for source_file in ordered_files:
        kept_counts[source_file.pseudonym] = kept_counts.get(source_file.pseudonym, 0) + len(
            _kept_lines(source_file)
        )
        shingles = _winnowed_shingles(source_file, parameters)
        if not shingles:
            continue
        indexed_submissions.add(source_file.pseudonym)
        for shingle in shingles:
            index.setdefault(shingle.digest, []).append(
                _Occurrence(
                    pseudonym=source_file.pseudonym,
                    file=source_file.path,
                    region=source_file.region,
                    pos=shingle.pos,
                    start_line=shingle.start_line,
                    end_line=shingle.end_line,
                )
            )

    # Heuristic assignment-provided-material filter: remove fingerprints that
    # also appear in the readable assignment text. A large distinctive block
    # survives when only a few of its lines overlap the task, because only
    # the overlapping shingles lose their fingerprints and the
    # near-contiguous merging tolerates the resulting gaps.
    assignment_digests = _assignment_fingerprints(assignment_text, parameters)
    filtered_assignment = 0
    for digest in list(index):
        if digest in assignment_digests:
            del index[digest]
            filtered_assignment += 1

    # Document-frequency cutoff for overly common fingerprints.
    filtered_common = 0
    for digest in list(index):
        documents = {occ.pseudonym for occ in index[digest]}
        if len(documents) > parameters.max_documents_per_fingerprint:
            del index[digest]
            filtered_common += 1

    # Accumulate pair points only for submissions sharing fingerprints.
    # points: (pos_a, pos_b, start_a, end_a, start_b, end_b)
    pair_points: Dict[Tuple[str, str], Dict[Tuple[str, int, str, int], List[Tuple[int, ...]]]] = {}
    for digest, occurrences in index.items():
        by_student: Dict[str, List[_Occurrence]] = {}
        for occ in occurrences:
            by_student.setdefault(occ.pseudonym, []).append(occ)
        pseudonyms = sorted(by_student)
        for i in range(len(pseudonyms)):
            for j in range(i + 1, len(pseudonyms)):
                pseudo_a, pseudo_b = pseudonyms[i], pseudonyms[j]
                for occ_a in by_student[pseudo_a]:
                    for occ_b in by_student[pseudo_b]:
                        file_key = (occ_a.file, occ_a.region, occ_b.file, occ_b.region)
                        pair_points.setdefault((pseudo_a, pseudo_b), {}).setdefault(file_key, []).append(
                            (occ_a.pos, occ_b.pos, occ_a.start_line, occ_a.end_line, occ_b.start_line, occ_b.end_line)
                        )

    candidates_by_target: Dict[str, List[dict]] = {}
    for (pseudo_a, pseudo_b), file_groups in sorted(pair_points.items()):
        blocks: List[_MatchingBlock] = []
        for file_key in sorted(file_groups):
            file_a, region_a, file_b, region_b = file_key
            points = sorted(file_groups[file_key])
            run: List[Tuple[int, ...]] = []
            for point in points:
                if run and (
                    point[0] - run[-1][0] > parameters.position_gap
                    or point[1] - run[-1][1] > parameters.position_gap
                    or point[0] < run[-1][0]
                    or point[1] < run[-1][1]
                ):
                    blocks.extend(_finalize_run(run, file_a, file_b, parameters))
                    run = []
                run.append(point)
            blocks.extend(_finalize_run(run, file_a, file_b, parameters))

        if not blocks:
            continue
        covered_a = _union_line_span([(b.target_start, b.target_end) for b in blocks])
        covered_b = _union_line_span([(b.candidate_start, b.candidate_end) for b in blocks])
        kept_a = kept_counts.get(pseudo_a, 0)
        kept_b = kept_counts.get(pseudo_b, 0)
        if kept_a <= 0 or kept_b <= 0:
            continue
        score = round(min(1.0, min(covered_a / kept_a, covered_b / kept_b)), 4)
        if score < parameters.min_candidate_score:
            continue

        sorted_for_a = sorted(blocks, key=lambda b: (b.target_file, b.target_start, b.candidate_file, b.candidate_start))
        sorted_for_b = sorted(blocks, key=lambda b: (b.candidate_file, b.candidate_start, b.target_file, b.target_start))
        candidates_by_target.setdefault(pseudo_a, []).append(
            {
                "candidate_pseudonym": pseudo_b,
                "score": score,
                "matching_blocks": [
                    {
                        "target_file": b.target_file,
                        "target_lines": _line_range(b.target_start, b.target_end),
                        "candidate_file": b.candidate_file,
                        "candidate_lines": _line_range(b.candidate_start, b.candidate_end),
                        "shared_fingerprint_count": b.shared_fingerprint_count,
                    }
                    for b in sorted_for_a
                ],
            }
        )
        candidates_by_target.setdefault(pseudo_b, []).append(
            {
                "candidate_pseudonym": pseudo_a,
                "score": score,
                "matching_blocks": [
                    {
                        "target_file": b.candidate_file,
                        "target_lines": _line_range(b.candidate_start, b.candidate_end),
                        "candidate_file": b.target_file,
                        "candidate_lines": _line_range(b.target_start, b.target_end),
                        "shared_fingerprint_count": b.shared_fingerprint_count,
                    }
                    for b in sorted_for_b
                ],
            }
        )

    students: Dict[str, List[dict]] = {}
    for pseudonym in sorted(kept_counts):
        records = candidates_by_target.get(pseudonym, [])
        records.sort(key=lambda record: (-record["score"], record["candidate_pseudonym"]))
        students[pseudonym] = records[: parameters.max_candidates_per_target]

    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": {
            "name": ALGORITHM_NAME,
            "version": ALGORITHM_VERSION,
            "parameters": {
                "shingle_size": parameters.shingle_size,
                "winnowing_window": parameters.winnowing_window,
                "min_block_length": parameters.min_block_length,
                "min_block_fingerprints": parameters.min_block_fingerprints,
                "min_candidate_score": parameters.min_candidate_score,
                "max_documents_per_fingerprint": parameters.max_documents_per_fingerprint,
                "position_gap": parameters.position_gap,
                "max_candidates_per_target": parameters.max_candidates_per_target,
                "filtered_assignment_fingerprints": filtered_assignment,
                "filtered_common_fingerprints": filtered_common,
                "note": (
                    "Heuristic filter: fingerprints that also appear in the readable "
                    "assignment text (likely starter code or task-mandated text) are "
                    "removed. Candidates are routing hints for inspection, not evidence "
                    "of copying or misconduct."
                ),
            },
        },
        "students": students,
    }


def _finalize_run(
    run: List[Tuple[int, ...]],
    file_a: str,
    file_b: str,
    parameters: SimilarityParameters,
) -> List[_MatchingBlock]:
    if len(run) < parameters.min_block_fingerprints:
        return []
    start_a = min(point[2] for point in run)
    end_a = max(point[3] for point in run)
    start_b = min(point[4] for point in run)
    end_b = max(point[5] for point in run)
    if end_a - start_a + 1 < parameters.min_block_length:
        return []
    if end_b - start_b + 1 < parameters.min_block_length:
        return []
    return [
        _MatchingBlock(
            target_file=file_a,
            target_start=start_a,
            target_end=end_a,
            candidate_file=file_b,
            candidate_start=start_b,
            candidate_end=end_b,
            shared_fingerprint_count=len(run),
        )
    ]


def _union_line_span(spans: Sequence[Tuple[int, int]]) -> int:
    total = 0
    for start, end in sorted(spans):
        total += end - start + 1
    return total


def generate_comparison_candidates(
    workspace: Path,
    associations: Sequence,
    assignment_text: str = "",
    parameters: SimilarityParameters = DEFAULT_PARAMETERS,
) -> CandidateGenerationResult:
    """Generate and atomically write ``comparison_candidates.json`` in the
    workspace for all resolved (matched) associations.

    ``associations`` are the prepare-time associations; only students with
    ``status == "matched"`` and files listed in their association enter the
    index.
    """
    submissions: List[SourceFile] = []
    for association in sorted(associations, key=lambda a: a.student.pseudonym):
        if association.status != "matched":
            continue
        # Only the association's listed concatenated text outputs are read;
        # every source region inside one of those files is associated by
        # construction, so no further region-level filtering is needed.
        for txt_file in association.txt_files:
            path = workspace / txt_file
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            submissions.extend(parse_concatenated_submission(text))

    artifact = generate_candidate_artifact(submissions, assignment_text, parameters)
    write_text_atomic(
        workspace / CANDIDATES_FILE_NAME,
        json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return CandidateGenerationResult(
        artifact=artifact,
        indexed_submissions=len({s.pseudonym for s in submissions}),
        indexed_files=len(submissions),
    )


def candidate_pair_count(artifact: dict) -> int:
    """Number of symmetric candidate pairs in an artifact."""
    seen: set = set()
    for pseudonym, records in artifact.get("students", {}).items():
        for record in records:
            seen.add(frozenset((pseudonym, record["candidate_pseudonym"])))
    return len(seen)
