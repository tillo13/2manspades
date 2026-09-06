"""Two-Man Spades records database operations."""
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

def get_game_details(hand_id: str) -> Optional[Dict[str, Any]]:
    """Get full game details for a specific hand_id including all events."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get game summary from vw_player_game_details
        cur.execute("""
            SELECT player_name, final_player_score, final_computer_score,
                   player_bags, won, margin, hands_played, completed_at,
                   game_end_reason, final_message
            FROM twomanspades.vw_player_game_details
            WHERE hand_id = %s
        """, (hand_id,))
        summary = cur.fetchone()

        if not summary:
            return None

        # Get all events for this game
        cur.execute("""
            SELECT event_type, hand_number, player, timestamp, event_data
            FROM twomanspades.game_events
            WHERE hand_id = %s
            ORDER BY timestamp
        """, (hand_id,))
        events = cur.fetchall()

        # Organize events by hand
        hands = {}
        game_completed = None

        for event in events:
            hand_num = event['hand_number'] or 0
            etype = event['event_type']
            data = event['event_data']

            if etype == 'game_completed':
                game_completed = {
                    'winner': data.get('winner'),
                    'final_message': data.get('final_message'),
                    'game_end_reason': data.get('game_end_reason'),
                    'hands_played': data.get('hands_played')
                }
                continue

            if hand_num not in hands:
                hands[hand_num] = {
                    'hand_number': hand_num,
                    'bids': [],
                    'tricks': [],
                    'scoring': None,
                    'trick_history': []
                }

            hand = hands[hand_num]

            if etype == 'action_regular_bid':
                # Use actual player name instead of "You"
                bid_player = summary['player_name'] if event['player'] == 'player' else 'Marta'
                bid_amount = data['action_data']['bid_amount']
                is_nil = data['action_data'].get('is_nil', False)
                hand['bids'].append({
                    'player': bid_player,
                    'amount': bid_amount,
                    'is_nil': is_nil,
                    'is_blind': False
                })

            elif etype == 'action_blind_bid':
                bid_player = summary['player_name'] if event['player'] == 'player' else 'Marta'
                bid_amount = data['action_data']['bid_amount']
                hand['bids'].append({
                    'player': bid_player,
                    'amount': bid_amount,
                    'is_nil': bid_amount == 0,
                    'is_blind': True
                })

            elif etype == 'trick_completed':
                winner = summary['player_name'] if data['winner'] == 'player' else 'Marta'
                hand['tricks'].append({
                    'number': data['trick_number'],
                    'winner': winner
                })

            elif etype == 'hand_scoring':
                scores = data.get('final_scores', {})
                hand['scoring'] = {
                    'player_score': scores.get('player_score'),
                    'computer_score': scores.get('computer_score'),
                    'explanation': data.get('scoring_explanation', '')
                }
                # Extract trick history if available, convert "You" to player name
                hand_results = data.get('hand_results', {})
                if 'trick_history' in hand_results:
                    trick_history = []
                    for trick in hand_results['trick_history']:
                        t = dict(trick)
                        if t.get('winner') == 'You':
                            t['winner'] = summary['player_name']
                        trick_history.append(t)
                    hand['trick_history'] = trick_history

        # Timing data — computed from `events` (already the full set, sorted by
        # timestamp). The old MIN/MAX aggregate queries hit a planner pathology
        # (backward timestamp-index walk, 30s statement timeouts on bot traffic).
        if events:
            game_start = events[0]['timestamp']
            game_end = events[-1]['timestamp']
            total_minutes = (game_end - game_start).total_seconds() / 60
            summary['game_start'] = game_start
            summary['game_end'] = game_end
            summary['total_minutes'] = round(total_minutes, 1) if total_minutes else None

        # Per-hand timing from the same in-memory list (events sorted ascending,
        # so first/last occurrence per hand = min/max timestamp)
        hand_spans = {}
        for event in events:
            hn = event['hand_number']
            if not hn or hn <= 0:
                continue
            if hn not in hand_spans:
                hand_spans[hn] = [event['timestamp'], event['timestamp']]
            else:
                hand_spans[hn][1] = event['timestamp']

        hand_timings = {}
        prev_hand_end = None
        for hn in sorted(hand_spans):
            hand_start, hand_end = hand_spans[hn]
            # Calculate duration relative to previous hand end (not absolute timestamps)
            if prev_hand_end and hand_end:
                duration = round((hand_end - prev_hand_end).total_seconds() / 60, 1)
            else:
                # First hand: use its own start to end
                hand_minutes = (hand_end - hand_start).total_seconds() / 60
                duration = round(hand_minutes, 1) if hand_minutes else None

            gap_minutes = None
            if prev_hand_end and hand_start:
                gap_minutes = round((hand_start - prev_hand_end).total_seconds() / 60, 1)

            hand_timings[hn] = {
                'start': hand_start,
                'end': hand_end,
                'duration_minutes': duration,
                'gap_from_previous': gap_minutes
            }
            prev_hand_end = hand_end

        # Add timing to hands
        for h in hands.values():
            if h['hand_number'] in hand_timings:
                h['timing'] = hand_timings[h['hand_number']]

        # Convert to sorted list
        hands_list = sorted(hands.values(), key=lambda h: h['hand_number'])

        return {
            'hand_id': hand_id,
            'summary': dict(summary),
            'hands': hands_list,
            'game_completed': game_completed
        }

    except Exception as e:
        print(f"Failed to get game details: {e}")
        return None
    finally:
        # Release on EVERY path — a statement-timeout here used to leak the
        # pooled conn idle-in-transaction (55min lock-holder, 7/17 DB alert).
        if conn is not None:
            return_db_connection(conn)


def get_player_games(player_name: str) -> Optional[Dict[str, Any]]:
    """Get all games for a specific player, sorted by date descending.
    Includes both completed and abandoned games."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get player stats summary (completed games only)
        cur.execute('''
            SELECT
                COUNT(*) as total_games,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN NOT won THEN 1 ELSE 0 END) as losses,
                ROUND(100.0 * SUM(CASE WHEN won THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as win_rate,
                MAX(final_player_score) as highest_score,
                MIN(final_player_score) as lowest_score,
                ROUND(AVG(final_player_score)::numeric, 0) as avg_score
            FROM twomanspades.vw_player_game_details
            WHERE player_name = %s
        ''', (player_name,))
        summary = dict(cur.fetchone())

        # Get all games (completed + abandoned) using UNION
        cur.execute('''
            WITH completed_games AS (
                SELECT
                    v.hand_id,
                    v.won,
                    v.final_player_score,
                    v.final_computer_score,
                    v.margin,
                    v.player_bags,
                    v.hands_played,
                    ge.timestamp as game_time,
                    v.game_end_reason,
                    false as is_abandoned
                FROM twomanspades.vw_player_game_details v
                JOIN twomanspades.game_events ge ON v.hand_id = ge.hand_id
                    AND ge.event_type = 'game_completed'
                WHERE v.player_name = %s
            ),
            abandoned_games AS (
                SELECT
                    h.hand_id,
                    NULL::boolean as won,
                    h.hand_player_score as final_player_score,
                    h.hand_computer_score as final_computer_score,
                    NULL::int as margin,
                    h.player_bags,
                    (SELECT COUNT(*) FROM twomanspades.game_events
                     WHERE hand_id = h.hand_id AND event_type = 'hand_completed') as hands_played,
                    h.started_at as game_time,
                    'abandoned' as game_end_reason,
                    true as is_abandoned
                FROM twomanspades.hands h
                JOIN twomanspades.vw_player_identity v ON h.hand_id = v.hand_id
                WHERE v.player_name = %s
                AND h.completed_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM twomanspades.game_events ge
                    WHERE ge.hand_id = h.hand_id AND ge.event_type = 'game_completed'
                )
                AND (
                    -- Must have actual progress to count as abandoned:
                    -- Either a non-zero score OR a completed hand event
                    (h.hand_player_score IS NOT NULL AND h.hand_player_score != 0)
                    OR (h.hand_computer_score IS NOT NULL AND h.hand_computer_score != 0)
                    OR EXISTS (
                        SELECT 1 FROM twomanspades.game_events ge
                        WHERE ge.hand_id = h.hand_id AND ge.event_type = 'hand_completed'
                    )
                )
            )
            SELECT * FROM completed_games
            UNION ALL
            SELECT * FROM abandoned_games
            ORDER BY game_time DESC
        ''', (player_name, player_name))
        games = [dict(row) for row in cur.fetchall()]

        # Add abandoned count to summary
        abandoned_count = sum(1 for g in games if g.get('is_abandoned'))
        summary['abandoned'] = abandoned_count

        return {
            'player_name': player_name,
            'summary': summary,
            'games': games
        }

    except Exception as e:
        print(f"Failed to get player games: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_player_record(google_email=None, player_name=None):
    """A person's whole history for the end-of-game screen: totals, win rate, current and best
    streaks, margins, per-rung record. Identity resolves the same way the ratchet does."""
    if not google_email and not player_name:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT v.won, v.margin, v.hands_played, h.difficulty, v.completed_at
              FROM twomanspades.vw_player_game_details v
              JOIN twomanspades.hands h ON h.hand_id = v.hand_id
             WHERE v.player_name = COALESCE(%s, (SELECT split_part(google_name, ' ', 1) FROM twomanspades.players
                                                 WHERE google_email = %s AND google_name IS NOT NULL LIMIT 1))
             ORDER BY v.completed_at
        """, (player_name, google_email))
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        print(f"[DB] Error getting player record: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)
    if not rows:
        return None
    wins = sum(1 for r in rows if r[0])
    margins = [r[1] or 0 for r in rows]
    best_win, cur_streak, cur_type = 0, 0, None
    for won, *_ in rows:
        if cur_type is None or won == cur_type:
            cur_streak += 1
        else:
            cur_streak = 1
        cur_type = won
        if won:
            best_win = max(best_win, cur_streak)
    rungs = {}
    for won, _m, _h, level, _t in rows:
        r = rungs.setdefault(level or 'easy', {'wins': 0, 'losses': 0})
        r['wins' if won else 'losses'] += 1
    return {
        'games': len(rows), 'wins': wins, 'losses': len(rows) - wins,
        'win_pct': round(100 * wins / len(rows)),
        'streak': cur_streak, 'streak_type': 'win' if cur_type else 'loss', 'best_win_streak': best_win,
        'avg_margin': round(sum(margins) / len(margins)),
        'biggest_win': max(margins), 'worst_loss': min(margins),
        'avg_hands': round(sum(r[2] or 0 for r in rows) / len(rows), 1),
        'rungs': rungs,
        'since': rows[0][4].strftime('%b %Y') if rows[0][4] else None,
    }
