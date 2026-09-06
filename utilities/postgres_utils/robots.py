"""Robot League read side: Otto vs Marta from twomanspades.bot_games / bot_decisions.
Bot games live in their own tables so nothing here (or in stats.py) can bleed into the
human leaderboard; this module is the only reader. Written by utilities/otto.py."""
import psycopg2.extras
from .connection import get_db_connection, return_db_connection


def robot_league():
    """Dict for the /stats Robot League section, or {} when no bot game has been filed yet."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        from utilities.schema_guard import table_exists
        if not table_exists(cur, 'twomanspades', 'bot_games'):
            return {}
        cur.execute("""
            SELECT COUNT(*) AS games,
                   COUNT(*) FILTER (WHERE winner = 'otto')  AS otto_wins,
                   COUNT(*) FILTER (WHERE winner = 'marta') AS marta_wins,
                   COUNT(*) FILTER (WHERE winner = 'tie')   AS ties,
                   COUNT(*) FILTER (WHERE played_at::date = CURRENT_DATE) AS games_today,
                   ROUND(AVG(hands), 1) AS avg_hands,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE winner = first_leader) / NULLIF(COUNT(*), 0), 1)
                       AS first_leader_win_pct
              FROM twomanspades.bot_games
        """)
        out = dict(cur.fetchone())
        if not out['games']:
            return {}
        cur.execute("SELECT winner FROM twomanspades.bot_games ORDER BY played_at DESC LIMIT 50")
        winners = [r['winner'] for r in cur.fetchall()]
        streak = 0
        for w in winners:
            if w != winners[0]:
                break
            streak += 1
        out['streak_holder'] = winners[0].title() if winners else ''
        out['streak'] = streak
        cur.execute("""
            SELECT seat,
                   COUNT(*) AS hands,
                   COUNT(*) FILTER (WHERE bid = tricks) AS exact,
                   COUNT(*) FILTER (WHERE bid = 0) AS nil_tried,
                   COUNT(*) FILTER (WHERE bid = 0 AND tricks = 0) AS nil_made,
                   COUNT(*) FILTER (WHERE blind) AS blind_tried,
                   COUNT(*) FILTER (WHERE blind AND tricks >= bid) AS blind_made,
                   ROUND(AVG(over), 2) AS avg_bags,
                   ROUND(AVG(bid), 2) AS avg_bid
              FROM (
                SELECT 'Otto' AS seat, (data->>'otto_bid')::int AS bid, (data->>'otto_tricks')::int AS tricks,
                       (data->>'otto_blind')::boolean AS blind, (data->>'otto_over')::int AS over
                  FROM twomanspades.bot_decisions WHERE kind = 'hand'
                UNION ALL
                SELECT 'Marta', (data->>'marta_bid')::int, (data->>'marta_tricks')::int,
                       (data->>'marta_blind')::boolean, (data->>'marta_over')::int
                  FROM twomanspades.bot_decisions WHERE kind = 'hand'
              ) h
             GROUP BY seat ORDER BY seat DESC
        """)
        seats = [dict(r) for r in cur.fetchall()]
        for s in seats:
            s['exact_pct'] = round(100.0 * s['exact'] / s['hands'], 1) if s['hands'] else 0
        out['seats'] = seats
        cur.execute("""
            SELECT game_id, played_at, winner, otto_score, marta_score, hands, first_leader, seed
              FROM twomanspades.bot_games ORDER BY played_at DESC LIMIT 12
        """)
        out['recent'] = [dict(r) for r in cur.fetchall()]
        cur.close()
        return out
    except Exception as e:
        print(f"Robot league stats failed: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)
