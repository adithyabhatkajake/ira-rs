#!/usr/bin/env python3
"""
Analyze bounded working set in EVM storage operations.

Outputs all numbers needed for the "Bounded Working Set" section:
- Per-block statistics (total ops, storage ops, unique keys)
- Working set size calculations
"""

import duckdb

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("BOUNDED WORKING SET ANALYSIS")
    print("=" * 70)

    # Per-block statistics
    print("\n" + "-" * 70)
    print("PER-BLOCK STATISTICS")
    print("-" * 70)

    stats = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                COUNT(*) as total_ops,
                SUM(CASE WHEN op_type IN (0, 1) THEN 1 ELSE 0 END) as storage_ops,
                COUNT(DISTINCT CASE WHEN op_type IN (0, 1) THEN (target_address, storage_slot) END) as unique_keys
            FROM read_parquet('{DATA_PATH}')
            GROUP BY block_number
        )
        SELECT
            -- Total operations
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_ops) as total_ops_median,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_ops) as total_ops_p95,
            MAX(total_ops) as total_ops_max,

            -- Storage operations
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY storage_ops) as storage_ops_median,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY storage_ops) as storage_ops_p95,
            MAX(storage_ops) as storage_ops_max,

            -- Unique storage keys
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY unique_keys) as unique_keys_median,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY unique_keys) as unique_keys_p95,
            MAX(unique_keys) as unique_keys_max,

            -- Additional stats
            AVG(unique_keys) as unique_keys_avg,
            MIN(unique_keys) as unique_keys_min,
            COUNT(*) as total_blocks
        FROM block_stats
    """).fetchone()

    (total_ops_median, total_ops_p95, total_ops_max,
     storage_ops_median, storage_ops_p95, storage_ops_max,
     unique_keys_median, unique_keys_p95, unique_keys_max,
     unique_keys_avg, unique_keys_min, total_blocks) = stats

    print(f"\nBlocks analyzed: {total_blocks:,}")

    print(f"\n{'Metric':<25} {'Median':>12} {'P95':>12} {'Max':>12}")
    print("-" * 61)
    print(f"{'Total operations':<25} {total_ops_median:>12,.0f} {total_ops_p95:>12,.0f} {total_ops_max:>12,}")
    print(f"{'Storage operations':<25} {storage_ops_median:>12,.0f} {storage_ops_p95:>12,.0f} {storage_ops_max:>12,}")
    print(f"{'Unique storage keys':<25} {unique_keys_median:>12,.0f} {unique_keys_p95:>12,.0f} {unique_keys_max:>12,}")

    print(f"\nAdditional unique keys stats:")
    print(f"  Min: {unique_keys_min:,.0f}")
    print(f"  Avg: {unique_keys_avg:,.0f}")

    # LaTeX table
    print("\n" + "-" * 70)
    print("LATEX TABLE: PER-BLOCK STATISTICS")
    print("-" * 70)
    print(f"""
\\begin{{table}}[t]
\\centering
\\caption{{Per-block storage statistics.}}
\\label{{tab:per-block}}
\\small
\\begin{{tabular}}{{lrrr}}
\\toprule
\\textbf{{Metric}} & \\textbf{{Median}} & \\textbf{{P95}} & \\textbf{{Max}} \\\\
\\midrule
Total operations & {total_ops_median:,.0f} & {total_ops_p95:,.0f} & {total_ops_max:,} \\\\
Storage operations & {storage_ops_median:,.0f} & {storage_ops_p95:,.0f} & {storage_ops_max:,} \\\\
Unique storage keys & {unique_keys_median:,.0f} & {unique_keys_p95:,.0f} & {unique_keys_max:,} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}
""")

    # Working set size calculations
    print("-" * 70)
    print("WORKING SET SIZE CALCULATIONS")
    print("-" * 70)

    key_size = 52  # 20 bytes address + 32 bytes slot
    median_keys = unique_keys_median
    p95_keys = unique_keys_p95

    median_size_bytes = median_keys * key_size
    median_size_kb = median_size_bytes / 1024

    p95_size_bytes = p95_keys * key_size
    p95_size_kb = p95_size_bytes / 1024

    print(f"\nKey size: {key_size} bytes (20-byte address + 32-byte slot)")
    print(f"\nMedian working set ({median_keys:,.0f} keys):")
    print(f"  Uncompressed: {median_size_bytes:,.0f} bytes ({median_size_kb:,.1f} KB)")

    print(f"\nP95 working set ({p95_keys:,.0f} keys):")
    print(f"  Uncompressed: {p95_size_bytes:,.0f} bytes ({p95_size_kb:,.1f} KB)")

    # Distribution of unique keys per block
    print("\n" + "-" * 70)
    print("UNIQUE KEYS DISTRIBUTION")
    print("-" * 70)

    dist = con.execute(f"""
        WITH block_stats AS (
            SELECT
                block_number,
                COUNT(DISTINCT CASE WHEN op_type IN (0, 1) THEN (target_address, storage_slot) END) as unique_keys
            FROM read_parquet('{DATA_PATH}')
            GROUP BY block_number
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN unique_keys < 500 THEN '<500'
                    WHEN unique_keys < 1000 THEN '500-1K'
                    WHEN unique_keys < 2000 THEN '1K-2K'
                    WHEN unique_keys < 3000 THEN '2K-3K'
                    WHEN unique_keys < 5000 THEN '3K-5K'
                    ELSE '>=5K'
                END as bucket,
                CASE
                    WHEN unique_keys < 500 THEN 1
                    WHEN unique_keys < 1000 THEN 2
                    WHEN unique_keys < 2000 THEN 3
                    WHEN unique_keys < 3000 THEN 4
                    WHEN unique_keys < 5000 THEN 5
                    ELSE 6
                END as sort_order
            FROM block_stats
        )
        SELECT
            bucket,
            COUNT(*) as blocks,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
        FROM bucketed
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """).fetchdf()

    print(f"\n{'Unique Keys':<15} {'Blocks':>12} {'Share':>10}")
    print("-" * 37)
    for _, row in dist.iterrows():
        print(f"{row['bucket']:<15} {row['blocks']:>12,} {row['pct']:>9.1f}%")

    # Calculate cumulative percentages for the paragraph
    cumul = 0
    cumul_2k = 0
    cumul_3k = 0
    for _, row in dist.iterrows():
        cumul += row['pct']
        if row['bucket'] in ['<500', '500-1K', '1K-2K']:
            cumul_2k += row['pct']
        if row['bucket'] in ['<500', '500-1K', '1K-2K', '2K-3K']:
            cumul_3k += row['pct']

    pct_under_2k = cumul_2k
    pct_under_3k = cumul_3k
    pct_over_5k = dist[dist['bucket'] == '>=5K']['pct'].values[0]

    # LaTeX table for distribution
    print("\n" + "-" * 70)
    print("LATEX TABLE: UNIQUE KEY DISTRIBUTION")
    print("-" * 70)
    print("""
\\begin{table}[t]
\\centering
\\caption{Distribution of unique storage keys accessed per block.}
\\label{tab:key-dist}
\\small
\\begin{tabular}{lrr}
\\toprule
\\textbf{Unique Keys} & \\textbf{Blocks} & \\textbf{Share} \\\\
\\midrule""")

    for _, row in dist.iterrows():
        bucket = row['bucket']
        if bucket == '>=5K':
            bucket = '$\\geq$5K'
        print(f"{bucket} & {row['blocks']:,} & {row['pct']:.1f}\\% \\\\")

    print("""\\bottomrule
\\end{tabular}
\\end{table}
""")

    # Suggested paragraph
    print("-" * 70)
    print("SUGGESTED PARAGRAPH")
    print("-" * 70)
    print(f"""
\\Cref{{tab:key-dist}} shows the distribution of unique storage keys per block.
The majority of blocks ({pct_under_2k:.0f}\\%) access fewer than 2,000 unique keys,
and {pct_under_3k:.0f}\\% access fewer than 3,000. Only {pct_over_5k:.1f}\\% of blocks
exceed 5,000 unique keys. This tight distribution suggests that a fixed-size
hint buffer of 2,000--3,000 keys would cover the vast majority of blocks,
making per-block prefetching hints both practical and efficient.
""")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY FOR WRITING")
    print("=" * 70)

    print(f"""
Per-block statistics:
- Median unique storage keys: {unique_keys_median:,.0f}
- P95 unique storage keys: {unique_keys_p95:,.0f}
- Max unique storage keys: {unique_keys_max:,}

Working set size:
- Median: {median_keys:,.0f} keys = {median_size_kb:,.0f} KB uncompressed
- P95: {p95_keys:,.0f} keys = {p95_size_kb:,.0f} KB uncompressed

LaTeX snippets:
- "The median block accesses {unique_keys_median:,.0f} unique storage keys, with the 95th percentile at {unique_keys_p95:,.0f} keys."
- "hinting {int(round(median_keys/1000)*1000):,} keys requires at most {int(round(median_keys/1000)*1000 * 52 / 1024):,}~KB uncompressed"
""")

    print("=" * 70)


if __name__ == "__main__":
    main()
