"""Career records and splits — the stats that only go up (Andy, 2026-09-08).

A current streak resets the moment it breaks, which makes it a bad thing to be proud of. These
are the numbers nobody can take back: the best run you ever put together, everything you have
piled up since your first game, and the strongest Marta you have beaten. The splits at the end
are for fun rather than pride — when you play well, and whether leading first is worth anything.

Every query reads vw_player_games (one row per game) rather than the base view.
"""
from typing import Any, Dict, List
import psycopg2.extras
from .connection import get_db_connection, return_db_connection


def _rows(cur, sql, args=None):
    cur.execute(sql, args or ())
    return [dict(r) for r in cur.fetchall()]


def career_stats() -> Dict[str, Any]:
    """{'records': [...], 'best_streaks': [...], 'by_hour': [...], 'first_leader': [...]}."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Everything piled up since the first game. Tricks come from the trick log rather than
        # the game rows, so they count actual tricks taken, not games won.
        records = _rows(cur, '''
            WITH mine AS (
                SELECT v.player_name, v.hand_id, v.won, v.hands_played, v.final_player_score,
                       gc.timestamp AS played_at
                  FROM twomanspades.vw_player_games v
                  JOIN twomanspades.vw_game_completion gc ON gc.hand_id = v.hand_id
                 WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'),
            tricks AS (
                SELECT v.player_name, COUNT(*) AS tricks_won
                  FROM twomanspades.game_events ge
                  JOIN twomanspades.vw_player_identity v ON v.hand_id = ge.hand_id
                 WHERE ge.event_type = 'trick_completed' AND ge.event_data->>'winner' = 'player'
                   AND v.player_name IS NOT NULL AND v.player_name <> 'Other'
                 GROUP BY 1)
            SELECT m.player_name AS player,
                   COUNT(*) AS games,
                   SUM(CASE WHEN m.won THEN 1 ELSE 0 END) AS wins,
                   COALESCE(SUM(m.hands_played), 0) AS hands,
                   COALESCE(t.tricks_won, 0) AS tricks,
                   COALESCE(SUM(GREATEST(m.final_player_score, 0)), 0) AS points,
                   MIN(m.played_at) AS first_game,
                   MAX(m.played_at) AS last_game,
                   (MAX(m.played_at)::date - MIN(m.played_at)::date) + 1 AS days
              FROM mine m
              LEFT JOIN tricks t ON t.player_name = m.player_name
             GROUP BY m.player_name, t.tricks_won
             ORDER BY games DESC
        ''')

        # The best run anyone ever put together, win or loss, and when it happened. Gaps and
        # islands: consecutive same-result games share (row number - row number within result).
        best = _rows(cur, '''
            WITH g AS (
                SELECT v.player_name, v.won, gc.timestamp AS played_at,
                       ROW_NUMBER() OVER (PARTITION BY v.player_name ORDER BY gc.timestamp) AS rn
                  FROM twomanspades.vw_player_games v
                  JOIN twomanspades.vw_game_completion gc ON gc.hand_id = v.hand_id
                 WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'),
            islands AS (
                SELECT player_name, won, played_at,
                       rn - ROW_NUMBER() OVER (PARTITION BY player_name, won ORDER BY rn) AS island
                  FROM g),
            runs AS (
                SELECT player_name, won, COUNT(*) AS len, MIN(played_at) AS started, MAX(played_at) AS ended
                  FROM islands GROUP BY player_name, won, island)
            SELECT DISTINCT ON (player_name, won) player_name AS player, won, len, started, ended
              FROM runs ORDER BY player_name, won, len DESC, ended DESC
        ''')
        best_streaks = _fold_best(best)

        # When each person plays their best. Four buckets, in the player's own clock is not
        # something we know, so this is server time and says so on the page.
        by_hour = _rows(cur, '''
            SELECT v.player_name AS player,
                   CASE WHEN EXTRACT(hour FROM gc.timestamp) < 6 THEN 'Late night'
                        WHEN EXTRACT(hour FROM gc.timestamp) < 12 THEN 'Morning'
                        WHEN EXTRACT(hour FROM gc.timestamp) < 18 THEN 'Afternoon'
                        ELSE 'Evening' END AS part,
                   COUNT(*) AS games,
                   ROUND(100.0 * AVG(v.won::int), 1) AS win_pct
              FROM twomanspades.vw_player_games v
              JOIN twomanspades.vw_game_completion gc ON gc.hand_id = v.hand_id
             WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'
             GROUP BY 1, 2 HAVING COUNT(*) >= 5
             ORDER BY 1, 4 DESC
        ''')

        # Is leading the first hand of the game worth anything?
        first_leader = _rows(cur, '''
            SELECT v.player_name AS player,
                   COUNT(*) FILTER (WHERE h.first_leader = 'player') AS led,
                   ROUND(100.0 * AVG(v.won::int) FILTER (WHERE h.first_leader = 'player'), 1) AS led_win_pct,
                   COUNT(*) FILTER (WHERE h.first_leader <> 'player') AS marta_led,
                   ROUND(100.0 * AVG(v.won::int) FILTER (WHERE h.first_leader <> 'player'), 1) AS marta_led_win_pct
              FROM twomanspades.vw_player_games v
              JOIN twomanspades.hands h ON h.hand_id = v.hand_id
             WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'
             GROUP BY 1 HAVING COUNT(*) >= 10
             ORDER BY 1
        ''')

        cur.close()
        return {'records': records, 'best_streaks': best_streaks,
                'by_hour': _best_part(by_hour), 'first_leader': first_leader}
    except Exception as e:
        print(f"Career stats failed: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def _fold_best(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per player carrying their best win run and their worst losing run."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        e = out.setdefault(r['player'], {'player': r['player']})
        side = 'win' if r['won'] else 'loss'
        e[f'best_{side}'] = r['len']
        e[f'{side}_started'] = r['started']
        e[f'{side}_ended'] = r['ended']
    return sorted(out.values(), key=lambda e: e.get('best_win', 0), reverse=True)


def _best_part(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each player's strongest part of the day, with how many games it rests on."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r['player'] not in out:
            out[r['player']] = r
    return sorted(out.values(), key=lambda r: r['win_pct'], reverse=True)
