"""Career records and the click-through that proves a streak."""
import datetime
import unittest
from utilities.postgres_utils.records import _run_of_games


def _g(won, day):
    return {'won': won, 'game_time': datetime.datetime(2026, 1, day)}


class RunOfGamesTests(unittest.TestCase):
    # newest first, the order the player page lists them in
    GAMES = [_g(True, 20), _g(True, 19), _g(True, 18),          # the run still going: 3 wins
             _g(False, 17),                                      # the loss that ended the last one
             _g(True, 16), _g(True, 15), _g(True, 14), _g(True, 13), _g(True, 12),   # the best run: 5 wins
             _g(False, 11), _g(False, 10)]

    def test_current_streak(self):
        run, shown = _run_of_games(self.GAMES, 'streak')
        self.assertEqual(len(run), 3)
        self.assertTrue(all(g['won'] for g in run))
        self.assertIn('3 wins in a row', shown)
        self.assertIn('January 17', shown)

    def test_best_run_is_not_the_current_one(self):
        run, shown = _run_of_games(self.GAMES, 'best')
        self.assertEqual(len(run), 5)
        self.assertIn('5 wins in a row', shown)
        self.assertIn('January 16', shown)                      # the day it ended
        self.assertEqual(run[0]['game_time'].day, 16)

    def test_losing_streak_reads_as_losses(self):
        run, shown = _run_of_games([_g(False, 3), _g(False, 2), _g(True, 1)], 'streak')
        self.assertEqual(len(run), 2)
        self.assertIn('2 losses in a row', shown)

    def test_abandoned_games_do_not_break_a_run(self):
        games = [_g(True, 5), {'won': None, 'game_time': datetime.datetime(2026, 1, 4)}, _g(True, 3)]
        run, shown = _run_of_games(games, 'streak')
        self.assertEqual(len(run), 2)
        self.assertIn('2 wins in a row', shown)

    def test_every_game_on_record(self):
        _run, shown = _run_of_games([_g(True, 2), _g(True, 1)], 'streak')
        self.assertIn('every game on record', shown)

    def test_no_wins_yet(self):
        run, shown = _run_of_games([_g(False, 1)], 'best')
        self.assertEqual(run, [])
        self.assertIn('no wins', shown)

    def test_empty(self):
        games = [{'won': None, 'game_time': datetime.datetime(2026, 1, 1)}]
        self.assertEqual(_run_of_games(games, 'streak'), (games, None))


if __name__ == '__main__':
    unittest.main()
