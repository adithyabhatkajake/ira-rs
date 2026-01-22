#!/usr/bin/env python3
"""Generate per-block unique storage keys count from parquet trace data.

For each block, count the number of unique (target_address, storage_slot) pairs.
"""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("PER-BLOCK UNIQUE STORAGE KEYS")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    print("\nCalculating unique keys per block...")

    results = con.execute(f"""
        SELECT
            block_number,
            COUNT(DISTINCT (target_address, storage_slot)) as unique_storage_keys
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)  -- SLOAD and SSTORE only
        GROUP BY block_number
        ORDER BY block_number
    """).fetchdf()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.per-block-unique-keys.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total blocks: {len(results):,}")

    # Print summary statistics
    print("\n" + "-" * 70)
    print("SAMPLE (first 10 blocks)")
    print("-" * 70)

    print(f"{'Block Number':<15} {'Unique Keys':>15}")
    print("-" * 30)

    for i, row in results.head(10).iterrows():
        print(f"{row['block_number']:<15} {row['unique_storage_keys']:>15,}")

    # Summary stats
    print("\n" + "-" * 70)
    print("SUMMARY STATISTICS")
    print("-" * 70)
    print(f"Total blocks: {len(results):,}")
    print(f"Total unique key accesses: {results['unique_storage_keys'].sum():,}")
    print(f"Mean unique keys per block: {results['unique_storage_keys'].mean():,.1f}")
    print(f"Median unique keys per block: {results['unique_storage_keys'].median():,.1f}")
    print(f"Min unique keys: {results['unique_storage_keys'].min():,}")
    print(f"Max unique keys: {results['unique_storage_keys'].max():,}")
    print(f"Std deviation: {results['unique_storage_keys'].std():,.1f}")

    # Percentile analysis
    print("\n" + "-" * 70)
    print("PERCENTILES")
    print("-" * 70)
    for pct in [10, 25, 50, 75, 90, 95, 99]:
        val = results['unique_storage_keys'].quantile(pct / 100)
        print(f"{pct}th percentile: {val:,.0f} keys")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
