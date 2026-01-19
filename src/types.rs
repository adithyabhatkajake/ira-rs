//! Data types for state access tracing.

/// Operation type enum representing different EVM state access operations.
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OpType {
    // Storage operations
    SLoad = 0,
    SStore = 1,

    // Account operations
    Balance = 2,
    SelfBalance = 3,
    ExtCodeSize = 4,
    ExtCodeHash = 5,

    // Bytecode read operations
    ExtCodeCopy = 6,
    Call = 7,
    StaticCall = 8,
    DelegateCall = 9,
    CallCode = 10,

    // Bytecode write operations
    Create = 11,
    Create2 = 12,

    // Account modification
    SelfDestruct = 13,
}

impl OpType {
    /// Returns the operation type name as a string.
    pub fn name(&self) -> &'static str {
        match self {
            OpType::SLoad => "SLOAD",
            OpType::SStore => "SSTORE",
            OpType::Balance => "BALANCE",
            OpType::SelfBalance => "SELFBALANCE",
            OpType::ExtCodeSize => "EXTCODESIZE",
            OpType::ExtCodeHash => "EXTCODEHASH",
            OpType::ExtCodeCopy => "EXTCODECOPY",
            OpType::Call => "CALL",
            OpType::StaticCall => "STATICCALL",
            OpType::DelegateCall => "DELEGATECALL",
            OpType::CallCode => "CALLCODE",
            OpType::Create => "CREATE",
            OpType::Create2 => "CREATE2",
            OpType::SelfDestruct => "SELFDESTRUCT",
        }
    }
}

/// A single state access operation captured during EVM execution.
#[derive(Debug, Clone)]
pub struct StateOperation {
    /// Block number containing this operation.
    pub block_number: u64,
    /// Transaction index within the block.
    pub tx_index: u16,
    /// Operation index within the transaction.
    pub op_index: u32,
    /// Type of state access operation.
    pub op_type: OpType,
    /// Target contract/account address (20 bytes).
    pub target_address: [u8; 20],
    /// Storage slot for SLOAD/SSTORE operations (32 bytes), None for non-storage ops.
    pub storage_slot: Option<[u8; 32]>,
    /// Size in bytes for bytecode operations (EXTCODECOPY, CALL, etc.), None for non-bytecode ops.
    pub value_size: Option<u32>,
}

impl StateOperation {
    /// Create a new storage operation (SLOAD or SSTORE).
    pub fn storage(
        block_number: u64,
        tx_index: u16,
        op_index: u32,
        op_type: OpType,
        address: [u8; 20],
        slot: [u8; 32],
    ) -> Self {
        Self {
            block_number,
            tx_index,
            op_index,
            op_type,
            target_address: address,
            storage_slot: Some(slot),
            value_size: None,
        }
    }

    /// Create a new account operation (BALANCE, SELFBALANCE, etc.).
    pub fn account(
        block_number: u64,
        tx_index: u16,
        op_index: u32,
        op_type: OpType,
        address: [u8; 20],
    ) -> Self {
        Self {
            block_number,
            tx_index,
            op_index,
            op_type,
            target_address: address,
            storage_slot: None,
            value_size: None,
        }
    }

    /// Create a new bytecode operation (CALL, CREATE, etc.).
    pub fn bytecode(
        block_number: u64,
        tx_index: u16,
        op_index: u32,
        op_type: OpType,
        address: [u8; 20],
        size: Option<u32>,
    ) -> Self {
        Self {
            block_number,
            tx_index,
            op_index,
            op_type,
            target_address: address,
            storage_slot: None,
            value_size: size,
        }
    }
}

/// Collection of operations for a batch of blocks.
#[derive(Debug, Default)]
pub struct OperationBatch {
    pub operations: Vec<StateOperation>,
    pub start_block: u64,
    pub end_block: u64,
}

impl OperationBatch {
    pub fn new(start_block: u64, end_block: u64) -> Self {
        Self {
            operations: Vec::new(),
            start_block,
            end_block,
        }
    }

    pub fn push(&mut self, op: StateOperation) {
        self.operations.push(op);
    }

    pub fn len(&self) -> usize {
        self.operations.len()
    }

    pub fn is_empty(&self) -> bool {
        self.operations.is_empty()
    }
}
