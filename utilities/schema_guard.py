"""Schema-guard helpers — check information_schema FIRST, never take AccessExclusiveLock when the column/index already exists.

CANONICAL LOCATION. Edit this file, NOT the vendored copies under each
project's utilities/schema_guard.py. The deploy tool copies this file into
every project that declares it in deploy.json shared_files.

Why this exists (2026-05-19): an outage at pilgri.ms traced to
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` running on every worker startup.
Even when the column already exists, `IF NOT EXISTS` still asks Postgres
for an AccessExclusiveLock on the table; Postgres grants it, sees the
column, releases it. The lock window is brief, but the AEL *request*
queues behind any existing lock holder AND blocks every subsequent
AccessShareLock (reads). Combined with a single idle-in-transaction
session and 20+ concurrent ensure_*() calls from cold workers, that turns
into multi-second head-of-line blocking on the whole table.

The fix: read pg_indexes / information_schema.columns first. If the
artifact exists, skip the ALTER/CREATE entirely. Steady-state cold-boot
path makes ~N cheap catalog SELECTs instead of ~N exclusive-lock
requests. The first deploy that introduces a new artifact still runs the
ALTER once.

API:
    column_exists(cur, schema, table, column) -> bool
    index_exists(cur, schema, index_name) -> bool
    table_exists(cur, schema, table) -> bool
    add_column_if_missing(cur, schema, table, column, sql_type, default=None) -> bool
    create_index_if_missing(cur, schema, index_name, on_table, columns, where=None, unique=False) -> bool

Return value of the mutating helpers: True if a write actually happened,
False if it was a no-op skip. Logs the write at INFO; silent on skip.
"""
import logging

logger = logging.getLogger(__name__)


def column_exists(cur, schema, table, column):
    """True if column already exists. Cheap — hits pg_attribute via information_schema."""
    cur.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s AND column_name = %s
         LIMIT 1
        """,
        (schema, table, column),
    )
    return cur.fetchone() is not None


def index_exists(cur, schema, index_name):
    """True if index already exists. Cheap — pg_indexes is a system view, no row scan."""
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname = %s AND indexname = %s LIMIT 1",
        (schema, index_name),
    )
    return cur.fetchone() is not None


def table_exists(cur, schema, table):
    """True if table already exists."""
    cur.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = %s AND table_name = %s
         LIMIT 1
        """,
        (schema, table),
    )
    return cur.fetchone() is not None


def add_column_if_missing(cur, schema, table, column, sql_type, default=None):
    """ALTER TABLE … ADD COLUMN, BUT ONLY IF THE COLUMN DOESN'T EXIST.

    Unlike `ADD COLUMN IF NOT EXISTS` (which silently requests
    AccessExclusiveLock even when the column is already there), this
    skips the ALTER entirely on steady-state. Returns True if a write
    actually happened, False if it was a no-op skip.
    """
    if column_exists(cur, schema, table, column):
        return False
    default_clause = f" DEFAULT {default}" if default is not None else ""
    sql = f'ALTER TABLE "{schema}"."{table}" ADD COLUMN "{column}" {sql_type}{default_clause}'
    logger.info("schema_guard: %s", sql)
    cur.execute(sql)
    return True


def create_index_if_missing(cur, schema, index_name, on_table, columns, where=None, unique=False):
    """CREATE INDEX, BUT ONLY IF NOT ALREADY THERE. Skips the catalog/lock work on steady state.

    columns: a string like "(client_id, status, created_at DESC)" or just "(id)".
    where: optional WHERE clause for partial indexes (e.g. "task_id IS NULL").
    """
    if index_exists(cur, schema, index_name):
        return False
    u = "UNIQUE " if unique else ""
    w = f" WHERE {where}" if where else ""
    sql = f'CREATE {u}INDEX "{index_name}" ON "{schema}"."{on_table}" {columns}{w}'
    logger.info("schema_guard: %s", sql)
    cur.execute(sql)
    return True
