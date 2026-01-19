#!/usr/bin/env python3
"""Plot IRA-L speedup from analysis CSV."""

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

def main():
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    figures_dir = script_dir.parent / "figures"

    # Read analysis CSV
    csv_path = data_dir / "2026.01.09.ira-l-analysis.csv"

    block_numbers = []
    speedups = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            block_numbers.append(int(row['block_number']))
            speedups.append(float(row['net_speedup']))

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 6))

    # Plot speedup
    ax.scatter(block_numbers, speedups, s=1, alpha=0.3, c='blue', label='Per-block speedup')

    # Add horizontal line at 1.0 (no speedup)
    ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1, label='No speedup (1.0x)')

    # Calculate and plot rolling average
    window = 1000
    rolling_avg = []
    for i in range(len(speedups)):
        start = max(0, i - window // 2)
        end = min(len(speedups), i + window // 2)
        rolling_avg.append(sum(speedups[start:end]) / (end - start))

    ax.plot(block_numbers, rolling_avg, color='green', linewidth=1.5,
            label=f'Rolling average ({window} blocks)')

    # Calculate overall average
    avg_speedup = sum(speedups) / len(speedups)
    ax.axhline(y=avg_speedup, color='orange', linestyle=':', linewidth=1.5,
               label=f'Overall average ({avg_speedup:.2f}x)')

    # Labels
    ax.set_xlabel('Block Number', fontsize=12)
    ax.set_ylabel('Net Speedup (baseline / IRA-L)', fontsize=12)

    # Format x-axis to show block numbers in millions
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1e6:.1f}M'))

    # Set y-axis limits
    ax.set_ylim(0, 3)

    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    # Save figure
    output_path = figures_dir / "ira-l-speedup.pdf"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    main()
