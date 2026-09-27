//! Factory instruction-budget regression tests (#831).

use raffle_shared::{PaginationParams, MAX_PAGE_LIMIT};
use soroban_sdk::{testutils::Address as _, Address, BytesN, Env, String, Vec as SdkVec};

use crate::{RaffleConfig, RaffleFactory, RaffleFactoryClient, RandomnessSource};

const TOLERANCE_FRACTION: f64 = 0.10;

const CREATE_RAFFLE: Baseline = Baseline {
    cpu_instructions: 25_000_000,
    memory_bytes: 8 * 1024 * 1024,
};
const GET_RAFFLES_PAGE_MAX: Baseline = Baseline {
    cpu_instructions: 15_000_000,
    memory_bytes: 5 * 1024 * 1024,
};

#[derive(Clone, Copy)]
struct Baseline {
    cpu_instructions: u64,
    memory_bytes: u64,
}

#[derive(Debug, Clone, Copy)]
struct Snapshot {
    cpu: u64,
    mem: u64,
}

fn measure<F: FnOnce()>(env: &Env, f: F) -> Snapshot {
    env.cost_estimate().budget().reset_default();
    f();
    let budget = env.cost_estimate().budget();
    Snapshot {
        cpu: budget.cpu_instruction_cost(),
        mem: budget.memory_bytes_cost(),
    }
}

fn assert_within_tolerance(label: &str, actual: Snapshot, baseline: Baseline) {
    let cpu_limit =
        ((baseline.cpu_instructions as f64) * (1.0 + TOLERANCE_FRACTION)).ceil() as u64;
    let mem_limit = ((baseline.memory_bytes as f64) * (1.0 + TOLERANCE_FRACTION)).ceil() as u64;
    assert!(actual.cpu <= cpu_limit, "{label}: cpu {} > {cpu_limit}", actual.cpu);
    assert!(actual.mem <= mem_limit, "{label}: memory {} > {mem_limit}", actual.mem);
}

fn setup_factory(env: &Env) -> (RaffleFactoryClient<'_>, Address, Address) {
    let admin = Address::generate(env);
    let treasury = Address::generate(env);
    let wasm_hash = BytesN::from_array(env, &[0u8; 32]);
    let contract_id = env.register(RaffleFactory, ());
    let client = RaffleFactoryClient::new(env, &contract_id);
    env.mock_all_auths();
    client.init_factory(&admin, &wasm_hash, &0u32, &treasury);
    client.set_creation_delay(&0u64);
    (client, admin, treasury)
}

fn test_config(env: &Env, payment_token: &Address) -> RaffleConfig {
    RaffleConfig {
        description: String::from_str(env, "budget"),
        end_time: 0,
        no_deadline: true,
        max_tickets: 10,
        max_tickets_per_tx: 10,
        max_tickets_per_address: 0,
        min_tickets: 1,
        allow_multiple: true,
        ticket_price: 10_000,
        payment_token: payment_token.clone(),
        prize_amount: 10_000,
        prizes: SdkVec::from_array(env, [10_000u32]),
        randomness_source: RandomnessSource::Internal,
        oracle_address: None,
        protocol_fee_bp: 0,
        treasury_address: None,
        swap_router: None,
        tikka_token: None,
        metadata_hash: BytesN::from_array(env, &[1u8; 32]),
        claim_lockup_seconds: None,
        swap_deadline_seconds: None,
        early_bird_ticket_percentage: 0,
        early_bird_discount_bp: 0,
        category: None,
        unique_winners: false,
        bundles: SdkVec::new(env),
        prize_token: None,
        nft_contract: None,
    }
}

#[test]
fn create_raffle_within_baseline() {
    let env = Env::default();
    let (client, _, treasury) = setup_factory(&env);
    let creator = Address::generate(&env);
    let token = env
        .register_stellar_asset_contract_v2(Address::generate(&env))
        .address();
    let mut config = test_config(&env, &token);
    config.treasury_address = Some(treasury);

    let snap = measure(&env, || {
        client.create_raffle(&creator, &config);
    });
    assert_within_tolerance("create_raffle", snap, CREATE_RAFFLE);
}

#[test]
fn get_raffles_page_at_max_limit_within_baseline() {
    let env = Env::default();
    let (client, _, treasury) = setup_factory(&env);
    let creator = Address::generate(&env);
    let token = env
        .register_stellar_asset_contract_v2(Address::generate(&env))
        .address();

    for i in 0..MAX_PAGE_LIMIT {
        let mut config = test_config(&env, &token);
        config.description = String::from_str(&env, &format!("r{i}"));
        config.treasury_address = Some(treasury.clone());
        client.create_raffle(&creator, &config);
    }

    let snap = measure(&env, || {
        let page = client.get_raffles_page(&PaginationParams {
            limit: MAX_PAGE_LIMIT,
            offset: 0,
        });
        assert_eq!(page.items.len() as u32, MAX_PAGE_LIMIT);
    });
    assert_within_tolerance("get_raffles_page_max", snap, GET_RAFFLES_PAGE_MAX);
}
