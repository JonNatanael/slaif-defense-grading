from __future__ import annotations

import argparse
import tempfile
import textwrap
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence

from .core import (
    build_big_output,
    build_per_student_outputs,
    group_similar_artifacts,
    infer_student_label,
    iter_nested_zips,
    iter_submission_dirs,
    merge_master_inputs,
    stage_zip_with_sibling_files,
)
from .io_utils import eprint, unique_path, write_partial_concatenation
from .models import SubmissionArtifact
from .finalize import finalize_outputs
from .prepare import prepare_workspace


REPO_ROOT = Path(__file__).resolve().parent.parent


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slaif-defense-grading.py",
        description="Local preprocessing for SLAIF defense grading.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="create a pseudonymized agent workspace from local instructor data",
        description=textwrap.dedent(
            """\
            Create a pseudonymized workspace for later AI-assisted oral defense preparation.

            Real roster data is read locally from --students-csv. The generated workspace
            receives only pseudonyms, copied task.tex, a workspace AGENTS.md, a report
            template, pseudonymized submission text files, associations.csv, and a locally
            rendered process.sh. The private pseudonym map, student-output copies, and
            preprocessing report are written under --private-output, outside the workspace.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_prepare_arguments(prepare_parser)

    finalize_parser = subparsers.add_parser(
        "finalize",
        help="collect pseudonymized agent outputs into private named instructor outputs",
        description=textwrap.dedent(
            """\
            Create private named final outputs after the agent has run in the pseudonymized
            workspace. This command reads the workspace and private prepare outputs, maps
            pseudonyms back to real local roster rows, and writes instructor-facing files
            under --output. It does not modify the pseudonymized workspace.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_finalize_arguments(finalize_parser)

    legacy_parser = subparsers.add_parser(
        "legacy",
        help="run the previous ZIP concatenation flow",
        description=legacy_description(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_legacy_arguments(legacy_parser)
    return parser


def legacy_description() -> str:
    return textwrap.dedent(
        """\
        Legacy local preprocessing for Moodle/Canvas-style submission exports.

        This mode preserves the previous behavior:
          1) Extracts all provided master ZIPs to temporary directories under /tmp.
             Later ZIPs replace earlier submissions for duplicate students.
          2) Finds every nested .zip recursively inside the extracted contents.
             If a student folder has no nested ZIPs, uses subfolders as submission sources.
          3) Concatenates readable source files into either one big output or one output
             per inferred student label.

        Privacy note:
          This legacy mode may derive labels from LMS folder names. Use `prepare` for the
          pseudonymized workspace workflow.
        """
    )


def add_legacy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input-file",
        "-i",
        nargs="+",
        required=True,
        help=(
            "Path(s) to one or more master ZIP files. If multiple ZIPs are provided, "
            "later ZIPs replace earlier submissions for duplicate students."
        ),
    )

    output_group = parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument("--output-file", "-o", help="Path to write the final big concatenated .txt file.")
    output_group.add_argument(
        "--output-directory",
        "-d",
        help=(
            "Directory to write one concatenated .txt file per student. PDFs are copied "
            "verbatim and renamed to match each student's .txt basename."
        ),
    )

    parser.add_argument(
        "--similarity-check",
        action="store_true",
        help=(
            "When set, compare all submissions for similarity before building the final "
            "concatenated output, and merge near-identical submissions into a single entry "
            "that lists all student names."
        ),
    )


def add_prepare_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input-file",
        "-i",
        nargs="+",
        required=True,
        help=(
            "Path(s) to one or more Moodle/Canvas master ZIP exports. Later ZIPs override "
            "earlier submissions for duplicate LMS student folders."
        ),
    )
    parser.add_argument("--students-csv", required=True, help="Private local roster CSV with at least name,surname.")
    parser.add_argument("--task-file", required=True, help="Task file to copy into the generated workspace as task.tex.")
    parser.add_argument("--workspace", required=True, help="Agent-facing output workspace with pseudonymized data only.")
    parser.add_argument(
        "--private-output",
        required=True,
        help="Private output directory for pseudonym_map.csv and preprocessing_report.md. Must be outside --workspace.",
    )
    parser.add_argument(
        "--include-opaque-documents",
        action="store_true",
        help=(
            "Opt in to copying opaque documents such as PDF/DOCX/DOC/ODT/RTF under pseudonymized filenames. "
            "This weakens the privacy guarantee because internal content and metadata are not redacted."
        ),
    )


def add_finalize_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True, help="Prepared pseudonymized workspace after the agent has run.")
    parser.add_argument("--private-output", required=True, help="Private output directory created by prepare.")
    parser.add_argument("--output", required=True, help="Private final output directory for named instructor outputs.")
    parser.add_argument("--strict", action="store_true", help="Fail if any expected report_aspects.md is missing.")


def build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slaif-defense-grading.py legacy",
        description=legacy_description(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_legacy_arguments(parser)
    return parser


def build_prepare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slaif-defense-grading.py prepare",
        description="Create a pseudonymized workspace from local instructor data.",
    )
    add_prepare_arguments(parser)
    return parser


def build_finalize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slaif-defense-grading.py finalize",
        description="Create private named final outputs from a completed pseudonymized workspace.",
    )
    add_finalize_arguments(parser)
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    if argv is not None:
        argv = list(argv)
        if argv and argv[0] not in {"prepare", "finalize", "legacy", "-h", "--help"}:
            return build_legacy_parser().parse_args(argv)
    return build_arg_parser().parse_args(argv)


def run_prepare(args: argparse.Namespace) -> int:
    input_zips = [Path(raw).expanduser().resolve() for raw in args.input_file]
    students_csv = Path(args.students_csv).expanduser().resolve()
    task_file = Path(args.task_file).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    private_output = Path(args.private_output).expanduser().resolve()
    template_path = REPO_ROOT / "templates" / "process.sh.tpl"
    workspace_agents_template = REPO_ROOT / "templates" / "workspace" / "AGENTS.md"
    report_template = REPO_ROOT / "templates" / "workspace" / "report_aspects_template.md"

    try:
        result = prepare_workspace(
            input_zips=input_zips,
            students_csv=students_csv,
            task_file=task_file,
            workspace=workspace,
            private_output=private_output,
            template_path=template_path,
            workspace_agents_template=workspace_agents_template,
            report_template=report_template,
            include_opaque_documents=args.include_opaque_documents,
        )
    except Exception as exc:  # noqa: BLE001
        eprint(f"ERROR: prepare failed: {exc}")
        return 2

    eprint(
        "[slaif-defense-grading] Prepared pseudonymized workspace "
        f"({result.matched_count}/{result.roster_count} students matched): {workspace}"
    )
    eprint(f"[slaif-defense-grading] Private outputs: {private_output}")
    return 0


def run_finalize(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    private_output = Path(args.private_output).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    try:
        result = finalize_outputs(
            workspace=workspace,
            private_output=private_output,
            output=output,
            strict=args.strict,
        )
    except Exception as exc:  # noqa: BLE001
        eprint(f"ERROR: finalize failed: {exc}")
        return 2

    eprint(
        "[slaif-defense-grading] Finalized private outputs "
        f"({result.found_reports}/{result.roster_count} reports found, "
        f"{result.copied_student_outputs} student outputs copied): {output}"
    )
    return 0


def run_legacy(args: argparse.Namespace) -> int:
    input_zips = [Path(raw).expanduser().resolve() for raw in args.input_file]
    output_file = Path(args.output_file).expanduser().resolve() if args.output_file else None
    output_directory = Path(args.output_directory).expanduser().resolve() if args.output_directory else None

    for input_zip in input_zips:
        if not input_zip.exists():
            eprint(f"ERROR: input file does not exist: {input_zip}")
            return 2

        if not zipfile.is_zipfile(input_zip):
            eprint(f"ERROR: input file is not a valid ZIP: {input_zip}")
            return 2

    artifacts: List[SubmissionArtifact] = []

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="slaif-defense-grading_") as tmp:
        tmpdir = Path(tmp)
        outer_extract = tmpdir / "outer_extracted"
        outer_extract.mkdir(parents=True, exist_ok=True)

        try:
            merge_master_inputs(input_zips, outer_extract)
        except Exception as exc:  # noqa: BLE001
            eprint(f"ERROR: failed to extract input ZIP(s): {exc}")
            return 3

        unzipped_root = tmpdir / "unzipped_submissions"
        unzipped_root.mkdir(parents=True, exist_ok=True)

        student_folders = sorted([p for p in outer_extract.iterdir() if p.is_dir()], key=lambda p: p.as_posix().casefold())

        if not student_folders:
            eprint("ERROR: No student folders were found inside the provided ZIP file(s).")
            return 4

        total_zips = 0
        total_dirs = 0

        for student_folder_path in student_folders:
            student_zips = sorted(iter_nested_zips(student_folder_path), key=lambda p: p.as_posix().casefold())

            if student_zips:
                total_zips += len(student_zips)
                for zpath in student_zips:
                    student_label, student_folder = infer_student_label(zpath, outer_extract)
                    zip_base = zpath.stem
                    rel = zpath.relative_to(outer_extract)

                    eprint(f"[slaif-defense-grading]  - {student_label} :: extracting {rel.as_posix()} (+ outside-ZIP files)")

                    try:
                        extracted_dir = stage_zip_with_sibling_files(zpath, outer_extract, unzipped_root)
                    except zipfile.BadZipFile:
                        eprint(f"[slaif-defense-grading]    WARNING: Bad zip file, skipping: {zpath}")
                        continue
                    except Exception as exc:  # noqa: BLE001
                        eprint(f"[slaif-defense-grading]    WARNING: Failed to extract {zpath}: {exc}")
                        continue

                    partial_path = unique_path(extracted_dir.parent / f"{zip_base}.txt")

                    try:
                        num = write_partial_concatenation(extracted_dir, partial_path)
                    except Exception as exc:  # noqa: BLE001
                        eprint(f"[slaif-defense-grading]    WARNING: Failed to concatenate files for {zpath}: {exc}")
                        continue

                    eprint(f"[slaif-defense-grading]    -> concatenated {num} file(s) into {partial_path.name}")

                    artifacts.append(
                        SubmissionArtifact(
                            student_label=student_label,
                            student_folder=student_folder,
                            submission_source=zpath,
                            submission_name=zip_base,
                            extracted_dir=extracted_dir,
                            partial_concat_path=partial_path,
                            source_kind="zip",
                        )
                    )
                continue

            submission_dirs = iter_submission_dirs(student_folder_path)
            if not submission_dirs:
                continue

            total_dirs += len(submission_dirs)
            for submission_dir in submission_dirs:
                student_label, student_folder = infer_student_label(submission_dir, outer_extract)
                submission_name = submission_dir.name

                rel = submission_dir.relative_to(outer_extract)
                extracted_dir = submission_dir
                partial_path = unique_path(unzipped_root / rel.parent / f"{submission_name}.txt")

                eprint(f"[slaif-defense-grading]  - {student_label} :: reading folder {rel.as_posix()}")

                try:
                    num = write_partial_concatenation(extracted_dir, partial_path)
                except Exception as exc:  # noqa: BLE001
                    eprint(f"[slaif-defense-grading]    WARNING: Failed to concatenate files for {submission_dir}: {exc}")
                    continue

                eprint(f"[slaif-defense-grading]    -> concatenated {num} file(s) into {partial_path.name}")

                artifacts.append(
                    SubmissionArtifact(
                        student_label=student_label,
                        student_folder=student_folder,
                        submission_source=submission_dir,
                        submission_name=submission_name,
                        extracted_dir=extracted_dir,
                        partial_concat_path=partial_path,
                        source_kind="dir",
                    )
                )

        if total_zips or total_dirs:
            eprint(f"[slaif-defense-grading] Found {total_zips} nested ZIP(s) and {total_dirs} submission folder(s).")

        if not artifacts:
            eprint("ERROR: No valid submission ZIPs or folders were processed.")
            return 5

        if output_directory is not None:
            if output_directory.exists() and not output_directory.is_dir():
                eprint(f"ERROR: output directory is not a directory: {output_directory}")
                return 6
            eprint(f"[slaif-defense-grading] Building per-student outputs -> {output_directory}")
            try:
                written = build_per_student_outputs(artifacts, output_directory)
            except Exception as exc:  # noqa: BLE001
                eprint(f"ERROR: Failed to write output directory: {exc}")
                return 6
            eprint(f"[slaif-defense-grading] Done. Wrote {len(written)} file(s) to {output_directory}")
        else:
            assert output_file is not None
            if args.similarity_check:
                eprint("[slaif-defense-grading] Running similarity check across submissions")
                artifacts = group_similar_artifacts(artifacts)
            eprint(f"[slaif-defense-grading] Building final output -> {output_file}")
            try:
                build_big_output(artifacts, output_file)
            except Exception as exc:  # noqa: BLE001
                eprint(f"ERROR: Failed to write output file: {exc}")
                return 6

            eprint(f"[slaif-defense-grading] Done. Wrote {output_file}")

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        import sys

        argv = sys.argv[1:]

    argv = list(argv)
    if not argv:
        build_arg_parser().print_help()
        return 0

    if argv[0] == "prepare":
        return run_prepare(build_prepare_parser().parse_args(argv[1:]))

    if argv[0] == "finalize":
        return run_finalize(build_finalize_parser().parse_args(argv[1:]))

    if argv[0] == "legacy":
        return run_legacy(build_legacy_parser().parse_args(argv[1:]))

    if argv[0] in {"-h", "--help"}:
        build_arg_parser().print_help()
        return 0

    return run_legacy(build_legacy_parser().parse_args(argv))
