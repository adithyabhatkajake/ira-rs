#!/usr/bin/env python3
"""Plot execution times for baseline, primary, and IRA-L."""

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath) as f:
        return list(csv.DictReader(f))

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

    # Build data arrays
    baseline = {int(r['block_number']): int(r['execution_time_us']) for r in baseline_data}

    primary = {}
    for r in primary_data:
        primary[int(r['block_number'])] = int(r['execution_time_us'])

    backup = {}
    for r in backup_data:
        bn = int(r['block_number'])
        backup[bn] = int(r['hint_read_time_us']) + int(r['prefetch_time_us']) + int(r['execution_time_us'])

    # Get common block numbers and sort
    block_numbers = sorted(set(baseline.keys()) & set(primary.keys()) & set(backup.keys()))

    baseline_times = [baseline[bn] / 1000 for bn in block_numbers]  # Convert to ms
    primary_times = [primary[bn] / 1000 for bn in block_numbers]
    ira_l_times = [backup[bn] / 1000 for bn in block_numbers]

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 6))

    # Plot all three as lines
    ax.plot(block_numbers, baseline_times, linewidth=0.5, alpha=0.7, c='red', label='Baseline')
    ax.plot(block_numbers, primary_times, linewidth=0.5, alpha=0.7, c='blue', label='Primary')
    ax.plot(block_numbers, ira_l_times, linewidth=0.5, alpha=0.7, c='green', label='IRA-L')

    # Labels and title
    ax.set_xlabel('Block Number', fontsize=12)
    ax.set_ylabel('Time (ms)', fontsize=12)
    ax.set_title('Execution Times: Baseline vs Primary vs IRA-L', fontsize=14)

    # Format x-axis to show block numbers in millions
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1e6:.1f}M'))

    # Set y-axis limits
    ax.set_ylim(0, 800)

    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    # Save figure
    output_path = figures_dir / "execution-times.pdf"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    main()
