"""Two-Man Spades achievements database operations."""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import os
import threading
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List
from .connection import get_db_connection
from .connection import return_db_connection

def get_player_achievements() -> Dict[str, Any]:
    """Get notable achievements for all known players (Tom/Luke/Jon/Andy).
    Uses vw_player_game_details view (based on game_completed events)."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Bid accuracy - uses player identity from view
        # Must join by BOTH hand_id AND hand_number to compare per-round bids to per-round tricks
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id,
                    ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            tricks_data AS (
                SELECT hand_id, hand_number, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                COUNT(*) as hands,
                ROUND(AVG(b.bid), 2) as avg_bid,
                ROUND(AVG(COALESCE(t.player_tricks, 0)), 2) as avg_tricks,
                SUM(CASE WHEN COALESCE(t.player_tricks, 0) = b.bid THEN 1 ELSE 0 END) as exact_bids,
                ROUND(100.0 * SUM(CASE WHEN COALESCE(t.player_tricks, 0) = b.bid THEN 1 ELSE 0 END) / COUNT(*), 1) as exact_pct
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id AND b.hand_number = t.hand_number
            GROUP BY b.player ORDER BY exact_pct DESC
        ''')
        bid_accuracy = [dict(row) for row in cur.fetchall()]

        # Nil stats - must join by hand_number to count tricks only in the nil round
        cur.execute('''
            WITH nil_bids AS (
                SELECT v.player_name as player, ge.hand_id, ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND (ge.event_data->'action_data'->>'bid_amount') = '0'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            nil_results AS (
                SELECT n.player, n.hand_id, n.hand_number, COALESCE(COUNT(t.*), 0) as tricks_taken
                FROM nil_bids n
                LEFT JOIN twomanspades.game_events t ON n.hand_id = t.hand_id
                    AND n.hand_number = t.hand_number
                    AND t.event_type = 'trick_completed' AND t.event_data->>'winner' = 'player'
                GROUP BY n.player, n.hand_id, n.hand_number
            )
            SELECT player, COUNT(*) as attempts,
                SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) as successful,
                ROUND(100.0 * SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as rate
            FROM nil_results GROUP BY player ORDER BY attempts DESC
        ''')
        nil_stats = [dict(row) for row in cur.fetchall()]

        # Closest wins (Nail-biters) - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT v.player_name as player, v.hand_id, v.final_player_score, v.final_computer_score,
                   v.margin, v.player_bags, COALESCE(v.completed_at, gc.timestamp) as completed_at
            FROM twomanspades.vw_player_game_details v
            LEFT JOIN twomanspades.game_events gc ON v.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
            WHERE v.won = true AND v.player_name != 'Other'
            AND v.final_player_score IS NOT NULL
            ORDER BY v.margin ASC LIMIT 5
        ''')
        closest_wins = [dict(row) for row in cur.fetchall()]

        # Biggest blowouts - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT v.player_name as player, v.hand_id, v.final_player_score, v.final_computer_score,
                   v.margin, v.player_bags, COALESCE(v.completed_at, gc.timestamp) as completed_at
            FROM twomanspades.vw_player_game_details v
            LEFT JOIN twomanspades.game_events gc ON v.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
            WHERE v.won = true AND v.player_name != 'Other'
            AND v.final_player_score IS NOT NULL
            ORDER BY v.margin DESC LIMIT 5
        ''')
        biggest_wins = [dict(row) for row in cur.fetchall()]

        # Current streaks - show every player's current streak (win or loss)
        # Uses game_events timestamp (always populated) instead of completed_at (can be NULL)
        # Also includes the date of the last opposite result (last loss for win streaks, etc.)
        cur.execute('''
            WITH recent_games AS (
                SELECT
                    v.player_name as player,
                    v.hand_id,
                    ge.timestamp as game_time,
                    v.won,
                    v.final_player_score,
                    v.final_computer_score,
                    ROW_NUMBER() OVER (PARTITION BY v.player_name ORDER BY ge.timestamp DESC) as rn
                FROM twomanspades.vw_player_game_details v
                JOIN twomanspades.game_events ge ON v.hand_id = ge.hand_id
                    AND ge.event_type = 'game_completed'
                WHERE v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            first_result AS (
                SELECT player, won as on_win_streak
                FROM recent_games WHERE rn = 1
            ),
            player_counts AS (
                SELECT player, MAX(rn) as total_games
                FROM recent_games
                GROUP BY player
            ),
            streak_calc AS (
                SELECT
                    r.player,
                    f.on_win_streak,
                    -- If no streak-breaking game found, streak = total games
                    COALESCE(
                        MIN(CASE WHEN r.won != f.on_win_streak THEN r.rn ELSE NULL END) - 1,
                        pc.total_games
                    ) as streak
                FROM recent_games r
                JOIN first_result f ON r.player = f.player
                JOIN player_counts pc ON r.player = pc.player
                GROUP BY r.player, f.on_win_streak, pc.total_games
            ),
            last_opposite AS (
                -- Find the most recent game that was the opposite of current streak
                SELECT DISTINCT ON (r.player)
                    r.player,
                    r.hand_id as last_opposite_hand_id,
                    r.game_time as last_opposite_date,
                    r.final_player_score as last_opposite_player_score,
                    r.final_computer_score as last_opposite_computer_score
                FROM recent_games r
                JOIN first_result f ON r.player = f.player
                WHERE r.won != f.on_win_streak
                ORDER BY r.player, r.game_time DESC
            )
            SELECT
                s.player,
                CASE WHEN s.on_win_streak THEN 'win' ELSE 'loss' END as streak_type,
                s.streak,
                lo.last_opposite_hand_id,
                lo.last_opposite_date,
                lo.last_opposite_player_score,
                lo.last_opposite_computer_score
            FROM streak_calc s
            LEFT JOIN last_opposite lo ON s.player = lo.player
            WHERE s.streak > 0
            ORDER BY s.streak DESC
        ''')
        streaks = [dict(row) for row in cur.fetchall()]

        # Overbid stats (bags per hand) - bags = overbidding penalty
        cur.execute('''
            SELECT
                player_name as player,
                SUM(player_bags) as total_bags,
                SUM(hands_played) as total_hands,
                ROUND(SUM(player_bags)::numeric / NULLIF(SUM(hands_played), 0), 2) as bags_per_hand,
                COUNT(*) as games
            FROM twomanspades.vw_player_game_details
            WHERE player_name IS NOT NULL AND player_name != 'Other'
            AND player_bags IS NOT NULL
            GROUP BY player_name
            ORDER BY bags_per_hand DESC
        ''')
        bag_stats = [dict(row) for row in cur.fetchall()]

        # Most common bid per player
        cur.execute('''
            WITH bid_counts AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    COUNT(*) as times
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                GROUP BY v.player_name, (ge.event_data->'action_data'->>'bid_amount')::int
            ),
            ranked AS (
                SELECT player, bid, times,
                    ROW_NUMBER() OVER (PARTITION BY player ORDER BY times DESC) as rn
                FROM bid_counts
            )
            SELECT player, bid as favorite_bid, times
            FROM ranked WHERE rn = 1
            ORDER BY times DESC
        ''')
        favorite_bids = [dict(row) for row in cur.fetchall()]

        # Worst losses - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT v.player_name as player, v.hand_id, v.final_player_score, v.final_computer_score,
                   v.final_computer_score - v.final_player_score as margin, v.player_bags,
                   COALESCE(v.completed_at, gc.timestamp) as completed_at
            FROM twomanspades.vw_player_game_details v
            LEFT JOIN twomanspades.game_events gc ON v.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
            WHERE v.won = false AND v.player_name != 'Other'
            AND v.final_player_score IS NOT NULL
            ORDER BY (v.final_computer_score - v.final_player_score) DESC LIMIT 5
        ''')
        worst_losses = [dict(row) for row in cur.fetchall()]

        # Biggest comebacks - games where player was furthest behind but won
        cur.execute('''
            WITH game_scores AS (
                SELECT
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'final_scores'->>'player_score')::int -
                    (ge.event_data->'final_scores'->>'computer_score')::int as deficit
                FROM twomanspades.game_events ge
                WHERE ge.event_type = 'hand_scoring'
            ),
            worst_deficits AS (
                SELECT hand_id, MIN(deficit) as worst_deficit
                FROM game_scores
                GROUP BY hand_id
                HAVING MIN(deficit) < -50
            )
            SELECT
                v.player_name as player,
                v.hand_id,
                COALESCE(v.completed_at, gc.timestamp) as completed_at,
                v.final_player_score,
                v.final_computer_score,
                ABS(wd.worst_deficit) as points_behind,
                v.player_bags,
                v.hands_played
            FROM worst_deficits wd
            JOIN twomanspades.vw_player_game_details v ON wd.hand_id = v.hand_id
            LEFT JOIN twomanspades.game_events gc ON v.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
            WHERE v.won = true AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ORDER BY ABS(wd.worst_deficit) DESC
            LIMIT 5
        ''')
        biggest_comebacks = [dict(row) for row in cur.fetchall()]

        # Blind bid stats - when offered blind (down 100+), did they take it and succeed?
        cur.execute('''
            WITH blind_decisions AS (
                SELECT
                    v.player_name as player,
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'action_data'->>'chose_blind')::boolean as chose_blind
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_blind_decision'
                AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            blind_bids AS (
                SELECT
                    v.player_name as player,
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'action_data'->>'bid_amount')::int as blind_bid
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_blind_bid'
                AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            hand_results AS (
                SELECT hand_id, hand_number,
                    SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as tricks_won
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                d.player,
                COUNT(*) as times_offered,
                SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END) as times_went_blind,
                SUM(CASE WHEN d.chose_blind AND COALESCE(hr.tricks_won, 0) >= bb.blind_bid THEN 1 ELSE 0 END) as blind_successes,
                ROUND(100.0 * SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as blind_rate,
                ROUND(100.0 * SUM(CASE WHEN d.chose_blind AND COALESCE(hr.tricks_won, 0) >= bb.blind_bid THEN 1 ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END), 0), 1) as blind_success_rate
            FROM blind_decisions d
            LEFT JOIN blind_bids bb ON d.hand_id = bb.hand_id AND d.hand_number = bb.hand_number AND d.player = bb.player
            LEFT JOIN hand_results hr ON d.hand_id = hr.hand_id AND d.hand_number = hr.hand_number
            GROUP BY d.player
            HAVING COUNT(*) >= 3
            ORDER BY times_offered DESC
        ''')
        blind_stats = [dict(row) for row in cur.fetchall()]

        # Blind bid breakdown by level (5-10) per player
        cur.execute('''
            WITH blind_bids AS (
                SELECT
                    v.player_name as player,
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'action_data'->>'bid_amount')::int as blind_bid
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_blind_bid'
                AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            hand_results AS (
                SELECT hand_id, hand_number,
                    SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as tricks_won
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                b.blind_bid as level,
                COUNT(*) as attempts,
                SUM(CASE WHEN COALESCE(hr.tricks_won, 0) >= b.blind_bid THEN 1 ELSE 0 END) as successes,
                ROUND(100.0 * SUM(CASE WHEN COALESCE(hr.tricks_won, 0) >= b.blind_bid THEN 1 ELSE 0 END) / COUNT(*), 0) as success_rate
            FROM blind_bids b
            LEFT JOIN hand_results hr ON b.hand_id = hr.hand_id AND b.hand_number = hr.hand_number
            GROUP BY b.player, b.blind_bid
            ORDER BY b.player, b.blind_bid
        ''')
        blind_by_level = [dict(row) for row in cur.fetchall()]

        cur.close()
        return_db_connection(conn)

        return {
            'bid_accuracy': bid_accuracy,
            'nil_stats': nil_stats,
            'closest_wins': closest_wins,
            'biggest_wins': biggest_wins,
            'streaks': streaks,  # Combined win and loss streaks
            'bag_stats': bag_stats,
            'favorite_bids': favorite_bids,
            'worst_losses': worst_losses,
            'biggest_comebacks': biggest_comebacks,
            'blind_stats': blind_stats,
            'blind_by_level': blind_by_level  # Blind bids broken down by level 5-10
        }

    except Exception as e:
        print(f"Failed to get player achievements: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_per_hand_stats() -> Dict[str, Any]:
    """Get fun per-hand statistics - things that happen within individual hands.
    Note: hand_id is actually a game_id, hand_number identifies hands within a game."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        stats = {}

        # Most overtricks in a single hand (biggest overbid) - using hand_number to identify individual hands
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    COALESCE(v.completed_at, gc.timestamp) as game_date,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id,
                    ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                LEFT JOIN twomanspades.game_events gc ON ge.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            tricks_data AS (
                SELECT hand_id, hand_number, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                b.hand_id,
                b.bid,
                b.game_date as completed_at,
                COALESCE(t.player_tricks, 0) as tricks_won,
                COALESCE(t.player_tricks, 0) - b.bid as overtricks
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id AND b.hand_number = t.hand_number
            WHERE b.bid > 0 AND COALESCE(t.player_tricks, 0) <= 10
            ORDER BY (COALESCE(t.player_tricks, 0) - b.bid) DESC
            LIMIT 5
        ''')
        stats['biggest_overtricks'] = [dict(row) for row in cur.fetchall()]

        # Most underbid (set by most) - bid high, won few
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    COALESCE(v.completed_at, gc.timestamp, ge.timestamp) as game_date,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id,
                    ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                LEFT JOIN twomanspades.game_events gc ON ge.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            tricks_data AS (
                SELECT hand_id, hand_number, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                b.hand_id,
                b.bid,
                b.game_date as completed_at,
                COALESCE(t.player_tricks, 0) as tricks_won,
                b.bid - COALESCE(t.player_tricks, 0) as undertricks
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id AND b.hand_number = t.hand_number
            WHERE b.bid > 0 AND COALESCE(t.player_tricks, 0) < b.bid
            ORDER BY (b.bid - COALESCE(t.player_tricks, 0)) DESC
            LIMIT 5
        ''')
        stats['biggest_sets'] = [dict(row) for row in cur.fetchall()]

        # Biggest single-hand point gains
        # Note: We must exclude hands where prev_score IS NULL (first hand of game or missing earlier hands)
        # to avoid showing cumulative scores as single-hand gains
        cur.execute('''
            WITH hand_scores AS (
                SELECT
                    ge.hand_id,
                    ge.hand_number,
                    ge.timestamp as event_timestamp,
                    (ge.event_data->'final_scores'->>'player_score')::int as cumulative_score,
                    LAG((ge.event_data->'final_scores'->>'player_score')::int)
                        OVER (PARTITION BY ge.hand_id ORDER BY ge.hand_number) as prev_score
                FROM twomanspades.game_events ge
                WHERE ge.event_type = 'hand_scoring'
            )
            SELECT
                v.player_name as player,
                hs.hand_id,
                hs.cumulative_score - hs.prev_score as points_scored,
                hs.hand_number,
                COALESCE(v.completed_at, gc.timestamp, hs.event_timestamp) as completed_at
            FROM hand_scores hs
            JOIN twomanspades.vw_player_identity v ON hs.hand_id = v.hand_id
            LEFT JOIN twomanspades.game_events gc ON hs.hand_id = gc.hand_id AND gc.event_type = 'game_completed'
            WHERE v.player_name IS NOT NULL AND v.player_name != 'Other'
            AND hs.prev_score IS NOT NULL
            AND (hs.cumulative_score - hs.prev_score) > 0
            ORDER BY (hs.cumulative_score - hs.prev_score) DESC
            LIMIT 5
        ''')
        stats['biggest_hand_points'] = [dict(row) for row in cur.fetchall()]

        # Average tricks per hand won (using hand_number to get per-hand averages)
        cur.execute('''
            WITH hand_tricks AS (
                SELECT
                    hand_id,
                    hand_number,
                    SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as player_tricks,
                    SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END) as computer_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                ROUND(AVG(player_tricks), 2) as avg_player_tricks,
                ROUND(AVG(computer_tricks), 2) as avg_computer_tricks
            FROM hand_tricks
            WHERE player_tricks + computer_tricks = 10
        ''')
        avg_tricks = cur.fetchone()
        stats['avg_player_tricks_per_hand'] = avg_tricks['avg_player_tricks']
        stats['avg_computer_tricks_per_hand'] = avg_tricks['avg_computer_tricks']

        # Average tricks per hand by player
        cur.execute('''
            WITH hand_tricks AS (
                SELECT
                    ge.hand_id,
                    ge.hand_number,
                    SUM(CASE WHEN ge.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as player_tricks
                FROM twomanspades.game_events ge
                WHERE ge.event_type = 'trick_completed'
                AND ge.hand_number IS NOT NULL
                GROUP BY ge.hand_id, ge.hand_number
            )
            SELECT
                v.player_name as player,
                COUNT(*) as total_hands,
                ROUND(AVG(ht.player_tricks), 2) as avg_tricks
            FROM hand_tricks ht
            JOIN twomanspades.vw_player_identity v ON ht.hand_id = v.hand_id
            WHERE v.player_name IS NOT NULL AND v.player_name != 'Other'
            GROUP BY v.player_name
            ORDER BY avg_tricks DESC
        ''')
        stats['player_tricks_per_hand'] = [dict(row) for row in cur.fetchall()]

        cur.close()
        return_db_connection(conn)
        return stats

    except Exception as e:
        print(f"Failed to get per-hand stats: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)
