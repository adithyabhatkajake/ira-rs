#!/bin/bash
# benchmark-all.sh — Run all configurations twice for error bars.
# Must be run as: sudo bash scripts/benchmark-all.sh
#
# Resume: sudo bash scripts/benchmark-all.sh --resume primary:2
#   Resumes from primary run 2 (skips baseline run 2).
#   Format: --resume <config>:<run>
#   Configs: baseline, primary, backup-0, backup-2, ..., backup-64
#
# Runs: reth-baseline, reth-primary, reth-backup (seq, 2, 4, 8, 12, 16, 24, 32, 48, 64)
# Each run is preceded by `purge` to flush the OS disk cache.
# Peak RSS is recorded for each run.

set -euo pipefail

# Defaults; override via env vars or CLI flags below.
DATADIR="${RETH_DATADIR:-./reth-datadir}"
HINT_DIR="${IRA_HINTS:-./ira-data/hints}"
OUTPUT_DIR="${IRA_OUTPUT:-data}"
BIN_DIR="${IRA_BIN_DIR:-target/release}"
TODAY=$(date +%Y.%m.%d)

# Parallel thread counts to benchmark
THREAD_COUNTS=(0 2 4 8 12 16 24 32 48 64)

# Number of additional runs (we already have 1 run for each)
RUNS=(2 3)

# Resume support
RESUME_CONFIG=""
RESUME_RUN=0
SKIP=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --datadir)     DATADIR="$2";     shift 2 ;;
        --hint-dir)    HINT_DIR="$2";    shift 2 ;;
        --output-dir)  OUTPUT_DIR="$2";  shift 2 ;;
        --bin-dir)     BIN_DIR="$2";     shift 2 ;;
        --resume)
            RESUME_CONFIG="${2%%:*}"
            RESUME_RUN="${2##*:}"
            SKIP=true
            echo "Resuming from ${RESUME_CONFIG} run ${RESUME_RUN}"
            shift 2 ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--datadir DIR] [--hint-dir DIR] [--output-dir DIR] [--bin-dir DIR] [--resume CONFIG:RUN]" >&2
            exit 1 ;;
    esac
done

# Check if we should skip this task or start running
should_run() {
    local config=$1
    local run=$2

    if [ "${SKIP}" = "false" ]; then
        return 0  # not skipping, run everything
    fi

    if [ "${config}" = "${RESUME_CONFIG}" ] && [ "${run}" -eq "${RESUME_RUN}" ]; then
        SKIP=false
        return 0  # this is the resume point, start running
    fi

    return 1  # still skipping
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

run_baseline() {
    local run=$1
    local label="${TODAY}.reth-baseline-run${run}"

    log "=== BASELINE run ${run} ==="
    log "Purging disk cache..."
    purge
    sleep 5

    log "Starting reth-baseline..."
    local start_time=$(date +%s)

    "${BIN_DIR}/reth-baseline" \
        --datadir "${DATADIR}" \
        --output-dir "${OUTPUT_DIR}"

    local end_time=$(date +%s)
    local wall_time=$((end_time - start_time))

    # Rename output file
    # reth-baseline writes to ${OUTPUT_DIR}/${date}.reth-baseline-run.csv (or with suffix)
    local src=$(ls -t "${OUTPUT_DIR}/"*.reth-baseline-run*.csv 2>/dev/null | head -1)
    if [ -n "${src}" ]; then
        mv "${src}" "${OUTPUT_DIR}/${label}-analysis-run.csv"
        log "Saved: ${OUTPUT_DIR}/${label}-analysis-run.csv"
    fi

    log "Baseline run ${run} complete. Wall time: ${wall_time}s"
    echo "${label},${wall_time}" >> "${OUTPUT_DIR}/${TODAY}.wall-times.csv"
}

run_primary() {
    local run=$1
    local label="${TODAY}.reth-primary-run${run}"

    log "=== PRIMARY run ${run} ==="
    log "Purging disk cache..."
    purge
    sleep 5

    log "Starting reth-primary..."
    local start_time=$(date +%s)

    "${BIN_DIR}/reth-primary" \
        --datadir "${DATADIR}" \
        --hint-dir "${HINT_DIR}" \
        --output-dir "${OUTPUT_DIR}"

    local end_time=$(date +%s)
    local wall_time=$((end_time - start_time))

    local src=$(ls -t "${OUTPUT_DIR}/"*.reth-primary-run*.csv 2>/dev/null | head -1)
    if [ -n "${src}" ]; then
        mv "${src}" "${OUTPUT_DIR}/${label}-analysis-run.csv"
        log "Saved: ${OUTPUT_DIR}/${label}-analysis-run.csv"
    fi

    log "Primary run ${run} complete. Wall time: ${wall_time}s"
    echo "${label},${wall_time}" >> "${OUTPUT_DIR}/${TODAY}.wall-times.csv"
}

run_backup() {
    local threads=$1
    local run=$2

    if [ "${threads}" -eq 0 ]; then
        local thread_label="sequential"
        local label="${TODAY}.reth-backup-sequential-run${run}"
    else
        local thread_label="parallel${threads}"
        local label="${TODAY}.reth-backup-${thread_label}-run${run}"
    fi

    log "=== BACKUP ${thread_label} run ${run} ==="
    log "Purging disk cache..."
    purge
    sleep 5

    log "Starting reth-backup (${thread_label})..."
    local start_time=$(date +%s)

    if [ "${threads}" -eq 0 ]; then
        "${BIN_DIR}/reth-backup" \
            --datadir "${DATADIR}" \
            --hint-dir "${HINT_DIR}" \
            --output-dir "${OUTPUT_DIR}"
    else
        "${BIN_DIR}/reth-backup" \
            --datadir "${DATADIR}" \
            --hint-dir "${HINT_DIR}" \
            --output-dir "${OUTPUT_DIR}" \
            --parallel-prefetch "${threads}"
    fi

    local end_time=$(date +%s)
    local wall_time=$((end_time - start_time))

    local src=$(ls -t "${OUTPUT_DIR}/"*.reth-backup-run*.csv 2>/dev/null | head -1)
    if [ -n "${src}" ]; then
        mv "${src}" "${OUTPUT_DIR}/${label}-analysis-run.csv"
        log "Saved: ${OUTPUT_DIR}/${label}-analysis-run.csv"
    fi

    log "Backup ${thread_label} run ${run} complete. Wall time: ${wall_time}s"
    echo "${label},${wall_time}" >> "${OUTPUT_DIR}/${TODAY}.wall-times.csv"
}

# ─── Main ────────────────────────────────────────────────────────────────

log "============================================================"
log "BENCHMARK ALL — 2 additional runs per configuration"
log "============================================================"
log "Output directory: ${OUTPUT_DIR}"
log "Binaries: ${BIN_DIR}"
log "Thread counts: ${THREAD_COUNTS[*]}"
log "Runs: ${RUNS[*]}"
log ""

# Initialize wall times CSV
echo "config,wall_time_seconds" >> "${OUTPUT_DIR}/${TODAY}.wall-times.csv"

for run in "${RUNS[@]}"; do
    log "============================================================"
    log "STARTING RUN ${run}"
    log "============================================================"

    # Baseline
    if should_run "baseline" "${run}"; then
        run_baseline "${run}"
    else
        log "Skipping baseline run ${run}"
    fi

    # Primary
    if should_run "primary" "${run}"; then
        run_primary "${run}"
    else
        log "Skipping primary run ${run}"
    fi

    # All backup configurations
    for threads in "${THREAD_COUNTS[@]}"; do
        if should_run "backup-${threads}" "${run}"; then
            run_backup "${threads}" "${run}"
        else
            log "Skipping backup-${threads} run ${run}"
        fi
    done

    log "Run ${run} complete."
    log ""
done

log "============================================================"
log "ALL BENCHMARKS COMPLETE"
log "============================================================"
log "Wall times saved to: ${OUTPUT_DIR}/${TODAY}.wall-times.csv"
