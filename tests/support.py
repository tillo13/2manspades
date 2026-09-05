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


def isolate_services(stack):
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
