#!/usr/bin/env python3
"""Analyze IRA-L benchmark results from CSV files."""

import csv
import sys
from pathlib import Path

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath) as f:
        return list(csv.DictReader(f))

def percentile(arr, p):
    """Calculate percentile of sorted array."""
    idx = int(len(arr) * p)
    return arr[min(idx, len(arr)-1)]

def main():
    # Find data directory
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"

    # Find latest CSV files
    primary_files = sorted(data_dir.glob("*.reth-primary-run*.csv"))
    baseline_files = sorted(data_dir.glob("*.reth-baseline-run*.csv"))
    backup_files = sorted(data_dir.glob("*.reth-backup-run*.csv"))

    if not primary_files or not baseline_files or not backup_files:
        print("Error: Missing CSV files in data directory")
        print(f"  Primary files: {len(primary_files)}")
        print(f"  Baseline files: {len(baseline_files)}")
        print(f"  Backup files: {len(backup_files)}")
        sys.exit(1)

    primary_file = primary_files[-1]
    baseline_file = baseline_files[-1]
    backup_file = backup_files[-1]

    print("=== IRA-L BENCHMARK ANALYSIS ===")
    print(f"\nFiles:")
    print(f"  Primary:  {primary_file.name}")
    print(f"  Baseline: {baseline_file.name}")
    print(f"  Backup:   {backup_file.name}")

    # Read data
    primary_data = read_csv(primary_file)
    baseline_data = read_csv(baseline_file)
    backup_data = read_csv(backup_file)

    print(f"\nBlocks analyzed: {len(baseline_data)}")

    # Build lookup dicts
    baseline = {int(r['block_number']): int(r['execution_time_us']) for r in baseline_data}

    backup = {}
    for r in backup_data:
        backup[int(r['block_number'])] = {
            'hint_read': int(r['hint_read_time_us']),
            'prefetch': int(r['prefetch_time_us']),
            'exec': int(r['execution_time_us'])
        }

    primary = {}
    for r in primary_data:
        primary[int(r['block_number'])] = {
            'exec': int(r['execution_time_us']),
            'hint_construct': int(r['hint_construction_time_us']),
            'hint_write': int(r['hint_write_time_us'])
        }

    # Calculate totals
    total_baseline = sum(baseline.values())
    total_backup_exec = sum(b['exec'] for b in backup.values())
    total_prefetch = sum(b['prefetch'] for b in backup.values())
    total_hint_read = sum(b['hint_read'] for b in backup.values())
    total_primary_exec = sum(p['exec'] for p in primary.values())
    total_hint_construct = sum(p['hint_construct'] for p in primary.values())
    total_hint_write = sum(p['hint_write'] for p in primary.values())

    n_blocks = len(baseline)

    print("\n" + "="*50)
    print("SUMMARY (totals)")
    print("="*50)

    print(f"\nPrimary (hint generation):")
    print(f"  Execution:         {total_primary_exec/1e6:>8.1f}s")
    print(f"  Hint construction: {total_hint_construct/1e6:>8.1f}s")
    print(f"  Hint write:        {total_hint_write/1e6:>8.1f}s")

    print(f"\nBaseline:")
    print(f"  Execution:         {total_baseline/1e6:>8.1f}s")

    print(f"\nBackup (with prefetching):")
    print(f"  Hint read:         {total_hint_read/1e6:>8.1f}s")
    print(f"  Prefetch:          {total_prefetch/1e6:>8.1f}s")
    print(f"  Execution:         {total_backup_exec/1e6:>8.1f}s")
    print(f"  Total:             {(total_hint_read+total_prefetch+total_backup_exec)/1e6:>8.1f}s")

    print("\n" + "="*50)
    print("AVERAGES (per block)")
    print("="*50)

    print(f"\nBaseline:       {total_baseline/n_blocks/1000:>6.1f} ms/block")
    print(f"Primary exec:   {total_primary_exec/n_blocks/1000:>6.1f} ms/block")
    print(f"Backup exec:    {total_backup_exec/n_blocks/1000:>6.1f} ms/block")
    print(f"Backup prefetch:{total_prefetch/n_blocks/1000:>6.1f} ms/block")

    print("\n" + "="*50)
    print("PERCENTILES")
    print("="*50)

    baseline_times = sorted(baseline.values())
    backup_exec_times = sorted([b['exec'] for b in backup.values()])
    backup_prefetch_times = sorted([b['prefetch'] for b in backup.values()])

    print(f"\nBaseline execution (ms):")
    print(f"  p50: {percentile(baseline_times, 0.5)/1000:>8.1f}")
    print(f"  p90: {percentile(baseline_times, 0.9)/1000:>8.1f}")
    print(f"  p99: {percentile(baseline_times, 0.99)/1000:>8.1f}")
    print(f"  max: {max(baseline_times)/1000:>8.1f}")

    print(f"\nBackup execution (ms):")
    print(f"  p50: {percentile(backup_exec_times, 0.5)/1000:>8.1f}")
    print(f"  p90: {percentile(backup_exec_times, 0.9)/1000:>8.1f}")
    print(f"  p99: {percentile(backup_exec_times, 0.99)/1000:>8.1f}")
    print(f"  max: {max(backup_exec_times)/1000:>8.1f}")

    print(f"\nBackup prefetch (ms):")
    print(f"  p50: {percentile(backup_prefetch_times, 0.5)/1000:>8.1f}")
    print(f"  p90: {percentile(backup_prefetch_times, 0.9)/1000:>8.1f}")
    print(f"  p99: {percentile(backup_prefetch_times, 0.99)/1000:>8.1f}")
    print(f"  max: {max(backup_prefetch_times)/1000:>8.1f}")

    print("\n" + "="*50)
    print("SPEEDUP ANALYSIS")
    print("="*50)

    # Per-block speedup
    speedups = []
    for bn in baseline:
        if bn in backup and backup[bn]['exec'] > 0:
            speedups.append(baseline[bn] / backup[bn]['exec'])

    speedups.sort()
    print(f"\nExecution speedup (baseline / backup_exec):")
    print(f"  Average: {sum(speedups)/len(speedups):.2f}x")
    print(f"  Median:  {speedups[len(speedups)//2]:.2f}x")
    print(f"  p10:     {percentile(speedups, 0.1):.2f}x")
    print(f"  p90:     {percentile(speedups, 0.9):.2f}x")

    print("\n" + "="*50)
    print("TIME BUDGET")
    print("="*50)

    exec_saved = total_baseline - total_backup_exec
    overhead = total_prefetch + total_hint_read
    net = exec_saved - overhead

    print(f"\nExecution time saved:  {exec_saved/1e6:>8.1f}s ({exec_saved/total_baseline*100:.1f}%)")
    print(f"Prefetch overhead:     {total_prefetch/1e6:>8.1f}s")
    print(f"Hint read overhead:    {total_hint_read/1e6:>8.1f}s")
    print(f"Total overhead:        {overhead/1e6:>8.1f}s")
    print(f"Net savings:           {net/1e6:>8.1f}s ({net/total_baseline*100:+.1f}%)")

    print("\n" + "="*50)
    print("CONCLUSIONS")
    print("="*50)

    exec_speedup = total_baseline / total_backup_exec
    print(f"\n1. Backup execution is {exec_speedup:.2f}x faster than baseline")
    print(f"   ({(1-1/exec_speedup)*100:.0f}% reduction in execution time)")

    print(f"\n2. However, prefetch overhead ({total_prefetch/1e6:.0f}s) exceeds")
    print(f"   execution savings ({exec_saved/1e6:.0f}s)")

    if net > 0:
        print(f"\n3. NET GAIN: {net/1e6:.1f}s saved overall")
    else:
        print(f"\n3. NET LOSS: {-net/1e6:.1f}s slower overall")
        print(f"   Need to pipeline prefetch with execution to see gains")

    # Calculate net IRA-L speedup (including all overhead)
    print("\n" + "="*50)
    print("NET IRA-L SPEEDUP")
    print("="*50)

    total_ira_l = total_hint_read + total_prefetch + total_backup_exec
    net_speedup = total_baseline / total_ira_l
    print(f"\nBaseline total:     {total_baseline/1e6:>8.1f}s")
    print(f"IRA-L total:        {total_ira_l/1e6:>8.1f}s")
    print(f"Net IRA-L speedup:  {net_speedup:.2f}x")
    print(f"Time reduction:     {(1-1/net_speedup)*100:.1f}%")

    # Per-block net speedup
    net_speedups = []
    for bn in baseline:
        if bn in backup:
            b = backup[bn]
            ira_l_time = b['hint_read'] + b['prefetch'] + b['exec']
            if ira_l_time > 0:
                net_speedups.append(baseline[bn] / ira_l_time)

    net_speedups.sort()
    print(f"\nPer-block net speedup distribution:")
    print(f"  Average: {sum(net_speedups)/len(net_speedups):.2f}x")
    print(f"  Median:  {net_speedups[len(net_speedups)//2]:.2f}x")
    print(f"  p10:     {percentile(net_speedups, 0.1):.2f}x")
    print(f"  p90:     {percentile(net_speedups, 0.9):.2f}x")

    # Write per-block analysis CSV
    output_csv = data_dir / "2026.01.09.ira-l-analysis.csv"
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'block_number',
            'baseline_time_us',
            'ira_l_time_us',
            'hint_read_us',
            'prefetch_us',
            'exec_us',
            'net_speedup'
        ])

        for bn in sorted(baseline.keys()):
            if bn in backup:
                b = backup[bn]
                ira_l_time = b['hint_read'] + b['prefetch'] + b['exec']
                speedup = baseline[bn] / ira_l_time if ira_l_time > 0 else 0
                writer.writerow([
                    bn,
                    baseline[bn],
                    ira_l_time,
                    b['hint_read'],
                    b['prefetch'],
                    b['exec'],
                    f"{speedup:.4f}"
                ])

    print(f"\nPer-block analysis written to: {output_csv.name}")

if __name__ == "__main__":
    main()
