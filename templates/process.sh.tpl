#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Detach from the interactive terminal so `codex exec` never waits on stdin
# after finishing a student's report.
exec < /dev/null

# PHASE2_COMMANDS
