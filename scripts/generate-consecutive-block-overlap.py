#!/usr/bin/env python3
"""Generate consecutive block overlap analysis from parquet trace data.

For each consecutive block pair (n, n+1), compute:
- keys_in_block_n: unique keys in block n
- keys_in_block_n_plus_1: unique keys in block n+1
- overlap: keys that appear in both
- overlap_pct: overlap / keys_in_block_n_plus_1 * 100
"""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("CONSECUTIVE BLOCK OVERLAP ANALYSIS")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    print("\nCalculating consecutive block overlaps (this may take a while)...")

    results = con.execute(f"""
        WITH block_keys AS (
            -- Get unique keys per block
            SELECT DISTINCT
                block_number,
                target_address,
                storage_slot
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)  -- SLOAD and SSTORE only
        ),
        block_key_counts AS (
            -- Count unique keys per block
            SELECT
                block_number,
                COUNT(*) as unique_keys
            FROM block_keys
            GROUP BY block_number
        ),
        overlap_counts AS (
            -- Find overlap between consecutive blocks
            SELECT
                b1.block_number,
                COUNT(*) as overlap_count
            FROM block_keys b1
            INNER JOIN block_keys b2
                ON b1.block_number + 1 = b2.block_number
                AND b1.target_address = b2.target_address
                AND b1.storage_slot = b2.storage_slot
            GROUP BY b1.block_number
        )
        SELECT
            c1.block_number,
            c1.unique_keys as keys_in_block,
            c2.unique_keys as keys_in_next_block,
            COALESCE(o.overlap_count, 0) as overlap,
            ROUND(100.0 * COALESCE(o.overlap_count, 0) / c2.unique_keys, 2) as overlap_pct
        FROM block_key_counts c1
        INNER JOIN block_key_counts c2 ON c1.block_number + 1 = c2.block_number
        LEFT JOIN overlap_counts o ON c1.block_number = o.block_number
        ORDER BY c1.block_number
    """).fetchdf()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.consecutive-block-overlap.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total block pairs: {len(results):,}")

    # Print summary statistics
    print("\n" + "-" * 70)
    print("SAMPLE (first 10 block pairs)")
    print("-" * 70)

    print(f"{'Block':<12} {'Keys':>10} {'Next Keys':>12} {'Overlap':>10} {'Overlap%':>10}")
    print("-" * 54)

    for i, row in results.head(10).iterrows():
        print(f"{row['block_number']:<12} {row['keys_in_block']:>10,} {row['keys_in_next_block']:>12,} {row['overlap']:>10,} {row['overlap_pct']:>9.2f}%")

    # Summary stats
    print("\n" + "-" * 70)
    print("OVERLAP STATISTICS")
    print("-" * 70)
    print(f"Mean overlap percentage: {results['overlap_pct'].mean():.2f}%")
    print(f"Median overlap percentage: {results['overlap_pct'].median():.2f}%")
    print(f"Min overlap percentage: {results['overlap_pct'].min():.2f}%")
    print(f"Max overlap percentage: {results['overlap_pct'].max():.2f}%")
    print(f"Std deviation: {results['overlap_pct'].std():.2f}%")

    # Percentile analysis
    print("\n" + "-" * 70)
    print("OVERLAP PERCENTILES")
    print("-" * 70)
    for pct in [10, 25, 50, 75, 90, 95, 99]:
        val = results['overlap_pct'].quantile(pct / 100)
        print(f"{pct}th percentile: {val:.2f}%")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
