# Zenodo deposit metadata

Use this when filling out the Zenodo upload form for the Ira USENIX Security
2026 artifact data deposit.

---

## Title

```
Ira: Efficient Transaction Replay for Ethereum — Artifact Data
```

## Authors

| Name | Affiliation | ORCID |
|---|---|---|
| Adithya Bhat | (fill in) | (fill in if applicable) |
| Harshal Shah | (fill in) | (fill in if applicable) |
| Mohsen Minaei | (fill in) | (fill in if applicable) |

## Resource type

`Dataset` (or `Software` if Zenodo prefers — both are valid for USENIX Available).

## Description

```markdown
Data artifact accompanying the USENIX Security 2026 paper *"Ira: Efficient
Transaction Replay for Ethereum"* by Adithya Bhat, Harshal Shah, and Mohsen
Minaei.

Source code, analysis scripts, benchmark CSVs, and README live at the
companion GitHub repository:
https://github.com/adithyabhatkajake/ira-rs (tagged release `v1.0-usenixsec26`).

This Zenodo record holds three large data assets that are too big to ship in
the source repository:

- **`ira-hints.tar`** (~14 GB). Hint database emitted by `reth-primary` over
  Ethereum mainnet blocks 24,019,447–24,120,246 (100,800 blocks,
  mid-to-late December 2025). Contains both the consolidated `hints.redb`
  (consumed by `reth-backup`) and the per-block `batch_*/<n>.hint.zst`
  files (consumed by the source-byte distribution analysis script).
- **`ira-parquet-traces.tar`** (~6.8 GB). Raw per-operation Ethereum
  execution traces emitted by `ira-trace-collector`. Schema: per-row
  Apache Parquet (Zstd) with `(block_number, tx_index, op_type, address,
  slot, value, source_byte)`. Consumed by the §3 case-study scripts under
  `scripts/analyze-*.py` and `scripts/generate-*.py`.
- **`ira-state-hashes.tar`** (~788 MB). Per-block deterministic post-state
  fingerprints emitted by `reth-primary`. Used by `reth-backup` for
  correctness verification (`--state-hash-dir`).

The full reth archive datadir (~3 TB) is **not** deposited — anyone can
reproduce it by running reth at the pinned commit
(`62abfdaeb54e8a205a8ee085ddebd56047d93374`) against mainnet up to block
24,120,246.

**SHA-256 checksums** are provided in `SHA256SUMS`. To verify:
`shasum -a 256 -c SHA256SUMS`.

**Reproduction.** See `README.md` in the GitHub repository for the
end-to-end build / run / regenerate-figures recipe. The bundled CSVs in
the GitHub repository regenerate all paper macros and figures without
this Zenodo data; the data here is only required for the full
re-execution path that starts from a synced reth archive node.
```

## Keywords

```
Ethereum, blockchain, state machine replication, transaction replay,
cache replacement, Belady, reth, hint-based optimization, USENIX Security 2026
```

## License

`MIT License` (matches the source repository).

## Related identifiers

| Relation | Identifier | Type |
|---|---|---|
| `isSupplementTo` | `arXiv:2601.21286` | arXiv paper |
| `isSupplementTo` | `https://github.com/adithyabhatkajake/ira-rs/releases/tag/v1.0-usenixsec26` | GitHub release |
| `isVersionOf` | `https://github.com/adithyabhatkajake/ira-rs` | GitHub source repository |

(Once Zenodo mints the DOI, add it back to the paper's bib entry [11] and
the README.)

## Publication date

`2026-05-XX` (date of Zenodo deposit; will autofill on submission).

## Communities

Search Zenodo communities for `USENIX Security 2026` or `usenix-security-2026`
— if a community exists, request inclusion. Otherwise skip.

## Funding (optional)

If applicable, list any grant numbers.

## After publish — update GitHub

1. Add a top-level badge to README:
   `[![DOI](https://zenodo.org/badge/DOI/<NEW-DOI>.svg)](https://doi.org/<NEW-DOI>)`
2. Update the bibtex citation block to include the DOI.
3. Update paper `\cite{AnonymousOpenScienceIra2026}` in
   `~/Overleaf/2026.Visa.Ira/Ira-bibliography-zotero.bib` to point at the
   Zenodo DOI + GitHub repo URL.
4. Submit the DOI as the canonical artifact identifier on the USENIX
   artifact submission system.
