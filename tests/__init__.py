"""Regression tests: venv_2man/bin/python -m unittest discover -s tests.

Nothing in this suite may open a real database connection. unittest imports this
package before it discovers any test module, so it is the one place a guard is
guaranteed to be installed before `import app` caches anything.

Why it exists: support.py stubs Secret Manager only around `import app`, so the
MagicMock credentials it produced were cached and then handed to a real
psycopg2.connect against the loopback Cloud SQL Auth Proxy. 34 connections per
run reached the shared instance, every one swallowed by a route's except clause,
so the suite reported OK while filling the engine log with `FATAL: password
authentication failed for user "<MagicMock ...>"` — over 1,000 in the 24h to
2026-09-09, the largest single error signature on an instance 20+ apps share.

Two deliberate choices. The guard raises a BaseException subclass, because a
plain Exception is exactly what the routes already swallow and a catchable guard
is an invisible one. And it blocks psycopg2 rather than every socket (the
pytest-socket approach) because google-api-core and gRPC legitimately open
sockets while this app imports; the database is the boundary that must never be
crossed, not the network.
"""
import psycopg2


class RealDatabaseConnectionAttempted(BaseException):
    """Not an Exception on purpose — see the module docstring."""


def _blocked(*args, **kwargs):
    raise RealDatabaseConnectionAttempted(
        'a test tried to open a real database connection. Patch '
        'utilities.postgres_utils.connection._get_pool — tests.support.'
        'isolate_services already does — instead of letting the driver dial out.')


psycopg2.connect = _blocked
