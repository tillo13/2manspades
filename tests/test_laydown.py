"""Otto Matic's lay down: the rest of the hand is settled when one side takes every remaining
trick whatever the other does. Found by search, explained in the referee's words, offered to a
person (lay them down / play it out) and dealt out at once for Otto."""
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO

from tests.support import load_app, isolate_services

A = load_app()


def card(txt):
    rank, suit = txt[:-1], txt[-1]
    return {'rank': rank, 'suit': suit, 'value': {'J': 11, 'Q': 12, 'K': 13, 'A': 14}.get(rank, int(rank) if rank.isdigit() else 0)}


def hand(*cards):
    return [card(c) for c in cards]


class LayDownTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        isolate_services(self.stack)

    def game(self, player, computer, **kw):
        g = {'trick_winner': None, 'player_hand': hand(*player), 'computer_hand': hand(*computer),
             'player_tricks': 1, 'computer_tricks': 5, 'player_bags': 0, 'computer_bags': 0, 'spades_broken': False,
             'player_score': 0, 'computer_score': 0, 'hand_number': 3, 'player_bid': 0, 'computer_bid': 5,
             'player_parity': 'even', 'computer_parity': 'odd', 'first_leader': 'computer', 'current_hand_id': 'x',
             'target_score': 300, 'winner': None, 'game_over': False, 'current_trick': [], 'phase': 'playing',
             'trick_history': [{'number': i, 'player_card': card('2♣'), 'computer_card': card('3♣'), 'winner': 'computer'} for i in range(1, 7)]}
        g.update(kw)
        return g

    def test_andys_hand_the_moment_the_4_of_hearts_goes(self):
        from utilities.computer_logic import lay_down
        # 2026-09-06, hand 3: Marta took the 6♥ trick and leads next
        ld = lay_down(self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '8♠']), 'computer')
        self.assertEqual((ld['winner'], ld['tricks']), ('computer', 4))
        self.assertEqual(ld['why'], 'You are not on lead; Marta has no hearts left, so your hearts never get led into; you have no spades to trump with.')

    def test_positions_that_are_live(self):
        from utilities.computer_logic import lay_down
        # Marta kept a heart: the J♥ takes it when she leads it
        self.assertIsNone(lay_down(self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '2♥']), 'computer'))
        # a shared suit where the follower's top card beats the leader's bottom card
        self.assertIsNone(lay_down(self.game(['3♦', '9♦', 'J♥', '3♥'], ['4♦', '7♦', '8♦', 'J♦']), 'computer'))
        # two live suits each side, nothing forced
        self.assertIsNone(lay_down(self.game(['A♥', '2♥', 'A♦', '2♦'], ['K♥', '3♥', 'K♦', '3♦']), 'player'))

    def test_shapes_the_search_finds_that_a_rule_list_would_miss(self):
        from utilities.computer_logic import lay_down
        # one low spade against three side-suit leads: you COULD trump and run hearts, but you could
        # also shed a heart and lose the trick, so it isn't guaranteed whatever either side does
        self.assertIsNone(lay_down(self.game(['3♥', '5♥', '9♥', '2♠'], ['4♣', '7♦', '8♦', 'J♦']), 'computer'))
        # seed 4 of the proof run: a winning line exists (9♠ first), but leading the 4♠ throws one away
        self.assertIsNone(lay_down(self.game(['J♣', 'J♦', 'Q♦', 'A♦', '4♠', '9♠'], ['5♣', '6♥', '10♥', 'Q♥', 'A♥', '8♠'], spades_broken=True), 'player'))
        # nothing but spades against none: every reply trumps, then the spades run
        ld = lay_down(self.game(['2♠', '5♠', '9♠'], ['4♣', '7♦', '8♦']), 'computer')
        self.assertEqual((ld['winner'], ld['tricks']), ('player', 3))
        self.assertIn('get trumped', ld['why'])
        # A K Q of spades over 3 4 of spades: the follower's spades are all under
        ld = lay_down(self.game(['3♠', '4♠', '5♥'], ['A♠', 'K♠', 'Q♠'], spades_broken=True), 'computer')
        self.assertEqual((ld['winner'], ld['tricks']), ('computer', 3))
        self.assertIn("your spades are all under Marta's", ld['why'])
        # the same hearts but you on lead: her lone 2♥ is under everything, so it's yours after all
        ld = lay_down(self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '2♥']), 'player')
        self.assertEqual(ld['winner'], 'player')
        # from the very first card: ten spades against ten hearts
        ld = lay_down(self.game(['A♠', 'K♠', 'Q♠', 'J♠', '10♠', '9♠', '8♠', '7♠', '6♠', '5♠'],
                                ['2♥', '3♥', '4♥', '5♥', '6♥', '7♥', '8♥', '9♥', '10♥', 'J♥'], trick_history=[]), 'player')
        self.assertEqual((ld['winner'], ld['tricks']), ('player', 10))

    def test_offered_to_a_person_then_laid_down(self):
        from utilities.hand_flow import process_auto_resolution, lay_them_down
        g = self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '8♠'])
        self.assertEqual(process_auto_resolution(g, {'game': g}, 'computer'), 'offered')
        self.assertEqual(g['lay_down_offer']['tricks'], 4)
        self.assertIn('Otto Matic has called a lay down', g['message'])
        self.assertEqual(g['turn'], 'player')
        self.assertTrue(lay_them_down(g, {'game': g}))
        self.assertEqual((g['computer_tricks'], g['player_tricks']), (9, 1))
        self.assertEqual(g['hand_results']['lay_down']['after_trick'], 6)
        self.assertTrue(all(t['laid_down'] for t in g['hand_results']['trick_history'][6:]))
        self.assertFalse(g['player_hand'] or g['computer_hand'])

    def test_played_out_and_checked(self):
        from utilities.hand_flow import process_auto_resolution, play_it_out, _complete_hand
        g = self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '8♠'])
        process_auto_resolution(g, {'game': g}, 'computer')
        self.assertTrue(play_it_out(g, {'game': g}))
        self.assertIsNone(g.get('lay_down_offer'))
        self.assertEqual(g['lay_down_predicted']['winner'], 'computer')
        self.assertEqual(len(g['current_trick']), 1)   # Marta led, as she was on lead
        # play it out by hand: Marta takes all four, as called
        g['current_trick'] = []
        for i in range(7, 11):
            g['trick_history'].append({'number': i, 'player_card': card('3♥'), 'computer_card': card('4♣'), 'winner': 'computer'})
        g['player_hand'] = []; g['computer_hand'] = []; g['computer_tricks'] = 9
        _complete_hand(g, {'game': g})
        self.assertTrue(g['hand_results']['lay_down_check']['held'])
        self.assertEqual(g['hand_results']['lay_down_check']['played'], 4)

    def test_otto_lays_it_down_at_once(self):
        from utilities.hand_flow import process_auto_resolution
        g = self.game(['3♥', '5♥', '9♥', 'J♥'], ['4♣', '7♦', '8♦', '8♠'], _no_log=True)
        self.assertTrue(process_auto_resolution(g, {'game': g}, 'computer', offer=False))
        self.assertTrue(g['hand_over'])

    def test_special_cards_in_a_lay_down_pay_the_side_that_takes_them(self):
        from utilities.computer_logic import autoplay_remaining_cards
        g = self.game(['3♥', '7♦', '9♥', 'J♥'], ['4♣', '8♦', 'J♦', '10♣'], computer_bags=4)
        self.assertTrue(autoplay_remaining_cards(g, None, 'computer')[0])
        self.assertEqual(g['computer_bags'], 1)            # 7♦ (2) and 10♣ (1) both land with Marta
        self.assertEqual(g['computer_trick_special_cards'], 3)

    def test_referee_page_renders_the_proof(self):
        client = A.app.test_client()
        r = client.get('/referee')
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn('lay downs called', body)
        self.assertIn('Played out: Otto', body)
        self.assertNotIn('did not hold', body)
        self.assertIn('/referee', A.app.test_client().get('/instructions').get_data(as_text=True))

    def test_last_trick_is_never_called(self):
        from utilities.computer_logic import lay_down
        self.assertIsNone(lay_down(self.game(['3♥'], ['4♣']), 'computer'))


if __name__ == '__main__':
    unittest.main()
