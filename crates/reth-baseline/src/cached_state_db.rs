//! Layered database that checks CrossBlockCache before hitting disk.
//!
//! This provides efficient cross-block caching without copying the entire
//! cache into each block's CacheDB. The cache is checked lazily on miss.

use crate::cross_block_cache::CrossBlockCache;
use alloy_primitives::{Address, B256, U256};
use reth_revm::revm::{
    database::DatabaseRef,
    state::{AccountInfo, Bytecode},
};
use std::fmt;

/// A database wrapper that checks CrossBlockCache first, then falls back to disk.
/// This avoids copying the entire cache into each block's CacheDB.
pub struct CachedStateDb<'a, DB> {
    /// Reference to the cross-block cache (checked first)
    cache: &'a CrossBlockCache,
    /// Inner database (disk) - checked if cache misses
    inner: DB,
}

impl<DB: fmt::Debug> fmt::Debug for CachedStateDb<'_, DB> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CachedStateDb")
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

impl<'a, DB> CachedStateDb<'a, DB> {
    pub fn new(cache: &'a CrossBlockCache, inner: DB) -> Self {
        Self { cache, inner }
    }
}

impl<DB: DatabaseRef> DatabaseRef for CachedStateDb<'_, DB> {
    type Error = DB::Error;

    fn basic_ref(&self, address: Address) -> Result<Option<AccountInfo>, Self::Error> {
        // Check cross-block cache first
        if let Some(info) = self.cache.get_account(&address) {
            return Ok(Some(info));
        }
        // Cache miss - read from disk
        self.inner.basic_ref(address)
    }

    fn code_by_hash_ref(&self, code_hash: B256) -> Result<Bytecode, Self::Error> {
        // Check cross-block cache first
        if let Some(bytecode) = self.cache.get_contract(&code_hash) {
            return Ok(bytecode);
        }
        // Cache miss - read from disk
        self.inner.code_by_hash_ref(code_hash)
    }

    fn storage_ref(&self, address: Address, index: U256) -> Result<U256, Self::Error> {
        // Check cross-block cache first
        if let Some(value) = self.cache.get_storage(&address, &index) {
            return Ok(value);
        }
        // Cache miss - read from disk
        self.inner.storage_ref(address, index)
    }

    fn block_hash_ref(&self, number: u64) -> Result<B256, Self::Error> {
        // Block hashes always go to disk (not cached cross-block)
        self.inner.block_hash_ref(number)
    }
}
