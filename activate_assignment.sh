#!/usr/bin/env bash
# Run a complete private oral-verification workflow for one assignment.
#
# Usage: ./activate_assignment.sh <codex-profile> <assignment-directory>
#
# The assignment directory must contain exactly one instruction file and one or
# more submission ZIPs. Its parent directory must contain exactly one
# students*.csv roster. Results are written to a timestamped, private run
# directory under <assignment-directory>/.slaif-defense-grading/runs/.
set -euo pipefail

if (( $# != 2 )); then
    echo "Usage: $0 <codex-profile> <assignment-directory>" >&2
    exit 64
fi

codex_profile=$1
assignment_arg=$2

if [[ ! -d "$assignment_arg" ]]; then
    echo "ERROR: assignment directory does not exist: $assignment_arg" >&2
    exit 2
fi

assignment_dir=$(cd "$assignment_arg" && pwd -P)
data_dir=$(cd "$assignment_dir/.." && pwd -P)
repo_dir=$(cd "$(dirname "$0")" && pwd -P)

mapfile -t rosters < <(find "$data_dir" -maxdepth 1 -type f -iname 'students*.csv' -print | LC_ALL=C sort)
if (( ${#rosters[@]} != 1 )); then
    echo "ERROR: expected exactly one students*.csv roster in $data_dir; found ${#rosters[@]}." >&2
    exit 2
fi

mapfile -t submission_zips < <(find "$assignment_dir" -maxdepth 1 -type f -iname '*.zip' -print | LC_ALL=C sort)
if (( ${#submission_zips[@]} == 0 )); then
    echo "ERROR: expected at least one submission ZIP in $assignment_dir." >&2
    exit 2
fi

# An assignment folder may contain ZIP submissions and one canonical instructor
# instruction file. Deliberately reject ambiguity rather than guessing.
mapfile -t task_files < <(find "$assignment_dir" -maxdepth 1 -type f ! -iname '*.zip' ! -name '.*' -print | LC_ALL=C sort)
if (( ${#task_files[@]} != 1 )); then
    echo "ERROR: expected exactly one non-ZIP instruction file in $assignment_dir; found ${#task_files[@]}." >&2
    exit 2
fi

umask 077
run_root="$assignment_dir/.slaif-defense-grading/runs"
run_stamp=$(date -u +'%Y%m%dT%H%M%SZ')
run_dir="$run_root/$run_stamp"
counter=1
while [[ -e "$run_dir" ]]; do
    counter=$((counter + 1))
    run_dir="$run_root/$run_stamp-$counter"
done

agent_workspace="$run_dir/agent-workspace"
private_output="$run_dir/private"
final_output="$run_dir/final"
normalized_roster="$private_output/students_normalized.csv"
mkdir -p "$run_dir"

echo "[slaif-defense-grading] Assignment: $assignment_dir" >&2
echo "[slaif-defense-grading] Roster: ${rosters[0]}" >&2
echo "[slaif-defense-grading] Instructions: ${task_files[0]}" >&2
echo "[slaif-defense-grading] Submission ZIPs: ${#submission_zips[@]}" >&2

# If a student_order.txt exists in the data directory, use it to control processing order.
student_order_args=()
order_file="$data_dir/student_order.txt"
if [[ -f "$order_file" ]]; then
    student_order_args=(--student-order-file "$order_file")
    echo "[slaif-defense-grading] Student order: $order_file" >&2
fi
echo "[slaif-defense-grading] Private run directory: $run_dir" >&2

PYTHONPATH="$repo_dir${PYTHONPATH:+:$PYTHONPATH}" python3 -m slaif_defense_grading.roster_normalize \
    --input "${rosters[0]}" \
    --output "$normalized_roster"

python3 "$repo_dir/slaif-defense-grading.py" prepare \
    --codex-profile "$codex_profile" \
    ${student_order_args[@]+"${student_order_args[@]}"} \
    --input-file "${submission_zips[@]}" \
    --students-csv "$normalized_roster" \
    --task-file "${task_files[0]}" \
    --workspace "$agent_workspace" \
    --private-output "$private_output"

# Finalize even when an individual agent invocation fails. process.sh records
# the partial timing state before it exits, and non-strict finalization retains
# completed reports while clearly listing missing ones.
set +e
bash "$agent_workspace/process.sh"
process_status=$?
set -e

python3 "$repo_dir/slaif-defense-grading.py" finalize \
    --workspace "$agent_workspace" \
    --private-output "$private_output" \
    --output "$final_output"
finalize_status=$?

echo "[slaif-defense-grading] Final private output: $final_output" >&2
if (( process_status != 0 )); then
    echo "WARNING: process.sh exited with status $process_status; partial results were finalized." >&2
fi

if (( finalize_status != 0 )); then
    exit "$finalize_status"
fi
exit "$process_status"
