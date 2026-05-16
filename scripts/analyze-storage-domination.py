#!/usr/bin/env python3
"""
Analyze storage domination in EVM state operations.

Outputs all numbers needed for the "Storage Dominates I/O" section:
- Operation distribution by category (storage, calls, account metadata, creation)
- Read-write ratio for storage operations
- Bytecode I/O estimates per block
"""

import os

import duckdb

DATA_PATH = os.environ.get("IRA_TRACES", "/Volumes/X/ira-new-analysis/*.parquet")


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("STORAGE DOMINATION ANALYSIS")
    print("=" * 70)

    # Get total blocks for per-block calculations
    total_blocks = con.execute(f"""
        SELECT COUNT(DISTINCT block_number) as blocks
        FROM read_parquet('{DATA_PATH}')
    """).fetchone()[0]
    print(f"\nTotal blocks analyzed: {total_blocks:,}")

    # Category breakdown
    # Storage: SLOAD (0), SSTORE (1)
    # Calls (bytecode load): CALL (7), STATICCALL (8), DELEGATECALL (9), CALLCODE (10), EXTCODESIZE (4), EXTCODEHASH (5), EXTCODECOPY (6)
    # Account metadata: BALANCE (2), SELFBALANCE (3)
    # Creation/destruction: CREATE (11), CREATE2 (12), SELFDESTRUCT (13)

    print("\n" + "-" * 70)
    print("OPERATION DISTRIBUTION BY CATEGORY")
    print("-" * 70)

    categories = con.execute(f"""
        WITH categorized AS (
            SELECT
                CASE
                    WHEN op_type IN (0, 1) THEN 'Storage (SLOAD/SSTORE)'
                    WHEN op_type IN (4, 5, 6, 7, 8, 9, 10) THEN 'Calls (bytecode load)'
                    WHEN op_type IN (2, 3) THEN 'Account metadata'
                    WHEN op_type IN (11, 12, 13) THEN 'Creation/destruction'
                END as category,
                op_type
            FROM read_parquet('{DATA_PATH}')
        )
        SELECT
            category,
            COUNT(*) as operations,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as share_pct
        FROM categorized
        GROUP BY category
        ORDER BY operations DESC
    """).fetchdf()

    total_ops = categories['operations'].sum()

    print(f"\n{'Category':<30} {'Operations':>15} {'Share':>10}")
    print("-" * 55)
    for _, row in categories.iterrows():
        print(f"{row['category']:<30} {row['operations']:>15,} {row['share_pct']:>9.1f}%")
    print("-" * 55)
    print(f"{'Total':<30} {total_ops:>15,} {'100.0':>9}%")

    # LaTeX table format
    print("\n" + "-" * 70)
    print("LATEX TABLE FORMAT")
    print("-" * 70)
    print("""
\\begin{table}[t]
\\centering
\\caption{State operation distribution across XXX blocks.}
\\label{tab:op-distribution}
\\small
\\begin{tabular}{lrr}
\\toprule
\\textbf{Category} & \\textbf{Operations} & \\textbf{Share} \\\\
\\midrule""")

    for _, row in categories.iterrows():
        ops_formatted = f"${row['operations']:,}$".replace(",", "{,}")
        print(f"{row['category']} & {ops_formatted} & ${row['share_pct']:.1f}\\%$ \\\\")

    print(f"""\\midrule
\\textbf{{Total}} & ${total_ops:,}$ & 100\\% \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}
""".replace(",", "{,}"))

    # Storage read-write breakdown
    print("-" * 70)
    print("STORAGE READ-WRITE RATIO")
    print("-" * 70)

    rw = con.execute(f"""
        SELECT
            SUM(CASE WHEN op_type = 0 THEN 1 ELSE 0 END) as sloads,
            SUM(CASE WHEN op_type = 1 THEN 1 ELSE 0 END) as sstores
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()

    sloads, sstores = rw
    ratio = sloads / sstores if sstores > 0 else 0

    print(f"\nSLOADs:  {sloads:>15,}")
    print(f"SSTOREs: {sstores:>15,}")
    print(f"Ratio:   {ratio:>15.1f}:1")
    print(f"\nLaTeX: {ratio:.1f}:1 ({sloads:,} \\texttt{{SLOAD}}s vs.\\ {sstores:,} \\texttt{{SSTORE}}s)".replace(",", "{,}"))

    # Bytecode I/O estimate
    print("\n" + "-" * 70)
    print("BYTECODE I/O ESTIMATE")
    print("-" * 70)

    # EXTCODECOPY has value_size field
    bytecode_stats = con.execute(f"""
        SELECT
            COUNT(*) as extcodecopy_ops,
            SUM(COALESCE(value_size, 0)) as total_bytes_copied,
            AVG(COALESCE(value_size, 0)) as avg_bytes_per_copy
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type = 6
    """).fetchone()

    extcodecopy_ops, total_bytes, avg_bytes = bytecode_stats
    bytes_per_block = total_bytes / total_blocks if total_blocks > 0 else 0

    print(f"\nEXTCODECOPY operations: {extcodecopy_ops:,}")
    print(f"Total bytes copied:    {total_bytes:,}")
    print(f"Avg bytes per copy:    {avg_bytes:.1f}")
    print(f"Bytes per block:       {bytes_per_block:.1f} ({bytes_per_block/1024:.1f} KB/block)")

    # Call operations don't directly load bytecode (it's cached), but we can estimate
    call_ops = con.execute(f"""
        SELECT COUNT(*) FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (7, 8, 9, 10)
    """).fetchone()[0]

    unique_call_targets = con.execute(f"""
        SELECT COUNT(DISTINCT target_address) FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (7, 8, 9, 10)
    """).fetchone()[0]

    print(f"\nCall operations (CALL/STATIC/DELEGATE/CALLCODE): {call_ops:,}")
    print(f"Unique call targets: {unique_call_targets:,}")
    print(f"Calls per unique target: {call_ops/unique_call_targets:.1f}x (bytecode cached after first load)")

    # Per-block summary
    print("\n" + "-" * 70)
    print("PER-BLOCK AVERAGES")
    print("-" * 70)

    per_block = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                SUM(CASE WHEN op_type IN (0, 1) THEN 1 ELSE 0 END) as storage_ops,
                SUM(CASE WHEN op_type IN (4, 5, 6, 7, 8, 9, 10) THEN 1 ELSE 0 END) as call_ops,
                SUM(CASE WHEN op_type IN (2, 3) THEN 1 ELSE 0 END) as account_ops,
                SUM(CASE WHEN op_type IN (11, 12, 13) THEN 1 ELSE 0 END) as create_ops,
                COUNT(*) as total_ops
            FROM read_parquet('{DATA_PATH}')
            GROUP BY block_number
        )
        SELECT
            ROUND(AVG(storage_ops), 1) as avg_storage,
            ROUND(AVG(call_ops), 1) as avg_calls,
            ROUND(AVG(account_ops), 1) as avg_account,
            ROUND(AVG(create_ops), 1) as avg_create,
            ROUND(AVG(total_ops), 1) as avg_total
        FROM block_stats
    """).fetchone()

    print(f"\nAvg storage ops/block:  {per_block[0]:,.1f}")
    print(f"Avg call ops/block:     {per_block[1]:,.1f}")
    print(f"Avg account ops/block:  {per_block[2]:,.1f}")
    print(f"Avg create ops/block:   {per_block[3]:,.1f}")
    print(f"Avg total ops/block:    {per_block[4]:,.1f}")

    # Summary for writing
    print("\n" + "=" * 70)
    print("SUMMARY FOR WRITING")
    print("=" * 70)

    storage_share = categories[categories['category'] == 'Storage (SLOAD/SSTORE)']['share_pct'].values[0]
    calls_share = categories[categories['category'] == 'Calls (bytecode load)']['share_pct'].values[0]
    account_share = categories[categories['category'] == 'Account metadata']['share_pct'].values[0]

    print(f"""
Key numbers for the paragraph:
- Storage operations share: {storage_share:.0f}% of all state accesses
- Read-write ratio: {ratio:.1f}:1
- SLOADs: {sloads:,}
- SSTOREs: {sstores:,}
- Bytecode I/O per block: ~{bytes_per_block/1024:.0f} KB/block
- Call operations share: {calls_share:.1f}%
- Account metadata share: {account_share:.1f}%
- Total blocks: {total_blocks:,}
- Total operations: {total_ops:,}
""")

    print("=" * 70)


if __name__ == "__main__":
    main()
