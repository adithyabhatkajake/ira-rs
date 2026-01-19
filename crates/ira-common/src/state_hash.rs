//! State changes hash computation and storage for correctness verification.
//!
//! The primary computes a deterministic hash of all state changes after execution
//! and writes it to a separate database. The backup verifies its execution produces
//! the same hash, proving correctness without full state root computation.

use alloy_primitives::B256;
use eyre::{Context, Result};
use reth_revm::revm::database::Cache;
use sha3::{Digest, Keccak256};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

/// Compute a deterministic hash of all state changes in a Cache.
///
/// The hash includes:
/// - Account addresses, nonces, balances, and code hashes
/// - Storage slots and values
///
/// Data is sorted by address/slot to ensure determinism regardless of
/// iteration order in the underlying HashMap.
pub fn compute_state_hash(cache: &Cache) -> B256 {
    let mut hasher = Keccak256::new();

    // Sort accounts by address for determinism
    let mut sorted_accounts: Vec<_> = cache.accounts.iter().collect();
    sorted_accounts.sort_by_key(|(addr, _)| *addr);

    for (addr, account) in sorted_accounts {
        // Hash address
        hasher.update(addr.as_slice());

        // Hash account info
        hasher.update(&account.info.nonce.to_le_bytes());
        hasher.update(account.info.balance.to_le_bytes::<32>());
        hasher.update(account.info.code_hash.as_slice());

        // Sort and hash storage slots
        let mut sorted_storage: Vec<_> = account.storage.iter().collect();
        sorted_storage.sort_by_key(|(slot, _)| *slot);

        for (slot, value) in sorted_storage {
            hasher.update(&slot.to_be_bytes::<32>());
            hasher.update(&value.to_be_bytes::<32>());
        }
    }

    // Also hash contracts for completeness
    let mut sorted_contracts: Vec<_> = cache.contracts.iter().collect();
    sorted_contracts.sort_by_key(|(hash, _)| *hash);

    for (code_hash, bytecode) in sorted_contracts {
        hasher.update(code_hash.as_slice());
        hasher.update(&(bytecode.len() as u64).to_le_bytes());
    }

    B256::from_slice(&hasher.finalize())
}

/// Simple file-based database for state hashes.
///
/// Stores one 32-byte hash per block in a flat file structure:
/// `{dir}/{block_number}.hash`
pub struct StateHashDb {
    path: PathBuf,
}

impl StateHashDb {
    /// Create a new StateHashDb at the given directory path.
    pub fn new(path: &Path) -> Self {
        Self {
            path: path.to_path_buf(),
        }
    }

    /// Write a state hash for a block.
    pub fn write(&self, block_number: u64, hash: B256) -> Result<()> {
        fs::create_dir_all(&self.path)?;
        let file_path = self.path.join(format!("{}.hash", block_number));
        let mut file = File::create(&file_path)
            .wrap_err_with(|| format!("Failed to create hash file: {:?}", file_path))?;
        file.write_all(hash.as_slice())?;
        Ok(())
    }

    /// Read a state hash for a block.
    pub fn read(&self, block_number: u64) -> Result<B256> {
        let file_path = self.path.join(format!("{}.hash", block_number));
        let mut file = File::open(&file_path)
            .wrap_err_with(|| format!("Failed to open hash file: {:?}", file_path))?;
        let mut buf = [0u8; 32];
        file.read_exact(&mut buf)?;
        Ok(B256::from(buf))
    }

    /// Check if a hash exists for a block.
    pub fn exists(&self, block_number: u64) -> bool {
        self.path.join(format!("{}.hash", block_number)).exists()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_state_hash_db_roundtrip() {
        let dir = tempdir().unwrap();
        let db = StateHashDb::new(dir.path());

        let hash = B256::from([0x42u8; 32]);
        db.write(12345, hash).unwrap();

        assert!(db.exists(12345));
        assert!(!db.exists(12346));

        let read_hash = db.read(12345).unwrap();
        assert_eq!(hash, read_hash);
    }
}
