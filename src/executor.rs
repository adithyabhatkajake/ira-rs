//! Block execution with state access tracing.
//!
//! Executes blocks in parallel using rayon, with proper state accumulation
//! across transactions within each block.

use crate::inspector::StateAccessInspector;
use crate::types::StateOperation;

use alloy_consensus::Transaction as TxTrait;
use alloy_primitives::TxKind;
use rayon::prelude::*;
use reth_ethereum::{
    chainspec::{ChainSpecBuilder, ChainSpecProvider},
    evm::primitives::ConfigureEvm,
    node::{EthEvmConfig, EthereumNode},
    primitives::SignerRecoverable,
    provider::{providers::ReadOnlyConfig, BlockNumReader, BlockReader, TransactionVariant},
    TransactionSigned,
};
// Import Evm trait for transact method
use alloy_evm::Evm;
use reth_revm::{
    database::StateProviderDatabase,
    revm::{context::TxEnv, database::CacheDB, state::EvmState},
};

use eyre::{Context, Result};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tracing::{debug, info, warn};

/// Process a range of blocks in parallel and extract state access operations.
pub fn process_blocks(
    datadir: &str,
    start_block: u64,
    end_block: u64,
    progress_callback: impl Fn(u64, u64) + Sync,
) -> Result<Vec<StateOperation>> {
    // Open database read-only
    info!("Opening reth database at {}", datadir);
    let spec = ChainSpecBuilder::mainnet().build();
    let factory = EthereumNode::provider_factory_builder()
        .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(datadir))
        .wrap_err("Failed to open reth database")?;

    let evm_config = EthEvmConfig::new(factory.chain_spec());

    // Progress counter
    let processed = Arc::new(AtomicU64::new(0));

    // Collect block numbers to process
    let block_nums: Vec<u64> = (start_block..=end_block).collect();
    let total_blocks = block_nums.len() as u64;

    info!(
        "Processing {} blocks in parallel using {} threads",
        total_blocks,
        rayon::current_num_threads()
    );

    // Process blocks in parallel
    let all_operations: Vec<Vec<StateOperation>> = block_nums
        .par_iter()
        .filter_map(|&block_num| {
            // Update progress periodically
            let count = processed.fetch_add(1, Ordering::Relaxed);
            if count % 100 == 0 {
                progress_callback(count, total_blocks);
            }

            // Get block with senders
            let provider = match factory.provider() {
                Ok(p) => p,
                Err(e) => {
                    warn!("Failed to get provider for block {}: {:?}", block_num, e);
                    return None;
                }
            };

            let block = match provider.sealed_block_with_senders(block_num.into(), TransactionVariant::NoHash) {
                Ok(Some(b)) => b,
                Ok(None) => return None, // Block not found
                Err(e) => {
                    warn!("Failed to get block {}: {:?}", block_num, e);
                    return None;
                }
            };

            // Skip empty blocks
            if block.body().transactions.is_empty() {
                return Some(Vec::new());
            }

            debug!(
                "Processing block {} with {} transactions",
                block_num,
                block.body().transactions.len()
            );

            // Get state at parent block and wrap in CacheDB for state accumulation
            let parent_state = match factory.history_by_block_number(block_num.saturating_sub(1)) {
                Ok(s) => s,
                Err(e) => {
                    warn!("Failed to get state for block {}: {:?}", block_num - 1, e);
                    return None;
                }
            };
            let base_db = StateProviderDatabase::new(parent_state);
            let cached_db = CacheDB::new(base_db);

            // Get EVM environment for this block
            let evm_env = match evm_config.evm_env(block.header()) {
                Ok(env) => env,
                Err(e) => {
                    warn!("Failed to create EVM env for block {}: {:?}", block_num, e);
                    return None;
                }
            };

            // Create inspector for this block
            let mut inspector = StateAccessInspector::new(block_num);
            let inspector_handle = inspector.handle();

            // Create EVM with CacheDB and inspector
            let mut evm = evm_config.evm_with_env_and_inspector(cached_db, evm_env, &mut inspector);

            // Execute each transaction
            for (tx_idx, tx) in block.body().transactions.iter().enumerate() {
                // Set transaction index via the handle
                inspector_handle.borrow_mut().set_tx_index(tx_idx as u16);

                // Create transaction environment
                let tx_env = create_tx_env(tx);

                // Execute transaction and commit state changes
                match evm.transact(tx_env) {
                    Ok(result) => {
                        // Commit state changes to the cached database for next transaction
                        commit_state_changes(evm.db_mut(), result.state);
                    }
                    Err(e) => {
                        debug!(
                            "EVM error executing tx {} in block {}: {:?}",
                            tx_idx, block_num, e
                        );
                    }
                }
            }

            // Return collected operations
            Some(inspector_handle.borrow_mut().take_operations())
        })
        .collect();

    // Flatten all operations
    let mut all_ops: Vec<StateOperation> = all_operations.into_iter().flatten().collect();

    // Sort by block number, tx index, op index for consistent output
    all_ops.sort_by(|a, b| {
        a.block_number
            .cmp(&b.block_number)
            .then(a.tx_index.cmp(&b.tx_index))
            .then(a.op_index.cmp(&b.op_index))
    });

    info!(
        "Processed {} blocks, collected {} operations",
        end_block - start_block + 1,
        all_ops.len()
    );

    Ok(all_ops)
}

/// Commit state changes from transaction execution to the cache database.
fn commit_state_changes<DB>(db: &mut CacheDB<DB>, state: EvmState) {
    for (address, account) in state {
        if account.is_touched() {
            let db_account = db.cache.accounts.entry(address).or_default();
            db_account.info = account.info.clone();

            db_account.account_state = if account.is_selfdestructed() {
                reth_revm::revm::database::AccountState::NotExisting
            } else if account.is_created() {
                reth_revm::revm::database::AccountState::StorageCleared
            } else {
                reth_revm::revm::database::AccountState::Touched
            };

            for (slot, value) in account.storage {
                db_account.storage.insert(slot, value.present_value);
            }
        }
    }
}

/// Create a transaction environment from a signed transaction.
fn create_tx_env(tx: &TransactionSigned) -> TxEnv {
    let caller = tx.recover_signer().unwrap_or_default();
    let gas_limit = tx.gas_limit();
    let gas_price = tx.gas_price().unwrap_or(tx.max_fee_per_gas());
    let value = tx.value();
    let nonce = tx.nonce();
    let data = tx.input().clone();
    let kind = tx.to().map(TxKind::Call).unwrap_or(TxKind::Create);

    TxEnv {
        caller,
        gas_limit,
        gas_price: gas_price as u128,
        kind,
        value,
        data,
        nonce,
        ..Default::default()
    }
}

/// Get the best (latest) block number from the database.
pub fn get_best_block_number(datadir: &str) -> Result<u64> {
    let spec = ChainSpecBuilder::mainnet().build();
    let factory = EthereumNode::provider_factory_builder()
        .open_read_only(spec.into(), ReadOnlyConfig::from_datadir(datadir))
        .wrap_err("Failed to open reth database")?;

    let provider = factory.provider()?;
    let best = provider.best_block_number()?;
    Ok(best)
}
