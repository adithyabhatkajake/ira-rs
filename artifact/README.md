# Ira Artifact — Paper Number Regeneration

This directory bundles the paper-side processing scripts that regenerate every
`\Eval*` / `\Source*` / `\Io*` / etc. macro and every figure used in the
USENIX Security '26 paper from the CSVs in `../data/`.

No archive node or `/Volumes/X` data is required.

## Layout

```
artifact/
├── scripts/         process_*.py + generate_numbers.py (orchestrator)
├── generated/       output: numbers.tex (229 macros)
└── figures/         output: all paper figure PDFs
```

Inputs read from `../data/` (the repo's CSVs).

## Reproduce

```sh
cd artifact
python3 scripts/generate_numbers.py
```

That regenerates `generated/numbers.tex` and all `figures/*.pdf`.

## Override paths (optional)

```sh
ARTIFACT_DATA=/path/to/csvs python3 scripts/generate_numbers.py
ARTIFACT_NUMBERS_TEX=/tmp/numbers.tex python3 scripts/generate_numbers.py
```

## Dependencies

Python 3.10+, `matplotlib`, `numpy`. No reth/Rust toolchain needed for
artifact reproduction — those are only required to regenerate the upstream
CSVs from a live Ethereum archive node (see top-level README).
