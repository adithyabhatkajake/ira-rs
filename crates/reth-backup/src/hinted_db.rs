//! HintedDB - A database wrapper that pre-loads state using hints with sorted batch reads.
//!
//! This module provides efficient batch reads using MDBX cursor walking with sorted keys
//! to convert random I/O into sequential I/O for better performance.
//!
//! Key optimization: Instead of seeking to each key randomly, we collect all keys from
//! multiple blocks, sort them, and read in sorted order. This dramatically improves
//! I/O efficiency as the cursor moves forward through the B-tree.
//!
//! Uses source byte optimization:
//! - SOURCE_IN_PLAIN_STATE (0): Read from PlainStorageState (fast path, ~90% of keys)
//! - SOURCE_NOT_YET_WRITTEN (1): Value is zero, skip read
//! - SOURCE_IN_CHANGESET (2): Let cache miss, fallback to historical provider

use alloy_consensus::constants::KECCAK_EMPTY;
use alloy_primitives::{map::HashMap, Address, B256, U256};
use ira_common::{BlockHints, SOURCE_IN_CHANGESET, SOURCE_IN_PLAIN_STATE, SOURCE_NOT_YET_WRITTEN};
use std::collections::BTreeMap;
use reth_db_api::{
    cursor::{DbCursorRO, DbDupCursorRO},
    tables,
    transaction::DbTx,
};
use reth_primitives_traits::Account;
use reth_revm::revm::{
    bytecode::Bytecode,
    database::{AccountState, CacheDB, DatabaseRef},
    state::AccountInfo,
};
use reth_storage_api::DBProvider;
use rayon::prelude::*;
use std::collections::HashSet;
use std::sync::Arc;

/// Error type for HintedDB operations
#[derive(Debug)]
pub enum HintedDbError {
    Database(String),
}

impl std::fmt::Display for HintedDbError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Database(msg) => write!(f, "Database error: {}", msg),
        }
    }
}

impl std::error::Error for HintedDbError {}

/// Pre-loaded state data from hints
#[derive(Clone)]
pub struct PreloadedState {
    /// Account info by address
    pub accounts: HashMap<Address, AccountInfo>,
    /// Storage slots by address
    pub storage: HashMap<Address, HashMap<U256, U256>>,
    /// Bytecode by code hash
    pub contracts: HashMap<B256, Bytecode>,
}

impl Default for PreloadedState {
    fn default() -> Self {
        Self {
            accounts: HashMap::default(),
            storage: HashMap::default(),
            contracts: HashMap::default(),
        }
    }
}

/// Load state from hints using cursor walking for efficient batch reads.
///
/// This function uses MDBX cursor walking to efficiently read multiple storage
/// slots for the same address without repeated seeks.
pub fn load_state_from_hints<Provider>(
    provider: &Provider,
    hints: &BlockHints,
) -> Result<PreloadedState, HintedDbError>
where
    Provider: DBProvider,
    Provider::Tx: DbTx,
{
    let tx = provider.tx_ref();
    let mut state = PreloadedState::default();

    // Collect slots by address, grouped by source type
    // We only preload SOURCE_IN_PLAIN_STATE keys (fast path)
    // SOURCE_NOT_YET_WRITTEN keys get zero value directly
    // SOURCE_IN_CHANGESET keys are left for historical provider fallback
    let mut plain_state_slots: HashMap<Address, HashSet<B256>> = HashMap::default();
    let mut zero_value_slots: HashMap<Address, HashSet<B256>> = HashMap::default();

    for key in &hints.storage_keys {
        let addr = Address::from_slice(&key.address);
        let slot = B256::from_slice(&key.slot);

        match key.source {
            SOURCE_IN_PLAIN_STATE => {
                plain_state_slots.entry(addr).or_default().insert(slot);
            }
            SOURCE_NOT_YET_WRITTEN => {
                zero_value_slots.entry(addr).or_default().insert(slot);
            }
            SOURCE_IN_CHANGESET | _ => {
                // Skip - will be fetched on-demand from historical provider
            }
        }
    }

    // Collect all addresses that need account info
    let mut all_addresses: HashSet<Address> = HashSet::default();
    for addr in plain_state_slots.keys() {
        all_addresses.insert(*addr);
    }
    for addr in zero_value_slots.keys() {
        all_addresses.insert(*addr);
    }
    for key in &hints.account_addresses {
        all_addresses.insert(Address::from_slice(&key.address));
    }
    for key in &hints.bytecode_addresses {
        all_addresses.insert(Address::from_slice(&key.address));
    }

    // Load all accounts from PlainAccountState
    let mut account_cursor = tx
        .cursor_read::<tables::PlainAccountState>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create account cursor: {:?}", e)))?;

    for addr in &all_addresses {
        if let Some(account) = account_cursor
            .seek_exact(*addr)
            .map_err(|e| HintedDbError::Database(format!("Account seek failed: {:?}", e)))?
            .map(|(_, acc)| acc)
        {
            let info = account_to_info(&account);
            state.accounts.insert(*addr, info);
        }
    }

    // Insert zero values for SOURCE_NOT_YET_WRITTEN slots (no DB read needed)
    for (addr, slots) in &zero_value_slots {
        let addr_storage = state.storage.entry(*addr).or_default();
        for slot in slots {
            addr_storage.insert(U256::from_be_bytes(slot.0), U256::ZERO);
        }
    }

    // Load storage from PlainStorageState for SOURCE_IN_PLAIN_STATE slots (fast path)
    let mut storage_cursor = tx
        .cursor_dup_read::<tables::PlainStorageState>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create storage cursor: {:?}", e)))?;

    for (addr, needed_slots) in &plain_state_slots {
        let addr_storage = state.storage.entry(*addr).or_default();

        // Seek to each needed slot directly (much faster than walking all slots)
        for slot in needed_slots {
            if let Some(entry) = storage_cursor
                .seek_by_key_subkey(*addr, *slot)
                .map_err(|e| HintedDbError::Database(format!("Storage seek failed: {:?}", e)))?
            {
                if entry.key == *slot {
                    addr_storage.insert(U256::from_be_bytes(slot.0), entry.value);
                }
            }
        }
    }

    // Load bytecode for ALL accounts that have code
    // This includes bytecode_addresses plus any account in account_addresses with a code_hash
    let mut bytecode_cursor = tx
        .cursor_read::<tables::Bytecodes>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create bytecode cursor: {:?}", e)))?;

    // Load bytecode for all accounts that have non-empty code_hash
    for (_, info) in &state.accounts {
        if info.code_hash != B256::ZERO
            && info.code_hash != KECCAK_EMPTY
            && !state.contracts.contains_key(&info.code_hash)
        {
            if let Some((_, bytecode)) = bytecode_cursor
                .seek_exact(info.code_hash)
                .map_err(|e| HintedDbError::Database(format!("Bytecode seek failed: {:?}", e)))?
            {
                state
                    .contracts
                    .insert(info.code_hash, bytecode_to_revm(bytecode));
            }
        }
    }

    Ok(state)
}

/// Batch load state from multiple blocks' hints using sorted keys for sequential I/O.
///
/// This function collects all keys from multiple blocks, sorts them, and reads them
/// in sorted order. This converts random I/O into sequential I/O, dramatically
/// improving performance on SSDs.
///
/// # Arguments
/// * `provider` - Database provider
/// * `hints_batch` - Vec of (block_number, BlockHints) tuples
///
/// # Returns
/// * HashMap mapping block_number to PreloadedState
pub fn load_state_from_hints_batch<Provider>(
    provider: &Provider,
    hints_batch: &[(u64, BlockHints)],
) -> Result<HashMap<u64, PreloadedState>, HintedDbError>
where
    Provider: DBProvider,
    Provider::Tx: DbTx,
{
    let tx = provider.tx_ref();

    // Initialize result map
    let mut results: HashMap<u64, PreloadedState> = HashMap::default();
    for (block_num, _) in hints_batch {
        results.insert(*block_num, PreloadedState::default());
    }

    // ========================================================================
    // Phase 1: Collect all keys from all blocks, tracking which block needs each
    // ========================================================================

    // Account addresses: sorted Address -> list of block_nums that need it
    let mut all_accounts: BTreeMap<Address, Vec<u64>> = BTreeMap::new();

    // Storage keys: sorted (Address, Slot) -> (value_or_zero, list of block_nums)
    // We use BTreeMap for sorted iteration
    let mut plain_state_storage: BTreeMap<(Address, B256), Vec<u64>> = BTreeMap::new();
    let mut zero_value_storage: BTreeMap<(Address, B256), Vec<u64>> = BTreeMap::new();

    // Code hashes: sorted B256 -> list of block_nums
    let mut all_code_hashes: BTreeMap<B256, Vec<u64>> = BTreeMap::new();

    for (block_num, hints) in hints_batch {
        // Collect account addresses
        for key in &hints.account_addresses {
            let addr = Address::from_slice(&key.address);
            all_accounts.entry(addr).or_default().push(*block_num);
        }

        // Collect bytecode addresses (also need account info)
        for key in &hints.bytecode_addresses {
            let addr = Address::from_slice(&key.address);
            all_accounts.entry(addr).or_default().push(*block_num);
        }

        // Collect storage keys by source type
        for key in &hints.storage_keys {
            let addr = Address::from_slice(&key.address);
            let slot = B256::from_slice(&key.slot);

            // Also need account info for storage addresses
            all_accounts.entry(addr).or_default().push(*block_num);

            match key.source {
                SOURCE_IN_PLAIN_STATE => {
                    plain_state_storage
                        .entry((addr, slot))
                        .or_default()
                        .push(*block_num);
                }
                SOURCE_NOT_YET_WRITTEN => {
                    zero_value_storage
                        .entry((addr, slot))
                        .or_default()
                        .push(*block_num);
                }
                SOURCE_IN_CHANGESET | _ => {
                    // Skip - will be fetched on-demand
                }
            }
        }
    }

    // ========================================================================
    // Phase 2: Read accounts in sorted order (sequential I/O)
    // ========================================================================

    let mut account_cursor = tx
        .cursor_read::<tables::PlainAccountState>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create account cursor: {:?}", e)))?;

    // Temporary storage for account info to look up code_hash later
    let mut account_infos: HashMap<Address, AccountInfo> = HashMap::default();

    // BTreeMap iterates in sorted order - cursor moves forward
    for (addr, block_nums) in &all_accounts {
        if let Some(account) = account_cursor
            .seek_exact(*addr)
            .map_err(|e| HintedDbError::Database(format!("Account seek failed: {:?}", e)))?
            .map(|(_, acc)| acc)
        {
            let info = account_to_info(&account);
            account_infos.insert(*addr, info.clone());

            // Distribute to all blocks that need this account
            for block_num in block_nums {
                if let Some(state) = results.get_mut(block_num) {
                    state.accounts.insert(*addr, info.clone());
                }
            }

            // Track code hash for bytecode loading
            if info.code_hash != B256::ZERO && info.code_hash != KECCAK_EMPTY {
                // Find which blocks need this account's bytecode
                for block_num in block_nums {
                    all_code_hashes
                        .entry(info.code_hash)
                        .or_default()
                        .push(*block_num);
                }
            }
        }
    }

    // ========================================================================
    // Phase 3: Insert zero values (no I/O needed)
    // ========================================================================

    for ((addr, slot), block_nums) in &zero_value_storage {
        let slot_u256 = U256::from_be_bytes(slot.0);
        for block_num in block_nums {
            if let Some(state) = results.get_mut(block_num) {
                state
                    .storage
                    .entry(*addr)
                    .or_default()
                    .insert(slot_u256, U256::ZERO);
            }
        }
    }

    // ========================================================================
    // Phase 4: Read storage in sorted order (sequential I/O)
    // ========================================================================

    let mut storage_cursor = tx
        .cursor_dup_read::<tables::PlainStorageState>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create storage cursor: {:?}", e)))?;

    // BTreeMap iterates in sorted (addr, slot) order
    // This means we process all slots for one address before moving to next
    let mut current_addr: Option<Address> = None;

    for ((addr, slot), block_nums) in &plain_state_storage {
        // If we moved to a new address, we might need to re-seek
        // But since we're iterating in sorted order, the cursor is likely already positioned correctly
        if current_addr != Some(*addr) {
            current_addr = Some(*addr);
        }

        if let Some(entry) = storage_cursor
            .seek_by_key_subkey(*addr, *slot)
            .map_err(|e| HintedDbError::Database(format!("Storage seek failed: {:?}", e)))?
        {
            if entry.key == *slot {
                let slot_u256 = U256::from_be_bytes(slot.0);
                // Distribute to all blocks that need this slot
                for block_num in block_nums {
                    if let Some(state) = results.get_mut(block_num) {
                        state
                            .storage
                            .entry(*addr)
                            .or_default()
                            .insert(slot_u256, entry.value);
                    }
                }
            }
        }
    }

    // ========================================================================
    // Phase 5: Read bytecodes in sorted order (sequential I/O)
    // ========================================================================

    let mut bytecode_cursor = tx
        .cursor_read::<tables::Bytecodes>()
        .map_err(|e| HintedDbError::Database(format!("Failed to create bytecode cursor: {:?}", e)))?;

    // Deduplicate code_hash -> block_nums mapping
    let mut deduped_code_hashes: BTreeMap<B256, Vec<u64>> = BTreeMap::new();
    for (code_hash, block_nums) in all_code_hashes {
        let entry = deduped_code_hashes.entry(code_hash).or_default();
        for bn in block_nums {
            if !entry.contains(&bn) {
                entry.push(bn);
            }
        }
    }

    // Read bytecodes in sorted order
    for (code_hash, block_nums) in &deduped_code_hashes {
        if let Some((_, bytecode)) = bytecode_cursor
            .seek_exact(*code_hash)
            .map_err(|e| HintedDbError::Database(format!("Bytecode seek failed: {:?}", e)))?
        {
            let revm_bytecode = bytecode_to_revm(bytecode);
            for block_num in block_nums {
                if let Some(state) = results.get_mut(block_num) {
                    state.contracts.insert(*code_hash, revm_bytecode.clone());
                }
            }
        }
    }

    Ok(results)
}

/// Parallel version of load_state_from_hints_batch.
///
/// Uses multiple threads to read from MDBX, triggering concurrent page faults.
/// Each thread gets its own database provider and cursors for isolation.
///
/// # Arguments
/// * `factory` - Provider factory (thread-safe, creates providers per thread)
/// * `hints_batch` - Vec of (block_number, BlockHints) tuples
/// * `num_threads` - Number of parallel threads to use
///
/// # Returns
/// * HashMap mapping block_number to PreloadedState
pub fn load_state_from_hints_batch_parallel<Factory, Provider>(
    factory: &Arc<Factory>,
    hints_batch: &[(u64, BlockHints)],
    num_threads: usize,
) -> Result<HashMap<u64, PreloadedState>, HintedDbError>
where
    Factory: Fn() -> Result<Provider, HintedDbError> + Send + Sync,
    Provider: DBProvider + Send,
    Provider::Tx: DbTx,
{
    // Initialize result map
    let mut results: HashMap<u64, PreloadedState> = HashMap::default();
    for (block_num, _) in hints_batch {
        results.insert(*block_num, PreloadedState::default());
    }

    // ========================================================================
    // Phase 1: Collect all keys from all blocks
    // ========================================================================

    // Account addresses: Address -> list of block_nums that need it
    let mut all_accounts: BTreeMap<Address, Vec<u64>> = BTreeMap::new();
    let mut plain_state_storage: BTreeMap<(Address, B256), Vec<u64>> = BTreeMap::new();
    let mut zero_value_storage: BTreeMap<(Address, B256), Vec<u64>> = BTreeMap::new();

    for (block_num, hints) in hints_batch {
        for key in &hints.account_addresses {
            let addr = Address::from_slice(&key.address);
            all_accounts.entry(addr).or_default().push(*block_num);
        }
        for key in &hints.bytecode_addresses {
            let addr = Address::from_slice(&key.address);
            all_accounts.entry(addr).or_default().push(*block_num);
        }
        for key in &hints.storage_keys {
            let addr = Address::from_slice(&key.address);
            let slot = B256::from_slice(&key.slot);
            all_accounts.entry(addr).or_default().push(*block_num);

            match key.source {
                SOURCE_IN_PLAIN_STATE => {
                    plain_state_storage
                        .entry((addr, slot))
                        .or_default()
                        .push(*block_num);
                }
                SOURCE_NOT_YET_WRITTEN => {
                    zero_value_storage
                        .entry((addr, slot))
                        .or_default()
                        .push(*block_num);
                }
                SOURCE_IN_CHANGESET | _ => {}
            }
        }
    }

    // ========================================================================
    // Phase 2: Insert zero values (no I/O needed)
    // ========================================================================
    for ((addr, slot), block_nums) in &zero_value_storage {
        let slot_u256 = U256::from_be_bytes(slot.0);
        for block_num in block_nums {
            if let Some(state) = results.get_mut(block_num) {
                state
                    .storage
                    .entry(*addr)
                    .or_default()
                    .insert(slot_u256, U256::ZERO);
            }
        }
    }

    // ========================================================================
    // Phase 3: Parallel account reads
    // ========================================================================

    // Convert to vec for parallel iteration
    let account_keys: Vec<_> = all_accounts.keys().cloned().collect();

    // Partition accounts across threads
    let chunk_size = (account_keys.len() + num_threads - 1) / num_threads;
    let account_chunks: Vec<_> = account_keys.chunks(chunk_size.max(1)).collect();

    // Each thread reads its chunk of accounts
    let account_results: Vec<_> = account_chunks
        .par_iter()
        .filter_map(|chunk| {
            let provider = factory().ok()?;
            let tx = provider.tx_ref();
            let mut cursor = tx.cursor_read::<tables::PlainAccountState>().ok()?;

            let mut thread_results: Vec<(Address, AccountInfo)> = Vec::new();
            for addr in *chunk {
                if let Ok(Some((_, account))) = cursor.seek_exact(*addr) {
                    thread_results.push((*addr, account_to_info(&account)));
                }
            }
            Some(thread_results)
        })
        .flatten()
        .collect();

    // Merge account results and track code hashes
    let mut all_code_hashes: BTreeMap<B256, Vec<u64>> = BTreeMap::new();
    for (addr, info) in account_results {
        if let Some(block_nums) = all_accounts.get(&addr) {
            if info.code_hash != B256::ZERO && info.code_hash != KECCAK_EMPTY {
                for block_num in block_nums {
                    all_code_hashes
                        .entry(info.code_hash)
                        .or_default()
                        .push(*block_num);
                }
            }
            for block_num in block_nums {
                if let Some(state) = results.get_mut(block_num) {
                    state.accounts.insert(addr, info.clone());
                }
            }
        }
    }

    // ========================================================================
    // Phase 4: Parallel storage reads
    // ========================================================================

    let storage_keys: Vec<_> = plain_state_storage.keys().cloned().collect();
    let storage_chunk_size = (storage_keys.len() + num_threads - 1) / num_threads;
    let storage_chunks: Vec<_> = storage_keys.chunks(storage_chunk_size.max(1)).collect();

    let storage_results: Vec<_> = storage_chunks
        .par_iter()
        .filter_map(|chunk| {
            let provider = factory().ok()?;
            let tx = provider.tx_ref();
            let mut cursor = tx.cursor_dup_read::<tables::PlainStorageState>().ok()?;

            let mut thread_results: Vec<((Address, B256), U256)> = Vec::new();
            for (addr, slot) in *chunk {
                if let Ok(Some(entry)) = cursor.seek_by_key_subkey(*addr, *slot) {
                    if entry.key == *slot {
                        thread_results.push(((*addr, *slot), entry.value));
                    }
                }
            }
            Some(thread_results)
        })
        .flatten()
        .collect();

    // Merge storage results
    for ((addr, slot), value) in storage_results {
        if let Some(block_nums) = plain_state_storage.get(&(addr, slot)) {
            let slot_u256 = U256::from_be_bytes(slot.0);
            for block_num in block_nums {
                if let Some(state) = results.get_mut(block_num) {
                    state.storage.entry(addr).or_default().insert(slot_u256, value);
                }
            }
        }
    }

    // ========================================================================
    // Phase 5: Parallel bytecode reads
    // ========================================================================

    // Deduplicate code hashes
    let mut deduped_code_hashes: BTreeMap<B256, Vec<u64>> = BTreeMap::new();
    for (code_hash, block_nums) in all_code_hashes {
        let entry = deduped_code_hashes.entry(code_hash).or_default();
        for bn in block_nums {
            if !entry.contains(&bn) {
                entry.push(bn);
            }
        }
    }

    let code_keys: Vec<_> = deduped_code_hashes.keys().cloned().collect();
    let code_chunk_size = (code_keys.len() + num_threads - 1) / num_threads;
    let code_chunks: Vec<_> = code_keys.chunks(code_chunk_size.max(1)).collect();

    let bytecode_results: Vec<_> = code_chunks
        .par_iter()
        .filter_map(|chunk| {
            let provider = factory().ok()?;
            let tx = provider.tx_ref();
            let mut cursor = tx.cursor_read::<tables::Bytecodes>().ok()?;

            let mut thread_results: Vec<(B256, Bytecode)> = Vec::new();
            for code_hash in *chunk {
                if let Ok(Some((_, bytecode))) = cursor.seek_exact(*code_hash) {
                    thread_results.push((*code_hash, bytecode_to_revm(bytecode)));
                }
            }
            Some(thread_results)
        })
        .flatten()
        .collect();

    // Merge bytecode results
    for (code_hash, bytecode) in bytecode_results {
        if let Some(block_nums) = deduped_code_hashes.get(&code_hash) {
            for block_num in block_nums {
                if let Some(state) = results.get_mut(block_num) {
                    state.contracts.insert(code_hash, bytecode.clone());
                }
            }
        }
    }

    Ok(results)
}

/// Build a pre-populated CacheDB from preloaded state
pub fn build_cache_db<DB: DatabaseRef>(
    base_db: DB,
    preloaded: PreloadedState,
) -> CacheDB<DB> {
    let mut cache_db = CacheDB::new(base_db);

    // Insert all accounts with their storage
    for (addr, info) in preloaded.accounts {
        let storage = preloaded.storage.get(&addr).cloned().unwrap_or_default();

        let db_account = cache_db.cache.accounts.entry(addr).or_default();
        db_account.info = info;
        db_account.account_state = AccountState::Touched;
        for (slot, value) in storage {
            db_account.storage.insert(slot, value);
        }
    }

    // Insert bytecodes
    for (hash, code) in preloaded.contracts {
        cache_db.cache.contracts.insert(hash, code);
    }

    cache_db
}

/// Convert reth Account to revm AccountInfo
fn account_to_info(account: &Account) -> AccountInfo {
    AccountInfo {
        balance: account.balance,
        nonce: account.nonce,
        code_hash: account.bytecode_hash.unwrap_or(KECCAK_EMPTY),
        code: None,
    }
}

/// Convert reth Bytecode to revm Bytecode
fn bytecode_to_revm(bytecode: reth_primitives_traits::Bytecode) -> Bytecode {
    Bytecode::new_raw(bytecode.bytes())
}

/// A database wrapper that panics on any read attempt.
/// Used to verify that hints provide complete coverage - if execution
/// ever tries to read from the database, it means the hints were incomplete.
#[derive(Debug, Clone, Default)]
pub struct PanicOnMissDB;

impl DatabaseRef for PanicOnMissDB {
    type Error = std::convert::Infallible;

    fn basic_ref(&self, address: Address) -> Result<Option<AccountInfo>, Self::Error> {
        panic!(
            "PanicOnMissDB: Attempted to read account info for {:?}. Hints are incomplete!",
            address
        );
    }

    fn code_by_hash_ref(&self, code_hash: B256) -> Result<Bytecode, Self::Error> {
        panic!(
            "PanicOnMissDB: Attempted to read bytecode for hash {:?}. Hints are incomplete!",
            code_hash
        );
    }

    fn storage_ref(&self, address: Address, index: U256) -> Result<U256, Self::Error> {
        panic!(
            "PanicOnMissDB: Attempted to read storage slot {:?} for {:?}. Hints are incomplete!",
            index, address
        );
    }

    fn block_hash_ref(&self, number: u64) -> Result<B256, Self::Error> {
        panic!(
            "PanicOnMissDB: Attempted to read block hash for block {}. Hints are incomplete!",
            number
        );
    }
}
