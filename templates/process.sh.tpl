#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Detach from the interactive terminal so `codex exec` never waits on stdin
# after finishing a student's report.
exec < /dev/null

PROCESS_STATS_FILE="processing_stats.json"
PROCESS_PLANNED_STUDENTS=__PLANNED_STUDENT_COUNT__
PROCESS_STARTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PROCESS_ENDED_AT=""
PROCESS_START_SECONDS=$SECONDS
PROCESS_RUN_STATUS="running"
declare -a PROCESS_PSEUDONYMS=()
declare -a PROCESS_DURATIONS=()
declare -a PROCESS_EXIT_CODES=()

write_processing_stats() {
    local processed_count=${#PROCESS_PSEUDONYMS[@]}
    local successful_count=0
    local failed_count=0
    local duration_sum=0
    local average_seconds="0.000"
    local elapsed_seconds=$((SECONDS - PROCESS_START_SECONDS))
    local index

    for ((index = 0; index < processed_count; index++)); do
        duration_sum=$((duration_sum + PROCESS_DURATIONS[index]))
        if ((PROCESS_EXIT_CODES[index] == 0)); then
            successful_count=$((successful_count + 1))
        else
            failed_count=$((failed_count + 1))
        fi
    done

    if ((processed_count > 0)); then
        average_seconds=$(printf '%d.%03d' \
            $((duration_sum / processed_count)) \
            $((((duration_sum % processed_count) * 1000) / processed_count)))
    fi

    {
        printf '{\n'
        printf '  "schema_version": 1,\n'
        printf '  "run_status": "%s",\n' "$PROCESS_RUN_STATUS"
        printf '  "started_at": "%s",\n' "$PROCESS_STARTED_AT"
        if [[ -n "$PROCESS_ENDED_AT" ]]; then
            printf '  "ended_at": "%s",\n' "$PROCESS_ENDED_AT"
        else
            printf '  "ended_at": null,\n'
        fi
        printf '  "planned_students": %d,\n' "$PROCESS_PLANNED_STUDENTS"
        printf '  "processed_students": %d,\n' "$processed_count"
        printf '  "successful_students": %d,\n' "$successful_count"
        printf '  "failed_students": %d,\n' "$failed_count"
        printf '  "total_time_seconds": %d,\n' "$elapsed_seconds"
        printf '  "average_time_seconds": %s,\n' "$average_seconds"
        printf '  "students": [\n'
        for ((index = 0; index < processed_count; index++)); do
            printf '    {"pseudonym": "%s", "duration_seconds": %d, "exit_code": %d}' \
                "${PROCESS_PSEUDONYMS[index]}" "${PROCESS_DURATIONS[index]}" "${PROCESS_EXIT_CODES[index]}"
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
    local script_exit_code=$1
    set +e
    if ((script_exit_code == 0)); then
        PROCESS_RUN_STATUS="completed"
    elif [[ "$PROCESS_RUN_STATUS" == "running" ]]; then
        PROCESS_RUN_STATUS="failed"
    fi
    PROCESS_ENDED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    write_processing_stats
}

run_student() {
    local pseudonym=$1
    shift
    local student_start_seconds=$SECONDS
    local exit_code

    set +e
    "$@"
    exit_code=$?
    set -e

    PROCESS_PSEUDONYMS+=("$pseudonym")
    PROCESS_DURATIONS+=("$((SECONDS - student_start_seconds))")
    PROCESS_EXIT_CODES+=("$exit_code")
    if ((exit_code != 0)); then
        PROCESS_RUN_STATUS="failed"
    fi
    write_processing_stats
    return "$exit_code"
}

trap 'finish_processing_stats "$?"' EXIT
write_processing_stats

# PHASE2_COMMANDS
