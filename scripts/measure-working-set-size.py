#!/usr/bin/env python3
"""
Measure hint key sizes and compression performance for every block.

For each block, measures:
- Raw size of all unique keys (storage keys + bytecode keys + account keys)
- Compressed size using zstd
- Compression time
- Decompression time

Keys are:
- Storage: address (20 bytes) + slot (32 bytes) = 52 bytes per key
- Bytecode: address (20 bytes) per unique called contract
- Account: address (20 bytes) per unique account accessed

Outputs CSV with one row per block.
"""

import duckdb
import zstandard as zstd
import time
from datetime import date
import csv
from collections import defaultdict

DATA_PATH = "/Volumes/X/ira-new-analysis/*.parquet"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"


def main():
    total_start_time = time.time()

    con = duckdb.connect()
    con.execute("SET threads TO 8")
    con.execute("SET memory_limit = '8GB'")

    print("=" * 70)
    print("PHASE 1: Fetching unique keys from parquet files")
    print("=" * 70)

    # Fetch all data in one go for efficiency
    # Storage keys
    phase_start = time.time()
    print("  [1/3] Fetching storage keys...", flush=True)
    storage_keys = con.execute(f"""
        SELECT DISTINCT block_number, target_address, storage_slot
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
        ORDER BY block_number
    """).fetchall()
    elapsed = time.time() - phase_start
    print(f"         {len(storage_keys):,} unique storage keys ({elapsed:.1f}s)", flush=True)

    # Bytecode keys (contracts called/created)
    phase_start = time.time()
    print("  [2/3] Fetching bytecode keys...", flush=True)
    bytecode_keys = con.execute(f"""
        SELECT DISTINCT block_number, target_address
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (6, 7, 8, 9, 10, 11, 12)
        ORDER BY block_number
    """).fetchall()
    elapsed = time.time() - phase_start
    print(f"         {len(bytecode_keys):,} unique bytecode keys ({elapsed:.1f}s)", flush=True)

    # Account keys
    phase_start = time.time()
    print("  [3/3] Fetching account keys...", flush=True)
    account_keys = con.execute(f"""
        SELECT DISTINCT block_number, target_address
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (2, 3, 4, 5)
        ORDER BY block_number
    """).fetchall()
    elapsed = time.time() - phase_start
    print(f"         {len(account_keys):,} unique account keys ({elapsed:.1f}s)", flush=True)

    # Get all block numbers
    all_blocks = con.execute(f"""
        SELECT DISTINCT block_number
        FROM read_parquet('{DATA_PATH}')
        ORDER BY block_number
    """).fetchall()
    all_blocks = [b[0] for b in all_blocks]

    phase1_time = time.time() - total_start_time
    print(f"\n  Phase 1 complete: {len(all_blocks):,} blocks, {phase1_time:.1f}s total", flush=True)

    print("\n" + "=" * 70)
    print("PHASE 2: Grouping keys by block")
    print("=" * 70)

    phase_start = time.time()
    print("  Grouping storage keys...", flush=True)
    storage_by_block = defaultdict(list)
    for i, (block_num, addr, slot) in enumerate(storage_keys):
        storage_by_block[block_num].append((bytes(addr), bytes(slot)))
        if i % 50_000_000 == 0 and i > 0:
            print(f"    {i:,}/{len(storage_keys):,} ({i*100/len(storage_keys):.0f}%)", flush=True)
    del storage_keys
    print(f"    Done ({time.time() - phase_start:.1f}s)", flush=True)

    phase_start = time.time()
    print("  Grouping bytecode keys...", flush=True)
    bytecode_by_block = defaultdict(set)
    for block_num, addr in bytecode_keys:
        bytecode_by_block[block_num].add(bytes(addr))
    del bytecode_keys
    print(f"    Done ({time.time() - phase_start:.1f}s)", flush=True)

    phase_start = time.time()
    print("  Grouping account keys...", flush=True)
    account_by_block = defaultdict(set)
    for block_num, addr in account_keys:
        account_by_block[block_num].add(bytes(addr))
    del account_keys
    print(f"    Done ({time.time() - phase_start:.1f}s)", flush=True)

    phase2_time = time.time() - total_start_time - phase1_time
    print(f"\n  Phase 2 complete: {phase2_time:.1f}s", flush=True)

    # Initialize zstd compressor/decompressor
    cctx = zstd.ZstdCompressor(level=3)
    dctx = zstd.ZstdDecompressor()

    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.measure-all-keys-as-hint-size.csv"

    print("\n" + "=" * 70)
    print("PHASE 3: Processing blocks (compress/decompress)")
    print("=" * 70)

    phase_start = time.time()
    results = []
    report_interval = 10000
    for i, block_num in enumerate(all_blocks):
        if i % report_interval == 0:
            if i == 0:
                print(f"  {i:,}/{len(all_blocks):,} blocks (0%)...", flush=True)
            else:
                elapsed = time.time() - phase_start
                rate = i / elapsed
                remaining = (len(all_blocks) - i) / rate
                pct = i * 100 / len(all_blocks)
                print(f"  {i:,}/{len(all_blocks):,} blocks ({pct:.0f}%) - {elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining", flush=True)

        # Collect all keys as bytes
        key_data = bytearray()

        # Add storage keys (52 bytes each: 20-byte address + 32-byte slot)
        for addr, slot in storage_by_block.get(block_num, []):
            key_data.extend(addr)
            key_data.extend(slot)

        # Add bytecode keys (20 bytes each: address only)
        for addr in bytecode_by_block.get(block_num, set()):
            key_data.extend(addr)

        # Add account keys (20 bytes each: address only)
        for addr in account_by_block.get(block_num, set()):
            key_data.extend(addr)

        raw_size = len(key_data)

        if raw_size == 0:
            results.append({
                'block_number': block_num,
                'raw_size_bytes': 0,
                'compressed_size_bytes': 0,
                'compression_time_us': 0,
                'decompression_time_us': 0,
            })
            continue

        # Compress
        key_bytes = bytes(key_data)
        start_time = time.perf_counter()
        compressed = cctx.compress(key_bytes)
        compression_time = (time.perf_counter() - start_time) * 1_000_000  # microseconds

        compressed_size = len(compressed)

        # Decompress
        start_time = time.perf_counter()
        _ = dctx.decompress(compressed)
        decompression_time = (time.perf_counter() - start_time) * 1_000_000  # microseconds

        results.append({
            'block_number': block_num,
            'raw_size_bytes': raw_size,
            'compressed_size_bytes': compressed_size,
            'compression_time_us': round(compression_time, 2),
            'decompression_time_us': round(decompression_time, 2),
        })

    phase3_time = time.time() - phase_start
    print(f"\n  Phase 3 complete: {phase3_time:.1f}s", flush=True)

    # Write CSV
    print("\n" + "=" * 70)
    print("PHASE 4: Writing CSV")
    print("=" * 70)
    print(f"  Writing {len(results):,} rows to {csv_path}...", flush=True)
    phase_start = time.time()
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['block_number', 'raw_size_bytes', 'compressed_size_bytes', 'compression_time_us', 'decompression_time_us'])
        writer.writeheader()
        writer.writerows(results)
    print(f"  Done ({time.time() - phase_start:.1f}s)", flush=True)

    # Calculate and print summary statistics
    raw_sizes = [r['raw_size_bytes'] for r in results if r['raw_size_bytes'] > 0]
    compressed_sizes = [r['compressed_size_bytes'] for r in results if r['raw_size_bytes'] > 0]
    compression_times = [r['compression_time_us'] for r in results if r['raw_size_bytes'] > 0]
    decompression_times = [r['decompression_time_us'] for r in results if r['raw_size_bytes'] > 0]

    def percentile(data, p):
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * p / 100)
        return sorted_data[min(idx, len(sorted_data) - 1)]

    print("\n" + "=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)

    print(f"\nBlocks analyzed: {len(results):,}")
    print(f"Blocks with data: {len(raw_sizes):,}")

    print(f"\n{'Metric':<25} {'Median':>12} {'P95':>12} {'Max':>12}")
    print("-" * 61)

    print(f"{'Raw size (KB)':<25} {percentile(raw_sizes, 50)/1024:>12,.1f} {percentile(raw_sizes, 95)/1024:>12,.1f} {max(raw_sizes)/1024:>12,.1f}")
    print(f"{'Compressed size (KB)':<25} {percentile(compressed_sizes, 50)/1024:>12,.1f} {percentile(compressed_sizes, 95)/1024:>12,.1f} {max(compressed_sizes)/1024:>12,.1f}")
    print(f"{'Compression ratio':<25} {percentile(raw_sizes, 50)/percentile(compressed_sizes, 50):>12,.2f}x {percentile(raw_sizes, 95)/percentile(compressed_sizes, 95):>12,.2f}x {'-':>12}")
    print(f"{'Compression time (µs)':<25} {percentile(compression_times, 50):>12,.0f} {percentile(compression_times, 95):>12,.0f} {max(compression_times):>12,.0f}")
    print(f"{'Decompression time (µs)':<25} {percentile(decompression_times, 50):>12,.0f} {percentile(decompression_times, 95):>12,.0f} {max(decompression_times):>12,.0f}")

    # Compression ratio distribution
    ratios = [r / c for r, c in zip(raw_sizes, compressed_sizes) if c > 0]
    print(f"\nCompression ratio stats:")
    print(f"  Median: {percentile(ratios, 50):.2f}x")
    print(f"  P5-P95: {percentile(ratios, 5):.2f}x - {percentile(ratios, 95):.2f}x")

    total_time = time.time() - total_start_time
    print("\n" + "=" * 70)
    print(f"COMPLETE - Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    print(f"Output saved to: {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
