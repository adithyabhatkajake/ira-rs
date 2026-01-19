//! Block execution utilities.

use alloy_consensus::Transaction as TxTrait;
use alloy_primitives::TxKind;
use reth_ethereum::{primitives::SignerRecoverable, TransactionSigned};
use reth_revm::revm::{context::TxEnv, database::CacheDB, state::EvmState};

/// Commit state changes from transaction execution to the cache database.
pub fn commit_state_changes<DB>(db: &mut CacheDB<DB>, state: EvmState) {
    for (address, account) in state {
        if account.is_touched() {
            let db_account = db.cache.accounts.entry(address).or_default();
            db_account.info = account.info.clone();

            db_account.account_state = if account.is_selfdestructed() {
                reth_revm::revm::database::AccountState::NotExisting
            } else if account.is_created() {
                reth_revm::revm::database::AccountState::StorageCleared
            } else {
                reth_revm::revm::database::AccountState::Touched
            };

            for (slot, value) in account.storage {
                db_account.storage.insert(slot, value.present_value);
            }
        }
    }
}

/// Create a transaction environment from a signed transaction.
pub fn create_tx_env(tx: &TransactionSigned) -> TxEnv {
    let caller = tx.recover_signer().unwrap_or_default();
    let gas_limit = tx.gas_limit();
    let gas_price = tx.gas_price().unwrap_or(tx.max_fee_per_gas());
    let value = tx.value();
    let nonce = tx.nonce();
    let data = tx.input().clone();
    let kind = tx.to().map(TxKind::Call).unwrap_or(TxKind::Create);

    TxEnv {
        caller,
        gas_limit,
        gas_price: gas_price as u128,
        kind,
        value,
        data,
        nonce,
        ..Default::default()
    }
}
