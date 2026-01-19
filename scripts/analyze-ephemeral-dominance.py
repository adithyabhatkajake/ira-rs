#!/usr/bin/env python3
"""
Analyze ephemeral key dominance in EVM storage operations.

Outputs all numbers needed for the "Ephemeral Key Dominance" section:
- Key lifespan distribution (how many blocks each key appears in)
- Consecutive block overlap statistics
"""

import duckdb

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("EPHEMERAL KEY DOMINANCE ANALYSIS")
    print("=" * 70)

    # Get block count
    total_blocks = con.execute(f"""
        SELECT COUNT(DISTINCT block_number) FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()[0]
    print(f"\nTotal blocks with storage ops: {total_blocks:,}")

    # 1. Key Lifespan Distribution
    print("\n" + "-" * 70)
    print("1. KEY LIFESPAN DISTRIBUTION")
    print("-" * 70)

    lifespan_dist = con.execute(f"""
        WITH key_lifespans AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN blocks_appeared = 1 THEN '1 block'
                    WHEN blocks_appeared BETWEEN 2 AND 5 THEN '2--5 blocks'
                    WHEN blocks_appeared BETWEEN 6 AND 20 THEN '6--20 blocks'
                    WHEN blocks_appeared BETWEEN 21 AND 50 THEN '21--50 blocks'
                    ELSE '>50 blocks'
                END as bucket,
                CASE
                    WHEN blocks_appeared = 1 THEN 1
                    WHEN blocks_appeared BETWEEN 2 AND 5 THEN 2
                    WHEN blocks_appeared BETWEEN 6 AND 20 THEN 3
                    WHEN blocks_appeared BETWEEN 21 AND 50 THEN 4
                    ELSE 5
                END as sort_order
            FROM key_lifespans
        )
        SELECT
            bucket,
            COUNT(*) as keys,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as share_pct
        FROM bucketed
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """).fetchdf()

    total_keys = lifespan_dist['keys'].sum()

    print(f"\nTotal unique keys: {total_keys:,}")
    print(f"\n{'Blocks Appeared':<20} {'Keys':>15} {'Share':>10}")
    print("-" * 45)
    for _, row in lifespan_dist.iterrows():
        print(f"{row['bucket']:<20} {row['keys']:>15,} {row['share_pct']:>9.1f}%")

    # LaTeX table
    print("\n" + "-" * 70)
    print("LATEX TABLE")
    print("-" * 70)
    print("""
\\begin{table}[t]
\\centering
\\caption{Key lifespan distribution: number of blocks in which each key appears.}
\\label{tab:key-lifespan}
\\small
\\begin{tabular}{lrr}
\\toprule
\\textbf{Blocks Appeared} & \\textbf{Keys} & \\textbf{Share} \\\\
\\midrule""")

    for _, row in lifespan_dist.iterrows():
        bucket = row['bucket']
        if bucket == '>50 blocks':
            bucket = '$>$50 blocks'
        keys_fmt = f"${row['keys']:,}$".replace(",", "{,}")
        print(f"{bucket} & {keys_fmt} & ${row['share_pct']:.1f}\\%$ \\\\")

    print("""\\bottomrule
\\end{tabular}
\\end{table}
""")

    # 2. Consecutive Block Overlap
    print("-" * 70)
    print("2. CONSECUTIVE BLOCK OVERLAP")
    print("-" * 70)
    print("\nComputing consecutive block overlap using efficient window functions...")

    # Efficient approach using LAG() window function:
    # For each key's appearance in a block, check if it also appeared in the previous block
    # This avoids expensive O(n^2) joins between block pairs
    overlap_stats = con.execute(f"""
        WITH block_keys AS (
            SELECT DISTINCT block_number, target_address, storage_slot
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
        ),
        -- For each key appearance, find the previous block it appeared in
        keys_with_prev AS (
            SELECT
                block_number,
                target_address,
                storage_slot,
                LAG(block_number) OVER (
                    PARTITION BY target_address, storage_slot
                    ORDER BY block_number
                ) as prev_key_block
            FROM block_keys
        ),
        -- Get the previous block number for each block (to check consecutiveness)
        block_sequence AS (
            SELECT
                block_number,
                LAG(block_number) OVER (ORDER BY block_number) as prev_block_num
            FROM (SELECT DISTINCT block_number FROM block_keys)
        ),
        -- For each block, count total keys and keys that came from the immediately previous block
        block_overlap AS (
            SELECT
                k.block_number,
                COUNT(*) as keys_in_block,
                SUM(CASE WHEN k.prev_key_block = bs.prev_block_num THEN 1 ELSE 0 END) as overlap_keys
            FROM keys_with_prev k
            JOIN block_sequence bs ON k.block_number = bs.block_number
            WHERE bs.prev_block_num IS NOT NULL
            GROUP BY k.block_number
        )
        SELECT
            AVG(overlap_keys * 100.0 / NULLIF(keys_in_block, 0)) as avg_overlap_pct,
            MIN(overlap_keys * 100.0 / NULLIF(keys_in_block, 0)) as min_overlap_pct,
            MAX(overlap_keys * 100.0 / NULLIF(keys_in_block, 0)) as max_overlap_pct,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY overlap_keys * 100.0 / NULLIF(keys_in_block, 0)) as median_overlap_pct,
            COUNT(*) as blocks_analyzed
        FROM block_overlap
        WHERE keys_in_block > 0
    """).fetchone()

    avg_overlap, min_overlap, max_overlap, median_overlap, blocks_analyzed = overlap_stats

    print(f"\nBlocks analyzed: {blocks_analyzed:,}")
    print(f"\nConsecutive block overlap statistics:")
    print(f"  Average: {avg_overlap:.1f}%")
    print(f"  Median:  {median_overlap:.1f}%")
    print(f"  Min:     {min_overlap:.1f}%")
    print(f"  Max:     {max_overlap:.1f}%")

    print(f"\nLaTeX: {avg_overlap:.1f}\\% (range: {min_overlap:.1f}\\%--{max_overlap:.1f}\\%)")

    # Additional: Distribution of overlap percentages
    print("\n" + "-" * 70)
    print("OVERLAP DISTRIBUTION")
    print("-" * 70)

    overlap_dist = con.execute(f"""
        WITH block_keys AS (
            SELECT DISTINCT block_number, target_address, storage_slot
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
        ),
        keys_with_prev AS (
            SELECT
                block_number,
                target_address,
                storage_slot,
                LAG(block_number) OVER (
                    PARTITION BY target_address, storage_slot
                    ORDER BY block_number
                ) as prev_key_block
            FROM block_keys
        ),
        block_sequence AS (
            SELECT
                block_number,
                LAG(block_number) OVER (ORDER BY block_number) as prev_block_num
            FROM (SELECT DISTINCT block_number FROM block_keys)
        ),
        block_overlap AS (
            SELECT
                k.block_number,
                COUNT(*) as keys_in_block,
                SUM(CASE WHEN k.prev_key_block = bs.prev_block_num THEN 1 ELSE 0 END) as overlap_keys
            FROM keys_with_prev k
            JOIN block_sequence bs ON k.block_number = bs.block_number
            WHERE bs.prev_block_num IS NOT NULL
            GROUP BY k.block_number
        ),
        overlap_pcts AS (
            SELECT overlap_keys * 100.0 / NULLIF(keys_in_block, 0) as pct
            FROM block_overlap
            WHERE keys_in_block > 0
        )
        SELECT
            CASE
                WHEN pct < 5 THEN '<5%'
                WHEN pct < 10 THEN '5-10%'
                WHEN pct < 20 THEN '10-20%'
                WHEN pct < 30 THEN '20-30%'
                WHEN pct < 50 THEN '30-50%'
                ELSE '>=50%'
            END as bucket,
            CASE
                WHEN pct < 5 THEN 1
                WHEN pct < 10 THEN 2
                WHEN pct < 20 THEN 3
                WHEN pct < 30 THEN 4
                WHEN pct < 50 THEN 5
                ELSE 6
            END as sort_order,
            COUNT(*) as pairs
        FROM overlap_pcts
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """).fetchdf()

    print(f"\n{'Overlap Range':<15} {'Block Pairs':>15} {'Share':>10}")
    print("-" * 40)
    total_pairs_dist = overlap_dist['pairs'].sum()
    for _, row in overlap_dist.iterrows():
        share = row['pairs'] / total_pairs_dist * 100
        print(f"{row['bucket']:<15} {row['pairs']:>15,} {share:>9.1f}%")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY FOR WRITING")
    print("=" * 70)

    single_block_pct = lifespan_dist[lifespan_dist['bucket'] == '1 block']['share_pct'].values[0]

    print(f"""
Key lifespan:
- Single-block keys: {single_block_pct:.1f}% of all keys
- Total unique keys: {total_keys:,}

Consecutive block overlap:
- Average overlap: {avg_overlap:.1f}%
- Range: {min_overlap:.1f}% to {max_overlap:.1f}%

LaTeX snippets:
- "Despite high intra-block reuse, most keys are ephemeral---appearing in only one block."
- "{single_block_pct:.1f}\\% of keys appear in only 1 block"
- "Consecutive block overlap averages only {avg_overlap:.1f}\\% (range: {min_overlap:.1f}\\%--{max_overlap:.1f}\\%)"
""")

    print("=" * 70)


if __name__ == "__main__":
    main()
