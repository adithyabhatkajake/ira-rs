# Ira: Efficient Transaction Replay for Ethereum

Ira accelerates Ethereum archive-node transaction replay by recording compact
state hints during a primary execution and using those hints to drive
backup replayers that bypass the trie. Against an unmodified reth baseline
on the same hardware, Ira's sequential backup achieves an aggregate 5.2x
wall-time speedup and 23.6x/25.9x at 16/64 threads, with 10.9% overhead on
the primary.

This repository is the *Available*-badge artifact for the USENIX Security '26
paper.

## Paper

> Adithya Bhat, Harshal Shah, Mohsen Minaei. *Ira: Efficient Transaction Replay for Ethereum.*
> USENIX Security Symposium, 2026. arXiv:[2601.21286](https://arxiv.org/abs/2601.21286).

## Repository layout

```
.
├── Cargo.toml              workspace root; also the ira-trace-collector binary (paper §3.1)
├── src/                    ira-trace-collector source (parquet trace emitter)
├── crates/
│   ├── reth-primary/       primary replayer that emits hints (paper §4)
│   ├── reth-baseline/      unmodified-reth baseline used for speedup measurements
│   ├── reth-backup/        backup replayer that consumes hints (paper §5)
│   ├── ira-common/         shared hint/state-hash codecs
│   ├── io-trace/           I/O attribution tool used for §6.2 numbers
│   └── block-size/         per-block byte-cost measurement tool
├── scripts/                22 Python analysis/measurement/plotting scripts
│                           plus benchmark-cold-cache.sh and benchmark-all.sh
├── data/                   46 bundled CSVs — the paper's actual evaluation data
│                           (Run #1: Jan 15-28, Run #2: Jan 29-Feb 2, Run #3: Feb 12-13)
├── artifact/               paper-side reproduction harness
│   ├── scripts/            generate_numbers.py + process_*.py (8 processors)
│   ├── generated/          output: numbers.tex (229 \newcommand macros) [gitignored]
│   ├── figures/            output: paper figure PDFs [gitignored]
│   └── README.md           short reproduction recipe
├── figures/                drawio sources and pre-rendered architecture PDFs
├── docs/architecture.md    system architecture notes
├── LICENSE                 MIT
└── AUTHORS                 Adithya Bhat <dth.bht@gmail.com>
```

## Quick start: reproduce paper numbers (no archive node required)

The bundled CSVs in `data/` are the exact evaluation inputs the paper draws
from. Regenerating `numbers.tex` and the figures takes under a minute and
requires only Python.

```sh
pip install -r requirements.txt
cd artifact
python3 scripts/generate_numbers.py
```

This writes `artifact/generated/numbers.tex` (229 macros) and all PDF figures
under `artifact/figures/`. The output is byte-identical to the version
shipped with the paper sources; you can verify with:

```sh
diff artifact/generated/numbers.tex /path/to/paper-sources/generated/numbers.tex
# expected: empty output, exit 0
```

The `generated/` directory is gitignored; the script creates it on first run.

## Full reproduction (requires an Ethereum archive node)

End-to-end reproduction regenerates the CSVs in `data/` from a synced reth
archive node. This requires roughly 3 TB of disk for the reth datadir and
roughly 12 GB of disk for raw parquet traces; neither is redistributed
(consistent with the paper's Open Science section). The evaluation window
is mainnet blocks **24,019,447 - 24,120,246** (100,800 blocks, approx. two
weeks, mid-to-late December 2025).

### Step 1 - build

```sh
cargo build --release --workspace
```

Produces six binaries in `target/release/`:
`reth-primary`, `reth-baseline`, `reth-backup`,
`ira-trace-collector`, `io-trace`, `block-size`.

A clean build takes roughly five minutes on a modern workstation. The
workspace pins reth to commit
`62abfdaeb54e8a205a8ee085ddebd56047d93374` (Oct 2024) and requires
Rust 1.88+ with edition 2024 (declared in `Cargo.toml`).

### Step 2 - generate Run #1 CSVs

```sh
export RETH_DATADIR=/path/to/reth-datadir
export IRA_HINTS=/path/to/hints-out
export IRA_STATE_HASHES=/path/to/state-hashes-out
export IRA_OUTPUT=/path/to/ira-rs/data
sudo bash scripts/benchmark-cold-cache.sh
```

`benchmark-cold-cache.sh` runs `reth-baseline`, then `reth-primary`
(producing hints + state hashes), then `reth-backup`, each preceded by a
`sudo purge` to flush the OS page cache. CSV outputs land in `$IRA_OUTPUT`
with names matching `YYYY.MM.DD.reth-{baseline,primary,backup-*}-analysis-run.csv`.

### Step 3 - optional multi-run error bars

```sh
sudo bash scripts/benchmark-all.sh
```

Runs each configuration twice more (`run2` and `run3`) across thread counts
`{seq, 2, 4, 8, 12, 16, 24, 32, 48, 64}`. Supports `--resume CONFIG:RUN` to
restart mid-sweep.

### Step 4 - regenerate macros and figures

```sh
cd artifact
python3 scripts/generate_numbers.py
```

Same as Quick Start, but now consuming the freshly-generated CSVs.

### Environment variables

| Variable               | Used by                          | Purpose |
|------------------------|----------------------------------|---------|
| `RETH_DATADIR`         | `benchmark-*.sh`                 | Path to synced reth archive datadir |
| `IRA_HINTS`            | `benchmark-*.sh`, source scripts | Output/input directory for hint files |
| `IRA_STATE_HASHES`     | `benchmark-cold-cache.sh`        | Output directory for state-hash files |
| `IRA_OUTPUT`           | `benchmark-*.sh`, all generators | CSV output directory (typically `./data`) |
| `IRA_BIN_DIR`          | `benchmark-*.sh`                 | Path to release binaries (default `target/release`) |
| `IRA_TRACES`           | `scripts/*.py` trace consumers   | Glob for raw parquet traces |
| `ARTIFACT_DATA`        | `artifact/scripts/*.py`          | Override CSV input directory (default `./data`) |
| `ARTIFACT_NUMBERS_TEX` | `artifact/scripts/generate_numbers.py` | Override `numbers.tex` output path |

## Number-to-script mapping

Each headline number in the paper expands from a `\newcommand` macro in
`numbers.tex`. The table below maps the headline claims to their macro
name, the producing script under `artifact/scripts/`, and the CSV inputs
under `data/`.

| Paper claim | Macro | Script | Input CSV |
|---|---|---|---|
| 5.2x aggregate sequential speedup | `\EvalWallSpeedupSequential` | `process_evaluation.py` | `2026.01.15.reth-baseline-analysis-run.csv`, `2026.01.16.reth-backup-sequential-analysis-run.csv` |
| 24.9x median per-block sequential | `\EvalSpeedupSequentialMedian` | `process_evaluation.py` | sequential backup + baseline CSVs |
| 23.6x at 16 threads | `\EvalWallSpeedupParallelSixteen` | `process_evaluation.py` | `2026.01.16.reth-backup-parallel16-analysis-run.csv` |
| 25.9x at 64 threads | `\EvalWallSpeedupParallelSixtyFour` | `process_evaluation.py` | `2026.01.16.reth-backup-parallel64-analysis-run.csv` |
| 10.9% primary overhead | `\EvalHintOverheadPct` | `process_evaluation.py` | `2026.01.15.reth-primary-analysis-run.csv` |
| 67.9% I/O dominance | `\IoTimePct` | `process_io_trace.py` | `2026.01.27.io-trace.csv` |
| 57% no-history-lookup keys | `\SourceNoHistoryPct` | `process_source_annotations.py` | `2026.01.28.source-byte-distribution.csv` |
| 100,800 blocks evaluated | `\EvalBlockCount` | `process_evaluation.py` | (all evaluation CSVs) |

`generate_numbers.py` orchestrates all eight `process_*.py` scripts and
emits the full 229-macro `numbers.tex` in one invocation.

## What is not in this repository

Per the paper's Open Science section, two large inputs are not
redistributed:

- **Reth archive datadir** (~3 TB). Anyone can regenerate this by running
  reth at the pinned commit against mainnet up to block 24,120,246.
- **Raw parquet traces** (~12 GB) emitted by `ira-trace-collector`. Used
  only by the `scripts/measure-*.py` and `scripts/generate-*.py` helpers
  that produce the bundled CSVs from raw traces. Set `IRA_TRACES` to a
  parquet glob if you regenerate.

Two intermediate outputs are large but reproducible from a primary run:

- **Hint files** (~14 GB). Output of `reth-primary`; consumed by
  `reth-backup`. A Zenodo deposit is planned.
- **State-hash files** (~788 MB). Output of `reth-primary`; consumed by
  `reth-backup` for post-block state-root verification.

## Dependencies

- **Rust 1.88+** with edition 2024 (workspace pins `rust-version = "1.88"`).
- **Python 3.10+**. Install with `pip install -r requirements.txt`.
- **reth** at commit `62abfdaeb54e8a205a8ee085ddebd56047d93374`. Fetched
  automatically by `cargo build` via the workspace `Cargo.toml`.
- **macOS or Linux**. The `benchmark-*.sh` scripts use `sudo purge` to
  flush page cache on macOS; substitute
  `echo 3 > /proc/sys/vm/drop_caches` on Linux.

## License

MIT. See `LICENSE` and `AUTHORS`.

## Citation

```bibtex
@inproceedings{bhat2026ira,
  title     = {Ira: Efficient Transaction Replay for Ethereum},
  author    = {Bhat, Adithya and Shah, Harshal and Minaei, Mohsen},
  booktitle = {35th USENIX Security Symposium (USENIX Security 26)},
  year      = {2026},
  publisher = {USENIX Association},
  eprint    = {2601.21286},
  archivePrefix = {arXiv},
  url       = {https://arxiv.org/abs/2601.21286}
}
```

DOI and proceedings URL will be added after publication.

## Anonymous review mirror

During review, the artifact was hosted at
`https://anonymous.4open.science/r/ira-rs-392A`. This GitHub repository is
the canonical, de-anonymized version; the anonymized mirror is preserved
only as a stable identifier for the review record.
