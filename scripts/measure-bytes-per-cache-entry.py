#!/usr/bin/env python3
"""
Measure bytes per cache entry.

Outputs a CSV with value sizes for different operation types:
- Storage operations (SLOAD/SSTORE): value is always 32 bytes (U256)
- Bytecode operations (EXTCODECOPY, CREATE, CREATE2): variable size from value_size field

The CSV contains one row per unique (op_type, value_size) combination with counts.
"""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("BYTES PER CACHE ENTRY ANALYSIS")
    print("=" * 70)

    # Get value size distribution
    # For storage ops (0, 1), value is always 32 bytes
    # For bytecode ops with value_size field, use that value

    print("\nQuerying value sizes...")

    # Query all operations with their effective value sizes
    results = con.execute(f"""
        SELECT
            op_type,
            CASE
                WHEN op_type IN (0, 1) THEN 32  -- SLOAD/SSTORE: U256 = 32 bytes
                WHEN op_type IN (2, 3) THEN 32  -- BALANCE/SELFBALANCE: U256 = 32 bytes
                WHEN op_type IN (4, 5) THEN 32  -- EXTCODESIZE/EXTCODEHASH: returns U256/H256
                WHEN op_type IN (6, 11, 12) THEN COALESCE(value_size, 0)  -- EXTCODECOPY, CREATE, CREATE2: variable
                WHEN op_type IN (7, 8, 9, 10) THEN 0  -- CALL ops: no value stored
                WHEN op_type = 13 THEN 0  -- SELFDESTRUCT: no value
                ELSE COALESCE(value_size, 0)
            END as value_bytes,
            COUNT(*) as count
        FROM read_parquet('{DATA_PATH}')
        GROUP BY op_type, value_bytes
        ORDER BY op_type, value_bytes
    """).fetchdf()

    # Map op_type to name
    op_names = {
        0: 'SLOAD', 1: 'SSTORE', 2: 'BALANCE', 3: 'SELFBALANCE',
        4: 'EXTCODESIZE', 5: 'EXTCODEHASH', 6: 'EXTCODECOPY',
        7: 'CALL', 8: 'STATICCALL', 9: 'DELEGATECALL', 10: 'CALLCODE',
        11: 'CREATE', 12: 'CREATE2', 13: 'SELFDESTRUCT'
    }

    results['op_name'] = results['op_type'].map(op_names)

    # Reorder columns
    results = results[['op_type', 'op_name', 'value_bytes', 'count']]

    # Save to CSV
    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.measure-bytes-per-cache-entry.csv"
    results.to_csv(csv_path, index=False)
    print(f"\nSaved to: {csv_path}")
    print(f"Total rows: {len(results):,}")

    # Print summary
    print("\n" + "-" * 70)
    print("SUMMARY BY OPERATION TYPE")
    print("-" * 70)

    summary = con.execute(f"""
        WITH sized AS (
            SELECT
                op_type,
                CASE
                    WHEN op_type IN (0, 1) THEN 32
                    WHEN op_type IN (2, 3) THEN 32
                    WHEN op_type IN (4, 5) THEN 32
                    WHEN op_type IN (6, 11, 12) THEN COALESCE(value_size, 0)
                    ELSE 0
                END as value_bytes
            FROM read_parquet('{DATA_PATH}')
        )
        SELECT
            op_type,
            COUNT(*) as count,
            MIN(value_bytes) as min_bytes,
            ROUND(AVG(value_bytes), 1) as avg_bytes,
            MAX(value_bytes) as max_bytes,
            SUM(value_bytes) as total_bytes
        FROM sized
        GROUP BY op_type
        ORDER BY op_type
    """).fetchdf()

    summary['op_name'] = summary['op_type'].map(op_names)

    print(f"\n{'Op':<15} {'Count':>14} {'Min':>8} {'Avg':>10} {'Max':>10} {'Total MB':>12}")
    print("-" * 69)
    for _, row in summary.iterrows():
        total_mb = row['total_bytes'] / (1024 * 1024)
        print(f"{row['op_name']:<15} {row['count']:>14,} {row['min_bytes']:>8} {row['avg_bytes']:>10.1f} {row['max_bytes']:>10} {total_mb:>12,.1f}")

    # Cache entry size calculation
    print("\n" + "-" * 70)
    print("CACHE ENTRY SIZE ESTIMATION")
    print("-" * 70)

    # For storage cache:
    # Key: address (20) + slot (32) = 52 bytes
    # Value: 32 bytes
    # Total: 84 bytes minimum (plus any hashmap overhead)

    storage_ops = summary[summary['op_type'].isin([0, 1])]['count'].sum()
    storage_bytes = storage_ops * 32  # value bytes only

    print(f"\nStorage cache entries:")
    print(f"  Key size: 52 bytes (20-byte address + 32-byte slot)")
    print(f"  Value size: 32 bytes (U256)")
    print(f"  Entry size: 84 bytes (key + value, no overhead)")
    print(f"  Total storage ops: {storage_ops:,}")
    print(f"  Total value bytes: {storage_bytes / (1024**3):.2f} GB")

    # For bytecode cache (EXTCODECOPY, CREATE, CREATE2)
    bytecode_stats = con.execute(f"""
        SELECT
            COUNT(*) as count,
            SUM(COALESCE(value_size, 0)) as total_bytes,
            AVG(COALESCE(value_size, 0)) as avg_bytes,
            MAX(COALESCE(value_size, 0)) as max_bytes
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (6, 11, 12)
    """).fetchone()

    print(f"\nBytecode cache entries (EXTCODECOPY, CREATE, CREATE2):")
    print(f"  Key size: 20 bytes (address only)")
    print(f"  Value size: variable (avg {bytecode_stats[2]:.0f} bytes, max {bytecode_stats[3]:,} bytes)")
    print(f"  Total ops: {bytecode_stats[0]:,}")
    print(f"  Total value bytes: {bytecode_stats[1] / (1024**2):.1f} MB")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
