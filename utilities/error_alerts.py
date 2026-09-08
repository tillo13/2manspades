"""One email per problem, not one per occurrence (2026-09-08).

The error handler already had an hourly rate limit, but it lived in a dict on the instance. App
Engine runs several instances and recycles them, so a crash loop mailed once per instance per
hour and then again for every fresh instance. A cron failing every 15 minutes got
kumoridotai@gmail.com blocked by Gmail (550 5.7.1 "likely unsolicited mail"), and that address
is shared by every app Andy runs, so it put unrelated mail at risk.

The fix is not to send less about real failures. It is to say the same thing once: the first
occurrence goes out immediately, and everything inside the cooldown is counted and folded into
the next message. The state lives in the database so every instance agrees.

If the database is itself the thing that is broken, this fails open — a missed dedupe is far
better than a missed alert.
"""
import time
from .postgres_utils.connection import get_db_connection, return_db_connection

COOLDOWN_SECONDS = 3600
_TABLE_OK = False
_FALLBACK = {}          # only used when the database cannot be reached


def _ensure(cur):
    global _TABLE_OK
    if _TABLE_OK:
        return
    cur.execute('''
        CREATE TABLE IF NOT EXISTS twomanspades.error_alerts (
            signature   TEXT PRIMARY KEY,
            first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_sent   TIMESTAMPTZ,
            since_sent  INT NOT NULL DEFAULT 0,
            total       INT NOT NULL DEFAULT 0)
    ''')
    _TABLE_OK = True


def record(signature, cooldown=COOLDOWN_SECONDS):
    """Count this occurrence and say whether to mail about it.

    Returns (send, note) where note describes what the message is standing in for, e.g.
    '47 more since 14:05' — empty for a first occurrence."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('''
            INSERT INTO twomanspades.error_alerts (signature, since_sent, total)
                 VALUES (%s, 1, 1)
            ON CONFLICT (signature) DO UPDATE
                    SET since_sent = twomanspades.error_alerts.since_sent + 1,
                        total      = twomanspades.error_alerts.total + 1,
                        last_seen  = NOW()
              RETURNING last_sent, since_sent, total, first_seen,
                        (last_sent IS NULL OR last_sent < NOW() - (%s || ' seconds')::interval) AS due
        ''', (signature, int(cooldown)))
        last_sent, since, total, first_seen, due = cur.fetchone()
        if not due:
            conn.commit()
            cur.close()
            return False, ''
        cur.execute('''UPDATE twomanspades.error_alerts SET last_sent = NOW(), since_sent = 0
                        WHERE signature = %s''', (signature,))
        conn.commit()
        cur.close()
        if last_sent is None:
            return True, ''
        extra = since - 1                       # this one is being reported, the rest were held
        held = f"{extra} more since {last_sent.strftime('%H:%M UTC')}" if extra > 0 else 'none held'
        return True, f"{held} · {total} in total since {first_seen.strftime('%b %-d %H:%M UTC')}"
    except Exception as e:
        print(f"[ALERTS] dedupe unavailable, failing open: {e}")
        now = time.time()
        if now - _FALLBACK.get(signature, 0) > cooldown:
            _FALLBACK[signature] = now
            return True, ''
        return False, ''
    finally:
        if conn is not None:
            return_db_connection(conn)
