"""
Process intra-block access frequency CSV to generate distribution graph.

Generates:
- Frequency distribution graph (# accesses vs # keys)
- Macros for intra-block locality statistics

Data source: data/2026.01.20.intra-block-access-frequency.csv
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def process_intra_block_frequency(macros):
    """Process intra-block access frequency and generate figure.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    csv_path = DATA_DIR / "2026.01.20.intra-block-access-frequency.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping")
        return

    macros.section("Intra-Block Access Frequency")

    # Read data
    access_counts = []
    num_keys = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            access_counts.append(int(row["access_count"]))
            num_keys.append(int(row["num_keys"]))

    access_counts = np.array(access_counts)
    num_keys = np.array(num_keys)

    # Compute statistics
    total_keys = num_keys.sum()
    total_accesses = (access_counts * num_keys).sum()

    # Keys with single access
    single_access_keys = num_keys[access_counts == 1].sum()
    single_access_pct = (single_access_keys / total_keys) * 100

    # Keys with 2+ accesses
    multi_access_keys = total_keys - single_access_keys
    multi_access_pct = (multi_access_keys / total_keys) * 100

    # Repeated accesses (total - first access for each key)
    first_accesses = total_keys
    repeated_accesses = total_accesses - first_accesses
    repeated_access_pct = (repeated_accesses / total_accesses) * 100

    # Reuse factor
    reuse_factor = total_accesses / total_keys

    # Max access count
    max_access_count = access_counts.max()

    # Compute bucketed stats for table (matching original table format)
    keys_1 = num_keys[access_counts == 1].sum()
    keys_2 = num_keys[access_counts == 2].sum()
    keys_3_5 = num_keys[(access_counts >= 3) & (access_counts <= 5)].sum()
    keys_6_10 = num_keys[(access_counts >= 6) & (access_counts <= 10)].sum()
    keys_gt_10 = num_keys[access_counts > 10].sum()

    # Add macros
    macros.add("IntraBlockTotalKeys", format_int(total_keys), "Total block-key pairs")
    macros.add("IntraBlockTotalAccesses", format_int(total_accesses), "Total storage accesses")
    macros.add("IntraBlockSingleAccessKeys", format_int(single_access_keys), "Keys accessed once")
    macros.add("IntraBlockSingleAccessPct", format_percent(single_access_pct, 1), "Pct keys accessed once")
    macros.add("IntraBlockMultiAccessPct", format_percent(multi_access_pct, 1), "Pct keys accessed 2+")
    macros.add("IntraBlockRepeatedAccessPct", format_percent(repeated_access_pct, 1), "Pct accesses that are repeats")
    macros.add("IntraBlockReuseFactor", format_float(reuse_factor, 2), "Avg accesses per key")
    macros.add("IntraBlockMaxAccessCount", format_int(max_access_count), "Max accesses to single key")

    # Bucketed counts for appendix table
    macros.add("IntraBlockKeysOne", format_int(keys_1), "Keys with 1 access")
    macros.add("IntraBlockKeysTwo", format_int(keys_2), "Keys with 2 accesses")
    macros.add("IntraBlockKeysThreeToFive", format_int(keys_3_5), "Keys with 3-5 accesses")
    macros.add("IntraBlockKeysSixToTen", format_int(keys_6_10), "Keys with 6-10 accesses")
    macros.add("IntraBlockKeysGtTen", format_int(keys_gt_10), "Keys with >10 accesses")

    # Percentages for appendix table
    macros.add("IntraBlockKeysOnePct", format_percent((keys_1/total_keys)*100, 1), "Pct keys with 1 access")
    macros.add("IntraBlockKeysTwoPct", format_percent((keys_2/total_keys)*100, 1), "Pct keys with 2 accesses")
    macros.add("IntraBlockKeysThreeToFivePct", format_percent((keys_3_5/total_keys)*100, 1), "Pct keys with 3-5 accesses")
    macros.add("IntraBlockKeysSixToTenPct", format_percent((keys_6_10/total_keys)*100, 1), "Pct keys with 6-10 accesses")
    macros.add("IntraBlockKeysGtTenPct", format_percent((keys_gt_10/total_keys)*100, 1), "Pct keys with >10 accesses")

    # Generate figure
    _generate_frequency_distribution_figure(
        access_counts,
        num_keys,
        PROJECT_ROOT / "figures" / "intra-block-frequency.pdf"
    )


def _generate_frequency_distribution_figure(access_counts, num_keys, output_path):
    """Generate frequency distribution graph."""

    # Bucket: merge all >10 into one bucket
    threshold = 10
    mask_below = access_counts <= threshold
    mask_above = access_counts > threshold

    # Data for counts <= 10
    counts_below = access_counts[mask_below]
    keys_below = num_keys[mask_below]

    # Aggregate counts > 10 into single bucket
    keys_above = num_keys[mask_above].sum()

    # Convert to percentages
    total_keys = keys_below.sum() + keys_above
    keys_below_pct = (keys_below / total_keys) * 100
    keys_above_pct = (keys_above / total_keys) * 100

    # Create figure
    fig, ax = plt.subplots(figsize=(6, 3))

    # Bar chart for counts <= 10
    ax.bar(counts_below, keys_below_pct, width=0.8, color="#2171b5", alpha=0.8, linewidth=0)

    # Add the >10 bucket as a separate bar
    ax.bar(threshold + 1.5, keys_above_pct, width=1.5, color="#2171b5", alpha=0.8, linewidth=0)

    ax.set_xlabel("Accesses per key (within block)")
    ax.set_ylabel("Share of keys (%)")

    # Linear scale
    ax.set_xlim(0, threshold + 3)
    ax.set_ylim(0, None)

    # Add label for the >10 bucket
    ax.annotate(
        f">10",
        xy=(threshold + 1.5, keys_above_pct),
        xytext=(threshold + 1.5, keys_above_pct + 1),
        ha="center",
        fontsize=8,
    )

    # Format x-axis ticks
    ax.set_xticks([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    ax.set_xticklabels(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])

    plt.tight_layout()

    # Save figure
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")
