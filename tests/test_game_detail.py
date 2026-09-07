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
        history[0].pop('leader')
        events[0]['hand_first_leader'] = 'computer'
        with patch('utilities.postgres_utils.records.get_db_connection', return_value=conn), \
             patch('utilities.postgres_utils.records.return_db_connection'):
            old_game = get_game_details('game')
        self.assertEqual(old_game['hands'][0]['trick_history'][0]['leader'], 'Marta')


if __name__ == '__main__':
    unittest.main()
