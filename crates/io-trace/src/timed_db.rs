//! Timed database wrapper for measuring I/O time.
//!
//! Wraps a database and measures time spent in each database operation
//! (account reads, storage reads, bytecode reads, block hash lookups).

use alloy_primitives::{Address, B256, U256};
use reth_revm::revm::{
    database::DatabaseRef,
    state::{AccountInfo, Bytecode},
};
use std::cell::Cell;
use std::fmt;
use std::time::{Duration, Instant};

/// Wrapper database that measures time spent in I/O operations.
pub struct TimedDb<DB> {
    pub inner: DB,
    io_time: Cell<Duration>,
}

impl<DB: fmt::Debug> fmt::Debug for TimedDb<DB> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("TimedDb")
            .field("inner", &self.inner)
            .field("io_time", &self.io_time.get())
            .finish()
    }
}

impl<DB> TimedDb<DB> {
    pub fn new(inner: DB) -> Self {
        Self {
            inner,
            io_time: Cell::new(Duration::ZERO),
        }
    }

    /// Get total I/O time accumulated.
    pub fn io_time(&self) -> Duration {
        self.io_time.get()
    }

    /// Reset I/O time counter.
    pub fn reset_io_time(&self) {
        self.io_time.set(Duration::ZERO);
    }

    fn add_time(&self, elapsed: Duration) {
        self.io_time.set(self.io_time.get() + elapsed);
    }
}

impl<DB: DatabaseRef> DatabaseRef for TimedDb<DB> {
    type Error = DB::Error;

    fn basic_ref(&self, address: Address) -> Result<Option<AccountInfo>, Self::Error> {
        let start = Instant::now();
        let result = self.inner.basic_ref(address);
        self.add_time(start.elapsed());
        result
    }

    fn code_by_hash_ref(&self, code_hash: B256) -> Result<Bytecode, Self::Error> {
        let start = Instant::now();
        let result = self.inner.code_by_hash_ref(code_hash);
        self.add_time(start.elapsed());
        result
    }

    fn storage_ref(&self, address: Address, index: U256) -> Result<U256, Self::Error> {
        let start = Instant::now();
        let result = self.inner.storage_ref(address, index);
        self.add_time(start.elapsed());
        result
    }

    fn block_hash_ref(&self, number: u64) -> Result<B256, Self::Error> {
        let start = Instant::now();
        let result = self.inner.block_hash_ref(number);
        self.add_time(start.elapsed());
        result
    }
}
