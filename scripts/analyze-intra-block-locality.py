#!/usr/bin/env python3
"""
Analyze intra-block locality in EVM storage operations.

Outputs all numbers needed for the "High Intra-Block Locality" section:
- Global reuse factor (total ops / unique keys)
- Intra-block reuse factor (average per-block reuse)
- Distribution of per-key access counts within blocks
- Cache hit potential percentage
"""

import duckdb

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("INTRA-BLOCK LOCALITY ANALYSIS")
    print("=" * 70)

    # Get block count
    total_blocks = con.execute(f"""
        SELECT COUNT(DISTINCT block_number) FROM read_parquet('{DATA_PATH}')
    """).fetchone()[0]
    print(f"\nTotal blocks analyzed: {total_blocks:,}")

    # 1. Global Reuse Factor
    print("\n" + "-" * 70)
    print("1. GLOBAL REUSE FACTOR")
    print("-" * 70)

    global_stats = con.execute(f"""
        SELECT
            COUNT(*) as total_ops,
            COUNT(DISTINCT (target_address, storage_slot)) as unique_keys
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()

    total_ops, unique_keys = global_stats
    global_reuse = total_ops / unique_keys if unique_keys > 0 else 0

    print(f"\nTotal storage operations: {total_ops:,}")
    print(f"Unique storage keys:      {unique_keys:,}")
    print(f"Global reuse factor:      {global_reuse:.2f}x")

    # Per-block reuse factor statistics
    per_block_reuse = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                COUNT(*) as ops,
                COUNT(DISTINCT (target_address, storage_slot)) as unique_keys
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY block_number
        )
        SELECT
            MIN(ops * 1.0 / unique_keys) as min_reuse,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ops * 1.0 / unique_keys) as median_reuse,
            MAX(ops * 1.0 / unique_keys) as max_reuse
        FROM block_stats
        WHERE unique_keys > 0
    """).fetchone()

    min_reuse, median_reuse, max_reuse = per_block_reuse

    print(f"\nPer-block reuse factor distribution:")
    print(f"  Min:    {min_reuse:.2f}x")
    print(f"  Median: {median_reuse:.2f}x")
    print(f"  Max:    {max_reuse:.2f}x")

    print(f"\nLaTeX: {global_reuse:.2f}$\\times$ ({total_ops:,} operations across {unique_keys:,} unique keys)".replace(",", "{,}"))

    # 2. Intra-Block Reuse Factor
    print("\n" + "-" * 70)
    print("2. INTRA-BLOCK REUSE FACTOR")
    print("-" * 70)

    intra_block = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                COUNT(*) as ops,
                COUNT(DISTINCT (target_address, storage_slot)) as unique_keys
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY block_number
        )
        SELECT
            AVG(ops * 1.0 / unique_keys) as avg_reuse,
            MIN(ops * 1.0 / unique_keys) as min_reuse,
            MAX(ops * 1.0 / unique_keys) as max_reuse,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ops * 1.0 / unique_keys) as median_reuse
        FROM block_stats
        WHERE unique_keys > 0
    """).fetchone()

    avg_reuse, min_reuse, max_reuse, median_reuse = intra_block

    print(f"\nAverage intra-block reuse factor: {avg_reuse:.2f}x")
    print(f"Median intra-block reuse factor:  {median_reuse:.2f}x")
    print(f"Min:                              {min_reuse:.2f}x")
    print(f"Max:                              {max_reuse:.2f}x")
    print(f"\nLaTeX: {avg_reuse:.2f}$\\times$")

    # 3. Distribution Table
    print("\n" + "-" * 70)
    print("3. INTRA-BLOCK ACCESS DISTRIBUTION")
    print("-" * 70)

    distribution = con.execute(f"""
        WITH key_accesses AS (
            SELECT
                block_number,
                target_address,
                storage_slot,
                COUNT(*) as accesses
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY block_number, target_address, storage_slot
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN accesses = 1 THEN '1'
                    WHEN accesses = 2 THEN '2'
                    WHEN accesses BETWEEN 3 AND 5 THEN '3--5'
                    WHEN accesses BETWEEN 6 AND 10 THEN '6--10'
                    ELSE '>10'
                END as bucket,
                CASE
                    WHEN accesses = 1 THEN 1
                    WHEN accesses = 2 THEN 2
                    WHEN accesses BETWEEN 3 AND 5 THEN 3
                    WHEN accesses BETWEEN 6 AND 10 THEN 4
                    ELSE 5
                END as sort_order
            FROM key_accesses
        )
        SELECT
            bucket,
            COUNT(*) as pairs,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as share_pct
        FROM bucketed
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """).fetchdf()

    total_pairs = distribution['pairs'].sum()

    print(f"\n{'Accesses per Key':<20} {'Block-Key Pairs':>18} {'Share':>10}")
    print("-" * 48)
    for _, row in distribution.iterrows():
        print(f"{row['bucket']:<20} {row['pairs']:>18,} {row['share_pct']:>9.1f}%")
    print("-" * 48)
    print(f"{'Total':<20} {total_pairs:>18,}")

    # LaTeX table
    print("\n" + "-" * 70)
    print("LATEX TABLE")
    print("-" * 70)
    print("""
\\begin{table}[t]
\\centering
\\caption{Intra-block access distribution: how many times each key is accessed within its block.}
\\label{tab:intra-block}
\\small
\\begin{tabular}{lrr}
\\toprule
\\textbf{Accesses per Key} & \\textbf{Block-Key Pairs} & \\textbf{Share} \\\\
\\midrule""")

    for _, row in distribution.iterrows():
        bucket = row['bucket']
        if bucket == '>10':
            bucket = '$>$10'
        pairs_fmt = f"${row['pairs']:,}$".replace(",", "{,}")
        print(f"{bucket} & {pairs_fmt} & ${row['share_pct']:.1f}\\%$ \\\\")

    print("""\\bottomrule
\\end{tabular}
\\end{table}
""")

    # 4. Cache Hit Potential
    print("-" * 70)
    print("4. CACHE HIT POTENTIAL")
    print("-" * 70)

    # Percentage of accesses that are re-accesses (not first access to that key in block)
    cache_stats = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                COUNT(*) as total_accesses,
                COUNT(DISTINCT (target_address, storage_slot)) as unique_keys
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY block_number
        )
        SELECT
            SUM(total_accesses) as total,
            SUM(unique_keys) as first_accesses,
            SUM(total_accesses - unique_keys) as re_accesses
        FROM block_stats
    """).fetchone()

    total_accesses, first_accesses, re_accesses = cache_stats
    cache_hit_pct = (re_accesses / total_accesses * 100) if total_accesses > 0 else 0

    print(f"\nTotal storage accesses:     {total_accesses:,}")
    print(f"First accesses (cache miss): {first_accesses:,}")
    print(f"Re-accesses (cache hit):    {re_accesses:,}")
    print(f"Cache hit potential:        {cache_hit_pct:.0f}%")

    print(f"\nLaTeX: {cache_hit_pct:.0f}\\% of key accesses within a block are to keys already accessed earlier in that block.")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY FOR WRITING")
    print("=" * 70)
    print(f"""
Key numbers for the paragraph:
- Global reuse factor: {global_reuse:.2f}x
- Total storage ops: {total_ops:,}
- Unique keys: {unique_keys:,}
- Avg intra-block reuse factor: {avg_reuse:.2f}x
- Cache hit potential: {cache_hit_pct:.0f}%
- Single-access keys share: {distribution[distribution['bucket'] == '1']['share_pct'].values[0]:.1f}%
""")

    print("=" * 70)


if __name__ == "__main__":
    main()
