#!/usr/bin/env python3
"""
Analyze two-tier access pattern for the summary section.

Outputs data for:
1. Persistent hot keys - keys appearing in many blocks, their % of accesses
2. Ephemeral keys - keys appearing in only one block, their intra-block reuse
"""

import duckdb

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("TWO-TIER ACCESS PATTERN ANALYSIS")
    print("=" * 70)

    # First get total stats
    totals = con.execute(f"""
        SELECT
            COUNT(*) as total_ops,
            COUNT(DISTINCT (target_address, storage_slot)) as total_keys
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()
    total_ops, total_keys = totals

    print(f"\nTotal storage operations: {total_ops:,}")
    print(f"Total unique keys: {total_keys:,}")

    # Analyze keys by lifespan (number of blocks they appear in)
    print("\n" + "-" * 70)
    print("KEY LIFESPAN VS ACCESS SHARE")
    print("-" * 70)

    lifespan_stats = con.execute(f"""
        WITH key_stats AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(*) as total_accesses,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        )
        SELECT
            CASE
                WHEN blocks_appeared = 1 THEN '1 block (ephemeral)'
                WHEN blocks_appeared BETWEEN 2 AND 10 THEN '2-10 blocks'
                WHEN blocks_appeared BETWEEN 11 AND 100 THEN '11-100 blocks'
                WHEN blocks_appeared BETWEEN 101 AND 1000 THEN '101-1K blocks'
                ELSE '>1K blocks (persistent)'
            END as lifespan,
            CASE
                WHEN blocks_appeared = 1 THEN 1
                WHEN blocks_appeared BETWEEN 2 AND 10 THEN 2
                WHEN blocks_appeared BETWEEN 11 AND 100 THEN 3
                WHEN blocks_appeared BETWEEN 101 AND 1000 THEN 4
                ELSE 5
            END as sort_order,
            COUNT(*) as num_keys,
            SUM(total_accesses) as total_accesses,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct_keys,
            ROUND(SUM(total_accesses) * 100.0 / SUM(SUM(total_accesses)) OVER(), 1) as pct_accesses
        FROM key_stats
        GROUP BY lifespan, sort_order
        ORDER BY sort_order
    """).fetchdf()

    print(f"\n{'Lifespan':<25} {'Keys':>12} {'% Keys':>10} {'Accesses':>14} {'% Accesses':>12}")
    print("-" * 73)
    for _, row in lifespan_stats.iterrows():
        print(f"{row['lifespan']:<25} {row['num_keys']:>12,} {row['pct_keys']:>9.1f}% {row['total_accesses']:>14,} {row['pct_accesses']:>11.1f}%")

    # Extract specific numbers for the text
    ephemeral = lifespan_stats[lifespan_stats['lifespan'] == '1 block (ephemeral)'].iloc[0]
    persistent = lifespan_stats[lifespan_stats['lifespan'] == '>1K blocks (persistent)'].iloc[0]

    print("\n" + "-" * 70)
    print("TIER 1: PERSISTENT HOT KEYS (>1K blocks)")
    print("-" * 70)

    print(f"\nKeys appearing in >1,000 blocks:")
    print(f"  Number of keys: {persistent['num_keys']:,} ({persistent['pct_keys']:.1f}% of all keys)")
    print(f"  Total accesses: {persistent['total_accesses']:,} ({persistent['pct_accesses']:.1f}% of all accesses)")

    # Get more detail on persistent keys with different thresholds
    persistent_thresholds = con.execute(f"""
        WITH key_stats AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(*) as total_accesses,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        )
        SELECT
            threshold,
            COUNT(*) as num_keys,
            SUM(total_accesses) as total_accesses,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM key_stats), 2) as pct_keys,
            ROUND(SUM(total_accesses) * 100.0 / (SELECT SUM(total_accesses) FROM key_stats), 1) as pct_accesses
        FROM key_stats, (SELECT unnest([50, 100, 500, 1000, 5000, 10000]) as threshold) t
        WHERE blocks_appeared >= threshold
        GROUP BY threshold
        ORDER BY threshold
    """).fetchdf()

    print(f"\nPersistent keys at different thresholds:")
    print(f"{'Threshold':<15} {'Keys':>12} {'% Keys':>10} {'% Accesses':>12}")
    print("-" * 49)
    for _, row in persistent_thresholds.iterrows():
        print(f">={row['threshold']:<14} {row['num_keys']:>12,} {row['pct_keys']:>9.2f}% {row['pct_accesses']:>11.1f}%")

    print("\n" + "-" * 70)
    print("TIER 2: EPHEMERAL KEYS (1 block only)")
    print("-" * 70)

    print(f"\nKeys appearing in exactly 1 block:")
    print(f"  Number of keys: {ephemeral['num_keys']:,} ({ephemeral['pct_keys']:.1f}% of all keys)")
    print(f"  Total accesses: {ephemeral['total_accesses']:,} ({ephemeral['pct_accesses']:.1f}% of all accesses)")

    # Intra-block reuse for ephemeral keys
    ephemeral_reuse = con.execute(f"""
        WITH key_stats AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(*) as total_accesses,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        ),
        ephemeral_keys AS (
            SELECT target_address, storage_slot, total_accesses
            FROM key_stats
            WHERE blocks_appeared = 1
        )
        SELECT
            COUNT(*) as num_keys,
            SUM(total_accesses) as total_accesses,
            SUM(CASE WHEN total_accesses > 1 THEN 1 ELSE 0 END) as keys_with_reuse,
            SUM(CASE WHEN total_accesses > 1 THEN total_accesses - 1 ELSE 0 END) as reuse_accesses,
            AVG(total_accesses) as avg_accesses_per_key
        FROM ephemeral_keys
    """).fetchone()

    eph_keys, eph_accesses, keys_with_reuse, reuse_accesses, avg_accesses = ephemeral_reuse

    # Intra-block reuse rate = (accesses - unique keys) / accesses
    # For ephemeral keys, each key appears in 1 block, so intra-block reuse = (accesses - keys) / accesses
    intra_block_reuse_pct = (eph_accesses - eph_keys) / eph_accesses * 100

    print(f"\nIntra-block reuse for ephemeral keys:")
    print(f"  Total accesses to ephemeral keys: {eph_accesses:,}")
    print(f"  First accesses (unique): {eph_keys:,}")
    print(f"  Repeat accesses: {eph_accesses - eph_keys:,}")
    print(f"  Intra-block reuse rate: {intra_block_reuse_pct:.1f}%")
    print(f"  Avg accesses per ephemeral key: {avg_accesses:.2f}x")
    print(f"  Keys accessed >1 time: {keys_with_reuse:,} ({keys_with_reuse/eph_keys*100:.1f}%)")

    # Summary for paper
    print("\n" + "=" * 70)
    print("SUMMARY FOR PAPER")
    print("=" * 70)

    # Find a good threshold for "persistent" - maybe >100 blocks
    persistent_100 = persistent_thresholds[persistent_thresholds['threshold'] == 100].iloc[0]
    persistent_1000 = persistent_thresholds[persistent_thresholds['threshold'] == 1000].iloc[0]

    print(f"""
TIER 1 - Persistent Hot Keys:
- Keys appearing in >100 blocks: {persistent_100['pct_keys']:.1f}% of keys, {persistent_100['pct_accesses']:.0f}% of accesses
- Keys appearing in >1,000 blocks: {persistent_1000['pct_keys']:.2f}% of keys, {persistent_1000['pct_accesses']:.0f}% of accesses

TIER 2 - Ephemeral Keys:
- Keys appearing in only 1 block: {ephemeral['pct_keys']:.0f}% of all keys
- Intra-block reuse rate: {intra_block_reuse_pct:.0f}%

Fill in the blanks:
- "these keys account for ???% of accesses" → {persistent_100['pct_accesses']:.0f}% (for >100 block keys) or {persistent_1000['pct_accesses']:.0f}% (for >1K block keys)
- "The majority of keys (???%)" → {ephemeral['pct_keys']:.0f}%
- "high intra-block reuse (???%)" → {intra_block_reuse_pct:.0f}%
""")

    # Additional: What if we use different definitions
    print("-" * 70)
    print("ALTERNATIVE THRESHOLDS")
    print("-" * 70)

    # Keys appearing in >50% of blocks (very persistent)
    blocks_analyzed = con.execute(f"""
        SELECT COUNT(DISTINCT block_number) FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()[0]

    print(f"\nTotal blocks: {blocks_analyzed:,}")

    very_persistent = con.execute(f"""
        WITH key_stats AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(*) as total_accesses,
                COUNT(DISTINCT block_number) as blocks_appeared
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        )
        SELECT
            COUNT(*) as num_keys,
            SUM(total_accesses) as total_accesses,
            ROUND(SUM(total_accesses) * 100.0 / (SELECT SUM(total_accesses) FROM key_stats), 1) as pct_accesses
        FROM key_stats
        WHERE blocks_appeared >= {blocks_analyzed} * 0.5
    """).fetchone()

    print(f"\nKeys in >50% of blocks ({blocks_analyzed//2:,}+ blocks):")
    print(f"  Keys: {very_persistent[0]:,}")
    print(f"  % of accesses: {very_persistent[2]:.1f}%")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
