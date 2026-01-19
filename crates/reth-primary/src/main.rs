//! reth-primary: Replay blocks, collect keys, and write hints.
//!
//! This program replays blocks sequentially, tracks all accessed keys using the
//! KeyCollector inspector, compresses them with zstd, and writes hint files to disk.
//! Sequential execution ensures accurate measurement of hint generation overhead.

mod collector;
mod source_tracking_db;

use alloy_consensus::Transaction as TxTrait;
use alloy_evm::Evm;
use chrono::Local;
use clap::Parser;
use collector::KeyCollector;
use eyre::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use ira_common::{commit_state_changes, compute_state_hash, create_tx_env, BlockHints, HintDbWriter, StateHashDb};
use reth_db::DatabaseEnv;
use reth_ethereum::{
    chainspec::{ChainSpecBuilder, ChainSpecProvider},
    evm::primitives::ConfigureEvm,
    node::{EthEvmConfig, EthereumNode},
    provider::{providers::ReadOnlyConfig, BlockReader, ProviderFactory, TransactionVariant},
};
use reth_node_builder::NodeTypesWithDBAdapter;
use reth_revm::{database::StateProviderDatabase, revm::database::CacheDB};
use source_tracking_db::determine_sources;
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
#[command(name = "reth-primary")]
#[command(about = "Replay blocks, collect keys, and write hints")]
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

    /// Hint output directory
    #[arg(long, default_value = "/Volumes/X/ira-analysis/hints")]
    hint_dir: PathBuf,

    /// Zstd compression level (1-22)
    #[arg(long, default_value = "3")]
    compression: i32,

    /// State hash output directory (for correctness verification)
    #[arg(long, default_value = "/Volumes/X/ira-analysis/state-hashes")]
    state_hash_dir: PathBuf,
}

/// Result of processing a single block
struct BlockResult {
    block_number: u64,
    execution_time_us: u64,
    hint_construction_time_us: u64,
    hint_write_time_us: u64,
    rss_bytes: u64,
}

fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("reth_primary=info".parse().unwrap()),
        )
        .init();

    let args = Args::parse();

    // Open database
    info!("Opening reth database at {}", args.datadir);
    let spec = ChainSpecBuilder::mainnet().build();
    let factory: Arc<EthProviderFactory> = Arc::new(
        EthereumNode::provider_factory_builder()
            .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(&args.datadir))
            .wrap_err("Failed to open reth database")?,
    );
    let evm_config = Arc::new(EthEvmConfig::new(factory.chain_spec()));

    // Create hint database writer
    let hint_writer = Arc::new(HintDbWriter::new(&args.hint_dir, args.compression)?);
    info!("Writing hints to {:?} (redb database)", args.hint_dir);

    // Create state hash DB for correctness verification
    let state_hash_db = Arc::new(StateHashDb::new(&args.state_hash_dir));
    info!("Writing state hashes to {:?}", args.state_hash_dir);

    // Create output file
    fs::create_dir_all(&args.output_dir)?;
    let today = Local::now().format("%Y.%m.%d").to_string();
    let output_path = find_available_path(&args.output_dir, &today, "reth-primary-run", "csv");
    info!("Writing metrics to {:?}", output_path);
    info!(
        "Processing blocks {} - {} (sequential)",
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

    // Process blocks sequentially
    let mut results: Vec<BlockResult> = Vec::with_capacity(total_blocks as usize);
    let start_time = Instant::now();

    for block_num in args.start_block..=args.end_block {
        let result = process_block(&factory, &evm_config, &hint_writer, &state_hash_db, block_num);
        results.push(result);
        pb.inc(1);

        // Log progress every 1000 blocks
        if results.len() % 1000 == 0 {
            let elapsed = start_time.elapsed().as_secs();
            let rate = results.len() as f64 / elapsed.max(1) as f64;
            info!("Progress: {}/{} blocks ({:.1} blocks/sec)", results.len(), total_blocks, rate);
        }
    }

    pb.finish_with_message("done");

    // Sort results by block number and write to file
    let mut sorted_results = results;
    sorted_results.sort_by_key(|r| r.block_number);

    let file = File::create(&output_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(
        writer,
        "block_number,execution_time_us,hint_construction_time_us,hint_write_time_us,rss_bytes"
    )?;

    for result in &sorted_results {
        writeln!(
            writer,
            "{},{},{},{},{}",
            result.block_number,
            result.execution_time_us,
            result.hint_construction_time_us,
            result.hint_write_time_us,
            result.rss_bytes
        )?;
    }
    writer.flush()?;

    // Report peak RSS
    let peak_rss = sorted_results.iter().map(|r| r.rss_bytes).max().unwrap_or(0);
    info!("Peak RSS: {} MB", peak_rss / 1024 / 1024);

    info!("Completed! Metrics written to {:?}", output_path);
    Ok(())
}

fn process_block(
    factory: &Arc<EthProviderFactory>,
    evm_config: &Arc<EthEvmConfig>,
    hint_writer: &Arc<HintDbWriter>,
    state_hash_db: &Arc<StateHashDb>,
    block_num: u64,
) -> BlockResult {
    let (execution_time_us, hint_construction_time_us, hint_write_time_us) =
        match process_block_inner(factory, evm_config, hint_writer, state_hash_db, block_num) {
            Ok((exec, construct, write)) => (exec, construct, write),
            Err(_) => (0, 0, 0),
        };

    // Get current RSS after block processing
    let rss_bytes = memory_stats()
        .map(|s| s.physical_mem as u64)
        .unwrap_or(0);

    BlockResult {
        block_number: block_num,
        execution_time_us,
        hint_construction_time_us,
        hint_write_time_us,
        rss_bytes,
    }
}

fn process_block_inner(
    factory: &Arc<EthProviderFactory>,
    evm_config: &Arc<EthEvmConfig>,
    hint_writer: &Arc<HintDbWriter>,
    state_hash_db: &Arc<StateHashDb>,
    block_num: u64,
) -> Result<(u64, u64, u64)> {
    // Get block with senders
    let block = factory
        .sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash)?
        .ok_or_else(|| eyre::eyre!("Block {} not found", block_num))?;

    // Handle empty blocks
    let txs = &block.body().transactions;
    if txs.is_empty() {
        // Still write empty hints file
        let hints = BlockHints::new(block_num);
        let write_start = Instant::now();
        hint_writer.write(&hints)?;
        let hint_write_time = write_start.elapsed().as_micros() as u64;
        // Write zero hash for empty blocks
        state_hash_db.write(block_num, alloy_primitives::B256::ZERO)?;
        return Ok((0, 0, hint_write_time));
    }

    // Get state at parent block
    let parent_state = factory.history_by_block_number(block_num.saturating_sub(1))?;
    let base_db = StateProviderDatabase::new(parent_state);
    let cached_db = CacheDB::new(base_db);

    // Get EVM environment
    let evm_env = evm_config
        .evm_env(block.header())
        .wrap_err("Failed to create EVM env")?;

    // Create key collector inspector
    let mut collector = KeyCollector::new();
    let collector_handle = collector.handle();

    // Create EVM with inspector
    let mut evm = evm_config.evm_with_env_and_inspector(cached_db, evm_env, &mut collector);

    // Execute all transactions
    let exec_start = Instant::now();

    for tx in txs.iter() {
        let tx_env = create_tx_env(tx);
        match evm.transact(tx_env) {
            Ok(result) => {
                commit_state_changes(evm.db_mut(), result.state);
            }
            Err(_) => {}
        }
    }

    let execution_time = exec_start.elapsed();

    // Construct hints from collected keys
    let construct_start = Instant::now();

    let collector_state = collector_handle.borrow();

    // Determine optimized sources for storage keys
    // Get a DBProvider from the factory for cursor access
    let db_provider = factory.provider().wrap_err("Failed to get database provider")?;
    let storage_keys =
        determine_sources(&db_provider, block_num.saturating_sub(1), &collector_state.storage_keys);

    // Collect all accounts: from collector + tx senders/recipients + coinbase
    // The KeyCollector only captures opcode-level accesses, but the EVM also
    // accesses sender/recipient accounts for balance/nonce operations
    let mut all_accounts: std::collections::HashSet<ira_common::AddressKey> =
        collector_state.account_addresses.iter().copied().collect();

    // Add transaction senders (already recovered from block)
    for sender in block.senders() {
        all_accounts.insert(ira_common::AddressKey::new(sender.into_array()));
    }

    // Add transaction recipients (to addresses, if not contract creation)
    // Also add to bytecode_addresses since recipients might be contracts
    let mut all_bytecodes: std::collections::HashSet<ira_common::AddressKey> =
        collector_state.bytecode_addresses.iter().copied().collect();

    for tx in txs.iter() {
        if let Some(to) = tx.to() {
            let key = ira_common::AddressKey::new(to.into_array());
            all_accounts.insert(key);
            all_bytecodes.insert(key); // Recipient might be a contract
        }
    }

    // Add block beneficiary (coinbase) - receives fees
    all_accounts.insert(ira_common::AddressKey::new(
        block.header().beneficiary.into_array(),
    ));

    let hints = BlockHints {
        block_number: block_num,
        storage_keys,
        bytecode_addresses: all_bytecodes.into_iter().collect(),
        account_addresses: all_accounts.into_iter().collect(),
    };

    let hint_construction_time = construct_start.elapsed();

    // Write hints to file
    let write_start = Instant::now();
    hint_writer.write(&hints)?;
    let hint_write_time = write_start.elapsed();

    // Compute and write state hash for correctness verification
    // This allows backups to verify their execution matches the primary
    let state_hash = compute_state_hash(&evm.db().cache);
    state_hash_db.write(block_num, state_hash)?;

    Ok((
        execution_time.as_micros() as u64,
        hint_construction_time.as_micros() as u64,
        hint_write_time.as_micros() as u64,
    ))
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
