"""The hand-over screen says what the hand was worth. Priced once when bidding closes."""
import unittest
from utilities.hand_flow import _stash_par
from utilities.postgres_utils.par import _card


def hand(codes):
    return [_card(c) for c in codes]


class StashParTests(unittest.TestCase):
    def test_prices_a_hand_and_the_two_sides_add_to_ten(self):
        game = {'player_hand': hand(['A♠', 'K♠', 'Q♠', 'J♠', '10♠', 'A♥', 'K♥', 'Q♥', 'J♥', '10♥']),
                'computer_hand': hand(['2♠', '3♠', '4♠', '5♠', '6♠', '2♥', '3♥', '4♥', '5♥', '6♥'])}
        _stash_par(game, 'player')
        self.assertEqual(game['hand_par'], {'player': 10, 'computer': 0}, 'every card is the boss')
        self.assertEqual(sum(game['hand_par'].values()), 10)

    def test_the_other_way_round(self):
        game = {'computer_hand': hand(['A♠', 'K♠', 'Q♠', 'J♠', '10♠', 'A♥', 'K♥', 'Q♥', 'J♥', '10♥']),
                'player_hand': hand(['2♠', '3♠', '4♠', '5♠', '6♠', '2♥', '3♥', '4♥', '5♥', '6♥'])}
        _stash_par(game, 'computer')
        self.assertEqual(game['hand_par'], {'player': 0, 'computer': 10})

    def test_leader_matters(self):
        cards = {'player_hand': hand(['A♣', '2♣', '3♣', '4♣', '5♣', '2♦', '3♦', '4♦', '5♦', '6♦']),
                 'computer_hand': hand(['K♣', '6♣', '7♣', '8♣', '9♣', '7♦', '8♦', '9♦', '10♦', 'J♦'])}
        a, b = dict(cards), dict(cards)
        _stash_par(a, 'player')
        _stash_par(b, 'computer')
        for g in (a, b):
            self.assertEqual(sum(g['hand_par'].values()), 10)
            self.assertTrue(0 <= g['hand_par']['player'] <= 10)

    def test_a_half_dealt_hand_is_left_unpriced_rather_than_guessed(self):
        game = {'player_hand': hand(['A♠']), 'computer_hand': []}
        _stash_par(game, 'player')
        self.assertNotIn('hand_par', game)
        game = {'hand_par': 'stale', 'player_hand': [], 'computer_hand': []}
        _stash_par(game, 'player')
        self.assertNotIn('hand_par', game)


if __name__ == '__main__':
    unittest.main()
