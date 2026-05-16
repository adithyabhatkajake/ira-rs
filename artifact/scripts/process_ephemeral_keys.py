"""
Process ephemeral key data to verify and generate macros.

Verifies:
- Key lifespan distribution
- Consecutive block overlap statistics
- Per-block unique keys statistics

Data sources:
- data/2026.01.20.key-lifespan-distribution.csv
- data/2026.01.20.consecutive-block-overlap.csv
- data/2026.01.20.per-block-unique-keys.csv
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def process_ephemeral_keys(macros):
    """Process ephemeral key data and generate macros.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    _process_key_lifespan(macros, DATA_DIR, PROJECT_ROOT)
    _process_consecutive_overlap(macros, DATA_DIR)
    _process_per_block_unique_keys(macros, DATA_DIR)


def _process_key_lifespan(macros, data_dir, project_root):
    """Process key lifespan distribution."""
    from generate_numbers import format_int, format_percent

    csv_path = data_dir / "2026.01.20.key-lifespan-distribution.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping key lifespan")
        return

    macros.section("Key Lifespan Distribution")

    # Read data
    blocks_appeared = []
    num_keys = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            blocks_appeared.append(int(row["blocks_appeared"]))
            num_keys.append(int(row["num_keys"]))

    blocks_appeared = np.array(blocks_appeared)
    num_keys = np.array(num_keys)

    total_keys = num_keys.sum()

    # Compute bucketed statistics matching the table
    keys_1 = num_keys[blocks_appeared == 1].sum()
    keys_2_5 = num_keys[(blocks_appeared >= 2) & (blocks_appeared <= 5)].sum()
    keys_6_20 = num_keys[(blocks_appeared >= 6) & (blocks_appeared <= 20)].sum()
    keys_21_50 = num_keys[(blocks_appeared >= 21) & (blocks_appeared <= 50)].sum()
    keys_gt_50 = num_keys[blocks_appeared > 50].sum()

    # Percentages
    pct_1 = (keys_1 / total_keys) * 100
    pct_2_5 = (keys_2_5 / total_keys) * 100
    pct_6_20 = (keys_6_20 / total_keys) * 100
    pct_21_50 = (keys_21_50 / total_keys) * 100
    pct_gt_50 = (keys_gt_50 / total_keys) * 100

    # Add macros
    macros.add("LifespanKeysOneBlock", format_int(keys_1), "Keys appearing in 1 block")
    macros.add("LifespanKeysTwoToFive", format_int(keys_2_5), "Keys appearing in 2-5 blocks")
    macros.add("LifespanKeysSixToTwenty", format_int(keys_6_20), "Keys appearing in 6-20 blocks")
    macros.add("LifespanKeysTwentyOneToFifty", format_int(keys_21_50), "Keys appearing in 21-50 blocks")
    macros.add("LifespanKeysGtFifty", format_int(keys_gt_50), "Keys appearing in >50 blocks")

    macros.add("LifespanPctOneBlock", format_percent(pct_1, 1), "Pct keys in 1 block")
    macros.add("LifespanPctTwoToFive", format_percent(pct_2_5, 1), "Pct keys in 2-5 blocks")
    macros.add("LifespanPctSixToTwenty", format_percent(pct_6_20, 1), "Pct keys in 6-20 blocks")
    macros.add("LifespanPctTwentyOneToFifty", format_percent(pct_21_50, 1), "Pct keys in 21-50 blocks")
    macros.add("LifespanPctGtFifty", format_percent(pct_gt_50, 1), "Pct keys in >50 blocks")

    # Print verification
    print(f"\n=== Key Lifespan Verification ===")
    print(f"Total keys: {total_keys:,}")
    print(f"1 block: {keys_1:,} ({pct_1:.1f}%)")
    print(f"2-5 blocks: {keys_2_5:,} ({pct_2_5:.1f}%)")
    print(f"6-20 blocks: {keys_6_20:,} ({pct_6_20:.1f}%)")
    print(f"21-50 blocks: {keys_21_50:,} ({pct_21_50:.1f}%)")
    print(f">50 blocks: {keys_gt_50:,} ({pct_gt_50:.1f}%)")

    # Generate figure
    _generate_key_lifespan_figure(
        [pct_1, pct_2_5, pct_6_20, pct_21_50, pct_gt_50],
        project_root / "figures" / "key-lifespan.pdf"
    )


def _generate_key_lifespan_figure(percentages, output_path):
    """Generate key lifespan distribution bar chart."""

    labels = ["1", "2–5", "6–20", "21–50", ">50"]
    x_pos = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(6, 3))

    bars = ax.bar(x_pos, percentages, width=0.7, color="#2171b5", alpha=0.8)

    # Add value labels on bars
    for bar, pct in zip(bars, percentages):
        height = bar.get_height()
        ax.annotate(
            f"{pct:.1f}%",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax.set_xlabel("Key lifespan (blocks)")
    ax.set_ylabel("Share of keys (%)")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(percentages) * 1.15)

    plt.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _process_consecutive_overlap(macros, data_dir):
    """Process consecutive block overlap statistics."""
    from generate_numbers import format_float, format_percent

    csv_path = data_dir / "2026.01.20.consecutive-block-overlap.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping consecutive overlap")
        return

    macros.section("Consecutive Block Overlap")

    # Read data
    overlap_pcts = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            overlap_pcts.append(float(row["overlap_pct"]))

    overlap_pcts = np.array(overlap_pcts)

    avg_overlap = overlap_pcts.mean()
    median_overlap = np.median(overlap_pcts)
    max_overlap = overlap_pcts.max()
    min_overlap = overlap_pcts.min()

    # Add macros
    macros.add("OverlapAvg", format_percent(avg_overlap, 1), "Avg consecutive block overlap")
    macros.add("OverlapMedian", format_percent(median_overlap, 1), "Median consecutive block overlap")
    macros.add("OverlapMax", format_percent(max_overlap, 1), "Max consecutive block overlap")
    macros.add("OverlapMin", format_percent(min_overlap, 1), "Min consecutive block overlap")

    # Print verification
    print(f"\n=== Consecutive Block Overlap Verification ===")
    print(f"Average: {avg_overlap:.1f}%")
    print(f"Median: {median_overlap:.1f}%")
    print(f"Max: {max_overlap:.1f}%")
    print(f"Min: {min_overlap:.1f}%")


def _process_per_block_unique_keys(macros, data_dir):
    """Process per-block unique keys statistics."""
    from generate_numbers import format_int, PROJECT_ROOT

    csv_path = data_dir / "2026.01.20.per-block-unique-keys.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping per-block unique keys")
        return

    macros.section("Per-Block Unique Keys")

    # Read data
    unique_keys = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            unique_keys.append(int(row["unique_storage_keys"]))

    unique_keys = np.array(unique_keys)

    median_keys = int(np.median(unique_keys))
    p95_keys = int(np.percentile(unique_keys, 95))
    max_keys = int(unique_keys.max())
    min_keys = int(unique_keys.min())

    # Add macros
    macros.add("UniqueKeysMedian", format_int(median_keys), "Median unique keys per block")
    macros.add("UniqueKeysPNinetyFive", format_int(p95_keys), "P95 unique keys per block")
    macros.add("UniqueKeysMax", format_int(max_keys), "Max unique keys per block")
    macros.add("UniqueKeysMin", format_int(min_keys), "Min unique keys per block")

    # Print verification
    print(f"\n=== Per-Block Unique Keys Verification ===")
    print(f"Median: {median_keys:,}")
    print(f"P95: {p95_keys:,}")
    print(f"Max: {max_keys:,}")
    print(f"Min: {min_keys:,}")

    # Process per-block operations and generate combined figure
    _process_per_block_stats(macros, data_dir, unique_keys, PROJECT_ROOT)


def _process_per_block_stats(macros, data_dir, unique_keys, project_root):
    """Process per-block operation statistics and generate figure."""
    from generate_numbers import format_int, format_float

    csv_path = data_dir / "2026.01.20.per-block-op-distribution.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping per-block stats figure")
        return

    macros.section("Per-Block Operations")

    # Read operation data
    total_ops = []
    storage_ops = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total = sum(int(row[col]) for col in row if col != 'block_number')
            storage = int(row['sload']) + int(row['sstore'])
            total_ops.append(total)
            storage_ops.append(storage)

    total_ops = np.array(total_ops)
    storage_ops = np.array(storage_ops)

    # Compute statistics
    total_median = int(np.median(total_ops))
    total_p95 = int(np.percentile(total_ops, 95))
    total_max = int(total_ops.max())

    storage_median = int(np.median(storage_ops))
    storage_p95 = int(np.percentile(storage_ops, 95))
    storage_max = int(storage_ops.max())

    unique_median = int(np.median(unique_keys))
    unique_p95 = int(np.percentile(unique_keys, 95))
    unique_max = int(unique_keys.max())

    # Add macros
    macros.add("TotalOpsMedian", format_int(total_median), "Median total ops per block")
    macros.add("TotalOpsPNinetyFive", format_int(total_p95), "P95 total ops per block")
    macros.add("TotalOpsMax", format_int(total_max), "Max total ops per block")

    macros.add("StorageOpsMedian", format_int(storage_median), "Median storage ops per block")
    macros.add("StorageOpsPNinetyFive", format_int(storage_p95), "P95 storage ops per block")
    macros.add("StorageOpsMax", format_int(storage_max), "Max storage ops per block")

    # Compute distribution percentages for unique keys
    total_blocks = len(unique_keys)
    pct_lt_2k = np.sum(unique_keys < 2000) / total_blocks * 100
    pct_lt_3k = np.sum(unique_keys < 3000) / total_blocks * 100
    pct_gte_5k = np.sum(unique_keys >= 5000) / total_blocks * 100

    macros.add("PctBlocksLtTwoK", format_int(round(pct_lt_2k)), "Pct blocks with <2K unique keys")
    macros.add("PctBlocksLtThreeK", format_int(round(pct_lt_3k)), "Pct blocks with <3K unique keys")
    macros.add("PctBlocksGteFiveK", format_float(pct_gte_5k, 1), "Pct blocks with >=5K unique keys")

    # Print verification
    print(f"\n=== Per-Block Operations Verification ===")
    print(f"Total ops - Median: {total_median:,}, P95: {total_p95:,}, Max: {total_max:,}")
    print(f"Storage ops - Median: {storage_median:,}, P95: {storage_p95:,}, Max: {storage_max:,}")

    # Generate figure
    _generate_per_block_stats_figure(
        total_ops,
        storage_ops,
        unique_keys,
        project_root / "figures" / "per-block-stats.pdf"
    )


def _generate_per_block_stats_figure(total_ops, storage_ops, unique_keys, output_path):
    """Generate per-block statistics CDF plot."""

    fig, ax = plt.subplots(figsize=(6, 3))

    # Sort and compute CDFs
    def plot_cdf(data, label, color, linestyle='-'):
        sorted_data = np.sort(data)
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data) * 100
        ax.plot(sorted_data, cdf, label=label, color=color, linewidth=1.5, linestyle=linestyle)

    plot_cdf(total_ops, 'Total operations', '#2171b5')
    plot_cdf(storage_ops, 'Storage operations', '#6baed6')
    plot_cdf(unique_keys, 'Unique keys', '#08519c', linestyle='--')

    ax.set_xlabel('Count per block')
    ax.set_ylabel('Cumulative % of blocks')
    ax.set_xscale('log')
    ax.set_xlim(100, 150000)
    ax.set_ylim(0, 100)

    # Add reference lines for key percentiles
    ax.axhline(y=50, color='#999999', linestyle=':', linewidth=0.5, alpha=0.7)
    ax.axhline(y=95, color='#999999', linestyle=':', linewidth=0.5, alpha=0.7)

    # Annotate median and P95
    ax.text(120, 52, 'Median', fontsize=9, color='#666666')
    ax.text(120, 91, 'P95', fontsize=9, color='#666666')

    ax.legend(loc='lower right', fontsize=8)

    plt.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")
