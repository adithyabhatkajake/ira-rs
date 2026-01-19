//! State access inspector implementation.
//!
//! This inspector captures all EVM state access operations during block execution.
//! Uses interior mutability (Rc<RefCell>) to allow setting transaction index
//! while the EVM holds a mutable borrow of the inspector.

use crate::types::{OpType, StateOperation};

use alloy_primitives::Address;
use reth_revm::revm::{
    bytecode::opcode::OpCode,
    context_interface::{ContextTr, JournalTr},
    inspector::Inspector,
    interpreter::{
        interpreter::EthInterpreter,
        interpreter_types::{InputsTr, Jumps},
        Interpreter,
    },
};

use std::cell::RefCell;
use std::rc::Rc;

/// Inner state for the inspector, wrapped in Rc<RefCell> for interior mutability.
#[derive(Debug, Default)]
pub struct InspectorState {
    /// Collected state operations.
    pub operations: Vec<StateOperation>,
    /// Current block number.
    pub block_number: u64,
    /// Current transaction index within the block.
    pub tx_index: u16,
    /// Current operation index within the transaction.
    pub op_index: u32,
}

impl InspectorState {
    /// Set the current transaction index and reset operation counter.
    pub fn set_tx_index(&mut self, tx_index: u16) {
        self.tx_index = tx_index;
        self.op_index = 0;
    }

    /// Reset for a new block.
    pub fn set_block(&mut self, block_number: u64) {
        self.block_number = block_number;
        self.tx_index = 0;
        self.op_index = 0;
    }

    /// Take the collected operations, leaving an empty vec.
    pub fn take_operations(&mut self) -> Vec<StateOperation> {
        std::mem::take(&mut self.operations)
    }

    /// Record a storage operation.
    fn record_storage(&mut self, op_type: OpType, address: [u8; 20], slot: [u8; 32]) {
        self.operations.push(StateOperation::storage(
            self.block_number,
            self.tx_index,
            self.op_index,
            op_type,
            address,
            slot,
        ));
        self.op_index += 1;
    }

    /// Record an account operation.
    fn record_account(&mut self, op_type: OpType, address: [u8; 20]) {
        self.operations.push(StateOperation::account(
            self.block_number,
            self.tx_index,
            self.op_index,
            op_type,
            address,
        ));
        self.op_index += 1;
    }

    /// Record a bytecode operation.
    fn record_bytecode(&mut self, op_type: OpType, address: [u8; 20], size: Option<u32>) {
        self.operations.push(StateOperation::bytecode(
            self.block_number,
            self.tx_index,
            self.op_index,
            op_type,
            address,
            size,
        ));
        self.op_index += 1;
    }
}

/// Handle to the inspector state, allowing modification from outside the EVM.
pub type InspectorHandle = Rc<RefCell<InspectorState>>;

/// Inspector that captures all state access operations during EVM execution.
/// Uses Rc<RefCell> for interior mutability so tx_index can be set while
/// the EVM holds the inspector.
#[derive(Debug, Clone)]
pub struct StateAccessInspector {
    state: InspectorHandle,
}

impl StateAccessInspector {
    /// Create a new inspector for the given block.
    pub fn new(block_number: u64) -> Self {
        Self {
            state: Rc::new(RefCell::new(InspectorState {
                operations: Vec::new(),
                block_number,
                tx_index: 0,
                op_index: 0,
            })),
        }
    }

    /// Get a handle to the inspector state for external modification.
    /// Use this to set tx_index between transactions while the EVM holds the inspector.
    pub fn handle(&self) -> InspectorHandle {
        Rc::clone(&self.state)
    }
}

impl<CTX> Inspector<CTX, EthInterpreter> for StateAccessInspector
where
    CTX: ContextTr,
{
    fn step(&mut self, interp: &mut Interpreter<EthInterpreter>, context: &mut CTX) {
        // Get the current opcode
        let Some(opcode) = OpCode::new(interp.bytecode.opcode()) else {
            return;
        };

        // Get the contract address - this is the address being executed
        let contract_address: [u8; 20] = interp.input.target_address().into_array();

        // Borrow state mutably to record operations
        let mut state = self.state.borrow_mut();

        match opcode {
            // Storage operations - read slot from stack position 0
            OpCode::SLOAD => {
                if let Some(slot) = get_stack_u256(interp, 0) {
                    state.record_storage(OpType::SLoad, contract_address, slot);
                }
            }
            OpCode::SSTORE => {
                if let Some(slot) = get_stack_u256(interp, 0) {
                    state.record_storage(OpType::SStore, contract_address, slot);
                }
            }

            // Account balance operations - read address from stack
            OpCode::BALANCE => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_account(OpType::Balance, addr);
                }
            }
            OpCode::SELFBALANCE => {
                state.record_account(OpType::SelfBalance, contract_address);
            }

            // External code operations
            OpCode::EXTCODESIZE => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_account(OpType::ExtCodeSize, addr);
                }
            }
            OpCode::EXTCODEHASH => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_account(OpType::ExtCodeHash, addr);
                }
            }
            OpCode::EXTCODECOPY => {
                // Stack: [address, destOffset, offset, size]
                if let (Some(addr), Some(size)) =
                    (get_stack_address(interp, 0), get_stack_u32(interp, 3))
                {
                    state.record_bytecode(OpType::ExtCodeCopy, addr, Some(size));
                }
            }

            // Call operations - address at stack position 1
            OpCode::CALL | OpCode::CALLCODE => {
                // Stack: [gas, address, value, argsOffset, argsSize, retOffset, retSize]
                if let Some(addr) = get_stack_address(interp, 1) {
                    let op = if opcode == OpCode::CALL {
                        OpType::Call
                    } else {
                        OpType::CallCode
                    };
                    // Look up bytecode size for the target address
                    let size = get_code_size(context, addr);
                    state.record_bytecode(op, addr, size);
                }
            }
            OpCode::STATICCALL | OpCode::DELEGATECALL => {
                // Stack: [gas, address, argsOffset, argsSize, retOffset, retSize]
                if let Some(addr) = get_stack_address(interp, 1) {
                    let op = if opcode == OpCode::STATICCALL {
                        OpType::StaticCall
                    } else {
                        OpType::DelegateCall
                    };
                    // Look up bytecode size for the target address
                    let size = get_code_size(context, addr);
                    state.record_bytecode(op, addr, size);
                }
            }

            // Create operations
            OpCode::CREATE => {
                // Stack: [value, offset, size]
                // Note: Created address not known until after execution
                let size = get_stack_u32(interp, 2);
                state.record_bytecode(OpType::Create, contract_address, size);
            }
            OpCode::CREATE2 => {
                // Stack: [value, offset, size, salt]
                let size = get_stack_u32(interp, 2);
                state.record_bytecode(OpType::Create2, contract_address, size);
            }

            // Self destruct
            OpCode::SELFDESTRUCT => {
                // Stack: [beneficiary]
                if let Some(beneficiary) = get_stack_address(interp, 0) {
                    state.record_bytecode(OpType::SelfDestruct, beneficiary, None);
                }
            }

            _ => {}
        }
    }
}

/// Get a U256 value from the stack at the given position as bytes.
fn get_stack_u256(interp: &Interpreter<EthInterpreter>, pos: usize) -> Option<[u8; 32]> {
    let stack = &interp.stack;
    if stack.len() <= pos {
        return None;
    }
    let value = stack.peek(pos).ok()?;
    Some(value.to_be_bytes())
}

/// Get an address from the stack at the given position.
fn get_stack_address(interp: &Interpreter<EthInterpreter>, pos: usize) -> Option<[u8; 20]> {
    let bytes = get_stack_u256(interp, pos)?;
    // Address is in the lower 20 bytes (big-endian, so bytes 12..32)
    let mut addr = [0u8; 20];
    addr.copy_from_slice(&bytes[12..32]);
    Some(addr)
}

/// Get a u32 value from the stack at the given position.
fn get_stack_u32(interp: &Interpreter<EthInterpreter>, pos: usize) -> Option<u32> {
    let bytes = get_stack_u256(interp, pos)?;
    // Get the lower 4 bytes as u32
    let value = u32::from_be_bytes([bytes[28], bytes[29], bytes[30], bytes[31]]);
    Some(value)
}

/// Get the bytecode size for an address from the context's journal.
fn get_code_size<CTX>(context: &mut CTX, addr: [u8; 20]) -> Option<u32>
where
    CTX: ContextTr,
    CTX::Journal: JournalTr,
{
    let address = Address::from(addr);

    // Get the account's code from the journal
    let code = context.journal_mut().code(address).ok()?;
    Some(code.len() as u32)
}
