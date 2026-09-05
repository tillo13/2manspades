"""Every DB helper must hand its pooled connection back on the failure path too.

The pool is 2 connections behind a 2-slot checkout gate; one leaked slot per
failed call would wedge the whole app after two failures."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import threading
import unittest
from unittest.mock import patch, MagicMock

from tests.support import load_app

load_app()
from utilities.postgres_utils import connection
from utilities import postgres_utils as db
from utilities import session_helpers, jukebox


def fake_pool(fail_after_ping=True):
    """A pool whose connections answer the SELECT 1 ping and then blow up."""
    conn = MagicMock()
    conn.info.transaction_status = 0
    conn.closed = 0
    calls = []

    def execute(sql, *args):
        calls.append(sql)
        if fail_after_ping and sql != 'SELECT 1':
            raise RuntimeError('simulated statement timeout')

    conn.cursor.return_value.execute.side_effect = execute
    conn.cursor.return_value.__enter__.return_value = conn.cursor.return_value
    conn.cursor.return_value.fetchone.return_value = (1,)
    conn.cursor.return_value.fetchall.return_value = []
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn


HELPERS = [
    (db.get_fun_stats, ()), (db.get_overall_game_stats, ()), (db.get_special_card_stats, ()),
    (db.get_player_achievements, ()), (db.get_per_hand_stats, ()),
    (db.get_game_details, ('h1',)), (db.get_player_games, ('Andy',)),
    (db.get_monthly_stats_by_location, ()), (db.get_suspected_player_from_ip, ('1.2.3.4',)),
    (db.get_user_difficulty, ('a@b.c',)), (db.save_user_difficulty, ('a@b.c', 'easy')),
    (db.upsert_player, ('1.2.3.4', 'ua')), (db.get_ip_address_game_stats, ('1.2.3.4',)),
    (db.save_ip_location_data, ('1.2.3.4', {'city': 'x'})), (db.save_failed_ip_lookup, ('1.2.3.4',)),
    (db.get_player_city_membership, ('1.2.3.4',)), (db.get_unified_leaderboard, ()),
    (db.get_competitive_leaders_stats, ()), (db.get_city_leaders_stats, ()),
    (db.insert_hand, ({'hand_id': 'h1'},)), (db.log_game_event_to_db, ('h1', 'e', {})),
    (db.finalize_hand, ('h1', {})), (db.batch_log_events, ('h1', [{'event_type': 'e', 'event_data': {}}])),
    (db.create_hand_with_player, ({'hand_id': 'h1'}, {'ip_address': '1.2.3.4'})),
    (jukebox.jukebox_stats, ()), (jukebox.record_play_event, ({'play_id': 'p', 'album_id': 'a', 'track_n': 1},)),
    (session_helpers._check_and_perform_ip_geolocation, ('1.2.3.4',)),
]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        self.stack.enter_context(patch.object(session_helpers, '_perform_ip_geolocation_lookup', return_value=False))

    def run_helper(self, helper, args, fail):
        connection._slots = threading.BoundedSemaphore(2)
        pool, conn = fake_pool(fail_after_ping=fail)
        with patch.object(connection, '_get_pool', return_value=pool):
            try:
                helper(*args)
            except Exception:
                pass
        return pool, conn

    def assert_slots_free(self, helper, mode):
        self.assertEqual(connection._slots._value, 2,
                         f'{helper.__name__} leaked a checkout slot on the {mode} path')

    def test_failure_path_releases_every_helper(self):
        for helper, args in HELPERS:
            with self.subTest(helper=helper.__name__):
                self.run_helper(helper, args, fail=True)
                self.assert_slots_free(helper, 'failure')

    def test_success_path_releases_every_helper(self):
        for helper, args in HELPERS:
            with self.subTest(helper=helper.__name__):
                pool, conn = self.run_helper(helper, args, fail=False)
                self.assert_slots_free(helper, 'success')
                conn.close.assert_not_called()

    def test_double_return_is_harmless(self):
        connection._slots = threading.BoundedSemaphore(2)
        pool, conn = fake_pool(fail_after_ping=False)
        with patch.object(connection, '_get_pool', return_value=pool):
            c = connection.get_db_connection()
            connection.return_db_connection(c)
            connection.return_db_connection(c)
        self.assertEqual(connection._slots._value, 2)
        self.assertEqual(pool.putconn.call_count, 1)


if __name__ == '__main__':
    unittest.main()
