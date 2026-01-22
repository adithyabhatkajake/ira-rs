#!/usr/bin/env python3
"""Generate intra-block access frequency distribution from parquet trace data.

This script calculates how many times each unique key is accessed within a single block,
then outputs the frequency distribution (how many keys are accessed 1 time, 2 times, etc.)
"""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("INTRA-BLOCK ACCESS FREQUENCY DISTRIBUTION")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    # Step 1: Count accesses per (block, address, slot) for storage ops
    # Step 2: Group by access count to get frequency distribution
    print("\nCalculating frequency distribution...")

    results = con.execute(f"""
        WITH key_access_counts AS (
            -- Count how many times each (block, address, slot) is accessed
            SELECT
                block_number,
                target_address,
                storage_slot,
                COUNT(*) as access_count
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)  -- SLOAD and SSTORE only (storage operations)
            GROUP BY block_number, target_address, storage_slot
        )
        SELECT
            access_count,
            COUNT(*) as num_keys
        FROM key_access_counts
        GROUP BY access_count
        ORDER BY access_count
    """).fetchdf()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.intra-block-access-frequency.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total unique access counts: {len(results):,}")

    # Print summary statistics
    print("\n" + "-" * 70)
    print("FREQUENCY DISTRIBUTION (top 20)")
    print("-" * 70)

    total_keys = results['num_keys'].sum()
    cumulative = 0

    print(f"{'Access Count':<15} {'Num Keys':>15} {'Percentage':>12} {'Cumulative':>12}")
    print("-" * 54)

    for i, row in results.head(20).iterrows():
        pct = row['num_keys'] / total_keys * 100
        cumulative += pct
        print(f"{row['access_count']:<15} {row['num_keys']:>15,} {pct:>11.2f}% {cumulative:>11.2f}%")

    if len(results) > 20:
        print(f"... and {len(results) - 20} more rows")

    # Summary stats
    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)
    print(f"Total (block, key) pairs: {total_keys:,}")
    print(f"Max access count: {results['access_count'].max():,}")
    print(f"Keys accessed only once: {results[results['access_count'] == 1]['num_keys'].sum():,} ({results[results['access_count'] == 1]['num_keys'].sum() / total_keys * 100:.1f}%)")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
