//! Parquet writer for state operations.

use crate::types::StateOperation;
use arrow::{
    array::{
        ArrayRef, FixedSizeBinaryBuilder, UInt16Array, UInt32Array, UInt64Array, UInt8Array,
    },
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use parquet::{
    arrow::ArrowWriter,
    basic::{Compression, ZstdLevel},
    file::properties::WriterProperties,
};
use std::{fs::File, path::Path, sync::Arc};

/// Schema for the state operations Parquet file.
pub fn create_schema() -> Schema {
    Schema::new(vec![
        Field::new("block_number", DataType::UInt64, false),
        Field::new("tx_index", DataType::UInt16, false),
        Field::new("op_index", DataType::UInt32, false),
        Field::new("op_type", DataType::UInt8, false),
        Field::new("target_address", DataType::FixedSizeBinary(20), false),
        Field::new("storage_slot", DataType::FixedSizeBinary(32), true),
        Field::new("value_size", DataType::UInt32, true),
    ])
}

/// Write state operations to a Parquet file.
pub fn write_operations_to_parquet(
    operations: &[StateOperation],
    output_path: impl AsRef<Path>,
) -> eyre::Result<()> {
    if operations.is_empty() {
        return Ok(());
    }

    let schema = Arc::new(create_schema());

    // Build arrays
    let block_numbers: UInt64Array = operations.iter().map(|op| op.block_number).collect();

    let tx_indices: UInt16Array = operations.iter().map(|op| op.tx_index).collect();

    let op_indices: UInt32Array = operations.iter().map(|op| op.op_index).collect();

    let op_types: UInt8Array = operations.iter().map(|op| op.op_type as u8).collect();

    // Build target addresses (non-nullable)
    let target_addresses = {
        let mut builder = FixedSizeBinaryBuilder::new(20);
        for op in operations {
            builder.append_value(&op.target_address)?;
        }
        builder.finish()
    };

    // Build storage slots (nullable)
    let storage_slots = {
        let mut builder = FixedSizeBinaryBuilder::new(32);
        for op in operations {
            if let Some(slot) = &op.storage_slot {
                builder.append_value(slot)?;
            } else {
                builder.append_null();
            }
        }
        builder.finish()
    };

    // Build value sizes (nullable)
    let value_sizes: UInt32Array = operations.iter().map(|op| op.value_size).collect();

    // Create record batch
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(block_numbers) as ArrayRef,
            Arc::new(tx_indices) as ArrayRef,
            Arc::new(op_indices) as ArrayRef,
            Arc::new(op_types) as ArrayRef,
            Arc::new(target_addresses) as ArrayRef,
            Arc::new(storage_slots) as ArrayRef,
            Arc::new(value_sizes) as ArrayRef,
        ],
    )?;

    // Write to Parquet with ZSTD compression
    let file = File::create(output_path)?;
    let props = WriterProperties::builder()
        .set_compression(Compression::ZSTD(ZstdLevel::try_new(3)?))
        .set_max_row_group_size(100_000)
        .build();

    let mut writer = ArrowWriter::try_new(file, schema, Some(props))?;
    writer.write(&batch)?;
    writer.close()?;

    Ok(())
}

/// Generate the output filename for a batch of blocks.
pub fn batch_filename(output_dir: impl AsRef<Path>, start_block: u64, end_block: u64) -> String {
    output_dir
        .as_ref()
        .join(format!("ops_{}_{}.parquet", start_block, end_block))
        .to_string_lossy()
        .to_string()
}
