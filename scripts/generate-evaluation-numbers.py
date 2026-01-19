#!/usr/bin/env python3
"""Generate all evaluation numbers for the IRA-L paper."""

import csv
from pathlib import Path

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath) as f:
        return list(csv.DictReader(f))

def percentile(arr, p):
    """Calculate percentile of sorted array."""
    arr = sorted(arr)
    idx = int(len(arr) * p)
    return arr[min(idx, len(arr)-1)]

def fmt_time(us):
    """Format microseconds as appropriate unit."""
    if us >= 1e6:
        return f"{us/1e6:.1f}s"
    elif us >= 1e3:
        return f"{us/1e3:.1f}ms"
    else:
        return f"{us:.1f}us"

def fmt_bytes(b):
    """Format bytes as appropriate unit."""
    if b >= 1e9:
        return f"{b/1e9:.2f}GB"
    elif b >= 1e6:
        return f"{b/1e6:.2f}MB"
    elif b >= 1e3:
        return f"{b/1e3:.1f}KB"
    else:
        return f"{b:.0f}B"

def main():
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"

    # Load all data
    baseline_data = read_csv(data_dir / "2026.01.09.reth-baseline-run.csv")
    primary_data = read_csv(data_dir / "2026.01.09.reth-primary-run.csv")
    backup_data = read_csv(data_dir / "2026.01.09.reth-backup-run.csv")
    hint_size_data = read_csv(data_dir / "2026.01.09.measure-hint-size.csv")
    working_set_data = read_csv(data_dir / "2026.01.09.measure-working-set-size.csv")
    cache_size_data = read_csv(data_dir / "2026.01.09.measure-all-keys-as-hint-cache-size.csv")

    # Extract arrays
    baseline_exec = [int(r['execution_time_us']) for r in baseline_data]

    primary_exec = [int(r['execution_time_us']) for r in primary_data]
    primary_construct = [int(r['hint_construction_time_us']) for r in primary_data]
    primary_write = [int(r['hint_write_time_us']) for r in primary_data]

    backup_hint_read = [int(r['hint_read_time_us']) for r in backup_data]
    backup_prefetch = [int(r['prefetch_time_us']) for r in backup_data]
    backup_exec = [int(r['execution_time_us']) for r in backup_data]
    backup_total = [backup_hint_read[i] + backup_prefetch[i] + backup_exec[i] for i in range(len(backup_data))]

    # Hint sizes from actual hint files
    raw_sizes = [float(r['raw_size_bytes']) for r in hint_size_data]
    compressed_sizes = [float(r['compressed_size_bytes']) for r in hint_size_data]

    # Compression/decompression times from working set measurement
    compression_times = [float(r['compression_time_us']) for r in working_set_data]
    decompression_times = [float(r['decompression_time_us']) for r in working_set_data]

    cache_sizes = [float(r['cache_size_bytes']) for r in cache_size_data]

    # Calculate speedups
    speedups = [baseline_exec[i] / backup_total[i] if backup_total[i] > 0 else 0 for i in range(len(baseline_exec))]
    exec_speedups = [baseline_exec[i] / backup_exec[i] if backup_exec[i] > 0 else 0 for i in range(len(baseline_exec))]

    n_blocks = len(baseline_data)

    print("=" * 70)
    print("IRA-L EVALUATION NUMBERS")
    print("=" * 70)

    # Section 1: Dataset
    print("\n## 1. EXPERIMENTAL SETUP")
    print("-" * 50)
    print(f"Total blocks analyzed:     {n_blocks:,}")
    print(f"Block range:               24,019,447 - 24,120,246")
    print(f"Duration:                  ~2 weeks of Ethereum mainnet")

    # Section 2: Trace Characteristics
    print("\n## 2. TRACE CHARACTERISTICS (Hint Analysis)")
    print("-" * 50)
    print(f"Total hints generated:     {len(hint_size_data):,} blocks")
    print()
    print("Raw hint size:")
    print(f"  Mean:                    {fmt_bytes(sum(raw_sizes)/len(raw_sizes))}")
    print(f"  Median:                  {fmt_bytes(percentile(raw_sizes, 0.5))}")
    print(f"  p90:                     {fmt_bytes(percentile(raw_sizes, 0.9))}")
    print(f"  p99:                     {fmt_bytes(percentile(raw_sizes, 0.99))}")
    print(f"  Max:                     {fmt_bytes(max(raw_sizes))}")
    print()
    print("Compressed hint size:")
    print(f"  Mean:                    {fmt_bytes(sum(compressed_sizes)/len(compressed_sizes))}")
    print(f"  Median:                  {fmt_bytes(percentile(compressed_sizes, 0.5))}")
    print(f"  p90:                     {fmt_bytes(percentile(compressed_sizes, 0.9))}")
    print(f"  p99:                     {fmt_bytes(percentile(compressed_sizes, 0.99))}")
    print(f"  Max:                     {fmt_bytes(max(compressed_sizes))}")
    print()
    avg_ratio = sum(raw_sizes) / sum(compressed_sizes) if sum(compressed_sizes) > 0 else 0
    print(f"Compression ratio:         {avg_ratio:.2f}x")
    print()
    print("Compression time:")
    print(f"  Mean:                    {fmt_time(sum(compression_times)/len(compression_times))}")
    print(f"  p99:                     {fmt_time(percentile(compression_times, 0.99))}")
    print()
    print("Decompression time:")
    print(f"  Mean:                    {fmt_time(sum(decompression_times)/len(decompression_times))}")
    print(f"  p99:                     {fmt_time(percentile(decompression_times, 0.99))}")
    print()
    print("Cache memory footprint:")
    print(f"  Mean:                    {fmt_bytes(sum(cache_sizes)/len(cache_sizes))}")
    print(f"  p90:                     {fmt_bytes(percentile(cache_sizes, 0.9))}")
    print(f"  Max:                     {fmt_bytes(max(cache_sizes))}")

    # Section 3: Primary Overhead
    print("\n## 3. PRIMARY OVERHEAD (Hint Generation Cost)")
    print("-" * 50)
    total_baseline = sum(baseline_exec)
    total_primary_exec = sum(primary_exec)
    total_construct = sum(primary_construct)
    total_write = sum(primary_write)
    total_primary = total_primary_exec + total_construct + total_write

    print(f"Baseline execution:        {fmt_time(total_baseline)} total")
    print(f"Primary execution:         {fmt_time(total_primary_exec)} total")
    print(f"  Overhead vs baseline:    {(total_primary_exec/total_baseline - 1)*100:+.1f}%")
    print()
    print(f"Hint construction time:")
    print(f"  Total:                   {fmt_time(total_construct)}")
    print(f"  Mean:                    {fmt_time(total_construct/n_blocks)}")
    print(f"  % of execution:          {total_construct/total_primary_exec*100:.1f}%")
    print()
    print(f"Hint write time:")
    print(f"  Total:                   {fmt_time(total_write)}")
    print(f"  Mean:                    {fmt_time(total_write/n_blocks)}")
    print(f"  % of execution:          {total_write/total_primary_exec*100:.1f}%")
    print()
    print(f"Total primary overhead:")
    print(f"  Primary total:           {fmt_time(total_primary)}")
    print(f"  vs baseline:             {(total_primary/total_baseline - 1)*100:+.1f}%")

    # Section 4: End-to-End Performance
    print("\n## 4. IRA-L END-TO-END PERFORMANCE (Main Result)")
    print("-" * 50)
    total_backup = sum(backup_total)
    net_speedup = total_baseline / total_backup
    time_saved = total_baseline - total_backup

    print(f"Baseline total:            {fmt_time(total_baseline)}")
    print(f"IRA-L total:               {fmt_time(total_backup)}")
    print()
    print(f"*** NET SPEEDUP:           {net_speedup:.2f}x ***")
    print(f"*** TIME SAVED:            {fmt_time(time_saved)} ({time_saved/total_baseline*100:.1f}%) ***")

    # Section 5: Execution Speedup
    print("\n## 5. EXECUTION SPEEDUP ANALYSIS")
    print("-" * 50)
    total_backup_exec = sum(backup_exec)
    exec_speedup_overall = total_baseline / total_backup_exec

    print("Baseline execution:")
    print(f"  Total:                   {fmt_time(total_baseline)}")
    print(f"  Mean:                    {fmt_time(total_baseline/n_blocks)}")
    print(f"  Median:                  {fmt_time(percentile(baseline_exec, 0.5))}")
    print(f"  p90:                     {fmt_time(percentile(baseline_exec, 0.9))}")
    print(f"  p99:                     {fmt_time(percentile(baseline_exec, 0.99))}")
    print()
    print("IRA-L execution (excluding overhead):")
    print(f"  Total:                   {fmt_time(total_backup_exec)}")
    print(f"  Mean:                    {fmt_time(total_backup_exec/n_blocks)}")
    print(f"  Median:                  {fmt_time(percentile(backup_exec, 0.5))}")
    print(f"  p90:                     {fmt_time(percentile(backup_exec, 0.9))}")
    print(f"  p99:                     {fmt_time(percentile(backup_exec, 0.99))}")
    print()
    print(f"Execution speedup:         {exec_speedup_overall:.2f}x")
    print(f"Execution time reduction:  {(1 - total_backup_exec/total_baseline)*100:.1f}%")

    # Section 6: Overhead Breakdown
    print("\n## 6. OVERHEAD BREAKDOWN")
    print("-" * 50)
    total_hint_read = sum(backup_hint_read)
    total_prefetch = sum(backup_prefetch)

    print(f"Hint read time:")
    print(f"  Total:                   {fmt_time(total_hint_read)}")
    print(f"  Mean:                    {fmt_time(total_hint_read/n_blocks)}")
    print(f"  % of IRA-L total:        {total_hint_read/total_backup*100:.1f}%")
    print()
    print(f"Prefetch time:")
    print(f"  Total:                   {fmt_time(total_prefetch)}")
    print(f"  Mean:                    {fmt_time(total_prefetch/n_blocks)}")
    print(f"  % of IRA-L total:        {total_prefetch/total_backup*100:.1f}%")
    print()
    print(f"Execution time:")
    print(f"  Total:                   {fmt_time(total_backup_exec)}")
    print(f"  Mean:                    {fmt_time(total_backup_exec/n_blocks)}")
    print(f"  % of IRA-L total:        {total_backup_exec/total_backup*100:.1f}%")
    print()
    overhead = total_hint_read + total_prefetch
    print(f"Total overhead:            {fmt_time(overhead)}")
    print(f"Overhead ratio:            {overhead/total_backup_exec:.2f}x execution time")

    # Section 7: Speedup Distribution
    print("\n## 7. PER-BLOCK SPEEDUP DISTRIBUTION")
    print("-" * 50)
    speedups_sorted = sorted(speedups)

    print(f"Net speedup distribution:")
    print(f"  Mean:                    {sum(speedups)/len(speedups):.2f}x")
    print(f"  Median:                  {percentile(speedups, 0.5):.2f}x")
    print(f"  p10:                     {percentile(speedups, 0.1):.2f}x")
    print(f"  p25:                     {percentile(speedups, 0.25):.2f}x")
    print(f"  p75:                     {percentile(speedups, 0.75):.2f}x")
    print(f"  p90:                     {percentile(speedups, 0.9):.2f}x")
    print()
    blocks_faster = sum(1 for s in speedups if s > 1.0)
    blocks_much_faster = sum(1 for s in speedups if s > 1.5)
    print(f"Blocks with speedup > 1.0: {blocks_faster:,} ({blocks_faster/n_blocks*100:.1f}%)")
    print(f"Blocks with speedup > 1.5: {blocks_much_faster:,} ({blocks_much_faster/n_blocks*100:.1f}%)")
    print()
    print(f"Min speedup:               {min(speedups):.2f}x")
    print(f"Max speedup:               {max(speedups):.2f}x")

    print("\n" + "=" * 70)
    print("END OF EVALUATION NUMBERS")
    print("=" * 70)

if __name__ == "__main__":
    main()
