//! Integration tests pinning the mint-hook contract semantics defined by
//! [`crate::NftTicketTrait`]. See issue #635.
//!
//! These tests exercise the trait/client boundary directly with a mock NFT
//! contract — they do not exercise `raffle-instance`'s purchase flow (which,
//! as of this writing, does not yet invoke the hook; see the rustdoc on
//! `NftTicketTrait` for the documented contract this test suite pins).

#![cfg(test)]

use crate::{NftTicketClient, NftTicketTrait};
use soroban_sdk::{contract, contractimpl, testutils::Address as _, Address, Env, Vec};

/// Storage key for the mock's recorded mint calls.
#[derive(Clone)]
#[soroban_sdk::contracttype]
pub struct RecordedMint {
    pub recipient: Address,
    pub ticket_id: u32,
    pub raffle_id: Address,
}

#[soroban_sdk::contracttype]
enum MockDataKey {
    Calls,
    ShouldPanic,
}

/// A mock NFT ticket contract that records every `mint` call it receives.
/// Panics on `mint` when armed via `set_should_panic`, to let tests pin the
/// failure-propagation semantics of the hook.
#[contract]
pub struct MockNftContract;

#[contractimpl]
impl MockNftContract {
    /// Arms/disarms panic-on-mint for failure-path tests.
    pub fn set_should_panic(env: Env, value: bool) {
        env.storage().instance().set(&MockDataKey::ShouldPanic, &value);
    }

    /// Returns every recorded mint call, in call order.
    pub fn get_calls(env: Env) -> Vec<RecordedMint> {
        env.storage()
            .instance()
            .get(&MockDataKey::Calls)
            .unwrap_or(Vec::new(&env))
    }
}

#[contractimpl]
impl NftTicketTrait for MockNftContract {
    fn mint(env: Env, recipient: Address, ticket_id: u32, raffle_id: Address) {
        let should_panic: bool = env
            .storage()
            .instance()
            .get(&MockDataKey::ShouldPanic)
            .unwrap_or(false);
        if should_panic {
            panic!("mock NFT contract: mint reverted");
        }
        let mut calls: Vec<RecordedMint> = env
            .storage()
            .instance()
            .get(&MockDataKey::Calls)
            .unwrap_or(Vec::new(&env));
        calls.push_back(RecordedMint {
            recipient,
            ticket_id,
            raffle_id,
        });
        env.storage().instance().set(&MockDataKey::Calls, &calls);
    }
}

fn setup(env: &Env) -> (Address, MockNftContractClient<'_>) {
    let contract_id = env.register(MockNftContract, ());
    let client = MockNftContractClient::new(env, &contract_id);
    (contract_id, client)
}

/// One `mint` call per ticket purchase, with the correct recipient,
/// ticket_id, and raffle namespace recorded — the core "happy path"
/// acceptance criterion.
#[test]
fn mint_records_one_call_per_ticket_with_correct_args() {
    let env = Env::default();
    let (_nft_id, nft_client) = setup(&env);

    let raffle_id = Address::generate(&env);
    let buyer = Address::generate(&env);

    // Simulate the raffle instance minting one NFT per ticket after a
    // 3-ticket purchase.
    nft_client.mint(&buyer, &1, &raffle_id);
    nft_client.mint(&buyer, &2, &raffle_id);
    nft_client.mint(&buyer, &3, &raffle_id);

    let calls = nft_client.get_calls();
    assert_eq!(calls.len(), 3);

    for (i, expected_ticket_id) in [1u32, 2u32, 3u32].into_iter().enumerate() {
        let call = calls.get(i as u32).unwrap();
        assert_eq!(call.recipient, buyer);
        assert_eq!(call.ticket_id, expected_ticket_id);
        assert_eq!(call.raffle_id, raffle_id);
    }
}

/// Two different raffle instances minting through the same NFT contract are
/// correctly namespaced by `raffle_id` — ticket_id alone is not globally
/// unique, only unique within a raffle.
#[test]
fn mint_namespaces_ticket_ids_by_raffle_id() {
    let env = Env::default();
    let (_nft_id, nft_client) = setup(&env);

    let raffle_a = Address::generate(&env);
    let raffle_b = Address::generate(&env);
    let buyer = Address::generate(&env);

    nft_client.mint(&buyer, &1, &raffle_a);
    nft_client.mint(&buyer, &1, &raffle_b);

    let calls = nft_client.get_calls();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls.get(0).unwrap().raffle_id, raffle_a);
    assert_eq!(calls.get(1).unwrap().raffle_id, raffle_b);
}

/// Documents and pins the failure semantics decision (see rustdoc on
/// `NftTicketTrait::mint`): a reverting NFT contract call is fatal to the
/// calling transaction. `NftTicketClient::mint` (as opposed to `try_mint`)
/// propagates the panic rather than swallowing it, so a raffle instance that
/// calls `.mint()` directly (not `.try_mint()`) gets atomic all-or-nothing
/// semantics for free from the host — the ticket purchase and the NFT mint
/// either both succeed or both roll back.
#[test]
#[should_panic(expected = "mock NFT contract: mint reverted")]
fn reverting_mint_propagates_panic_to_caller() {
    let env = Env::default();
    let (_nft_id, nft_client) = setup(&env);
    nft_client.set_should_panic(&true);

    let raffle_id = Address::generate(&env);
    let buyer = Address::generate(&env);

    // A caller using `.mint()` (not `.try_mint()`) gets the panic
    // propagated — this call aborts the host transaction.
    nft_client.mint(&buyer, &1, &raffle_id);
}

/// The soft-fail counterpart: a caller that explicitly opts into
/// `try_mint` observes the failure as a `Result` instead of an aborted
/// transaction. This is *not* the behavior raffle-instance uses today (see
/// module docs), but it's pinned here so the trade-off is explicit: if a
/// future caller wants purchases to survive a broken NFT contract, this is
/// the call it must use instead of `.mint()`.
#[test]
fn try_mint_surfaces_failure_as_result_without_aborting() {
    let env = Env::default();
    let (_nft_id, nft_client) = setup(&env);
    nft_client.set_should_panic(&true);

    let raffle_id = Address::generate(&env);
    let buyer = Address::generate(&env);

    let result = nft_client.try_mint(&buyer, &1, &raffle_id);
    assert!(result.is_err());

    // No call was recorded — the panic happened before the record step.
    nft_client.set_should_panic(&false);
    assert_eq!(nft_client.get_calls().len(), 0);
}

/// The no-NFT-configured path: nothing in `raffle-shared` requires an NFT
/// contract to exist at all. Callers that never construct an
/// `NftTicketClient` are entirely unaffected by this trait — there is no
/// hook to fail, and no state managed by this module in that case. This
/// test exists to make that (currently implicit) contract explicit: it's a
/// smoke test that the mock/trait plumbing itself imposes no requirement
/// that every consumer wire it up.
#[test]
fn no_nft_configured_path_is_a_no_op_by_construction() {
    let env = Env::default();
    // No NftTicketClient is registered or called at all — purchase-like
    // logic that never references this trait is, by construction,
    // unaffected by it. Nothing to assert beyond "this compiles and the
    // env is otherwise unused," which is the point: the hook is opt-in.
    let _ = env;
}