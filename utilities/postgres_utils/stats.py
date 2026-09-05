"""Two-Man Spades stats database operations."""
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

def get_fun_stats() -> Dict[str, Any]:
    """Get fun/interesting stats for display.
    Uses game_completed events as source of truth for finished games."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        stats = {}

        # Total hands played (all completed hands, not just games)
        cur.execute('SELECT COUNT(DISTINCT hand_id) FROM twomanspades.hands WHERE completed_at IS NOT NULL')
        stats['total_hands'] = cur.fetchone()[0]

        # Total completed GAMES - from game_completed events (authoritative source)
        cur.execute("SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = 'game_completed'")
        stats['total_games'] = cur.fetchone()[0]

        cur.execute('SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = %s', ('trick_completed',))
        stats['total_tricks'] = cur.fetchone()[0]

        # Win/loss from game_completed events (authoritative source)
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END),
                SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END)
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
        ''')
        row = cur.fetchone()
        stats['human_wins'] = row[0] or 0
        stats['marta_wins'] = row[1] or 0
        total = stats['human_wins'] + stats['marta_wins']
        stats['human_win_pct'] = round(100 * stats['human_wins'] / total, 1) if total > 0 else 0

        # Bid distribution
        cur.execute('''
            SELECT
                (event_data->'action_data'->>'bid_amount')::int as bid,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'action_regular_bid' AND player = 'player'
            GROUP BY (event_data->'action_data'->>'bid_amount')::int
            ORDER BY 1
        ''')
        stats['bid_distribution'] = [{'bid': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Average game length - from game_completed events
        cur.execute('''
            SELECT
                ROUND(AVG((event_data->>'hands_played')::int), 1),
                MIN((event_data->>'hands_played')::int),
                MAX((event_data->>'hands_played')::int)
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
            AND event_data->>'hands_played' IS NOT NULL
        ''')
        row = cur.fetchone()
        stats['avg_game_length'] = row[0]
        stats['shortest_game'] = row[1]
        stats['longest_game'] = row[2]

        # Get hand_ids for shortest and longest games by hands played
        cur.execute('''
            SELECT hand_id, timestamp, (event_data->>'hands_played')::int as hands
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
            AND event_data->>'hands_played' IS NOT NULL
            ORDER BY (event_data->>'hands_played')::int ASC, timestamp DESC
            LIMIT 1
        ''')
        shortest = cur.fetchone()
        if shortest:
            stats['shortest_game_hand_id'] = shortest[0]
            stats['shortest_game_date'] = shortest[1]

        cur.execute('''
            SELECT hand_id, timestamp, (event_data->>'hands_played')::int as hands
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
            AND event_data->>'hands_played' IS NOT NULL
            ORDER BY (event_data->>'hands_played')::int DESC, timestamp DESC
            LIMIT 1
        ''')
        longest = cur.fetchone()
        if longest:
            stats['longest_game_hand_id'] = longest[0]
            stats['longest_game_date'] = longest[1]

        # Average game duration in minutes (time from first to last event)
        cur.execute('''
            WITH game_times AS (
                SELECT
                    gt.hand_id,
                    MIN(gt.timestamp) as start_time,
                    MAX(gt.timestamp) as end_time
                FROM twomanspades.game_events gt
                WHERE gt.hand_id IN (
                    SELECT hand_id FROM twomanspades.game_events
                    WHERE event_type = 'game_completed'
                )
                GROUP BY gt.hand_id
            )
            SELECT
                ROUND(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60)::numeric, 1) as avg_minutes,
                ROUND(MIN(EXTRACT(EPOCH FROM (end_time - start_time)) / 60)::numeric, 1) as min_minutes,
                ROUND(MAX(EXTRACT(EPOCH FROM (end_time - start_time)) / 60)::numeric, 1) as max_minutes
            FROM game_times
            WHERE end_time > start_time
        ''')
        duration = cur.fetchone()
        if duration:
            stats['avg_game_duration_minutes'] = duration[0]
            stats['min_game_duration_minutes'] = duration[1]
            stats['max_game_duration_minutes'] = duration[2]

        # Get hand_ids for fastest and slowest games
        cur.execute('''
            WITH game_times AS (
                SELECT
                    gt.hand_id,
                    MIN(gt.timestamp) as start_time,
                    MAX(gt.timestamp) as end_time,
                    EXTRACT(EPOCH FROM (MAX(gt.timestamp) - MIN(gt.timestamp))) / 60 as duration_minutes
                FROM twomanspades.game_events gt
                WHERE gt.hand_id IN (
                    SELECT hand_id FROM twomanspades.game_events
                    WHERE event_type = 'game_completed'
                )
                GROUP BY gt.hand_id
                HAVING MAX(gt.timestamp) > MIN(gt.timestamp)
            )
            SELECT hand_id, start_time, duration_minutes
            FROM game_times
            ORDER BY duration_minutes ASC
            LIMIT 1
        ''')
        fastest = cur.fetchone()
        if fastest:
            stats['fastest_game_hand_id'] = fastest[0]
            stats['fastest_game_date'] = fastest[1]

        cur.execute('''
            WITH game_times AS (
                SELECT
                    gt.hand_id,
                    MIN(gt.timestamp) as start_time,
                    MAX(gt.timestamp) as end_time,
                    EXTRACT(EPOCH FROM (MAX(gt.timestamp) - MIN(gt.timestamp))) / 60 as duration_minutes
                FROM twomanspades.game_events gt
                WHERE gt.hand_id IN (
                    SELECT hand_id FROM twomanspades.game_events
                    WHERE event_type = 'game_completed'
                )
                GROUP BY gt.hand_id
                HAVING MAX(gt.timestamp) > MIN(gt.timestamp)
            )
            SELECT hand_id, start_time, duration_minutes
            FROM game_times
            ORDER BY duration_minutes DESC
            LIMIT 1
        ''')
        slowest = cur.fetchone()
        if slowest:
            stats['slowest_game_hand_id'] = slowest[0]
            stats['slowest_game_date'] = slowest[1]

        # Average hand duration in minutes (time between hand_scoring events)
        cur.execute('''
            WITH hand_times AS (
                SELECT
                    hand_id,
                    hand_number,
                    timestamp as end_time,
                    LAG(timestamp) OVER (PARTITION BY hand_id ORDER BY hand_number) as prev_time
                FROM twomanspades.game_events
                WHERE event_type = 'hand_scoring'
                AND hand_id IN (
                    SELECT hand_id FROM twomanspades.game_events
                    WHERE event_type = 'game_completed'
                )
            )
            SELECT
                ROUND(AVG(EXTRACT(EPOCH FROM (end_time - prev_time)) / 60)::numeric, 2) as avg_hand_minutes,
                ROUND(MIN(EXTRACT(EPOCH FROM (end_time - prev_time)) / 60)::numeric, 2) as min_hand_minutes,
                ROUND(MAX(EXTRACT(EPOCH FROM (end_time - prev_time)) / 60)::numeric, 2) as max_hand_minutes
            FROM hand_times
            WHERE prev_time IS NOT NULL AND end_time > prev_time
        ''')
        hand_duration = cur.fetchone()
        if hand_duration:
            stats['avg_hand_duration_minutes'] = hand_duration[0]
            stats['min_hand_duration_minutes'] = hand_duration[1]
            stats['max_hand_duration_minutes'] = hand_duration[2]

        cur.close()
        return_db_connection(conn)
        return stats

    except Exception as e:
        print(f"Failed to get fun stats: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_overall_game_stats() -> Dict[str, Any]:
    """Get fun overall game statistics across all players - big numbers and interesting data."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        stats = {}

        # Total points scored ever (all completed hands)
        cur.execute('''
            SELECT
                SUM(hand_player_score) as total_player_points,
                SUM(hand_computer_score) as total_computer_points,
                SUM(hand_player_score) + SUM(hand_computer_score) as grand_total_points
            FROM twomanspades.hands
            WHERE completed_at IS NOT NULL
            AND hand_player_score IS NOT NULL
        ''')
        points = dict(cur.fetchone())
        stats['total_player_points'] = points['total_player_points'] or 0
        stats['total_computer_points'] = points['total_computer_points'] or 0
        stats['grand_total_points'] = points['grand_total_points'] or 0

        # Total bags accumulated
        cur.execute('''
            SELECT
                SUM(player_bags) as total_player_bags,
                SUM(computer_bags) as total_computer_bags
            FROM twomanspades.hands
            WHERE completed_at IS NOT NULL
        ''')
        bags = dict(cur.fetchone())
        stats['total_player_bags'] = bags['total_player_bags'] or 0
        stats['total_computer_bags'] = bags['total_computer_bags'] or 0

        # Total cards played (13 cards per hand, 2 players)
        cur.execute('SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = %s', ('trick_completed',))
        tricks = cur.fetchone()['count']
        stats['total_cards_played'] = tricks * 2  # 2 cards per trick

        # Nil attempts and success rate overall - must join by hand_number
        cur.execute('''
            WITH nil_bids AS (
                SELECT ge.hand_id, ge.hand_number
                FROM twomanspades.game_events ge
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND (ge.event_data->'action_data'->>'bid_amount') = '0'
                AND ge.hand_number IS NOT NULL
            ),
            nil_results AS (
                SELECT n.hand_id, n.hand_number, COALESCE(COUNT(t.*), 0) as tricks_taken
                FROM nil_bids n
                LEFT JOIN twomanspades.game_events t ON n.hand_id = t.hand_id
                    AND n.hand_number = t.hand_number
                    AND t.event_type = 'trick_completed' AND t.event_data->>'winner' = 'player'
                GROUP BY n.hand_id, n.hand_number
            )
            SELECT
                COUNT(*) as total_nil_attempts,
                SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) as successful_nils,
                ROUND(100.0 * SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as nil_success_rate
            FROM nil_results
        ''')
        nil = dict(cur.fetchone())
        stats['total_nil_attempts'] = nil['total_nil_attempts'] or 0
        stats['successful_nils'] = nil['successful_nils'] or 0
        stats['nil_success_rate'] = nil['nil_success_rate'] or 0

        # Highest single game score ever (with bags)
        cur.execute('''
            SELECT final_player_score, player_bags, player_name
            FROM twomanspades.vw_player_game_details
            WHERE final_player_score IS NOT NULL
            ORDER BY final_player_score DESC
            LIMIT 1
        ''')
        highest_player = cur.fetchone()
        if highest_player:
            stats['highest_player_score_ever'] = highest_player['final_player_score']
            stats['highest_player_score_bags'] = highest_player['player_bags']
            stats['highest_player_score_player'] = highest_player['player_name']

        cur.execute('''
            SELECT final_computer_score
            FROM twomanspades.vw_player_game_details
            WHERE final_computer_score IS NOT NULL
            ORDER BY final_computer_score DESC
            LIMIT 1
        ''')
        highest_computer = cur.fetchone()
        if highest_computer:
            stats['highest_computer_score_ever'] = highest_computer['final_computer_score']

        # Lowest winning score (closest game) with bags
        cur.execute('''
            SELECT
                v.final_player_score,
                v.final_computer_score,
                v.player_name,
                v.player_bags
            FROM twomanspades.vw_player_game_details v
            WHERE v.won = true
            ORDER BY v.final_player_score ASC
            LIMIT 1
        ''')
        lowest_win = cur.fetchone()
        if lowest_win:
            stats['lowest_winning_score'] = lowest_win['final_player_score']
            stats['lowest_win_opponent_score'] = lowest_win['final_computer_score']
            stats['lowest_win_bags'] = lowest_win['player_bags']

        # Biggest comeback (largest negative to positive swing)
        cur.execute('''
            WITH game_scores AS (
                SELECT
                    hand_id,
                    event_data->>'player_score' as player_score,
                    event_data->>'computer_score' as computer_score,
                    hand_number
                FROM twomanspades.game_events
                WHERE event_type = 'hand_complete'
            )
            SELECT
                hand_id,
                MIN((player_score)::int - (computer_score)::int) as worst_deficit
            FROM game_scores
            GROUP BY hand_id
            HAVING MIN((player_score)::int - (computer_score)::int) < -100
            ORDER BY worst_deficit ASC
            LIMIT 1
        ''')
        comeback = cur.fetchone()
        if comeback:
            # Check if this game was won
            cur.execute('''
                SELECT event_data->>'winner' as winner
                FROM twomanspades.game_events
                WHERE hand_id = %s AND event_type = 'game_completed'
            ''', (comeback['hand_id'],))
            result = cur.fetchone()
            if result and result['winner'] == 'player':
                stats['biggest_comeback_deficit'] = abs(comeback['worst_deficit'])

        # Spades broken stats - average hand number when spades break
        cur.execute('''
            SELECT
                ROUND(AVG(hand_number), 1) as avg_hand_spades_broken,
                MIN(hand_number) as earliest_spades_broken,
                MAX(hand_number) as latest_spades_broken
            FROM twomanspades.game_events
            WHERE event_type = 'spades_broken' AND hand_number IS NOT NULL
        ''')
        spades_broken = cur.fetchone()
        stats['avg_hand_spades_broken'] = spades_broken['avg_hand_spades_broken']
        stats['earliest_spades_broken'] = spades_broken['earliest_spades_broken']
        stats['latest_spades_broken'] = spades_broken['latest_spades_broken']

        # Average tricks per hand won by players vs Marta
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as player_tricks,
                SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END) as computer_tricks
            FROM twomanspades.game_events
            WHERE event_type = 'trick_completed'
        ''')
        trick_wins = dict(cur.fetchone())
        stats['total_player_tricks'] = trick_wins['player_tricks'] or 0
        stats['total_computer_tricks'] = trick_wins['computer_tricks'] or 0

        # Most popular bid overall
        cur.execute('''
            SELECT
                (event_data->'action_data'->>'bid_amount')::int as bid,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'action_regular_bid' AND player = 'player'
            GROUP BY (event_data->'action_data'->>'bid_amount')::int
            ORDER BY times DESC
            LIMIT 1
        ''')
        popular = cur.fetchone()
        if popular:
            stats['most_popular_bid'] = popular['bid']
            stats['most_popular_bid_times'] = popular['times']

        # Blind nil stats
        cur.execute('''
            SELECT
                COUNT(*) as blind_nil_attempts,
                SUM(CASE WHEN event_data->>'result' = 'success' THEN 1 ELSE 0 END) as blind_nil_successes
            FROM twomanspades.game_events
            WHERE event_type = 'blind_nil_result'
        ''')
        blind = cur.fetchone()
        if blind and blind['blind_nil_attempts']:
            stats['blind_nil_attempts'] = blind['blind_nil_attempts']
            stats['blind_nil_successes'] = blind['blind_nil_successes'] or 0

        # First game ever date
        cur.execute('''
            SELECT MIN(started_at) as first_game
            FROM twomanspades.hands
        ''')
        first = cur.fetchone()
        if first and first['first_game']:
            stats['first_game_date'] = first['first_game'].strftime('%B %d, %Y')

        cur.close()
        return_db_connection(conn)
        return stats

    except Exception as e:
        print(f"Failed to get overall game stats: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_special_card_stats() -> Dict[str, Any]:
    """Get stats about the special cards (10 of clubs, 7 of diamonds).
    Uses vw_player_identity for consistent player mapping."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Overall special card captures
        cur.execute('''
            SELECT
                CASE WHEN event_data->>'beneficiary' = 'You' THEN 'Players' ELSE 'Marta' END as winner,
                CASE
                    WHEN event_data->>'explanation' LIKE '%10%' THEN '10 of Clubs'
                    WHEN event_data->>'explanation' LIKE '%7%' THEN '7 of Diamonds'
                END as card,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
            GROUP BY 1, 2
            ORDER BY card, winner
        ''')
        overall_captures = [dict(row) for row in cur.fetchall()]

        # Special card captures by player - uses vw_player_identity for unified mapping
        # Includes per-game rate for fair comparison across players
        cur.execute('''
            WITH player_games AS (
                SELECT player_name, COUNT(*) as games_played
                FROM twomanspades.vw_player_game_details
                WHERE player_name IS NOT NULL AND player_name != 'Other'
                GROUP BY player_name
            ),
            captures AS (
                SELECT
                    COALESCE(v.player_name, 'Other') as player,
                    SUM(CASE WHEN ge.event_data->>'explanation' LIKE '%10%' THEN 1 ELSE 0 END) as ten_clubs,
                    SUM(CASE WHEN ge.event_data->>'explanation' LIKE '%7%' THEN 1 ELSE 0 END) as seven_diamonds,
                    COUNT(*) as total_special,
                    SUM((ge.event_data->>'bag_reduction')::int) as total_bags_saved
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'special_card_effect'
                AND ge.event_data->>'beneficiary' = 'You'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                GROUP BY COALESCE(v.player_name, 'Other')
            )
            SELECT
                c.player,
                c.ten_clubs,
                c.seven_diamonds,
                c.total_special,
                c.total_bags_saved,
                pg.games_played,
                ROUND(c.total_bags_saved::numeric / NULLIF(pg.games_played, 0), 2) as bags_saved_per_game
            FROM captures c
            JOIN player_games pg ON c.player = pg.player_name
            ORDER BY bags_saved_per_game DESC
        ''')
        player_captures = [dict(row) for row in cur.fetchall()]

        # Win rate when capturing special cards - uses game_completed events
        cur.execute('''
            WITH special_games AS (
                SELECT DISTINCT ge.hand_id, v.player_name
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'special_card_effect'
                AND ge.event_data->>'beneficiary' = 'You'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            )
            SELECT
                sg.player_name as player,
                COUNT(*) as games_with_special,
                SUM(CASE WHEN gc.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as wins,
                ROUND(100.0 * SUM(CASE WHEN gc.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
            FROM special_games sg
            JOIN twomanspades.game_events gc ON sg.hand_id = gc.hand_id
            WHERE gc.event_type = 'game_completed'
            GROUP BY sg.player_name
            ORDER BY games_with_special DESC
        ''')
        win_rate_with_special = [dict(row) for row in cur.fetchall()]

        # Marta's special card captures (for comparison)
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'explanation' LIKE '%10%' THEN 1 ELSE 0 END) as ten_clubs,
                SUM(CASE WHEN event_data->>'explanation' LIKE '%7%' THEN 1 ELSE 0 END) as seven_diamonds,
                COUNT(*) as total
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
            AND event_data->>'beneficiary' = 'Marta'
        ''')
        marta_captures = dict(cur.fetchone())

        # Total special card appearances
        cur.execute('''
            SELECT COUNT(*) as total_appearances
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
        ''')
        total = cur.fetchone()['total_appearances']

        cur.close()
        return_db_connection(conn)

        return {
            'overall_captures': overall_captures,
            'player_captures': player_captures,
            'win_rate_with_special': win_rate_with_special,
            'marta_captures': marta_captures,
            'total_appearances': total
        }

    except Exception as e:
        print(f"Failed to get special card stats: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)
