"""
Process evaluation CSV files to generate performance macros.

Generates macros for:
- Primary overhead (wall time, per-block hint cost)
- Hint sizes (compressed, raw, compression ratio)
- Backup speedup (per-block speedup distribution, tail behavior, wait time)
- Thread scaling (wall time at different thread counts)
- Resource usage (peak RSS)

Data sources:
    data/2026.01.15.reth-primary-analysis-run.csv
    data/2026.01.15.reth-baseline-analysis-run.csv
    data/2026.01.16.reth-backup-sequential-analysis-run.csv
    data/2026.01.16.reth-backup-parallel16-analysis-run.csv
    data/2026.01.16.reth-backup-parallel64-analysis-run.csv
    data/2026.01.09.measure-hint-size.csv
    data/2026.01.15.peak-rss.txt
    data/2026.01.16.peak-rss.txt
"""

import csv
import re
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def process_evaluation(macros):
    """Process evaluation data and generate macros.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    # =========================================================================
    # Primary Overhead
    # =========================================================================
    primary_csv = DATA_DIR / "2026.01.15.reth-primary-analysis-run.csv"
    baseline_csv = DATA_DIR / "2026.01.15.reth-baseline-analysis-run.csv"

    if not primary_csv.exists() or not baseline_csv.exists():
        print(f"Warning: primary/baseline CSVs not found, skipping evaluation")
        return

    macros.section("Evaluation: Primary Overhead")

    # Read primary data
    primary_rows = []
    with open(primary_csv) as f:
        for row in csv.DictReader(f):
            primary_rows.append(row)

    total_exec_us = sum(int(r["execution_time_us"]) for r in primary_rows)
    total_hint_construct_us = sum(int(r["hint_construction_time_us"]) for r in primary_rows)
    total_hint_write_us = sum(int(r["hint_write_time_us"]) for r in primary_rows)
    total_hint_us = total_hint_construct_us + total_hint_write_us
    num_blocks = len(primary_rows)

    # Per-block hint fraction
    hint_fractions = []
    for r in primary_rows:
        exec_t = int(r["execution_time_us"])
        hint_c = int(r["hint_construction_time_us"])
        hint_w = int(r["hint_write_time_us"])
        if exec_t > 0:
            hint_fractions.append((hint_c + hint_w) / exec_t)

    hint_fractions_sorted = sorted(hint_fractions)
    n = len(hint_fractions)

    macros.add("EvalBlockCount", format_int(num_blocks), "Blocks in evaluation")
    macros.add("EvalPrimaryExecTimeSec", format_int(int(total_exec_us / 1e6)),
               "Primary aggregate execution time (s)")
    macros.add("EvalHintConstructTimeSec", format_int(int(total_hint_construct_us / 1e6)),
               "Hint construction time (s)")
    macros.add("EvalHintWriteTimeSec", format_int(int(total_hint_write_us / 1e6)),
               "Hint write/serialization time (s)")
    macros.add("EvalHintTotalTimeSec", format_int(int(total_hint_us / 1e6)),
               "Total hint time (s)")
    macros.add("EvalHintOverheadPct", format_percent(total_hint_us / total_exec_us * 100, 1),
               "Hint overhead as pct of execution time")
    macros.add("EvalHintConstructOverheadPct",
               format_percent(total_hint_construct_us / total_exec_us * 100, 1),
               "Hint construction overhead as pct of execution time")
    macros.add("EvalHintWriteOverheadPct",
               format_percent(total_hint_write_us / total_exec_us * 100, 1),
               "Hint serialization overhead as pct of execution time")
    macros.add("EvalHintFractionMedianPct",
               format_percent(statistics.median(hint_fractions) * 100, 1),
               "Median per-block hint fraction")
    macros.add("EvalHintFractionPNinetyFivePct",
               format_percent(hint_fractions_sorted[int(n * 0.95)] * 100, 1),
               "P95 per-block hint fraction")

    # Generate per-block hint cost figure
    block_numbers = [int(r["block_number"]) for r in primary_rows if int(r["execution_time_us"]) > 0]
    construction_fracs = []
    write_fracs = []
    construction_ms = []
    write_ms = []
    for r in primary_rows:
        exec_t = int(r["execution_time_us"])
        if exec_t > 0:
            construction_fracs.append(int(r["hint_construction_time_us"]) / exec_t * 100)
            write_fracs.append(int(r["hint_write_time_us"]) / exec_t * 100)
            construction_ms.append(int(r["hint_construction_time_us"]) / 1000)
            write_ms.append(int(r["hint_write_time_us"]) / 1000)

    construction_ms_arr = np.array(construction_ms)
    write_ms_arr = np.array(write_ms)

    macros.add("EvalConstructMedianMs", format_float(float(np.median(construction_ms_arr)), 1),
               "Median per-block construction time (ms)")
    macros.add("EvalConstructPNinetyFiveMs", format_float(float(np.percentile(construction_ms_arr, 95)), 1),
               "P95 per-block construction time (ms)")
    macros.add("EvalWriteMedianMs", format_float(float(np.median(write_ms_arr)), 1),
               "Median per-block serialization time (ms)")
    macros.add("EvalWritePNinetyFiveMs", format_float(float(np.percentile(write_ms_arr, 95)), 1),
               "P95 per-block serialization time (ms)")

    _generate_per_block_hint_cost_figure(
        np.array(block_numbers),
        np.array(construction_fracs),
        np.array(write_fracs),
        PROJECT_ROOT / "figures" / "per-block-hint-cost.pdf",
    )

    _generate_per_block_hint_cost_absolute_figure(
        construction_ms_arr,
        write_ms_arr,
        PROJECT_ROOT / "figures" / "per-block-hint-cost-absolute.pdf",
    )

    # =========================================================================
    # Hint Cost Scaling Analysis
    # =========================================================================
    macros.section("Evaluation: Hint Cost Scaling")

    # Load unique keys per block
    unique_keys_csv = DATA_DIR / "2026.01.20.per-block-unique-keys.csv"
    if unique_keys_csv.exists():
        unique_keys_map = {}
        with open(unique_keys_csv) as f:
            for row in csv.DictReader(f):
                unique_keys_map[int(row["block_number"])] = int(row["unique_storage_keys"])

        # Build paired arrays for blocks with both primary and unique_keys data
        construct_times_us = []
        write_times_us = []
        exec_times_us = []
        keys_arr = []
        hint_frac_arr = []

        for r in primary_rows:
            bn = int(r["block_number"])
            exec_t = int(r["execution_time_us"])
            if exec_t > 0 and bn in unique_keys_map:
                c = int(r["hint_construction_time_us"])
                w = int(r["hint_write_time_us"])
                construct_times_us.append(c)
                write_times_us.append(w)
                exec_times_us.append(exec_t)
                keys_arr.append(unique_keys_map[bn])
                hint_frac_arr.append((c + w) / exec_t * 100)

        construct_times_us = np.array(construct_times_us, dtype=float)
        write_times_us = np.array(write_times_us, dtype=float)
        exec_times_us = np.array(exec_times_us, dtype=float)
        keys_arr = np.array(keys_arr, dtype=float)
        hint_frac_arr = np.array(hint_frac_arr)
        hint_total_us = construct_times_us + write_times_us

        # Per-key construction cost
        construct_per_key = construct_times_us / keys_arr
        macros.add("EvalConstructPerKeyUs",
                   format_float(np.median(construct_per_key), 1),
                   "Median construction cost per key (us)")
        macros.add("EvalConstructPerKeyCV",
                   format_float(np.std(construct_per_key) / np.mean(construct_per_key), 2),
                   "CV of per-key construction cost")

        # Serialization time stats
        write_ms = write_times_us / 1e3
        macros.add("EvalSerializationMedianMs",
                   format_float(np.median(write_ms), 1),
                   "Median serialization time (ms)")
        macros.add("EvalSerializationIQRLowMs",
                   format_float(np.percentile(write_ms, 25), 1),
                   "Serialization P25 (ms)")
        macros.add("EvalSerializationIQRHighMs",
                   format_float(np.percentile(write_ms, 75), 1),
                   "Serialization P75 (ms)")

        # Variance decomposition
        actual_var = np.var(hint_frac_arr)
        exec_fixed = np.full_like(exec_times_us, np.median(exec_times_us))
        frac_fixed_exec = hint_total_us / exec_fixed * 100
        var_reduction_exec = (1 - np.var(frac_fixed_exec) / actual_var) * 100

        write_fixed = np.full_like(write_times_us, np.median(write_times_us))
        frac_fixed_write = (construct_times_us + write_fixed) / exec_times_us * 100
        var_reduction_write = (1 - np.var(frac_fixed_write) / actual_var) * 100

        macros.add("EvalHintFracVarFromExecPct",
                   format_int(int(round(var_reduction_exec))),
                   "Pct of hint frac variance explained by exec time")
        macros.add("EvalHintFracVarFromWritePct",
                   format_int(int(round(var_reduction_write))),
                   "Pct of hint frac variance explained by write time")

        # Correlation coefficients
        r_construct_keys = np.corrcoef(construct_times_us, keys_arr)[0, 1]
        r_write_keys = np.corrcoef(write_times_us, keys_arr)[0, 1]
        macros.add("EvalConstructKeysCorr",
                   format_float(r_construct_keys, 2),
                   "Pearson r: construction time vs unique keys")
        macros.add("EvalWriteKeysCorr",
                   format_float(r_write_keys, 2),
                   "Pearson r: serialization time vs unique keys")

        # Binned hint fraction by working set size
        bins = [(0, 500), (500, 1000), (1000, 2000), (2000, 3000),
                (3000, 5000), (5000, 100000)]
        bin_labels = ["LtFiveHundred", "FiveHundredToOneK", "OneKToTwoK",
                      "TwoKToThreeK", "ThreeKToFiveK", "GtFiveK"]
        bin_display = ["$<$500", "500--1K", "1K--2K", "2K--3K", "3K--5K", "$>$5K"]

        for (lo, hi), label, display in zip(bins, bin_labels, bin_display):
            mask = (keys_arr >= lo) & (keys_arr < hi)
            if mask.sum() > 10:
                macros.add(f"EvalBin{label}Count",
                           format_int(int(mask.sum())),
                           f"Blocks with {display} keys")
                macros.add(f"EvalBin{label}HintFracMedian",
                           format_float(np.median(hint_frac_arr[mask]), 1),
                           f"Median hint frac for {display} keys")
                macros.add(f"EvalBin{label}ExecMedianMs",
                           format_int(int(np.median(exec_times_us[mask] / 1e3))),
                           f"Median exec time for {display} keys (ms)")
                macros.add(f"EvalBin{label}HintMedianMs",
                           format_float(np.median(hint_total_us[mask] / 1e3), 1),
                           f"Median hint time for {display} keys (ms)")

        # Generate scaling figure
        _generate_hint_cost_scaling_figure(
            keys_arr, construct_times_us, write_times_us,
            PROJECT_ROOT / "figures" / "hint-cost-scaling.pdf",
        )

    # =========================================================================
    # Wall-Time Overhead (from peak-rss.txt files)
    # =========================================================================
    macros.section("Evaluation: Wall Time")

    rss_primary = DATA_DIR / "2026.01.15.peak-rss.txt"
    rss_backup = DATA_DIR / "2026.01.16.peak-rss.txt"

    baseline_wall_s = None
    primary_wall_s = None
    backup_wall_s = None
    baseline_rss_mb = None
    primary_rss_mb = None
    backup_rss_mb = None

    if rss_primary.exists():
        text = rss_primary.read_text()
        for line in text.splitlines():
            if "reth-baseline wall time:" in line:
                baseline_wall_s = int(re.search(r"(\d+)\s+seconds", line).group(1))
            elif "reth-primary wall time:" in line:
                primary_wall_s = int(re.search(r"(\d+)\s+seconds", line).group(1))
            elif line.startswith("reth-baseline:"):
                baseline_rss_mb = int(re.search(r"(\d+)\s+MB", line).group(1))
            elif line.startswith("reth-primary:"):
                primary_rss_mb = int(re.search(r"(\d+)\s+MB", line).group(1))

    if rss_backup.exists():
        text = rss_backup.read_text()
        for line in text.splitlines():
            if "reth-backup wall time:" in line:
                backup_wall_s = int(re.search(r"(\d+)\s+seconds", line).group(1))
            elif line.startswith("reth-backup:"):
                backup_rss_mb = int(re.search(r"(\d+)\s+MB", line).group(1))

    if baseline_wall_s is not None:
        macros.add("EvalBaselineWallTimeSec", format_int(baseline_wall_s),
                   "Baseline wall time (s)")
    if primary_wall_s is not None:
        macros.add("EvalPrimaryWallTimeSec", format_int(primary_wall_s),
                   "Primary wall time (s)")
    if baseline_wall_s and primary_wall_s:
        overhead = (primary_wall_s - baseline_wall_s) / baseline_wall_s * 100
        macros.add("EvalPrimaryWallOverheadPct", format_percent(overhead, 1),
                   "Primary wall-time overhead pct")

    # =========================================================================
    # Hint Sizes
    # =========================================================================
    macros.section("Evaluation: Hint Sizes")

    hint_csv = DATA_DIR / "2026.01.09.measure-hint-size.csv"
    if hint_csv.exists():
        hint_block_numbers = []
        compressed_sizes = []
        raw_sizes = []
        with open(hint_csv) as f:
            for row in csv.DictReader(f):
                hint_block_numbers.append(int(row["block_number"]))
                compressed_sizes.append(int(row["compressed_size_bytes"]))
                raw_sizes.append(int(row["raw_size_bytes"]))

        compressed_sorted = sorted(compressed_sizes)
        hn = len(compressed_sizes)

        macros.add("EvalHintCompressedMedianKB",
                   format_float(statistics.median(compressed_sizes) / 1024, 1),
                   "Median compressed hint size (KB)")
        macros.add("EvalHintCompressedMeanKB",
                   format_float(statistics.mean(compressed_sizes) / 1024, 1),
                   "Mean compressed hint size (KB)")
        macros.add("EvalHintCompressedPNinetyFiveKB",
                   format_float(compressed_sorted[int(hn * 0.95)] / 1024, 1),
                   "P95 compressed hint size (KB)")
        macros.add("EvalHintCompressedMaxKB",
                   format_float(max(compressed_sizes) / 1024, 1),
                   "Max compressed hint size (KB)")
        macros.add("EvalHintRawMedianKB",
                   format_float(statistics.median(raw_sizes) / 1024, 1),
                   "Median raw hint size (KB)")
        macros.add("EvalHintCompressionRatio",
                   format_float(statistics.mean(raw_sizes) / statistics.mean(compressed_sizes), 2),
                   "Hint compression ratio")

        # Generate hint size CDF figure
        _generate_hint_size_cdf_figure(
            np.array(compressed_sizes, dtype=float),
            np.array(raw_sizes, dtype=float),
            PROJECT_ROOT / "figures" / "hint-size-cdf.pdf",
        )

        # Generate hint size vs block number figure
        _generate_hint_size_vs_block_figure(
            np.array(hint_block_numbers, dtype=float),
            np.array(compressed_sizes, dtype=float),
            np.array(raw_sizes, dtype=float),
            PROJECT_ROOT / "figures" / "hint-size-per-block.pdf",
        )


    # =========================================================================
    # Backup Speedup
    # =========================================================================
    macros.section("Evaluation: Backup Speedup")

    # Read baseline execution times
    baseline_exec = {}
    with open(baseline_csv) as f:
        for row in csv.DictReader(f):
            baseline_exec[int(row["block_number"])] = int(row["execution_time_us"])

    baseline_total_us = sum(baseline_exec.values())
    macros.add("EvalBaselineTotalTimeSec", format_int(int(baseline_total_us / 1e6)),
               "Baseline aggregate execution time (s)")

    backup_configs = [
        ("Sequential", DATA_DIR / "2026.01.16.reth-backup-sequential-analysis-run.csv"),
        ("ParallelSixteen", DATA_DIR / "2026.01.16.reth-backup-parallel16-analysis-run.csv"),
        ("ParallelSixtyFour", DATA_DIR / "2026.01.16.reth-backup-parallel64-analysis-run.csv"),
    ]

    # Collect per-config data for figure generation
    all_speedups = {}
    all_wait_times = {}
    all_exec_times = {}
    all_wall_times = {}

    for label, csv_path in backup_configs:
        if not csv_path.exists():
            print(f"Warning: {csv_path} not found, skipping {label}")
            continue

        speedups = []
        speedup_block_numbers = []
        slower_count = 0
        wait_times = []
        exec_times = []
        total_backup_us = 0

        with open(csv_path) as f:
            for row in csv.DictReader(f):
                bn = int(row["block_number"])
                wait = int(row["wait_time_us"])
                backup_exec = int(row["execution_time_us"])
                wait_times.append(wait)
                exec_times.append(backup_exec)
                total_backup_us += wait + backup_exec

                if bn in baseline_exec:
                    base = baseline_exec[bn]
                    backup_total = wait + backup_exec
                    if backup_total > 0:
                        s = base / backup_total
                        speedups.append(s)
                        speedup_block_numbers.append(bn)
                        if s < 1.0:
                            slower_count += 1

        speedups_sorted = sorted(speedups)
        sn = len(speedups)

        # Save for figure generation
        all_speedups[label] = (np.array(speedup_block_numbers), np.array(speedups))
        all_wait_times[label] = np.array(wait_times, dtype=float)
        all_exec_times[label] = np.array(exec_times, dtype=float)
        all_wall_times[label] = total_backup_us

        # Speedup percentiles
        macros.add(f"EvalSpeedup{label}Median",
                   format_float(statistics.median(speedups), 1),
                   f"{label} median speedup")
        macros.add(f"EvalSpeedup{label}Mean",
                   format_float(statistics.mean(speedups), 1),
                   f"{label} mean speedup")
        macros.add(f"EvalSpeedup{label}PTen",
                   format_float(speedups_sorted[int(sn * 0.10)], 1),
                   f"{label} P10 speedup")
        macros.add(f"EvalSpeedup{label}PNinety",
                   format_float(speedups_sorted[int(sn * 0.90)], 1),
                   f"{label} P90 speedup")
        macros.add(f"EvalSpeedup{label}PNinetyNine",
                   format_float(speedups_sorted[int(sn * 0.99)], 1),
                   f"{label} P99 speedup")
        macros.add(f"EvalSpeedup{label}Max",
                   format_float(max(speedups), 1),
                   f"{label} max speedup")
        macros.add(f"EvalSpeedup{label}Min",
                   format_float(min(speedups), 4),
                   f"{label} min speedup")

        # Tail behavior
        macros.add(f"EvalSlower{label}Count",
                   format_int(slower_count),
                   f"{label} blocks slower than baseline")
        macros.add(f"EvalSlower{label}Pct",
                   format_percent(slower_count / sn * 100, 2),
                   f"{label} pct blocks slower")

        # Wall time
        macros.add(f"EvalWallTime{label}Sec",
                   format_int(int(total_backup_us / 1e6)),
                   f"{label} aggregate wall time (s)")
        wall_speedup = baseline_total_us / total_backup_us
        macros.add(f"EvalWallSpeedup{label}",
                   format_float(wall_speedup, 1),
                   f"{label} wall-time speedup vs baseline")

        # Wait time
        macros.add(f"EvalWaitMean{label}Ms",
                   format_float(statistics.mean(wait_times) / 1e3, 1),
                   f"{label} mean wait time (ms)")
        macros.add(f"EvalWaitMedian{label}Ms",
                   format_float(statistics.median(wait_times) / 1e3, 1),
                   f"{label} median wait time (ms)")
        wait_sorted = sorted(wait_times)
        macros.add(f"EvalWaitPNinetyFive{label}Ms",
                   format_float(wait_sorted[int(sn * 0.95)] / 1e3, 1),
                   f"{label} P95 wait time (ms)")

    # Generate backup speedup figures
    if all_speedups:
        _generate_speedup_cdf_figure(
            all_speedups,
            PROJECT_ROOT / "figures" / "speedup-per-block.pdf",
        )
        _generate_wait_time_cdf_figure(
            all_wait_times,
            all_exec_times,
            PROJECT_ROOT / "figures" / "wait-time-cdf.pdf",
        )

    # =========================================================================
    # Thread Scaling
    # =========================================================================
    macros.section("Evaluation: Thread Scaling")

    def _total_time_us(path):
        total = 0
        with open(path) as f:
            for row in csv.DictReader(f):
                total += int(row["wait_time_us"]) + int(row["execution_time_us"])
        return total

    # Discover all parallel config files and build thread_count -> wall_time map
    thread_times_us = {}  # thread_count -> total wall time in us

    # Sequential = 1 thread
    seq_path = DATA_DIR / "2026.01.16.reth-backup-sequential-analysis-run.csv"
    if seq_path.exists():
        thread_times_us[1] = _total_time_us(seq_path)

    # Find all parallel CSV files matching the naming pattern
    for csv_file in sorted(DATA_DIR.glob("*.reth-backup-parallel*-analysis-run.csv")):
        match = re.search(r"parallel(\d+)-analysis-run\.csv$", csv_file.name)
        if match:
            n_threads = int(match.group(1))
            thread_times_us[n_threads] = _total_time_us(csv_file)

    if thread_times_us:
        # Sort by thread count
        sorted_threads = sorted(thread_times_us.keys())

        # Add scaling macros for key transitions
        if 1 in thread_times_us and 16 in thread_times_us:
            macros.add("EvalScalingOneToSixteen",
                       format_float(thread_times_us[1] / thread_times_us[16], 1),
                       "Speedup from 1 to 16 threads")
        if 16 in thread_times_us and 64 in thread_times_us:
            macros.add("EvalScalingSixteenToSixtyFour",
                       format_float(thread_times_us[16] / thread_times_us[64], 1),
                       "Speedup from 16 to 64 threads")

        # Generate thread scaling figure with all data points
        _generate_thread_scaling_figure(
            baseline_total_us,
            thread_times_us,
            PROJECT_ROOT / "figures" / "thread-scaling.pdf",
        )

    # =========================================================================
    # Resource Usage (Peak RSS)
    # =========================================================================
    macros.section("Evaluation: Resource Usage")

    if baseline_rss_mb is not None:
        macros.add("EvalBaselineRssGB",
                   format_float(baseline_rss_mb / 1024, 1),
                   "Baseline peak RSS (GB)")
    if primary_rss_mb is not None:
        macros.add("EvalPrimaryRssGB",
                   format_float(primary_rss_mb / 1024, 1),
                   "Primary peak RSS (GB)")
    if backup_rss_mb is not None:
        macros.add("EvalBackupRssGB",
                   format_float(backup_rss_mb / 1024, 1),
                   "Backup peak RSS (GB)")


def _generate_per_block_hint_cost_figure(block_numbers, construction_pct, write_pct, output_path):
    """Generate CDF of per-block hint cost as a fraction of execution time.

    Shows three CDF lines: total hint cost, construction only, and
    serialization only, so the reader can see the relative contribution
    of each component.  X-axis is clipped at the 99.9th percentile to
    keep the meaningful range visible (a small number of very-short
    blocks produce extreme outlier ratios).
    """
    total_pct = construction_pct + write_pct

    # Sort for CDF
    total_sorted = np.sort(total_pct)
    construction_sorted = np.sort(construction_pct)
    write_sorted = np.sort(write_pct)
    n = len(total_sorted)
    cdf_y = np.arange(1, n + 1) / n

    fig, ax = plt.subplots(figsize=(6, 3))

    ax.plot(total_sorted, cdf_y, color="#2171b5", linewidth=1.5,
            label="Total hint generation cost")
    ax.plot(construction_sorted, cdf_y, color="#6baed6", linewidth=1.2,
            linestyle="--", label="Construction only")
    ax.plot(write_sorted, cdf_y, color="#fd8d3c", linewidth=1.2,
            linestyle=":", label="Serialization only")

    # Mark median and P95 of total
    median_val = np.median(total_pct)
    p95_val = np.percentile(total_pct, 95)

    ax.axvline(median_val, color="#888888", linewidth=0.8, linestyle="-", alpha=0.5)
    ax.axvline(p95_val, color="#888888", linewidth=0.8, linestyle="-", alpha=0.5)
    ax.annotate(f"median\n{median_val:.1f}%", xy=(median_val, 0.50),
                xytext=(median_val + 4, 0.35), fontsize=7, color="#555555",
                arrowprops=dict(arrowstyle="-", color="#888888", lw=0.5))
    ax.annotate(f"P95\n{p95_val:.1f}%", xy=(p95_val, 0.95),
                xytext=(p95_val + 4, 0.80), fontsize=7, color="#555555",
                arrowprops=dict(arrowstyle="-", color="#888888", lw=0.5))

    # Clip x-axis to P99.5 to focus on the meaningful range;
    # only 0.5% of blocks exceed this threshold (short blocks with
    # disproportionate hint cost).
    x_max = np.percentile(total_pct, 99.5)
    # Round up to nearest 5
    x_max = int(np.ceil(x_max / 5) * 5)

    ax.set_xlabel("Hint cost (% of block execution time)")
    ax.set_ylabel("CDF")
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, 1.02)

    ax.legend(loc="center right", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_per_block_hint_cost_absolute_figure(construction_ms, write_ms, output_path):
    """Generate CDF of per-block hint cost in absolute time (ms).

    Companion to the fraction-based CDF: shows the same three distributions
    (construction, serialization, total) but with milliseconds on the x-axis
    so the reader can see that construction dominates in absolute time even
    though serialization dominates the per-block fraction for short blocks.
    """
    total_ms = construction_ms + write_ms

    # Sort for CDF
    total_sorted = np.sort(total_ms)
    construction_sorted = np.sort(construction_ms)
    write_sorted = np.sort(write_ms)
    n = len(total_sorted)
    cdf_y = np.arange(1, n + 1) / n

    fig, ax = plt.subplots(figsize=(6, 3))

    ax.plot(total_sorted, cdf_y, color="#2171b5", linewidth=1.5,
            label="Total hint generation cost")
    ax.plot(construction_sorted, cdf_y, color="#6baed6", linewidth=1.2,
            linestyle="--", label="Construction only")
    ax.plot(write_sorted, cdf_y, color="#fd8d3c", linewidth=1.2,
            linestyle=":", label="Serialization only")

    # Mark medians
    median_construct = np.median(construction_ms)
    median_write = np.median(write_ms)
    median_total = np.median(total_ms)

    ax.axvline(median_construct, color="#6baed6", linewidth=0.8, linestyle="--", alpha=0.4)
    ax.axvline(median_write, color="#fd8d3c", linewidth=0.8, linestyle=":", alpha=0.4)
    ax.axvline(median_total, color="#888888", linewidth=0.8, linestyle="-", alpha=0.5)
    ax.annotate(f"median total\n{median_total:.1f} ms", xy=(median_total, 0.50),
                xytext=(median_total + 8, 0.35), fontsize=7, color="#555555",
                arrowprops=dict(arrowstyle="-", color="#888888", lw=0.5))

    # Clip x-axis at P99.5 of total
    x_max = np.percentile(total_ms, 99.5)
    x_max = int(np.ceil(x_max / 10) * 10)

    ax.set_xlabel("Hint cost per block (ms)")
    ax.set_ylabel("CDF")
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, 1.02)

    ax.legend(loc="center right", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_hint_cost_scaling_figure(keys, construct_us, write_us, output_path):
    """Generate dual-panel scatter plot showing hint cost scaling.

    Left panel: construction time vs unique keys (linear scaling).
    Right panel: serialization time vs unique keys (flat / constant).
    """
    construct_ms = construct_us / 1e3
    write_ms = write_us / 1e3

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 2.8),
                                    gridspec_kw={"width_ratios": [1, 1]})

    # Common x-axis range
    x_max = np.percentile(keys, 99.5)
    x_max = int(np.ceil(x_max / 1000) * 1000)

    # Subsample for scatter readability (60K points is too dense)
    rng = np.random.default_rng(42)
    n = len(keys)
    idx = rng.choice(n, size=min(3000, n), replace=False)

    # --- Left panel: construction time vs keys ---
    ax1.scatter(keys[idx], construct_ms[idx], s=1, alpha=0.3, color="#2171b5",
                rasterized=True)

    # Linear fit — display slope in us/key for readability
    coeffs = np.polyfit(keys, construct_ms, 1)
    slope_us_per_key = coeffs[0] * 1000  # ms/key -> us/key
    x_fit = np.linspace(0, x_max, 100)
    ax1.plot(x_fit, np.polyval(coeffs, x_fit), color="#d94801", linewidth=1.2,
             label=f"fit: {slope_us_per_key:.0f} $\\mu$s/key")

    ax1.set_xlabel("Unique storage keys")
    ax1.set_ylabel("Time (ms)")
    ax1.set_title("Construction", fontsize=9)
    ax1.set_xlim(0, x_max)
    ax1.set_ylim(0, None)
    ax1.legend(fontsize=6.5, frameon=False, loc="upper left")

    # Annotate Pearson r
    r_val = np.corrcoef(keys, construct_ms)[0, 1]
    ax1.annotate(f"r = {r_val:.2f}", xy=(0.95, 0.05), xycoords="axes fraction",
                 fontsize=7, ha="right", color="#555555")

    # --- Right panel: serialization time vs keys ---
    ax2.scatter(keys[idx], write_ms[idx], s=1, alpha=0.3, color="#fd8d3c",
                rasterized=True)

    # Clip y-axis to P99 to avoid extreme outliers dominating
    y_max = np.percentile(write_ms, 99)
    y_max = int(np.ceil(y_max / 5) * 5)

    ax2.set_xlabel("Unique storage keys")
    ax2.set_title("Serialization", fontsize=9)
    ax2.set_xlim(0, x_max)
    ax2.set_ylim(0, y_max)

    # Annotate Pearson r
    r_val2 = np.corrcoef(keys, write_ms)[0, 1]
    ax2.annotate(f"r = {r_val2:.2f}", xy=(0.95, 0.05), xycoords="axes fraction",
                 fontsize=7, ha="right", color="#555555")

    # Annotate median as horizontal line
    med_write = np.median(write_ms)
    ax2.axhline(med_write, color="#888888", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.annotate(f"median = {med_write:.1f} ms", xy=(x_max * 0.55, med_write),
                 xytext=(x_max * 0.55, med_write + y_max * 0.15),
                 fontsize=6.5, color="#555555",
                 arrowprops=dict(arrowstyle="-", color="#888888", lw=0.5))

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_hint_size_cdf_figure(compressed_bytes, raw_bytes, output_path):
    """Generate CDF + histogram combo of hint sizes per block.

    Primary axis: histogram of compressed hint sizes (filled bars) with
    a lighter overlay for raw sizes, giving density context.
    Secondary axis: CDF line of compressed sizes for precise percentile
    reading.  Annotates median and P95 on the CDF.
    """
    compressed_kb = compressed_bytes / 1024
    raw_kb = raw_bytes / 1024

    # Clip at P99.5 for readability; tail is sparse and stretches the axis
    x_clip = float(np.percentile(raw_kb, 99.5))
    x_max = int(np.ceil(x_clip / 25) * 25)  # round up to nearest 25 KB
    bins = np.arange(0, x_max + 5, 5)  # 5 KB bins

    fig, ax_hist = plt.subplots(figsize=(6, 3))
    ax_cdf = ax_hist.twinx()

    # --- Histogram (back layer) ---
    ax_hist.hist(raw_kb, bins=bins, color="#fdae6b", alpha=0.45,
                 edgecolor="none", label="Raw", zorder=1)
    ax_hist.hist(compressed_kb, bins=bins, color="#6baed6", alpha=0.7,
                 edgecolor="none", label="Compressed", zorder=2)

    # --- CDF (front layer) ---
    compressed_sorted = np.sort(compressed_kb)
    n = len(compressed_sorted)
    cdf_y = np.arange(1, n + 1) / n
    ax_cdf.plot(compressed_sorted, cdf_y, color="#08519c", linewidth=1.6,
                zorder=3, label="CDF (compressed)")

    # Mark median and P95 on CDF
    median_val = float(np.median(compressed_kb))
    p95_val = float(np.percentile(compressed_kb, 95))

    for val, pct_label, y_anchor, txt_offset in [
        (median_val, "median", 0.50, (18, -0.12)),
        (p95_val, "P95", 0.95, (18, -0.12)),
    ]:
        ax_cdf.plot(val, y_anchor, "o", color="#08519c", markersize=4, zorder=4)
        ax_cdf.annotate(
            f"{pct_label}\n{val:.1f} KB",
            xy=(val, y_anchor),
            xytext=(val + txt_offset[0], y_anchor + txt_offset[1]),
            fontsize=7, color="#333333",
            arrowprops=dict(arrowstyle="-", color="#888888", lw=0.6),
            zorder=5,
        )

    # --- Axes ---
    ax_hist.set_xlabel("Hint size (KB)")
    ax_hist.set_ylabel("Blocks per 5 KB bin")
    ax_cdf.set_ylabel("CDF")
    ax_hist.set_xlim(0, x_max)
    ax_cdf.set_ylim(0, 1.02)

    # Combine legends from both axes
    h1, l1 = ax_hist.get_legend_handles_labels()
    h2, l2 = ax_cdf.get_legend_handles_labels()
    ax_cdf.legend(h1 + h2, l1 + l2, loc="center right", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_speedup_cdf_figure(all_speedups, output_path):
    """Generate block-by-block speedup scatter with rolling average.

    Shows per-block speedup (sequential backup vs baseline) as a light
    scatter with a 500-block rolling average overlay.  A horizontal
    dashed line marks the median, and a shaded P5--P95 band gives the
    spread.  Only the sequential configuration is plotted (the three
    configs are nearly identical).
    """
    blocks, speedups = all_speedups["Sequential"]

    # Sort by block number
    order = np.argsort(blocks)
    blocks = blocks[order]
    speedups = speedups[order]

    window = 500

    def _rolling(arr, func):
        """Compute a rolling statistic over non-overlapping-ish windows."""
        out = np.empty(len(arr) - window + 1)
        for i in range(len(out)):
            out[i] = func(arr[i:i + window])
        return out

    # Use fast rolling mean via cumsum
    def _rolling_mean(arr):
        cs = np.cumsum(arr)
        cs = np.insert(cs, 0, 0)
        return (cs[window:] - cs[:-window]) / window

    blocks_smooth = _rolling_mean(blocks.astype(float))
    speedup_smooth = _rolling_mean(speedups)

    # Rolling P5 and P95 (strided for speed — compute every 50th window)
    stride = 50
    p5_pts = []
    p95_pts = []
    block_pts = []
    for i in range(0, len(speedups) - window + 1, stride):
        chunk = speedups[i:i + window]
        p5_pts.append(np.percentile(chunk, 5))
        p95_pts.append(np.percentile(chunk, 95))
        block_pts.append(np.mean(blocks[i:i + window]))
    p5_pts = np.array(p5_pts)
    p95_pts = np.array(p95_pts)
    block_pts = np.array(block_pts)

    fig, ax = plt.subplots(figsize=(6, 3))

    # Light scatter (subsampled for readability)
    rng = np.random.default_rng(42)
    n = len(blocks)
    idx = rng.choice(n, size=min(4000, n), replace=False)
    # Clip scatter y for visual clarity
    y_clip = np.percentile(speedups, 99.5)
    scatter_speedups = np.clip(speedups[idx], 0, y_clip)
    ax.scatter(blocks[idx], scatter_speedups, s=0.3, alpha=0.15,
               color="#9ecae1", rasterized=True, zorder=1)

    # P5--P95 shaded band
    ax.fill_between(block_pts, p5_pts, np.clip(p95_pts, 0, y_clip),
                    color="#c6dbef", alpha=0.5, zorder=2,
                    label="P5\u2013P95 band (500-block)")

    # Rolling mean line
    ax.plot(blocks_smooth, speedup_smooth, color="#2171b5", linewidth=1.2,
            zorder=3, label="500-block rolling mean")

    # Median horizontal line
    median_val = float(np.median(speedups))
    ax.axhline(median_val, color="#d94801", linewidth=0.9, linestyle="--",
               alpha=0.7, zorder=4)
    # Place label at ~80% along the x-axis, well above the line
    x_label = blocks[0] + 0.80 * (blocks[-1] - blocks[0])
    y_label = median_val + (y_clip - median_val) * 0.35
    ax.annotate(f"median {median_val:.1f}$\\times$",
                xy=(x_label, median_val),
                xytext=(x_label, y_label),
                fontsize=7, color="#d94801", ha="center", zorder=5,
                arrowprops=dict(arrowstyle="-|>", color="#d94801",
                                lw=0.8, shrinkA=0, shrinkB=2))

    # Break-even line at 1.0
    ax.axhline(1.0, color="#888888", linewidth=0.6, linestyle=":", alpha=0.5,
               zorder=4)

    ax.set_xlabel("Block number")
    ax.set_ylabel("Per-block speedup ($\\times$)")
    ax.set_xlim(blocks[0], blocks[-1])
    ax.set_ylim(0, y_clip * 1.05)

    # Format x-axis with millions
    ax.xaxis.set_major_formatter(
        ticker.FuncFormatter(lambda x, _: f"{x / 1e6:.2f}M"))

    ax.legend(loc="upper left", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_wait_time_cdf_figure(all_wait_times, all_exec_times, output_path):
    """Generate stacked bar chart of wall time by wait category.

    For each backup configuration, shows total wall time split into two
    segments: time from zero-wait blocks (bottom) and time from
    nonzero-wait blocks (top).  Annotations show the percentage of
    blocks and wall-time share for each segment.
    """
    fig, ax = plt.subplots(figsize=(5, 3))

    config_order = ["Sequential", "ParallelSixteen", "ParallelSixtyFour"]
    config_labels = {
        "Sequential": "Sequential",
        "ParallelSixteen": "Parallel-16",
        "ParallelSixtyFour": "Parallel-64",
    }

    bar_labels = []
    zero_wait_s = []
    nonzero_wait_s = []
    annotations = []  # (pct_nonzero_blocks, pct_nonzero_wall)

    for label in config_order:
        if label not in all_wait_times:
            continue
        wait_us = all_wait_times[label]
        exec_us = all_exec_times[label]
        per_block_wall = wait_us + exec_us

        is_nonzero = wait_us > 0
        wall_zero = float(np.sum(per_block_wall[~is_nonzero])) / 1e6  # seconds
        wall_nonzero = float(np.sum(per_block_wall[is_nonzero])) / 1e6
        total_wall = wall_zero + wall_nonzero

        pct_blocks = float(np.sum(is_nonzero)) / len(wait_us) * 100
        pct_wall = wall_nonzero / total_wall * 100 if total_wall > 0 else 0

        bar_labels.append(config_labels[label])
        zero_wait_s.append(wall_zero)
        nonzero_wait_s.append(wall_nonzero)
        annotations.append((pct_blocks, pct_wall))

    x = np.arange(len(bar_labels))
    width = 0.5

    bars_zero = ax.bar(x, zero_wait_s, width, label="Zero-wait blocks",
                       color="#6baed6", edgecolor="none")
    bars_nonzero = ax.bar(x, nonzero_wait_s, width, bottom=zero_wait_s,
                          label="Nonzero-wait blocks", color="#d94801",
                          edgecolor="none")

    # Annotate nonzero-wait segment with block% and wall%
    y_max = max(z + nz for z, nz in zip(zero_wait_s, nonzero_wait_s))
    for i, (pct_b, pct_w) in enumerate(annotations):
        top = zero_wait_s[i] + nonzero_wait_s[i]
        if nonzero_wait_s[i] <= 0:
            continue
        text = f"{pct_b:.1f}% blocks\n{pct_w:.0f}% wall time"
        # If nonzero segment is tall enough, place text inside it
        if nonzero_wait_s[i] > y_max * 0.20:
            mid = zero_wait_s[i] + nonzero_wait_s[i] / 2
            ax.text(x[i], mid, text, ha="center", va="center",
                    fontsize=6.5, color="white", fontweight="bold")
        else:
            # Place above the bar with an arrow into the segment
            mid = zero_wait_s[i] + nonzero_wait_s[i] / 2
            ax.annotate(text,
                        xy=(x[i], mid),
                        xytext=(x[i], top + y_max * 0.12),
                        ha="center", va="bottom",
                        fontsize=6.5, color="#d94801", fontweight="bold",
                        arrowprops=dict(arrowstyle="-|>", color="#d94801",
                                        lw=0.8, shrinkA=0, shrinkB=2))

    ax.set_xticks(x)
    ax.set_xticklabels(bar_labels)
    ax.set_ylabel("Aggregate wall time (s)")
    ax.set_ylim(0, y_max * 1.25)

    # Format y-axis with comma separator
    ax.yaxis.set_major_formatter(
        ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    ax.legend(loc="upper right", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_thread_scaling_figure(baseline_us, thread_times_us, output_path):
    """Generate line plot of wall-time speedup vs prefetch thread count.

    Shows speedup relative to baseline for each thread count, with
    annotations for absolute wall time at key points.
    """
    sorted_threads = sorted(thread_times_us.keys())
    times = [thread_times_us[t] for t in sorted_threads]
    speedups = [baseline_us / t for t in times]

    fig, ax = plt.subplots(figsize=(5, 3))

    # Plot line with markers
    ax.plot(sorted_threads, speedups, color="#2171b5", linewidth=1.5,
            marker="o", markersize=5, markerfacecolor="#2171b5",
            markeredgecolor="white", markeredgewidth=0.8, zorder=3)

    # Baseline reference line at 1.0x
    ax.axhline(1.0, color="#bdbdbd", linewidth=0.8, linestyle="--", alpha=0.7,
               zorder=1, label="Baseline")

    # Annotate select points with wall time (first, inflection region, last)
    # Pick a subset to avoid clutter: 1, 8, 16, 32, 64 (or whatever exists)
    annotate_threads = set()
    annotate_threads.add(sorted_threads[0])   # first
    annotate_threads.add(sorted_threads[-1])   # last
    # Add midpoint and any key values
    for t in [4, 8, 16, 32, 64]:
        if t in thread_times_us:
            annotate_threads.add(t)

    for i, t in enumerate(sorted_threads):
        if t in annotate_threads:
            wall_s = times[i] / 1e6
            if wall_s >= 1000:
                time_label = f"{wall_s / 1e3:.1f}K s"
            else:
                time_label = f"{wall_s:,.0f} s"
            ax.annotate(time_label,
                        xy=(t, speedups[i]),
                        xytext=(0, 8), textcoords="offset points",
                        ha="center", fontsize=6.5, color="#555555")

    ax.set_xlabel("Prefetch threads")
    ax.set_ylabel("Wall-time speedup ($\\times$)")
    ax.set_xlim(0, sorted_threads[-1] + 2)
    ax.set_ylim(0, max(speedups) * 1.18)

    # Use actual thread counts as tick positions
    ax.set_xticks(sorted_threads)
    ax.tick_params(axis='x', labelsize=7)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _generate_hint_size_vs_block_figure(block_numbers, compressed_bytes, raw_bytes,
                                        output_path):
    """Generate stacked area chart of hint sizes over block number.

    Bottom layer: compressed size (what is actually transmitted).
    Top layer: compression savings (raw - compressed), so the full
    height equals the raw size.  Uses a rolling mean to smooth over
    block-to-block noise while preserving macro trends.
    """
    compressed_kb = compressed_bytes / 1024
    raw_kb = raw_bytes / 1024
    savings_kb = raw_kb - compressed_kb

    # Sort by block number (should already be sorted, but be safe)
    order = np.argsort(block_numbers)
    blocks = block_numbers[order]
    compressed_kb = compressed_kb[order]
    savings_kb = savings_kb[order]

    # Rolling mean over 500-block windows to smooth noise
    window = 500

    def _rolling_mean(arr):
        cumsum = np.cumsum(arr)
        cumsum = np.insert(cumsum, 0, 0)
        return (cumsum[window:] - cumsum[:-window]) / window

    blocks_smooth = _rolling_mean(blocks)
    compressed_smooth = _rolling_mean(compressed_kb)
    savings_smooth = _rolling_mean(savings_kb)

    fig, ax = plt.subplots(figsize=(6, 3))

    ax.fill_between(blocks_smooth, 0, compressed_smooth,
                    color="#6baed6", alpha=0.8, label="Compressed (transmitted)")
    ax.fill_between(blocks_smooth, compressed_smooth,
                    compressed_smooth + savings_smooth,
                    color="#fdae6b", alpha=0.5, label="Compression savings")

    ax.set_xlabel("Block number", fontsize=9)
    ax.set_ylabel("Hint size (KB)", fontsize=9)
    ax.set_xlim(blocks_smooth[0], blocks_smooth[-1])
    ax.set_ylim(0, None)

    # Format x-axis with millions
    ax.xaxis.set_major_formatter(
        ticker.FuncFormatter(lambda x, _: f"{x / 1e6:.2f}M"))

    ax.legend(loc="upper left", fontsize=7, frameon=False)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


