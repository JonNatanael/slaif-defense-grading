#!/bin/bash
set -euo pipefail

# Phase 1: run the initial workspace-wide processing step.
./phase1.sh

# Phase 2: run one command per pseudonymized student entry in deterministic order.
# PHASE2_COMMANDS
