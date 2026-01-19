#!/usr/bin/env python3
"""
Measure cache size if all keys accessed in each block were held in memory.

Outputs a CSV with block_number and cache_size_bytes.

Includes:
- Storage: key (20-byte address + 32-byte slot) + value (32 bytes)
- Bytecode: key (20-byte address) + value (variable, from value_size)
- Account state: key (20-byte address) + value (32 bytes for balance/hash)
"""

import duckdb
from datetime import date

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    con = duckdb.connect()

    # Configure for maximum performance
    con.execute("SET threads TO 8")
    con.execute("SET memory_limit = '8GB'")

    print("Measuring per-block cache size (all state accesses)...")

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.measure-all-keys-as-hint-cache-size.csv"

    # Calculate cache size for all state types:
    # 1. Storage (op_type 0,1): key = address(20) + slot(32), value = 32 bytes
    # 2. Bytecode (op_type 6,11,12): key = address(20), value = value_size
    # 3. Account state (op_type 2,3,4,5): key = address(20), value = 32 bytes
    con.execute(f"""
        COPY (
            WITH
            -- Storage: unique (address, slot) pairs per block
            storage_cache AS (
                SELECT
                    block_number,
                    SUM(52 + 32) as size_bytes  -- key(52) + value(32)
                FROM (
                    SELECT DISTINCT block_number, target_address, storage_slot
                    FROM read_parquet('{DATA_PATH}')
                    WHERE op_type IN (0, 1)
                )
                GROUP BY block_number
            ),
            -- Bytecode: unique addresses per block with their code size
            -- Includes CALL operations (7,8,9,10) which load bytecode
            bytecode_cache AS (
                SELECT
                    block_number,
                    SUM(20 + value_size) as size_bytes  -- key(20) + bytecode
                FROM (
                    SELECT block_number, target_address, MAX(COALESCE(value_size, 0)) as value_size
                    FROM read_parquet('{DATA_PATH}')
                    WHERE op_type IN (6, 7, 8, 9, 10, 11, 12)  -- EXTCODECOPY, CALL, STATICCALL, DELEGATECALL, CALLCODE, CREATE, CREATE2
                    GROUP BY block_number, target_address
                )
                GROUP BY block_number
            ),
            -- Account state: unique addresses per block (balance, codesize, codehash)
            account_cache AS (
                SELECT
                    block_number,
                    SUM(20 + 32) as size_bytes  -- key(20) + value(32)
                FROM (
                    SELECT DISTINCT block_number, target_address
                    FROM read_parquet('{DATA_PATH}')
                    WHERE op_type IN (2, 3, 4, 5)  -- BALANCE, SELFBALANCE, EXTCODESIZE, EXTCODEHASH
                )
                GROUP BY block_number
            ),
            -- Get all block numbers
            all_blocks AS (
                SELECT DISTINCT block_number FROM read_parquet('{DATA_PATH}')
            )
            SELECT
                b.block_number,
                COALESCE(s.size_bytes, 0) + COALESCE(bc.size_bytes, 0) + COALESCE(a.size_bytes, 0) as cache_size_bytes
            FROM all_blocks b
            LEFT JOIN storage_cache s ON b.block_number = s.block_number
            LEFT JOIN bytecode_cache bc ON b.block_number = bc.block_number
            LEFT JOIN account_cache a ON b.block_number = a.block_number
            ORDER BY b.block_number
        ) TO '{csv_path}' (HEADER, DELIMITER ',')
    """)

    # Get summary stats
    stats = con.execute(f"""
        SELECT
            COUNT(*) as num_blocks,
            MIN(cache_size_bytes) as min_size,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cache_size_bytes) as median_size,
            AVG(cache_size_bytes) as avg_size,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cache_size_bytes) as p95_size,
            MAX(cache_size_bytes) as max_size,
            SUM(cache_size_bytes) as total_size
        FROM read_csv('{csv_path}', types={{'cache_size_bytes': 'BIGINT'}})
    """).fetchone()

    num_blocks, min_size, median_size, avg_size, p95_size, max_size, total_size = stats

    print(f"\nSaved to: {csv_path}")
    print(f"Total blocks: {num_blocks:,}")

    print("\n" + "=" * 50)
    print("CACHE SIZE STATISTICS (per block)")
    print("=" * 50)
    print(f"  Min:    {min_size:>12,} bytes ({min_size/1024:>8.1f} KB)")
    print(f"  Median: {median_size:>12,.0f} bytes ({median_size/1024:>8.1f} KB)")
    print(f"  Avg:    {avg_size:>12,.0f} bytes ({avg_size/1024:>8.1f} KB)")
    print(f"  P95:    {p95_size:>12,.0f} bytes ({p95_size/1024:>8.1f} KB)")
    print(f"  Max:    {max_size:>12,} bytes ({max_size/1024:>8.1f} KB)")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
