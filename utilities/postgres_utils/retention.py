"""Keep game_events small enough to stay in the shared instance's buffer cache.

game_events is the biggest table on twomanspades and `action_card_play` is most of
it: 119,934 of 282,825 rows and 25 MB of the JSON on 2026-09-16. Nothing reads it.
No view references it, no query filters on it, and the only mention in the codebase
is a test asserting that otto WRITES it. It is a write-only log of every individual
card played since 2025-09-14.

That matters because the instance is shared. shared_buffers is 128 MB for all 17
apps on it, and the main database was running an 88.6% cache hit ratio against
kumori's own 95% floor. A scan of this table evicts every other app's pages, which
is why twomanspades, kindness, pilgrims and kumori all logged statement timeouts
and pool exhaustion inside the same two minutes on 2026-09-15.

Rows are MOVED, never dropped: the archive table is cold, so its pages never enter
the working set, and the data is still there if a replay or a training set ever
wants it.
"""
import logging

from .connection import db_cursor

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
# One tick's ceiling. The move is a single transaction, so this also bounds how
# long game_events holds row locks while a game could be writing to it.
BATCH = 5000


def _ensure_archive(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS twomanspades.game_events_archive
        (LIKE twomanspades.game_events INCLUDING DEFAULTS)""")


def prune_card_plays(days: int = RETENTION_DAYS, limit: int = BATCH) -> dict:
    """Move one batch of aged action_card_play rows to the archive. Returns counts."""
    with db_cursor(commit=True) as cur:
        _ensure_archive(cur)
        # DELETE ... RETURNING feeding the INSERT keeps the move atomic: if the
        # insert fails, the delete rolls back with it and nothing is lost.
        cur.execute("""
            WITH moved AS (
                DELETE FROM twomanspades.game_events
                 WHERE id IN (
                     SELECT id FROM twomanspades.game_events
                      WHERE event_type = 'action_card_play'
                        AND timestamp < now() - (%s || ' days')::interval
                      ORDER BY id
                      LIMIT %s)
                RETURNING *)
            INSERT INTO twomanspades.game_events_archive SELECT * FROM moved""",
            (days, limit))
        moved = cur.rowcount
        cur.execute("""
            SELECT count(*) FROM twomanspades.game_events
             WHERE event_type = 'action_card_play'
               AND timestamp < now() - (%s || ' days')::interval""", (days,))
        remaining = cur.fetchone()[0]
    if moved:
        logger.info("retention: archived %d action_card_play rows, %d still aged", moved, remaining)
    return {'archived': moved, 'remaining': remaining}
