"""
Process access concentration CSV files to verify and generate macros.

Generates macros for:
- Contract-level access concentration (top N contracts)
- Global key-level access concentration (keys with 100+ accesses, etc.)

Data sources:
- data/2026.01.20.contract-access-concentration.csv
- data/2026.01.20.global-key-access-frequency.csv
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def process_access_concentration(macros):
    """Process access concentration data and generate macros.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        PROJECT_ROOT,
        format_int,
        format_float,
        format_percent,
    )

    # Process contract-level concentration
    _process_contract_concentration(macros, DATA_DIR, PROJECT_ROOT)

    # Process global key-level concentration
    _process_global_key_concentration(macros, DATA_DIR)


def _process_contract_concentration(macros, data_dir, project_root):
    """Process contract-level access concentration."""
    from generate_numbers import format_percent

    csv_path = data_dir / "2026.01.20.contract-access-concentration.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping contract concentration")
        return

    macros.section("Contract Access Concentration")

    # Read all data for the figure
    ranks = []
    cumulative_shares_list = []
    cumulative_shares = {}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            share = float(row["cumulative_share"])
            ranks.append(i)
            cumulative_shares_list.append(share)
            cumulative_shares[i] = share

    # Count total contracts
    total_contracts = len(ranks)
    macros.add("TotalContracts", f"{total_contracts:,}", "Total unique contracts")

    # Add macros for top N contracts
    macros.add("ConcentrationTopOne", format_percent(cumulative_shares.get(1, 0), 1), "Top 1 contract share")
    macros.add("ConcentrationTopTwo", format_percent(cumulative_shares.get(2, 0), 1), "Top 2 contracts share")
    macros.add("ConcentrationTopThree", format_percent(cumulative_shares.get(3, 0), 1), "Top 3 contracts share")
    macros.add("ConcentrationTopTen", format_percent(cumulative_shares.get(10, 0), 1), "Top 10 contracts share")
    macros.add("ConcentrationTopTwenty", format_percent(cumulative_shares.get(20, 0), 1), "Top 20 contracts share")
    macros.add("ConcentrationTopHundred", format_percent(cumulative_shares.get(100, 0), 1), "Top 100 contracts share")
    macros.add("ConcentrationTopThousand", format_percent(cumulative_shares.get(1000, 0), 1), "Top 1000 contracts share")
    macros.add("ConcentrationTopTenThousand", format_percent(cumulative_shares.get(10000, 0), 1), "Top 10000 contracts share")

    # Generate figure
    _generate_concentration_figure(
        ranks,
        cumulative_shares_list,
        project_root / "figures" / "contract-concentration.pdf"
    )


def _generate_concentration_figure(ranks, cumulative_shares, output_path):
    """Generate contract concentration curve figure."""

    ranks = np.array(ranks)
    cumulative_shares = np.array(cumulative_shares)
    total_contracts = len(ranks)

    fig, ax = plt.subplots(figsize=(6, 3))

    # Plot cumulative concentration curve
    ax.plot(ranks, cumulative_shares, color="#2171b5", linewidth=1.5)
    ax.fill_between(ranks, 0, cumulative_shares, alpha=0.3, color="#2171b5")

    # Define milestone points to annotate
    milestones = [
        (10, "Top 10"),
        (100, "Top 100"),
        (1000, "Top 1K"),
        (10000, "Top 10K"),
    ]

    # Annotate key points with their cumulative shares
    annotations = []
    for rank, label in milestones:
        if rank <= len(cumulative_shares):
            share = cumulative_shares[rank - 1]
            annotations.append((rank, share, label))

    # Don't add final point annotation - it goes outside the figure
    # Total contracts mentioned in caption instead

    # Position annotations to avoid overlap
    prev_y = 0
    for i, (rank, share, label) in enumerate(annotations):
        # Stagger text positions
        if rank <= 100:
            text_x = rank * 2.5
            text_y = share - 6
        elif rank <= 1000:
            text_x = rank * 2
            text_y = share - 4
        else:
            text_x = rank * 1.5
            text_y = share - 3

        ax.annotate(
            f"{label}: {share:.0f}%",
            xy=(rank, share),
            xytext=(text_x, text_y),
            fontsize=7,
            arrowprops=dict(arrowstyle="-", color="#666666", lw=0.5),
        )

    ax.set_xlabel("Contract rank")
    ax.set_ylabel("Cumulative access share (%)")
    ax.set_xlim(1, total_contracts)
    ax.set_ylim(0, 100)

    # Use log scale for x-axis to show the steep initial rise
    ax.set_xscale("log")
    ax.set_xticks([1, 10, 100, 1000, 10000, 100000])
    ax.set_xticklabels(["1", "10", "100", "1K", "10K", "100K"])

    plt.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Generated figure: {output_path}")


def _process_global_key_concentration(macros, data_dir):
    """Process global key-level access concentration."""
    from generate_numbers import format_int, format_float, format_percent

    csv_path = data_dir / "2026.01.20.global-key-access-frequency.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping global key concentration")
        return

    macros.section("Global Key Access Concentration")

    # Read all data
    access_counts = []
    num_keys = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            access_counts.append(int(row["access_count"]))
            num_keys.append(int(row["num_keys"]))

    access_counts = np.array(access_counts)
    num_keys = np.array(num_keys)

    # Total keys and total accesses
    total_keys = num_keys.sum()
    total_accesses = (access_counts * num_keys).sum()

    # Keys with 100+ accesses
    mask_100plus = access_counts >= 100
    keys_100plus = num_keys[mask_100plus].sum()
    accesses_100plus = (access_counts[mask_100plus] * num_keys[mask_100plus]).sum()
    keys_100plus_pct = (keys_100plus / total_keys) * 100
    accesses_100plus_pct = (accesses_100plus / total_accesses) * 100

    # Keys with 1-2 accesses
    mask_1_2 = access_counts <= 2
    keys_1_2 = num_keys[mask_1_2].sum()
    accesses_1_2 = (access_counts[mask_1_2] * num_keys[mask_1_2]).sum()
    keys_1_2_pct = (keys_1_2 / total_keys) * 100
    accesses_1_2_pct = (accesses_1_2 / total_accesses) * 100

    # Global reuse factor
    global_reuse_factor = total_accesses / total_keys

    # Add macros
    macros.add("GlobalTotalKeys", format_int(total_keys), "Total unique keys globally")
    macros.add("GlobalTotalAccesses", format_int(total_accesses), "Total storage accesses globally")
    macros.add("GlobalReuseFactor", format_float(global_reuse_factor, 2), "Global reuse factor")

    macros.add("GlobalKeysHundredPlus", format_int(keys_100plus), "Keys with 100+ accesses")
    macros.add("GlobalKeysHundredPlusPct", format_float(keys_100plus_pct, 2), "Pct of keys with 100+ accesses")
    macros.add("GlobalAccessesHundredPlusPct", format_float(accesses_100plus_pct, 1), "Pct of accesses from 100+ keys")

    macros.add("GlobalKeysOneToTwo", format_int(keys_1_2), "Keys with 1-2 accesses")
    macros.add("GlobalKeysOneToTwoPct", format_int(round(keys_1_2_pct)), "Pct of keys with 1-2 accesses")
    macros.add("GlobalAccessesOneToTwoPct", format_float(accesses_1_2_pct, 1), "Pct of accesses from 1-2 keys")

    # Print verification info
    print(f"\n=== Global Key Concentration Verification ===")
    print(f"Total unique keys: {total_keys:,}")
    print(f"Total accesses: {total_accesses:,}")
    print(f"Global reuse factor: {global_reuse_factor:.2f}x")
    print(f"Keys with 100+ accesses: {keys_100plus:,} ({keys_100plus_pct:.2f}%)")
    print(f"Accesses from 100+ keys: {accesses_100plus_pct:.1f}%")
    print(f"Keys with 1-2 accesses: {keys_1_2:,} ({keys_1_2_pct:.0f}%)")
    print(f"Accesses from 1-2 keys: {accesses_1_2_pct:.1f}%")
    print("=" * 50)
