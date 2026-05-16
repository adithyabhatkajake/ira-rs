#!/usr/bin/env python3
"""Generate key lifespan distribution from parquet trace data.

For each unique (target_address, storage_slot) pair, count the number of
DISTINCT blocks in which it appears, then output the frequency distribution.
"""

import os
import duckdb
from datetime import date

DATA_PATH = os.environ.get("IRA_TRACES", "/Volumes/X/ira-new-analysis/*.parquet")
OUTPUT_DIR = os.environ.get("IRA_OUTPUT", "data")


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("KEY LIFESPAN DISTRIBUTION")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    print("\nCalculating key lifespans (this may take a while)...")

    results = con.execute(f"""
        WITH key_block_counts AS (
            -- Count how many distinct blocks each (address, slot) appears in
            SELECT
                target_address,
                storage_slot,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)  -- SLOAD and SSTORE only
            GROUP BY target_address, storage_slot
        )
        SELECT
            blocks_appeared,
            COUNT(*) as num_keys
        FROM key_block_counts
        GROUP BY blocks_appeared
        ORDER BY blocks_appeared
    """).fetchdf()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.key-lifespan-distribution.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total unique lifespan values: {len(results):,}")

    # Print summary statistics
    print("\n" + "-" * 70)
    print("LIFESPAN DISTRIBUTION (top 20)")
    print("-" * 70)

    total_keys = results['num_keys'].sum()
    cumulative = 0

    print(f"{'Blocks Appeared':<18} {'Num Keys':>15} {'Percentage':>12} {'Cumulative':>12}")
    print("-" * 57)

    for i, row in results.head(20).iterrows():
        pct = row['num_keys'] / total_keys * 100
        cumulative += pct
        print(f"{row['blocks_appeared']:<18} {row['num_keys']:>15,} {pct:>11.2f}% {cumulative:>11.2f}%")

    if len(results) > 20:
        print(f"... and {len(results) - 20} more rows")

    # Summary stats
    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)
    print(f"Total unique (address, slot) keys: {total_keys:,}")
    print(f"Max blocks appeared: {results['blocks_appeared'].max():,}")

    single_block = results[results['blocks_appeared'] == 1]['num_keys'].sum()
    print(f"Keys appearing in only 1 block: {single_block:,} ({single_block / total_keys * 100:.1f}%)")

    # Percentile analysis
    cumsum = results['num_keys'].cumsum()
    for pct in [50, 90, 95, 99]:
        threshold = total_keys * pct / 100
        idx = (cumsum >= threshold).idxmax()
        print(f"Blocks appeared at {pct}th percentile: {results.loc[idx, 'blocks_appeared']:,}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
