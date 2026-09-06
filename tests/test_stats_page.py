"""/stats renders every section from a full fake payload — catches template errors before deploy."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from io import StringIO
import unittest
from unittest.mock import patch

from tests.support import load_app, isolate_services

A = load_app()
D = datetime(2026, 9, 1, 12, 0)
G = {'player': 'Tom', 'final_player_score': 311, 'final_computer_score': 310, 'margin': 1, 'player_bags': 1,
     'hand_id': 'abc', 'completed_at': D, 'points_behind': 120}
H = {'player': 'Luke', 'overtricks': 4, 'undertricks': 3, 'bid': 5, 'tricks_won': 9, 'points_scored': 150,
     'hand_number': 3, 'hand_id': 'abc', 'completed_at': D}
PAYLOAD = {
    'google_leaders': [{'player_name': 'Tom', 'wins': 378, 'losses': 25, 'win_rate': 93.8, 'total_games': 403,
                        'highest_score': 440, 'highest_score_bags': -1, 'avg_winning_score': 308}],
    'fun_stats': {'total_games': 734, 'total_hands': 2330, 'total_tricks': 54029, 'human_wins': 672, 'marta_wins': 62,
                  'human_win_pct': 91.6, 'avg_game_length': 7.2, 'avg_game_duration_minutes': 16.1,
                  'avg_hand_duration_minutes': 6.2, 'min_game_duration_minutes': 0.4, 'fastest_game_hand_id': 'abc',
                  'fastest_game_date': D, 'max_game_duration_minutes': 3781, 'slowest_game_hand_id': 'abc',
                  'slowest_game_date': D, 'shortest_game': 2, 'shortest_game_hand_id': 'abc', 'shortest_game_date': D,
                  'longest_game': 25, 'longest_game_hand_id': 'abc', 'longest_game_date': D},
    'achievements': {'bid_accuracy': [{'player': 'Tom', 'exact_pct': 40.4, 'exact_bids': 1250, 'hands': 3097}],
                     'nil_stats': [{'player': 'Tom', 'successful': 22, 'attempts': 32, 'rate': 68.8}],
                     'closest_wins': [G], 'biggest_wins': [G], 'worst_losses': [G], 'biggest_comebacks': [G],
                     'streaks': [{'player': 'Tom', 'streak_type': 'win', 'streak': 49, 'last_opposite_date': D,
                                  'last_opposite_hand_id': 'abc', 'last_opposite_player_score': 220,
                                  'last_opposite_computer_score': 316},
                                 {'player': 'Jon', 'streak_type': 'loss', 'streak': 1, 'last_opposite_date': None}],
                     'favorite_bids': [{'player': 'Tom', 'favorite_bid': 4, 'times': 1258}],
                     'bag_stats': [{'player': 'Tom', 'bags_per_hand': 0.15, 'total_bags': 300}],
                     'blind_stats': [{'player': 'Tom', 'blind_successes': 3, 'times_went_blind': 5,
                                      'blind_success_rate': 60, 'blind_rate': 2}],
                     'blind_by_level': [{'player': 'Tom', 'level': 5, 'successes': 3, 'attempts': 5, 'success_rate': 60}]},
    'special_cards': {'overall_captures': [{'winner': 'Players', 'card': '10 of Clubs', 'times': 400}],
                      'player_captures': [{'player': 'Tom', 'ten_clubs': 200, 'seven_diamonds': 150,
                                           'total_special': 350, 'total_bags_saved': 500, 'games_played': 400,
                                           'bags_saved_per_game': 1.25}],
                      'win_rate_with_special': [{'player': 'Tom', 'games_with_special': 300, 'wins': 280, 'win_rate': 93.3}],
                      'marta_captures': {'ten_clubs': 100, 'seven_diamonds': 80}},
    'overall_stats': {'grand_total_points': 300000, 'total_player_points': 200000, 'total_computer_points': 100000,
                      'total_cards_played': 108058, 'total_player_tricks': 30000, 'total_computer_tricks': 24029,
                      'total_player_bags': 1000, 'total_computer_bags': 5095, 'highest_player_score_ever': 496,
                      'highest_player_score_bags': 6, 'highest_computer_score_ever': 362, 'lowest_winning_score': 120,
                      'lowest_win_opponent_score': -211, 'lowest_win_bags': 0, 'biggest_comeback_deficit': 200,
                      'most_popular_bid': 4, 'most_popular_bid_times': 1976, 'total_nil_attempts': 162,
                      'successful_nils': 91, 'nil_success_rate': 56.2, 'blind_nil_attempts': 3, 'blind_nil_successes': 1,
                      'avg_hand_spades_broken': 4.5, 'first_game_date': 'September 14, 2025'},
    'per_hand_stats': {'biggest_overtricks': [H], 'biggest_sets': [H], 'biggest_hand_points': [H],
                       'avg_player_tricks_per_hand': 5.6, 'avg_computer_tricks_per_hand': 4.4,
                       'player_tricks_per_hand': [{'player': 'Tom', 'avg_tricks': 5.7, 'total_hands': 3097}]},
    'hoyt': {'totals': {'plays': 24, 'hours': 0.6, 'songs': 21, 'albums': 5, 'listeners': 2},
             'top_songs': [{'title': 'Boney Fingers', 'plays': 2, 'album_title': 'Life Machine', 'year': '1974'}],
             'top_albums': [{'album_title': 'Life Machine', 'year': '1974', 'plays': 5, 'minutes': 12}],
             'listeners': [{'listener': 'Andy', 'plays': 20, 'minutes': 30, 'last_play': D}],
             'recent': [{'title': 'Boney Fingers', 'album_title': 'Life Machine', 'started_at': D,
                         'seconds_played': 95, 'completed': True}]},
    'robots': {'games': 40, 'otto_wins': 19, 'marta_wins': 20, 'ties': 1, 'games_today': 3, 'avg_hands': 8.7,
               'first_leader_win_pct': 48.1, 'streak_holder': 'Marta', 'streak': 2,
               'seats': [{'seat': 'Otto', 'hands': 348, 'exact': 66, 'exact_pct': 19.0, 'nil_tried': 0, 'nil_made': 0,
                          'blind_tried': 28, 'blind_made': 18, 'avg_bags': 1.49, 'avg_bid': 3.66}]},
    'marta_levels': {'levels': [{'level': 'easy', 'hands': 2321, 'pct': 99.6}, {'level': 'medium', 'hands': 0, 'pct': 0},
                                {'level': 'hard', 'hands': 0, 'pct': 0}, {'level': 'ruthless', 'hands': 9, 'pct': 0.4}],
                     'avg_strength': 0.4, 'total': 2330, 'above_easy_pct': 0.4},
}


class StatsPageTests(unittest.TestCase):
    def test_full_payload_renders_every_section(self):
        from utilities.postgres_utils.stats import player_styles
        payload = dict(PAYLOAD)
        payload['styles'] = player_styles(payload['google_leaders'], payload['achievements'],
                                          payload['per_hand_stats'], payload['robots'])
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            isolate_services(stack)
            stack.enter_context(patch('utilities.postgres_utils.stats.stats_payload', return_value=payload))
            r = A.app.test_client().get('/stats')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for needle in ('Player Leaderboard', 'Playing Styles', 'Otto (bot)', 'Records', 'Nail-Biters',
                       'Robot League', 'Ruthless', 'Special Cards', 'By the Numbers', 'Hoyt Axton Jukebox',
                       '672-62', 'Avg Marta Level'):
            self.assertIn(needle, html, needle)
        tom = next(p for p in payload['styles'] if p['player'] == 'Tom')
        self.assertEqual((tom['exact_pct'], tom['fav_bid'], tom['nil'], tom['tricks']), (40.4, 4, '22/32', 5.7))

    def test_empty_payload_still_renders(self):
        empty = {k: {} for k in PAYLOAD}
        empty['google_leaders'] = []
        empty['styles'] = []
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            isolate_services(stack)
            stack.enter_context(patch('utilities.postgres_utils.stats.stats_payload', return_value=empty))
            r = A.app.test_client().get('/stats')
        self.assertEqual(r.status_code, 200)
        self.assertIn('No players yet', r.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
