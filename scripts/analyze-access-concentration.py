#!/usr/bin/env python3
"""
Analyze access concentration in EVM storage operations.

Outputs all numbers needed for the "Extreme Access Concentration" section:
- Cumulative storage access share by contract rank
- Key-level concentration statistics
"""

import os

import duckdb

DATA_PATH = os.environ.get("IRA_TRACES", "/Volumes/X/ira-new-analysis/*.parquet")

# Known contract names for annotation
CONTRACT_NAMES = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
}


def get_contract_name(address: str) -> str:
    """Get human-readable name for known contracts."""
    addr_lower = address.lower()
    return CONTRACT_NAMES.get(addr_lower, "")


def main():
    con = duckdb.connect()

    print("=" * 70)
    print("ACCESS CONCENTRATION ANALYSIS")
    print("=" * 70)

    # Total storage operations
    total_ops = con.execute(f"""
        SELECT COUNT(*) FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
    """).fetchone()[0]

    print(f"\nTotal storage operations: {total_ops:,}")

    # 1. Contract-level concentration
    print("\n" + "-" * 70)
    print("1. CONTRACT-LEVEL CONCENTRATION")
    print("-" * 70)

    # Get top contracts ranked by storage operations
    top_contracts = con.execute(f"""
        SELECT
            '0x' || hex(target_address) as contract,
            COUNT(*) as ops,
            ROUND(COUNT(*) * 100.0 / {total_ops}, 2) as share_pct
        FROM read_parquet('{DATA_PATH}')
        WHERE op_type IN (0, 1)
        GROUP BY target_address
        ORDER BY ops DESC
        LIMIT 50
    """).fetchdf()

    # Calculate cumulative share
    top_contracts['cumulative_pct'] = top_contracts['share_pct'].cumsum()

    print(f"\n{'Rank':<6} {'Contract':<46} {'Ops':>12} {'Share':>8} {'Cumul.':>8}")
    print("-" * 80)
    for i, row in top_contracts.head(20).iterrows():
        name = get_contract_name(row['contract'])
        name_str = f" ({name})" if name else ""
        contract_display = row['contract'][:18] + "..." + name_str
        print(f"{i+1:<6} {contract_display:<46} {row['ops']:>12,} {row['share_pct']:>7.1f}% {row['cumulative_pct']:>7.1f}%")

    # Cumulative share at specific ranks
    print("\n" + "-" * 70)
    print("CUMULATIVE SHARE BY RANK")
    print("-" * 70)

    milestones = [1, 2, 3, 5, 10, 20, 50, 100]
    print(f"\n{'Top-N Contracts':<20} {'Cumulative Share':>20}")
    print("-" * 40)

    for n in milestones:
        if n <= len(top_contracts):
            cumul = top_contracts.iloc[n-1]['cumulative_pct']
            # Get contract name for top 3
            if n <= 3:
                name = get_contract_name(top_contracts.iloc[n-1]['contract'])
                label = f"Top {n}" + (f" (+{name})" if name and n > 1 else f" ({name})" if name else "")
            else:
                label = f"Top {n}"
            print(f"{label:<20} {cumul:>19.1f}%")

    # LaTeX table
    print("\n" + "-" * 70)
    print("LATEX TABLE")
    print("-" * 70)
    print("""
\\begin{table}[t]
\\centering
\\caption{Cumulative storage access share by contract rank.}
\\label{tab:concentration}
\\small
\\begin{tabular}{lr}
\\toprule
\\textbf{Top-N Contracts} & \\textbf{Cumulative Share} \\\\
\\midrule""")

    # Top 1, 2, 3 with names
    for n in [1, 2, 3]:
        name = get_contract_name(top_contracts.iloc[n-1]['contract'])
        cumul = top_contracts.iloc[n-1]['cumulative_pct']
        if n == 1:
            label = f"Top 1 ({name})" if name else "Top 1"
        else:
            label = f"Top {n} (+{name})" if name else f"Top {n}"
        print(f"{label} & ${cumul:.1f}\\%$ \\\\")

    # Top 10, 20
    for n in [10, 20]:
        cumul = top_contracts.iloc[n-1]['cumulative_pct']
        print(f"Top {n} & ${cumul:.1f}\\%$ \\\\")

    print("""\\bottomrule
\\end{tabular}
\\end{table}
""")

    # 2. Key-level concentration
    print("-" * 70)
    print("2. KEY-LEVEL CONCENTRATION")
    print("-" * 70)

    # Get key access distribution
    key_stats = con.execute(f"""
        WITH key_accesses AS (
            SELECT
                target_address,
                storage_slot,
                COUNT(*) as accesses
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        )
        SELECT
            COUNT(*) as total_keys,
            SUM(accesses) as total_accesses,
            SUM(CASE WHEN accesses >= 100 THEN 1 ELSE 0 END) as keys_100plus,
            SUM(CASE WHEN accesses >= 100 THEN accesses ELSE 0 END) as ops_100plus,
            SUM(CASE WHEN accesses <= 2 THEN 1 ELSE 0 END) as keys_1or2,
            SUM(CASE WHEN accesses <= 2 THEN accesses ELSE 0 END) as ops_1or2
        FROM key_accesses
    """).fetchone()

    total_keys, total_accesses, keys_100plus, ops_100plus, keys_1or2, ops_1or2 = key_stats

    pct_keys_100plus = keys_100plus / total_keys * 100
    pct_ops_100plus = ops_100plus / total_accesses * 100
    pct_keys_1or2 = keys_1or2 / total_keys * 100
    pct_ops_1or2 = ops_1or2 / total_accesses * 100

    print(f"\nTotal unique keys: {total_keys:,}")
    print(f"Total storage accesses: {total_accesses:,}")

    print(f"\nHigh-frequency keys (100+ accesses):")
    print(f"  Keys:       {keys_100plus:,} ({pct_keys_100plus:.2f}% of all keys)")
    print(f"  Operations: {ops_100plus:,} ({pct_ops_100plus:.1f}% of all ops)")

    print(f"\nLow-frequency keys (1-2 accesses):")
    print(f"  Keys:       {keys_1or2:,} ({pct_keys_1or2:.1f}% of all keys)")
    print(f"  Operations: {ops_1or2:,} ({pct_ops_1or2:.1f}% of all ops)")

    # More detailed breakdown
    print("\n" + "-" * 70)
    print("KEY ACCESS FREQUENCY DISTRIBUTION")
    print("-" * 70)

    freq_dist = con.execute(f"""
        WITH key_accesses AS (
            SELECT COUNT(*) as accesses
            FROM read_parquet('{DATA_PATH}')
            WHERE op_type IN (0, 1)
            GROUP BY target_address, storage_slot
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN accesses = 1 THEN '1'
                    WHEN accesses = 2 THEN '2'
                    WHEN accesses BETWEEN 3 AND 10 THEN '3-10'
                    WHEN accesses BETWEEN 11 AND 100 THEN '11-100'
                    WHEN accesses BETWEEN 101 AND 1000 THEN '101-1K'
                    WHEN accesses BETWEEN 1001 AND 10000 THEN '1K-10K'
                    ELSE '>10K'
                END as bucket,
                CASE
                    WHEN accesses = 1 THEN 1
                    WHEN accesses = 2 THEN 2
                    WHEN accesses BETWEEN 3 AND 10 THEN 3
                    WHEN accesses BETWEEN 11 AND 100 THEN 4
                    WHEN accesses BETWEEN 101 AND 1000 THEN 5
                    WHEN accesses BETWEEN 1001 AND 10000 THEN 6
                    ELSE 7
                END as sort_order,
                accesses
            FROM key_accesses
        )
        SELECT
            bucket,
            COUNT(*) as keys,
            SUM(accesses) as ops,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as pct_keys,
            ROUND(SUM(accesses) * 100.0 / SUM(SUM(accesses)) OVER(), 2) as pct_ops
        FROM bucketed
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """).fetchdf()

    print(f"\n{'Accesses':<12} {'Keys':>14} {'% Keys':>10} {'Ops':>16} {'% Ops':>10}")
    print("-" * 62)
    for _, row in freq_dist.iterrows():
        print(f"{row['bucket']:<12} {row['keys']:>14,} {row['pct_keys']:>9.2f}% {row['ops']:>16,} {row['pct_ops']:>9.2f}%")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY FOR WRITING")
    print("=" * 70)

    top1_name = get_contract_name(top_contracts.iloc[0]['contract'])
    top2_name = get_contract_name(top_contracts.iloc[1]['contract'])
    top3_name = get_contract_name(top_contracts.iloc[2]['contract'])

    print(f"""
Contract-level concentration:
- Top 1 ({top1_name}): {top_contracts.iloc[0]['cumulative_pct']:.1f}%
- Top 2 (+{top2_name}): {top_contracts.iloc[1]['cumulative_pct']:.1f}%
- Top 3 (+{top3_name}): {top_contracts.iloc[2]['cumulative_pct']:.1f}%
- Top 10: {top_contracts.iloc[9]['cumulative_pct']:.1f}%
- Top 20: {top_contracts.iloc[19]['cumulative_pct']:.1f}%

Key-level concentration:
- High-frequency keys (100+ accesses): {pct_keys_100plus:.2f}% of keys, {pct_ops_100plus:.1f}% of ops
- Low-frequency keys (1-2 accesses): {pct_keys_1or2:.1f}% of keys, {pct_ops_1or2:.1f}% of ops

LaTeX snippets:
- "The top {pct_keys_100plus:.2f}\\% of keys ({keys_100plus:,} keys with 100+ accesses) account for {pct_ops_100plus:.1f}\\% of all storage operations."
- "Conversely, {pct_keys_1or2:.0f}\\% of keys are accessed only once or twice, contributing just {pct_ops_1or2:.1f}\\% of total accesses."
""")

    print("=" * 70)


if __name__ == "__main__":
    main()
