"""The whole game rides in the session cookie, and a browser silently drops a Set-Cookie over
4,093 bytes. 2026-09-17: on hand 33 of one game the cookie reached 4,105 bytes, the phone kept the
previous one, and the game sat on a finished trick with every card greyed out. The cookie must
stay the same size however long a game runs, and an oversize one must be an error, never a drop."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import base64
import os
import random
import unittest
from unittest.mock import patch

from tests.support import load_app, isolate_services

A = load_app()
LIMIT = A.app.config['MAX_COOKIE_SIZE']
# What production adds that this suite can't: the Secure attribute, an IPv6 address, Marta's opponent
# model and peek, the ratchet on the final screen. As of 2026-09-17 those came to ~110-260 bytes (the
# old uncapped hand log with them added measured 4,101 at hand 33 against 4,105 logged in production).
HEADROOM = 400
HANDS = 45


def session_cookie_size(response):
    return max((len(h) for h in response.headers.getlist('Set-Cookie') if h.startswith('session=')), default=0)


class LongGameCookieTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)
        self.stack.enter_context(patch.object(A, 'send_simple_email'))
        self.stack.enter_context(patch.object(A, 'save_user_difficulty', return_value=True))
        self.stack.enter_context(patch('utilities.hand_flow.check_game_over', return_value=False))
        self.client = A.app.test_client()

    def play_long_game(self, seed, until=lambda g: g['hand_over'] and g['hand_number'] == HANDS):
        """Peak cookie size per hand, playing varied hands as a logged-in player until `until(game)`.
        The game is never allowed to end (random bids reach the mercy rule by hand 39)."""
        from utilities.gameplay_logic import is_valid_play
        rng = random.Random(seed)
        random.seed(seed)
        c = self.client
        c.get('/')
        with c.session_transaction() as s:
            s['user'] = {'email': 'player@example.test', 'name': 'Test Player', 'google_id': '1' * 21,
                         'picture': 'https://lh3.googleusercontent.com/a/ACg8ocJqT0vY3mXw9LbKzR4eNpH7sDfG2uCiAoV1tB6yWn8QjE5=s96-c'}
            s.permanent = True
        c.get('/?new=true')
        peaks, self.rows = {}, {}
        for _ in range(3000):
            with c.session_transaction() as s:
                g = s['game']
            if g['hand_over']:
                self.rows[g['hand_number']] = g['hand_log'][-1]
            if until(g):
                return peaks
            if g['hand_over']:
                path, body = '/next_hand', {}
            elif g.get('lay_down_offer'):
                path, body = '/lay_down', {'choice': rng.choice(['lay', 'play'])}
            elif g['phase'] == 'blind_decision':
                path, body = rng.choice(['/choose_normal_bidding', '/choose_blind_bidding']), {}
            elif g['phase'] == 'blind_bidding':
                path, body = '/blind_bid', {'bid': rng.choice([5, 6, 7])}
            elif g['phase'] == 'discard':
                path, body = '/discard', {'index': rng.randrange(len(g['player_hand']))}
            elif g['phase'] == 'bidding':
                path, body = '/bid', {'bid': rng.choice([0, 1, 2, 3, 3, 4, 4, 5, 6])}
            elif g.get('trick_completed'):
                path, body = '/clear_trick', {}
            else:
                legal = [i for i, card in enumerate(g['player_hand'])
                         if is_valid_play(card, g['player_hand'], g['current_trick'], g['spades_broken'])]
                path, body = '/play', {'index': rng.choice(legal)}
            response = c.post(path, json=body)
            self.assertEqual(response.status_code, 200, (path, response.get_data(as_text=True)))
            peaks[g['hand_number']] = max(peaks.get(g['hand_number'], 0), session_cookie_size(response))
        self.fail('the long game stalled')

    def test_cookie_does_not_grow_with_the_game(self):
        for seed in (3, 17):
            with self.subTest(seed=seed):
                peaks = self.play_long_game(seed)
                middle = max(peaks[h] for h in range(16, 31))
                late = max(peaks[h] for h in range(31, HANDS + 1))
                # as of 2026-09-17: capped, late minus middle ran -103 to +2 over five seeds; uncapped, +564 and +592
                self.assertLessEqual(late, middle + 150, f'hands 31-{HANDS} peaked at {late}, hands 16-30 at {middle}')
                self.assertLess(max(peaks.values()), LIMIT - HEADROOM, peaks)
                self.assert_tally_counts_every_hand(HANDS)

    def test_game_saved_before_the_cap_gets_unstuck(self):
        """The hung game: hand 33, 32 hands logged before the cap existed, a finished trick on the
        table. Its next save has to shrink it, since it can't finish a hand to get there."""
        from flask.sessions import SecureCookieSessionInterface
        with patch.object(A.app, 'session_interface', SecureCookieSessionInterface()):
            self.play_long_game(8, until=lambda g: g['hand_number'] == 33 and g.get('trick_completed'))
        with self.client.session_transaction() as s:
            self.assertEqual(len(s['game']['hand_log']), 32)
        response = self.client.post('/clear_trick', json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(0 < session_cookie_size(response) < LIMIT - HEADROOM)
        self.assertLess(len(self.client.get('/state').get_json()['current_trick']), 2)   # the trick left the table
        self.assert_tally_counts_every_hand(32)

    def assert_tally_counts_every_hand(self, hands):
        """The final screen's tiles, worked out the way game.js did before the log was capped."""
        from utilities.hand_flow import HAND_LOG_ROWS
        state = self.client.get('/state').get_json()
        self.assertEqual([h['hand'] for h in state['hand_log']], list(range(hands - HAND_LOG_ROWS + 1, hands + 1)))
        log = [self.rows[h] for h in sorted(self.rows)]
        self.assertEqual(len(log), hands)
        bid = [h for h in log if h['player_bid'] > 0]
        blinds = [h for h in log if h['player_blind']]
        self.assertEqual(state['hand_tally'], {
            'bids': len(bid),
            'made': sum(h['player_tricks'] >= h['player_bid'] for h in bid),
            'bags': sum(max(0, h['player_tricks'] - h['player_bid']) for h in bid),
            'blinds': len(blinds),
            'blinds_made': sum(h['player_tricks'] >= h['player_bid'] for h in blinds)})


class OversizeCookieTests(unittest.TestCase):
    def test_oversize_cookie_raises_and_alerts_once(self):
        from utilities.session_helpers import SessionCookieTooLarge
        junk = base64.b64encode(os.urandom(4000)).decode()      # random: compression can't rescue it
        with A.app.test_request_context('/clear_trick', method='POST'), \
                patch('utilities.error_alerts.record', return_value=(True, '')) as record, \
                patch('utilities.session_helpers.send_simple_email') as mail, \
                redirect_stdout(StringIO()):
            from flask import session
            session['junk'] = junk
            response = A.app.response_class()
            with self.assertRaises(SessionCookieTooLarge):
                A.app.session_interface.save_session(A.app, session, response)
        record.assert_called_once()
        mail.assert_called_once()
        self.assertIn('junk', mail.call_args.kwargs['body'])

    def test_normal_cookie_passes(self):
        with A.app.test_request_context('/'):
            from flask import session
            session['game'] = {'hand_number': 1}
            response = A.app.response_class()
            A.app.session_interface.save_session(A.app, session, response)
            self.assertTrue(0 < session_cookie_size(response) < LIMIT)


if __name__ == '__main__':
    unittest.main()
