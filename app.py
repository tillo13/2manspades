from flask import Flask, render_template, request, session, jsonify, redirect
import sys
import os
import time
import traceback

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
    start_development_server, process_ip_geolocation
)
from utilities.gameplay_logic import is_valid_play, init_new_hand
from utilities.logging_utils import log_action, log_game_event, get_client_ip, start_async_db_logging, IS_PRODUCTION
from utilities.postgres_utils import get_unified_leaderboard, get_fun_stats, get_player_achievements, get_special_card_stats, get_overall_game_stats, get_per_hand_stats, get_suspected_player_from_ip
from utilities.gmail_utils import send_simple_email

from utilities.google_auth_utils import SimpleGoogleAuth



app = Flask(__name__)
google_auth = SimpleGoogleAuth(app)

app.secret_key = 'a-super-secret-key-change-this-or-dont-whatever-its-spades-man'

# Session configuration - keep users logged in for 30 days
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JS access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection


# Initialize async logging for production immediately when module loads
if IS_PRODUCTION:
    start_async_db_logging()
    print("[STARTUP] Async database logging initialized")

DEBUG_MODE = False
session_tracker = {}

# Error notification system
LAST_ERROR_EMAIL_TIME = {}  # Track when we last emailed about each error type




@app.route('/login')
def login():
    """Start Google OAuth flow"""
    print("[AUTH] Login initiated")
    return google_auth.login()

# In app.py

@app.route('/auth/callback')
def auth_callback():
    """Handle OAuth callback"""
    if google_auth.handle_callback():
        # Make session permanent so it persists across browser closes (30 days)
        session.permanent = True
        print(f"[AUTH] User logged in: {session.get('user')}")

        # CRITICAL: Update game client_info with Google auth
        if 'game' in session:
            if not session['game'].get('client_info'):
                session['game']['client_info'] = {}
            session['game']['client_info']['google_auth'] = session['user']
            session.modified = True
            print(f"[AUTH] Updated game client_info with Google auth")

        return redirect('/')
    else:
        print(f"[AUTH] Login failed")
        return redirect('/')

@app.route('/logout')
def logout():
    """Logout user"""
    user = session.get('user')
    print(f"[AUTH] User logged out: {user}")
    google_auth.logout()
    return redirect('/')





@app.errorhandler(Exception)
def handle_error(error):
    """Catch all errors and email notifications"""
    from werkzeug.exceptions import HTTPException
    
    # Ignore HTTP exceptions (404s, 301s, etc.) - these are just bots/scanners
    # Just pass them through without sending error emails
    if isinstance(error, HTTPException):
        return error
    
    # Only process actual application errors below this point
    error_type = type(error).__name__
    error_message = str(error)
    error_key = f"{error_type}_{error_message[:50]}"  # Unique key for this error
    
    # Rate limiting: only email once per hour per error type
    current_time = time.time()
    last_email_time = LAST_ERROR_EMAIL_TIME.get(error_key, 0)
    
    if current_time - last_email_time > 3600:  # 3600 seconds = 1 hour
        LAST_ERROR_EMAIL_TIME[error_key] = current_time
        
        # Get request context
        endpoint = request.endpoint or 'unknown'
        client_ip = get_client_ip(request)
        
        # Get game state if available
        game_state = "No game in session"
        if 'game' in session:
            game = session['game']
            game_state = f"""
Hand #{game.get('hand_number', '?')}
Phase: {game.get('phase', '?')}
Player Score: {game.get('player_score', '?')}
Computer Score: {game.get('computer_score', '?')}
Player Bid: {game.get('player_bid', '?')}
Computer Bid: {game.get('computer_bid', '?')}
pending_discard_result: {game.get('pending_discard_result', 'NOT SET')}
blind_decision_made: {game.get('blind_decision_made', 'NOT SET')}
"""
        
        # Build email body
        email_body = f"""
2MANSPADES ERROR DETECTED

Error Type: {error_type}
Error Message: {error_message}
Endpoint: {endpoint}
Player IP: {client_ip}
Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}

GAME STATE:
{game_state}

STACK TRACE:
{traceback.format_exc()}
"""
        
        # Send email (non-blocking, won't slow down response)
        try:
            send_simple_email(
                subject=f"[2MANSPADES BUG] {error_type} in {endpoint}",
                body=email_body,
                to_email="andy.tillo@gmail.com"  # YOUR EMAIL HERE
            )
            print(f"[ERROR EMAIL] Sent notification about {error_type} in {endpoint}")
        except Exception as email_error:
            print(f"[ERROR EMAIL] Failed to send: {email_error}")
    
    # Re-raise the error so normal logging still works
    raise error


@app.route('/debug_async_logging')
def debug_async_logging():
    """Debug endpoint to check async logging status"""
    from utilities.logging_utils import get_async_db_stats, IS_PRODUCTION
    
    stats = get_async_db_stats()
    
    return jsonify({
        'is_production': IS_PRODUCTION,
        'async_logging_enabled': IS_PRODUCTION,
        'worker_running': stats['worker_running'],
        'queue_size': stats['queue_size'],
        'operations_completed': stats['operations_completed'],
        'operations_failed': stats['operations_failed'],
        'queue_max_size': 1000
    })

@app.route('/')
def index():
    force_new = request.args.get('new', '').lower() == 'true'

    if force_new or 'game' not in session:
        # CRITICAL: Preserve user login and difficulty when clearing game session
        user = session.get('user')
        difficulty = session.get('difficulty', 'easy')
        session.clear()
        if user:
            session['user'] = user
            session.permanent = True  # Keep them logged in
        session['difficulty'] = difficulty
        session['game'] = initialize_new_game_session(request, difficulty)

        # ADD THIS: Trigger geolocation for new visitors
        client_info = track_request_session(session, request)
        if client_info and client_info.get('ip_address'):
            process_ip_geolocation(client_info['ip_address'])

    # Check if we should show "We think you're X" prompt
    suspected_player = None
    if not session.get('user'):  # Not logged in
        client_ip = get_client_ip(request)
        if client_ip and IS_PRODUCTION:
            suspected_player = get_suspected_player_from_ip(client_ip)

    return render_template('index.html', suspected_player=suspected_player)

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

@app.route('/set_difficulty', methods=['POST'])
def set_difficulty():
    """Set Marta's difficulty level"""
    data = request.get_json() or {}
    difficulty = data.get('difficulty', 'easy')
    if difficulty not in ('easy', 'medium', 'ruthless'):
        return jsonify({'error': 'Invalid difficulty'}), 400
    session['difficulty'] = difficulty
    # Update current game if exists
    if 'game' in session:
        session['game']['difficulty'] = difficulty
        session.modified = True
    return jsonify({'success': True, 'difficulty': difficulty})

@app.route('/get_difficulty')
def get_difficulty():
    """Get current difficulty setting"""
    return jsonify({'difficulty': session.get('difficulty', 'easy')})

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
    game['blind_decision_made'] = True  # CRITICAL: Mark decision as made
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
    
    # CRITICAL FIX: Go to discard phase, not bidding phase
    # Player must discard before bidding
    game['phase'] = 'discard'
    game['blind_decision_made'] = True  # Mark decision as made
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
    init_new_hand(game)  # This now creates a new current_hand_id
    
    # CREATE DATABASE RECORD FOR NEW HAND with Google auth
    if client_info and 'user' in session:
        client_info['google_auth'] = session['user']
    
    from utilities.logging_utils import queue_db_operation
    from utilities.postgres_utils import create_hand_with_player
    
    if IS_PRODUCTION:
        queue_db_operation(create_hand_with_player, game, client_info)
    else:
        # Synchronous in development for easier debugging
        create_hand_with_player(game, client_info)
    
    session.modified = True
    return jsonify({'success': True})

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

@app.route('/stats')
def stats():
    # Unified leaderboard: Tom/Luke/Jon/Andy/Other (from vw_unified_leaderboard view)
    google_leaders = get_unified_leaderboard()
    fun_stats = get_fun_stats()
    achievements = get_player_achievements()
    special_cards = get_special_card_stats()
    overall_stats = get_overall_game_stats()
    per_hand_stats = get_per_hand_stats()

    return render_template('stats.html',
                        google_leaders=google_leaders,
                        fun_stats=fun_stats,
                        achievements=achievements,
                        special_cards=special_cards,
                        overall_stats=overall_stats,
                        per_hand_stats=per_hand_stats)


@app.route('/player/<name>')
def player_profile(name):
    """Show all games for a specific player."""
    from utilities.postgres_utils import get_player_games
    player_data = get_player_games(name)
    if not player_data:
        return render_template('404.html', message=f"Player '{name}' not found"), 404
    return render_template('player.html', player=player_data)


@app.route('/game/<hand_id>')
def game_detail(hand_id):
    """Show detailed breakdown of a specific game."""
    from utilities.postgres_utils import get_game_details
    game = get_game_details(hand_id)
    if not game:
        return render_template('404.html', message=f"Game not found: {hand_id}"), 404
    return render_template('game_detail.html', game=game)


@app.route('/debug_game_creation')
def debug_game_creation():
    """Debug game creation issues"""
    if 'game' not in session:
        return jsonify({'error': 'No game in session'})
    
    game = session['game']
    game_id = game.get('game_id')
    
    # Try to create the game synchronously to see the error
    try:
        from utilities.postgres_utils import create_game_with_player, get_db_connection
        
        # First test database connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        db_connection_ok = True
    except Exception as e:
        db_connection_ok = False
        db_error = str(e)
    
    # Try creating the game
    try:
        from utilities.postgres_utils import create_game_with_player
        creation_result = create_game_with_player(game, game.get('client_info'))
    except Exception as e:
        creation_result = f"Exception: {e}"
    
    return jsonify({
        'game_id': game_id,
        'game_started_at': game.get('game_started_at'),
        'client_info': game.get('client_info'),
        'db_connection_ok': db_connection_ok,
        'db_error': db_error if not db_connection_ok else None,
        'creation_result': creation_result,
        'is_production': IS_PRODUCTION
    })

if __name__ == '__main__':
    start_development_server(app)