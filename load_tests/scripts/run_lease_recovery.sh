#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

load_scenario "${LOAD_SCENARIO:-${LOAD_ROOT}/scenarios/lease_recovery.env}"
load_defaults
require_commands psql uv

mkdir -p "${LOAD_ROOT}/results"
result_file="${LOAD_ROOT}/results/lease-recovery-$(result_timestamp).json"

psql "${LOAD_DSN}" -f "${LOAD_ROOT}/sql/reset.sql"
psql "${LOAD_DSN}" \
    -v event_count=1 \
    -v event_type="${LOAD_EVENT_TYPE}" \
    -f "${LOAD_ROOT}/sql/seed.sql"

cd "${PROJECT_ROOT}"
uv run python -m load_tests.lease_recovery \
    --dsn "${LOAD_DSN}" \
    --lease-seconds "${LOAD_LEASE_SECONDS}" \
    --timeout-seconds "${LOAD_TIMEOUT_SECONDS}" \
    --monitor-timeout-seconds "${LOAD_MONITOR_TIMEOUT_SECONDS}" \
    --recovery-handler-delay-ms "${LOAD_RECOVERY_HANDLER_DELAY_MS}" \
    --json-output "${result_file}"

echo "Result saved to ${result_file}"
