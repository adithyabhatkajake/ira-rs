#!/bin/bash
# Benchmark all three programs: reth-primary, reth-baseline, reth-backup
# Run with: ./scripts/benchmark-cold-cache.sh

set -e

# Configuration - modify these as needed
DATADIR="/Volumes/X/reth-eth-datadir"
HINT_DIR="/Volumes/X/ira-analysis/hints"
STATE_HASH_DIR="/Volumes/X/ira-analysis/state-hashes"
OUTPUT_DIR="data"
BIN_DIR="target/release"

START_BLOCK=24019447
END_BLOCK=24120246  # ~100,800 blocks (~2 weeks)
THREADS=8           # Number of threads for backup initial prefetch

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --datadir)
            DATADIR="$2"
            shift 2
            ;;
        --hint-dir)
            HINT_DIR="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --start-block)
            START_BLOCK="$2"
            shift 2
            ;;
        --end-block)
            END_BLOCK="$2"
            shift 2
            ;;
        --threads|-t)
            THREADS="$2"
            shift 2
            ;;
        --skip-primary)
            SKIP_PRIMARY=1
            shift
            ;;
        --skip-baseline)
            SKIP_BASELINE=1
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=1
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --datadir PATH       Path to reth data directory"
            echo "  --hint-dir PATH      Path to hint directory"
            echo "  --output-dir PATH    Output directory for CSV logs"
            echo "  --start-block N      Start block number"
            echo "  --end-block N        End block number"
            echo "  -t, --threads N      Number of threads for backup prefetch (default: 8)"
            echo "  --skip-primary       Skip reth-primary (use existing hints)"
            echo "  --skip-baseline      Skip reth-baseline"
            echo "  --skip-backup        Skip reth-backup"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

TOTAL_BLOCKS=$((END_BLOCK - START_BLOCK + 1))

echo "=============================================="
echo "Benchmark - All Three Programs"
echo "=============================================="
echo "Blocks: $START_BLOCK - $END_BLOCK ($TOTAL_BLOCKS blocks)"
echo "Backup prefetch threads: $THREADS"
echo "Data dir: $DATADIR"
echo "Hint dir: $HINT_DIR"
echo "Output dir: $OUTPUT_DIR"
echo ""

# Create output directory if needed
mkdir -p "$OUTPUT_DIR"

# Results file for peak RSS
TODAY=$(date +%Y.%m.%d)
RSS_FILE="$OUTPUT_DIR/$TODAY.peak-rss.txt"
echo "Peak RSS Results - $(date)" > "$RSS_FILE"
echo "Blocks: $START_BLOCK - $END_BLOCK ($TOTAL_BLOCKS blocks)" >> "$RSS_FILE"
echo "=============================================" >> "$RSS_FILE"
echo "" >> "$RSS_FILE"

# Build release binaries
echo "Building release binaries..."
cargo build --release -p reth-baseline -p reth-primary -p reth-backup
echo ""

# Function to extract peak RSS from CSV (in MB)
extract_peak_rss() {
    local csv_file="$1"
    local name="$2"
    if [ -f "$csv_file" ]; then
        # Find the column index for rss_bytes
        local header=$(head -1 "$csv_file")
        local rss_col=$(echo "$header" | tr ',' '\n' | grep -n "rss_bytes" | cut -d: -f1)
        if [ -n "$rss_col" ]; then
            local peak_bytes=$(awk -F',' -v col="$rss_col" 'NR>1 {if($col>max) max=$col} END {print max}' "$csv_file")
            local peak_mb=$((peak_bytes / 1024 / 1024))
            echo "$name: $peak_mb MB ($peak_bytes bytes)" >> "$RSS_FILE"
            echo "  Peak RSS: $peak_mb MB"
        else
            echo "$name: RSS column not found in CSV" >> "$RSS_FILE"
        fi
    fi
}

# 1. Baseline
if [ -z "$SKIP_BASELINE" ]; then
    echo ""
    echo "=============================================="
    echo "1. Running reth-baseline"
    echo "=============================================="
    echo "Purging OS disk cache..."
    sudo purge
    sleep 2

    BASELINE_START=$(date +%s)
    $BIN_DIR/reth-baseline \
        --datadir "$DATADIR" \
        --start-block $START_BLOCK \
        --end-block $END_BLOCK \
        --output-dir "$OUTPUT_DIR"
    BASELINE_END=$(date +%s)
    BASELINE_TIME=$((BASELINE_END - BASELINE_START))

    BASELINE_FILE=$(ls -t "$OUTPUT_DIR"/*.reth-baseline-run*.csv 2>/dev/null | head -1)
    echo "Output: $BASELINE_FILE"
    echo "Wall time: $BASELINE_TIME seconds"
    extract_peak_rss "$BASELINE_FILE" "reth-baseline"
    echo "reth-baseline wall time: $BASELINE_TIME seconds" >> "$RSS_FILE"
    echo "" >> "$RSS_FILE"
else
    echo ""
    echo "=============================================="
    echo "1. Skipping reth-baseline"
    echo "=============================================="
fi

# 2. Primary - generate hints (sequential)
if [ -z "$SKIP_PRIMARY" ]; then
    echo ""
    echo "=============================================="
    echo "2. Running reth-primary (sequential, generate hints)"
    echo "=============================================="
    echo "Purging OS disk cache..."
    sudo purge
    sleep 2

    PRIMARY_START=$(date +%s)
    $BIN_DIR/reth-primary \
        --datadir "$DATADIR" \
        --start-block $START_BLOCK \
        --end-block $END_BLOCK \
        --hint-dir "$HINT_DIR" \
        --state-hash-dir "$STATE_HASH_DIR" \
        --output-dir "$OUTPUT_DIR"
    PRIMARY_END=$(date +%s)
    PRIMARY_TIME=$((PRIMARY_END - PRIMARY_START))

    PRIMARY_FILE=$(ls -t "$OUTPUT_DIR"/*.reth-primary-run*.csv 2>/dev/null | head -1)
    echo "Output: $PRIMARY_FILE"
    echo "Wall time: $PRIMARY_TIME seconds"
    extract_peak_rss "$PRIMARY_FILE" "reth-primary"
    echo "reth-primary wall time: $PRIMARY_TIME seconds" >> "$RSS_FILE"
    echo "" >> "$RSS_FILE"
else
    echo ""
    echo "=============================================="
    echo "2. Skipping reth-primary (using existing hints)"
    echo "=============================================="
fi

# 3. Backup (pipelined)
if [ -z "$SKIP_BACKUP" ]; then
    echo ""
    echo "=============================================="
    echo "3. Running reth-backup (pipelined)"
    echo "=============================================="
    echo "Purging OS disk cache..."
    sudo purge
    sleep 2

    BACKUP_START=$(date +%s)
    $BIN_DIR/reth-backup \
        --datadir "$DATADIR" \
        --start-block $START_BLOCK \
        --end-block $END_BLOCK \
        --hint-dir "$HINT_DIR" \
        --state-hash-dir "$STATE_HASH_DIR" \
        --output-dir "$OUTPUT_DIR" \
        --threads $THREADS
    BACKUP_END=$(date +%s)
    BACKUP_TIME=$((BACKUP_END - BACKUP_START))

    BACKUP_FILE=$(ls -t "$OUTPUT_DIR"/*.reth-backup-run*.csv 2>/dev/null | head -1)
    echo "Output: $BACKUP_FILE"
    echo "Wall time: $BACKUP_TIME seconds"
    extract_peak_rss "$BACKUP_FILE" "reth-backup"
    echo "reth-backup wall time: $BACKUP_TIME seconds" >> "$RSS_FILE"
    echo "" >> "$RSS_FILE"
else
    echo ""
    echo "=============================================="
    echo "3. Skipping reth-backup"
    echo "=============================================="
fi

# Summary
echo ""
echo "=============================================="
echo "SOSP BENCHMARK RESULTS"
echo "=============================================="
echo "Blocks: $START_BLOCK - $END_BLOCK ($TOTAL_BLOCKS blocks, ~2 weeks)"
echo ""

# Calculate and display results
echo "┌─────────────────┬──────────────┬──────────────┬──────────────┐"
echo "│ Binary          │ Wall Time    │ Peak RSS     │ Blocks/sec   │"
echo "├─────────────────┼──────────────┼──────────────┼──────────────┤"

if [ -n "$BASELINE_TIME" ]; then
    BASELINE_BPS=$(echo "scale=2; $TOTAL_BLOCKS / $BASELINE_TIME" | bc)
    BASELINE_RSS_MB=$(awk -F',' 'NR>1 {if($NF>max) max=$NF} END {printf "%.0f", max/1024/1024}' "$BASELINE_FILE" 2>/dev/null || echo "N/A")
    printf "│ %-15s │ %10ss │ %8s MB │ %10s   │\n" "reth-baseline" "$BASELINE_TIME" "$BASELINE_RSS_MB" "$BASELINE_BPS"
fi

if [ -n "$PRIMARY_TIME" ]; then
    PRIMARY_BPS=$(echo "scale=2; $TOTAL_BLOCKS / $PRIMARY_TIME" | bc)
    PRIMARY_RSS_MB=$(awk -F',' 'NR>1 {if($NF>max) max=$NF} END {printf "%.0f", max/1024/1024}' "$PRIMARY_FILE" 2>/dev/null || echo "N/A")
    printf "│ %-15s │ %10ss │ %8s MB │ %10s   │\n" "reth-primary" "$PRIMARY_TIME" "$PRIMARY_RSS_MB" "$PRIMARY_BPS"
fi

if [ -n "$BACKUP_TIME" ]; then
    BACKUP_BPS=$(echo "scale=2; $TOTAL_BLOCKS / $BACKUP_TIME" | bc)
    BACKUP_RSS_MB=$(awk -F',' 'NR>1 {if($NF>max) max=$NF} END {printf "%.0f", max/1024/1024}' "$BACKUP_FILE" 2>/dev/null || echo "N/A")
    printf "│ %-15s │ %10ss │ %8s MB │ %10s   │\n" "reth-backup" "$BACKUP_TIME" "$BACKUP_RSS_MB" "$BACKUP_BPS"
fi

echo "└─────────────────┴──────────────┴──────────────┴──────────────┘"

# Speedup calculation
if [ -n "$BASELINE_TIME" ] && [ -n "$BACKUP_TIME" ]; then
    SPEEDUP=$(echo "scale=2; $BASELINE_TIME / $BACKUP_TIME" | bc)
    echo ""
    echo "Speedup (baseline/backup): ${SPEEDUP}x"
fi

# Primary overhead
if [ -n "$BASELINE_TIME" ] && [ -n "$PRIMARY_TIME" ]; then
    OVERHEAD=$(echo "scale=2; ($PRIMARY_TIME - $BASELINE_TIME) * 100 / $BASELINE_TIME" | bc)
    echo "Primary overhead: ${OVERHEAD}%"
fi

echo ""
echo "Output files:"
[ -n "$BASELINE_FILE" ] && echo "  Baseline: $BASELINE_FILE"
[ -n "$PRIMARY_FILE" ] && echo "  Primary:  $PRIMARY_FILE"
[ -n "$BACKUP_FILE" ] && echo "  Backup:   $BACKUP_FILE"
echo ""
echo "=============================================="
echo "Done!"
