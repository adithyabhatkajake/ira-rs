//! Source determination for storage keys.
//!
//! This module provides utilities to determine the source (PlainState, Changeset,
//! or NotYetWritten) for each storage key after block execution. This information
//! is used to generate optimized hints for the backup replica.

use alloy_primitives::{Address, B256};
use ira_common::{StorageKey, SOURCE_IN_CHANGESET, SOURCE_IN_PLAIN_STATE, SOURCE_NOT_YET_WRITTEN};
use reth_db_api::{
    cursor::DbCursorRO,
    models::storage_sharded_key::StorageShardedKey,
    tables,
    transaction::DbTx,
};
use reth_storage_api::DBProvider;
use std::collections::HashSet;

/// Determine sources for a set of storage keys.
///
/// For each (address, slot) pair, queries the history index to determine
/// where the value should be read from:
/// - `SOURCE_IN_PLAIN_STATE` (0): Read from PlainStorageState table
/// - `SOURCE_NOT_YET_WRITTEN` (1): Value is zero (never written before this block)
/// - `SOURCE_IN_CHANGESET` (2): Need to read from changesets via historical provider
///
/// # Arguments
/// * `provider` - Database provider with read access
/// * `block_number` - The block number we're querying state for (parent block)
/// * `keys` - Set of storage keys collected during execution
///
/// # Returns
/// Vector of `StorageKey` with the source byte set correctly
pub fn determine_sources<Provider>(
    provider: &Provider,
    block_number: u64,
    keys: &HashSet<StorageKey>,
) -> Vec<StorageKey>
where
    Provider: DBProvider,
{
    let tx = provider.tx_ref();

    keys.iter()
        .map(|key| {
            let address = Address::from_slice(&key.address);
            let slot = B256::from_slice(&key.slot);

            // Query history info to determine source
            let source = storage_history_lookup(tx, address, slot, block_number)
                .unwrap_or(SOURCE_IN_CHANGESET); // Fallback on error

            StorageKey::with_source(key.address, key.slot, source)
        })
        .collect()
}

/// Look up storage history to determine where the value should be read from.
///
/// This replicates the logic from reth's HistoricalStateProviderRef::storage_history_lookup
/// but returns our source byte directly.
fn storage_history_lookup<Tx: DbTx>(
    tx: &Tx,
    address: Address,
    storage_key: B256,
    block_number: u64,
) -> Result<u8, reth_db_api::DatabaseError> {
    let history_key = StorageShardedKey::new(address, storage_key, block_number);

    let mut cursor = tx.cursor_read::<tables::StoragesHistory>()?;

    // Lookup the history chunk in the history index
    match cursor.seek(history_key)? {
        Some((key, block_list)) if key.address == address && key.sharded_key.key == storage_key => {
            let chunk = block_list.0;

            // Get the rank of the first entry before or equal to our block
            let mut rank = chunk.rank(block_number);

            // Adjust rank to get entry strictly before our block (not equal)
            if rank.checked_sub(1).and_then(|r| chunk.select(r)) == Some(block_number) {
                rank -= 1;
            }

            let selected_block = chunk.select(rank);

            // Check if this is before the first write ever
            if rank == 0 && selected_block != Some(block_number) {
                // Look at previous entry to see if key was written before
                if !cursor
                    .prev()?
                    .is_some_and(|(k, _)| k.address == address && k.sharded_key.key == storage_key)
                {
                    // Key was never written before this point
                    return Ok(SOURCE_NOT_YET_WRITTEN);
                }
            }

            // If we have a selected block in the chunk, we need to read from changeset
            if selected_block.is_some() {
                return Ok(SOURCE_IN_CHANGESET);
            }

            // No entry after our block in this chunk - value is in plain state
            Ok(SOURCE_IN_PLAIN_STATE)
        }
        _ => {
            // No history entry found - slot was never modified, read from plain state
            Ok(SOURCE_IN_PLAIN_STATE)
        }
    }
}
