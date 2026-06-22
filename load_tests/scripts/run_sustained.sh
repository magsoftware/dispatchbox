#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

load_scenario "${LOAD_SCENARIO:-${LOAD_ROOT}/scenarios/sustained.env}"
load_defaults
require_commands pgbench psql uv
validate_positive_integer LOAD_DURATION_SECONDS "${LOAD_DURATION_SECONDS}"
validate_positive_integer LOAD_RATE "${LOAD_RATE}"

mkdir -p "${LOAD_ROOT}/results"
timestamp="$(result_timestamp)"
result_file="${LOAD_ROOT}/results/sustained-${timestamp}.json"
worker_log="${LOAD_ROOT}/results/sustained-${timestamp}-worker.log"
pgbench_log="${LOAD_ROOT}/results/sustained-${timestamp}-pgbench.log"
stop_file="${LOAD_ROOT}/results/sustained-${timestamp}.stop"
worker_duration=$((LOAD_DURATION_SECONDS + 30))
rm -f "${stop_file}"

psql "${LOAD_DSN}" -f "${LOAD_ROOT}/sql/reset.sql"

cd "${PROJECT_ROOT}"
uv run python -m load_tests.worker_runner \
    --dsn "${LOAD_DSN}" \
    --mode duration \
    --duration-seconds "${worker_duration}" \
    --processes "${LOAD_PROCESSES}" \
    --batch-size "${LOAD_BATCH_SIZE}" \
    --max-parallel "${LOAD_MAX_PARALLEL}" \
    --poll-interval "${LOAD_POLL_INTERVAL}" \
    --lease-seconds "${LOAD_LEASE_SECONDS}" \
    --monitor-timeout-seconds "${LOAD_MONITOR_TIMEOUT_SECONDS}" \
    --handler-delay-ms "${LOAD_HANDLER_DELAY_MS}" \
    --handler-jitter-ms "${LOAD_HANDLER_JITTER_MS}" \
    --failure-rate "${LOAD_FAILURE_RATE}" \
    --stop-file "${stop_file}" \
    --json-output "${result_file}" \
    >"${worker_log}" 2>&1 &
worker_pid=$!

cleanup() {
    if kill -0 "${worker_pid}" >/dev/null 2>&1; then
        kill -TERM "${worker_pid}" >/dev/null 2>&1 || true
        wait "${worker_pid}" || true
    fi
}
trap cleanup EXIT INT TERM

pgbench \
    -n \
    -c "${LOAD_PGBENCH_CLIENTS}" \
    -j "${LOAD_PGBENCH_THREADS}" \
    -T "${LOAD_DURATION_SECONDS}" \
    -R "${LOAD_RATE}" \
    -P 5 \
    -f "${LOAD_ROOT}/sql/pgbench_insert.sql" \
    "${LOAD_DSN}" | tee "${pgbench_log}"

touch "${stop_file}"
wait "${worker_pid}"
trap - EXIT INT TERM
rm -f "${stop_file}"
cat "${worker_log}"
echo "Worker result saved to ${result_file}"
echo "pgbench output saved to ${pgbench_log}"
