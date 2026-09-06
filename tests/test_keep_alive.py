"""The middle can be thrown back on a game-deciding hand (family rule, 2026-09-06).
Fixture: Andy's real hand 3 that night — 260 vs 143 going in, Andy 4 for 4, Marta blind 5
taking 6, 9♥ + 5♥ in the middle for a doubled 20 to Marta. Site said 300-264, game over.
House rule: 280-244, hand 4 dealt."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import unittest

from tests.support import load_app, isolate_services

A = load_app()


def andy_hand(player_score=260, computer_score=140, computer_bags=3, kitty_winner='computer', pts=20):
    return {
        'player_score': player_score, 'computer_score': computer_score,
        'player_bags': 0, 'computer_bags': computer_bags, 'target_score': 300,
        'player_bid': 4, 'player_tricks': 4, 'computer_bid': 5, 'computer_tricks': 6,
        'blind_bid': None, 'computer_blind_bid': 5, 'hand_number': 3,
        'player_parity': 'odd', 'computer_parity': 'even', 'first_leader': 'player',
        'player_hand': [], 'computer_hand': [], 'trick_history': [], 'current_trick': [],
        'player_discarded': {'rank': '9', 'suit': '♥', 'value': 9},
        'computer_discarded': {'rank': '5', 'suit': '♥', 'value': 5},
        'pending_discard_result': {'winner': kitty_winner, 'is_double': True, 'total': 14,
                                   'player_bonus': pts if kitty_winner == 'player' else 0,
                                   'computer_bonus': pts if kitty_winner == 'computer' else 0,
                                   'explanation': 'Discards: 9♥ (9) + 5♥ (5) = 14 (even) (DOUBLE) → Marta gets 20 pts!',
                                   'denial_option_used': False},
        'pending_special_discard_result': {'player_bag_reduction': 0, 'computer_bag_reduction': 0, 'explanation': ''},
        'player_trick_special_cards': 1, 'computer_trick_special_cards': 0,
        'hand_over': True, 'game_over': False, 'winner': None, 'message': '',
    }


class KeepAliveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)

    def finish(self, game):
        from utilities.hand_flow import process_hand_completion
        from utilities.custom_rules import get_display_score
        process_hand_completion(game, {'game': game})
        return (get_display_score(game['player_score'], game['player_bags']),
                get_display_score(game['computer_score'], game['computer_bags']))

    def test_andys_hand_goes_another_hand(self):
        g = andy_hand()
        self.assertEqual(self.finish(g), (280, 244))
        self.assertFalse(g['game_over'])
        self.assertIn('KEEP ALIVE', g['discard_bonus_explanation'])
        self.assertIn('KEEP ALIVE', g['hand_results']['discard_info'])

    def test_no_throwback_when_it_cannot_save_the_game(self):
        g = andy_hand(player_score=290)          # 290 + 40 = 330; minus 20 is still out
        self.assertEqual(self.finish(g), (330, 264))
        self.assertTrue(g['game_over'])
        self.assertEqual(g['winner'], 'player')

    def test_winner_of_both_keeps_the_middle(self):
        g = andy_hand(kitty_winner='player')      # Andy took the middle and goes out: 320 vs 244
        self.assertEqual(self.finish(g), (320, 244))
        self.assertTrue(g['game_over'])

    def test_symmetric_for_the_human(self):
        g = andy_hand(player_score=140, computer_score=260, computer_bags=0, kitty_winner='player')
        g.update(player_bid=5, blind_bid=5, player_tricks=6, computer_bid=4, computer_tricks=4,
                 computer_blind_bid=None, player_bags=3)
        self.assertEqual(self.finish(g), (244, 280))
        self.assertFalse(g['game_over'])
        self.assertIn('you throw the middle back', g['discard_bonus_explanation'])

    def test_ordinary_hand_untouched(self):
        g = andy_hand(player_score=100, computer_score=100)
        self.assertEqual(self.finish(g), (140, 224))
        self.assertNotIn('KEEP ALIVE', g['discard_bonus_explanation'])


if __name__ == '__main__':
    unittest.main()
