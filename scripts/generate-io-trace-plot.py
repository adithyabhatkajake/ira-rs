#!/usr/bin/env python3
"""Generate stacked bar plot of I/O time vs compute time from io-trace data."""

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

def read_csv(filepath):
    """Read CSV file and return list of dicts."""
    with open(filepath) as f:
        return list(csv.DictReader(f))

def main():
    script_dir = Path(__file__).parent
    figures_dir = script_dir.parent / "figures"
    data_dir = Path("/Volumes/X/ira-data")

    # Find io-trace CSV
    io_trace_files = sorted(data_dir.glob("*.io-trace.csv"))
    if not io_trace_files:
        print("No io-trace CSV files found in", data_dir)
        return

    io_trace_file = io_trace_files[-1]
    print(f"Reading {io_trace_file}")

    # Read data
    data = read_csv(io_trace_file)

    # Extract arrays (filter out empty blocks)
    block_numbers = []
    io_times = []
    compute_times = []
    tx_counts = []

    for r in data:
        tx_count = int(r['tx_count'])
        if tx_count > 0:  # Skip empty blocks
            block_numbers.append(int(r['block_number']))
            io_times.append(int(r['io_time_us']) / 1000)  # Convert to ms
            compute_times.append(int(r['compute_time_us']) / 1000)
            tx_counts.append(tx_count)

    print(f"Loaded {len(block_numbers):,} non-empty blocks")

    # Bin data for stacked bar chart (100k blocks is too many bars)
    bin_size = 500  # blocks per bin
    n_bins = len(block_numbers) // bin_size

    bin_centers = []
    bin_io = []
    bin_compute = []
    bin_tx = []

    for i in range(n_bins):
        start = i * bin_size
        end = start + bin_size
        bin_centers.append(np.mean(block_numbers[start:end]))
        bin_io.append(np.mean(io_times[start:end]))
        bin_compute.append(np.mean(compute_times[start:end]))
        bin_tx.append(np.mean(tx_counts[start:end]))

    print(f"Created {n_bins} bins of {bin_size} blocks each")

    # Create figure with two y-axes
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax2 = ax1.twinx()

    # Bar width
    width = (bin_centers[1] - bin_centers[0]) * 0.8

    # Stacked bar chart: compute on bottom, I/O on top
    bars1 = ax1.bar(bin_centers, bin_compute, width, label='Compute Time', color='#2980b9', alpha=0.9)
    bars2 = ax1.bar(bin_centers, bin_io, width, bottom=bin_compute, label='I/O Time', color='#c0392b', alpha=0.9)

    # Transaction count as line on secondary axis (gray/black for neutral contrast)
    ax2.plot(bin_centers, bin_tx, linewidth=1.5, c='#2c3e50', label='Transactions', marker='', linestyle='-')

    # Labels (no title)
    ax1.set_xlabel('Block Number', fontsize=11)
    ax1.set_ylabel('Time (ms)', fontsize=11)
    ax2.set_ylabel('Transaction Count', fontsize=11, color='#2c3e50')

    # Format x-axis to show block numbers in millions
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1e6:.2f}M'))

    # Set y-axis colors
    ax1.tick_params(axis='y', labelcolor='black')
    ax2.tick_params(axis='y', labelcolor='#2c3e50')

    # Grid
    ax1.grid(True, alpha=0.3, axis='y')

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=9)

    # Save figure
    figures_dir.mkdir(exist_ok=True)
    output_path = figures_dir / "io-trace-breakdown.pdf"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    main()
