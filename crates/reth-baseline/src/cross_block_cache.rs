//! Cross-block cache for simulating production reth behavior.
//!
//! In production reth, state accessed during block N is cached and available
//! for block N+1. This module implements a bounded LRU cross-block cache that
//! persists account info, storage, and bytecode across sequential block execution.
//!
//! The cache is bounded to prevent unbounded memory growth and O(n²) slowdown
//! when processing many blocks.

use alloy_primitives::{Address, B256, U256};
use lru::LruCache;
use reth_revm::{
    revm::database::Cache,
    revm::state::{AccountInfo, Bytecode},
};
use std::num::NonZeroUsize;

/// Default cache sizes - tuned for reasonable memory usage while maintaining
/// good hit rates for sequential block execution.
const DEFAULT_ACCOUNT_CACHE_SIZE: usize = 100_000;
const DEFAULT_STORAGE_CACHE_SIZE: usize = 1_000_000;
const DEFAULT_CONTRACT_CACHE_SIZE: usize = 10_000;

/// A storage slot key combining address and slot.
#[derive(Hash, Eq, PartialEq, Clone)]
struct StorageKey {
    address: Address,
    slot: U256,
}

/// Cross-block cache that persists state across sequential block execution.
/// Uses LRU eviction to maintain bounded memory usage.
pub struct CrossBlockCache {
    /// Cached account info (bounded LRU)
    accounts: LruCache<Address, AccountInfo>,
    /// Cached storage slots (bounded LRU) - flattened to avoid nested maps
    storage: LruCache<StorageKey, U256>,
    /// Cached bytecode (bounded LRU)
    contracts: LruCache<B256, Bytecode>,
}

impl CrossBlockCache {
    pub fn new() -> Self {
        Self::with_capacity(
            DEFAULT_ACCOUNT_CACHE_SIZE,
            DEFAULT_STORAGE_CACHE_SIZE,
            DEFAULT_CONTRACT_CACHE_SIZE,
        )
    }

    pub fn with_capacity(
        account_capacity: usize,
        storage_capacity: usize,
        contract_capacity: usize,
    ) -> Self {
        Self {
            accounts: LruCache::new(NonZeroUsize::new(account_capacity).unwrap()),
            storage: LruCache::new(NonZeroUsize::new(storage_capacity).unwrap()),
            contracts: LruCache::new(NonZeroUsize::new(contract_capacity).unwrap()),
        }
    }

    /// Merge state from a Cache into the cross-block cache.
    /// This should be called after each block execution to persist touched state.
    pub fn merge_from_cache_state(&mut self, cache: &Cache) {
        // Merge accounts and their storage
        for (address, db_account) in &cache.accounts {
            // Cache account info (LRU will evict old entries if at capacity)
            self.accounts.put(*address, db_account.info.clone());

            // Cache storage slots
            for (slot, value) in &db_account.storage {
                let key = StorageKey {
                    address: *address,
                    slot: (*slot).into(),
                };
                self.storage.put(key, *value);
            }
        }

        // Merge contracts/bytecode
        for (code_hash, bytecode) in &cache.contracts {
            self.contracts.put(*code_hash, bytecode.clone());
        }
    }

    /// Get cache statistics
    pub fn stats(&self) -> (usize, usize, usize) {
        (self.accounts.len(), self.storage.len(), self.contracts.len())
    }

    /// Get account info from cache (for read-through caching)
    pub fn get_account(&self, address: &Address) -> Option<AccountInfo> {
        self.accounts.peek(address).cloned()
    }

    /// Get storage value from cache (for read-through caching)
    pub fn get_storage(&self, address: &Address, slot: &U256) -> Option<U256> {
        let key = StorageKey {
            address: *address,
            slot: *slot,
        };
        self.storage.peek(&key).copied()
    }

    /// Get contract bytecode from cache (for read-through caching)
    pub fn get_contract(&self, code_hash: &B256) -> Option<Bytecode> {
        self.contracts.peek(code_hash).cloned()
    }
}

impl Default for CrossBlockCache {
    fn default() -> Self {
        Self::new()
    }
}
