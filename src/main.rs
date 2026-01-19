//! Ira Trace Collector
//!
//! Extract EVM state access traces from a reth node's database by re-executing
//! blocks with a custom Inspector. Output traces to Parquet files.

mod executor;
mod inspector;
mod parquet;
mod types;

use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use tracing::{error, info};

/// Extract EVM state access traces from reth database.
#[derive(Parser, Debug)]
#[command(name = "ira-trace-collector")]
#[command(about = "Extract EVM state access traces from reth")]
struct Args {
    /// Path to reth data directory (contains db/ subdirectory).
    #[arg(long)]
    datadir: String,

    /// Start block (inclusive). If not specified with --num-blocks, defaults to latest - 99.
    #[arg(long)]
    start_block: Option<u64>,

    /// End block (inclusive). If not specified, uses latest available block.
    #[arg(long)]
    end_block: Option<u64>,

    /// Number of blocks to process (backwards from end). Alternative to --start-block.
    #[arg(long)]
    num_blocks: Option<u64>,

    /// Output directory for Parquet files.
    #[arg(long, default_value = "/Volumes/X/ira-new-analysis")]
    output: String,

    /// Blocks per output file.
    #[arg(long, default_value = "10000")]
    batch_size: u64,
}

fn main() -> eyre::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let args = Args::parse();

    info!("Ira Trace Collector starting");
    info!("Data directory: {}", args.datadir);
    info!("Output directory: {}", args.output);

    // Create output directory if it doesn't exist
    std::fs::create_dir_all(&args.output)?;

    // Determine block range
    let best_block = executor::get_best_block_number(&args.datadir)?;
    info!("Best block in database: {}", best_block);

    let end_block = args.end_block.unwrap_or(best_block).min(best_block);

    let start_block = if let Some(start) = args.start_block {
        start
    } else if let Some(num) = args.num_blocks {
        end_block.saturating_sub(num - 1)
    } else {
        // Default: latest 100 blocks
        end_block.saturating_sub(99)
    };

    if start_block > end_block {
        error!(
            "Start block {} is greater than end block {}",
            start_block, end_block
        );
        return Err(eyre::eyre!("Invalid block range"));
    }

    info!(
        "Processing blocks {} to {} ({} blocks)",
        start_block,
        end_block,
        end_block - start_block + 1
    );

    // Process in batches
    let total_blocks = end_block - start_block + 1;
    let pb = ProgressBar::new(total_blocks);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} blocks ({per_sec}, ETA: {eta})")?
            .progress_chars("#>-"),
    );

    let mut current = start_block;
    let mut total_operations = 0u64;

    while current <= end_block {
        let batch_end = (current + args.batch_size - 1).min(end_block);

        info!("Processing batch: blocks {} to {}", current, batch_end);

        // Process batch
        let operations = executor::process_blocks(&args.datadir, current, batch_end, |block, _| {
            pb.set_position(block - start_block);
        })?;

        total_operations += operations.len() as u64;

        // Write to Parquet
        if !operations.is_empty() {
            let filename = parquet::batch_filename(&args.output, current, batch_end);
            info!(
                "Writing {} operations to {}",
                operations.len(),
                filename
            );
            parquet::write_operations_to_parquet(&operations, &filename)?;
        } else {
            info!("No operations in batch {} to {}", current, batch_end);
        }

        pb.set_position(batch_end - start_block + 1);
        current = batch_end + 1;
    }

    pb.finish_with_message("Done!");

    info!(
        "Completed! Processed {} blocks, collected {} total operations",
        total_blocks, total_operations
    );
    info!("Output files in: {}", args.output);

    Ok(())
}
