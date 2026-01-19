//! KeyCollector inspector for collecting all accessed keys during block execution.

use ira_common::{AddressKey, StorageKey};
use reth_revm::revm::{
    bytecode::opcode::OpCode,
    context_interface::ContextTr,
    inspector::Inspector,
    interpreter::{
        interpreter::EthInterpreter,
        interpreter_types::{InputsTr, Jumps},
        Interpreter,
    },
};
use std::cell::RefCell;
use std::collections::HashSet;
use std::rc::Rc;

/// Inner state for the key collector.
#[derive(Debug, Default)]
pub struct CollectorState {
    pub storage_keys: HashSet<StorageKey>,
    pub bytecode_addresses: HashSet<AddressKey>,
    pub account_addresses: HashSet<AddressKey>,
}

impl CollectorState {
    pub fn new() -> Self {
        Self {
            storage_keys: HashSet::new(),
            bytecode_addresses: HashSet::new(),
            account_addresses: HashSet::new(),
        }
    }

    fn record_storage(&mut self, address: [u8; 20], slot: [u8; 32]) {
        self.storage_keys.insert(StorageKey::new(address, slot));
    }

    fn record_bytecode(&mut self, address: [u8; 20]) {
        self.bytecode_addresses.insert(AddressKey::new(address));
    }

    fn record_account(&mut self, address: [u8; 20]) {
        self.account_addresses.insert(AddressKey::new(address));
    }
}

pub type CollectorHandle = Rc<RefCell<CollectorState>>;

/// Inspector that collects all accessed keys during EVM execution.
#[derive(Debug, Clone)]
pub struct KeyCollector {
    state: CollectorHandle,
}

impl KeyCollector {
    pub fn new() -> Self {
        Self {
            state: Rc::new(RefCell::new(CollectorState::new())),
        }
    }

    pub fn handle(&self) -> CollectorHandle {
        Rc::clone(&self.state)
    }
}

impl<CTX> Inspector<CTX, EthInterpreter> for KeyCollector
where
    CTX: ContextTr,
{
    fn step(&mut self, interp: &mut Interpreter<EthInterpreter>, _context: &mut CTX) {
        let Some(opcode) = OpCode::new(interp.bytecode.opcode()) else {
            return;
        };

        let contract_address: [u8; 20] = interp.input.target_address().into_array();
        let mut state = self.state.borrow_mut();

        match opcode {
            // Storage operations
            OpCode::SLOAD | OpCode::SSTORE => {
                if let Some(slot) = get_stack_u256(interp, 0) {
                    state.record_storage(contract_address, slot);
                }
            }

            // Account balance operations
            OpCode::BALANCE => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_account(addr);
                }
            }
            OpCode::SELFBALANCE => {
                state.record_account(contract_address);
            }

            // External code operations
            OpCode::EXTCODESIZE | OpCode::EXTCODEHASH => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_account(addr);
                }
            }
            OpCode::EXTCODECOPY => {
                if let Some(addr) = get_stack_address(interp, 0) {
                    state.record_bytecode(addr);
                }
            }

            // Call operations - record bytecode access
            OpCode::CALL | OpCode::CALLCODE => {
                // Stack: [gas, address, value, argsOffset, argsSize, retOffset, retSize]
                if let Some(addr) = get_stack_address(interp, 1) {
                    state.record_bytecode(addr);
                }
            }
            OpCode::STATICCALL | OpCode::DELEGATECALL => {
                // Stack: [gas, address, argsOffset, argsSize, retOffset, retSize]
                if let Some(addr) = get_stack_address(interp, 1) {
                    state.record_bytecode(addr);
                }
            }

            // Create operations
            OpCode::CREATE | OpCode::CREATE2 => {
                state.record_bytecode(contract_address);
            }

            _ => {}
        }
    }
}

fn get_stack_u256(interp: &Interpreter<EthInterpreter>, pos: usize) -> Option<[u8; 32]> {
    let stack = &interp.stack;
    if stack.len() <= pos {
        return None;
    }
    let value = stack.peek(pos).ok()?;
    Some(value.to_be_bytes())
}

fn get_stack_address(interp: &Interpreter<EthInterpreter>, pos: usize) -> Option<[u8; 20]> {
    let bytes = get_stack_u256(interp, pos)?;
    let mut addr = [0u8; 20];
    addr.copy_from_slice(&bytes[12..32]);
    Some(addr)
}
