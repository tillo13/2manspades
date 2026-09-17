"""Game records preserve the complete trick history and recorded play order."""
import unittest
from datetime import datetime, timedelta, timezone
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


class GameAssemblyTests(unittest.TestCase):
    def load(self, events, summary=None):
        summary = summary or dict(player_name='Andy', final_player_score=-31, final_computer_score=336,
                                  won=False, hands_played=2, player_bags=1)
        conn = MagicMock()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = summary
        cur.fetchall.return_value = events
        with patch('utilities.postgres_utils.records.get_db_connection', return_value=conn), \
             patch('utilities.postgres_utils.records.return_db_connection'):
            return get_game_details('game'), [c.args[0] for c in cur.execute.call_args_list]

    def test_hands_of_one_game_are_found_by_start_time_not_player(self):
        """player_id is per IP: Andy's 2026-09-16/17 game had hands 1-9 on one id and 10-33 on another."""
        _, sql = self.load([])
        events_sql = next(q for q in sql if 'game_events' in q)
        self.assertIn('h.started_at = me.started_at', events_sql)
        self.assertNotIn('player_id', events_sql)

    def test_game_time_leaves_out_breaks_and_sits_at_the_top(self):
        t0 = datetime(2026, 9, 16, 13, 39, tzinfo=timezone.utc)
        at = lambda minutes: t0 + timedelta(minutes=minutes)
        events = [dict(hand_number=1, event_type='discard_scoring', timestamp=at(m),
                       event_data=dict(player_card='2♥', computer_card='3♥', winner='player', n=m))
                  for m in (0, 2, 4, 24 * 60, 24 * 60 + 3)]
        game, _ = self.load(events)
        self.assertEqual((game['summary']['play_minutes'], game['summary']['had_breaks']), (7.0, True))
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        app.add_url_rule('/player/<name>', 'player_profile', lambda name: '')
        with app.test_request_context('/'):
            html = render_template('game_detail.html', game=game)
        header = html.split('Hand by Hand')[0]
        self.assertIn('Game time 7.0 min playing · 24.1 hours start to finish', ' '.join(header.split()))
        self.assertLess(header.index('Game time'), header.index('hands played'))
        self.assertIn('Bag penalties (-100)', header)
        self.assertNotIn('Duration:', html)


class FactualSummaryTests(unittest.TestCase):
    def hand(self, number=1):
        return dict(hand_number=number, difficulty='easy', bids=[], auto_tricks=3,
                    final_bids=dict(player_bid=0, computer_bid=3, player_blind=False, computer_blind=False),
                    scoring=dict(player_score=200, computer_score=46, explanation='You: NIL SUCCESS! 0 bid, 0 tricks (+200 pts)'),
                    middle=dict(player_card='3♥', computer_card='4♠', winner='player'),
                    trick_history=[dict(number=n, winner='Marta', player_card=f'{n}♥', computer_card='A♠')
                                   for n in range(1, 11)])

    def rows(self, result, *labels):
        return [r for r in result['comparison'] if r['label'].startswith(labels)]

    def test_totals_from_complete_history_and_final_bids(self):
        from utilities.postgres_utils.game_summary import summarize_game
        hands = [self.hand(), self.hand(2)]
        hands[1]['final_bids'].update(computer_bid=5, computer_blind=True)
        hands[1]['scoring'].update(player_score=410, computer_score=44)
        result = summarize_game(hands, dict(player_name='Andy', hands_played=2))
        self.assertEqual(self.rows(result, 'Tricks', 'Nils', 'Blinds'), [
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
        totals = ('Tricks', 'Nils', 'Blinds')
        self.assertEqual(self.rows(summarize_game([hand], dict(player_name='Andy', hands_played=1)), *totals), [])
        self.assertEqual(self.rows(summarize_game([self.hand()], dict(player_name='Andy', hands_played=2)), *totals), [])
        hand = self.hand()
        hand.pop('final_bids')
        result = summarize_game([hand], dict(player_name='Andy', hands_played=1))
        self.assertEqual(len(self.rows(result, *totals)), 1)

    def test_bag_penalties_and_special_cards_count_every_hand(self):
        from utilities.postgres_utils.game_summary import summarize_game
        hands = [self.hand(n) for n in (1, 2, 3)]
        hands[0]['scoring']['explanation'] = 'You: 4 bid, 9 tricks (+5 bags) | You: BAG PENALTY! -100 pts | Bags: You 0/7, Marta 3/7'
        hands[1]['scoring']['explanation'] = 'Marta: BAG PENALTY! -200 pts | You: BLIND 5 FAILED! 2 tricks (DOUBLE PENALTY: -100 pts)'
        hands[0]['trick_history'][2].update(player_card='10♣', winner='Andy')     # Andy takes 10♣ in a trick
        hands[0]['middle'].update(computer_card='7♦', winner='computer')          # Marta takes 7♦ in the middle
        hands[1]['trick_history'][9].update(player_card='7♦', laid_down=True)     # laid down, still Marta's
        hands[2]['middle'].update(player_card='10♣')                              # Andy takes 10♣ in the middle
        result = summarize_game(hands, dict(player_name='Andy', hands_played=3))
        self.assertEqual(self.rows(result, 'Bag', '10♣', '7♦'), [
            dict(label='Bag penalties (-100)', player=1, computer=2),
            dict(label='10♣ taken', player=2, computer=0),
            dict(label='7♦ taken', player=0, computer=2)])
        # a hand with no record isn't counted, and the row says so
        hands[2].update(scoring=None, middle=None)
        result = summarize_game(hands, dict(player_name='Andy', hands_played=3))
        self.assertEqual(self.rows(result, 'Bag', '10♣', '7♦'), [
            dict(label='Bag penalties (-100) (2 of 3 hands recorded)', player=1, computer=2),
            dict(label='10♣ taken (2 of 3 hands recorded)', player=1, computer=0),
            dict(label='7♦ taken (2 of 3 hands recorded)', player=0, computer=2)])


if __name__ == '__main__':
    unittest.main()
