#!/usr/bin/env python3
"""Generate per-block operation distribution from parquet trace data."""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("PER-BLOCK OPERATION DISTRIBUTION")
    print("=" * 70)
    print(f"\nReading from: {DATA_PATH}")

    # Pivot to get per-block counts for each op type
    results = con.execute(f"""
        SELECT
            block_number,
            COUNT(*) FILTER (WHERE op_type = 0) as sload,
            COUNT(*) FILTER (WHERE op_type = 1) as sstore,
            COUNT(*) FILTER (WHERE op_type = 2) as balance,
            COUNT(*) FILTER (WHERE op_type = 3) as selfbalance,
            COUNT(*) FILTER (WHERE op_type = 4) as extcodesize,
            COUNT(*) FILTER (WHERE op_type = 5) as extcodehash,
            COUNT(*) FILTER (WHERE op_type = 6) as extcodecopy,
            COUNT(*) FILTER (WHERE op_type = 7) as call,
            COUNT(*) FILTER (WHERE op_type = 8) as staticcall,
            COUNT(*) FILTER (WHERE op_type = 9) as delegatecall,
            COUNT(*) FILTER (WHERE op_type = 10) as callcode,
            COUNT(*) FILTER (WHERE op_type = 11) as create,
            COUNT(*) FILTER (WHERE op_type = 12) as create2,
            COUNT(*) FILTER (WHERE op_type = 13) as selfdestruct
        FROM read_parquet('{DATA_PATH}')
        GROUP BY block_number
        ORDER BY block_number
    """).fetchdf()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.per-block-op-distribution.csv"
    results.to_csv(csv_path, index=False)

    print(f"\nSaved to: {csv_path}")
    print(f"Total blocks: {len(results):,}")

    # Print summary statistics
    print("\n" + "-" * 70)
    print("SUMMARY (total ops across all blocks)")
    print("-" * 70)

    op_cols = ['sload', 'sstore', 'balance', 'selfbalance', 'extcodesize',
               'extcodehash', 'extcodecopy', 'call', 'staticcall',
               'delegatecall', 'callcode', 'create', 'create2', 'selfdestruct']

    for col in op_cols:
        total = results[col].sum()
        avg = results[col].mean()
        print(f"  {col.upper():<14}: {total:>14,} total, {avg:>10,.1f} avg/block")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
