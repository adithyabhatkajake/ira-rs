#!/usr/bin/env python3
"""Generate contract-level access concentration from parquet trace data.

For each unique contract address, count total storage operations (SLOAD + SSTORE),
sorted by total_ops descending with cumulative share.
"""

import os
import duckdb
from datetime import date

DATA_PATH = os.environ.get("IRA_TRACES", "/Volumes/X/ira-new-analysis/*.parquet")
OUTPUT_DIR = os.environ.get("IRA_OUTPUT", "data")


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("CONTRACT-LEVEL ACCESS CONCENTRATION")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    print("\nCalculating contract access counts...")

    results = con.execute(f"""
        WITH contract_ops AS (
            SELECT
                target_address as contract_address,
                COUNT(*) as total_ops
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)  -- SLOAD and SSTORE only
            GROUP BY target_address
            ORDER BY total_ops DESC
        ),
        with_total AS (
            SELECT
                *,
                SUM(total_ops) OVER () as grand_total
            FROM contract_ops
        )
        SELECT
            contract_address,
            total_ops,
            ROUND(100.0 * SUM(total_ops) OVER (ORDER BY total_ops DESC) / grand_total, 2) as cumulative_share
        FROM with_total
        ORDER BY total_ops DESC
    """).fetchdf()

    # Convert contract_address bytes to hex string
    results['contract_address'] = results['contract_address'].apply(
        lambda x: '0x' + x.hex() if isinstance(x, (bytes, bytearray)) else x
    )

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.contract-access-concentration.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total unique contracts: {len(results):,}")

    # Print top contracts
    print("\n" + "-" * 70)
    print("TOP 20 CONTRACTS BY STORAGE OPERATIONS")
    print("-" * 70)

    total_ops = results['total_ops'].sum()
    print(f"{'Rank':<6} {'Contract':<44} {'Ops':>14} {'Cum%':>8}")
    print("-" * 72)

    for i, row in results.head(20).iterrows():
        print(f"{i+1:<6} {row['contract_address']:<44} {row['total_ops']:>14,} {row['cumulative_share']:>7.2f}%")

    # Summary stats
    print("\n" + "-" * 70)
    print("CONCENTRATION SUMMARY")
    print("-" * 70)
    print(f"Total storage ops: {total_ops:,}")
    print(f"Total unique contracts: {len(results):,}")

    # Find how many contracts account for 50%, 80%, 90% of ops
    for threshold in [50, 80, 90, 95, 99]:
        n_contracts = len(results[results['cumulative_share'] <= threshold]) + 1
        print(f"Contracts for {threshold}% of ops: {n_contracts:,} ({n_contracts/len(results)*100:.2f}%)")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
