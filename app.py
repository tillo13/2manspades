from flask import Flask, render_template, request, session, jsonify
import sys
import os
import time

# Add utilities directory to path if running as main
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utilities.gameplay_logic import (
    init_game,
    init_new_hand,
    sort_hand,
    is_valid_play,
    determine_trick_winner,
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

# Import logging utilities
from utilities.logging_utils import (
    initialize_game_logging_with_client,
    log_action,
    log_game_event,
    log_ai_decision,
    track_session_client,
    finalize_game_logging, get_client_ip
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

DEBUG_MODE = False  # Set to False to hide Marta's cards completely

session_tracker = {}

def get_display_score(base_score, bags):
    """Convert base score and bags to display score (bags in ones column)"""
    # Only modify ones digit if bags are non-negative
    if bags >= 0:
        # For negative scores, we need to handle the ones digit differently
        if base_score < 0:
            # Remove ones digit from negative number and subtract bags
            tens_and_higher = (base_score // 10) * 10
            return tens_and_higher - bags
        else:
            # For positive scores, remove ones digit and add bags
            tens_and_higher = (base_score // 10) * 10
            return tens_and_higher + bags
    else:
        # If bags are negative, show base score unchanged
        return base_score

def get_base_score_from_display(display_score, bags):
    """Convert display score back to base score (removing bags from ones column)"""
    return display_score - bags

def track_request_session():
    """Track client info for this request session"""
    if 'game' in session:
        return track_session_client(session, request)
    return None

def resolve_trick_with_delay(game, session_obj=None):
    """Resolve trick and set it up to be displayed for 3 seconds with logging"""
    if len(game['current_trick']) != 2:
        return
    
    winner = determine_trick_winner(game['current_trick'])
    
    # SAVE TRICK TO HISTORY BEFORE PROCESSING
    trick_number = len(game.get('trick_history', [])) + 1
    player_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'player'), None)
    computer_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'computer'), None)
    
    game.setdefault('trick_history', []).append({
        'number': trick_number,
        'player_card': player_card,
        'computer_card': computer_card,
        'winner': winner
    })
    
    # LOG TRICK COMPLETION TO CONSOLE AND JSON
    p_text = f"{player_card['rank']}{player_card['suit']}" if player_card else "?"
    c_text = f"{computer_card['rank']}{computer_card['suit']}" if computer_card else "?"
    winner_name = "Tom" if winner == 'player' else "Marta"
    print(f"TRICK {trick_number}: {p_text} vs {c_text} -> {winner_name} wins")
    
    # LOG TO JSON AS WELL
    if session_obj:
        log_game_event(
            event_type='trick_completed',
            event_data={
                'trick_number': trick_number,
                'player_card': p_text,
                'computer_card': c_text,
                'winner': winner,
                'winner_name': winner_name
            },
            session=session_obj
        )
    
    # Check for special cards in the trick and apply bag reduction IMMEDIATELY
    from utilities.custom_rules import check_special_cards_in_trick, reduce_bags_safely
    special_result = check_special_cards_in_trick(game['current_trick'], winner)
    
    if special_result['bag_reduction'] > 0:
        if winner == 'player':
            current_bags = game.get('player_bags', 0)
            game['player_bags'] = reduce_bags_safely(current_bags, special_result['bag_reduction'])
            game['player_trick_special_cards'] = game.get('player_trick_special_cards', 0) + special_result['bag_reduction']
        else:
            current_bags = game.get('computer_bags', 0)
            game['computer_bags'] = reduce_bags_safely(current_bags, special_result['bag_reduction'])
            game['computer_trick_special_cards'] = game.get('computer_trick_special_cards', 0) + special_result['bag_reduction']
        
        game['special_card_message'] = special_result['explanation']
        
        # Log special card effect
        if session_obj:
            log_game_event(
                event_type='special_card_effect',
                event_data={
                    'trick_number': trick_number,
                    'bag_reduction': special_result['bag_reduction'],
                    'beneficiary': winner_name,
                    'explanation': special_result['explanation']
                },
                session=session_obj
            )
    
    # Award trick
    if winner == 'player':
        game['player_tricks'] += 1
        base_message = 'You won the trick!'
    else:
        game['computer_tricks'] += 1
        base_message = 'Marta won the trick!'
    
    # Add special card info to message if present
    if special_result['explanation']:
        game['message'] = f"{base_message} {special_result['explanation']} Cards will clear in 3 seconds..."
    else:
        game['message'] = f"{base_message} Cards will clear in 3 seconds..."
    
    # Mark trick as completed but don't clear yet
    game['trick_completed'] = True
    game['trick_winner'] = winner

def computer_follow_with_logging(game, session_obj=None):
    """Computer plays a card when following with logging"""
    hand = game['computer_hand']
    trick = game['current_trick']
    
    if not trick or not hand:
        return
    
    # Use enhanced following strategy from computer_logic
    from utilities.computer_logic import computer_follow_strategy
    chosen_idx = computer_follow_strategy(hand, trick, game)
    
    if chosen_idx is None:
        # Fallback to original simple logic if strategy fails
        lead_card = trick[0]['card']
        lead_suit = lead_card['suit']
        lead_value = lead_card['value']
        
        # Find valid plays
        same_suit = [(i, c) for i, c in enumerate(hand) if c['suit'] == lead_suit]
        spades = [(i, c) for i, c in enumerate(hand) if c['suit'] == '♠']
        
        if same_suit:
            # Must follow suit - try to win with lowest winning card
            winners = [(i, c) for i, c in same_suit if c['value'] > lead_value]
            if winners:
                chosen_idx = min(winners, key=lambda x: x[1]['value'])[0]
            else:
                # Can't win, play lowest
                chosen_idx = min(same_suit, key=lambda x: x[1]['value'])[0]
        elif lead_suit != '♠' and spades:
            # Can't follow suit, can trump with spade
            chosen_idx = min(spades, key=lambda x: x[1]['value'])[0]
        else:
            # Can't follow or trump, discard lowest
            all_cards = [(i, c) for i, c in enumerate(hand)]
            chosen_idx = min(all_cards, key=lambda x: x[1]['value'])[0]
    
    # Play the chosen card
    card = hand.pop(chosen_idx)
    game['current_trick'].append({'player': 'computer', 'card': card})
    
    # LOG COMPUTER'S RESPONSE
    if session_obj:
        lead_card = game['current_trick'][0]['card'] if len(game['current_trick']) >= 1 else None
        log_action(
            action_type='card_play',
            player='computer',
            action_data={
                'card_played': f"{card['rank']}{card['suit']}",
                'trick_position': 2,
                'following_suit': card['suit'] == lead_card['suit'] if lead_card else False
            },
            session=session_obj,
            additional_context={
                'responding_to': f"{lead_card['rank']}{lead_card['suit']}" if lead_card else None,
                'hand_size_after': len(hand)
            }
        )
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        if session_obj:
            log_game_event('spades_broken', {'broken_by': 'computer', 'card': f"{card['rank']}{card['suit']}"}, session_obj)

def computer_lead_with_logging(game, session_obj=None):
    """Computer plays a card when leading with logging"""
    hand = game['computer_hand']
    
    if not hand:
        return
    
    # Use enhanced leading strategy from computer_logic
    from utilities.computer_logic import computer_lead_strategy
    chosen_idx = computer_lead_strategy(hand, game['spades_broken'])
    
    if chosen_idx is None:
        # Fallback to original simple logic if strategy fails
        valid = []
        for i, card in enumerate(hand):
            if card['suit'] != '♠' or game['spades_broken'] or all(c['suit'] == '♠' for c in hand):
                valid.append((i, card))
        
        if valid:
            chosen = min(valid, key=lambda x: (x[1]['suit'] == '♠', x[1]['value']))
            chosen_idx = chosen[0]
        else:
            return
    
    # Play the chosen card
    card = hand.pop(chosen_idx)
    game['current_trick'] = [{'player': 'computer', 'card': card}]
    game['trick_leader'] = 'computer'
    
    # LOG COMPUTER'S LEAD
    if session_obj:
        log_action(
            action_type='card_play',
            player='computer',
            action_data={
                'card_played': f"{card['rank']}{card['suit']}",
                'trick_position': 1,
                'leading': True
            },
            session=session_obj,
            additional_context={
                'hand_size_after': len(hand)
            }
        )
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        if session_obj:
            log_game_event('spades_broken', {'broken_by': 'computer', 'card': f"{card['rank']}{card['suit']}"}, session_obj)

def determine_martha_bids_first(game):
    """
    Determine if Martha should bid first based on game conditions.
    You can customize this logic based on your game rules.
    """
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    hand_number = game.get('hand_number', 1)
    
    # Example conditions for Martha to bid first:
    # 1. Martha is significantly behind (100+ points)
    # 2. Alternating pattern based on hand number
    # 3. Random chance
    # 4. Based on who won the discard pile
    
    # Condition 1: Martha bids first when she's behind by 75+ points
    if computer_base_score <= player_base_score - 75:
        return True
    
    # Condition 2: Martha bids first on even hand numbers when scores are close
    score_diff = abs(player_base_score - computer_base_score)
    if score_diff <= 50 and hand_number % 2 == 0:
        return True
    
    # Condition 3: Martha bids first if she won the discard pile
    pending_discard = game.get('pending_discard_result')
    if pending_discard and pending_discard.get('winner') == 'computer':
        return True
    
    # Default: Tom bids first
    return False

# In the index() route:
@app.route('/')
def index():
    # Check if we should force a new game (via query parameter)
    force_new = request.args.get('new', '').lower() == 'true'
    
    # Only start fresh if explicitly requested or no existing game
    if force_new or 'game' not in session:
        session.clear()
        player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
        game = init_game(player_parity, computer_parity, first_player)
        # Initialize logging with client tracking
        game = initialize_game_logging_with_client(game, request)
        session['game'] = game
    
    # If there's an existing game, preserve it
    return render_template('index.html')

@app.route('/new_game', methods=['POST'])
def new_game():
    # Track client session
    client_info = track_request_session()
    
    # Finalize previous game logging if exists
    if 'game' in session:
        finalize_game_logging(session['game'])
    
    # Assign new even/odd and first player for the new game
    player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
    game = init_game(player_parity, computer_parity, first_player)
    # Initialize logging with client tracking - this starts a new JSON file
    game = initialize_game_logging_with_client(game, request)
    session['game'] = game
    
    # Log the new game start
    log_game_event(
        event_type='new_game_started',
        event_data={
            'player_parity': player_parity,
            'computer_parity': computer_parity,
            'first_leader': first_player
        },
        session=session
    )
    
    return jsonify({'success': True})


@app.route('/state')
def get_state():
    global session_tracker
    client_ip = get_client_ip(request)
    session_tracker[client_ip] = time.time()
    
    # Clean up old sessions and print stats every time
    cutoff = time.time() - 300  # 5 minutes ago
    active = {k: v for k, v in session_tracker.items() if v > cutoff}
    session_tracker = active  # Clean up the tracker
    
    # Print with more useful info
    total_ips = len(active)
    game_phase = session.get('game', {}).get('phase', 'no-game')
    print(f"ACTIVE: {total_ips} users | Phase: {game_phase} | IP: {client_ip[:15]}...")
    
    if 'game' not in session:
        player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
        session['game'] = init_game(player_parity, computer_parity, first_player)
    
    game = session['game']
    
    # Get player names with parity
    player_name, computer_name = get_player_names_with_parity(
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd')
    )
    
    # Only show discard_bonus_explanation if hand is over
    show_discard_explanation = game.get('hand_over', False)
    discard_explanation = game.get('discard_bonus_explanation') if show_discard_explanation else None
    
    # Calculate display scores (base score + bags)
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    
    # Prepare safe state
    safe_state = {
        'player_hand': game['player_hand'],
        # Only include computer_hand_count if DEBUG_MODE is True
        'computer_hand_count': len(game['computer_hand']) if DEBUG_MODE else 0,
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
        'show_computer_hand': game.get('show_computer_hand', False) and DEBUG_MODE,
        'player_bid': game.get('player_bid'),
        'computer_bid': game.get('computer_bid'),
        'total_tricks': game.get('total_tricks', 10),
        'player_score': player_display_score,  # Display score with bags
        'computer_score': computer_display_score,  # Display score with bags
        'player_base_score': player_base_score,  # Keep base score for internal calculations
        'computer_base_score': computer_base_score,  # Keep base score for internal calculations
        'player_bags': player_bags,
        'computer_bags': computer_bags,
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
        'debug_mode': DEBUG_MODE,
        'hand_results': game.get('hand_results')
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


@app.route('/choose_blind_bidding', methods=['POST'])
def choose_blind_bidding():
    """Handle when player chooses to go blind"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    
    if game['phase'] != 'blind_decision':
        return jsonify({'error': 'Not in blind decision phase'}), 400
    
    # Log the decision
    log_action(
        action_type='blind_decision',
        player='player',
        action_data={
            'chose_blind': True,
            'chose_normal': False
        },
        session=session,
        request=request
    )
    
    # Move to blind bidding phase
    game['phase'] = 'blind_bidding'
    game['message'] = 'Choose your blind bid amount (5-10 tricks). Double points if you make it, double penalty if you fail!'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/choose_normal_bidding', methods=['POST'])
def choose_normal_bidding():
    """Handle when player chooses normal bidding"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    
    if game['phase'] != 'blind_decision':
        return jsonify({'error': 'Not in blind decision phase'}), 400
    
    # Log the decision
    log_action(
        action_type='blind_decision',
        player='player',
        action_data={
            'chose_blind': False,
            'chose_normal': True
        },
        session=session,
        request=request
    )
    
    # Move to discard phase
    game['phase'] = 'discard'
    game['message'] = 'You chose normal bidding. Select a card to discard.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/blind_bid', methods=['POST'])
def make_blind_bid():
    """Handle blind bidding during blind_bidding phase"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'blind_bidding':
        return jsonify({'error': 'Can only make blind bid during blind bidding phase'}), 400
    
    if bid < 5 or bid > 10:
        return jsonify({'error': 'Blind bid must be between 5 and 10'}), 400
    
    # Log blind bid
    log_action(
        action_type='blind_bid',
        player='player',
        action_data={
            'bid_amount': bid
        },
        session=session,
        request=request
    )
    
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
        log_action(
            action_type='blind_bid',
            player='computer',
            action_data={
                'bid_amount': computer_bid,
                'in_response_to_player': True
            },
            session=session
        )
    else:
        log_action(
            action_type='regular_bid',
            player='computer',
            action_data={
                'bid_amount': computer_bid,
                'in_response_to_blind': True
            },
            session=session
        )
    
    # After blind bid, go to discard phase
    game['phase'] = 'discard'
    computer_blind_text = " (BLIND)" if computer_is_blind else ""
    game['message'] = f'You bid BLIND {bid}! Marta bid {computer_bid}{computer_blind_text}. Select a card to discard.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/bid', methods=['POST'])
def make_bid():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    data = request.get_json()
    bid = data.get('bid')
    
    if game['phase'] != 'bidding':
        return jsonify({'error': 'Not in bidding phase'}), 400
    
    if bid < 0 or bid > 10:
        return jsonify({'error': 'Bid must be between 0 and 10'}), 400
    
    # Log player bid
    log_action(
        action_type='regular_bid',
        player='player',
        action_data={
            'bid_amount': bid,
            'is_nil': bid == 0
        },
        session=session,
        request=request
    )
    
    # Player makes regular bid
    game['player_bid'] = bid
    
    # Check if computer has already bid (Martha-first scenario)
    if game.get('computer_bid') is None:
        # Normal scenario - computer bids after player
        computer_bid, computer_is_blind = computer_bidding_brain(
            game['computer_hand'], 
            bid, 
            game
        )
        game['computer_bid'] = computer_bid
        
        # Handle computer blind bid
        if computer_is_blind:
            game['computer_blind_bid'] = computer_bid
            log_action(
                action_type='blind_bid',
                player='computer',
                action_data={
                    'bid_amount': computer_bid,
                    'in_response_to_player': True
                },
                session=session
            )
        else:
            log_action(
                action_type='regular_bid',
                player='computer',
                action_data={
                    'bid_amount': computer_bid,
                    'in_response_to_player': True
                },
                session=session
            )
            
        computer_blind_text = " (BLIND)" if computer_is_blind else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Martha bid {computer_bid}{computer_blind_text}.'
    else:
        # Martha already bid - just acknowledge Tom's bid
        computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Martha bid {game["computer_bid"]}{computer_blind_text}.'
    
    # Start playing phase with the designated first leader
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
    # Log bidding phase complete
    log_game_event(
        event_type='bidding_complete',
        event_data={
            'player_bid': game['player_bid'],
            'computer_bid': game['computer_bid'],
            'first_leader': first_leader,
            'player_blind': game.get('blind_bid') is not None,
            'computer_blind': game.get('computer_blind_bid') is not None
        },
        session=session
    )
    
    # Create message indicating who leads first
    if first_leader == 'player':
        game['message'] = f'{message_base} Your turn to lead the first trick.'
    else:
        game['message'] = f'{message_base} Martha leads the first trick.'
        # If computer leads, make the computer play immediately
        computer_lead_with_logging(game, session)
        game['turn'] = 'player'
        game['message'] = f'{message_base} Martha led. Your turn to follow.'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/discard', methods=['POST'])
def discard_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    data = request.get_json()
    card_index = data.get('index')
    
    if game['phase'] != 'discard':
        return jsonify({'error': 'Not in discard phase'}), 400
    
    if card_index < 0 or card_index >= len(game['player_hand']):
        return jsonify({'error': 'Invalid card index'}), 400
    
    # Player discards
    player_card = game['player_hand'].pop(card_index)
    game['player_discarded'] = player_card
    
    # Log player discard
    log_action(
        action_type='discard',
        player='player',
        action_data={
            'card_discarded': f"{player_card['rank']}{player_card['suit']}",
            'card_index': card_index
        },
        session=session,
        additional_context={
            'hand_size_after': len(game['player_hand'])
        },
        request=request
    )
    
    # Computer discards using enhanced strategy
    idx = computer_discard_strategy(game['computer_hand'], game)
    computer_card = game['computer_hand'].pop(idx)
    game['computer_discarded'] = computer_card
    
    # Log computer discard
    log_action(
        action_type='discard',
        player='computer',
        action_data={
            'card_discarded': f"{computer_card['rank']}{computer_card['suit']}",
            'card_index': idx
        },
        session=session,
        additional_context={
            'hand_size_after': len(game['computer_hand'])
        }
    )
    
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
    
    # Log discard results
    log_game_event(
        event_type='discard_scoring',
        event_data={
            'player_card': f"{player_card['rank']}{player_card['suit']}",
            'computer_card': f"{computer_card['rank']}{computer_card['suit']}",
            'winner': discard_result['winner'],
            'bonus_points': discard_result['player_bonus'] + discard_result['computer_bonus'],
            'is_double': discard_result['is_double'],
            'explanation': discard_result['explanation']
        },
        session=session
    )
    
    # Check if bids were already made (blind bidding scenario)
    if game.get('player_bid') is not None:
        # Bids already set, go straight to playing
        game['phase'] = 'playing'
        first_leader = game.get('first_leader', 'player')
        game['turn'] = first_leader
        game['trick_leader'] = first_leader
        
        player_blind_text = " (BLIND)" if game.get('blind_bid') else ""
        computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
        
        if first_leader == 'player':
            game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Martha bid {game["computer_bid"]}{computer_blind_text}. Your turn to lead the first trick.'
        else:
            game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Martha bid {game["computer_bid"]}{computer_blind_text}. Martha leads the first trick.'
            # If computer leads, make the computer play immediately
            computer_lead_with_logging(game, session)
            game['turn'] = 'player'
            game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Martha bid {game["computer_bid"]}{computer_blind_text}. Martha led. Your turn to follow.'
    else:
        # Normal flow - check for blind bidding eligibility FIRST
        player_base_score = game.get('player_score', 0)
        computer_base_score = game.get('computer_score', 0)
        blind_eligibility = check_blind_bidding_eligibility(player_base_score, computer_base_score)
        
        print(f"DEBUG BLIND CHECK: Player={player_base_score}, Computer={computer_base_score}, Deficit={computer_base_score - player_base_score}, Eligible={blind_eligibility['player_eligible']}")
        
        # Determine who bids first based on game conditions
        should_martha_bid_first = determine_martha_bids_first(game)
        
        if should_martha_bid_first:
            # Martha bids first
            computer_bid, computer_is_blind = computer_bidding_brain(
                game['computer_hand'], 
                None,  # No player bid yet since Martha goes first
                game
            )
            game['computer_bid'] = computer_bid
            
            if computer_is_blind:
                game['computer_blind_bid'] = computer_bid
                log_action(
                    action_type='blind_bid',
                    player='computer',
                    action_data={
                        'bid_amount': computer_bid,
                        'martha_bids_first': True
                    },
                    session=session
                )
            else:
                log_action(
                    action_type='regular_bid',
                    player='computer',
                    action_data={
                        'bid_amount': computer_bid,
                        'martha_bids_first': True
                    },
                    session=session
                )
            
            # Start bidding phase with Martha's bid already made
            game['phase'] = 'bidding'
            game['turn'] = 'player'
            
            computer_blind_text = " (BLIND)" if computer_is_blind else ""
            game['message'] = f'Cards discarded. Martha bid {computer_bid}{computer_blind_text} tricks. Now make your bid: How many tricks will you take? (0-10)'
        else:
            # Tom bids first - check for blind eligibility
            if blind_eligibility['player_eligible']:
                # Enter blind decision phase
                game['phase'] = 'blind_decision'
                deficit = computer_base_score - player_base_score
                game['message'] = f'Cards discarded! You are down by {deficit} points. Choose: Go BLIND for double points/penalties, or bid normally?'
                
                print(f"DEBUG: Entering blind_decision phase with deficit of {deficit}")
            else:
                # No blind eligibility - go straight to normal bidding
                game['phase'] = 'bidding'
                game['turn'] = 'player'
                game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/play', methods=['POST'])
def play_card():
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    # Track client session
    client_info = track_request_session()
    
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
    
    # LOG THE PLAYER'S CARD PLAY
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
    
    # Play the card
    game['player_hand'].pop(card_index)
    game['current_trick'].append({'player': 'player', 'card': card})
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        log_game_event('spades_broken', {'broken_by': 'player', 'card': f"{card['rank']}{card['suit']}"}, session)
    
    # Determine next action based on trick state
    if len(game['current_trick']) == 1:
        # Player just led, computer needs to follow
        game['trick_leader'] = 'player'
        game['turn'] = 'computer'
        computer_follow_with_logging(game, session)
        # After computer follows, resolve the trick with delay
        resolve_trick_with_delay(game, session)
    elif len(game['current_trick']) == 2:
        # This shouldn't happen in normal flow, but handle it
        resolve_trick_with_delay(game, session)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/clear_trick', methods=['POST'])
def clear_trick():
    """Called by frontend after displaying trick for 3 seconds"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'}), 400
    
    game = session['game']
    
    # CHANGE THIS: Don't error if trick is already cleared
    if not game.get('trick_completed'):
        return jsonify({'success': True, 'message': 'No trick to clear'}), 200  # Changed to 200
    
    
    winner = game.get('trick_winner')
    
    # Clear the trick
    game['current_trick'] = []
    game['trick_completed'] = False
    game['trick_winner'] = None
    
    # Check for hand over
    if len(game['player_hand']) == 0:
        game['hand_over'] = True
        
        # Log hand completion
        log_game_event(
            event_type='hand_completed',
            event_data={
                'hand_number': game['hand_number'],
                'player_tricks': game['player_tricks'],
                'computer_tricks': game['computer_tricks'],
                'player_bid': game.get('player_bid', 0),
                'computer_bid': game.get('computer_bid', 0)
            },
            session=session
        )
        
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
        
        # Calculate display scores for hand results
        player_display_score = get_display_score(game['player_score'], game.get('player_bags', 0))
        computer_display_score = get_display_score(game['computer_score'], game.get('computer_bags', 0))
        
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
                'player_score': player_display_score,  # Display score with bags
                'computer_score': computer_display_score  # Display score with bags
            }
        }
        
        # Store structured results for frontend
        game['hand_results'] = hand_results
        
        # Log final scoring
        log_game_event(
            event_type='hand_scoring',
            event_data={
                'scoring_explanation': scoring_result['explanation'],
                'final_scores': {
                    'player_score': player_display_score,
                    'computer_score': computer_display_score
                },
                'hand_results': hand_results
            },
            session=session
        )
        
        # Simple message for basic display
        game['message'] = f"Hand #{game['hand_number']} complete! Click 'Next Hand' to continue"
        
        # Check if game is over using base scores for comparison
        game_over = check_game_over(game)
        if game_over:
            log_game_event(
                event_type='game_completed',
                event_data={
                    'winner': game['winner'],
                    'final_message': game['message'],
                    'hands_played': game['hand_number']
                },
                session=session
            )
        
    elif winner == 'computer':
        # Computer won last trick, so computer leads
        computer_lead_with_logging(game, session)
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
    
    # Track client session
    client_info = track_request_session()
    
    game = session['game']
    
    if not game.get('hand_over', False) or game.get('game_over', False):
        return jsonify({'error': 'Cannot start next hand'}), 400
    
    # Log new hand start
    log_game_event(
        event_type='new_hand_started',
        event_data={
            'previous_hand': game['hand_number'],
            'new_hand': game['hand_number'] + 1
        },
        session=session
    )
    
    # Increment hand number and start new hand
    game['hand_number'] += 1
    init_new_hand(game)
    
    session.modified = True
    return jsonify({'success': True})


if __name__ == '__main__':
    import subprocess
    import webbrowser
    import time
    import socket
    
    def kill_process_on_port(port):
        """Kill any process using the specified port"""
        try:
            # macOS/Linux approach
            result = subprocess.run(['lsof', '-ti:' + str(port)], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid.strip():
                        subprocess.run(['kill', '-9', pid.strip()], capture_output=True)
                        print(f"Killed process {pid.strip()} on port {port}")
                time.sleep(1)
                return True
        except FileNotFoundError:
            try:
                # Windows approach
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if parts:
                            pid = parts[-1]
                            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                            print(f"Killed process {pid} on port {port}")
                time.sleep(1)
                return True
            except:
                pass
        except Exception as e:
            print(f"Could not kill processes on port {port}: {e}")
        return False
    
    def is_port_available(port):
        """Check if a port is available"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        return result != 0
    
    def find_available_port(start_port=5000, max_attempts=10):
        """Find an available port, killing processes if needed"""
        for port in range(start_port, start_port + max_attempts):
            if is_port_available(port):
                print(f"Port {port} is available")
                return port
            else:
                print(f"Port {port} is in use, attempting to kill process...")
                if kill_process_on_port(port):
                    # Check again after killing
                    time.sleep(0.5)
                    if is_port_available(port):
                        print(f"Successfully freed port {port}")
                        return port
                    else:
                        print(f"Port {port} still in use after kill attempt")
                else:
                    print(f"Could not kill process on port {port}")
        
        raise RuntimeError(f"Could not find an available port in range {start_port}-{start_port + max_attempts - 1}")
    
    # Find and secure a port
    try:
        port = find_available_port(5000, 10)
    except RuntimeError as e:
        print(f"Error: {e}")
        print("Please manually kill processes or restart your computer")
        exit(1)
    
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