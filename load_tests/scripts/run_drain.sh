#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

load_scenario "${LOAD_SCENARIO:-${LOAD_ROOT}/scenarios/drain.env}"
load_defaults
require_commands psql uv
validate_positive_integer LOAD_EVENTS "${LOAD_EVENTS}"

mkdir -p "${LOAD_ROOT}/results"
result_file="${LOAD_ROOT}/results/drain-$(result_timestamp).json"

echo "Resetting and seeding ${LOAD_EVENTS} events..."
psql "${LOAD_DSN}" -f "${LOAD_ROOT}/sql/reset.sql"
psql "${LOAD_DSN}" \
    -v event_count="${LOAD_EVENTS}" \
    -v event_type="${LOAD_EVENT_TYPE}" \
    -f "${LOAD_ROOT}/sql/seed.sql"

cd "${PROJECT_ROOT}"
uv run python -m load_tests.worker_runner \
    --dsn "${LOAD_DSN}" \
    --mode drain \
    --timeout-seconds "${LOAD_TIMEOUT_SECONDS}" \
    --processes "${LOAD_PROCESSES}" \
    --batch-size "${LOAD_BATCH_SIZE}" \
    --max-parallel "${LOAD_MAX_PARALLEL}" \
    --poll-interval "${LOAD_POLL_INTERVAL}" \
    --lease-seconds "${LOAD_LEASE_SECONDS}" \
    --monitor-timeout-seconds "${LOAD_MONITOR_TIMEOUT_SECONDS}" \
    --handler-delay-ms "${LOAD_HANDLER_DELAY_MS}" \
    --handler-jitter-ms "${LOAD_HANDLER_JITTER_MS}" \
    --failure-rate "${LOAD_FAILURE_RATE}" \
    --json-output "${result_file}"

echo "Result saved to ${result_file}"
