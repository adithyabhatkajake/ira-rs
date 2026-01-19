#!/usr/bin/env python3
"""
Graph compression and decompression times from the CSV data.

Creates a single plot showing the distribution of compression vs decompression times.
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

    # Sort by block number
    df = df.sort_values('block_number')

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot line charts with block number on x-axis
    ax.plot(df['block_number'], df['compression_time_us'], alpha=0.7,
            label=f'Compression (median: {df["compression_time_us"].median():.0f} µs)', color='#e74c3c', linewidth=0.5)
    ax.plot(df['block_number'], df['decompression_time_us'], alpha=0.7,
            label=f'Decompression (median: {df["decompression_time_us"].median():.0f} µs)', color='#3498db', linewidth=0.5)

    ax.set_xlabel('Block Number', fontsize=11)
    ax.set_ylabel('Time (µs)', fontsize=11)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Format x-axis to show block numbers nicely
    ax.ticklabel_format(axis='x', style='plain', useOffset=False)

    plt.tight_layout()

    # Save figure
    pdf_path = OUTPUT_DIR / "hint-compression-decompression-time.pdf"
    plt.savefig(pdf_path, bbox_inches='tight')
    print(f"Saved: {pdf_path}")

    # Print summary
    median_compress = df['compression_time_us'].median()
    median_decompress = df['decompression_time_us'].median()
    speedup = median_compress / median_decompress

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Compression time:   median {median_compress:.0f} µs, P95 {df['compression_time_us'].quantile(0.95):.0f} µs")
    print(f"Decompression time: median {median_decompress:.0f} µs, P95 {df['decompression_time_us'].quantile(0.95):.0f} µs")
    print(f"Decompression is {speedup:.1f}x faster")


if __name__ == "__main__":
    main()
