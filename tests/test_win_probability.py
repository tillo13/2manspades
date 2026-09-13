"""The forecast describes a scored position, never the value of a bid or an unfinished trick."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from utilities.win_probability import estimate_win, features, probability, _model


class ForecastTests(unittest.TestCase):
    def game(self, **changes):
        return dict(dict(player_score=270, computer_score=160, player_bags=1, computer_bags=1,
                         difficulty='easy', first_leader='player', target_score=300), **changes)

    def test_screenshot_and_opponent_strength(self):
        easy=estimate_win(self.game())
        ruthless=estimate_win(self.game(difficulty='ruthless'))
        self.assertGreater(easy['percent'], 90)
        self.assertLess(ruthless['percent'], easy['percent'])
        self.assertEqual(ruthless['strength'], 100)
        self.assertEqual(ruthless, estimate_win(self.game(difficulty=100)))
        self.assertTrue(easy['experimental'])

    def test_bag_risk_and_score_change_the_forecast(self):
        base=estimate_win(self.game(player_score=220, computer_score=220))['percent']
        self.assertLess(estimate_win(self.game(player_score=220, computer_score=220, player_bags=6))['percent'], base)
        self.assertGreater(estimate_win(self.game(player_score=220, computer_score=220, computer_bags=6))['percent'], base)
        self.assertGreater(estimate_win(self.game())['percent'], base)
        self.assertLess(estimate_win(self.game(player_score=160,computer_score=270))['percent'], base)

    def test_unfinished_games_never_show_certainty_or_unsupported_predictions(self):
        for p,c in ((290,0),(0,290),(-100,100),(100,-100)):
            pct=estimate_win(self.game(player_score=p,computer_score=c))['percent']
            self.assertTrue(0 < pct < 100)
        for changes in (dict(game_over=True),dict(player_score=300),dict(computer_score=300),
                        dict(target_score=500),dict(player_score=-400),dict(player_bags=7),
                        dict(player_score=0,computer_score=-300)):
            self.assertIsNone(estimate_win(self.game(**changes)),changes)

    def test_hidden_cards_and_bid_do_not_change_a_position_forecast(self):
        g=self.game()
        self.assertEqual(estimate_win(g), estimate_win(dict(g, player_hand=['A♠'],computer_hand=['2♥'],player_bid=9)))

    def test_bot_baseline_is_not_used_for_humans(self):
        w=_model()['coefficients']
        human=probability(features(150,150,0,0,0,True,'human'),w)
        otto=probability(features(150,150,0,0,0,True,'otto'),w)
        self.assertNotEqual(human,otto)

    def test_missing_model_has_no_invented_percentage(self):
        with patch('utilities.win_probability._model', return_value=None):
            self.assertIsNone(estimate_win(self.game()))

    def test_held_out_predictions_improve_on_human_baseline(self):
        v=_model()['validation']['human']
        self.assertGreater(v['games'],200)
        self.assertLess(v['brier'],v['baseline_brier'])

    def test_completion_uses_final_score_after_keep_alive_and_bag_changes(self):
        from tests.test_keep_alive import andy_hand
        from tests.support import isolate_services
        from utilities.hand_flow import process_hand_completion
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            isolate_services(stack)
            g=andy_hand()
            process_hand_completion(g,{'game':g})
            self.assertFalse(g['game_over'])
            self.assertEqual(g['hand_results']['win_estimate'],estimate_win(g))
            self.assertEqual(g['hand_results']['totals'],{'player_score':280,'computer_score':244})
            g=andy_hand(player_score=290)
            process_hand_completion(g,{'game':g})
            self.assertTrue(g['game_over'])
            self.assertIsNone(g['hand_results']['win_estimate'])


if __name__=='__main__': unittest.main()
