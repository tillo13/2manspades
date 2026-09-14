"""A cron waits out a busy pool; a page request still fails fast.

2026-09-14 19:01 UTC: cron_andybot raised PoolError mid-game because another
project was running heavy reads on the shared instance and the two-slot pool
was held by stats queries sitting at the 30s statement timeout. Same thing on
2026-09-10. Transient, and the tick has an hour before the next one.
"""
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import psycopg2.pool

from tests.support import offline_pool
from utilities.postgres_utils import connection


class PatienceTests(unittest.TestCase):
    def setUp(self):
        self.stack_out = redirect_stdout(StringIO()); self.stack_out.__enter__()
        self.addCleanup(self.stack_out.__exit__, None, None, None)
        self.sleeps = []
        self.addCleanup(lambda: setattr(connection, '_slots', threading.BoundedSemaphore(2)))

    def busy_pool(self, free_after_sleeps):
        """Both slots taken; a slot frees up after N sleeps (0 = never)."""
        connection._slots = threading.BoundedSemaphore(2)
        connection._slots.acquire(); connection._slots.acquire()

        def sleep(secs):
            self.sleeps.append(secs)
            if len(self.sleeps) == free_after_sleeps:
                connection._slots.release()
        self.stack = patch.multiple(connection, time=type('T', (), {'sleep': staticmethod(sleep)}),
                                    _get_pool=lambda: offline_pool())
        self.stack.start(); self.addCleanup(self.stack.stop)
        # the first acquire(timeout=10) must fail immediately, not hang the suite
        real = connection._slots.acquire
        patch.object(connection._slots.__class__, 'acquire', lambda self_, timeout=None: real(blocking=False)).start()
        self.addCleanup(patch.stopall)

    def test_page_request_fails_fast(self):
        self.busy_pool(free_after_sleeps=1)
        with self.assertRaises(psycopg2.pool.PoolError):
            connection.get_db_connection()
        self.assertEqual(self.sleeps, [], 'a page request must not wait')

    def test_cron_waits_and_gets_a_slot(self):
        self.busy_pool(free_after_sleeps=2)
        with connection.patient_pool():
            conn = connection.get_db_connection()
        self.assertIsNotNone(conn)
        self.assertEqual(self.sleeps, [2, 5], 'two waits, then the slot came free')
        connection.return_db_connection(conn)

    def test_cron_gives_up_after_the_last_wait(self):
        self.busy_pool(free_after_sleeps=0)
        with connection.patient_pool():
            with self.assertRaises(psycopg2.pool.PoolError):
                connection.get_db_connection()
        self.assertEqual(self.sleeps, [2, 5, 10], 'every wait used before the error is raised')

    def test_policy_is_scoped_to_the_block(self):
        with connection.patient_pool(waits=(1,)):
            self.assertEqual(connection._patient.waits, (1,))
            with connection.patient_pool(waits=(3, 3)):
                self.assertEqual(connection._patient.waits, (3, 3))
            self.assertEqual(connection._patient.waits, (1,))
        self.assertIsNone(connection._patient.waits)


if __name__ == '__main__':
    unittest.main()
