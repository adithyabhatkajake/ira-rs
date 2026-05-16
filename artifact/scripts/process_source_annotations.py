"""
Process source annotation distribution data.

Computes the distribution of PlainState, Zero (NotYetWritten), and Changeset
source annotations across all storage keys.

Data source:
- data/2026.01.28.source-byte-distribution.csv
"""

import csv

import numpy as np


def process_source_annotations(macros):
    """Process source annotation distribution and generate macros.

    This function is called by generate_numbers.py with a MacroCollection.
    """
    from generate_numbers import (
        DATA_DIR,
        format_int,
        format_percent,
    )

    csv_path = DATA_DIR / "2026.01.28.source-byte-distribution.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping source annotations")
        return

    macros.section("Source Annotation Distribution")

    # Read data
    storage_keys = []
    plain_state = []
    zero = []
    changeset = []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            storage_keys.append(int(row["storage_keys"]))
            plain_state.append(int(row["source_plain_state"]))
            zero.append(int(row["source_not_yet_written"]))
            changeset.append(int(row["source_in_changeset"]))

    storage_keys = np.array(storage_keys)
    plain_state = np.array(plain_state)
    zero = np.array(zero)
    changeset = np.array(changeset)

    # Aggregate totals
    total_plain = int(plain_state.sum())
    total_zero = int(zero.sum())
    total_changeset = int(changeset.sum())
    total_annotated = total_plain + total_zero + total_changeset

    pct_plain = (total_plain / total_annotated) * 100
    pct_zero = (total_zero / total_annotated) * 100
    pct_changeset = (total_changeset / total_annotated) * 100

    # Add aggregate macros
    macros.add("SourceTotalKeys", format_int(total_annotated), "Total annotated storage keys")
    macros.add("SourcePlainStateCount", format_int(total_plain), "PlainState keys")
    macros.add("SourceZeroCount", format_int(total_zero), "Zero/NotYetWritten keys")
    macros.add("SourceChangesetCount", format_int(total_changeset), "Changeset keys")
    macros.add("SourcePlainStatePct", format_percent(pct_plain, 1), "PlainState share")
    macros.add("SourceZeroPct", format_percent(pct_zero, 1), "Zero/NotYetWritten share")
    macros.add("SourceChangesetPct", format_percent(pct_changeset, 1), "Changeset share")

    # Combined: keys that avoid history lookup (PlainState + Zero)
    total_no_history = total_plain + total_zero
    pct_no_history = (total_no_history / total_annotated) * 100
    macros.add("SourceNoHistoryPct", format_percent(pct_no_history, 1), "PlainState + Zero share (no history lookup)")

    # Per-block statistics (excluding blocks with 0 storage keys)
    valid = storage_keys > 0
    plain_pcts = (plain_state[valid] / storage_keys[valid]) * 100
    zero_pcts = (zero[valid] / storage_keys[valid]) * 100
    changeset_pcts = (changeset[valid] / storage_keys[valid]) * 100
    no_history_pcts = ((plain_state[valid] + zero[valid]) / storage_keys[valid]) * 100

    macros.add("SourcePlainStateMedianPct", format_percent(np.median(plain_pcts), 1), "Median per-block PlainState share")
    macros.add("SourceZeroMedianPct", format_percent(np.median(zero_pcts), 1), "Median per-block Zero share")
    macros.add("SourceChangesetMedianPct", format_percent(np.median(changeset_pcts), 1), "Median per-block Changeset share")
    macros.add("SourceNoHistoryMedianPct", format_percent(np.median(no_history_pcts), 1), "Median per-block no-history share")

    # IQR for PlainState
    macros.add("SourcePlainStatePTwentyFivePct", format_percent(np.percentile(plain_pcts, 25), 1), "P25 per-block PlainState share")
    macros.add("SourcePlainStatePSeventyFivePct", format_percent(np.percentile(plain_pcts, 75), 1), "P75 per-block PlainState share")

    # IQR for Zero
    macros.add("SourceZeroPTwentyFivePct", format_percent(np.percentile(zero_pcts, 25), 1), "P25 per-block Zero share")
    macros.add("SourceZeroPSeventyFivePct", format_percent(np.percentile(zero_pcts, 75), 1), "P75 per-block Zero share")

    # IQR for Changeset
    macros.add("SourceChangesetPTwentyFivePct", format_percent(np.percentile(changeset_pcts, 25), 1), "P25 per-block Changeset share")
    macros.add("SourceChangesetPSeventyFivePct", format_percent(np.percentile(changeset_pcts, 75), 1), "P75 per-block Changeset share")

    # P5 and P95 tails
    macros.add("SourcePlainStatePFivePct", format_percent(np.percentile(plain_pcts, 5), 1), "P5 per-block PlainState share")
    macros.add("SourcePlainStatePNinetyFivePct", format_percent(np.percentile(plain_pcts, 95), 1), "P95 per-block PlainState share")
    macros.add("SourceZeroPFivePct", format_percent(np.percentile(zero_pcts, 5), 1), "P5 per-block Zero share")
    macros.add("SourceZeroPNinetyFivePct", format_percent(np.percentile(zero_pcts, 95), 1), "P95 per-block Zero share")
    macros.add("SourceChangesetPFivePct", format_percent(np.percentile(changeset_pcts, 5), 1), "P5 per-block Changeset share")
    macros.add("SourceChangesetPNinetyFivePct", format_percent(np.percentile(changeset_pcts, 95), 1), "P95 per-block Changeset share")

    # Print verification
    print(f"\n=== Source Annotation Distribution Verification ===")
    print(f"Total annotated keys: {total_annotated:,}")
    print(f"PlainState: {total_plain:,} ({pct_plain:.1f}%)")
    print(f"Zero: {total_zero:,} ({pct_zero:.1f}%)")
    print(f"Changeset: {total_changeset:,} ({pct_changeset:.1f}%)")
    print(f"No history lookup (PlainState + Zero): {total_no_history:,} ({pct_no_history:.1f}%)")
    print(f"Per-block PlainState median: {np.median(plain_pcts):.1f}%")
    print(f"Per-block Zero median: {np.median(zero_pcts):.1f}%")
    print(f"Per-block Changeset median: {np.median(changeset_pcts):.1f}%")
