"""Game records preserve the complete trick history and recorded play order."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, render_template
from pathlib import Path
from utilities.postgres_utils.records import get_game_details


class GameDetailTests(unittest.TestCase):
    def test_complete_history_includes_laydowns_and_lead_order(self):
        now = datetime.now(timezone.utc)
        summary = dict(player_name='Andy', final_player_score=410, final_computer_score=44,
                       won=True, hands_played=1, player_bags=0)
        history = [dict(number=n, winner='Marta', leader='You' if n == 1 else None,
                        player_card='6♥', computer_card='7♥', laid_down=n > 7)
                   for n in range(1, 11)]
        events = [dict(hand_number=1, event_type='hand_scoring', timestamp=now,
                       event_data={'hand_results': {'trick_history': history}})]
        for kind, data in [
            ('discard_scoring', dict(player_card='10♥', computer_card='2♣', explanation='12 (even) → You get 10 pts!')),
            ('special_card_effect', dict(trick_number=4, explanation='Marta won 10♣ (-1 bags)')),
            ('hand_auto_resolved', dict(tricks_simulated=3, explanation='Marta had only spades, you had none')),
        ]:
            events.append(dict(hand_number=1, event_type=kind, timestamp=now, event_data=data))
        conn = MagicMock()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = summary
        cur.fetchall.return_value = events
        with patch('utilities.postgres_utils.records.get_db_connection', return_value=conn), \
             patch('utilities.postgres_utils.records.return_db_connection'):
            game = get_game_details('game')
        self.assertEqual(game['hands'][0]['trick_history'][0]['leader'], 'Andy')
        game['game_completed'] = {'final_message': 'GAME OVER! You WIN by mercy rule 410 to 44! (300+ point lead)'}
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        app.add_url_rule('/player/<name>', 'player_profile', lambda name: '')
        with app.test_request_context('/'):
            html = render_template('game_detail.html', game=game)
        self.assertNotIn('class="tricks-grid"', html)
        self.assertEqual(html.count('<strong>Trick '), 10)
        self.assertEqual(html.count('Laid down</span>'), 3)
        self.assertIn('class="trick-history show"', html)
        self.assertIn('aria-expanded="true"', html)
        self.assertIn('Andy <span class="trick-note">led</span>', html)
        second = html.split('<strong>Trick 2</strong>')[1].split('<strong>Trick 3</strong>')[0]
        self.assertLess(second.index('Marta'), second.index('Andy'))
        self.assertIn('red-card', html)
        self.assertIn('Andy WINS by mercy rule 410 to 44!', html)
        self.assertNotIn('You WIN', html)
        self.assertIn('12 (even) → Andy gets 10 pts!', html)
        self.assertIn('Marta won 10♣ (-1 bags)', html)
        self.assertIn('Marta had only spades, Andy had none', html)
        history[0].pop('leader')
        events[0]['hand_first_leader'] = 'computer'
        with patch('utilities.postgres_utils.records.get_db_connection', return_value=conn), \
             patch('utilities.postgres_utils.records.return_db_connection'):
            old_game = get_game_details('game')
        self.assertEqual(old_game['hands'][0]['trick_history'][0]['leader'], 'Marta')


class FactualSummaryTests(unittest.TestCase):
    def hand(self, number=1):
        return dict(hand_number=number, difficulty='easy', bids=[], auto_tricks=3,
                    final_bids=dict(player_bid=0, computer_bid=3, player_blind=False, computer_blind=False),
                    scoring=dict(player_score=200, computer_score=46),
                    trick_history=[dict(number=n, winner='Marta') for n in range(1, 11)])

    def test_totals_from_complete_history_and_final_bids(self):
        from utilities.postgres_utils.game_summary import summarize_game
        hands = [self.hand(), self.hand(2)]
        hands[1]['final_bids'].update(computer_bid=5, computer_blind=True)
        hands[1]['scoring'].update(player_score=410, computer_score=44)
        result = summarize_game(hands, dict(player_name='Andy', hands_played=2))
        self.assertEqual(result['comparison'], [
            dict(label='Tricks taken', player=0, computer=20),
            dict(label='Nils made / bid', player='2 / 2', computer='0 / 0'),
            dict(label='Blinds made / bid', player='0 / 0', computer='1 / 1')])
        self.assertEqual(result['progression'][-1], dict(hand=2, player=410, computer=44))
        self.assertEqual(result['difficulties'], ['easy'])
        self.assertEqual([t['number'] for t in hands[0]['trick_history'] if t['auto_played']], [8, 9, 10])
        self.assertTrue(hands[0]['bids'][0]['made'])
        self.assertEqual([b['player'] for b in hands[0]['bids']], ['Andy', 'Marta'])
        self.assertEqual(hands[0]['first_bidder'], 'Andy')

    def test_marta_bids_first_when_she_leads(self):
        from utilities.postgres_utils.game_summary import summarize_game
        hand = self.hand()
        hand['final_bids']['first_leader'] = 'computer'
        summarize_game([hand], dict(player_name='Andy', hands_played=1))
        self.assertEqual([b['player'] for b in hand['bids']], ['Marta', 'Andy'])
        self.assertEqual(hand['first_bidder'], 'Marta')
        hand = self.hand()
        hand.pop('final_bids')
        hand['first_leader'] = 'computer'
        summarize_game([hand], dict(player_name='Andy', hands_played=1))
        self.assertEqual(hand['first_bidder'], 'Marta')

    def test_partial_history_does_not_invent_totals(self):
        from utilities.postgres_utils.game_summary import summarize_game
        hand = self.hand()
        hand['trick_history'].pop()
        self.assertEqual(summarize_game([hand], dict(player_name='Andy', hands_played=1))['comparison'], [])
        self.assertEqual(summarize_game([self.hand()], dict(player_name='Andy', hands_played=2))['comparison'], [])
        hand = self.hand()
        hand.pop('final_bids')
        result = summarize_game([hand], dict(player_name='Andy', hands_played=1))
        self.assertEqual(len(result['comparison']), 1)


if __name__ == '__main__':
    unittest.main()
