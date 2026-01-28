#!/usr/bin/env python3
"""Generate source byte distribution from hint files.

For each storage key in the hints, extract the source byte and count
the distribution across PlainState, NotYetWritten, and Changeset.

Hint file format (.hint.zst = Zstd compressed):
  - [4 bytes] storage_count (u32 LE)
  - [53 * N bytes] storage keys (20 addr + 32 slot + 1 source)
  - [4 bytes] bytecode_count (u32 LE)
  - [20 * N bytes] bytecode addresses
  - [4 bytes] account_count (u32 LE)
  - [20 * N bytes] account addresses

Source byte values:
  0 = IN_PLAIN_STATE
  1 = NOT_YET_WRITTEN
  2 = IN_CHANGESET
"""

import os
import struct
import zstandard
from datetime import date
from pathlib import Path

HINTS_DIR = "/Volumes/X/ira-analysis/hints"
OUTPUT_DIR = "/Users/adithyabhat/Github/ira-analytical/ira-trace-collector/data"

SOURCE_NAMES = {
    0: "IN_PLAIN_STATE",
    1: "NOT_YET_WRITTEN",
    2: "IN_CHANGESET",
}


def parse_hint_file(filepath):
    """Parse a .hint.zst file and return source byte counts and key type counts."""
    dctx = zstandard.ZstdDecompressor()
    with open(filepath, "rb") as f:
        raw = f.read()

    # Hint file header: IRABHINT (8) + version (4) + block_num (8) + uncompressed_size (4) + compressed_size (4) = 28 bytes
    header_size = 28
    compressed_payload = raw[header_size:]
    data = dctx.decompress(compressed_payload, max_output_size=10 * 1024 * 1024)

    offset = 0

    # Storage keys
    storage_count = struct.unpack_from("<I", data, offset)[0]
    offset += 4

    source_counts = {0: 0, 1: 0, 2: 0}
    for _ in range(storage_count):
        # Source byte is at offset + 52 within each 53-byte key
        source = data[offset + 52]
        source_counts[source] = source_counts.get(source, 0) + 1
        offset += 53

    # Bytecode addresses
    bytecode_count = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    offset += bytecode_count * 20

    # Account addresses
    account_count = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    offset += account_count * 20

    return storage_count, bytecode_count, account_count, source_counts


def main():
    print("=" * 70)
    print("SOURCE BYTE DISTRIBUTION")
    print("=" * 70)
    print(f"\nReading hints from: {HINTS_DIR}")

    total_source = {0: 0, 1: 0, 2: 0}
    total_storage = 0
    total_bytecode = 0
    total_account = 0
    block_count = 0

    # Per-block results for CSV
    per_block = []

    # Iterate over batch directories
    batch_dirs = sorted(
        p for p in Path(HINTS_DIR).iterdir()
        if p.is_dir() and p.name.startswith("batch_")
    )

    for batch_dir in batch_dirs:
        print(f"  Processing {batch_dir.name}...")
        hint_files = sorted(batch_dir.glob("*.hint.zst"))

        for hint_file in hint_files:
            block_num = int(hint_file.stem.split(".")[0])
            storage, bytecode, account, sources = parse_hint_file(hint_file)

            total_storage += storage
            total_bytecode += bytecode
            total_account += account
            for k, v in sources.items():
                total_source[k] += v
            block_count += 1

            per_block.append({
                "block_number": block_num,
                "storage_keys": storage,
                "bytecode_addresses": bytecode,
                "account_addresses": account,
                "source_plain_state": sources.get(0, 0),
                "source_not_yet_written": sources.get(1, 0),
                "source_in_changeset": sources.get(2, 0),
            })

    # Write per-block CSV
    today = date.today().strftime("%Y.%m.%d")
    csv_path = f"{OUTPUT_DIR}/{today}.source-byte-distribution.csv"

    with open(csv_path, "w") as f:
        f.write("block_number,storage_keys,bytecode_addresses,account_addresses,"
                "source_plain_state,source_not_yet_written,source_in_changeset\n")
        for row in sorted(per_block, key=lambda r: r["block_number"]):
            f.write(f"{row['block_number']},{row['storage_keys']},"
                    f"{row['bytecode_addresses']},{row['account_addresses']},"
                    f"{row['source_plain_state']},{row['source_not_yet_written']},"
                    f"{row['source_in_changeset']}\n")

    print(f"\nSaved to: {csv_path}")
    print(f"Blocks processed: {block_count:,}")

    # Summary
    total_keys = total_storage + total_bytecode + total_account
    total_src = sum(total_source.values())

    print("\n" + "-" * 70)
    print("KEY TYPE DISTRIBUTION")
    print("-" * 70)
    print(f"  Storage keys:       {total_storage:>15,} ({total_storage/total_keys*100:.1f}%)")
    print(f"  Bytecode addresses: {total_bytecode:>15,} ({total_bytecode/total_keys*100:.1f}%)")
    print(f"  Account addresses:  {total_account:>15,} ({total_account/total_keys*100:.1f}%)")
    print(f"  Total:              {total_keys:>15,}")

    print("\n" + "-" * 70)
    print("SOURCE BYTE DISTRIBUTION (storage keys only)")
    print("-" * 70)
    for source_val in [0, 1, 2]:
        count = total_source[source_val]
        pct = count / total_src * 100 if total_src > 0 else 0
        print(f"  {SOURCE_NAMES[source_val]:<20}: {count:>15,} ({pct:.2f}%)")
    print(f"  {'Total':<20}: {total_src:>15,}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
