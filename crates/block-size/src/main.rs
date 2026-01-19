//! block-size: Measure RLP-encoded block sizes from reth database.
//!
//! Outputs a CSV with block_number, header_size, body_size, total_size, tx_count.

use alloy_rlp::Encodable;
use chrono::Local;
use clap::Parser;
use eyre::{Context, Result};
use indicatif::{ProgressBar, ProgressStyle};
use rayon::prelude::*;
use reth_db::DatabaseEnv;
use reth_ethereum::{
    chainspec::ChainSpecBuilder,
    node::EthereumNode,
    provider::{providers::ReadOnlyConfig, BlockReader, ProviderFactory, TransactionVariant},
};
use reth_node_builder::NodeTypesWithDBAdapter;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tracing::info;

/// Concrete factory type for Ethereum mainnet
type EthProviderFactory = ProviderFactory<NodeTypesWithDBAdapter<EthereumNode, Arc<DatabaseEnv>>>;

#[derive(Parser, Debug)]
#[command(name = "block-size")]
#[command(about = "Measure RLP-encoded block sizes from reth database")]
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

    /// Number of parallel threads
    #[arg(long, default_value = "8")]
    threads: usize,
}

/// Result of measuring a single block
struct BlockSizeResult {
    block_number: u64,
    header_size: usize,
    body_size: usize,
    total_size: usize,
    tx_count: usize,
}

fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("block_size=info".parse().unwrap()),
        )
        .init();

    let args = Args::parse();

    // Set rayon thread pool size
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

    // Create output file
    fs::create_dir_all(&args.output_dir)?;
    let today = Local::now().format("%Y.%m.%d").to_string();
    let output_path = args.output_dir.join(format!("{}.block-size.csv", today));
    info!("Writing output to {:?}", output_path);

    // Progress bar
    let total_blocks = args.end_block - args.start_block + 1;
    let pb = ProgressBar::new(total_blocks);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})")
            .unwrap()
            .progress_chars("#>-"),
    );

    info!(
        "Processing blocks {} - {} ({} blocks) with {} threads",
        args.start_block, args.end_block, total_blocks, args.threads
    );

    let progress_counter = AtomicU64::new(0);
    let block_numbers: Vec<u64> = (args.start_block..=args.end_block).collect();

    // Process blocks in parallel
    let results: Vec<BlockSizeResult> = block_numbers
        .par_iter()
        .map(|&block_num| {
            let result = measure_block(&factory, block_num);

            // Update progress
            let count = progress_counter.fetch_add(1, Ordering::Relaxed);
            if count % 100 == 0 {
                pb.set_position(count);
            }

            result
        })
        .collect();

    pb.finish_with_message("done");

    // Sort and write results
    let mut sorted_results = results;
    sorted_results.sort_by_key(|r| r.block_number);

    let file = File::create(&output_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "block_number,header_size,body_size,total_size,tx_count")?;

    for result in sorted_results {
        writeln!(
            writer,
            "{},{},{},{},{}",
            result.block_number,
            result.header_size,
            result.body_size,
            result.total_size,
            result.tx_count
        )?;
    }
    writer.flush()?;

    info!("Completed! Output written to {:?}", output_path);
    Ok(())
}

fn measure_block(factory: &Arc<EthProviderFactory>, block_num: u64) -> BlockSizeResult {
    let block = match factory.sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash) {
        Ok(Some(b)) => b,
        _ => {
            return BlockSizeResult {
                block_number: block_num,
                header_size: 0,
                body_size: 0,
                total_size: 0,
                tx_count: 0,
            }
        }
    };

    // Measure RLP-encoded sizes
    let header_size = block.header().length();
    let body = block.body();
    let tx_count = body.transactions.len();

    // Calculate body size (sum of transaction sizes)
    let body_size: usize = body.transactions.iter().map(|tx| tx.length()).sum();
    let total_size = header_size + body_size;

    BlockSizeResult {
        block_number: block_num,
        header_size,
        body_size,
        total_size,
        tx_count,
    }
}
