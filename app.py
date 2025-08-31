from flask import Flask, render_template, request, session, jsonify
import sys
import os
import logging

# Add utilities directory to path if running as main
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utilities.gameplay_logic import (
    init_game,
    init_new_hand,
    sort_hand,
    is_valid_play,
    resolve_trick_with_delay,
    computer_follow,
    computer_lead,
    check_game_over
)

from utilities.custom_rules import (
    assign_even_odd_at_game_start,
    calculate_discard_score_with_winner,
    calculate_hand_scores_with_bags,
    get_player_names_with_parity,
    check_special_cards_in_discard,
    reduce_bags_safely,
    check_blind_bidding_eligibility
)

from utilities.computer_logic import (
    computer_bidding_brain,
    computer_discard_strategy
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

DEBUG_MODE = False  # Set to False to hide Marta's cards completely

# In the index() route:
@app.route('/')
def index():
    # Always start completely fresh
    session.clear()
    player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
    session['game'] = init_game(player_parity, computer_parity, first_player)
    return render_template('index.html')




# In the get_state() route, modify the safe_state dict:
@app.route('/state')
def get_state():
    if 'game' not in session:
        player_parity, computer_parity = assign_even_odd_at_game_start()
        session['game'] = init_game(player_parity, computer_parity)
    
    game = session['game']
    
    # Get player names with parity
    player_name, computer_name = get_player_names_with_parity(
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd')
    )
    
    # Only show discard_bonus_explanation if hand is over
    show_discard_explanation = game.get('hand_over', False)
    discard_explanation = game.get('discard_bonus_explanation') if show_discard_explanation else None
    
    # Prepare safe state
    safe_state = {
        'player_hand': game['player_hand'],
        'computer_hand_count': len(game['computer_hand']),
        'current_trick': game['current_trick'],
        'player_tricks': game['player_tricks'],
        'computer_tricks': game['computer_tricks'],
        'spades_broken': game['spades_broken'],
        'phase': game['phase'],
        'turn': game['turn'],
        'trick_leader': game.get('trick_leader'),
        'hand_over': game.get('hand_over', False),
        'game_over': game.get('game_over', False),
        'winner': game['winner'],
        'message': game['message'],
        'player_discarded': game.get('player_discarded'),
        'computer_discarded': game.get('computer_discarded'),
        'show_computer_hand': game.get('show_computer_hand', False) and DEBUG_MODE,  # Hide if DEBUG_MODE=False
        'player_bid': game.get('player_bid'),
        'computer_bid': game.get('computer_bid'),
        'total_tricks': game.get('total_tricks', 10),
        'player_score': game.get('player_score', 0),
        'computer_score': game.get('computer_score', 0),
        'player_bags': game.get('player_bags', 0),
        'computer_bags': game.get('computer_bags', 0),
        'hand_number': game.get('hand_number', 1),
        'target_score': game.get('target_score', 300),
        'player_parity': game.get('player_parity', 'even'),
        'computer_parity': game.get('computer_parity', 'odd'),
        'player_name': player_name,
        'computer_name': computer_name,
        'discard_bonus_explanation': discard_explanation,
        'blind_bidding_available': game.get('blind_bidding_available', False),
        'blind_bid': game.get('blind_bid'),
        'computer_blind_bid': game.get('computer_blind_bid'),
        'debug_mode': DEBUG_MODE  # Send debug mode state to frontend
    }
    
    # Include computer hand only if debug mode is on AND showing
    if DEBUG_MODE and game.get('show_computer_hand', False):
        safe_state['computer_hand'] = game['computer_hand']
    
    return jsonify(safe_state)

# Modify the toggle_computer_hand route:
@app.route('/toggle_computer_hand', methods=['POST'])
def toggle_computer_hand():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Don't allow toggling if debug mode is off
    if not DEBUG_MODE:
        return jsonify({'error': 'Debug mode disabled'}), 400
    
    game = session['game']
    game['show_computer_hand'] = not game.get('show_computer_hand', False)
    session.modified = True
    
    return jsonify({'success': True, 'showing': game['show_computer_hand']})

@app.route('/blind_bid', methods=['POST'])
def make_blind_bid():
    """Handle blind bidding before discard phase"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'discard':
        return jsonify({'error': 'Can only make blind bid before discard'}), 400
    
    # Check blind bidding eligibility
    blind_eligibility = check_blind_bidding_eligibility(
        game.get('player_score', 0),
        game.get('computer_score', 0)
    )
    
    if not blind_eligibility['player_eligible']:
        return jsonify({'error': 'Not eligible for blind bidding'}), 400
    
    if bid < 5 or bid > 10:
        return jsonify({'error': 'Blind bid must be between 5 and 10'}), 400
    
    # Set blind bid and regular bid
    game['blind_bid'] = bid
    game['player_bid'] = bid
    
    # Computer makes its decision (might also go blind if eligible)
    computer_bid, computer_is_blind = computer_bidding_brain(
        game['computer_hand'], 
        bid, 
        game
    )
    game['computer_bid'] = computer_bid
    
    if computer_is_blind:
        game['computer_blind_bid'] = computer_bid
    
    # Now proceed to discard with bids already set
    player_blind_text = " (BLIND)"
    computer_blind_text = " (BLIND)" if computer_is_blind else ""
    game['message'] = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}. Now select a card to discard.'
    
    # Stay in discard phase but with bids set
    session.modified = True
    return jsonify({'success': True})

@app.route('/bid', methods=['POST'])
def make_bid():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'bidding':
        return jsonify({'error': 'Not in bidding phase'}), 400
    
    if bid < 0 or bid > 10:
        return jsonify({'error': 'Bid must be between 0 and 10'}), 400
    
    # Player makes regular bid
    game['player_bid'] = bid
    
    # Computer makes intelligent bid using enhanced brain
    computer_bid, computer_is_blind = computer_bidding_brain(
        game['computer_hand'], 
        bid, 
        game
    )
    game['computer_bid'] = computer_bid
    
    # Handle computer blind bid
    if computer_is_blind:
        game['computer_blind_bid'] = computer_bid
    
    # Start playing phase with the designated first leader
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
    # Create message indicating who leads first
    player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
    computer_blind_text = " (BLIND)" if computer_is_blind else ""
    
    if first_leader == 'player':
        game['message'] = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}. Your turn to lead the first trick.'
    else:
        game['message'] = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}. Marta leads the first trick.'
        # If computer leads, make the computer play immediately
        computer_lead(game)
        game['turn'] = 'player'
        game['message'] = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}. Marta led. Your turn to follow.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/discard', methods=['POST'])
def discard_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    data = request.get_json()
    card_index = data.get('index')
    
    if game['phase'] != 'discard':
        return jsonify({'error': 'Not in discard phase'}), 400
    
    if card_index < 0 or card_index >= len(game['player_hand']):
        return jsonify({'error': 'Invalid card index'}), 400
    
    # Player discards
    game['player_discarded'] = game['player_hand'].pop(card_index)
    
    # Computer discards using enhanced strategy
    idx = computer_discard_strategy(game['computer_hand'], game)
    game['computer_discarded'] = game['computer_hand'].pop(idx)
    
    # Calculate discard bonus points and determine winner
    discard_result = calculate_discard_score_with_winner(
        game['player_discarded'],
        game['computer_discarded'],
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd')
    )
    
    # Store discard results for later reveal
    game['pending_discard_result'] = discard_result
    
    # Check for special cards in discards and store for later
    special_discard_result = check_special_cards_in_discard(
        game['player_discarded'],
        game['computer_discarded'],
        discard_result['winner']
    )
    
    game['pending_special_discard_result'] = special_discard_result
    
    # Check if bids were already made (blind bidding scenario)
    if game.get('player_bid') is not None:
        # Bids already set, go straight to playing
        game['phase'] = 'playing'
        game['turn'] = 'player'
        game['trick_leader'] = 'player'
        
        player_blind_text = " (BLIND)" if game.get('blind_bid') else ""
        computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Your turn to lead the first trick.'
    else:
        # Normal flow - check if player is eligible for blind bidding
        blind_eligibility = check_blind_bidding_eligibility(
            game.get('player_score', 0),
            game.get('computer_score', 0)
        )
        
        if blind_eligibility['player_eligible']:
            game['blind_bidding_available'] = True
            game['message'] = f'Cards discarded. You are down by {blind_eligibility["player_deficit"]} points - would you like to go BLIND? (5-10 tricks, double points/penalties) Or make a regular bid? (0-10)'
        else:
            game['blind_bidding_available'] = False
            game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
        
        # Start bidding phase
        game['phase'] = 'bidding'
        game['turn'] = 'player'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/play', methods=['POST'])
def play_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
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
    
    # Validate the play
    if not is_valid_play(card, game['player_hand'], game['current_trick'], game['spades_broken']):
        return jsonify({'error': 'Invalid play - must follow suit if possible'}), 400
    
    # Play the card
    game['player_hand'].pop(card_index)
    game['current_trick'].append({'player': 'player', 'card': card})
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
    
    # Determine next action based on trick state
    if len(game['current_trick']) == 1:
        # Player just led, computer needs to follow
        game['trick_leader'] = 'player'
        game['turn'] = 'computer'
        computer_follow(game)
        # After computer follows, resolve the trick with delay
        resolve_trick_with_delay(game)
    elif len(game['current_trick']) == 2:
        # This shouldn't happen in normal flow, but handle it
        resolve_trick_with_delay(game)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/clear_trick', methods=['POST'])
def clear_trick():
    """Called by frontend after displaying trick for 3 seconds"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    
    if not game.get('trick_completed'):
        return jsonify({'error': 'No completed trick to clear'}), 400
    
    winner = game.get('trick_winner')
    
    # Clear the trick
    game['current_trick'] = []
    game['trick_completed'] = False
    game['trick_winner'] = None
    
    # Check for hand over
    if len(game['player_hand']) == 0:
        game['hand_over'] = True
        
        # Apply stored discard results at the end of the hand
        if 'pending_discard_result' in game:
            discard_result = game['pending_discard_result']
            game['player_score'] += discard_result['player_bonus']
            game['computer_score'] += discard_result['computer_bonus']
            
            # Apply special card effects from discards
            if 'pending_special_discard_result' in game:
                special_discard_result = game['pending_special_discard_result']
                
                if special_discard_result['player_bag_reduction'] > 0:
                    game['player_bags'] = reduce_bags_safely(
                        game.get('player_bags', 0), 
                        special_discard_result['player_bag_reduction']
                    )
                
                if special_discard_result['computer_bag_reduction'] > 0:
                    game['computer_bags'] = reduce_bags_safely(
                        game.get('computer_bags', 0), 
                        special_discard_result['computer_bag_reduction']
                    )
                
                # Store explanation for the final message
                game['discard_bonus_explanation'] = discard_result['explanation']
                if special_discard_result['explanation']:
                    game['discard_bonus_explanation'] += " | " + special_discard_result['explanation']
            else:
                game['discard_bonus_explanation'] = discard_result['explanation']
            
            # Clean up pending results
            del game['pending_discard_result']
            if 'pending_special_discard_result' in game:
                del game['pending_special_discard_result']
        
        # Calculate scoring with bags system
        scoring_result = calculate_hand_scores_with_bags(game)
        
        # Create structured hand results for cleaner display
        trick_history = game.get('trick_history', [])
        hand_results = {
            'hand_number': game['hand_number'],
            'parity': {
                'player': game.get('player_parity', 'even').title(),
                'computer': game.get('computer_parity', 'odd').title()
            },
            'discard_info': game.get('discard_bonus_explanation', ''),
            'scoring': scoring_result['explanation'],
            'trick_history': [
                {
                    'number': trick['number'],
                    'player_card': f"{trick['player_card']['rank']}{trick['player_card']['suit']}" if trick['player_card'] else "?",
                    'computer_card': f"{trick['computer_card']['rank']}{trick['computer_card']['suit']}" if trick['computer_card'] else "?",
                    'winner': "Tom" if trick['winner'] == 'player' else "Marta"
                }
                for trick in trick_history
            ],
            'totals': {
                'player_score': game['player_score'],
                'computer_score': game['computer_score']
            }
        }
        
        # Store structured results for frontend
        game['hand_results'] = hand_results
        
        # Simple message for basic display
        game['message'] = f"Hand #{game['hand_number']} complete! Click 'Next Hand' to continue"
        
        # Check if game is over
        check_game_over(game)
        
    elif winner == 'computer':
        # Computer won last trick, so computer leads
        computer_lead(game)
        game['turn'] = 'player'
        game['message'] = 'Marta led. Your turn to follow.'
    else:
        # Player won last trick, player leads next
        game['turn'] = 'player'
        game['message'] = 'You won the trick! Your turn to lead.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/next_hand', methods=['POST'])
def next_hand():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    
    if not game.get('hand_over', False) or game.get('game_over', False):
        return jsonify({'error': 'Cannot start next hand'}), 400
    
    # Increment hand number and start new hand
    game['hand_number'] += 1
    init_new_hand(game)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/new_game', methods=['POST'])
def new_game():
    # Assign new even/odd and first player for the new game
    player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
    session['game'] = init_game(player_parity, computer_parity, first_player)
    return jsonify({'success': True})

if __name__ == '__main__':
    import subprocess
    import webbrowser
    import time
    import socket
    
    # Kill existing processes on port 5000
    try:
        result = subprocess.run(['lsof', '-ti:5000'], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid.strip():
                    subprocess.run(['kill', '-9', pid.strip()])
                    print(f"Killed process {pid.strip()} on port 5000")
            time.sleep(1)
    except FileNotFoundError:
        try:
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if ':5000' in line and 'LISTENING' in line:
                    parts = line.split()
                    pid = parts[-1]
                    subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                    print(f"Killed process {pid} on port 5000")
                    time.sleep(1)
        except:
            pass
    except Exception as e:
        print(f"Could not check for existing processes: {e}")
    
    # Check if port is still in use and find an alternative
    port = 5000
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    
    for p in range(5000, 5011):
        result = sock.connect_ex(('localhost', p))
        if result != 0:
            port = p
            break
    sock.close()
    
    if port != 5000:
        print(f"Port 5000 is in use, using port {port} instead")
    
    def open_browser():
        time.sleep(1.5)
        url = f'http://localhost:{port}'
        
        chrome_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
            '/usr/bin/google-chrome',
            '/usr/bin/chromium-browser',
        ]
        
        opened = False
        for chrome_path in chrome_paths:
            if os.path.exists(chrome_path):
                try:
                    subprocess.Popen([chrome_path, url])
                    print(f"Opened Chrome at {url}")
                    opened = True
                    break
                except:
                    pass
        
        # If Chrome wasn't found, use default browser
        if not opened:
            webbrowser.open(url)
            print(f"Opened default browser at {url}")
    
    # Start browser opening in a separate thread
    from threading import Thread
    browser_thread = Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    print(f"Starting Flask app on port {port}...")
    print(f"The browser should open automatically in a moment...")
    print(f"If not, navigate to http://localhost:{port}")
    
    # Run Flask app
    app.run(debug=True, port=port, use_reloader=False)