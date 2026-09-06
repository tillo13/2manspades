"""Exercise real HTTP game flows and auth boundaries without network access."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import random
import unittest
from unittest.mock import patch, Mock

from tests.support import load_app, isolate_services

A = load_app()


class GameTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)
        self.stack.enter_context(patch.object(A, 'send_simple_email'))
        self.stack.enter_context(patch.object(A, 'save_user_difficulty', return_value=True))
        random.seed(1234)
        self.client = A.app.test_client()

    def start(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def post(self, path, **data):
        response = self.client.post(path, json=data)
        self.assertEqual(response.status_code, 200, (path, response.get_data(as_text=True)))
        return response.get_json()

    def finish_hand(self):
        from utilities.gameplay_logic import is_valid_play
        for _ in range(25):
            with self.client.session_transaction() as session:
                game = session['game']
                if game['hand_over']:
                    self.assertEqual(game['player_tricks'] + game['computer_tricks'], 10)
                    return
                completed = game.get('trick_completed')
                if not completed:
                    index = next(i for i, card in enumerate(game['player_hand'])
                                 if is_valid_play(card, game['player_hand'], game['current_trick'], game['spades_broken']))
            if completed:
                self.post('/clear_trick')
            else:
                self.post('/play', index=index)
        self.fail('Hand did not complete')

    def test_full_hand_and_next_hand(self):
        self.start()
        self.post('/discard', index=0)
        self.post('/bid', bid=4)
        self.finish_hand()
        self.post('/next_hand')
        state = self.client.get('/state').get_json()
        self.assertEqual(state['hand_number'], 2)
        self.assertEqual(len(state['player_hand']), 11)
        self.assertNotIn('computer_hand', state)

    def test_nil_and_blind_hand(self):
        for blind in (False, True):
            with self.subTest(blind=blind):
                self.post('/new_game')
                if blind:
                    with self.client.session_transaction() as session:
                        session['game']['phase'] = 'blind_decision'
                        session['game']['computer_score'] = 150
                        session.modified = True
                    self.post('/choose_blind_bidding')
                    self.post('/blind_bid', bid=5)
                    self.post('/discard', index=0)
                else:
                    self.post('/discard', index=0)
                    self.post('/bid', bid=0)
                self.finish_hand()

    def test_routes_and_debug_boundaries(self):
        self.assertEqual(self.client.get('/health').get_json()['status'], 'ok')
        for route in ('/debug_async_logging', '/debug_game_creation'):
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.get('/instructions').status_code, 200)
        self.assertEqual(self.client.post('/play', json={'index': 0}).status_code, 400)

    def test_invalid_moves_do_not_change_hand(self):
        self.start()
        for value in (-1, 99, None, '0', True, [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.client.post('/discard', json={'index': value}).status_code, 400)
        state = self.client.get('/state').get_json()
        self.assertEqual(len(state['player_hand']), 11)
        self.assertEqual(state['phase'], 'discard')

    def test_chat_uses_router_and_retry_contract(self):
        self.start()
        with patch('utilities.marta_chat.get_smart_marta_response', return_value='Your lead.'):
            self.assertEqual(self.post('/chat_response', message='Hello')['response'], 'Your lead.')
        with patch('utilities.marta_chat.get_smart_marta_response', return_value='__RETRY__'):
            self.assertTrue(self.post('/chat_response', message='Song?')['retry'])

    def test_audio_auth_and_range(self):
        from utilities.jukebox import playlist
        album = playlist()['albums'][0]
        url = f"/jukebox/audio/{album['id']}/{album['tracks'][0]['n']}"
        self.assertEqual(self.client.get(url).status_code, 401)
        with self.client.session_transaction() as session:
            session['user'] = {'email': 'player@example.test', 'name': 'Test Player'}
        blob = Mock(size=100)
        blob.download_as_bytes.return_value = b'0123456789'
        with patch('utilities.jukebox._bucket') as bucket:
            bucket.return_value.get_blob.return_value = blob
            response = self.client.get(url, headers={'Range': 'bytes=0-9'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.headers['Content-Range'], 'bytes 0-9/100')
            self.assertEqual(self.client.get(url, headers={'Range': 'bytes=101-'}).status_code, 416)

    def test_login_survives_new_game(self):
        self.start()
        with self.client.session_transaction() as session:
            session['user'] = {'email': 'player@example.test', 'name': 'Test Player', 'picture': ''}
            session.permanent = True
        self.post('/new_game')
        self.client.get('/?new=true')
        with self.client.session_transaction() as session:
            self.assertEqual(session['user']['email'], 'player@example.test')
            self.assertTrue(session.permanent)


if __name__ == '__main__':
    unittest.main()


class MartaReplyShapeTests(unittest.TestCase):
    def test_clipped_reply_is_cut_at_last_sentence(self):
        from utilities.marta_chat import _finish_sentence
        clipped = ("Della and the Dealer is one of Hoyt's story-songs about a hustler. That's not a bluff, sugar, "
                   "that's a funeral. Ten tricks to two, and I didn't even have to")
        self.assertTrue(_finish_sentence(clipped).endswith("that's a funeral."))
        self.assertEqual(_finish_sentence("Your lead."), "Your lead.")
        self.assertEqual(_finish_sentence("Nice hand, I guess"), "Nice hand, I guess")
