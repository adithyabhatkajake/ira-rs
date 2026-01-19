//! Data types for hint files and metrics.

use std::io::Read;

/// Storage source: read from PlainStorageState (most common, ~90% of keys).
pub const SOURCE_IN_PLAIN_STATE: u8 = 0;
/// Storage source: slot never written before this block, value is zero.
pub const SOURCE_NOT_YET_WRITTEN: u8 = 1;
/// Storage source: need to read from changesets via historical provider (rare).
pub const SOURCE_IN_CHANGESET: u8 = 2;

/// Storage key: address (20 bytes) + slot (32 bytes) + source (1 byte) = 53 bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(C, packed)]
pub struct StorageKey {
    pub address: [u8; 20],
    pub slot: [u8; 32],
    pub source: u8,
}

impl StorageKey {
    /// Create a new storage key with default source (fallback to changeset).
    pub fn new(address: [u8; 20], slot: [u8; 32]) -> Self {
        Self {
            address,
            slot,
            source: SOURCE_IN_CHANGESET,
        }
    }

    /// Create a new storage key with explicit source.
    pub fn with_source(address: [u8; 20], slot: [u8; 32], source: u8) -> Self {
        Self {
            address,
            slot,
            source,
        }
    }

    /// Serialize to bytes (53 bytes).
    pub fn to_bytes(&self) -> [u8; 53] {
        let mut bytes = [0u8; 53];
        bytes[..20].copy_from_slice(&self.address);
        bytes[20..52].copy_from_slice(&self.slot);
        bytes[52] = self.source;
        bytes
    }

    /// Deserialize from bytes.
    pub fn from_bytes(bytes: &[u8; 53]) -> Self {
        let mut address = [0u8; 20];
        let mut slot = [0u8; 32];
        address.copy_from_slice(&bytes[..20]);
        slot.copy_from_slice(&bytes[20..52]);
        Self {
            address,
            slot,
            source: bytes[52],
        }
    }
}

/// Address key: just address (20 bytes).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(C)]
pub struct AddressKey {
    pub address: [u8; 20],
}

impl AddressKey {
    pub fn new(address: [u8; 20]) -> Self {
        Self { address }
    }

    /// Serialize to bytes (20 bytes).
    pub fn to_bytes(&self) -> [u8; 20] {
        self.address
    }

    /// Deserialize from bytes.
    pub fn from_bytes(bytes: &[u8; 20]) -> Self {
        Self { address: *bytes }
    }
}

/// Block hints containing all keys accessed in a block.
#[derive(Debug, Clone, Default)]
pub struct BlockHints {
    pub block_number: u64,
    pub storage_keys: Vec<StorageKey>,
    pub bytecode_addresses: Vec<AddressKey>,
    pub account_addresses: Vec<AddressKey>,
}

impl BlockHints {
    pub fn new(block_number: u64) -> Self {
        Self {
            block_number,
            storage_keys: Vec::new(),
            bytecode_addresses: Vec::new(),
            account_addresses: Vec::new(),
        }
    }

    /// Serialize to binary format.
    /// Format:
    /// - [4 bytes] storage_count (u32 LE)
    /// - [53 * N bytes] storage keys (address + slot + source)
    /// - [4 bytes] bytecode_count (u32 LE)
    /// - [20 * N bytes] bytecode addresses
    /// - [4 bytes] account_count (u32 LE)
    /// - [20 * N bytes] account addresses
    pub fn serialize(&self) -> Vec<u8> {
        let size = 4 + self.storage_keys.len() * 53 + 4 + self.bytecode_addresses.len() * 20 + 4
            + self.account_addresses.len() * 20;

        let mut buf = Vec::with_capacity(size);

        // Storage keys
        buf.extend_from_slice(&(self.storage_keys.len() as u32).to_le_bytes());
        for key in &self.storage_keys {
            buf.extend_from_slice(&key.to_bytes());
        }

        // Bytecode addresses
        buf.extend_from_slice(&(self.bytecode_addresses.len() as u32).to_le_bytes());
        for addr in &self.bytecode_addresses {
            buf.extend_from_slice(&addr.to_bytes());
        }

        // Account addresses
        buf.extend_from_slice(&(self.account_addresses.len() as u32).to_le_bytes());
        for addr in &self.account_addresses {
            buf.extend_from_slice(&addr.to_bytes());
        }

        buf
    }

    /// Deserialize from binary format.
    pub fn deserialize(data: &[u8]) -> eyre::Result<Self> {
        let mut cursor = std::io::Cursor::new(data);

        // Storage keys
        let mut count_buf = [0u8; 4];
        cursor.read_exact(&mut count_buf)?;
        let storage_count = u32::from_le_bytes(count_buf) as usize;

        let mut storage_keys = Vec::with_capacity(storage_count);
        for _ in 0..storage_count {
            let mut key_buf = [0u8; 53];
            cursor.read_exact(&mut key_buf)?;
            storage_keys.push(StorageKey::from_bytes(&key_buf));
        }

        // Bytecode addresses
        cursor.read_exact(&mut count_buf)?;
        let bytecode_count = u32::from_le_bytes(count_buf) as usize;

        let mut bytecode_addresses = Vec::with_capacity(bytecode_count);
        for _ in 0..bytecode_count {
            let mut addr_buf = [0u8; 20];
            cursor.read_exact(&mut addr_buf)?;
            bytecode_addresses.push(AddressKey::from_bytes(&addr_buf));
        }

        // Account addresses
        cursor.read_exact(&mut count_buf)?;
        let account_count = u32::from_le_bytes(count_buf) as usize;

        let mut account_addresses = Vec::with_capacity(account_count);
        for _ in 0..account_count {
            let mut addr_buf = [0u8; 20];
            cursor.read_exact(&mut addr_buf)?;
            account_addresses.push(AddressKey::from_bytes(&addr_buf));
        }

        Ok(Self {
            block_number: 0, // Set by caller
            storage_keys,
            bytecode_addresses,
            account_addresses,
        })
    }

    /// Total number of keys.
    pub fn total_keys(&self) -> usize {
        self.storage_keys.len() + self.bytecode_addresses.len() + self.account_addresses.len()
    }

    /// Raw size in bytes (before compression).
    pub fn raw_size(&self) -> usize {
        self.storage_keys.len() * 53 + self.bytecode_addresses.len() * 20
            + self.account_addresses.len() * 20
    }
}
