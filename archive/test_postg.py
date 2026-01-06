# test_game_logging.py
from utilities.postgres_utils import insert_game, log_game_event_to_db
import time

# Test game data
test_game = {
    'game_id': f'test_{int(time.time())}',
    'game_started_at': time.time(),
    'player_parity': 'even',
    'computer_parity': 'odd',
    'first_leader': 'player',
    'client_info': {'ip_address': '127.0.0.1', 'user_agent': 'test'}
}

# Test inserting game
if insert_game(test_game):
    print("Game inserted successfully!")
    
    # Test logging an event
    if log_game_event_to_db(
        test_game['game_id'],
        'test_event',
        {'action': 'card_play', 'card': 'A♠'},
        hand_number=1,
        session_sequence=1,
        player='player',
        action_type='card_play'
    ):
        print("Event logged successfully!")
    else:
        print("Event logging failed")
else:
    print("Game insertion failed")