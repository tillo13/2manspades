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
        with patch('utilities.otto.play_cron_tick', return_value={'target_today': 42, 'played_now': 3,
                                                                    'games': []}) as tick:
            r = client.get('/cron/otto', headers={'X-Appengine-Cron': 'true'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['target_today'], 42)
        tick.assert_called_once_with()

    def test_daily_quota_is_fixed_per_day_and_spread(self):
        import datetime
        from utilities.otto import daily_target, games_due
        d = datetime.date(2026, 9, 6)
        t = daily_target(d)
        self.assertEqual(t, daily_target(d))
        self.assertTrue(1 <= t <= 100)
        self.assertNotEqual(sorted({daily_target(datetime.date(2026, 9, i)) for i in range(1, 30)}), [t])
        noon = datetime.datetime(2026, 9, 6, 12, 0)
        self.assertEqual(games_due(100, 50, noon), 0)      # on pace
        self.assertEqual(games_due(100, 40, noon), 2)      # behind: catch up two at a time
        self.assertEqual(games_due(1, 1, noon), 0)         # quota done
        self.assertEqual(games_due(4, 0, datetime.datetime(2026, 9, 6, 23, 59)), 2)



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

    def test_short_specials_go_to_the_middle_as_she_climbs(self):
        from utilities.computer_logic import computer_discard_strategy, get_difficulty_params
        card = lambda r, su: {'rank': r, 'suit': su, 'value': {'J': 11, 'Q': 12, 'K': 13, 'A': 14}.get(r, int(r) if r.isdigit() else 0)}
        # 7♦ with one companion, 10♣ with two, a singleton 4♥ to tempt the void score
        hand = [card('7', '♦'), card('K', '♦'), card('10', '♣'), card('J', '♣'), card('Q', '♣'), card('4', '♥'),
                card('2', '♠'), card('5', '♠'), card('9', '♠'), card('J', '♠'), card('A', '♠')]
        pick = lambda d: hand[computer_discard_strategy(list(hand), {'difficulty': d})]
        self.assertEqual(get_difficulty_params('easy')['special_hold'], 1)
        self.assertEqual(pick('easy'), card('4', '♥'))            # pre-dial: any companion protects
        self.assertEqual(pick('medium'), card('7', '♦'))          # doubleton special is tossed
        self.assertEqual(pick(100), card('7', '♦'))               # first toss candidate wins the tie
        self.assertEqual(pick({'special_hold': 3}), card('7', '♦'))
        hand.remove(card('7', '♦')); hand.append(card('8', '♦'))
        self.assertEqual(pick('hard'), card('10', '♣'))           # hard (2.2) still calls two companions short
        self.assertEqual(pick('medium'), card('4', '♥'))          # medium (1.6) keeps it
        # Canary: a singleton special is tossed on every rung, as before
        lone = [card('7', '♦'), card('K', '♣'), card('Q', '♣'), card('J', '♣'), card('9', '♥'), card('8', '♥'),
                card('2', '♠'), card('5', '♠'), card('9', '♠'), card('J', '♠'), card('A', '♠')]
        for d in ('easy', 'ruthless'):
            self.assertEqual(lone[computer_discard_strategy(list(lone), {'difficulty': d})], card('7', '♦'), d)

    def test_table_memory_scales_with_the_dial(self):
        from utilities.computer_logic import table_memory
        from utilities.otto import _mirror
        c = lambda r, su: {'rank': r, 'suit': su, 'value': 0}
        hand = [c('A', '♥'), c('3', '♠')]
        game = {'first_leader': 'computer', 'player_discarded': c('7', '♦'), 'computer_discarded': c('2', '♣'),
                'trick_history': [
                    {'number': 1, 'player_card': c('4', '♠'), 'computer_card': c('6', '♣'), 'winner': 'player'},
                    {'number': 2, 'player_card': c('10', '♣'), 'computer_card': c('9', '♣'), 'winner': 'player'},
                    {'number': 3, 'player_card': c('5', '♦'), 'computer_card': c('K', '♦'), 'winner': 'computer'}],
                'current_trick': [{'player': 'player', 'card': c('Q', '♠')}]}
        full = table_memory(hand, dict(game, difficulty='ruthless'))
        self.assertEqual(full['specials_out'], [])
        self.assertEqual(full['opp_void'], {'♣'})        # trick 1: she led a club, he spaded it
        self.assertEqual(full['opp_spades'], 2)          # the 4♠ then, the Q♠ on the table now
        self.assertIn('K♦', full['seen'])
        none = table_memory(hand, dict(game, difficulty='easy'))
        self.assertEqual(none['specials_out'], ['7♦', '10♣'])
        self.assertEqual(none['opp_void'], set())
        self.assertEqual(none['seen'], {'A♥', '3♠', 'Q♠'})  # her hand and the table, nothing spent
        self.assertEqual(none['opp_spades'], 1)
        # From Otto's seat the same table reads the other way round
        otto = table_memory([c('2', '♦')], _mirror(dict(game, current_trick=[]), 'ruthless'))
        self.assertEqual(otto['opp_void'], set())         # Marta followed every lead Otto made
        self.assertEqual(otto['opp_spades'], 0)
        self.assertEqual(otto['specials_out'], [])

    def test_levels_round_trip_through_routes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        for level in ('medium', 'hard', 'ruthless', 'easy'):
            r = self.client.post('/set_difficulty', json={'difficulty': level})
            self.assertEqual(r.status_code, 200, level)
            self.assertEqual(self.client.get('/get_difficulty').get_json()['difficulty'], level)
        self.assertEqual(self.client.post('/set_difficulty', json={'difficulty': 'legend'}).status_code, 400)
        # the slider posts a number; the rung name follows from it
        for strength, rung in ((0, 'easy'), (14, 'easy'), (15, 'medium'), (55, 'hard'), (100, 'ruthless')):
            r = self.client.post('/set_difficulty', json={'strength': strength})
            self.assertEqual((r.status_code, r.get_json()['difficulty'], r.get_json()['strength']), (200, rung, strength))
            self.assertEqual(self.client.get('/get_difficulty').get_json()['strength'], strength)
        for bad in (-1, 101, 'lots', None):
            self.assertEqual(self.client.post('/set_difficulty', json={'strength': bad}).status_code, 400, bad)
        levels = self.client.get('/get_difficulty').get_json()['levels']
        self.assertEqual([l['level'] for l in levels], ['easy', 'medium', 'hard', 'ruthless'])
        self.assertEqual([(l['floor'], l['preset']) for l in levels], [(0, 0), (15, 30), (45, 60), (80, 100)])
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
            return s['game'].get('ratchet'), s.get('difficulty')

    def test_ratchet_moves_for_veterans_only(self):
        r, setting = self._finish_game('tom@example.com', 40)
        self.assertEqual(r, {'before': 60, 'after': 69, 'from_level': 'hard', 'level': 'hard'})
        self.assertEqual(setting, 69)
        r, setting = self._finish_game('new@example.com', 3)
        self.assertIsNone(r)
        self.assertEqual(setting, 60)
        r, setting = self._finish_game(None, 100)
        self.assertIsNone(r)
        r, setting = self._finish_game('tom@example.com', 40, winner='computer')
        self.assertEqual((r['after'], r['level']), (51, 'hard'))
        # the state payload carries it as data; the message stays the plain result sentence
        state = self.client.get('/state').get_json()
        self.assertEqual(state['ratchet']['after'], 51)
        self.assertNotIn('Marta drops', state['message'])

    def test_ip_known_family_member_ratchets_without_login(self):
        # Jon has never logged in; his IP is known to the family map, so he rides the ratchet too
        with patch.object(A, 'IS_PRODUCTION', True), \
             patch.object(A, 'get_suspected_player_from_ip', return_value='Jon') as who, \
             patch('utilities.postgres_utils.save_user_strength', return_value=True) as save, \
             patch('utilities.postgres_utils.get_user_strength', return_value=35):
            self.assertEqual(self.client.get('/?new=true').status_code, 200)
            with self.client.session_transaction() as s:
                self.assertEqual(s['difficulty'], 35)         # picked up from his IP row
            r, setting = self._finish_game(None, 45)
            self.assertEqual((r['before'], r['after']), (60, 69))
            self.assertEqual(setting, 69)
            save.assert_called_with(None, 69, '127.0.0.1')
            self.assertTrue(who.called)
            with patch('utilities.postgres_utils.get_user_level_record', return_value={'easy': {'wins': 45, 'losses': 0}}) as rec:
                d = self.client.get('/get_difficulty').get_json()
                rec.assert_called_with(None, 'Jon')
            self.assertEqual((d['ratchet']['eligible'], d['ratchet']['logged_in'], d['player']), (True, False, None))
        # A stranger's IP still gets nothing
        with patch.object(A, 'IS_PRODUCTION', True), patch.object(A, 'get_suspected_player_from_ip', return_value=None):
            self.assertIsNone(self._finish_game(None, 100)[0])

    def test_gear_reports_strength_and_ratchet(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.client.post('/set_difficulty', json={'difficulty': 'hard'})
        d = self.client.get('/get_difficulty').get_json()
        self.assertEqual((d['difficulty'], d['strength'], d['ratchet']['needed']), ('hard', 60, 25))



class PersonaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)

    def test_persona_game_rides_the_human_logging_path(self):
        from utilities import logging_utils, otto
        from utilities.otto import play_game, ANDY
        flagged = []
        with patch('utilities.postgres_utils.create_hand_with_player', return_value=True) as create, \
             patch.object(otto, '_open_persona_hand', side_effect=lambda g, p: (create(g, g['client_info']), flagged.append(g['current_hand_id']))), \
             patch.object(logging_utils, 'IS_PRODUCTION', True), \
             patch.object(logging_utils, 'LOGGING_ENABLED', True), \
             patch.object(logging_utils, 'queue_db_operation') as q:
            r = play_game(seed=11, otto_difficulty=ANDY['params'], marta_difficulty=30, persona=ANDY)
        self.assertEqual(len(flagged), r['hands'])            # one hands row per hand, each flagged
        self.assertEqual(create.call_args[0][1]['google_auth']['email'], 'andy.tillo@gmail.com')
        joined = ' '.join(str(c.args[2]) for c in q.call_args_list if len(c.args) > 2 and isinstance(c.args[2], str))
        for needle in ('action_card_play', 'action_regular_bid', 'action_discard', 'trick_completed', 'game_completed'):
            self.assertIn(needle, joined, needle)

    def test_plain_bot_game_still_silent(self):
        from utilities import logging_utils
        from utilities.otto import play_game
        with patch.object(logging_utils, 'IS_PRODUCTION', True), patch.object(logging_utils, 'queue_db_operation') as q:
            play_game(seed=12)
        q.assert_not_called()

    def test_persona_plan_is_fixed_per_day_and_sparse(self):
        import datetime
        from utilities.otto import persona_plan
        days = [datetime.date(2026, 9, d) for d in range(1, 29)]
        plans = [persona_plan('andybot', d) for d in days]
        self.assertEqual(plans, [persona_plan('andybot', d) for d in days])
        playing = [p for p in plans if p]
        self.assertTrue(6 <= len(playing) <= 18)                 # ~3 days a week over 4 weeks
        self.assertTrue(all(1 <= len(p) <= 3 and all(9 <= h <= 21 for h in p) for p in playing))

    def test_cron_route_requires_header(self):
        client = A.app.test_client()
        self.assertEqual(client.get('/cron/andybot').status_code, 403)
        with patch('utilities.otto.play_persona_tick', return_value={'plan': [], 'played': False, 'reason': 'x'}):
            self.assertEqual(client.get('/cron/andybot', headers={'X-Appengine-Cron': 'true'}).status_code, 200)

if __name__ == '__main__':
    unittest.main()
