"""Hoyt Axton jukebox backend: playlist lookup + private-bucket audio proxy.

Audio lives in a PRIVATE GCS bucket (twomanspades-hoyt, us-central1). Nothing is
public; the App Engine service account reads objects and this route streams them
to the browser with HTTP Range support so <audio> can seek. Object layout:
    hoyt/<album_id>/<NN>.m4a      hoyt/<album_id>/cover.jpg (covers also ship in static/)
Only ids present in static/jukebox/playlist.json are served, so the route cannot
be used to read arbitrary objects.

Play events land in twomanspades.jukebox_plays keyed by a client-minted UUID play_id (the
browser upserts the same row across page reloads, so the id has to leave the server): this is
the documented exception to the fleet SERIAL default (decided 2026-09-05).
"""
import json
import os
import re
from flask import Response, request, abort

BUCKET = os.environ.get('HOYT_BUCKET', 'twomanspades-hoyt')
_PLAYLIST = None
_client = None


def playlist():
    global _PLAYLIST
    if _PLAYLIST is None:
        path = os.path.join(os.path.dirname(__file__), '..', 'static', 'jukebox', 'playlist.json')
        _PLAYLIST = json.load(open(path))
    return _PLAYLIST


def _known(album_id, n):
    for a in playlist()['albums']:
        if a['id'] == album_id:
            return any(t['n'] == n for t in a['tracks'])
    return False


def _bucket():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(BUCKET)


def stream_track(album_id, n):
    """Proxy one m4a from the private bucket. Honors a single-range Range header.
    Signed-in players only: the catalogue is Andy's, the table is public."""
    from flask import session
    if not session.get('user'):
        abort(401)
    if not re.fullmatch(r'[a-z0-9-]{4,80}', album_id) or not _known(album_id, n):
        abort(404)
    blob = _bucket().get_blob(f'hoyt/{album_id}/{n:02d}.m4a')
    if blob is None:
        abort(404)
    size = blob.size
    headers = {'Accept-Ranges': 'bytes', 'Content-Type': 'audio/mp4',
               'Cache-Control': 'private, max-age=86400'}
    rng = request.headers.get('Range')
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
    if m and rng:
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        end = int(m.group(2)) if (m.group(1) and m.group(2)) else size - 1
        end = min(end, size - 1)
        if start > end:
            return Response(status=416, headers={'Content-Range': f'bytes */{size}'})
        data = blob.download_as_bytes(start=start, end=end)
        headers.update({'Content-Range': f'bytes {start}-{end}/{size}', 'Content-Length': str(len(data))})
        return Response(data, status=206, headers=headers)
    data = blob.download_as_bytes()
    headers['Content-Length'] = str(len(data))
    return Response(data, status=200, headers=headers)


# ─── play logging ────────────────────────────────────────────────────────────
# One row per play, keyed by a client-generated play_id, upserted as the track
# progresses. Writes go through logging_utils' async queue (fire-and-forget, prod
# only) so the audio path never waits on the database.
_SCHEMA_OK = False


def _ensure_schema(cur):
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    from utilities.schema_guard import table_exists, create_index_if_missing
    if not table_exists(cur, 'twomanspades', 'jukebox_plays'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS twomanspades.jukebox_plays (
                play_id        UUID PRIMARY KEY,
                user_email     TEXT,
                user_name      TEXT,
                ip_address     TEXT,
                album_id       TEXT NOT NULL,
                track_n        SMALLINT NOT NULL,
                title          TEXT,
                album_title    TEXT,
                year           TEXT,
                source         TEXT,                      -- shuffle | album | search | resume
                started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                seconds_played REAL NOT NULL DEFAULT 0,
                duration       REAL,
                completed      BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
    create_index_if_missing(cur, 'twomanspades', 'idx_jukebox_plays_user_started', 'jukebox_plays', '(user_email, started_at DESC)')
    create_index_if_missing(cur, 'twomanspades', 'idx_jukebox_plays_track', 'jukebox_plays', '(album_id, track_n)')
    _SCHEMA_OK = True


def record_play_event(ev):
    """Runs on the async DB worker. ev: dict from POST /jukebox/event."""
    from utilities.postgres_utils import get_db_connection, return_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        _ensure_schema(cur)
        cur.execute("""
            INSERT INTO twomanspades.jukebox_plays
                (play_id, user_email, user_name, ip_address, album_id, track_n, title, album_title, year,
                 source, seconds_played, duration, completed)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (play_id) DO UPDATE SET
                seconds_played = GREATEST(twomanspades.jukebox_plays.seconds_played, EXCLUDED.seconds_played),
                duration       = COALESCE(EXCLUDED.duration, twomanspades.jukebox_plays.duration),
                completed      = twomanspades.jukebox_plays.completed OR EXCLUDED.completed,
                last_seen_at   = NOW()
        """, (ev['play_id'], ev.get('user_email'), ev.get('user_name'), ev.get('ip'), ev['album_id'], int(ev['n']),
              ev.get('title'), ev.get('album_title'), ev.get('year'), ev.get('source'),
              float(ev.get('seconds') or 0), ev.get('duration'), bool(ev.get('completed'))))
        conn.commit()
        cur.close()
    finally:
        return_db_connection(conn)


def queue_play_event(ev, session, ip):
    """Validate + enrich a client event, then hand it to the async worker."""
    from utilities.logging_utils import queue_db_operation
    if not re.fullmatch(r'[0-9a-f-]{36}', str(ev.get('play_id', ''))): return False
    if not _known(str(ev.get('album_id', '')), int(ev.get('n') or 0)): return False
    if ev.get('source') not in ('shuffle', 'album', 'search', 'resume'): ev['source'] = 'unknown'
    user = (session.get('user') or {})
    ev['user_email'] = user.get('email'); ev['user_name'] = user.get('name'); ev['ip'] = ip
    for k in ('title', 'album_title', 'year'):
        ev[k] = str(ev.get(k) or '')[:200]
    queue_db_operation(record_play_event, ev)
    return True


def jukebox_stats():
    """Listening stats for the /stats page. Read-only; empty dict on any failure so the
    page renders without the section rather than 500ing."""
    from utilities.postgres_utils import get_db_connection, return_db_connection
    import psycopg2.extras
    out = {}
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT to_regclass('twomanspades.jukebox_plays') AS t")
        if not cur.fetchone()['t']:
            return out
        cur.execute("""
            SELECT COUNT(*) AS plays, COUNT(*) FILTER (WHERE completed) AS completed,
                   COALESCE(SUM(seconds_played), 0) AS seconds, COUNT(DISTINCT album_id) AS albums,
                   COUNT(DISTINCT (album_id, track_n)) AS songs,
                   COUNT(DISTINCT COALESCE(user_email, ip_address)) AS listeners
            FROM twomanspades.jukebox_plays""")
        out['totals'] = dict(cur.fetchone())
        out['totals']['hours'] = round((out['totals']['seconds'] or 0) / 3600, 1)
        cur.execute("""
            SELECT title, album_title, year, COUNT(*) AS plays, ROUND(SUM(seconds_played)/60) AS minutes
            FROM twomanspades.jukebox_plays WHERE seconds_played >= 30
            GROUP BY album_id, track_n, title, album_title, year ORDER BY plays DESC, minutes DESC LIMIT 10""")
        out['top_songs'] = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT album_title, year, COUNT(*) AS plays, ROUND(SUM(seconds_played)/60) AS minutes
            FROM twomanspades.jukebox_plays WHERE seconds_played >= 30
            GROUP BY album_id, album_title, year ORDER BY minutes DESC, plays DESC LIMIT 10""")
        out['top_albums'] = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT COALESCE(NULLIF(split_part(user_name, ' ', 1), ''), 'Anonymous') AS listener,
                   COUNT(*) AS plays, ROUND(SUM(seconds_played)/60) AS minutes, MAX(started_at) AS last_play
            FROM twomanspades.jukebox_plays
            GROUP BY 1 ORDER BY minutes DESC LIMIT 10""")
        out['listeners'] = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT title, album_title, started_at, seconds_played, completed
            FROM twomanspades.jukebox_plays ORDER BY started_at DESC LIMIT 8""")
        out['recent'] = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        print(f"[JUKEBOX] stats failed: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)
    return out
