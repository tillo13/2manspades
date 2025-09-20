"""
App helper functions for Two-Man Spades
Contains all non-routing logic moved from app.py
"""
from flask import session
import time
from .logging_utils import log_action, log_game_event, track_session_client, get_client_ip, IS_PRODUCTION
from .custom_rules import (
    check_special_cards_in_trick, reduce_bags_safely, assign_even_odd_at_game_start,
    calculate_discard_score_with_winner, calculate_hand_scores_with_bags, 
    get_player_names_with_parity, check_special_cards_in_discard,
    check_blind_bidding_eligibility
)
from .gameplay_logic import determine_trick_winner, init_game, init_new_hand, check_game_over
from .computer_logic import (
    computer_follow_strategy, computer_lead_strategy, computer_bidding_brain,
    computer_discard_strategy, autoplay_remaining_cards
)
from .logging_utils import initialize_game_logging_with_client, finalize_game_logging, flush_hand_events




# =============================================================================
# CONTENT FILTERING
# =============================================================================

def process_ip_geolocation(client_ip: str):
    """Process IP geolocation lookup - queue background lookup if needed"""
    if not client_ip or client_ip == 'unknown':
        return
    
    from .logging_utils import queue_db_operation
    
    # Always queue background geolocation lookup for production
    if IS_PRODUCTION:
        queue_db_operation(_perform_ip_geolocation_lookup, client_ip)
        print(f"[GEO] Queued geolocation lookup for IP: {client_ip}")
    
    return None

def _perform_ip_geolocation_lookup(ip_address: str):
    """
    Background worker function to perform actual geolocation API call
    Saves ONLY the data returned from the IP API - no calculated fields
    """
    import urllib.request
    import urllib.error
    import json
    import time
    
    try:
        print(f"[GEO] Starting geolocation lookup for {ip_address}")
        
        # Use ip-api.com
        url = f"http://ip-api.com/json/{ip_address}"
        
        request = urllib.request.Request(url)
        request.add_header('User-Agent', 'TwoManSpades-GeoLookup/1.0')
        
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('status') == 'success':
                    # Extract ALL the data from the API response
                    location_data = {
                        'country': data.get('country', 'Unknown'),
                        'region': data.get('regionName', 'Unknown'),  # Note: API returns 'regionName'
                        'city': data.get('city', 'Unknown'),
                        'lat': data.get('lat', 0),
                        'lon': data.get('lon', 0),
                        'timezone': data.get('timezone', 'Unknown'),
                        'zip': data.get('zip', 'Unknown'),
                        'isp': data.get('isp', 'Unknown'),
                        'org': data.get('org', data.get('isp', 'Unknown')),  # Fallback to ISP if org missing
                        'as': data.get('as', 'Unknown')  # Full AS string like "AS7922 Comcast Cable Communications, LLC"
                    }
                    
                    from .postgres_utils import save_ip_location_data
                    success = save_ip_location_data(ip_address, location_data)
                    
                    if success:
                        print(f"[GEO] Successfully saved location data for {ip_address}: {location_data['city']}, {location_data['country']}")
                    else:
                        print(f"[GEO] Failed to save location data for {ip_address}")
                    
                    return success
                else:
                    print(f"[GEO] API returned failure for {ip_address}: {data.get('message', 'Unknown error')}")
                    
                    # Save failed lookup record
                    from .postgres_utils import save_failed_ip_lookup
                    save_failed_ip_lookup(ip_address)
                    return False
            else:
                print(f"[GEO] HTTP error {response.getcode()} for {ip_address}")
                return False
                
    except Exception as e:
        print(f"[GEO] Geolocation lookup failed for {ip_address}: {e}")
        return False

def get_blocked_words():
    """Get blocked words from tinyurl"""
    import requests
    
    try:
        url = "https://tinyurl.com/35wba3d6"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return [word.strip() for word in response.text.split('\n') if word.strip()]
    except:
        pass
    
    # Fallback minimal list if tinyurl fails
    return ['placeholder1', 'placeholder2']

def check_content_filter(message):
    """Check if message contains disallowed content"""
    try:
        blocked_phrases = get_blocked_words()
        
        message_lower = message.lower()
        for phrase in blocked_phrases:
            if phrase.lower() in message_lower:
                print(f"[FILTER] BLOCKED message containing '{phrase}': '{message[:50]}{'...' if len(message) > 50 else ''}'")
                return False, "Hey, watch the language! Let's keep it PG-13 here - I've got a reputation to maintain!"
        
        return True, None
    except Exception as e:
        print(f"[FILTER] Error checking content filter: {e}")
        return True, None

# =============================================================================
# DEVELOPMENT SERVER UTILITIES
# =============================================================================

def start_development_server(app):
    """Start development server with port management and browser opening (macOS optimized)"""
    import subprocess
    import webbrowser
    import time
    import socket
    import os
    from threading import Thread
    
    def kill_process_on_port(port):
        try:
            result = subprocess.run(['lsof', '-ti:' + str(port)], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid.strip():
                        subprocess.run(['kill', '-9', pid.strip()], capture_output=True)
                        print(f"Killed process {pid.strip()} on port {port}")
                time.sleep(1)
                return True
        except Exception as e:
            print(f"Could not kill processes on port {port}: {e}")
        return False
    
    def is_port_available(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        return result != 0
    
    def find_available_port(start_port=5000, max_attempts=10):
        for port in range(start_port, start_port + max_attempts):
            if is_port_available(port):
                print(f"Port {port} is available")
                return port
            else:
                print(f"Port {port} is in use, attempting to kill process...")
                if kill_process_on_port(port):
                    time.sleep(0.5)
                    if is_port_available(port):
                        print(f"Successfully freed port {port}")
                        return port
                    else:
                        print(f"Port {port} still in use after kill attempt")
                else:
                    print(f"Could not kill process on port {port}")
        
        raise RuntimeError(f"Could not find an available port in range {start_port}-{start_port + max_attempts - 1}")
    
    def open_browser(port):
        time.sleep(1.5)
        url = f'http://localhost:{port}'
        
        # macOS Chrome path
        chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        
        opened = False
        if os.path.exists(chrome_path):
            try:
                subprocess.Popen([chrome_path, url])
                print(f"Opened Chrome at {url}")
                opened = True
            except:
                pass
        
        if not opened:
            webbrowser.open(url)
            print(f"Opened default browser at {url}")
    
    # Find and secure a port
    try:
        port = find_available_port(5000, 10)
    except RuntimeError as e:
        print(f"Error: {e}")
        print("Please manually kill processes or restart your computer")
        exit(1)
    
    # Start browser opening in a separate thread
    browser_thread = Thread(target=lambda: open_browser(port))
    browser_thread.daemon = True
    browser_thread.start()
    
    print(f"Starting Flask app on port {port}...")
    print(f"The browser should open automatically in a moment...")
    print(f"If not, navigate to http://localhost:{port}")
    
    # Run Flask app
    app.run(debug=True, port=port, use_reloader=False)

# =============================================================================
# SCORE DISPLAY FUNCTIONS
# =============================================================================

def get_display_score(base_score, bags):
    """Convert base score and bags to display score (bags in ones column)"""
    if bags >= 0:
        if base_score < 0:
            tens_and_higher = (base_score // 10) * 10
            return tens_and_higher - bags
        else:
            tens_and_higher = (base_score // 10) * 10
            return tens_and_higher + bags
    else:
        return base_score

def get_base_score_from_display(display_score, bags):
    """Convert display score back to base score (removing bags from ones column)"""
    return display_score - bags

# =============================================================================
# SESSION TRACKING
# =============================================================================

def track_request_session(session, request):
    """Track client session for this request"""
    if 'game' in session:
        return track_session_client(session, request)
    return None

# =============================================================================
# GAME INITIALIZATION
# =============================================================================

def initialize_new_game_session(request):
    """Initialize a new game session with logging"""
    player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
    game = init_game(player_parity, computer_parity, first_player)
    game = initialize_game_logging_with_client(game, request)
    return game

def process_new_game_request(session, request):
    """Process new game request with logging cleanup"""
    client_info = track_request_session(session, request)
    
    if 'game' in session:
        finalize_game_logging(session['game'])
    
    game = initialize_new_game_session(request)
    
    # UNCOMMENT THIS LINE:
    if client_info and client_info.get('ip_address'):
        process_ip_geolocation(client_info['ip_address'])
    
    log_game_event(
        event_type='new_game_started',
        event_data={
            'player_parity': game.get('player_parity'),
            'computer_parity': game.get('computer_parity'),
            'first_leader': game.get('first_leader')
        },
        session={'game': game}
    )
    
    return game

# =============================================================================
# GAME STATE BUILDING
# =============================================================================

def build_safe_game_state(game, debug_mode=False):
    """Build safe game state for frontend"""
    player_name, computer_name = get_player_names_with_parity(
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd')
    )
    
    show_discard_explanation = game.get('hand_over', False)
    discard_explanation = game.get('discard_bonus_explanation') if show_discard_explanation else None
    
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    
    safe_state = {
        'player_hand': game['player_hand'],
        'computer_hand_count': len(game['computer_hand']) if debug_mode else 0,
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
        'show_computer_hand': game.get('show_computer_hand', False) and debug_mode,
        'player_bid': game.get('player_bid'),
        'computer_bid': game.get('computer_bid'),
        'total_tricks': game.get('total_tricks', 10),
        'player_score': player_display_score,
        'computer_score': computer_display_score,
        'player_base_score': player_base_score,
        'computer_base_score': computer_base_score,
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
        'debug_mode': debug_mode,
        'hand_results': game.get('hand_results')
    }
    
    if debug_mode and game.get('show_computer_hand', False):
        safe_state['computer_hand'] = game['computer_hand']
    
    return safe_state

# =============================================================================
# BIDDING LOGIC
# =============================================================================

def process_bidding_phase(game, session, bid, request):
    """Process player bidding with computer response and game state updates"""
    log_action(
        action_type='regular_bid',
        player='player',
        action_data={'bid_amount': bid, 'is_nil': bid == 0},
        session=session,
        request=request
    )
    
    game['player_bid'] = bid
    
    if game.get('computer_bid') is None:
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
                action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
                session=session
            )
        else:
            log_action(
                action_type='regular_bid',
                player='computer',
                action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
                session=session
            )
            
        computer_blind_text = " (BLIND)" if computer_is_blind else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}.'
    else:
        computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}.'
    
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
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
    
    if first_leader == 'player':
        game['message'] = f'{message_base} Your turn to lead the first trick.'
    else:
        game['message'] = f'{message_base} Marta leads the first trick.'
        computer_lead_with_logging(game, session)
        game['turn'] = 'player'
        game['message'] = f'{message_base} Marta led. Your turn to follow.'

def process_blind_bid_phase(game, session, bid, request):
    """Process blind bidding phase"""
    log_action(
        action_type='blind_bid',
        player='player',
        action_data={'bid_amount': bid},
        session=session,
        request=request
    )
    
    game['blind_bid'] = bid
    game['player_bid'] = bid
    
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
            action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
            session=session
        )
    else:
        log_action(
            action_type='regular_bid',
            player='computer',
            action_data={'bid_amount': computer_bid, 'in_response_to_blind': True},
            session=session
        )
    
    game['phase'] = 'discard'
    computer_blind_text = " (BLIND)" if computer_is_blind else ""
    game['message'] = f'You bid BLIND {bid}! Marta bid {computer_bid}{computer_blind_text}. Select a card to discard.'

# =============================================================================
# DISCARD LOGIC
# =============================================================================

def process_discard_phase(game, session, card_index, request):
    """Process discard phase with computer response and scoring"""
    player_card = game['player_hand'].pop(card_index)
    game['player_discarded'] = player_card
    
    log_action(
        action_type='discard',
        player='player',
        action_data={
            'card_discarded': f"{player_card['rank']}{player_card['suit']}",
            'card_index': card_index
        },
        session=session,
        additional_context={'hand_size_after': len(game['player_hand'])},
        request=request
    )
    
    idx = computer_discard_strategy(game['computer_hand'], game)
    computer_card = game['computer_hand'].pop(idx)
    game['computer_discarded'] = computer_card
    
    log_action(
        action_type='discard',
        player='computer',
        action_data={
            'card_discarded': f"{computer_card['rank']}{computer_card['suit']}",
            'card_index': idx
        },
        session=session,
        additional_context={'hand_size_after': len(game['computer_hand'])}
    )
    
    discard_result = calculate_discard_score_with_winner(
        game['player_discarded'],
        game['computer_discarded'],
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd'),
        game
    )
    
    game['pending_discard_result'] = discard_result
    
    special_discard_result = check_special_cards_in_discard(
        game['player_discarded'],
        game['computer_discarded'],
        discard_result['winner']
    )
    
    game['pending_special_discard_result'] = special_discard_result
    
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
    
    # Handle post-discard phase transitions
    if game.get('player_bid') is not None:
        # Bids already set, go to playing
        transition_to_playing_phase(game, session)
    else:
        # Check blind eligibility or go to bidding
        transition_to_bidding_phase(game, session)

def transition_to_playing_phase(game, session):
    """Transition from discard to playing phase"""
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
    player_blind_text = " (BLIND)" if game.get('blind_bid') else ""
    computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
    
    if first_leader == 'player':
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Your turn to lead the first trick.'
    else:
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Marta leads the first trick.'
        computer_lead_with_logging(game, session)
        game['turn'] = 'player'
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Marta led. Your turn to follow.'

def transition_to_bidding_phase(game, session):
    """Transition from discard to bidding phase (or blind decision) - Uses display scores for eligibility"""
    
    # CRITICAL FIX: Only check blind eligibility ONCE per hand
    # If we've already been through blind decision, skip straight to bidding
    if game.get('blind_decision_made', False):
        print(f"DEBUG: Blind decision already made this hand, proceeding to normal bidding")
        game['phase'] = 'bidding'
        first_leader = game.get('first_leader', 'player')
        
        if first_leader == 'computer':
            # Computer bids first
            computer_bid, computer_is_blind = computer_bidding_brain(
                game['computer_hand'], 
                None,
                game
            )
            game['computer_bid'] = computer_bid
            
            if computer_is_blind:
                game['computer_blind_bid'] = computer_bid
                computer_blind_text = " (BLIND)"
                log_action(
                    action_type='blind_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            else:
                computer_blind_text = ""
                log_action(
                    action_type='regular_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            
            game['message'] = f'Cards discarded. Marta bid {computer_bid}{computer_blind_text}. Your turn to bid.'
        else:
            # Player bids first
            game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
        return
    
    # First time checking blind eligibility this hand - use DISPLAY SCORES
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    
    # Calculate display scores (what players actually see)
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    
    # Check eligibility based on display scores
    blind_eligibility = check_blind_bidding_eligibility(player_display_score, computer_display_score)
    
    print(f"DEBUG BLIND CHECK: Player Display={player_display_score} (base={player_base_score}, bags={player_bags}), Computer Display={computer_display_score} (base={computer_base_score}, bags={computer_bags})")
    print(f"DEBUG BLIND CHECK: Player Eligible={blind_eligibility['player_eligible']}, Computer Eligible={blind_eligibility['computer_eligible']}")
    print(f"DEBUG BLIND CHECK: Player Deficit={blind_eligibility['player_deficit']}, Computer Deficit={blind_eligibility['computer_deficit']}")
    
    if blind_eligibility['player_eligible']:
        # Player is eligible for blind bidding - ask them to choose
        game['phase'] = 'blind_decision'
        game['blind_decision_made'] = True  # Mark that we've presented the choice
        deficit = computer_display_score - player_display_score
        game['message'] = f'Cards discarded! You are down by {deficit} points. Choose: Go BLIND for double points/penalties, or bid normally?'
        
        print(f"DEBUG: Entering blind_decision phase with deficit of {deficit}")
    else:
        # Player not eligible for blind bidding - go straight to normal bidding
        game['blind_decision_made'] = True  # Mark that we've checked (even though not eligible)
        game['phase'] = 'bidding'
        first_leader = game.get('first_leader', 'player')
        
        if first_leader == 'computer':
            # Computer bids first
            computer_bid, computer_is_blind = computer_bidding_brain(
                game['computer_hand'], 
                None,
                game
            )
            game['computer_bid'] = computer_bid
            
            if computer_is_blind:
                game['computer_blind_bid'] = computer_bid
                computer_blind_text = " (BLIND)"
                log_action(
                    action_type='blind_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            else:
                computer_blind_text = ""
                log_action(
                    action_type='regular_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            
            game['message'] = f'Cards discarded. Marta bid {computer_bid}{computer_blind_text}. Your turn to bid.'
        else:
            # Player bids first
            game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
        
        print(f"DEBUG: Player not eligible for blind bidding (deficit only {blind_eligibility['player_deficit']}), proceeding to normal bidding")

# =============================================================================
# GAME LOGIC HELPERS
# =============================================================================

def resolve_trick_with_delay(game, session_obj=None):
    """Resolve trick and set it up to be displayed for 3 seconds with logging"""
    if len(game['current_trick']) != 2:
        return
    
    winner = determine_trick_winner(game['current_trick'])
    
    # Save trick to history
    trick_number = len(game.get('trick_history', [])) + 1
    player_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'player'), None)
    computer_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'computer'), None)
    
    game.setdefault('trick_history', []).append({
        'number': trick_number,
        'player_card': player_card,
        'computer_card': computer_card,
        'winner': winner
    })
    
    # Console logging
    p_text = f"{player_card['rank']}{player_card['suit']}" if player_card else "?"
    c_text = f"{computer_card['rank']}{computer_card['suit']}" if computer_card else "?"
    winner_name = "You" if winner == 'player' else "Marta"
    print(f"TRICK {trick_number}: {p_text} vs {c_text} -> {winner_name} wins")
    
    # JSON logging
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
    
    # Apply special card effects immediately
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
    
    # Award trick and set message
    if winner == 'player':
        game['player_tricks'] += 1
        base_message = 'You won the trick!'
    else:
        game['computer_tricks'] += 1
        base_message = 'Marta won the trick!'
    
    if special_result['explanation']:
        game['message'] = f"{base_message} {special_result['explanation']}."
    else:
        game['message'] = f"{base_message}."
    
    game['trick_completed'] = True
    game['trick_winner'] = winner

def computer_follow_with_logging(game, session_obj=None):
    """Computer plays a card when following with logging"""
    hand = game['computer_hand']
    trick = game['current_trick']
    
    if not trick or not hand:
        return
    
    # Use enhanced strategy or fallback
    chosen_idx = computer_follow_strategy(hand, trick, game)
    
    if chosen_idx is None:
        # Fallback logic
        lead_card = trick[0]['card']
        lead_suit = lead_card['suit']
        lead_value = lead_card['value']
        
        same_suit = [(i, c) for i, c in enumerate(hand) if c['suit'] == lead_suit]
        spades = [(i, c) for i, c in enumerate(hand) if c['suit'] == '♠']
        
        if same_suit:
            winners = [(i, c) for i, c in same_suit if c['value'] > lead_value]
            if winners:
                chosen_idx = min(winners, key=lambda x: x[1]['value'])[0]
            else:
                chosen_idx = min(same_suit, key=lambda x: x[1]['value'])[0]
        elif lead_suit != '♠' and spades:
            chosen_idx = min(spades, key=lambda x: x[1]['value'])[0]
        else:
            all_cards = [(i, c) for i, c in enumerate(hand)]
            chosen_idx = min(all_cards, key=lambda x: x[1]['value'])[0]
    
    # Play the card
    card = hand.pop(chosen_idx)
    game['current_trick'].append({'player': 'computer', 'card': card})
    
    # Logging
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
    
    # Use enhanced strategy or fallback
    chosen_idx = computer_lead_strategy(hand, game['spades_broken'], game)
    
    if chosen_idx is None:
        # Fallback logic
        valid = []
        for i, card in enumerate(hand):
            if card['suit'] != '♠' or game['spades_broken'] or all(c['suit'] == '♠' for c in hand):
                valid.append((i, card))
        
        if valid:
            chosen = min(valid, key=lambda x: (x[1]['suit'] == '♠', x[1]['value']))
            chosen_idx = chosen[0]
        else:
            return
    
    # Play the card
    card = hand.pop(chosen_idx)
    game['current_trick'] = [{'player': 'computer', 'card': card}]
    game['trick_leader'] = 'computer'
    
    # Logging
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

# =============================================================================
# HAND COMPLETION LOGIC
# =============================================================================
def process_hand_completion(game, session):
    """Process hand completion with all scoring logic"""
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
    
    # Check if blind nil ended the game (but don't return early - show full results)
    blind_nil_ending = game.get('game_over', False)
    
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
                'winner': "You" if trick['winner'] == 'player' else "Marta"
            }
            for trick in trick_history
        ],
        'totals': {
            'player_score': player_display_score,
            'computer_score': computer_display_score
        }
    }
    
    # Store structured results for frontend
    game['hand_results'] = hand_results
    
    # Flush batched events to database
    from .logging_utils import flush_hand_events
    flush_hand_events(session)
    
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
    
    # Set appropriate message based on game state
    if blind_nil_ending:
        # Keep the blind nil message - it's already set in calculate_hand_scores_with_bags
        # Results will still be shown alongside the game over screen
        log_game_event(
            event_type='game_completed',
            event_data={
                'winner': game['winner'],
                'final_message': game['message'],
                'hands_played': game['hand_number'],
                'game_end_reason': 'blind_nil'
            },
            session=session
        )
    else:
        # Normal hand completion message
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

def process_auto_resolution(game, session):
    """Process auto-resolution of remaining cards"""
    auto_resolved, explanation = autoplay_remaining_cards(game, session)
    
    if auto_resolved:
        # Continue with normal hand completion logic
        if 'pending_discard_result' in game:
            discard_result = game['pending_discard_result']
            game['player_score'] += discard_result['player_bonus']
            game['computer_score'] += discard_result['computer_bonus']
            
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
                
                game['discard_bonus_explanation'] = discard_result['explanation']
                if special_discard_result['explanation']:
                    game['discard_bonus_explanation'] += " | " + special_discard_result['explanation']
            else:
                game['discard_bonus_explanation'] = discard_result['explanation']
            
            del game['pending_discard_result']
            if 'pending_special_discard_result' in game:
                del game['pending_special_discard_result']
        
        # Calculate scoring
        scoring_result = calculate_hand_scores_with_bags(game)
        
        # Check if blind nil ended the game (auto-resolve case)
        blind_nil_ending = game.get('game_over', False)
        
        # Create hand results
        trick_history = game.get('trick_history', [])
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
            'auto_resolution': explanation,
            'trick_history': [
                {
                    'number': trick['number'],
                    'player_card': f"{trick['player_card']['rank']}{trick['player_card']['suit']}" if trick['player_card'] else "?",
                    'computer_card': f"{trick['computer_card']['rank']}{trick['computer_card']['suit']}" if trick['computer_card'] else "?",
                    'winner': "You" if trick['winner'] == 'player' else "Marta"
                }
                for trick in trick_history
            ],
            'totals': {
                'player_score': player_display_score,
                'computer_score': computer_display_score
            }
        }
        
        game['hand_results'] = hand_results
        
        # Flush batched events to database
        from .logging_utils import flush_hand_events
        flush_hand_events(session)
        
        if blind_nil_ending:
            # Keep blind nil message and log completion
            log_game_event(
                event_type='game_completed',
                event_data={
                    'winner': game['winner'],
                    'final_message': game['message'],
                    'hands_played': game['hand_number'],
                    'game_end_reason': 'blind_nil_auto_resolve'
                },
                session=session
            )
        else:
            game['message'] = f"{explanation}. Hand #{game['hand_number']} complete! Click 'Next Hand' to continue"
            
            # Check if game is over
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
        
        return True
    
    return False
