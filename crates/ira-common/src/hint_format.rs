//! Hint file format for reading and writing block hints.
//!
//! File format (28-byte header + payload):
//! - [8 bytes] Magic: "IRABHINT"
//! - [4 bytes] Version: 1
//! - [8 bytes] Block number (u64 LE)
//! - [4 bytes] Uncompressed size (u32 LE)
//! - [4 bytes] Compressed size (u32 LE)
//! - [...] Zstd-compressed BlockHints

use crate::types::BlockHints;
use eyre::{bail, Context, Result};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

const MAGIC: &[u8; 8] = b"IRABHINT";
const VERSION: u32 = 2; // v2: Added source byte to StorageKey (53 bytes instead of 52)
const HEADER_SIZE: usize = 28;
const BATCH_SIZE: u64 = 10_000;

/// Get the hint file path for a block number.
pub fn hint_path(hint_dir: &Path, block_number: u64) -> PathBuf {
    let batch_start = (block_number / BATCH_SIZE) * BATCH_SIZE;
    let batch_end = batch_start + BATCH_SIZE - 1;
    hint_dir
        .join(format!("batch_{}_{}", batch_start, batch_end))
        .join(format!("{}.hint.zst", block_number))
}

/// Writer for hint files.
pub struct HintWriter {
    hint_dir: PathBuf,
    compression_level: i32,
}

impl HintWriter {
    pub fn new(hint_dir: impl AsRef<Path>, compression_level: i32) -> Self {
        Self {
            hint_dir: hint_dir.as_ref().to_path_buf(),
            compression_level,
        }
    }

    /// Write a block's hints to the appropriate file.
    pub fn write(&self, hints: &BlockHints) -> Result<(usize, usize)> {
        let path = hint_path(&self.hint_dir, hints.block_number);

        // Ensure directory exists
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .wrap_err_with(|| format!("Failed to create directory {:?}", parent))?;
        }

        // Serialize hints
        let raw_data = hints.serialize();
        let raw_size = raw_data.len();

        // Compress
        let compressed = zstd::encode_all(&raw_data[..], self.compression_level)
            .wrap_err("Failed to compress hints")?;
        let compressed_size = compressed.len();

        // Write file
        let file = File::create(&path)
            .wrap_err_with(|| format!("Failed to create hint file {:?}", path))?;
        let mut writer = BufWriter::new(file);

        // Write header
        writer.write_all(MAGIC)?;
        writer.write_all(&VERSION.to_le_bytes())?;
        writer.write_all(&hints.block_number.to_le_bytes())?;
        writer.write_all(&(raw_size as u32).to_le_bytes())?;
        writer.write_all(&(compressed_size as u32).to_le_bytes())?;

        // Write compressed payload
        writer.write_all(&compressed)?;
        writer.flush()?;

        Ok((raw_size, compressed_size))
    }
}

/// Reader for hint files.
pub struct HintReader {
    hint_dir: PathBuf,
}

impl HintReader {
    pub fn new(hint_dir: impl AsRef<Path>) -> Self {
        Self {
            hint_dir: hint_dir.as_ref().to_path_buf(),
        }
    }

    /// Read a block's hints from the file.
    /// Returns (hints, compressed_size, decompress_time_us).
    pub fn read(&self, block_number: u64) -> Result<(BlockHints, usize)> {
        let path = hint_path(&self.hint_dir, block_number);

        let file = File::open(&path)
            .wrap_err_with(|| format!("Failed to open hint file {:?}", path))?;
        let mut reader = BufReader::new(file);

        // Read header
        let mut header = [0u8; HEADER_SIZE];
        reader.read_exact(&mut header)?;

        // Validate magic
        if &header[0..8] != MAGIC {
            bail!("Invalid hint file magic");
        }

        // Validate version
        let version = u32::from_le_bytes(header[8..12].try_into().unwrap());
        if version != VERSION {
            bail!("Unsupported hint file version: {}", version);
        }

        // Read metadata
        let file_block_number = u64::from_le_bytes(header[12..20].try_into().unwrap());
        if file_block_number != block_number {
            bail!(
                "Block number mismatch: expected {}, got {}",
                block_number,
                file_block_number
            );
        }

        let _uncompressed_size = u32::from_le_bytes(header[20..24].try_into().unwrap());
        let compressed_size = u32::from_le_bytes(header[24..28].try_into().unwrap()) as usize;

        // Read compressed data
        let mut compressed = vec![0u8; compressed_size];
        reader.read_exact(&mut compressed)?;

        // Decompress
        let decompressed =
            zstd::decode_all(&compressed[..]).wrap_err("Failed to decompress hints")?;

        // Deserialize
        let mut hints = BlockHints::deserialize(&decompressed)?;
        hints.block_number = block_number;

        Ok((hints, compressed_size))
    }

    /// Check if hint file exists for a block.
    pub fn exists(&self, block_number: u64) -> bool {
        hint_path(&self.hint_dir, block_number).exists()
    }
}

// ============================================================================
// Database-backed hint storage using redb
// ============================================================================

use redb::{Database, TableDefinition};

const HINTS_TABLE: TableDefinition<u64, &[u8]> = TableDefinition::new("hints");

/// Database path for hints.
pub fn hints_db_path(hint_dir: &Path) -> PathBuf {
    hint_dir.join("hints.redb")
}

/// Writer for hint database (redb).
/// Stores hints in a single mmap'd B-tree database for efficient batch reads.
pub struct HintDbWriter {
    db: Database,
    compression_level: i32,
}

impl HintDbWriter {
    /// Create a new hint database writer.
    /// Creates the database file if it doesn't exist.
    pub fn new(hint_dir: impl AsRef<Path>, compression_level: i32) -> Result<Self> {
        let db_path = hints_db_path(hint_dir.as_ref());

        // Ensure directory exists
        if let Some(parent) = db_path.parent() {
            fs::create_dir_all(parent)
                .wrap_err_with(|| format!("Failed to create directory {:?}", parent))?;
        }

        let db = Database::create(&db_path)
            .wrap_err_with(|| format!("Failed to create hint database at {:?}", db_path))?;

        Ok(Self {
            db,
            compression_level,
        })
    }

    /// Write a block's hints to the database.
    /// Returns (raw_size, compressed_size).
    pub fn write(&self, hints: &BlockHints) -> Result<(usize, usize)> {
        // Serialize hints
        let raw_data = hints.serialize();
        let raw_size = raw_data.len();

        // Compress
        let compressed = zstd::encode_all(&raw_data[..], self.compression_level)
            .wrap_err("Failed to compress hints")?;
        let compressed_size = compressed.len();

        // Write to database
        let write_txn = self.db.begin_write()
            .wrap_err("Failed to begin write transaction")?;
        {
            let mut table = write_txn.open_table(HINTS_TABLE)
                .wrap_err("Failed to open hints table")?;
            table.insert(hints.block_number, compressed.as_slice())
                .wrap_err_with(|| format!("Failed to insert hints for block {}", hints.block_number))?;
        }
        write_txn.commit()
            .wrap_err("Failed to commit write transaction")?;

        Ok((raw_size, compressed_size))
    }

    /// Compact the database (optional, call after bulk writes).
    pub fn compact(&mut self) -> Result<()> {
        self.db.compact()
            .wrap_err("Failed to compact database")?;
        Ok(())
    }
}

/// Reader for hint database (redb).
/// Uses mmap for efficient sequential access to hints.
pub struct HintDbReader {
    db: Database,
}

impl HintDbReader {
    /// Open an existing hint database for reading.
    pub fn new(hint_dir: impl AsRef<Path>) -> Result<Self> {
        let db_path = hints_db_path(hint_dir.as_ref());

        let db = Database::open(&db_path)
            .wrap_err_with(|| format!("Failed to open hint database at {:?}", db_path))?;

        Ok(Self { db })
    }

    /// Read a single block's hints from the database.
    /// Returns (hints, compressed_size).
    pub fn read(&self, block_number: u64) -> Result<(BlockHints, usize)> {
        let read_txn = self.db.begin_read()
            .wrap_err("Failed to begin read transaction")?;
        let table = read_txn.open_table(HINTS_TABLE)
            .wrap_err("Failed to open hints table")?;

        let compressed = table.get(block_number)
            .wrap_err_with(|| format!("Failed to get hints for block {}", block_number))?
            .ok_or_else(|| eyre::eyre!("Hints not found for block {}", block_number))?;

        let compressed_bytes = compressed.value();
        let compressed_size = compressed_bytes.len();

        // Decompress
        let decompressed = zstd::decode_all(compressed_bytes)
            .wrap_err("Failed to decompress hints")?;

        // Deserialize
        let mut hints = BlockHints::deserialize(&decompressed)?;
        hints.block_number = block_number;

        Ok((hints, compressed_size))
    }

    /// Batch read multiple blocks' hints in a single transaction.
    /// This is much more efficient than calling read() in a loop because:
    /// - Single transaction overhead amortized across all reads
    /// - B-tree cursor can exploit sequential access patterns
    /// Returns Vec of (block_number, hints) for blocks that exist.
    pub fn read_batch(&self, block_numbers: &[u64]) -> Result<Vec<(u64, BlockHints)>> {
        let read_txn = self.db.begin_read()
            .wrap_err("Failed to begin read transaction")?;
        let table = read_txn.open_table(HINTS_TABLE)
            .wrap_err("Failed to open hints table")?;

        let mut results = Vec::with_capacity(block_numbers.len());

        for &block_num in block_numbers {
            if let Some(compressed) = table.get(block_num)
                .wrap_err_with(|| format!("Failed to get hints for block {}", block_num))?
            {
                let decompressed = zstd::decode_all(compressed.value())
                    .wrap_err_with(|| format!("Failed to decompress hints for block {}", block_num))?;

                let mut hints = BlockHints::deserialize(&decompressed)?;
                hints.block_number = block_num;
                results.push((block_num, hints));
            }
        }

        Ok(results)
    }

    /// Check if hints exist for a block.
    pub fn exists(&self, block_number: u64) -> bool {
        let Ok(read_txn) = self.db.begin_read() else {
            return false;
        };
        let Ok(table) = read_txn.open_table(HINTS_TABLE) else {
            return false;
        };
        table.get(block_number).ok().flatten().is_some()
    }

    /// Check if the database file exists.
    pub fn db_exists(hint_dir: impl AsRef<Path>) -> bool {
        hints_db_path(hint_dir.as_ref()).exists()
    }
}
