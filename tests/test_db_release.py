"""Every DB helper must hand its pooled connection back on the failure path too.

The pool is 2 connections behind a 2-slot checkout gate; one leaked slot per
failed call would wedge the whole app after two failures."""
from contextlib import ExitStack, redirect_stdout
import json
from io import StringIO
import threading
import unittest
from unittest.mock import patch, MagicMock

from tests.support import load_app, isolate_services

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

    def test_new_game_never_waits_on_the_bid_bias_query(self):
        """POST /new_game must not run get_player_bid_bias. It reads every trick the player
        has ever played — 4.1s mean, 21.6s worst in production — and on 2026-09-08 it sat on
        the request path and made Play Again take 11 seconds, holding one of the app's two
        connections long enough to freeze /my_record and /jukebox/stats alongside it."""
        import app as A
        from utilities.postgres_utils import records
        with ExitStack() as st:
            st.enter_context(redirect_stdout(StringIO()))
            isolate_services(st)
            st.enter_context(patch.object(A, 'IS_PRODUCTION', True))
            st.enter_context(patch.object(A, '_ratchet_identity',
                                          return_value={'email': 'a@b.c', 'name': None, 'ip': None}))
            # `_with_opp_model` imports from the package at call time, so the package
            # attribute is the only name that patching actually intercepts.
            slow = st.enter_context(patch.object(db, 'get_player_bid_bias', return_value=0.5))
            records._BIAS_CACHE.clear()
            records._BIAS_PENDING.clear()
            client = A.app.test_client()
            self.assertEqual(client.post('/new_game', json={}).status_code, 200)
            slow.assert_not_called()

    def test_par_solver_holds_no_connection_while_solving(self):
        """fill_par must give the connection back before it starts solving. The solver is pure
        CPU for tens of seconds; holding one of two connections across it starved whoever was
        playing during the every-15-minutes cron tick."""
        from utilities.postgres_utils import par
        import utilities.marta_mind as mm
        hand = [f'{r}♣' for r in ('2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q')]
        other = [f'{r}♥' for r in ('2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q')]
        row = {'hand_id': 'h1', 'hand_number': 1, 'p_cards': json.dumps(hand),
               'c_cards': json.dumps(other), 'p_out': hand[0], 'c_out': other[0],
               'first_leader': 'player'}

        connection._slots = threading.BoundedSemaphore(2)
        free_while_solving = []
        pool, conn = fake_pool(fail_after_ping=False)
        with ExitStack() as st:
            st.enter_context(redirect_stdout(StringIO()))
            st.enter_context(patch.object(connection, '_get_pool', return_value=pool))
            st.enter_context(patch.object(par, '_unsolved', return_value=[row]))
            st.enter_context(patch.object(par, '_ensure_table'))
            st.enter_context(patch.object(mm, '_count',
                                          side_effect=lambda *a, **k: (
                                              free_while_solving.append(connection._slots._value), 4)[1]))
            st.enter_context(patch('psycopg2.extras.execute_values'))
            self.assertEqual(par.fill_par(limit=10), 1)

        self.assertEqual(free_while_solving, [2],
                         'fill_par was still holding a pooled connection while the solver ran')
        self.assertEqual(connection._slots._value, 2, 'fill_par leaked a slot')

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
