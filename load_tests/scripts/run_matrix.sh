#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

load_scenario "${LOAD_SCENARIO:-${LOAD_ROOT}/scenarios/drain.env}"
load_defaults
require_commands psql uv
validate_positive_integer LOAD_EVENTS "${LOAD_EVENTS}"

matrix_processes="${LOAD_MATRIX_PROCESSES:-1 2 4 8}"
matrix_batch_sizes="${LOAD_MATRIX_BATCH_SIZES:-10 100 500}"
result_dir="${LOAD_ROOT}/results/matrix-$(result_timestamp)"
mkdir -p "${result_dir}"

cd "${PROJECT_ROOT}"
for processes in ${matrix_processes}; do
    validate_positive_integer LOAD_MATRIX_PROCESSES "${processes}"
    for batch_size in ${matrix_batch_sizes}; do
        validate_positive_integer LOAD_MATRIX_BATCH_SIZES "${batch_size}"
        result_file="${result_dir}/p${processes}-b${batch_size}.json"
        echo "Running processes=${processes}, batch_size=${batch_size}..."

        psql "${LOAD_DSN}" -f "${LOAD_ROOT}/sql/reset.sql" >/dev/null
        psql "${LOAD_DSN}" \
            -v event_count="${LOAD_EVENTS}" \
            -v event_type="${LOAD_EVENT_TYPE}" \
            -f "${LOAD_ROOT}/sql/seed.sql" >/dev/null

        uv run python -m load_tests.worker_runner \
            --dsn "${LOAD_DSN}" \
            --mode drain \
            --timeout-seconds "${LOAD_TIMEOUT_SECONDS}" \
            --processes "${processes}" \
            --batch-size "${batch_size}" \
            --max-parallel "${LOAD_MAX_PARALLEL}" \
            --poll-interval "${LOAD_POLL_INTERVAL}" \
            --lease-seconds "${LOAD_LEASE_SECONDS}" \
            --monitor-timeout-seconds "${LOAD_MONITOR_TIMEOUT_SECONDS}" \
            --handler-delay-ms "${LOAD_HANDLER_DELAY_MS}" \
            --handler-jitter-ms "${LOAD_HANDLER_JITTER_MS}" \
            --failure-rate "${LOAD_FAILURE_RATE}" \
            --json-output "${result_file}"
    done
done

echo "Matrix results saved to ${result_dir}"
