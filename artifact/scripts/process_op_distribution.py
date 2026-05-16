"""
Process per-block operation distribution CSV to generate stacked area chart.

Generates:
- Stacked area chart showing operation category breakdown over blocks
- Macros for operation distribution statistics

Data source: data/2026.01.20.per-block-op-distribution.csv
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def process_op_distribution(macros):
    """Process per-block operation distribution and generate figure.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    csv_path = DATA_DIR / "2026.01.20.per-block-op-distribution.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping")
        return

    macros.section("Per-Block Operation Distribution")

    # Read data
    blocks = []
    storage_ops = []  # SLOAD + SSTORE
    call_ops = []  # EXTCODESIZE, EXTCODEHASH, EXTCODECOPY, CALL, STATICCALL, DELEGATECALL, CALLCODE
    account_ops = []  # BALANCE + SELFBALANCE
    creation_ops = []  # CREATE, CREATE2, SELFDESTRUCT

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            blocks.append(int(row["block_number"]))

            storage = int(row["sload"]) + int(row["sstore"])
            calls = (int(row["extcodesize"]) + int(row["extcodehash"]) +
                    int(row["extcodecopy"]) + int(row["call"]) +
                    int(row["staticcall"]) + int(row["delegatecall"]) +
                    int(row["callcode"]))
            account = int(row["balance"]) + int(row["selfbalance"])
            creation = int(row["create"]) + int(row["create2"]) + int(row["selfdestruct"])

            storage_ops.append(storage)
            call_ops.append(calls)
            account_ops.append(account)
            creation_ops.append(creation)

    # Convert to numpy arrays
    blocks = np.array(blocks)
    storage_ops = np.array(storage_ops)
    call_ops = np.array(call_ops)
    account_ops = np.array(account_ops)
    creation_ops = np.array(creation_ops)

    total_ops = storage_ops + call_ops + account_ops + creation_ops

    # Compute aggregate statistics (these should match the existing macros)
    total_storage = storage_ops.sum()
    total_calls = call_ops.sum()
    total_account = account_ops.sum()
    total_creation = creation_ops.sum()
    grand_total = total_storage + total_calls + total_account + total_creation

    # Per-block averages
    avg_ops_per_block = grand_total / len(blocks)
    avg_storage_per_block = total_storage / len(blocks)

    # Add macros
    macros.add("OpDistBlockCount", format_int(len(blocks)), "Blocks in op distribution trace")
    macros.add("AvgOpsPerBlock", format_int(int(avg_ops_per_block)), "Avg operations per block")
    macros.add("AvgStorageOpsPerBlock", format_int(int(avg_storage_per_block)), "Avg storage ops per block")

    # Generate figure - use same block range as IO trace for consistency
    # Filter to first 1000 blocks to match IO trace figure
    mask = blocks <= blocks[0] + 999
    _generate_op_distribution_figure(
        blocks[mask],
        storage_ops[mask],
        call_ops[mask],
        account_ops[mask],
        creation_ops[mask],
        PROJECT_ROOT / "figures" / "op-distribution.pdf"
    )


def _generate_op_distribution_figure(blocks, storage_ops, call_ops, account_ops, creation_ops, output_path):
    """Generate stacked area chart showing operation distribution over blocks."""

    # Convert to percentages per block
    total_ops = storage_ops + call_ops + account_ops + creation_ops
    # Avoid division by zero
    total_ops = np.where(total_ops == 0, 1, total_ops)

    storage_pct = (storage_ops / total_ops) * 100
    call_pct = (call_ops / total_ops) * 100
    account_pct = (account_ops / total_ops) * 100
    creation_pct = (creation_ops / total_ops) * 100

    # Use rolling average to smooth the data (window of 20 blocks)
    window = 20

    def rolling_mean(arr, w):
        cumsum = np.cumsum(np.insert(arr, 0, 0))
        return (cumsum[w:] - cumsum[:-w]) / w

    # Smooth the data
    storage_smooth = rolling_mean(storage_pct, window)
    call_smooth = rolling_mean(call_pct, window)
    account_smooth = rolling_mean(account_pct, window)
    creation_smooth = rolling_mean(creation_pct, window)
    blocks_smooth = blocks[window - 1:]

    # Create figure with two y-axes
    fig, ax1 = plt.subplots(figsize=(6, 3))

    # Stacked area chart for Storage and Calls/Code (primary y-axis)
    ax1.fill_between(
        blocks_smooth,
        0,
        storage_smooth,
        alpha=0.8,
        label="Storage",
        color="#2171b5",
    )
    ax1.fill_between(
        blocks_smooth,
        storage_smooth,
        storage_smooth + call_smooth,
        alpha=0.8,
        label="Calls/Code",
        color="#6baed6",
    )

    ax1.set_xlabel("Block number")
    ax1.set_ylabel("Share of operations (%)")
    ax1.set_xlim(blocks_smooth[0], blocks_smooth[-1])
    ax1.set_ylim(0, 100)

    # Format x-axis to show block numbers nicely
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{x/1e6:.2f}M"))

    # Secondary y-axis for Account and Create/Destroy (lines, zoomed scale)
    ax2 = ax1.twinx()
    ax2.plot(
        blocks_smooth,
        account_smooth,
        color="#cc8400",
        linewidth=1.5,
        label="Account",
    )
    ax2.plot(
        blocks_smooth,
        creation_smooth,
        color="#cc8400",
        linewidth=1.5,
        linestyle="--",
        label="Create/Destroy",
    )
    ax2.set_ylabel("Minor operations (%)", color="#cc8400")
    ax2.tick_params(axis="y", labelcolor="#cc8400", colors="#cc8400")
    ax2.spines["right"].set_color("#cc8400")
    ax2.set_ylim(0, 2)

    # Combined legend outside on top, single row
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.15),
        ncol=4,
        fontsize=8,
        frameon=False,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    # Save figure
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")
