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
            FROM twomanspades.vw_player_games
            WHERE hand_id = %s
        """, (hand_id,))
        summary = cur.fetchone()

        if not summary:
            return None

        # Every hand of the game: each hand has its own hand_id, and the hands of one game share
        # the player and the game's start time (the page used to read only the last hand's
        # events and then call the game "older, incomplete logging", 2026-09-06). Identical
        # rows are collapsed: events were being written twice.
        cur.execute("""
            SELECT DISTINCT ON (e.hand_number, e.event_type, e.event_data::text)
                   e.event_type, e.hand_number, e.player, e.timestamp, e.event_data,
                   h.first_leader AS hand_first_leader, h.difficulty
              FROM twomanspades.game_events e
              JOIN twomanspades.hands h ON h.hand_id = e.hand_id
              JOIN twomanspades.hands me ON me.hand_id = %s
             WHERE h.player_id = me.player_id AND h.started_at = me.started_at
             ORDER BY e.hand_number, e.event_type, e.event_data::text, e.timestamp
        """, (hand_id,))
        events = sorted(cur.fetchall(), key=lambda e: e['timestamp'])

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
                    'first_leader': event.get('hand_first_leader'),
                    'difficulty': event.get('difficulty'),
                    'middle': None,
                    'specials': [],
                    'auto_resolution': None,
                    'bids': [],
                    'tricks': [],
                    'scoring': None,
                    'trick_history': []
                }

            hand = hands[hand_num]

            if etype == 'discard_scoring':
                hand['middle'] = data
            elif etype == 'special_card_effect':
                hand['specials'].append(data)
            elif etype == 'hand_auto_resolved':
                hand['auto_resolution'] = data.get('explanation')
                hand['auto_tricks'] = data.get('tricks_simulated')
            elif etype == 'bidding_complete':
                hand['final_bids'] = data
            elif etype == 'action_regular_bid':
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
                hand['middle_explanation'] = hand_results.get('discard_info')
                hand['auto_resolution'] = hand_results.get('auto_resolution') or hand['auto_resolution']
                if 'trick_history' in hand_results:
                    trick_history = []
                    for trick in hand_results['trick_history']:
                        t = dict(trick)
                        if t.get('winner') == 'You':
                            t['winner'] = summary['player_name']
                        if t.get('leader') == 'You':
                            t['leader'] = summary['player_name']
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
            leader = {'player': summary['player_name'], 'computer': 'Marta'}.get(h['first_leader'])
            previous_number = 0
            for trick in sorted(h['trick_history'], key=lambda t: t['number']):
                if not trick.get('leader'):
                    trick['leader'] = leader if trick['number'] == previous_number + 1 else None
                leader = trick['winner']
                previous_number = trick['number']
            if h['hand_number'] in hand_timings:
                h['timing'] = hand_timings[h['hand_number']]

        # Convert to sorted list
        hands_list = sorted(hands.values(), key=lambda h: h['hand_number'])
        from .game_summary import summarize_game
        summary.update(summarize_game(hands_list, summary))

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


def get_player_games(player_name: str, only: str = None) -> Optional[Dict[str, Any]]:
    """Get all games for a specific player, sorted by date descending.
    Includes both completed and abandoned games.

    only='streak' trims the list to the current run of wins or losses, so a stat on the stats
    page can hand over the games behind it instead of asking to be believed (Andy, 2026-09-08)."""
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
            FROM twomanspades.vw_player_games
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
                    h.first_leader,
                    false as is_abandoned
                FROM twomanspades.vw_player_games v
                JOIN twomanspades.vw_game_completion ge ON v.hand_id = ge.hand_id
                JOIN twomanspades.hands h ON h.hand_id = v.hand_id
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
                    (SELECT COUNT(*) FROM twomanspades.vw_hand_completed
                     WHERE hand_id = h.hand_id) as hands_played,
                    h.started_at as game_time,
                    'abandoned' as game_end_reason,
                    h.first_leader,
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
                        SELECT 1 FROM twomanspades.vw_hand_completed ge
                        WHERE ge.hand_id = h.hand_id
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

        shown = None
        if only:
            games, shown = filter_games(games, only)

        return {
            'player_name': player_name,
            'summary': summary,
            'games': games,
            'shown': shown,
        }

    except Exception as e:
        print(f"Failed to get player games: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)


# Every stat on the stats page links here with one of these, so a number can always be checked
# against the games behind it (Andy, 2026-09-08: "make all them click through to prove they're
# right always"). Each is (label, predicate) over the rows get_player_games already fetched.
_PART = {'latenight': ('late at night', range(0, 6)), 'morning': ('in the morning', range(6, 12)),
         'afternoon': ('in the afternoon', range(12, 18)), 'evening': ('in the evening', range(18, 24))}

FILTERS = {
    'wins':      ('every win', lambda g: g['won'] is True),
    'losses':    ('every loss', lambda g: g['won'] is False),
    'close':     ('every game decided by 50 or less', lambda g: g['won'] is not None and abs(g['margin'] or 0) <= 50),
    'blowout':   ('every game decided by 200 or more', lambda g: g['won'] is not None and abs(g['margin'] or 0) >= 200),
    'bags':      ('every game finished carrying 5 or more bags', lambda g: (g.get('player_bags') or 0) >= 5),
    'long':      ('every game that went 15 hands or more', lambda g: (g.get('hands_played') or 0) >= 15),
    'abandoned': ('every game walked away from', lambda g: bool(g.get('is_abandoned'))),
    'led':       ('every game they led first', lambda g: g.get('first_leader') == 'player'),
    'martaled':  ('every game Marta led first', lambda g: g.get('first_leader') not in (None, 'player')),
}


def filter_games(games, only):
    """(games, a line saying what is on screen) for one of FILTERS, a run, or a part of the day.
    An unknown filter shows everything rather than an empty page."""
    if only in ('streak', 'best', 'worst'):
        return _run_of_games(games, only)
    if only in _PART:
        label, hours = _PART[only]
        keep = [g for g in games if g['game_time'] and g['game_time'].hour in hours]
        return keep, f"every game played {label} ({_record(keep)})"
    if only in FILTERS:
        label, keep_it = FILTERS[only]
        keep = [g for g in games if keep_it(g)]
        return keep, f"{label} ({_record(keep)})"
    return games, None


def _record(games):
    n = f"{len(games)} game" + ('' if len(games) == 1 else 's')
    played = [g for g in games if g.get('won') is not None]
    if not played:
        return n
    w = sum(1 for g in played if g['won'])
    return f"{n}, {w}-{len(played) - w}"


def _run_of_games(games, which):
    """The games behind a streak stat, newest first, plus a line saying what is on screen.
    'streak' is the run still going, 'best' the longest winning run ever, 'worst' the longest
    losing one. Abandoned games have no result, so they are skipped rather than counted."""
    played = [g for g in games if g.get('won') is not None]
    if not played:
        return games, None
    runs, cur = [], []
    for g in played:                                  # newest first, so each run is newest first too
        if cur and g['won'] != cur[-1]['won']:
            runs.append(cur); cur = []
        cur.append(g)
    if cur:
        runs.append(cur)
    if which in ('best', 'worst'):
        want = which == 'best'
        side = [r for r in runs if r[0]['won'] is want]
        if not side:
            return [], f"no {'wins' if want else 'losses'} on record yet"
        run = max(side, key=len)
        when = run[0]['game_time'].strftime('%B %-d, %Y')
        word = 'wins' if want else 'losses'
        return run, f"the {'best' if want else 'longest losing'} run on record: {len(run)} {word} in a row, ending {when}"
    run = runs[0]
    kind = run[0]['won']
    word = ('win' if kind else 'loss') + ('' if len(run) == 1 else ('s' if kind else 'es'))
    after = played[len(run):]
    tail = (f", back to the last {'loss' if kind else 'win'} on "
            f"{after[0]['game_time'].strftime('%B %-d, %Y')}") if after else ", every game on record"
    return run, f"{len(run)} {word} in a row{tail}"


def get_player_bid_bias(google_email=None, player_name=None):
    """How this person bids against what they take: AVG(tricks taken - bid) over their hands,
    for Marta's thinking (she deals them hands they would have bid the way they did). None for
    strangers or under 10 hands."""
    if not google_email and not player_name:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            WITH mine AS (
                SELECT hand_id FROM twomanspades.vw_player_identity
                 WHERE player_name = COALESCE(%s, (SELECT split_part(google_name, ' ', 1) FROM twomanspades.players
                                                   WHERE google_email = %s AND google_name IS NOT NULL LIMIT 1))),
            bids AS (
                SELECT ge.hand_id, ge.hand_number, (ge.event_data->'action_data'->>'bid_amount')::int AS bid
                  FROM twomanspades.game_events ge JOIN mine USING (hand_id)
                 WHERE ge.player = 'player' AND ge.event_type IN ('action_regular_bid', 'action_blind_bid')),
            taken AS (
                SELECT hand_id, hand_number, COUNT(*) FILTER (WHERE event_data->>'winner' = 'player') AS taken
                  FROM twomanspades.game_events WHERE event_type = 'trick_completed' GROUP BY 1, 2)
            SELECT AVG(t.taken - b.bid), COUNT(*) FROM bids b JOIN taken t USING (hand_id, hand_number)
        """, (player_name, google_email))
        avg, n = cur.fetchone()
        cur.close()
        return round(float(avg), 2) if avg is not None and n >= 10 else None
    except Exception as e:
        print(f"[DB] Error getting bid bias: {e}")
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
              FROM twomanspades.vw_player_games v
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
        'last_played': rows[-1][4],
        'recent': [bool(r[0]) for r in rows[-10:]],
    }
