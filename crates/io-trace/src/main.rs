//! io-trace: Measure I/O time vs compute time for block execution.
//!
//! This binary replays blocks and measures how much time is spent in
//! database I/O (state reads) vs EVM compute.

mod timed_db;

use alloy_evm::Evm;
use chrono::Local;
use clap::Parser;
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
use timed_db::TimedDb;
use tracing::info;

/// Concrete factory type for Ethereum mainnet
type EthProviderFactory = ProviderFactory<NodeTypesWithDBAdapter<EthereumNode, Arc<DatabaseEnv>>>;

#[derive(Parser, Debug)]
#[command(name = "io-trace")]
#[command(about = "Measure I/O time vs compute time for block execution")]
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

    /// Output directory for CSV
    #[arg(long, default_value = "/Volumes/X/ira-data")]
    output_dir: PathBuf,
}

/// Result of processing a single block
struct BlockResult {
    block_number: u64,
    total_time_us: u64,
    io_time_us: u64,
    compute_time_us: u64,
    tx_count: usize,
}

fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("io_trace=info".parse().unwrap()),
        )
        .init();

    let args = Args::parse();

    // Open database
    eprintln!("Opening reth database at {}...", args.datadir);
    let spec = ChainSpecBuilder::mainnet().build();
    let factory: EthProviderFactory = EthereumNode::provider_factory_builder()
        .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(&args.datadir))
        .wrap_err("Failed to open reth database")?;
    let evm_config = EthEvmConfig::new(factory.chain_spec());

    // Create output file
    fs::create_dir_all(&args.output_dir)?;
    let today = Local::now().format("%Y.%m.%d").to_string();
    let output_path = args.output_dir.join(format!("{}.io-trace.csv", today));
    eprintln!("Writing output to {:?}", output_path);

    let file = File::create(&output_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "block_number,total_time_us,io_time_us,compute_time_us,tx_count")?;

    // Progress bar
    let total_blocks = args.end_block - args.start_block + 1;
    let pb = ProgressBar::new(total_blocks);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})")
            .unwrap()
            .progress_chars("#>-"),
    );

    eprintln!(
        "Processing blocks {} - {} ({} blocks)",
        args.start_block, args.end_block, total_blocks
    );

    // Process blocks sequentially (no cross-block cache to measure true I/O)
    for block_num in args.start_block..=args.end_block {
        let result = process_block(&factory, &evm_config, block_num);

        writeln!(
            writer,
            "{},{},{},{},{}",
            result.block_number,
            result.total_time_us,
            result.io_time_us,
            result.compute_time_us,
            result.tx_count
        )?;

        let count = block_num - args.start_block;
        if count % 100 == 0 {
            pb.set_position(count);
            writer.flush()?;
        }
    }

    pb.finish_with_message("done");
    writer.flush()?;

    info!("Completed! Output written to {:?}", output_path);
    Ok(())
}

fn process_block(
    factory: &EthProviderFactory,
    evm_config: &EthEvmConfig,
    block_num: u64,
) -> BlockResult {
    match process_block_inner(factory, evm_config, block_num) {
        Ok(result) => result,
        Err(_) => BlockResult {
            block_number: block_num,
            total_time_us: 0,
            io_time_us: 0,
            compute_time_us: 0,
            tx_count: 0,
        },
    }
}

fn process_block_inner(
    factory: &EthProviderFactory,
    evm_config: &EthEvmConfig,
    block_num: u64,
) -> Result<BlockResult> {
    // Get block with senders
    let block = factory
        .sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash)?
        .ok_or_else(|| eyre::eyre!("Block {} not found", block_num))?;

    // Skip empty blocks
    let txs = &block.body().transactions;
    if txs.is_empty() {
        return Ok(BlockResult {
            block_number: block_num,
            total_time_us: 0,
            io_time_us: 0,
            compute_time_us: 0,
            tx_count: 0,
        });
    }

    // Get state at parent block
    let parent_state = factory.history_by_block_number(block_num.saturating_sub(1))?;
    let base_db = StateProviderDatabase::new(parent_state);

    // Wrap with TimedDb to measure I/O
    let timed_db = TimedDb::new(base_db);
    let cached_db = CacheDB::new(timed_db);

    // Get EVM environment
    let evm_env = evm_config
        .evm_env(block.header())
        .wrap_err("Failed to create EVM env")?;

    // Create EVM without inspector
    let mut evm = evm_config.evm_with_env(cached_db, evm_env);

    // Execute all transactions and measure total time
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

    let total_time = start.elapsed();

    // Get I/O time from the timed database
    // The timed_db is inside cached_db, we need to access it
    let io_time = evm.db().db.io_time();
    let compute_time = total_time.saturating_sub(io_time);

    Ok(BlockResult {
        block_number: block_num,
        total_time_us: total_time.as_micros() as u64,
        io_time_us: io_time.as_micros() as u64,
        compute_time_us: compute_time.as_micros() as u64,
        tx_count: txs.len(),
    })
}
