"""Re-dealt hands: someone who did not like the deal and pressed New Game instead of playing it.

A reroll is a hand that was dealt, never touched, and followed by another deal from the same
person. Nothing new is written for this — every deal already logs `new_game_started`, so the
view reads history that is already there.

Read `seconds_held` before drawing any conclusion from a row. A deliberate reroll means someone
looked at eleven cards and decided against them, which takes several seconds. Anything under
about five is the same person clicking a button that had not answered yet — on 2026-09-08 a
4-second query inside POST /new_game produced whole bursts of those, three deals from one click.
"""
from .connection import db_cursor

# Deals before this are not comparable: /new_game answered in 10ms for a year, then spent
# 2026-09-08 taking 7-21s, so that day's history is a mix of real rerolls and stuck buttons.
SINCE = '2026-09-08'

_VIEW_SQL = f"""
CREATE VIEW twomanspades.vw_rerolls AS
WITH dealt AS (
    SELECT e.hand_id,
           e.timestamp AS dealt_at,
           COALESCE(NULLIF(e.google_email, ''), e.client_ip) AS who,
           NOT EXISTS (SELECT 1 FROM twomanspades.game_events x
                        WHERE x.hand_id = e.hand_id
                          AND x.event_type NOT IN ('new_game_started', 'hand_dealt')) AS untouched
      FROM twomanspades.game_events e
     WHERE e.event_type = 'new_game_started'
       AND e.timestamp >= TIMESTAMPTZ '{SINCE} 00:00:00+00'
),
seq AS (
    SELECT d.*,
           LEAD(d.dealt_at) OVER (PARTITION BY d.who ORDER BY d.dealt_at) AS next_deal
      FROM dealt d
)
SELECT who,
       hand_id,
       dealt_at,
       ROUND(EXTRACT(EPOCH FROM (next_deal - dealt_at))::numeric, 1) AS seconds_held,
       EXTRACT(EPOCH FROM (next_deal - dealt_at)) >= 5 AS looks_deliberate
  FROM seq
 WHERE untouched
   AND next_deal IS NOT NULL
   AND next_deal - dealt_at < INTERVAL '5 minutes'
"""


def ensure_reroll_view():
    """Create vw_rerolls once. Checked against the catalog first so steady-state costs one
    cheap SELECT rather than a DDL lock (see utilities/schema_guard.py for why that matters).
    Never raises: this runs inside the Otto cron tick, which has real work to finish."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""SELECT 1 FROM information_schema.views
                            WHERE table_schema = 'twomanspades' AND table_name = 'vw_rerolls'""")
            if cur.fetchone():
                return False
            cur.execute(_VIEW_SQL)
            print('[DB] created twomanspades.vw_rerolls')
            return True
    except Exception as e:
        print(f'[DB] vw_rerolls not created: {e}')
        return False


def reroll_counts(deliberate_only=True):
    """Who has re-dealt, how often, and when they last did it."""
    with db_cursor(dict_rows=True) as cur:
        cur.execute(f"""
            SELECT who, COUNT(*) AS rerolls,
                   ROUND(AVG(seconds_held), 1) AS avg_seconds_held,
                   MAX(dealt_at) AS last_reroll
              FROM twomanspades.vw_rerolls
             {'WHERE looks_deliberate' if deliberate_only else ''}
             GROUP BY who ORDER BY rerolls DESC
        """)
        return [dict(r) for r in cur.fetchall()]
