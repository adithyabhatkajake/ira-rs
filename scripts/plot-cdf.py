#!/usr/bin/env python3
"""Plot CDF of execution times for baseline, primary, and IRA-L."""

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

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

    # Extract times in ms
    baseline_times = sorted([int(r['execution_time_us']) / 1000 for r in baseline_data])
    primary_times = sorted([int(r['execution_time_us']) / 1000 for r in primary_data])
    ira_l_times = sorted([
        (int(r['hint_read_time_us']) + int(r['prefetch_time_us']) + int(r['execution_time_us'])) / 1000
        for r in backup_data
    ])

    # Calculate CDFs
    n = len(baseline_times)
    cdf_y = np.arange(1, n + 1) / n

    # Create figure
    fig, ax = plt.subplots(figsize=(8, 5))

    # Better color palette
    color_baseline = '#E63946'  # red
    color_primary = '#457B9D'   # blue
    color_ira_l = '#2A9D8F'     # teal

    # Plot CDFs
    ax.plot(baseline_times, cdf_y, linewidth=1.5, c=color_baseline, label='Baseline')
    ax.plot(primary_times, cdf_y, linewidth=1.5, c=color_primary, label='Primary')
    ax.plot(ira_l_times, cdf_y, linewidth=1.5, c=color_ira_l, label='IRA-L')

    # Labels
    ax.set_xlabel('Time (ms)', fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)

    # Set x-axis limit to focus on the bulk of the data (up to p99)
    p99 = max(baseline_times[int(n * 0.99)], primary_times[int(n * 0.99)], ira_l_times[int(n * 0.99)])
    ax.set_xlim(0, p99 * 1.1)
    ax.set_ylim(0, 1.02)

    # Add horizontal guide lines at key percentiles
    for p, label in [(0.5, 'p50'), (0.9, 'p90'), (0.99, 'p99')]:
        ax.axhline(y=p, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
        ax.text(p99 * 1.05, p, label, fontsize=9, color='gray', va='center')

    # Get median values
    baseline_median = baseline_times[n // 2]
    primary_median = primary_times[n // 2]
    ira_l_median = ira_l_times[n // 2]

    # Add vertical median lines
    ax.axvline(x=baseline_median, color=color_baseline, linestyle='--', linewidth=1, alpha=0.7)
    ax.axvline(x=primary_median, color=color_primary, linestyle='--', linewidth=1, alpha=0.7)
    ax.axvline(x=ira_l_median, color=color_ira_l, linestyle='--', linewidth=1, alpha=0.7)

    # Align all labels to the right (use the farthest median + offset)
    label_x = max(baseline_median, primary_median, ira_l_median) + 80

    # Annotate with arrows pointing to median lines, labels aligned on right
    ax.annotate(f'{baseline_median:.0f} ms', xy=(baseline_median, 0.25), xytext=(label_x, 0.25),
                fontsize=9, color=color_baseline, va='center',
                arrowprops=dict(arrowstyle='->', color=color_baseline, lw=1))
    ax.annotate(f'{primary_median:.0f} ms', xy=(primary_median, 0.15), xytext=(label_x, 0.15),
                fontsize=9, color=color_primary, va='center',
                arrowprops=dict(arrowstyle='->', color=color_primary, lw=1))
    ax.annotate(f'{ira_l_median:.0f} ms', xy=(ira_l_median, 0.35), xytext=(label_x, 0.35),
                fontsize=9, color=color_ira_l, va='center',
                arrowprops=dict(arrowstyle='->', color=color_ira_l, lw=1))

    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', fontsize=10)

    # Save figure
    output_path = figures_dir / "execution-times-cdf.pdf"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")

    # Print median values
    print(f"\nMedian times:")
    print(f"  Baseline: {baseline_median:.1f} ms")
    print(f"  Primary:  {primary_median:.1f} ms")
    print(f"  IRA-L:    {ira_l_median:.1f} ms")

if __name__ == "__main__":
    main()
