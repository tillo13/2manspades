"""Offline routing tests: no credentials, model calls, or app startup."""
import unittest
from unittest.mock import Mock, patch

from utilities import marta_chat as marta


class MartaRoutingTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('builtins.print'))
        self.enterContext(patch.dict(marta._RESERVE_DISABLED, flag=False))
        self.free = self.enterContext(patch.object(marta, 'llm_chat_resilient'))
        self.reserve = self.enterContext(patch.object(marta, 'llm_chat_reserve'))
        self.free.return_value = ('Free reply.', 'free', [], None)
        self.reserve.return_value = ('Claude reply.', 'claude')
        self.order = Mock()
        self.order.attach_mock(self.free, 'free')
        self.order.attach_mock(self.reserve, 'reserve')
        self.chat = marta.MartaChat()
        self.chat.user_sub = 'test-user'
        self.chat._fallback_marta_response = Mock(return_value='Canned reply.')

    def test_free_success_never_calls_claude(self):
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Free reply.')
        self.reserve.assert_not_called()
        kwargs = self.free.call_args.kwargs
        self.assertEqual(kwargs['budget_ms'], 8000)
        self.assertFalse(kwargs['retry_on_5xx'])
        self.assertEqual(kwargs['app_name'], 'twomanspades')

    def test_empty_free_calls_reserve_second_with_same_context(self):
        self.free.return_value = ('  ', 'free', [], None)
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Claude reply.')
        self.assertEqual([c[0] for c in self.order.mock_calls], ['free', 'reserve'])
        for key in ('messages', 'system', 'max_tokens', 'temperature', 'app_name'):
            self.assertEqual(self.free.call_args.kwargs[key], self.reserve.call_args.kwargs[key])
        self.assertEqual(self.reserve.call_args.kwargs['auth_sub'], 'test-user')

    def test_free_error_still_calls_reserve(self):
        self.free.side_effect = marta.KumoriAPIError('timeout', status_code=504)
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Claude reply.')
        self.assertEqual([c[0] for c in self.order.mock_calls], ['free', 'reserve'])

    def test_both_fail_returns_canned_reply(self):
        self.free.side_effect = RuntimeError('offline')
        self.reserve.side_effect = RuntimeError('offline')
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Canned reply.')

    def test_both_empty_returns_canned_reply(self):
        self.free.return_value = (None, None, [], None)
        self.reserve.return_value = ('', None)
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Canned reply.')

    def test_music_failure_preserves_retry_sentinel(self):
        self.free.side_effect = RuntimeError('offline')
        self.reserve.side_effect = RuntimeError('offline')
        self.assertEqual(self.chat.get_marta_response('What song?', now_playing={'title': 'Test'}), '__RETRY__')

    def test_forbidden_reserve_is_not_retried_but_free_still_is(self):
        self.free.side_effect = RuntimeError('offline')
        self.reserve.side_effect = marta.KumoriAPIError('forbidden', status_code=403)
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Canned reply.')
        self.assertEqual(self.chat.get_marta_response('Again'), 'Canned reply.')
        self.assertEqual(self.free.call_count, 2)
        self.reserve.assert_called_once()
        self.free.side_effect = None
        self.assertEqual(self.chat.get_marta_response('Recovered'), 'Free reply.')

    def test_rate_limit_does_not_disable_reserve_permanently(self):
        self.free.side_effect = RuntimeError('offline')
        self.reserve.side_effect = marta.KumoriAPIError('cap', status_code=429)
        self.assertEqual(self.chat.get_marta_response('Hello'), 'Canned reply.')
        self.assertFalse(marta._RESERVE_DISABLED['flag'])

    def test_hidden_cards_not_sent_to_either_lane(self):
        self.free.return_value = ('', None, [], None)
        self.chat.get_marta_response('Hello', game_context={
            'player_hand': [{'rank': 'SECRET_PLAYER', 'suit': 'S'}],
            'computer_hand': [{'rank': 'SECRET_MARTA', 'suit': 'H'}],
            'pending_discard_result': 'SECRET_DISCARD',
        })
        for provider in (self.free, self.reserve):
            prompt = provider.call_args.kwargs['messages'][0]['content']
            self.assertNotIn('SECRET_', prompt)
            self.assertIn('opponent_hand_size', prompt)


if __name__ == '__main__':
    unittest.main()
