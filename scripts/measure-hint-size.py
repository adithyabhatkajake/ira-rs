#!/usr/bin/env python3
"""
Measure actual IRA-L hint file sizes from the hints directory.

Reads the header of each hint file to extract:
- Uncompressed (raw) size
- Compressed size

Hint file format (28-byte header):
- [8 bytes] Magic: "IRABHINT"
- [4 bytes] Version
- [8 bytes] Block number (u64 LE)
- [4 bytes] Uncompressed size (u32 LE)
- [4 bytes] Compressed size (u32 LE)
- [...] Zstd-compressed payload
"""

import os
import struct
import csv
import time
from pathlib import Path
from datetime import date

HINT_DIR = os.environ.get("IRA_HINTS", "/Volumes/X/ira-analysis/hints")
OUTPUT_DIR = os.environ.get("IRA_OUTPUT", "data")
HEADER_SIZE = 28
MAGIC = b"IRABHINT"


def read_hint_header(filepath):
    """Read hint file header and return (block_number, raw_size, compressed_size)."""
    with open(filepath, 'rb') as f:
        header = f.read(HEADER_SIZE)

    if len(header) < HEADER_SIZE:
        return None

    magic = header[0:8]
    if magic != MAGIC:
        return None

    block_number = struct.unpack('<Q', header[12:20])[0]
    raw_size = struct.unpack('<I', header[20:24])[0]
    compressed_size = struct.unpack('<I', header[24:28])[0]

    return block_number, raw_size, compressed_size


def main():
    start_time = time.time()

    print("=" * 70)
    print("MEASURING ACTUAL HINT FILE SIZES")
    print("=" * 70)
    print(f"Hint directory: {HINT_DIR}")

    # Find all hint files
    hint_dir = Path(HINT_DIR)
    batch_dirs = sorted(hint_dir.glob("batch_*"))

    print(f"Found {len(batch_dirs)} batch directories")

    results = []
    total_files = 0

    for batch_dir in batch_dirs:
        hint_files = sorted(batch_dir.glob("*.hint.zst"))
        total_files += len(hint_files)

    print(f"Total hint files: {total_files:,}")
    print()

    processed = 0
    for batch_dir in batch_dirs:
        hint_files = sorted(batch_dir.glob("*.hint.zst"))

        for hint_file in hint_files:
            result = read_hint_header(hint_file)
            if result:
                block_number, raw_size, compressed_size = result
                # File size on disk (includes 28-byte header)
                file_size = os.path.getsize(hint_file)

                results.append({
                    'block_number': block_number,
                    'raw_size_bytes': raw_size,
                    'compressed_size_bytes': compressed_size,
                    'file_size_bytes': file_size,
                })

            processed += 1
            if processed % 10000 == 0:
                elapsed = time.time() - start_time
                pct = processed * 100 / total_files
                print(f"  Processed {processed:,}/{total_files:,} ({pct:.1f}%) - {elapsed:.1f}s", flush=True)

    # Sort by block number
    results.sort(key=lambda x: x['block_number'])

    # Write CSV
    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.measure-hint-size.csv"

    print(f"\nWriting {len(results):,} rows to {csv_path}")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['block_number', 'raw_size_bytes', 'compressed_size_bytes', 'file_size_bytes'])
        writer.writeheader()
        writer.writerows(results)

    # Summary statistics
    raw_sizes = [r['raw_size_bytes'] for r in results if r['raw_size_bytes'] > 0]
    compressed_sizes = [r['compressed_size_bytes'] for r in results if r['compressed_size_bytes'] > 0]

    def percentile(arr, p):
        arr = sorted(arr)
        idx = int(len(arr) * p)
        return arr[min(idx, len(arr)-1)]

    print("\n" + "=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    print(f"Blocks with hints: {len(results):,}")
    print(f"Blocks with data:  {len(raw_sizes):,}")

    if raw_sizes:
        print(f"\nRaw (uncompressed) hint size:")
        print(f"  Mean:   {sum(raw_sizes)/len(raw_sizes)/1024:.1f} KB")
        print(f"  Median: {percentile(raw_sizes, 0.5)/1024:.1f} KB")
        print(f"  p90:    {percentile(raw_sizes, 0.9)/1024:.1f} KB")
        print(f"  p99:    {percentile(raw_sizes, 0.99)/1024:.1f} KB")
        print(f"  Max:    {max(raw_sizes)/1024:.1f} KB")

        print(f"\nCompressed hint size:")
        print(f"  Mean:   {sum(compressed_sizes)/len(compressed_sizes)/1024:.1f} KB")
        print(f"  Median: {percentile(compressed_sizes, 0.5)/1024:.1f} KB")
        print(f"  p90:    {percentile(compressed_sizes, 0.9)/1024:.1f} KB")
        print(f"  p99:    {percentile(compressed_sizes, 0.99)/1024:.1f} KB")
        print(f"  Max:    {max(compressed_sizes)/1024:.1f} KB")

        print(f"\nCompression ratio: {sum(raw_sizes)/sum(compressed_sizes):.2f}x")

    elapsed = time.time() - start_time
    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Output: {csv_path}")


if __name__ == "__main__":
    main()
