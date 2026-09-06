"""Otto plays a whole game through the real hand_flow with no database and no network."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from tests.support import load_app, isolate_services

A = load_app()


class OttoTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)

    def test_seeded_game_completes_and_is_replayable(self):
        from utilities.otto import play_game
        a = play_game(seed=42)
        b = play_game(seed=42)
        self.assertIn(a['winner'], ('otto', 'marta', 'tie'))
        self.assertGreaterEqual(a['hands'], 1)
        self.assertLess(a['hands'], 60)
        self.assertEqual((a['winner'], a['otto_score'], a['marta_score'], a['hands']),
                         (b['winner'], b['otto_score'], b['marta_score'], b['hands']))
        kinds = {(d['seat'], d['kind']) for d in a['decisions']}
        for seat in ('otto', 'marta'):
            for kind in ('bid', 'discard', 'lead', 'follow'):
                self.assertIn((seat, kind), kinds, f'{seat} never logged a {kind}')
        hands = [d for d in a['decisions'] if d['kind'] == 'hand']
        self.assertEqual(len(hands), a['hands'])
        for d in hands:
            self.assertEqual(d['otto_tricks'] + d['marta_tricks'], 10)
        plays = [d for d in a['decisions'] if d['kind'] in ('lead', 'follow')]
        self.assertTrue(plays and all('won' in d for d in plays))
        bids = [d for d in a['decisions'] if d['kind'] == 'bid']
        self.assertTrue(all(d['branch'] in ('nil', 'blind', 'regular') for d in bids))

    def test_bot_game_never_reaches_human_logging(self):
        from utilities import logging_utils
        from utilities.otto import play_game
        with patch.object(logging_utils, 'queue_db_operation') as q, \
             patch.object(logging_utils, 'IS_PRODUCTION', True):
            play_game(seed=7)
        q.assert_not_called()

    def test_batch_summary_shape(self):
        from utilities.otto import play_game, summarize
        s = summarize([play_game(seed=i) for i in range(3)])
        self.assertEqual(s['games'], 3)
        self.assertEqual(s['otto'] + s['marta'] + s['tie'], 3)
        self.assertEqual({x['seat'] for x in s['seats']}, {'Otto', 'Marta'})

    def test_cron_route_requires_appengine_header(self):
        client = A.app.test_client()
        self.assertEqual(client.get('/cron/otto').status_code, 403)
        with patch('utilities.otto.play_game', return_value={
                'winner': 'otto', 'hands': 8, 'otto_score': 301, 'marta_score': 240,
                'decision_count': 150, 'ms': 90}) as pg:
            r = client.get('/cron/otto', headers={'X-Appengine-Cron': 'true'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['winner'], 'otto')
        pg.assert_called_once_with(persist=True, source='cron')



class LadderTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)
        self.stack.enter_context(patch.object(A, 'save_user_difficulty', return_value=True))
        self.client = A.app.test_client()

    def test_easy_is_pinned_and_rungs_climb(self):
        from utilities.computer_logic import get_difficulty_params, _EASY, DIFFICULTY_LEVELS, STRENGTH_PRESETS
        self.assertEqual(get_difficulty_params('easy'), _EASY)
        self.assertEqual(get_difficulty_params(0), _EASY)
        self.assertEqual(get_difficulty_params('nonsense'), _EASY)
        offsets = [get_difficulty_params(l)['bid_offset'] for l in DIFFICULTY_LEVELS]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(get_difficulty_params({'bid_offset': 0.5})['bid_offset'], 0.5)
        self.assertEqual(list(STRENGTH_PRESETS), list(DIFFICULTY_LEVELS))

    def test_levels_round_trip_through_routes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        for level in ('medium', 'hard', 'ruthless', 'easy'):
            r = self.client.post('/set_difficulty', json={'difficulty': level})
            self.assertEqual(r.status_code, 200, level)
            self.assertEqual(self.client.get('/get_difficulty').get_json()['difficulty'], level)
        self.assertEqual(self.client.post('/set_difficulty', json={'difficulty': 'legend'}).status_code, 400)
        levels = self.client.get('/get_difficulty').get_json()['levels']
        self.assertEqual([l['level'] for l in levels], ['easy', 'medium', 'hard', 'ruthless'])
        self.assertTrue(all(l['blurb'] for l in levels))
if __name__ == '__main__':
    unittest.main()
