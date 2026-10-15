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
    alter_if_columns_missing(cur, schema, table, alter_sql) -> bool
    index_ddl_if_missing(cur, schema, ddl) -> bool
    replace_check_if_changed(cur, schema, table, name, add_sql) -> bool

The last three take an existing DDL string unchanged, so a long
`ADD COLUMN IF NOT EXISTS ...` block or a `CREATE INDEX IF NOT EXISTS` keeps
its text and only runs when something it names is missing.

Return value of the mutating helpers: True if a write actually happened,
False if it was a no-op skip. Logs the write at INFO; silent on skip.
"""
import logging
import re

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



def alter_if_columns_missing(cur, schema, table, alter_sql):
    """Run an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS a, ADD COLUMN IF NOT EXISTS b ...`
    block only when at least one of the columns it names is missing (one catalog read)."""
    wanted = re.findall(r'ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+"?(\w+)', alter_sql, re.I)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    )
    have = {r[0] if not isinstance(r, dict) else r['column_name'] for r in cur.fetchall()}
    if wanted and set(wanted) <= have:
        return False
    logger.info("schema_guard: adding %s to %s.%s", sorted(set(wanted) - have), schema, table)
    cur.execute(alter_sql)
    return True


def index_ddl_if_missing(cur, schema, ddl):
    """Run a `CREATE [UNIQUE] INDEX IF NOT EXISTS name ...` statement only when the index is
    missing. The raw form takes a SHARE lock on the table (blocking its writes) before it
    looks the name up, and keeps it until the transaction ends."""
    m = re.search(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\s+"?(\w+)', ddl, re.I)
    if m and index_exists(cur, schema, m.group(1)):
        return False
    logger.info("schema_guard: %s", ' '.join(ddl.split())[:200])
    cur.execute(ddl)
    return True


def _literals(sql):
    return set(re.findall(r"'((?:[^']|'')*)'", sql))


def replace_check_if_changed(cur, schema, table, name, add_sql):
    """DROP + re-ADD a CHECK constraint only when the allowed literals changed. Re-adding it
    every boot takes AccessExclusiveLock and rescans the whole table to validate it."""
    cur.execute(
        """
        SELECT pg_get_constraintdef(c.oid)
          FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = %s AND t.relname = %s AND c.conname = %s
        """,
        (schema, table, name),
    )
    row = cur.fetchone()
    have = (row[0] if not isinstance(row, dict) else row['pg_get_constraintdef']) if row else None
    if have is not None and _literals(have) == _literals(add_sql):
        return False
    logger.info("schema_guard: replacing CHECK %s on %s.%s", name, schema, table)
    cur.execute(f'ALTER TABLE "{schema}"."{table}" DROP CONSTRAINT IF EXISTS "{name}"')
    cur.execute(add_sql)
    return True
