"""
Process bytes-per-cache-entry CSV to generate operation distribution macros.

Generates macros for Table 2 (tab:op-distribution) and related statistics.
Data source: data/2026.01.08.measure-bytes-per-cache-entry.csv
Code reference: src/types.rs:6-30 (OpType enum)
"""

import csv
from pathlib import Path


def process_bytes_per_cache_entry(macros):
    """Process operation distribution data and generate macros.

    This function is called by generate_numbers.py with a MacroCollection.
    We import the necessary utilities here to avoid circular imports.
    """
    from generate_numbers import (
        DATA_DIR,
        format_int,
        format_float,
        format_percent,
    )

    csv_path = DATA_DIR / "2026.01.08.measure-bytes-per-cache-entry.csv"
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, skipping")
        return

    macros.section("Operation Distribution (Table 2)")

    # Operation type mapping (from src/types.rs)
    # 0=SLOAD, 1=SSTORE, 2=BALANCE, 3=SELFBALANCE, 4=EXTCODESIZE,
    # 5=EXTCODEHASH, 6=EXTCODECOPY, 7=CALL, 8=STATICCALL, 9=DELEGATECALL,
    # 10=CALLCODE, 11=CREATE, 12=CREATE2, 13=SELFDESTRUCT

    # Initialize counters
    counts = {i: 0 for i in range(14)}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            op_type = int(row["op_type"])
            count = int(row["count"])
            counts[op_type] += count

    # Individual operation counts
    sload = counts[0]
    sstore = counts[1]
    balance = counts[2]
    selfbalance = counts[3]
    extcodesize = counts[4]
    extcodehash = counts[5]
    extcodecopy = counts[6]
    call = counts[7]
    staticcall = counts[8]
    delegatecall = counts[9]
    callcode = counts[10]
    create = counts[11]
    create2 = counts[12]
    selfdestruct = counts[13]

    # Category totals (matching Table 2 categorization)
    storage_total = sload + sstore
    account_metadata = balance + selfbalance
    # Note: EXTCODESIZE and EXTCODEHASH grouped with calls in paper
    calls_total = call + staticcall + delegatecall + callcode + extcodesize + extcodehash + extcodecopy
    creation_destruction = create + create2 + selfdestruct
    grand_total = storage_total + account_metadata + calls_total + creation_destruction

    # Percentages
    storage_pct = (storage_total / grand_total) * 100
    account_pct = (account_metadata / grand_total) * 100
    calls_pct = (calls_total / grand_total) * 100
    creation_pct = (creation_destruction / grand_total) * 100

    # Read-write ratio
    rw_ratio = sload / sstore

    # === Add macros ===

    # Individual counts
    macros.add("SloadCount", format_int(sload), "SLOAD operations")
    macros.add("SstoreCount", format_int(sstore), "SSTORE operations")
    macros.add("BalanceCount", format_int(balance), "BALANCE operations")
    macros.add("SelfbalanceCount", format_int(selfbalance), "SELFBALANCE operations")
    macros.add("ExtcodesizeCount", format_int(extcodesize), "EXTCODESIZE operations")
    macros.add("ExtcodehashCount", format_int(extcodehash), "EXTCODEHASH operations")
    macros.add("ExtcodecopyCount", format_int(extcodecopy), "EXTCODECOPY operations")
    macros.add("CallCount", format_int(call), "CALL operations")
    macros.add("StaticcallCount", format_int(staticcall), "STATICCALL operations")
    macros.add("DelegatecallCount", format_int(delegatecall), "DELEGATECALL operations")
    macros.add("CallcodeCount", format_int(callcode), "CALLCODE operations")
    macros.add("CreateCount", format_int(create), "CREATE operations")
    macros.add("CreateTwoCount", format_int(create2), "CREATE2 operations")
    macros.add("SelfdestructCount", format_int(selfdestruct), "SELFDESTRUCT operations")

    # Table 2 category totals
    macros.add("StorageOpsTotal", format_int(storage_total), "SLOAD + SSTORE")
    macros.add("AccountMetadataTotal", format_int(account_metadata), "BALANCE + SELFBALANCE")
    macros.add("CallsTotal", format_int(calls_total), "All call/code operations")
    macros.add("CreationDestructionTotal", format_int(creation_destruction), "CREATE + CREATE2 + SELFDESTRUCT")
    macros.add("OpsGrandTotal", format_int(grand_total), "All operations")

    # Table 2 percentages
    macros.add("StorageOpsPct", format_percent(storage_pct, 1), "Storage share")
    macros.add("AccountMetadataPct", format_percent(account_pct, 1), "Account metadata share")
    macros.add("CallsPct", format_percent(calls_pct, 1), "Calls share")
    macros.add("CreationDestructionPct", format_percent(creation_pct, 1), "Creation/destruction share")

    # Read-write ratio
    macros.add("StorageRwRatio", format_float(rw_ratio, 1), "SLOAD:SSTORE ratio")
