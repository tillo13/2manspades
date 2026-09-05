"""/stats must hit the DB helpers once per minute, not once per page view."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from tests.support import load_app

A = load_app()
from utilities.postgres_utils import stats as S

HELPERS = ('get_unified_leaderboard', 'get_fun_stats', 'get_player_achievements',
           'get_special_card_stats', 'get_overall_game_stats', 'get_per_hand_stats')


class StatsCacheTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        self.calls = {}
        for name in HELPERS:
            self.calls[name] = self.stack.enter_context(patch.object(S, name, return_value={} if 'leaderboard' not in name else []))
        self.calls['jukebox_stats'] = self.stack.enter_context(patch('utilities.jukebox.jukebox_stats', return_value={}))
        S._PAYLOAD.update(data=None, ts=0.0)
        self.client = A.app.test_client()

    def total_calls(self):
        return sum(m.call_count for m in self.calls.values())

    def test_second_view_within_ttl_makes_no_db_calls(self):
        self.assertEqual(self.client.get('/stats').status_code, 200)
        self.assertEqual(self.total_calls(), len(self.calls), 'every helper exactly once on a cold load')
        self.client.get('/stats')
        self.client.get('/stats')
        self.assertEqual(self.total_calls(), len(self.calls), 'warm views must not touch the DB')

    def test_expired_cache_recomputes(self):
        self.client.get('/stats')
        S._PAYLOAD['ts'] -= S._PAYLOAD_TTL + 1
        self.client.get('/stats')
        self.assertEqual(self.total_calls(), 2 * len(self.calls))


if __name__ == '__main__':
    unittest.main()
