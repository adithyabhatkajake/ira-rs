# Ira-L Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              IRA-L ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                               PRIMARY NODE                                   │
│  (reth-primary)                                                             │
│                                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────┐        │
│  │   Block     │───▶│   EVM Executor   │───▶│   State Changes     │        │
│  │  (from P2P) │    │  + KeyCollector  │    │                     │        │
│  └─────────────┘    │   (Inspector)    │    └─────────────────────┘        │
│                     └────────┬─────────┘                                    │
│                              │ Intercepts:                                  │
│                              │ • SLOAD/SSTORE → storage_keys                │
│                              │ • CALL/STATICCALL → bytecode_addresses       │
│                              │ • BALANCE/EXTCODE → account_addresses        │
│                              ▼                                              │
│                     ┌──────────────────┐                                    │
│                     │ SourceTrackingDB │  Determines for each key:          │
│                     │                  │  • SOURCE_IN_PLAIN_STATE (0)       │
│                     │                  │  • SOURCE_NOT_YET_WRITTEN (1)      │
│                     │                  │  • SOURCE_IN_CHANGESET (2)         │
│                     └────────┬─────────┘                                    │
│                              ▼                                              │
│                     ┌──────────────────┐    ┌─────────────────────┐        │
│                     │   BlockHints     │───▶│  Zstd Compress +    │        │
│                     │  (per block)     │    │  Write to redb      │        │
│                     └──────────────────┘    └─────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Hints transmitted alongside block
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                               BACKUP NODE                                    │
│  (reth-backup)                                                              │
│                                                                             │
│  Phase 1: Initial Prefetch (parallel, fills 8GB buffer)                     │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  rayon::par_iter over first ~3000 blocks                        │       │
│  │  Each thread: read hints → load state from MDBX → build CacheDB │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  Phase 2: Pipelined Execution                                               │
│  ┌─────────────────────┐         ┌─────────────────────────────┐           │
│  │  Prefetcher Thread  │────────▶│     Executor Thread         │           │
│  │                     │ channel │                             │           │
│  │  For each batch:    │         │  While prefetched blocks:   │           │
│  │  1. Read hints      │         │  1. Pop CacheDB from buffer │           │
│  │  2. Sort keys       │         │  2. Execute block (EVM)     │           │
│  │  3. Load from MDBX  │         │  3. Discard CacheDB         │           │
│  │  4. Send CacheDB    │         │                             │           │
│  └─────────────────────┘         └─────────────────────────────┘           │
│         │                                                                   │
│         │ --parallel-prefetch N                                            │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  Parallel MDBX Reads (triggers concurrent page faults)          │       │
│  │  • Partition keys across N threads                              │       │
│  │  • Each thread: own provider → own cursor → parallel I/O        │       │
│  └─────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Hint Structure

```
BlockHints {
    block_number: u64,
    storage_keys: Vec<StorageKey>,     // address(20) + slot(32) + src(1) = 53 bytes
    bytecode_addresses: Vec<Address>,  // 20 bytes each
    account_addresses: Vec<Address>,   // 20 bytes each
}
```

### Source Byte Optimization

| Value | Meaning | Frequency | Backup Action |
|-------|---------|-----------|---------------|
| 0 | SOURCE_IN_PLAIN_STATE | ~90% | Fast path: read current value from PlainStorageState |
| 1 | SOURCE_NOT_YET_WRITTEN | ~5% | Value is zero, skip I/O entirely |
| 2 | SOURCE_IN_CHANGESET | ~5% | Needs historical lookup via changeset |

### Storage Format

- **Database**: redb (mmap'd B-tree)
- **Compression**: Zstd
- **Size**: ~10KB compressed per block

## Key Components

### Primary (reth-primary)

| File | Purpose |
|------|---------|
| `main.rs` | Block execution loop, hint generation orchestration |
| `collector.rs` | `KeyCollector` inspector that intercepts EVM opcodes |
| `source_tracking_db.rs` | Determines source byte for each storage key |

### Backup (reth-backup)

| File | Purpose |
|------|---------|
| `main.rs` | Two-phase pipelined execution |
| `hinted_db.rs` | `load_state_from_hints_batch` and parallel variant |

### Common (ira-common)

| File | Purpose |
|------|---------|
| `types.rs` | `BlockHints`, `StorageKey`, `AddressKey` definitions |
| `hint_format.rs` | Hint serialization, redb storage |
| `executor.rs` | Shared EVM execution utilities |

## Key Design Decisions

1. **Inspector-based collection**: Uses revm's `Inspector` trait to intercept EVM opcodes and collect accessed keys without modifying execution

2. **Source byte optimization**: Primary determines WHERE to read each key from, saving backup from expensive history lookups

3. **Sorted batch reads**: Keys are sorted before reading to convert random I/O → sequential I/O

4. **Pipelined architecture**: Prefetcher and executor run concurrently, overlapping I/O with computation

5. **Parallel page faults**: Multiple threads trigger concurrent MDBX page faults for faster cold-cache reads

## Data Flow

```
Block Execution (Primary):
  1. Receive block from P2P
  2. Execute transactions with KeyCollector inspector
  3. Inspector intercepts: SLOAD, SSTORE, CALL, BALANCE, etc.
  4. Collect unique (address, slot) pairs for storage
  5. Collect addresses for bytecode and account info
  6. Query history index to determine source byte for each key
  7. Serialize and compress hints
  8. Write to redb database

Block Replay (Backup):
  1. Read hints from redb (batch read, single transaction)
  2. Sort all keys across batch for sequential I/O
  3. Load state from MDBX:
     - SOURCE_IN_PLAIN_STATE: Read from PlainStorageState
     - SOURCE_NOT_YET_WRITTEN: Return zero (no I/O)
     - SOURCE_IN_CHANGESET: Read from historical provider
  4. Build CacheDB with preloaded state
  5. Execute block using CacheDB (no I/O during execution)
  6. Discard CacheDB after execution
```

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Hint size per block | ~10KB compressed |
| Primary overhead | 28% |
| Backup speedup (sequential) | 5.3x |
| Backup speedup (parallel-64) | 25x |
| Median per-block speedup | 25x |
| P99 per-block speedup | 103x |
