"""Request/session side of the game: client tracking, IP geolocation, chat content filter,
new-game setup, the safe (opponent-hand-free) state sent to the browser, and the dev server."""
from flask import session
import time
from .logging_utils import log_action, log_game_event, track_session_client, get_client_ip, IS_PRODUCTION
from .custom_rules import (
    check_special_cards_in_trick, reduce_bags_safely, assign_even_odd_at_game_start,
    calculate_discard_score_with_winner, calculate_hand_scores_with_bags,
    get_player_names_with_parity, check_special_cards_in_discard,
    check_blind_bidding_eligibility, get_display_score
)
from .gameplay_logic import determine_trick_winner, init_game, init_new_hand, check_game_over
from .computer_logic import (
    computer_follow_strategy, computer_lead_strategy, computer_bidding_brain,
    computer_discard_strategy, autoplay_remaining_cards
)
from .logging_utils import initialize_game_logging_with_client, finalize_game_logging, flush_hand_events



def process_ip_geolocation(client_ip: str):
    """Process IP geolocation lookup - queue background lookup if needed"""
    if not client_ip or client_ip == 'unknown':
        return
    
    from .logging_utils import queue_db_operation
    
    # Always queue background geolocation lookup for production
    if IS_PRODUCTION:
        queue_db_operation(_check_and_perform_ip_geolocation, client_ip)
        print(f"[GEO] Queued geolocation check for IP: {client_ip}")
    
    return None


def _check_and_perform_ip_geolocation(ip_address: str):
    """Check if IP exists in database, only call API if missing"""
    try:
        from .postgres_utils import get_db_connection, return_db_connection
        
        # Check if we already have data for this IP
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT ip_address FROM twomanspades.ip_location_data WHERE ip_address = %s", (ip_address,))
            existing = cur.fetchone()
            cur.close()
        finally:
            return_db_connection(conn)
        
        if existing:
            print(f"[GEO] IP {ip_address} already in database, skipping API call")
            return True
        
        # No existing data, proceed with API call
        print(f"[GEO] IP {ip_address} not found, calling API...")
        return _perform_ip_geolocation_lookup(ip_address)
        
    except Exception as e:
        print(f"[GEO] Database check failed for {ip_address}: {e}")
        # Fall back to API call if database check fails
        return _perform_ip_geolocation_lookup(ip_address)


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


def track_request_session(session, request):
    """Track client session for this request - ALWAYS refresh Google auth"""
    if 'game' in session:
        client_info = track_session_client(session, request)
        
        # CRITICAL: Always update game's client_info with latest Google auth
        if client_info and 'game' in session:
            # Get fresh Google auth from session if available
            from flask import session as flask_session
            if 'user' in flask_session:
                client_info['google_auth'] = flask_session['user']
                # Update the game state with refreshed client_info
                session['game']['client_info'] = client_info
                session.modified = True
            
        return client_info
    return None


def initialize_new_game_session(request, difficulty='easy'):
    """Initialize a new game session with logging"""
    player_parity, computer_parity, first_player = assign_even_odd_at_game_start()
    game = init_game(player_parity, computer_parity, first_player)
    game['difficulty'] = difficulty  # Store difficulty in game state
    game = initialize_game_logging_with_client(game, request)
    return game


def process_new_game_request(session, request):
    """Process new game request with logging cleanup"""
    client_info = track_request_session(session, request)
    difficulty = session.get('difficulty', 'easy')

    if 'game' in session:
        finalize_game_logging(session['game'])

    game = initialize_new_game_session(request, difficulty)
    
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
        'hand_results': game.get('hand_results'),
        # the final screen: the ratchet as data, one row per hand, and the finished game's page
        'ratchet': game.get('ratchet'),
        'lay_down_offer': game.get('lay_down_offer'),
        'lay_down_predicted': game.get('lay_down_predicted'),
        'hand_log': game.get('hand_log', []),
        'game_id': game.get('current_hand_id') if game.get('game_over') else None,
    }
    
    if debug_mode and game.get('show_computer_hand', False):
        safe_state['computer_hand'] = game['computer_hand']
    
    return safe_state
