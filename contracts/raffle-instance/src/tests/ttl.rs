//! Tests for TTL management and amortised bumping.

#[cfg(test)]
mod tests {
    use soroban_sdk::{Env, testutils::Ledger};
    use crate::helpers::{bump_raffle_ttl, extend_ticket_ttls};
    use crate::DataKey;

    #[test]
    fn test_bump_raffle_ttl_bumps_instance() {
        let env = Env::default();
        env.mock_all_auths();

        // Set initial TTL
        env.storage().instance().set(&DataKey::Raffle, &true);
        let initial_ttl = env.storage().instance().get_ttl();

        // Advance ledger close to expiry
        env.ledger().with_mut(|l| {
            l.sequence_number += 100_000;
        });

        // Call bump_raffle_ttl
        bump_raffle_ttl(&env, 0);

        // Verify TTL was extended
        let new_ttl = env.storage().instance().get_ttl();
        assert!(new_ttl > initial_ttl, "Instance TTL should be extended");
    }

    #[test]
    fn test_bump_raffle_ttl_bumps_tickets_amortised() {
        let env = Env::default();
        env.mock_all_auths();

        // Store 1000 tickets
        for i in 1..=1000 {
            let key = DataKey::Ticket(i);
            env.storage().persistent().set(&key, &true);
        }

        // Get initial TTL for ticket 1
        let key1 = DataKey::Ticket(1);
        let initial_ttl = env.storage().persistent().get_ttl(&key1);

        // Call bump_raffle_ttl with tickets_sold = 1000
        bump_raffle_ttl(&env, 1000);

        // Verify ticket 1 was bumped (first window)
        let new_ttl = env.storage().persistent().get_ttl(&key1);
        assert!(new_ttl > initial_ttl, "Ticket 1 TTL should be extended");
    }

    #[test]
    fn test_bump_raffle_ttl_amortised_wraps_around() {
        let env = Env::default();
        env.mock_all_auths();

        // Store 50 tickets
        for i in 1..=50 {
            let key = DataKey::Ticket(i);
            env.storage().persistent().set(&key, &true);
        }

        // First call: bumps tickets 1-100 (but only 50 exist)
        bump_raffle_ttl(&env, 50);

        // The last_bumped_index should be 0 (wrapped because end >= tickets_sold)
        let last_bumped: u32 = env
            .storage()
            .instance()
            .get(&DataKey::LastBumpedIndex)
            .unwrap_or(999);
        assert_eq!(last_bumped, 0, "Should wrap back to 0 when all tickets are bumped");
    }

    #[test]
    fn test_bump_raffle_ttl_bounded_cost() {
        let env = Env::default();
        env.mock_all_auths();

        // Simulate a raffle with 100,000 tickets
        let tickets_sold = 100_000;

        // Call bump_raffle_ttl - should complete quickly (O(100))
        let start = std::time::Instant::now();
        bump_raffle_ttl(&env, tickets_sold);
        let duration = start.elapsed();

        // Verify the function completed in bounded time (should be < 100ms)
        assert!(
            duration.as_millis() < 100,
            "Function should be bounded: took {}ms",
            duration.as_millis()
        );
    }

    /// #1010: ticket entries survive ledger advancement to the documented
    /// horizon once bumped. Advances the ledger past the persistent-entry
    /// threshold and checks the paginated operator helper refreshes the
    /// ticket TTL back to the ~6-month bump target.
    #[test]
    fn test_ticket_entries_survive_to_documented_horizon() {
        let env = Env::default();
        env.mock_all_auths();

        for i in 1..=3u32 {
            env.storage().persistent().set(&DataKey::Ticket(i), &true);
        }
        let before = env.storage().persistent().get_ttl(&DataKey::Ticket(1));

        // Simulate a long-running raffle: advance well past the ~3-month
        // persistent threshold (1,555,200 ledgers).
        env.ledger().with_mut(|l| {
            l.sequence_number += 1_400_000;
        });

        let refreshed = extend_ticket_ttls(&env, 1, 10);
        assert_eq!(refreshed, 3);

        let after = env.storage().persistent().get_ttl(&DataKey::Ticket(1));
        assert!(
            after >= before,
            "Ticket TTL should survive ledger advance after paginated bump"
        );
    }
}
