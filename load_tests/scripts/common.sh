#!/usr/bin/env bash

set -euo pipefail

LOAD_ROOT="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(CDPATH='' cd -- "${LOAD_ROOT}/.." && pwd)"
export PROJECT_ROOT

load_scenario() {
    local scenario_file="$1"
    if [[ ! -f "${scenario_file}" ]]; then
        echo "Scenario file not found: ${scenario_file}" >&2
        exit 1
    fi
    set -a
    # shellcheck source=/dev/null
    source "${scenario_file}"
    set +a
}

load_defaults() {
    : "${LOAD_DSN:=host=localhost port=5432 dbname=outbox user=postgres password=postgres}"
    : "${LOAD_EVENT_TYPE:=load.test}"
    : "${LOAD_EVENTS:=100000}"
    : "${LOAD_PROCESSES:=4}"
    : "${LOAD_BATCH_SIZE:=100}"
    : "${LOAD_MAX_PARALLEL:=10}"
    : "${LOAD_POLL_INTERVAL:=0.01}"
    : "${LOAD_LEASE_SECONDS:=300}"
    : "${LOAD_TIMEOUT_SECONDS:=600}"
    : "${LOAD_MONITOR_TIMEOUT_SECONDS:=10}"
    : "${LOAD_HANDLER_DELAY_MS:=0}"
    : "${LOAD_HANDLER_JITTER_MS:=0}"
    : "${LOAD_FAILURE_RATE:=0}"
    : "${LOAD_RECOVERY_HANDLER_DELAY_MS:=200}"
    : "${LOAD_DURATION_SECONDS:=300}"
    : "${LOAD_PGBENCH_CLIENTS:=4}"
    : "${LOAD_PGBENCH_THREADS:=2}"
    : "${LOAD_RATE:=1000}"
    export LOAD_DSN LOAD_EVENT_TYPE LOAD_EVENTS LOAD_PROCESSES LOAD_BATCH_SIZE
    export LOAD_MAX_PARALLEL LOAD_POLL_INTERVAL LOAD_LEASE_SECONDS LOAD_TIMEOUT_SECONDS
    export LOAD_MONITOR_TIMEOUT_SECONDS
    export LOAD_HANDLER_DELAY_MS LOAD_HANDLER_JITTER_MS LOAD_FAILURE_RATE
    export LOAD_RECOVERY_HANDLER_DELAY_MS
    export LOAD_DURATION_SECONDS LOAD_PGBENCH_CLIENTS LOAD_PGBENCH_THREADS LOAD_RATE
}

require_commands() {
    local command_name
    for command_name in "$@"; do
        if ! command -v "${command_name}" >/dev/null 2>&1; then
            echo "Required command not found: ${command_name}" >&2
            exit 1
        fi
    done
}

validate_positive_integer() {
    local name="$1"
    local value="$2"
    if [[ ! "${value}" =~ ^[1-9][0-9]*$ ]]; then
        echo "${name} must be a positive integer, got: ${value}" >&2
        exit 1
    fi
}

result_timestamp() {
    date -u +%Y%m%dT%H%M%SZ
}
