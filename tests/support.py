"""Offline application fixture: real routes and rules, stubbed external services."""
import os
import secrets
from unittest.mock import patch

os.environ.setdefault('KUMORI_API_KEY', 'test-router')
os.environ.setdefault('TWOMANSPADES_FLASK_SECRET', secrets.token_hex(32))


def load_app():
    # No telemetry from tests: the visitor flusher is a daemon thread that opens gRPC +
    # psycopg2 during interpreter exit and segfaulted the deploy gate 1 run in 4 (2026-09-05).
    with patch('google.cloud.secretmanager.SecretManagerServiceClient'), \
         patch('utilities.visitor_logging.install_middleware'):
        import app
    app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return app


def offline_pool():
    """A pool whose connections answer the ping and return nothing interesting.

    isolate_services installs this so no route the suite exercises can reach the
    driver. Patching Secret Manager is the wrong seam — it stubs where the
    credentials come from and leaves psycopg2 free to dial out — so the seam is
    the pool. Tests that care about pool behaviour patch _get_pool again with a
    double of their own; the innermost patch wins.
    """
    from unittest.mock import MagicMock
    conn = MagicMock()
    conn.info.transaction_status = 0      # TRANSACTION_STATUS_IDLE, so the ping passes
    conn.closed = 0
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = (1,)
    cur.fetchall.return_value = []
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool


def no_database(stack):
    """Close the driver boundary for the life of `stack`.

    Separate from isolate_services because a test class that patches its own
    helpers still needs this: test_stats_cache patched the six helpers it counts
    and left robot_league — reached through _build_payload — to open a real
    connection on every run.
    """
    from utilities.postgres_utils import connection
    stack.enter_context(patch.object(connection, '_get_pool', return_value=offline_pool()))


def isolate_services(stack):
    no_database(stack)
    from utilities import logging_utils
    for name in ('LOGGING_ENABLED', 'LOG_TO_FILE', 'LOG_TO_CONSOLE'):
        stack.enter_context(patch.object(logging_utils, name, False))
    stack.enter_context(patch('utilities.logging_utils._start_new_log_file'))
    stack.enter_context(patch('utilities.logging_utils._finalize_current_log_file'))
    stack.enter_context(patch('utilities.logging_utils.queue_db_operation'))
    stack.enter_context(patch('utilities.postgres_utils.create_hand_with_player', return_value=True))
    stack.enter_context(patch('utilities.postgres_utils.finalize_hand', return_value=True))
    stack.enter_context(patch('utilities.postgres_utils.save_user_difficulty', return_value=True))
    stack.enter_context(patch('utilities.gmail_utils.send_email', side_effect=AssertionError('No email in tests')))
