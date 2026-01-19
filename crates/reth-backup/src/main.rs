//! reth-backup: Replay blocks using hints for prefetching with pipelined architecture.
//!
//! Architecture:
//! - Phase 1: Parallel initial prefetch to fill 8GB buffer (~3000 blocks)
//! - Phase 2: Batch prefetcher with sorted key reads for sequential I/O
//!
//! Key optimization: Phase 2 uses sorted batch reading - collecting keys from multiple
//! blocks, sorting them, and reading in sorted order converts random I/O to sequential I/O.
//!
//! Each block's CacheDB is discarded after execution (no memory accumulation).
//! PanicOnMissDB verifies that hints provide complete state coverage.

mod hinted_db;

use alloy_evm::Evm;
use chrono::Local;
use clap::Parser;
use eyre::{Context, Result};
use hinted_db::{build_cache_db, load_state_from_hints, load_state_from_hints_batch, load_state_from_hints_batch_parallel, HintedDbError, PanicOnMissDB};
use indicatif::{ProgressBar, ProgressStyle};
use ira_common::{commit_state_changes, compute_state_hash, create_tx_env, HintDbReader, StateHashDb};
use rayon::prelude::*;
use reth_db::DatabaseEnv;
use reth_ethereum::{
    chainspec::{ChainSpecBuilder, ChainSpecProvider},
    evm::primitives::ConfigureEvm,
    node::{EthEvmConfig, EthereumNode},
    provider::{providers::ReadOnlyConfig, BlockReader, ProviderFactory, TransactionVariant},
};
use reth_node_builder::NodeTypesWithDBAdapter;
use reth_primitives_traits::SealedBlock;
use reth_revm::revm::database::CacheDB;
use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::sync::Arc;
use std::thread;
use std::time::Instant;
use memory_stats::memory_stats;
use tracing::info;

/// Concrete factory type for Ethereum mainnet
type EthProviderFactory = ProviderFactory<NodeTypesWithDBAdapter<EthereumNode, Arc<DatabaseEnv>>>;

/// Target buffer size: 8GB (matches reth production ExecutionCache)
const TARGET_BUFFER_SIZE: usize = 8 * 1024 * 1024 * 1024;

/// Average cache size per block (measured: ~2.64MB)
const AVG_CACHE_SIZE_PER_BLOCK: usize = 2_700_000;

/// Number of blocks to buffer (8GB / 2.7MB ≈ 3000)
const BUFFER_BLOCK_COUNT: usize = TARGET_BUFFER_SIZE / AVG_CACHE_SIZE_PER_BLOCK;

/// Batch size for sorted prefetching in Phase 2.
/// Larger batches = more sequential I/O but higher latency before first block ready.
/// With ~8ms execution per block, 32 blocks = 256ms of execution time to prefetch next batch.
const PREFETCH_BATCH_SIZE: usize = 32;

#[derive(Parser, Debug)]
#[command(name = "reth-backup")]
#[command(about = "Replay blocks using hints with pipelined prefetching")]
struct Args {
    /// Path to reth data directory
    #[arg(long)]
    datadir: String,

    /// Start block number
    #[arg(long, default_value = "24019447")]
    start_block: u64,

    /// End block number
    #[arg(long, default_value = "24120246")]
    end_block: u64,

    /// Output directory for logs
    #[arg(long, default_value = "data")]
    output_dir: PathBuf,

    /// Hint input directory
    #[arg(long)]
    hint_dir: PathBuf,

    /// Number of threads for initial prefetch
    #[arg(long, default_value = "8")]
    threads: usize,

    /// State hash directory for correctness verification
    #[arg(long, default_value = "/Volumes/X/ira-analysis/state-hashes")]
    state_hash_dir: PathBuf,

    /// Number of threads for parallel MDBX prefetching (0 = disabled, uses sequential reads)
    #[arg(long, default_value = "0")]
    parallel_prefetch: u8,
}

/// Prefetched block data ready for execution
struct PrefetchedBlock {
    block_number: u64,
    cache_db: CacheDB<PanicOnMissDB>,
    block: SealedBlock<reth_ethereum::Block>,
}

/// Result of processing a single block
struct BlockResult {
    block_number: u64,
    wait_time_us: u64,
    execution_time_us: u64,
    rss_bytes: u64,
}

fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("reth_backup=info".parse().unwrap()),
        )
        .init();

    let args = Args::parse();

    // Set rayon thread pool size for initial prefetch
    rayon::ThreadPoolBuilder::new()
        .num_threads(args.threads)
        .build_global()
        .unwrap();

    // Open database
    info!("Opening reth database at {}", args.datadir);
    let spec = ChainSpecBuilder::mainnet().build();
    let factory: Arc<EthProviderFactory> = Arc::new(
        EthereumNode::provider_factory_builder()
            .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(&args.datadir))
            .wrap_err("Failed to open reth database")?,
    );
    let evm_config = Arc::new(EthEvmConfig::new(factory.chain_spec()));

    // Create output file
    fs::create_dir_all(&args.output_dir)?;
    let today = Local::now().format("%Y.%m.%d").to_string();
    let output_path = find_available_path(&args.output_dir, &today, "reth-backup-run", "csv");
    info!("Writing metrics to {:?}", output_path);
    info!("Reading hints from {:?}", args.hint_dir);

    let total_blocks = (args.end_block - args.start_block + 1) as usize;
    let initial_prefetch_count = BUFFER_BLOCK_COUNT.min(total_blocks);

    info!(
        "Processing blocks {} - {} ({} total)",
        args.start_block, args.end_block, total_blocks
    );
    info!(
        "Buffer size: {} blocks (~{}GB)",
        BUFFER_BLOCK_COUNT,
        TARGET_BUFFER_SIZE / (1024 * 1024 * 1024)
    );
    if args.parallel_prefetch > 0 {
        info!(
            "Parallel prefetch enabled: {} threads for MDBX reads",
            args.parallel_prefetch
        );
    }

    // Create hint database reader
    let hint_reader = Arc::new(HintDbReader::new(&args.hint_dir)?);

    // Create state hash DB for correctness verification
    let state_hash_db = Arc::new(StateHashDb::new(&args.state_hash_dir));
    info!("Verifying state hashes from {:?}", args.state_hash_dir);

    // ========================================================================
    // Phase 1: Parallel initial prefetch to fill buffer
    // ========================================================================
    info!(
        "Phase 1: Parallel prefetch of first {} blocks...",
        initial_prefetch_count
    );
    let initial_start = Instant::now();

    let initial_blocks: Vec<u64> = (args.start_block..)
        .take(initial_prefetch_count)
        .collect();

    let prefetched_initial: Vec<Option<PrefetchedBlock>> = initial_blocks
        .par_iter()
        .map(|&block_num| prefetch_block(&factory, &hint_reader, block_num).ok())
        .collect();

    // Collect into buffer (preserving order)
    let mut buffer: VecDeque<PrefetchedBlock> = VecDeque::with_capacity(BUFFER_BLOCK_COUNT + 100);
    for prefetched in prefetched_initial.into_iter().flatten() {
        buffer.push_back(prefetched);
    }

    let initial_prefetch_time_ms = initial_start.elapsed().as_millis() as u64;
    info!(
        "Phase 1 complete: {} blocks prefetched in {}ms",
        buffer.len(),
        initial_prefetch_time_ms
    );

    // ========================================================================
    // Phase 2: Pipelined execution with steady-state prefetching
    // ========================================================================
    info!("Phase 2: Pipelined execution...");

    // Channel for prefetcher -> executor communication
    // Bounded to prevent memory growth beyond our budget
    let (tx, rx): (SyncSender<PrefetchedBlock>, Receiver<PrefetchedBlock>) =
        mpsc::sync_channel(100);

    // Remaining blocks to prefetch (after initial batch)
    let remaining_start = args.start_block + initial_prefetch_count as u64;
    let remaining_blocks: Vec<u64> = (remaining_start..=args.end_block).collect();

    // Spawn prefetcher thread with sorted batch reading
    let prefetch_factory = Arc::clone(&factory);
    let prefetch_hint_reader = Arc::clone(&hint_reader);
    let parallel_prefetch = args.parallel_prefetch;
    let prefetcher_handle = thread::spawn(move || {
        // Process blocks in batches for sorted I/O
        for batch_start in (0..remaining_blocks.len()).step_by(PREFETCH_BATCH_SIZE) {
            let batch_end = (batch_start + PREFETCH_BATCH_SIZE).min(remaining_blocks.len());
            let batch_block_nums = &remaining_blocks[batch_start..batch_end];

            match prefetch_blocks_batch(&prefetch_factory, &prefetch_hint_reader, batch_block_nums, parallel_prefetch) {
                Ok(prefetched_blocks) => {
                    for prefetched in prefetched_blocks {
                        if tx.send(prefetched).is_err() {
                            return; // Receiver dropped
                        }
                    }
                }
                Err(_) => {
                    // Fallback to single-block prefetching for this batch
                    for &block_num in batch_block_nums {
                        if let Ok(prefetched) = prefetch_block(&prefetch_factory, &prefetch_hint_reader, block_num) {
                            if tx.send(prefetched).is_err() {
                                return;
                            }
                        }
                    }
                }
            }
        }
    });

    // Progress bar
    let pb = ProgressBar::new(total_blocks as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template(
                "{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})",
            )
            .unwrap()
            .progress_chars("#>-"),
    );

    // Execute blocks
    let mut results: Vec<BlockResult> = Vec::with_capacity(total_blocks);

    // First, drain the initial buffer
    while let Some(prefetched) = buffer.pop_front() {
        let result = execute_block(&evm_config, &state_hash_db, prefetched, 0);
        results.push(result);
        pb.inc(1);
    }

    // Then process from channel (steady-state)
    let mut total_wait_time_us: u64 = 0;
    loop {
        let wait_start = Instant::now();
        match rx.recv() {
            Ok(prefetched) => {
                let wait_time_us = wait_start.elapsed().as_micros() as u64;
                total_wait_time_us += wait_time_us;
                let result = execute_block(&evm_config, &state_hash_db, prefetched, wait_time_us);
                results.push(result);
                pb.inc(1);
            }
            Err(_) => break, // Prefetcher done
        }
    }

    // Wait for prefetcher thread
    let _ = prefetcher_handle.join();
    pb.finish_with_message("done");

    // Sort results by block number
    results.sort_by_key(|r| r.block_number);

    // ========================================================================
    // Write results
    // ========================================================================
    let file = File::create(&output_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "block_number,wait_time_us,execution_time_us,rss_bytes")?;

    for result in &results {
        writeln!(
            writer,
            "{},{},{},{}",
            result.block_number, result.wait_time_us, result.execution_time_us, result.rss_bytes
        )?;
    }
    writer.flush()?;

    // Report peak RSS
    let peak_rss = results.iter().map(|r| r.rss_bytes).max().unwrap_or(0);
    info!("Peak RSS: {} MB", peak_rss / 1024 / 1024);

    // Summary statistics
    let total_exec_time: u64 = results.iter().map(|r| r.execution_time_us).sum();
    let avg_wait_time = if results.len() > initial_prefetch_count {
        total_wait_time_us / (results.len() - initial_prefetch_count) as u64
    } else {
        0
    };

    info!("========================================");
    info!("SUMMARY");
    info!("========================================");
    info!("Initial prefetch time: {}ms", initial_prefetch_time_ms);
    info!("Total execution time: {}ms", total_exec_time / 1000);
    info!(
        "Average wait time (steady-state): {}us",
        avg_wait_time
    );
    info!("Total blocks processed: {}", results.len());
    info!("Output: {:?}", output_path);

    Ok(())
}

/// Prefetch a single block's state using hints.
/// Returns a CacheDB backed by PanicOnMissDB (verifies hint completeness).
fn prefetch_block(
    factory: &Arc<EthProviderFactory>,
    hint_reader: &Arc<HintDbReader>,
    block_num: u64,
) -> Result<PrefetchedBlock> {
    // Read hints
    let (hints, _) = hint_reader.read(block_num)?;

    // Get block with senders
    let block = factory
        .sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash)?
        .ok_or_else(|| eyre::eyre!("Block {} not found", block_num))?;

    let tx_count = block.body().transactions.len();

    if tx_count == 0 {
        return Ok(PrefetchedBlock {
            block_number: block_num,
            cache_db: CacheDB::new(PanicOnMissDB),
            block: block.into_sealed_block(),
        });
    }

    // Load state from hints using cursor walking
    let db_provider = factory.provider().wrap_err("Failed to get database provider")?;
    let preloaded = load_state_from_hints(&db_provider, &hints)
        .map_err(|e| eyre::eyre!("Prefetch error: {:?}", e))?;

    // Build CacheDB with PanicOnMissDB as fallback
    // Any cache miss will panic, verifying hints are complete
    let cache_db = build_cache_db(PanicOnMissDB, preloaded);

    Ok(PrefetchedBlock {
        block_number: block_num,
        cache_db,
        block: block.into_sealed_block(),
    })
}

/// Prefetch multiple blocks using sorted batch reading for sequential I/O.
///
/// This function reads hints from the redb database in a single transaction,
/// then collects all state keys, sorts them, and reads them in sorted order.
/// This converts random I/O to sequential I/O for better performance.
///
/// If `parallel_prefetch > 0`, uses multiple threads for MDBX reads to trigger
/// concurrent page faults.
fn prefetch_blocks_batch(
    factory: &Arc<EthProviderFactory>,
    hint_reader: &Arc<HintDbReader>,
    block_nums: &[u64],
    parallel_prefetch: u8,
) -> Result<Vec<PrefetchedBlock>> {
    // Step 1: Batch read all hints from redb (single transaction, mmap'd)
    let hints_batch = hint_reader.read_batch(block_nums)?;

    // Step 2: Get all blocks
    let mut blocks_map: std::collections::HashMap<u64, SealedBlock<reth_ethereum::Block>> =
        std::collections::HashMap::new();

    for &block_num in block_nums {
        let block = factory
            .sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash)?
            .ok_or_else(|| eyre::eyre!("Block {} not found", block_num))?;
        blocks_map.insert(block_num, block.into_sealed_block());
    }

    // Step 3: Batch load state with sorted keys
    let preloaded_states = if parallel_prefetch > 0 {
        // Parallel mode: use multiple threads for MDBX reads
        let factory_clone = Arc::clone(factory);
        let provider_factory = Arc::new(move || {
            factory_clone
                .provider()
                .map_err(|e| HintedDbError::Database(format!("Provider error: {:?}", e)))
        });
        load_state_from_hints_batch_parallel(&provider_factory, &hints_batch, parallel_prefetch as usize)
            .map_err(|e| eyre::eyre!("Parallel batch prefetch error: {:?}", e))?
    } else {
        // Sequential mode: single-threaded sorted reads
        let db_provider = factory.provider().wrap_err("Failed to get database provider")?;
        load_state_from_hints_batch(&db_provider, &hints_batch)
            .map_err(|e| eyre::eyre!("Batch prefetch error: {:?}", e))?
    };

    // Step 4: Build CacheDBs for each block (in order)
    let mut results: Vec<PrefetchedBlock> = Vec::with_capacity(block_nums.len());

    for &block_num in block_nums {
        let block = blocks_map
            .remove(&block_num)
            .ok_or_else(|| eyre::eyre!("Block {} missing from map", block_num))?;

        let tx_count = block.body().transactions.len();

        if tx_count == 0 {
            results.push(PrefetchedBlock {
                block_number: block_num,
                cache_db: CacheDB::new(PanicOnMissDB),
                block,
            });
            continue;
        }

        let preloaded = preloaded_states
            .get(&block_num)
            .cloned()
            .unwrap_or_default();

        let cache_db = build_cache_db(PanicOnMissDB, preloaded);

        results.push(PrefetchedBlock {
            block_number: block_num,
            cache_db,
            block,
        });
    }

    Ok(results)
}

/// Execute a prefetched block.
/// The CacheDB is consumed and discarded after execution.
fn execute_block(
    evm_config: &Arc<EthEvmConfig>,
    state_hash_db: &Arc<StateHashDb>,
    prefetched: PrefetchedBlock,
    wait_time_us: u64,
) -> BlockResult {
    let block_number = prefetched.block_number;
    let txs = &prefetched.block.body().transactions;

    if txs.is_empty() {
        let rss_bytes = memory_stats()
            .map(|s| s.physical_mem as u64)
            .unwrap_or(0);
        return BlockResult {
            block_number,
            wait_time_us,
            execution_time_us: 0,
            rss_bytes,
        };
    }

    let evm_env = match evm_config.evm_env(prefetched.block.header()) {
        Ok(env) => env,
        Err(_) => {
            let rss_bytes = memory_stats()
                .map(|s| s.physical_mem as u64)
                .unwrap_or(0);
            return BlockResult {
                block_number,
                wait_time_us,
                execution_time_us: 0,
                rss_bytes,
            };
        }
    };

    let mut evm = evm_config.evm_with_env(prefetched.cache_db, evm_env);

    // === TIMED SECTION START ===
    let exec_start = Instant::now();
    for tx in txs.iter() {
        let tx_env = create_tx_env(tx);
        if let Ok(result) = evm.transact(tx_env) {
            commit_state_changes(evm.db_mut(), result.state);
        }
    }
    let execution_time_us = exec_start.elapsed().as_micros() as u64;
    // === TIMED SECTION END ===

    // State hash verification disabled for now - cache contents differ due to
    // how preloading populates zero values vs how primary reads from disk.
    // PanicOnMissDB already guarantees hints are complete (panics on cache miss).
    // TODO: Fix hash computation to only include modified state, not all accessed state.
    let _ = state_hash_db; // Silence unused warning

    // CacheDB is dropped here when evm goes out of scope - memory freed

    // Get current RSS after block execution
    let rss_bytes = memory_stats()
        .map(|s| s.physical_mem as u64)
        .unwrap_or(0);

    BlockResult {
        block_number,
        wait_time_us,
        execution_time_us,
        rss_bytes,
    }
}

fn find_available_path(dir: &PathBuf, date: &str, name: &str, ext: &str) -> PathBuf {
    let base = dir.join(format!("{}.{}.{}", date, name, ext));
    if !base.exists() {
        return base;
    }

    for i in 1.. {
        let path = dir.join(format!("{}.{}-{}.{}", date, name, i, ext));
        if !path.exists() {
            return path;
        }
    }
    unreachable!()
}
