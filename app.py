from flask import Flask, render_template, request, session, jsonify
import sys
import os
import time

# Add utilities directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all helper functions
from utilities.app_helpers import (
    check_content_filter, track_request_session, 
    initialize_new_game_session, process_new_game_request,
    build_safe_game_state, process_bidding_phase, process_blind_bid_phase,
    process_discard_phase, resolve_trick_with_delay,
    computer_follow_with_logging, computer_lead_with_logging,
    process_hand_completion, process_auto_resolution,
    start_development_server
)
from utilities.gameplay_logic import is_valid_play, init_new_hand
from utilities.logging_utils import log_action, log_game_event, get_client_ip, start_async_db_logging, IS_PRODUCTION

app = Flask(__name__)
app.secret_key = 'a-super-secret-key-change-this-or-dont-whatever-its-spades-man'

DEBUG_MODE = False
session_tracker = {}

@app.route('/')
def index():
    force_new = request.args.get('new', '').lower() == 'true'
    
    if force_new or 'game' not in session:
        session.clear()
        session['game'] = initialize_new_game_session(request)
    
    return render_template('index.html')

@app.route('/new_game', methods=['POST'])
def new_game():
    session['game'] = process_new_game_request(session, request)
    return jsonify({'success': True})

@app.route('/chat_response', methods=['POST'])
def chat_response():
    print("[CHAT] Received chat request")
    
    try:
        data = request.get_json()
        player_message = data.get('message', '')
        print(f"[CHAT] Player message: '{player_message}'")
        
        # Content filter check with working tinyurl filtering
        is_allowed, filter_message = check_content_filter(player_message)
        if not is_allowed:
            print(f"[CHAT] Message blocked by content filter")
            return jsonify({'response': filter_message})
        
        if 'game' in session:
            game_state = session['game']
            print(f"[CHAT] Game state found: Hand {game_state.get('hand_number', 1)}, Phase {game_state.get('phase', 'unknown')}")
            
            from utilities.claude_utils import get_smart_marta_response
            
            print("[CHAT] Calling Claude...")
            response = get_smart_marta_response(player_message, game_state)
            print(f"[CHAT] Final response: '{response}'")
            
            return jsonify({'response': response})
        else:
            print("[CHAT] No game session found")
            return jsonify({'response': 'Hi there! Start a game and let\'s chat!'})
            
    except Exception as e:
        print(f"[CHAT] Error: {e}")
        fallback_responses = [
            "That's interesting!",
            "I see what you mean...",
            "Good point!",
            "Let's focus on the game!",
            "Hmm, tell me more..."
        ]
        import random
        fallback = random.choice(fallback_responses)
        print(f"[CHAT] Using fallback: '{fallback}'")
        return jsonify({'response': fallback})

@app.route('/state')
def get_state():
    global session_tracker
    client_ip = get_client_ip(request)
    game_phase = session.get('game', {}).get('phase', 'no-game')
    
    session_tracker[client_ip] = {'last_seen': time.time(), 'phase': game_phase}
    
    cutoff = time.time() - 300
    active = {ip: data for ip, data in session_tracker.items() if data['last_seen'] > cutoff}
    session_tracker = active
    
    total_ips = len(active)
    print(f"ACTIVE: {total_ips} users | Current: {client_ip} ({game_phase})")
    if total_ips > 1:
        for ip, data in active.items():
            print(f"  {ip}: {data['phase']}")
    
    if 'game' not in session:
        session['game'] = initialize_new_game_session(request)
    
    game = session['game']
    safe_state = build_safe_game_state(game, DEBUG_MODE)
    
    return jsonify(safe_state)

@app.route('/toggle_computer_hand', methods=['POST'])
def toggle_computer_hand():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    if not DEBUG_MODE:
        return jsonify({'error': 'Debug mode disabled'}), 400
    
    game = session['game']
    game['show_computer_hand'] = not game.get('show_computer_hand', False)
    session.modified = True
    
    return jsonify({'success': True, 'showing': game['show_computer_hand']})

@app.route('/choose_blind_bidding', methods=['POST'])
def choose_blind_bidding():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    
    if game['phase'] != 'blind_decision':
        return jsonify({'error': 'Not in blind decision phase'}), 400
    
    log_action(
        action_type='blind_decision',
        player='player',
        action_data={'chose_blind': True, 'chose_normal': False},
        session=session,
        request=request
    )
    
    game['phase'] = 'blind_bidding'
    game['message'] = 'Choose your blind bid amount (5-10 tricks). Double points if you make it, double penalty if you fail!'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/choose_normal_bidding', methods=['POST'])
def choose_normal_bidding():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    
    if game['phase'] != 'blind_decision':
        return jsonify({'error': 'Not in blind decision phase'}), 400
    
    log_action(
        action_type='blind_decision',
        player='player',
        action_data={'chose_blind': False, 'chose_normal': True},
        session=session,
        request=request
    )
    
    game['phase'] = 'discard'
    game['message'] = 'You chose normal bidding. Select a card to discard.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/blind_bid', methods=['POST'])
def make_blind_bid():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'blind_bidding':
        return jsonify({'error': 'Can only make blind bid during blind bidding phase'}), 400
    
    if bid < 5 or bid > 10:
        return jsonify({'error': 'Blind bid must be between 5 and 10'}), 400
    
    process_blind_bid_phase(game, session, bid, request)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/choose_blind_nil', methods=['POST'])
def choose_blind_nil():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    if game['phase'] != 'blind_decision':
        return jsonify({'error': 'Not in blind decision phase'}), 400
    
    game['blind_bid'] = 0
    game['player_bid'] = 0
    game['blind_nil'] = True
    
    from utilities.computer_logic import computer_bidding_brain
    computer_bid, computer_is_blind = computer_bidding_brain(
        game['computer_hand'], 0, game
    )
    game['computer_bid'] = computer_bid
    if computer_is_blind:
        game['computer_blind_bid'] = computer_bid
    
    game['phase'] = 'discard'
    computer_text = f" Marta bid {computer_bid}{'(BLIND)' if computer_is_blind else ''}."
    game['message'] = f'BLIND NIL chosen! Win instantly with 0 tricks or lose the game!{computer_text} Select a card to discard.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/bid', methods=['POST'])
def make_bid():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'bidding':
        return jsonify({'error': 'Not in bidding phase'}), 400
    
    if bid < 0 or bid > 10:
        return jsonify({'error': 'Bid must be between 0 and 10'}), 400
    
    process_bidding_phase(game, session, bid, request)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/discard', methods=['POST'])
def discard_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    data = request.get_json()
    card_index = data.get('index')
    
    if game['phase'] != 'discard':
        return jsonify({'error': 'Not in discard phase'}), 400
    
    if card_index < 0 or card_index >= len(game['player_hand']):
        return jsonify({'error': 'Invalid card index'}), 400
    
    process_discard_phase(game, session, card_index, request)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/play', methods=['POST'])
def play_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    data = request.get_json()
    card_index = data.get('index')
    
    if game['phase'] != 'playing':
        return jsonify({'error': 'Not in playing phase'}), 400
    
    if game['turn'] != 'player':
        return jsonify({'error': 'Not your turn'}), 400
    
    if card_index < 0 or card_index >= len(game['player_hand']):
        return jsonify({'error': 'Invalid card index'}), 400
    
    card = game['player_hand'][card_index]
    
    if not is_valid_play(card, game['player_hand'], game['current_trick'], game['spades_broken']):
        return jsonify({'error': 'Invalid play - must follow suit if possible'}), 400
    
    log_action(
        action_type='card_play',
        player='player', 
        action_data={
            'card_played': f"{card['rank']}{card['suit']}",
            'card_index': card_index,
            'trick_position': len(game['current_trick']) + 1,
            'leading': len(game['current_trick']) == 0
        },
        session=session,
        additional_context={
            'hand_size_before': len(game['player_hand']),
            'spades_broken_before': game['spades_broken']
        },
        request=request
    )
    
    game['player_hand'].pop(card_index)
    game['current_trick'].append({'player': 'player', 'card': card})
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        log_game_event('spades_broken', {'broken_by': 'player', 'card': f"{card['rank']}{card['suit']}"}, session)
    
    if len(game['current_trick']) == 1:
        game['trick_leader'] = 'player'
        game['turn'] = 'computer'
        computer_follow_with_logging(game, session)
        resolve_trick_with_delay(game, session)
    elif len(game['current_trick']) == 2:
        resolve_trick_with_delay(game, session)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/clear_trick', methods=['POST'])
def clear_trick():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    
    if not game.get('trick_completed'):
        return jsonify({'success': True, 'message': 'No trick to clear'}), 200
    
    winner = game.get('trick_winner')
    
    game['current_trick'] = []
    game['trick_completed'] = False
    game['trick_winner'] = None
    
    if len(game['player_hand']) == 0:
        game['hand_over'] = True
        process_hand_completion(game, session)
    elif len(game['player_hand']) > 0 and len(game['computer_hand']) > 0:
        auto_resolved = process_auto_resolution(game, session)
        
        if not auto_resolved:
            if winner == 'computer':
                computer_lead_with_logging(game, session)
                game['turn'] = 'player'
                game['message'] = 'Marta led. Your turn to follow.'
            else:
                game['turn'] = 'player'
                game['message'] = 'You won the trick! Your turn to lead.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/next_hand', methods=['POST'])
def next_hand():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    client_info = track_request_session(session, request)
    game = session['game']
    
    if not game.get('hand_over', False) or game.get('game_over', False):
        return jsonify({'error': 'Cannot start next hand'}), 400
    
    log_game_event(
        event_type='new_hand_started',
        event_data={
            'previous_hand': game['hand_number'],
            'new_hand': game['hand_number'] + 1
        },
        session=session
    )
    
    game['hand_number'] += 1
    init_new_hand(game)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

# Then in the main block at the very end of app.py, add this:
if __name__ == '__main__':
    # Start async database logging in production
    if IS_PRODUCTION:  # You'll need to import this from logging_utils too
        start_async_db_logging()
    
    start_development_server(app)