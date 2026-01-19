#!/usr/bin/env python3
"""Plot execution times with percentile bands over block range."""

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath) as f:
        return list(csv.DictReader(f))

def compute_percentile_bands(block_numbers, values, window=1000):
    """Compute rolling percentile bands."""
    n = len(values)
    medians = []
    p10s = []
    p90s = []

    for i in range(n):
        start = max(0, i - window // 2)
        end = min(n, i + window // 2)
        window_vals = sorted(values[start:end])
        w_len = len(window_vals)

        medians.append(window_vals[w_len // 2])
        p10s.append(window_vals[int(w_len * 0.1)])
        p90s.append(window_vals[int(w_len * 0.9)])

    return medians, p10s, p90s

def main():
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    figures_dir = script_dir.parent / "figures"

    # Find latest CSV files
    primary_files = sorted(data_dir.glob("*.reth-primary-run*.csv"))
    baseline_files = sorted(data_dir.glob("*.reth-baseline-run*.csv"))
    backup_files = sorted(data_dir.glob("*.reth-backup-run*.csv"))

    primary_file = primary_files[-1]
    baseline_file = baseline_files[-1]
    backup_file = backup_files[-1]

    # Read data
    primary_data = read_csv(primary_file)
    baseline_data = read_csv(baseline_file)
    backup_data = read_csv(backup_file)

    # Build data dicts
    baseline = {int(r['block_number']): int(r['execution_time_us']) / 1000 for r in baseline_data}
    primary = {int(r['block_number']): int(r['execution_time_us']) / 1000 for r in primary_data}
    backup = {}
    for r in backup_data:
        bn = int(r['block_number'])
        backup[bn] = (int(r['hint_read_time_us']) + int(r['prefetch_time_us']) + int(r['execution_time_us'])) / 1000

    # Get common block numbers and sort
    block_numbers = sorted(set(baseline.keys()) & set(primary.keys()) & set(backup.keys()))

    baseline_times = [baseline[bn] for bn in block_numbers]
    primary_times = [primary[bn] for bn in block_numbers]
    ira_l_times = [backup[bn] for bn in block_numbers]

    # Compute percentile bands
    window = 2000
    baseline_med, baseline_p10, baseline_p90 = compute_percentile_bands(block_numbers, baseline_times, window)
    primary_med, primary_p10, primary_p90 = compute_percentile_bands(block_numbers, primary_times, window)
    ira_l_med, ira_l_p10, ira_l_p90 = compute_percentile_bands(block_numbers, ira_l_times, window)

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot percentile bands (p10-p90 shaded, median line)
    ax.fill_between(block_numbers, baseline_p10, baseline_p90, alpha=0.2, color='red')
    ax.plot(block_numbers, baseline_med, linewidth=1.5, color='red', label='Baseline')

    ax.fill_between(block_numbers, primary_p10, primary_p90, alpha=0.2, color='blue')
    ax.plot(block_numbers, primary_med, linewidth=1.5, color='blue', label='Primary')

    ax.fill_between(block_numbers, ira_l_p10, ira_l_p90, alpha=0.2, color='green')
    ax.plot(block_numbers, ira_l_med, linewidth=1.5, color='green', label='IRA-L')

    # Labels
    ax.set_xlabel('Block Number', fontsize=12)
    ax.set_ylabel('Time (ms)', fontsize=12)

    # Format x-axis
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1e6:.2f}M'))

    # Set y-axis limits
    ax.set_ylim(0, 500)

    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=10)

    # Save figure
    output_path = figures_dir / "execution-times-bands.pdf"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    main()
