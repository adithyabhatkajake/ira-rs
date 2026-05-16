"""
Process IO trace CSV to generate execution time breakdown statistics and figures.

Generates:
- Macros for IO vs compute time statistics
- Stacked area chart showing IO/compute time breakdown with tx count overlay

Data source: data/2026.01.27.io-trace.csv
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def process_io_trace(macros):
    """Process IO trace data and generate macros and figures.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    csv_path = DATA_DIR / "2026.01.27.io-trace.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping")
        return

    macros.section("IO vs Compute Time Breakdown")

    # Read data
    blocks = []
    io_times = []
    compute_times = []
    tx_counts = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            blocks.append(int(row["block_number"]))
            io_times.append(int(row["io_time_us"]))
            compute_times.append(int(row["compute_time_us"]))
            tx_counts.append(int(row["tx_count"]))

    # Convert to numpy arrays
    blocks = np.array(blocks)
    io_times = np.array(io_times)
    compute_times = np.array(compute_times)
    tx_counts = np.array(tx_counts)
    total_times = io_times + compute_times

    # Compute aggregate statistics
    total_io = io_times.sum()
    total_compute = compute_times.sum()
    total_time = total_io + total_compute
    total_tx = tx_counts.sum()

    io_pct = (total_io / total_time) * 100
    compute_pct = (total_compute / total_time) * 100
    io_compute_ratio = total_io / total_compute

    avg_tx_per_block = total_tx / len(blocks)
    avg_time_per_block_ms = (total_time / len(blocks)) / 1000  # Convert to ms

    # Per-block IO percentages for distribution analysis
    # Filter out blocks with zero total time to avoid division by zero
    valid_mask = total_times > 0
    per_block_io_pct = np.zeros_like(total_times, dtype=float)
    per_block_io_pct[valid_mask] = (io_times[valid_mask] / total_times[valid_mask]) * 100
    valid_io_pct = per_block_io_pct[valid_mask]
    median_io_pct = np.median(valid_io_pct)
    p5_io_pct = np.percentile(valid_io_pct, 5)
    p95_io_pct = np.percentile(valid_io_pct, 95)

    # Add macros
    macros.add("IoTraceBlockCount", format_int(len(blocks)), "Blocks in IO trace")
    macros.add("IoTraceBlockStart", format_int(blocks[0]), "First block in trace")
    macros.add("IoTraceBlockEnd", format_int(blocks[-1]), "Last block in trace")

    macros.add("IoTimePct", format_percent(io_pct, 1), "IO share of execution time")
    macros.add("ComputeTimePct", format_percent(compute_pct, 1), "Compute share of execution time")
    macros.add("IoComputeRatio", format_float(io_compute_ratio, 1), "IO:Compute ratio")

    macros.add("MedianIoTimePct", format_percent(median_io_pct, 1), "Median per-block IO share")
    macros.add("IoTimePctPFive", format_percent(p5_io_pct, 1), "5th percentile IO share")
    macros.add("IoTimePctPNinetyFive", format_percent(p95_io_pct, 1), "95th percentile IO share")

    macros.add("AvgTxPerBlock", format_int(int(avg_tx_per_block)), "Avg transactions per block")
    macros.add("AvgBlockTimeMs", format_float(avg_time_per_block_ms, 1), "Avg block execution time (ms)")

    # Generate figure
    _generate_io_breakdown_figure(
        blocks, io_times, compute_times, tx_counts,
        PROJECT_ROOT / "figures" / "io-breakdown.pdf"
    )


def _generate_io_breakdown_figure(blocks, io_times, compute_times, tx_counts, output_path):
    """Generate stacked area chart with IO/compute breakdown and tx count overlay."""

    # Use rolling average to smooth the data (window of 20 blocks)
    window = 20

    def rolling_mean(arr, w):
        # Pad to handle edges
        cumsum = np.cumsum(np.insert(arr, 0, 0))
        return (cumsum[w:] - cumsum[:-w]) / w

    # Smooth the data
    io_smooth = rolling_mean(io_times, window)
    compute_smooth = rolling_mean(compute_times, window)
    tx_smooth = rolling_mean(tx_counts, window)
    blocks_smooth = blocks[window - 1 :]

    # Convert to milliseconds for readability
    io_ms = io_smooth / 1000
    compute_ms = compute_smooth / 1000

    # Create figure with two y-axes
    fig, ax1 = plt.subplots(figsize=(6, 3))

    # Stacked area chart for IO and compute time
    ax1.fill_between(
        blocks_smooth,
        0,
        io_ms,
        alpha=0.7,
        label="I/O time",
        color="#2171b5",
    )
    ax1.fill_between(
        blocks_smooth,
        io_ms,
        io_ms + compute_ms,
        alpha=0.9,
        label="Compute time",
        color="#fec44f",  # Yellow for visibility
    )

    ax1.set_xlabel("Block number")
    ax1.set_ylabel("Execution time (ms)")
    ax1.set_xlim(blocks_smooth[0], blocks_smooth[-1])
    ax1.set_ylim(0, None)

    # Format x-axis to show block numbers nicely
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{x/1e6:.1f}M"))

    # Secondary y-axis for transaction count
    ax2 = ax1.twinx()
    ax2.plot(
        blocks_smooth,
        tx_smooth,
        color="#d94801",
        linewidth=1.0,
        label="Transactions",
        alpha=0.8,
    )
    ax2.set_ylabel("Transactions per block", color="#d94801")
    ax2.tick_params(axis="y", labelcolor="#d94801")
    ax2.set_ylim(100, None)  # Start at 100 to avoid legend overlap

    # Combined legend - single row outside figure on top
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.15),
        ncol=3,
        fontsize=8,
        frameon=False,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.95])  # Leave room for legend on top

    # Save figure
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")
