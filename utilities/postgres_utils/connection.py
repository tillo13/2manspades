"""Two-Man Spades connection database operations."""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List

_pool = None
_pool_lock = threading.Lock()
_secrets_cache = {}
_sm_client = None
_slots = threading.BoundedSemaphore(2)
_checked_out = set()   # id(conn) of every conn currently handed out
_patient = threading.local()   # per-thread retry policy, see patient_pool


@contextmanager
def patient_pool(waits=(2, 5, 10)):
    """Crons and batch work wait for a busy pool instead of failing at once.

    The pool is two slots on a Cloud SQL instance shared by 20+ apps. Any of
    their batch jobs can slow it for a minute, and a request whose queries hit
    the 30s statement timeout holds a slot the whole time. A cron tick that
    lands in that minute used to raise PoolError on the first 10s wait and
    email a stack trace (2026-09-10 and 2026-09-14, cron_andybot, both while
    another project ran heavy reads). Cloud SQL's own guidance and every job
    runner retry transient connection failures with backoff; this is that,
    scoped to the thread so page requests keep failing fast.

    waits: seconds to sleep between the 10s acquire attempts, so the default
    is up to ~47s before giving up. Nest-safe: restores the previous policy.
    """
    prev = getattr(_patient, 'waits', None)
    _patient.waits = tuple(waits)
    try:
        yield
    finally:
        _patient.waits = prev

def get_secret(secret_id: str, project_id: str = "kumori-404602") -> str:
    """Get secret from Google Secret Manager (cached)"""
    if secret_id in os.environ:
        return os.environ[secret_id]
    cache_key = f"{project_id}:{secret_id}"
    if cache_key in _secrets_cache:
        return _secrets_cache[cache_key]
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = _sm_client.access_secret_version(request={"name": name}, timeout=10)
    val = response.payload.data.decode('UTF-8')
    _secrets_cache[cache_key] = val
    return val


def _get_pool():
    """Get or create the connection pool (singleton)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
                if is_gcp:
                    connection_name = get_secret('TWOMANSPADES_POSTGRES_CONNECTION_NAME')
                    host = f"/cloudsql/{connection_name}"
                else:
                    host = os.getenv('DB_HOST', '127.0.0.1')
                    if host not in ('127.0.0.1', 'localhost', '::1'):
                        raise ValueError('Local database access must use a loopback Cloud SQL Auth Proxy')
                dbname = get_secret('TWOMANSPADES_POSTGRES_DB_NAME')
                # Cloud SQL IAM login (#170): on GCP with KUMORI_DB_AUTH=iam the app logs in as
                # twomanspades@appspot with a one-hour token and runs as twomanspades_app; no DB
                # password read. The IAM pool is kumori's canonical one (utilities/kumori_db.py,
                # vendored on deploy); this module keeps its own checkout gate. search_path is
                # passed per connection because the role's own setting only applies to its login.
                if is_gcp and os.environ.get('KUMORI_DB_AUTH') == 'iam':
                    try:
                        from utilities.kumori_db import _IAMConnectionPool, _iam_db_user
                        _pool = _IAMConnectionPool(
                            1, 2, host=host, database=dbname, user=_iam_db_user(), password='',
                            port=5432, application_name='twomanspades', connect_timeout=10,
                            options='-c statement_timeout=30000 '
                                    '-c idle_in_transaction_session_timeout=120000 '
                                    '-c role=twomanspades_app -c search_path=twomanspades,public')
                        print('[POOL] Created IAM-auth connection pool as twomanspades_app')
                        return _pool
                    except Exception as e:
                        print(f'[POOL] IAM DB auth failed, falling back to password login: {e}')
                user = get_secret('TWOMANSPADES_POSTGRES_USERNAME')
                password = get_secret('TWOMANSPADES_POSTGRES_PASSWORD')
                if user == 'postgres':
                    raise ValueError('The app must use its own database role')
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 2, host=host, database=dbname,
                    user=user, password=password,
                    port=int(os.getenv('DB_PORT', '5432' if is_gcp else '5433')),
                    application_name='twomanspades',
                    connect_timeout=10,
                    # idle_in_transaction backstop: many helpers only return
                    # the pooled conn on the happy path, so an exception can
                    # strand a conn mid-transaction holding locks (7/15+7/17
                    # DB alerts: 37-55min idle-in-transaction). The server now
                    # kills those after 2min; the pool ping replaces them.
                    options='-c statement_timeout=30000 '
                            '-c idle_in_transaction_session_timeout=120000'
                )
    return _pool


def get_db_connection():
    """Get a connection from the pool (fast!), pinging out stale conns.

    Cloud SQL reaps idle conns (~10min) and the idle_in_transaction timeout
    kills stranded ones; without the ping the pool hands those corpses to the
    next request, which dies with OperationalError on its first execute.
    """
    if not _slots.acquire(timeout=10):
        waited = 0
        for wait in (getattr(_patient, 'waits', None) or ()):
            time.sleep(wait)
            waited += wait + 10
            if _slots.acquire(timeout=10):
                print(f"[POOL] busy, got a slot after ~{waited}s of waiting")
                break
        else:
            raise psycopg2.pool.PoolError('Database pool busy; retry shortly')
    try:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.rollback()   # don't hand out an open txn from the ping
        except psycopg2.Error:
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = pool.getconn()
        _checked_out.add(id(conn))
        return conn
    except Exception:
        _slots.release()
        raise


def return_db_connection(conn):
    """Return a connection to the pool (with rollback to clear any aborted txn).

    Idempotent: helpers release in a `finally`, so a second return of the same
    conn must be a no-op rather than over-releasing the checkout gate."""
    if id(conn) not in _checked_out:
        return
    _checked_out.discard(id(conn))
    try:
        conn.rollback()
    except Exception:
        pass
    try:
        _get_pool().putconn(conn, close=bool(conn.closed))
    except Exception:
        try:
            conn.close()
        except:
            pass
    finally:
        _slots.release()


@contextmanager
def db_cursor(commit=False, dict_rows=False):
    """Canonical pooled cursor; release the connection on success and failure."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if dict_rows else None) as cur:
            yield cur
        if commit:
            conn.commit()
    finally:
        return_db_connection(conn)


def test_connection():
    """Test database connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"PostgreSQL connection successful: {version[0]}")
        cur.close()
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False
