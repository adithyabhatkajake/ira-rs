#!/usr/bin/env python3
"""
Graph hint sizes (raw and compressed) from the CSV data.

Creates a single plot showing the distribution of raw vs compressed hint sizes.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data")
OUTPUT_DIR = Path("/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/figures")


def main():
    # Find the most recent CSV file
    csv_files = list(DATA_DIR.glob("*.measure-all-keys-as-hint-size.csv"))
    if not csv_files:
        print("No CSV files found in data directory")
        return

    csv_path = sorted(csv_files)[-1]  # Most recent
    print(f"Reading: {csv_path}")

    df = pd.read_csv(csv_path)

    # Filter out blocks with no data
    df = df[df['raw_size_bytes'] > 0]
    print(f"Blocks with data: {len(df):,}")

    # Convert to KB
    df['raw_size_kb'] = df['raw_size_bytes'] / 1024
    df['compressed_size_kb'] = df['compressed_size_bytes'] / 1024

    # Sort by block number
    df = df.sort_values('block_number')

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot line charts with block number on x-axis
    ax.plot(df['block_number'], df['raw_size_kb'], alpha=0.7,
            label=f'Raw (median: {df["raw_size_kb"].median():.1f} KB)', color='#e74c3c', linewidth=0.5)
    ax.plot(df['block_number'], df['compressed_size_kb'], alpha=0.7,
            label=f'Compressed (median: {df["compressed_size_kb"].median():.1f} KB)', color='#3498db', linewidth=0.5)

    ax.set_xlabel('Block Number', fontsize=11)
    ax.set_ylabel('Hint Size (KB)', fontsize=11)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Format x-axis to show block numbers nicely
    ax.ticklabel_format(axis='x', style='plain', useOffset=False)

    plt.tight_layout()

    # Save figure
    pdf_path = OUTPUT_DIR / "hint-size-normal-and-compressed.pdf"
    plt.savefig(pdf_path, bbox_inches='tight')
    print(f"Saved: {pdf_path}")

    # Print summary
    median_ratio = df['raw_size_bytes'].median() / df['compressed_size_bytes'].median()

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Raw size:        median {df['raw_size_kb'].median():.1f} KB, P95 {df['raw_size_kb'].quantile(0.95):.1f} KB")
    print(f"Compressed size: median {df['compressed_size_kb'].median():.1f} KB, P95 {df['compressed_size_kb'].quantile(0.95):.1f} KB")
    print(f"Compression ratio: {median_ratio:.2f}x")


if __name__ == "__main__":
    main()
