-- Narrow covering indexes keep the stats refresh out of the full event heap.
-- Run with autocommit; concurrent builds leave gameplay writes available.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_tricks_stats
ON twomanspades.game_events (hand_id, hand_number) INCLUDE (event_data)
WHERE event_type = 'trick_completed';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_completed_stats
ON twomanspades.game_events (hand_id, hand_number, timestamp) INCLUDE (event_data)
WHERE event_type = 'hand_completed';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_bids_stats
ON twomanspades.game_events (hand_id, hand_number, player) INCLUDE (event_type, event_data)
WHERE event_type IN ('action_regular_bid', 'action_blind_bid');
