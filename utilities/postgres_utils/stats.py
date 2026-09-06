"""Two-Man Spades stats database operations."""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import os
import threading
import time
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List
from .connection import get_db_connection
from .connection import return_db_connection
from .achievements import get_player_achievements, get_per_hand_stats
from .players import get_unified_leaderboard

# /stats is read-mostly and costs ~65 queries (measured 2026-09-05: 4–8 s server-side on the
# shared micro instance). Stale-while-revalidate (2026-09-06): the last payload is served
# instantly, always; once it is older than _PAYLOAD_TTL one background thread rebuilds it
# for the next visitor. Only a cold process ever makes a visitor wait, and warm_stats_cache()
# at boot plus the Otto cron touching /stats every 15 min keep processes warm.
_PAYLOAD = {'data': None, 'ts': 0.0}
_PAYLOAD_TTL = 300
_PAYLOAD_LOCK = threading.Lock()      # single-flight: one rebuild at a time, ever
_REFRESHING = {'on': False}


def _build_payload():
    from utilities.jukebox import jukebox_stats
    from .robots import robot_league
    data = {
        'google_leaders': get_unified_leaderboard(),
        'fun_stats': get_fun_stats(),
        'achievements': get_player_achievements(),
        'special_cards': get_special_card_stats(),
        'overall_stats': get_overall_game_stats(),
        'per_hand_stats': get_per_hand_stats(),
        'hoyt': jukebox_stats(),
        'robots': robot_league(),
        'marta_levels': get_marta_levels(),
    }
    data['styles'] = player_styles(data['google_leaders'], data['achievements'],
                                   data['per_hand_stats'], data['robots'])
    data['reads'] = marta_reads()
    data['live'] = live_tables()
    return data


def _refresh_payload(force=False):
    with _PAYLOAD_LOCK:
        # A visitor who queued behind the boot warm-up finds the payload built by the time
        # the lock frees: don't build it a second time (that doubled a cold load to 15 s).
        if not force and _PAYLOAD['data'] is not None and time.time() - _PAYLOAD['ts'] < _PAYLOAD_TTL:
            _REFRESHING['on'] = False
            return
        try:
            _PAYLOAD.update(data=_build_payload(), ts=time.time())
        except Exception as e:
            print(f"[STATS] payload rebuild failed: {e}")
        finally:
            _REFRESHING['on'] = False


def stats_payload():
    """Everything /stats renders. Serves the cached payload at once; kicks off a background
    rebuild when it is stale. Blocks only on a cold process (no payload yet)."""
    if _PAYLOAD['data'] is None:
        _refresh_payload()
        return _PAYLOAD['data']
    if time.time() - _PAYLOAD['ts'] >= _PAYLOAD_TTL and not _REFRESHING['on']:
        _REFRESHING['on'] = True
        threading.Thread(target=_refresh_payload, kwargs={'force': True}, name='stats-refresh', daemon=True).start()
    return _PAYLOAD['data']


def warm_stats_cache():
    """Build the payload once in the background at process boot so the first visitor is fast."""
    if _PAYLOAD['data'] is None and not _REFRESHING['on']:
        _REFRESHING['on'] = True
        threading.Thread(target=_refresh_payload, name='stats-warm', daemon=True).start()


def live_tables():
    """Tables with activity in the last hour: who, which hand, the score so far, whether the
    game is still going, and a link into it. Anonymous tables show as their city or 'Someone'."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            WITH recent AS (
                SELECT hand_id, MAX(timestamp) AS last_seen, MIN(timestamp) AS first_seen,
                       MAX(hand_number) AS hand_number,
                       BOOL_OR(event_type = 'game_completed') AS finished,
                       MAX(CASE WHEN event_type = 'game_completed' THEN event_data->>'winner' END) AS winner
                  FROM twomanspades.game_events
                 WHERE timestamp > NOW() - INTERVAL '60 minutes'
                 GROUP BY hand_id)
            SELECT r.hand_id, r.last_seen, r.hand_number, r.finished, r.winner,
                   COALESCE(v.player_name, NULLIF(v.city, ''), 'Someone') AS who,
                   h.hand_player_score, h.hand_computer_score
              FROM recent r
              JOIN twomanspades.hands h ON h.hand_id = r.hand_id
              LEFT JOIN twomanspades.vw_player_identity v ON v.hand_id = r.hand_id
             ORDER BY r.last_seen DESC
             LIMIT 60
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        now = datetime.now(rows[0]['last_seen'].tzinfo) if rows and rows[0]['last_seen'] else datetime.now()
        # one line per person: their latest table, plus how many they opened this hour
        # (a "New Game" click a minute is one player, not twelve)
        seen, out = {}, []
        for r in rows:
            mins = int((now - r['last_seen']).total_seconds() // 60) if r['last_seen'] else None
            r['ago'] = 'just now' if mins is not None and mins < 1 else (f"{mins} min ago" if mins is not None else '')
            r['status'] = ('won' if r['winner'] == 'player' else 'lost') if r['finished'] else 'playing'
            if r['who'] in seen:
                seen[r['who']]['tables'] += 1
                continue
            r['tables'] = 1
            seen[r['who']] = r
            out.append(r)
        return out
    except Exception as e:
        print(f"Live tables failed: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)


# ─── Marta's read on the table ─────────────────────────────────────────────────
# One computed title per regular, from thresholds over their own bids/discards/gambles
# (2026-09-06, Andy: "publish those titles at the top"). Rules are ordered; the first that
# fits is the title, the rest become the evidence line. Minimum 50 hands so a newcomer
# isn't branded off a weekend. Otto's mirror match is the yardstick: 19% exact, 1.49 bags.
READ_MIN_HANDS = 50


def style_title(p):
    """(title, evidence) for a profile row from player_profiles(). Pure; tested."""
    hands = p['hands'] or 1
    nil_rate = 100.0 * p['nil_tried'] / hands
    blind_rate = 100.0 * p['blind_tried'] / hands
    nil_made = 100.0 * p['nil_made'] / p['nil_tried'] if p['nil_tried'] else 0
    blind_made = 100.0 * p['blind_made'] / p['blind_tried'] if p['blind_tried'] else 0
    # the distinctive facts first (gambles, overbooking), the generic ones after
    facts = [f"{p['exact_pct']}% exact bids", f"{p['bags_per_hand']} bags a hand"]
    if p['nil_tried']:
        facts.append(f"nil {p['nil_made']} of {p['nil_tried']}")
    if p['blind_tried']:
        facts.append(f"blind {p['blind_made']} of {p['blind_tried']}")
    if p['overbook_pct'] >= 5:
        facts.append(f"bids the table past 10 on {p['overbook_pct']}% of hands")
    facts += [f"set {p['set_pct']}% of hands", f"avg bid {p['avg_bid']}"]
    rules = [
        ('The Accountant', p['exact_pct'] >= 38 and p['bags_per_hand'] <= 0.85),
        ('The Nil Specialist', nil_rate >= 4 and nil_made >= 50),
        ('The Overbidder', p['set_pct'] >= 22 or p['overbook_pct'] >= 8),
        ('The Gambler', blind_rate >= 8 or nil_rate >= 4),
        ('The Bag Collector', p['bags_per_hand'] >= 1.3),
        ('The Conservative', p['nil_tried'] == 0 and p['blind_tried'] == 0 and p['set_pct'] <= 14),
    ]
    title = next((t for t, ok in rules if ok), 'The Steady Hand')
    return title, ', '.join(facts[:5])


def player_profiles():
    """Per regular: the bidding/discard/gamble numbers the titles are computed from."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            WITH hands AS (
                SELECT h.hand_id, v.player_name
                  FROM twomanspades.hands h
                  JOIN twomanspades.vw_player_identity v ON v.hand_id = h.hand_id
                 WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'),
            bids AS (
                SELECT hand_id, hand_number, (event_data->'action_data'->>'bid_amount')::int AS bid,
                       event_type = 'action_blind_bid' AS blind
                  FROM twomanspades.game_events
                 WHERE player = 'player' AND event_type IN ('action_regular_bid', 'action_blind_bid')),
            mbids AS (
                SELECT hand_id, hand_number, (event_data->'action_data'->>'bid_amount')::int AS mbid
                  FROM twomanspades.game_events
                 WHERE player = 'computer' AND event_type IN ('action_regular_bid', 'action_blind_bid')),
            tricks AS (
                SELECT hand_id, hand_number, COUNT(*) FILTER (WHERE event_data->>'winner' = 'player') AS taken
                  FROM twomanspades.game_events WHERE event_type = 'trick_completed' GROUP BY 1, 2)
            SELECT h.player_name AS player, COUNT(*) AS hands,
                   ROUND(AVG(b.bid), 2) AS avg_bid,
                   ROUND(100.0 * AVG((b.bid = t.taken)::int), 1) AS exact_pct,
                   ROUND(100.0 * AVG((t.taken < b.bid)::int), 1) AS set_pct,
                   ROUND(AVG(GREATEST(t.taken - b.bid, 0)), 2) AS bags_per_hand,
                   COUNT(*) FILTER (WHERE b.bid = 0) AS nil_tried,
                   COUNT(*) FILTER (WHERE b.bid = 0 AND t.taken = 0) AS nil_made,
                   COUNT(*) FILTER (WHERE b.blind) AS blind_tried,
                   COUNT(*) FILTER (WHERE b.blind AND t.taken >= b.bid) AS blind_made,
                   ROUND(100.0 * AVG((b.bid + m.mbid > 10)::int), 1) AS overbook_pct
              FROM hands h
              JOIN bids b ON b.hand_id = h.hand_id
              JOIN tricks t ON t.hand_id = b.hand_id AND t.hand_number = b.hand_number
              LEFT JOIN mbids m ON m.hand_id = b.hand_id AND m.hand_number = b.hand_number
             GROUP BY 1 HAVING COUNT(*) >= %s
             ORDER BY 2 DESC
        """, (READ_MIN_HANDS,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            for k in ('avg_bid', 'exact_pct', 'set_pct', 'bags_per_hand', 'overbook_pct'):
                r[k] = float(r[k] or 0)
        return rows
    except Exception as e:
        print(f"Player profiles failed: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)


def style_review(p, title):
    """Two short paragraphs in Marta's voice: why the title fits, and how to play against
    them. Built from the numbers so it stays true as they change (Andy, 2026-09-06: "put the
    verbiage as to why, and how to play against each one")."""
    name = p['player']
    hands = p['hands'] or 1
    nil_rate = 100.0 * p['nil_tried'] / hands
    blind_rate = 100.0 * p['blind_tried'] / hands
    nil_made = round(100.0 * p['nil_made'] / p['nil_tried']) if p['nil_tried'] else 0
    blind_made = round(100.0 * p['blind_made'] / p['blind_tried']) if p['blind_tried'] else 0
    why = {
        'The Accountant': (f"{name} bids what the hand will take: exact on {p['exact_pct']}% of hands, twice my "
                           f"own rate, and only {p['bags_per_hand']} bags a hand. Nothing is wasted. The price is "
                           f"getting set {p['set_pct']}% of the time, because there is no cushion under a bid like that."),
        'The Nil Specialist': (f"{name} has bid nil {p['nil_tried']} times and made it {nil_made}% of the time, and "
                               f"goes blind on {blind_rate:.0f}% of hands with a {blind_made}% strike rate. A third of "
                               f"the edge comes from the two big swings; the ordinary hands are bid a shade under."),
        'The Overbidder': (f"{name} bids a trick more than the hand holds: average bid {p['avg_bid']}, set "
                           f"{p['set_pct']}% of the time, and the two bids add past 10 on {p['overbook_pct']}% of "
                           f"hands. The hand reads fine; the rounding is up, every time. Blind bids are the equalizer: "
                           f"{p['blind_made']} of {p['blind_tried']} made."),
        'The Gambler': (f"{name} goes blind on {blind_rate:.0f}% of hands and bids nil on {nil_rate:.0f}%, and lives "
                        f"on the swings: blind {p['blind_made']} of {p['blind_tried']}, nil {p['nil_made']} of {p['nil_tried']}."),
        'The Bag Collector': (f"{name} takes tricks that weren't bid: {p['bags_per_hand']} bags a hand. The bids are "
                              f"safe ({p['set_pct']}% set) and the penalty arrives every few hands anyway."),
        'The Conservative': (f"{name} has never bid nil or gone blind in {p['hands']} hands, and is set only "
                             f"{p['set_pct']}% of the time. Safe bids, no swings, no surprises."),
    }.get(title, f"{name} bids {p['avg_bid']} on average, exact {p['exact_pct']}% of the time, {p['bags_per_hand']} bags a hand.")
    counter = {
        'The Accountant': ("You won't out-bid them, so make the bid cost something: once they've bid, hand them "
                           "tricks they don't want. Lead high when they're made and let the bags pile up. Their nil "
                           "is real, so break it early with a low lead in their long suit."),
        'The Nil Specialist': ("Assume the nil is coming whenever they're behind, and duck under everything: lead "
                               "your lowest cards, follow under theirs, force them to win one. When they go blind, "
                               "bid normally and set them; a failed blind is a hundred points the other way."),
        'The Overbidder': ("Let the bid do the work. Bid your hand honestly, then play to set them: hold the high "
                           "cards in their long suits, trump their winners, and don't chase tricks you don't need. "
                           "When they go blind, that's the hand to be careful in; it's the one they win."),
        'The Gambler': ("Play the percentages against the swings. Duck to break the nil, bid straight and set the "
                        "blind. Most of their losses come from the gambles that don't land."),
        'The Bag Collector': ("Feed them. Once they've made their bid, lead cards they have to win; the penalty "
                              "does the rest. Never take a trick you don't need against this player."),
        'The Conservative': ("Bid to your hand and take the tricks they leave behind. They won't punish an "
                             "aggressive bid, and they won't gamble their way back when behind."),
    }.get(title, "Bid your hand and take what they leave behind.")
    return why, counter


def marta_reads():
    """[{player, title, evidence, why, counter, hands}] for the top-of-page section."""
    out = []
    for p in player_profiles():
        title, evidence = style_title(p)
        why, counter = style_review(p, title)
        out.append({'player': p['player'], 'title': title, 'evidence': evidence, 'why': why,
                    'counter': counter, 'hands': p['hands']})
    return out


def get_marta_levels():
    """Completed hands by Marta level, plus the average strength (0-100) people play her at."""
    from utilities.computer_logic import STRENGTH_PRESETS, DIFFICULTY_LEVELS
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(difficulty, 'easy'), COUNT(*)
              FROM twomanspades.hands WHERE completed_at IS NOT NULL GROUP BY 1
        """)
        counts = dict(cur.fetchall())
        cur.close()
        total = sum(counts.values()) or 1
        rows = [{'level': lvl, 'hands': counts.get(lvl, 0), 'pct': round(100.0 * counts.get(lvl, 0) / total, 1)}
                for lvl in DIFFICULTY_LEVELS]
        avg = sum(STRENGTH_PRESETS.get(k, 0) * n for k, n in counts.items()) / total
        return {'levels': rows, 'avg_strength': round(avg, 1), 'total': total,
                'above_easy_pct': round(100.0 * (total - counts.get('easy', 0)) / total, 1)}
    except Exception as e:
        print(f"Marta level stats failed: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def player_styles(leaders, achievements, per_hand, robots):
    """One row per player with the numbers that define how they play, plus Otto and Marta
    (the bot mirror match) as the control rows. Pure merge of payloads already computed."""
    rows = {}
    def row(name):
        return rows.setdefault(name, {'player': name})
    for p in leaders or []:
        row(p['player_name']).update(games=p.get('total_games'), win_rate=p.get('win_rate'))
    a = achievements or {}
    for p in a.get('bid_accuracy', []):
        row(p['player']).update(exact_pct=p['exact_pct'], hands=p['hands'])
    for p in a.get('favorite_bids', []):
        row(p['player']).update(fav_bid=p['favorite_bid'])
    for p in a.get('bag_stats', []):
        row(p['player']).update(bags_per_hand=p['bags_per_hand'])
    for p in a.get('nil_stats', []):
        row(p['player']).update(nil=f"{p['successful']}/{p['attempts']}")
    for p in a.get('blind_stats', []):
        row(p['player']).update(blind=f"{p['blind_successes']}/{p['times_went_blind']}")
    for p in (per_hand or {}).get('player_tricks_per_hand', []):
        row(p['player']).update(tricks=p['avg_tricks'])
    humans = [r for n, r in rows.items() if n and n != 'Other' and r.get('hands')]
    humans.sort(key=lambda r: -(r.get('hands') or 0))
    controls = []
    for s in (robots or {}).get('seats', []):
        controls.append({'player': f"{s['seat']} (bot)", 'hands': s['hands'], 'exact_pct': s['exact_pct'],
                         'bags_per_hand': s['avg_bags'], 'nil': f"{s['nil_made']}/{s['nil_tried']}",
                         'blind': f"{s['blind_made']}/{s['blind_tried']}", 'avg_bid': s['avg_bid'],
                         'control': True})
    return humans + controls

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
