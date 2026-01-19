//! reth-baseline: Replay blocks with cross-block caching (production-like).
//!
//! This benchmark replays blocks sequentially with a cross-block cache that
//! persists state across blocks, simulating production reth behavior where
//! block N+1 benefits from cached state from block N.

mod cached_state_db;
mod cross_block_cache;

use alloy_evm::Evm;
use cached_state_db::CachedStateDb;
use chrono::Local;
use clap::Parser;
use cross_block_cache::CrossBlockCache;
use eyre::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use ira_common::{commit_state_changes, create_tx_env};
use reth_db::DatabaseEnv;
use reth_ethereum::{
    chainspec::{ChainSpecBuilder, ChainSpecProvider},
    evm::primitives::ConfigureEvm,
    node::{EthEvmConfig, EthereumNode},
    provider::{providers::ReadOnlyConfig, BlockReader, ProviderFactory, TransactionVariant},
};
use reth_node_builder::NodeTypesWithDBAdapter;
use reth_revm::{database::StateProviderDatabase, revm::database::CacheDB};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use memory_stats::memory_stats;
use tracing::info;

/// Concrete factory type for Ethereum mainnet
type EthProviderFactory = ProviderFactory<NodeTypesWithDBAdapter<EthereumNode, Arc<DatabaseEnv>>>;

#[derive(Parser, Debug)]
#[command(name = "reth-baseline")]
#[command(about = "Replay blocks with cross-block caching (production-like)")]
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
}

/// Result of processing a single block
struct BlockResult {
    block_number: u64,
    execution_time_us: u64,
    rss_bytes: u64,
}

fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("reth_baseline=info".parse().unwrap()),
        )
        .init();

    let args = Args::parse();

    // Open database
    info!("Opening reth database at {}", args.datadir);
    let spec = ChainSpecBuilder::mainnet().build();
    let factory: EthProviderFactory = EthereumNode::provider_factory_builder()
        .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(&args.datadir))
        .wrap_err("Failed to open reth database")?;
    let evm_config = EthEvmConfig::new(factory.chain_spec());

    // Create output file
    fs::create_dir_all(&args.output_dir)?;
    let today = Local::now().format("%Y.%m.%d").to_string();
    let output_path = find_available_path(&args.output_dir, &today, "reth-baseline-run", "csv");
    info!("Writing output to {:?}", output_path);
    info!(
        "Processing blocks {} - {} SEQUENTIALLY with cross-block caching",
        args.start_block, args.end_block
    );

    // Progress bar
    let total_blocks = args.end_block - args.start_block + 1;
    let pb = ProgressBar::new(total_blocks);
    pb.set_style(
        ProgressStyle::default_bar()
            .template(
                "{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})",
            )
            .unwrap()
            .progress_chars("#>-"),
    );

    // Cross-block cache - persists state across blocks
    let mut cross_block_cache = CrossBlockCache::new();

    // Process blocks sequentially
    let mut results = Vec::with_capacity(total_blocks as usize);

    for block_num in args.start_block..=args.end_block {
        let result = process_block(&factory, &evm_config, &mut cross_block_cache, block_num);
        results.push(result);

        // Update progress
        let count = block_num - args.start_block;
        if count % 100 == 0 {
            pb.set_position(count);
        }
    }

    pb.finish_with_message("done");

    // Report cache stats
    let (accounts, storage, contracts) = cross_block_cache.stats();
    info!(
        "Final cache size: {} accounts, {} storage slots, {} contracts",
        accounts, storage, contracts
    );

    // Write results to file
    let file = File::create(&output_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "block_number,execution_time_us,rss_bytes")?;

    for result in &results {
        writeln!(writer, "{},{},{}", result.block_number, result.execution_time_us, result.rss_bytes)?;
    }
    writer.flush()?;

    // Report peak RSS
    let peak_rss = results.iter().map(|r| r.rss_bytes).max().unwrap_or(0);
    info!("Peak RSS: {} MB", peak_rss / 1024 / 1024);

    info!("Completed! Output written to {:?}", output_path);
    Ok(())
}

fn process_block(
    factory: &EthProviderFactory,
    evm_config: &EthEvmConfig,
    cross_block_cache: &mut CrossBlockCache,
    block_num: u64,
) -> BlockResult {
    let execution_time_us = match process_block_inner(factory, evm_config, cross_block_cache, block_num) {
        Ok(time) => time,
        Err(_) => 0,
    };

    // Get current RSS after block execution
    let rss_bytes = memory_stats()
        .map(|s| s.physical_mem as u64)
        .unwrap_or(0);

    BlockResult {
        block_number: block_num,
        execution_time_us,
        rss_bytes,
    }
}

fn process_block_inner(
    factory: &EthProviderFactory,
    evm_config: &EthEvmConfig,
    cross_block_cache: &mut CrossBlockCache,
    block_num: u64,
) -> Result<u64> {
    // Get block with senders
    let block = factory
        .sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash)?
        .ok_or_else(|| eyre::eyre!("Block {} not found", block_num))?;

    // Skip empty blocks
    let txs = &block.body().transactions;
    if txs.is_empty() {
        return Ok(0);
    }

    // Get state at parent block
    let parent_state = factory.history_by_block_number(block_num.saturating_sub(1))?;
    let base_db = StateProviderDatabase::new(parent_state);

    // Clone the cache state after execution (extracted before dropping to avoid borrow conflict)
    let cache_state;
    let execution_time;

    {
        // Use layered read-through caching:
        // CacheDB -> CachedStateDb (checks CrossBlockCache) -> StateProviderDatabase (disk)
        // This avoids copying the entire cache into each block's CacheDB
        let cached_state_db = CachedStateDb::new(cross_block_cache, base_db);
        let cached_db = CacheDB::new(cached_state_db);

        // Get EVM environment
        let evm_env = evm_config
            .evm_env(block.header())
            .wrap_err("Failed to create EVM env")?;

        // Create EVM without inspector
        let mut evm = evm_config.evm_with_env(cached_db, evm_env);

        // Execute all transactions and measure time
        let start = Instant::now();

        for tx in txs.iter() {
            let tx_env = create_tx_env(tx);
            match evm.transact(tx_env) {
                Ok(result) => {
                    commit_state_changes(evm.db_mut(), result.state);
                }
                Err(_) => {}
            }
        }

        execution_time = start.elapsed().as_micros() as u64;

        // Clone the cache state before dropping EVM (to release borrow of cross_block_cache)
        cache_state = evm.db().cache.clone();
    } // EVM and CachedStateDb dropped here, releasing immutable borrow

    // Now we can mutably borrow cross_block_cache to merge the touched state
    cross_block_cache.merge_from_cache_state(&cache_state);

    Ok(execution_time)
}

/// Find an available file path, appending -1, -2, etc. if file exists.
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
