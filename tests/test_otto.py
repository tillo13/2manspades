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


class RatchetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)
        self.stack.enter_context(patch.object(A, 'save_user_difficulty', return_value=True))
        self.stack.enter_context(patch('utilities.postgres_utils.save_user_strength', return_value=True))
        self.client = A.app.test_client()

    def test_ratchet_math(self):
        from utilities.computer_logic import ratchet, level_name, strength_of
        self.assertEqual(ratchet(50, True, 10), 55)
        self.assertEqual(ratchet(50, True, 300), 65)
        self.assertEqual(ratchet(50, False, 120), 41)
        self.assertEqual(ratchet(2, False, 400), 0)
        self.assertEqual(ratchet('ruthless', True, 50), 100)
        self.assertEqual([level_name(s) for s in (0, 14, 15, 44, 45, 79, 80, 100)],
                         ['easy', 'easy', 'medium', 'medium', 'hard', 'hard', 'ruthless', 'ruthless'])
        self.assertEqual(strength_of('hard'), 60)
        self.assertEqual(strength_of(73), 73)

    def _finish_game(self, email, games, winner='player'):
        self.assertEqual(self.client.get('/?new=true').status_code, 200)   # fresh game each case
        record = {'easy': {'wins': games, 'losses': 0}}
        with self.client.session_transaction() as s:
            if email:
                s['user'] = {'email': email, 'google_id': 'x', 'name': 'Tom Tillo'}
            else:
                s.pop('user', None)
            s['difficulty'] = 60
            g = s['game']
            g.update(game_over=True, winner=winner, trick_completed=True, trick_winner='player',
                     player_hand=[{'rank': '2', 'suit': '♣', 'value': 2}], computer_hand=[],
                     player_score=310, computer_score=200, player_bags=0, computer_bags=0, message='GAME OVER!')
            s.modified = True
        with patch('utilities.postgres_utils.get_user_level_record', return_value=record):
            self.assertEqual(self.client.post('/clear_trick').status_code, 200)
        with self.client.session_transaction() as s:
            return s['game'].get('message', ''), s.get('difficulty')

    def test_ratchet_moves_for_veterans_only(self):
        msg, setting = self._finish_game('tom@example.com', 40)
        self.assertIn('Marta climbs to 69/100 (Hard)', msg)
        self.assertEqual(setting, 69)
        msg, setting = self._finish_game('new@example.com', 3)
        self.assertNotIn('Marta', msg)
        self.assertEqual(setting, 60)
        msg, setting = self._finish_game(None, 100)
        self.assertNotIn('climbs', msg)
        msg, setting = self._finish_game('tom@example.com', 40, winner='computer')
        self.assertIn('Marta drops to 51/100 (Hard)', msg)

    def test_gear_reports_strength_and_ratchet(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.client.post('/set_difficulty', json={'difficulty': 'hard'})
        d = self.client.get('/get_difficulty').get_json()
        self.assertEqual((d['difficulty'], d['strength'], d['ratchet']['needed']), ('hard', 60, 25))

if __name__ == '__main__':
    unittest.main()
