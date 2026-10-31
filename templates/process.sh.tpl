#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Detach from the interactive terminal so `codex exec` never waits on stdin
# after finishing a student's report.
exec < /dev/null

PROCESS_STATS_FILE="processing_stats.json"
PROCESS_PLANNED_STUDENTS=__PLANNED_STUDENT_COUNT__
PROCESS_FORCE=0

if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 64
fi
if [[ $# -eq 1 && "$1" != "--force" ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 64
fi
if [[ $# -eq 1 ]]; then
    PROCESS_FORCE=1
fi

PROCESS_STARTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PROCESS_ENDED_AT=""
PROCESS_START_SECONDS=$SECONDS
PROCESS_RUN_STATUS="running"
declare -a PROCESS_PSEUDONYMS=()
declare -a PROCESS_DURATIONS=()
declare -a PROCESS_EXIT_CODES=()
declare -a PROCESS_OUTCOMES=()

write_processing_stats() {
    local processed_count=${#PROCESS_PSEUDONYMS[@]}
    local success_count=0
    local failed_count=0
    local skipped_count=0
    local generated_count=0
    local duration_sum=0
    local average_seconds="0.000"
    local elapsed_seconds=$((SECONDS - PROCESS_START_SECONDS))
    local index

    for ((index = 0; index < processed_count; index++)); do
        duration_sum=$((duration_sum + PROCESS_DURATIONS[index]))
        case "${PROCESS_OUTCOMES[index]}" in
            agent_success) success_count=$((success_count + 1)) ;;
            agent_failed) failed_count=$((failed_count + 1)) ;;
            skipped_valid_report) skipped_count=$((skipped_count + 1)) ;;
            generated_unresolved) generated_count=$((generated_count + 1)) ;;
        esac
    done

    if ((processed_count > 0)); then
        average_seconds=$(printf '%d.%03d' \
            $((duration_sum / processed_count)) \
            $((((duration_sum % processed_count) * 1000) / processed_count)))
    fi

    {
        printf '{\n'
        printf '  "schema_version": 2,\n'
        printf '  "run_status": "%s",\n' "$PROCESS_RUN_STATUS"
        printf '  "started_at": "%s",\n' "$PROCESS_STARTED_AT"
        if [[ -n "$PROCESS_ENDED_AT" ]]; then
            printf '  "ended_at": "%s",\n' "$PROCESS_ENDED_AT"
        else
            printf '  "ended_at": null,\n'
        fi
        printf '  "planned_students": %d,\n' "$PROCESS_PLANNED_STUDENTS"
        printf '  "processed_students": %d,\n' "$processed_count"
        printf '  "successful_students": %d,\n' "$success_count"
        printf '  "failed_students": %d,\n' "$failed_count"
        printf '  "skipped_students": %d,\n' "$skipped_count"
        printf '  "generated_unresolved_students": %d,\n' "$generated_count"
        printf '  "total_time_seconds": %d,\n' "$elapsed_seconds"
        printf '  "average_time_seconds": %s,\n' "$average_seconds"
        printf '  "students": [\n'
        for ((index = 0; index < processed_count; index++)); do
            printf '    {"pseudonym": "%s", "outcome": "%s", "duration_seconds": %d, "exit_code": %d}' \
                "${PROCESS_PSEUDONYMS[index]}" "${PROCESS_OUTCOMES[index]}" "${PROCESS_DURATIONS[index]}" "${PROCESS_EXIT_CODES[index]}"
            if ((index + 1 < processed_count)); then
                printf ','
            fi
            printf '\n'
        done
        printf '  ]\n'
        printf '}\n'
    } > "${PROCESS_STATS_FILE}.tmp"
    mv "${PROCESS_STATS_FILE}.tmp" "$PROCESS_STATS_FILE"
}

finish_processing_stats() {
    # The run only counts as completed once the planned-student loop finished
    # normally and marked it as such. Anything still "running" here (e.g. an
    # interrupted or crashed run) is a failure; the explicit exit code cannot
    # be trusted because bash reports 0 to EXIT traps after fatal signals.
    set +e
    if [[ "$PROCESS_RUN_STATUS" == "running" ]]; then
        PROCESS_RUN_STATUS="failed"
    fi
    PROCESS_ENDED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    write_processing_stats
}

validate_report() {
    local pseudonym=$1
    local report_path=$2
    [[ -f "$report_path" ]] || return 1
    python3 report_validator.py "$pseudonym" "$report_path"
}

generate_unresolved_report() {
    local pseudonym=$1
    local report_path="$pseudonym/report.json"
    local tmp_path="${report_path}.tmp.$$"

    mkdir -p "$pseudonym"
    if ! python3 - "$pseudonym" "$tmp_path" <<'PY'
import json
import sys

pseudonym, output_path = sys.argv[1], sys.argv[2]
report = {
    "pseudonym": pseudonym,
    "assignment_submitted": False,
    "all_tasks_implemented": "unknown",
    "task_details": [],
    "looks_llm_generated": "uncertain",
    "llm_generation_indicators": [],
    "code_copy_indications": [],
    "notes": "No submission material was associated with this pseudonymized student, so no implementation or authorship indicators could be assessed.",
}
with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(report, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY
    then
        rm -f "$tmp_path"
        return 1
    fi
    if ! python3 report_validator.py "$pseudonym" "$tmp_path"; then
        rm -f "$tmp_path"
        return 1
    fi
    mv "$tmp_path" "$report_path"
    return 0
}

process_one_student() {
    local pseudonym=$1
    local status=$2
    shift 2
    local report_path="$pseudonym/report.json"
    local agent_exit_code=0
    local validation_exit_code=0

    if [[ "$status" == "unresolved" ]]; then
        if [[ "$PROCESS_FORCE" -eq 0 ]] && validate_report "$pseudonym" "$report_path"; then
            PROCESS_LAST_OUTCOME="skipped_valid_report"
            return 0
        fi
        if generate_unresolved_report "$pseudonym"; then
            PROCESS_LAST_OUTCOME="generated_unresolved"
            return 0
        fi
        echo "ERROR: could not generate a neutral report for $pseudonym" >&2
        PROCESS_LAST_OUTCOME="agent_failed"
        return 1
    fi

    if [[ "$PROCESS_FORCE" -eq 0 ]] && validate_report "$pseudonym" "$report_path"; then
        PROCESS_LAST_OUTCOME="skipped_valid_report"
        return 0
    fi

    # This function is always invoked by run_planned_student inside a
    # `set +e` region, so a failing agent invocation or invalid report cannot
    # trigger errexit and stop the later planned students.
    "$@"
    agent_exit_code=$?
    validate_report "$pseudonym" "$report_path"
    validation_exit_code=$?

    if ((agent_exit_code == 0)) && ((validation_exit_code == 0)); then
        PROCESS_LAST_OUTCOME="agent_success"
        return 0
    fi
    if ((agent_exit_code != 0)); then
        echo "ERROR: agent invocation failed for $pseudonym (exit code $agent_exit_code)" >&2
    else
        echo "ERROR: agent invocation for $pseudonym finished, but the report is missing or invalid" >&2
    fi
    PROCESS_LAST_OUTCOME="agent_failed"
    return 1
}

run_planned_student() {
    local pseudonym=$1
    local status=$2
    shift 2
    local student_start_seconds=$SECONDS
    local student_exit_code=0

    # A failure for one student must not stop later students from being
    # attempted; failures are tracked and reported once at the end.
    set +e
    process_one_student "$pseudonym" "$status" "$@"
    student_exit_code=$?
    set -e

    PROCESS_PSEUDONYMS+=("$pseudonym")
    PROCESS_DURATIONS+=("$((SECONDS - student_start_seconds))")
    PROCESS_EXIT_CODES+=("$student_exit_code")
    PROCESS_OUTCOMES+=("$PROCESS_LAST_OUTCOME")
    if ((student_exit_code != 0)); then
        PROCESS_RUN_STATUS="failed"
    fi
    write_processing_stats
    return 0
}

trap 'finish_processing_stats' EXIT
write_processing_stats

# PHASE2_COMMANDS

if [[ "$PROCESS_RUN_STATUS" == "running" ]]; then
    PROCESS_RUN_STATUS="completed"
    write_processing_stats
fi

if [[ "$PROCESS_RUN_STATUS" == "failed" ]]; then
    echo "ERROR: one or more planned students were not processed successfully; see $PROCESS_STATS_FILE" >&2
    exit 1
fi
