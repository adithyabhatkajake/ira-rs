#!/usr/bin/env python3
"""
Graph bytes per cache entry from the CSV data.

Creates a matplotlib figure showing value size distribution by operation type.
"""

import os

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

DATA_DIR = Path(os.environ.get("IRA_OUTPUT", "data"))
OUTPUT_DIR = Path(os.environ.get("IRA_FIGURES", "figures"))


def main():
    # Find the most recent CSV file
    csv_files = list(DATA_DIR.glob("*.measure-bytes-per-cache-entry.csv"))
    if not csv_files:
        print("No CSV files found in data directory")
        return

    csv_path = sorted(csv_files)[-1]  # Most recent
    print(f"Reading: {csv_path}")

    df = pd.read_csv(csv_path)

    # Filter out insignificant operation types (those with 0 value bytes everywhere)
    # Keep: SLOAD, SSTORE, BALANCE, SELFBALANCE, EXTCODESIZE, EXTCODEHASH, EXTCODECOPY, CREATE, CREATE2
    # Remove: CALL, STATICCALL, DELEGATECALL, CALLCODE, SELFDESTRUCT (all have 0 value bytes)
    significant_ops = ['SLOAD', 'SSTORE', 'EXTCODECOPY', 'CREATE', 'CREATE2']
    df = df[df['op_name'].isin(significant_ops)]

    # Also filter out rows where value_bytes is 0 (not meaningful for cache)
    df = df[df['value_bytes'] > 0]

    print(f"Filtered to {len(df)} rows across {df['op_name'].nunique()} operation types")

    # Single plot with all data
    # Format: (name, op_names, color, use_bars)
    plot_groups = [
        ('Storage (SLOAD/SSTORE)', ['SLOAD', 'SSTORE'], '#3498db', True),
        ('EXTCODECOPY', ['EXTCODECOPY'], '#e74c3c', False),
        ('CREATE', ['CREATE'], '#9b59b6', False),
        ('CREATE2', ['CREATE2'], '#f39c12', False),
    ]

    fig, ax = plt.subplots(figsize=(8, 5))

    # Calculate grand total for percentages
    grand_total = df['count'].sum()

    for group_name, op_names, color, use_bars in plot_groups:
        # Combine data for this group
        group_data = df[df['op_name'].isin(op_names)].copy()
        if len(group_data) == 0:
            continue

        # Aggregate by value_bytes
        agg_data = group_data.groupby('value_bytes')['count'].sum().reset_index()
        agg_data = agg_data.sort_values('value_bytes')

        total_count = agg_data['count'].sum()
        pct = total_count / grand_total * 100
        # Use more decimal places for small percentages to show at least one significant digit
        if pct >= 0.1:
            pct_str = f'{pct:.1f}%'
        elif pct >= 0.01:
            pct_str = f'{pct:.2f}%'
        else:
            pct_str = f'{pct:.3f}%'
        label = f'{group_name} ({pct_str})'

        if use_bars:
            # Use bars for constant/fixed value sizes
            ax.bar(agg_data['value_bytes'], agg_data['count'],
                   width=agg_data['value_bytes'].max() * 0.15,
                   color=color, alpha=0.8, label=label)
        else:
            # Use lines for variable-size distributions
            if len(agg_data) > 50:
                # Bin the data for smoother lines
                bins = np.logspace(np.log10(max(1, agg_data['value_bytes'].min())),
                                   np.log10(agg_data['value_bytes'].max()), 50)
                agg_data['bin'] = pd.cut(agg_data['value_bytes'], bins=bins, labels=False)
                binned = agg_data.groupby('bin').agg({
                    'value_bytes': 'mean',
                    'count': 'sum'
                }).dropna()

                ax.plot(binned['value_bytes'], binned['count'],
                        color=color, linewidth=2, alpha=0.9, label=label)
                ax.fill_between(binned['value_bytes'], binned['count'],
                                color=color, alpha=0.2)
            else:
                ax.plot(agg_data['value_bytes'], agg_data['count'],
                        color=color, linewidth=2, alpha=0.9, label=label)
                ax.fill_between(agg_data['value_bytes'], agg_data['count'],
                                color=color, alpha=0.2)

    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Value Size (bytes)', fontsize=11)
    ax.set_ylabel('Count', fontsize=11)
    ax.set_xlim(10, 50000)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3, which='both')

    plt.tight_layout()

    # Save figure as PDF
    pdf_path = OUTPUT_DIR / "bytes-per-cache-entry.pdf"
    plt.savefig(pdf_path, bbox_inches='tight')
    print(f"Saved: {pdf_path}")

    # Print summary statistics
    print("\n" + "=" * 60)
    print("SUMMARY STATISTICS")
    print("=" * 60)

    for op_name in significant_ops:
        op_data = df[df['op_name'] == op_name]
        if len(op_data) == 0:
            continue

        total_count = op_data['count'].sum()
        weighted_avg = (op_data['value_bytes'] * op_data['count']).sum() / total_count
        min_size = op_data['value_bytes'].min()
        max_size = op_data['value_bytes'].max()

        print(f"\n{op_name}:")
        print(f"  Total operations: {total_count:,}")
        print(f"  Value size range: {min_size} - {max_size} bytes")
        print(f"  Weighted avg size: {weighted_avg:.1f} bytes")


if __name__ == "__main__":
    main()
