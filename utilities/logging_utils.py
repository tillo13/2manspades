"""
Streamlined logging utilities for Two-Man Spades - WRITE-ONLY approach
Logs everything for historical analysis but NEVER reads/loads existing files during normal operation
All logging is append-only for performance - reading is only available via explicit debug endpoints
"""
import time
import uuid
import json
import os
import platform
from datetime import datetime

# =============================================================================
# GLOBAL LOGGING CONFIGURATION
# =============================================================================

# Environment detection
IS_LOCAL_DEVELOPMENT = os.environ.get('GAE_ENV') != 'standard'
IS_PRODUCTION = not IS_LOCAL_DEVELOPMENT

LOGGING_ENABLED = True
LOG_TO_CONSOLE = True
LOG_TO_FILE = IS_LOCAL_DEVELOPMENT
LOG_GAME_ACTIONS = True
LOG_AI_DECISIONS = True
LOG_AI_ANALYSIS = True
LOG_GAME_EVENTS = True
CONSOLE_LOG_LEVEL = 'ALL'  # 'ALL', 'ACTIONS_ONLY', 'AI_ONLY', 'EVENTS_ONLY', 'OFF'
LOGS_DIRECTORY = 'logging' if IS_LOCAL_DEVELOPMENT else None
CURRENT_LOG_FILE = None

# Production logging placeholder
PRODUCTION_LOG_PLACEHOLDER = "[PRODUCTION] Log entry saved to pending database implementation"

# =============================================================================
# CLIENT IP TRACKING FUNCTIONS
# =============================================================================

def get_client_ip(request):
    """Get the client's IP address, handling proxies and load balancers, preferring IPv4."""
    forwarded_ips = [
        'X-Forwarded-For',
        'X-Real-IP',
        'X-Appengine-Remote-Addr',
        'CF-Connecting-IP',
        'X-Client-IP',
    ]
    
    all_ips = []
    
    # Debug: Print what headers we're getting
    print(f"DEBUG: Checking IP headers...")
    
    # Collect all possible IPs
    for header in forwarded_ips:
        ip = request.headers.get(header)
        if ip:
            print(f"DEBUG: Found {header}: {ip}")
            # Handle comma-separated list
            ips = [ip.strip() for ip in ip.split(',')]
            for candidate_ip in ips:
                if candidate_ip and candidate_ip != 'unknown':
                    all_ips.append(candidate_ip)
                    print(f"DEBUG: Added candidate: {candidate_ip}")
    
    # Also check REMOTE_ADDR
    remote_addr = request.environ.get('REMOTE_ADDR')
    print(f"DEBUG: REMOTE_ADDR: {remote_addr}")
    if remote_addr and remote_addr != 'unknown':
        all_ips.append(remote_addr)
        print(f"DEBUG: Added REMOTE_ADDR: {remote_addr}")
    
    print(f"DEBUG: All IPs found: {all_ips}")
    
    if not all_ips:
        print("DEBUG: No IPs found - returning 'no-ip-found'")
        return 'no-ip-found'
    
    # Simple IPv4 preference: look for anything with dots and no colons
    ipv4_candidates = [ip for ip in all_ips if '.' in ip and ':' not in ip]
    print(f"DEBUG: IPv4 candidates: {ipv4_candidates}")
    
    if ipv4_candidates:
        chosen_ip = ipv4_candidates[0]
        print(f"DEBUG: Chose IPv4: {chosen_ip}")
        return chosen_ip
    
    # Fallback to first available IP (likely IPv6)
    chosen_ip = all_ips[0]
    print(f"DEBUG: Chose fallback: {chosen_ip}")
    return chosen_ip

def get_client_info(request):
    """Get comprehensive client information for logging."""
    client_ip = get_client_ip(request)
    
    return {
        'ip_address': client_ip,
        'user_agent': request.headers.get('User-Agent', 'unknown'),
        'referer': request.headers.get('Referer', 'none'),
        'method': request.method,
        'endpoint': request.endpoint,
        'is_local': client_ip.startswith('127.') or client_ip.startswith('192.168.') or client_ip == 'localhost'
    }

def track_session_client(session, request):
    """Track client info in session for persistent identification."""
    client_info = get_client_info(request)
    
    session_client = {
        'ip_address': client_info['ip_address'],
        'first_seen': session.get('client_first_seen', time.time()),
        'last_seen': time.time(),
        'session_actions': session.get('client_actions', 0) + 1
    }
    
    session['client_info'] = session_client
    session['client_actions'] = session_client['session_actions'] 
    session['client_first_seen'] = session_client['first_seen']
    session.modified = True
    
    return session_client

def get_session_client_summary(session):
    """Get summary of client activity for this session."""
    client_info = session.get('client_info', {})
    
    if client_info:
        session_duration = time.time() - session.get('client_first_seen', time.time())
        return {
            'ip_address': client_info.get('ip_address', 'unknown'),
            'actions_this_session': session.get('client_actions', 0),
            'session_duration_minutes': round(session_duration / 60, 1),
            'first_seen': datetime.fromtimestamp(session.get('client_first_seen', 0)).strftime('%H:%M:%S')
        }
    
    return None

# =============================================================================
# FILE MANAGEMENT FUNCTIONS - WRITE ONLY
# =============================================================================

def _ensure_logs_directory():
    """Ensure the logging directory exists - only in local development, no scanning"""
    if not IS_LOCAL_DEVELOPMENT:
        return
        
    if LOGS_DIRECTORY and not os.path.exists(LOGS_DIRECTORY):
        os.makedirs(LOGS_DIRECTORY)

def _generate_log_filename(game_id, timestamp=None):
    """Generate a unique log filename for a game - only used in local development"""
    if not IS_LOCAL_DEVELOPMENT:
        return None
        
    if timestamp is None:
        timestamp = datetime.now()
    
    date_str = timestamp.strftime("%Y%m%d")
    time_str = timestamp.strftime("%H%M%S")
    short_game_id = game_id[:8] if game_id else "unknown"
    
    return f"game_log_{date_str}_{time_str}_{short_game_id}.json"

def _start_new_log_file(game_id):
    """Start a new log file for a game - WRITE ONLY, no existing file checking"""
    global CURRENT_LOG_FILE
    
    if not IS_LOCAL_DEVELOPMENT:
        return
    
    if not LOG_TO_FILE:
        return
    
    _ensure_logs_directory()  # Only creates if missing, no scanning
    
    filename = _generate_log_filename(game_id)
    CURRENT_LOG_FILE = os.path.join(LOGS_DIRECTORY, filename)
    
    # Initialize with game metadata
    initial_entry = {
        'log_type': 'game_metadata',
        'data': {
            'game_id': game_id,
            'log_file_created': datetime.now().isoformat(),
            'log_version': '2.0',
            'game_type': 'two_man_spades',
            'environment': 'local_development'
        }
    }
    
    try:
        # Write initial entry - no reading of existing files
        with open(CURRENT_LOG_FILE, 'w') as f:
            json.dump([initial_entry], f, indent=2, default=str)
        
        if LOG_TO_CONSOLE:
            print(f"Started new game log: {filename}")
        
    except Exception as e:
        if LOG_TO_CONSOLE:
            print(f"Warning: Could not create new log file: {e}")
        CURRENT_LOG_FILE = None

def _write_to_current_log_file(log_entry):
    """Write log entry to current game's log file - APPEND ONLY"""
    if not IS_LOCAL_DEVELOPMENT or not LOG_TO_FILE or not CURRENT_LOG_FILE:
        return
    
    try:
        # APPEND-ONLY approach - read existing, append new, write back
        logs = []
        if os.path.exists(CURRENT_LOG_FILE):
            try:
                with open(CURRENT_LOG_FILE, 'r') as f:
                    logs = json.load(f)
            except (json.JSONDecodeError, IOError):
                logs = []  # Start fresh if file is corrupted
        
        logs.append(log_entry)
        
        with open(CURRENT_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2, default=str)
            
    except Exception as e:
        if LOG_TO_CONSOLE:
            print(f"Warning: Could not write to log file: {e}")

def _finalize_current_log_file(final_game_state):
    """Add final game metadata and close current log file"""
    if not IS_LOCAL_DEVELOPMENT or not CURRENT_LOG_FILE:
        return
        
    finalization_entry = {
        'log_type': 'game_finalization',
        'data': {
            'game_completed_at': datetime.now().isoformat(),
            'final_scores': {
                'player_score': final_game_state.get('player_score', 0),
                'computer_score': final_game_state.get('computer_score', 0)
            },
            'winner': final_game_state.get('winner'),
            'hands_played': final_game_state.get('hand_number', 1),
            'environment': 'local_development'
        }
    }
    
    _write_to_current_log_file(finalization_entry)
    
    if LOG_TO_CONSOLE:
        print(f"Finalized game log: {os.path.basename(CURRENT_LOG_FILE)}")

# =============================================================================
# GAME INITIALIZATION - STREAMLINED
# =============================================================================

def initialize_game_logging(game):
    """Initialize logging structures and start new log file for a new game - NO FILE SCANNING"""
    # Use Unix timestamp with microsecond precision as game ID for easy time correlation
    game_id = str(int(time.time() * 1000000))
    hand_id = str(uuid.uuid4())
    
    game.update({
        'game_id': game_id,
        'current_hand_id': hand_id,
        'game_started_at': time.time(),
        'action_sequence': 0
    })
    
    # Start new log file - NO scanning of existing files
    _start_new_log_file(game_id)
    
    # Log game initialization
    _write_to_current_log_file({
        'log_type': 'game_init',
        'data': {
            'game_id': game_id,
            'started_at': time.time(),
            'player_parity': game.get('player_parity'),
            'computer_parity': game.get('computer_parity'),
            'first_leader': game.get('first_leader')
        }
    })
    
    return game

def initialize_game_logging_with_client(game, request=None):
    """Enhanced game initialization with client tracking - NO FILE SCANNING"""
    game = initialize_game_logging(game)
    
    if request:
        client_info = get_client_info(request)
        game['client_info'] = client_info
        
        # Console output only
        if LOG_TO_CONSOLE:
            print(f"NEW GAME STARTED by {client_info['ip_address']}")
            print(f"   Game ID: {game.get('game_id', 'unknown')}")
    
    return game

def finalize_game_logging(game):
    """Called when a game ends to finalize the log file"""
    _finalize_current_log_file(game)

def start_new_hand_logging(game):
    """Generate new hand ID and log hand start"""
    hand_id = str(uuid.uuid4())
    game['current_hand_id'] = hand_id

# =============================================================================
# CORE LOGGING FUNCTIONS - WRITE ONLY
# =============================================================================

def log_action(action_type, player, action_data, session=None, additional_context=None, request=None):
    """Central logging function for all player/system game actions with optional client tracking"""
    if not LOGGING_ENABLED or not LOG_GAME_ACTIONS:
        return
    
    client_info = get_client_info(request) if request else None
    action_record = _build_action_record(action_type, player, action_data, session, additional_context)
    
    if client_info:
        action_record['client_info'] = client_info
    
    _write_to_current_log_file({
        'log_type': 'action',
        'data': action_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'ACTIONS_ONLY']:
        _print_action_log(action_record)

def log_ai_decision(decision_type, decision_data, analysis=None, reasoning=None, session=None):
    """Central logging function for AI decision-making process"""
    if not LOGGING_ENABLED or not LOG_AI_DECISIONS:
        return
    
    decision_record = _build_ai_decision_record(decision_type, decision_data, analysis, reasoning)
    
    _write_to_current_log_file({
        'log_type': 'ai_decision',
        'data': decision_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'AI_ONLY']:
        _print_ai_decision_log(decision_record)

def log_game_event(event_type, event_data, session=None):
    """Central logging function for major game events"""
    if not LOGGING_ENABLED or not LOG_GAME_EVENTS:
        return
    
    event_record = _build_event_record(event_type, event_data, session)
    
    _write_to_current_log_file({
        'log_type': 'game_event',
        'data': event_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'EVENTS_ONLY']:
        _print_event_log(event_record)

def log_ai_analysis(analysis_type, analysis_data, session=None):
    """Log detailed AI analysis with structured data"""
    if not LOGGING_ENABLED or not LOG_AI_ANALYSIS:
        return
    
    analysis_record = {
        'timestamp': time.time(),
        'analysis_type': analysis_type,
        'analysis_data': analysis_data
    }
    
    _write_to_current_log_file({
        'log_type': 'ai_analysis',
        'data': analysis_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'AI_ONLY']:
        _print_ai_analysis_log(analysis_record)

def log_ai_strategy(strategy_type, strategy_data, session=None):
    """Log AI strategy decisions and evaluations"""
    if not LOGGING_ENABLED or not LOG_AI_ANALYSIS:
        return
    
    strategy_record = {
        'timestamp': time.time(),
        'strategy_type': strategy_type,
        'strategy_data': strategy_data
    }
    
    _write_to_current_log_file({
        'log_type': 'ai_strategy',
        'data': strategy_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'AI_ONLY']:
        _print_ai_strategy_log(strategy_record)

def log_ai_evaluation(evaluation_type, candidates, chosen_candidate, session=None):
    """Log AI evaluation of multiple options"""
    if not LOGGING_ENABLED or not LOG_AI_ANALYSIS:
        return
    
    evaluation_record = {
        'timestamp': time.time(),
        'evaluation_type': evaluation_type,
        'candidates_evaluated': len(candidates),
        'all_candidates': candidates,
        'chosen_candidate': chosen_candidate,
        'confidence': _calculate_evaluation_confidence(candidates, chosen_candidate)
    }
    
    _write_to_current_log_file({
        'log_type': 'ai_evaluation',
        'data': evaluation_record
    })
    
    if LOG_TO_CONSOLE and CONSOLE_LOG_LEVEL in ['ALL', 'AI_ONLY']:
        _print_ai_evaluation_log(evaluation_record)

# =============================================================================
# INTERNAL HELPER FUNCTIONS
# =============================================================================

def _build_action_record(action_type, player, action_data, session, additional_context):
    """Build standardized action record"""
    game = session['game'] if session and 'game' in session else {}
    
    game['action_sequence'] = game.get('action_sequence', 0) + 1
    
    return {
        'sequence': game['action_sequence'],
        'timestamp': time.time(),
        'game_id': game.get('game_id'),
        'hand_id': game.get('current_hand_id'),
        'action_type': action_type,
        'player': player,
        'hand_number': game.get('hand_number', 1),
        'phase': game.get('phase', 'unknown'),
        'action_data': action_data,
        'game_context': {
            'player_score': game.get('player_score', 0),
            'computer_score': game.get('computer_score', 0),
            'player_tricks': game.get('player_tricks', 0),
            'computer_tricks': game.get('computer_tricks', 0),
            'player_bags': game.get('player_bags', 0),
            'computer_bags': game.get('computer_bags', 0),
            'spades_broken': game.get('spades_broken', False),
            'turn': game.get('turn'),
            'trick_leader': game.get('trick_leader')
        },
        'additional_context': additional_context
    }

def _build_ai_decision_record(decision_type, decision_data, analysis, reasoning):
    """Build standardized AI decision record"""
    return {
        'timestamp': time.time(),
        'decision_type': decision_type,
        'decision_data': decision_data,
        'analysis': analysis,
        'reasoning': reasoning,
        'confidence': _calculate_confidence(decision_type, decision_data, analysis)
    }

def _build_event_record(event_type, event_data, session):
    """Build standardized event record"""
    game = session['game'] if session and 'game' in session else {}
    
    return {
        'timestamp': time.time(),
        'game_id': game.get('game_id'),
        'hand_id': game.get('current_hand_id'),
        'event_type': event_type,
        'hand_number': game.get('hand_number', 1),
        'event_data': event_data
    }

def _calculate_confidence(decision_type, decision_data, analysis):
    """Calculate confidence score for AI decisions"""
    if not analysis:
        return 0.5
    
    if decision_type == 'bid':
        expected_tricks = analysis.get('base_expectation', 0)
        bid_amount = decision_data.get('bid_amount', 0)
        diff = abs(expected_tricks - bid_amount)
        return max(0.0, min(1.0, 1.0 - (diff / 5.0)))
    
    elif decision_type == 'discard_choice':
        chosen_score = decision_data.get('final_score', 0)
        if chosen_score >= 1000:
            return 1.0
        elif chosen_score >= 500:
            return 0.9
        else:
            return 0.6
    
    return 0.5

def _calculate_evaluation_confidence(candidates, chosen_candidate):
    """Calculate confidence for AI evaluations"""
    if not candidates or len(candidates) < 2:
        return 1.0
    
    if isinstance(chosen_candidate, dict) and 'score' in chosen_candidate:
        try:
            scores = [c.get('score', 0) for c in candidates if isinstance(c, dict)]
            if scores and len(scores) >= 2:
                best_score = max(scores)
                second_best = sorted(scores, reverse=True)[1]
                if best_score > 0:
                    confidence = min(1.0, (best_score - second_best) / best_score)
                    return max(0.1, confidence)
        except:
            pass
    
    return max(0.3, 1.0 - (len(candidates) * 0.1))

# =============================================================================
# CONSOLE OUTPUT FUNCTIONS
# =============================================================================

def _print_action_log(action_record):
    """Print action log to console with formatting"""
    timestamp_str = datetime.fromtimestamp(action_record['timestamp']).strftime('%H:%M:%S.%f')[:-3]
    
    print(f"=== ACTION #{action_record['sequence']}: {action_record['action_type'].upper()} by {action_record['player'].upper()} ===")
    print(f"Hand #{action_record['hand_number']} | Phase: {action_record['phase']} | Time: {timestamp_str}")
    print(f"Data: {action_record['action_data']}")
    
    ctx = action_record['game_context']
    print(f"Context: Score {ctx['player_score']}-{ctx['computer_score']} | Tricks {ctx['player_tricks']}-{ctx['computer_tricks']} | Bags {ctx['player_bags']}-{ctx['computer_bags']}")
    
    if action_record.get('additional_context'):
        print(f"Extra: {action_record['additional_context']}")
    
    print("=" * 60)

def _print_ai_decision_log(decision_record):
    """Print AI decision log to console with formatting"""
    timestamp_str = datetime.fromtimestamp(decision_record['timestamp']).strftime('%H:%M:%S.%f')[:-3]
    
    print(f"AI DECISION: {decision_record['decision_type'].upper()}")
    print(f"Time: {timestamp_str} | Confidence: {decision_record['confidence']:.2f}")
    print(f"Decision: {decision_record['decision_data']}")
    
    if decision_record.get('analysis'):
        print(f"Analysis: {decision_record['analysis']}")
    
    if decision_record.get('reasoning'):
        print(f"Reasoning: {decision_record['reasoning']}")
    
    print("=" * 58)

def _print_event_log(event_record):
    """Print game event log to console with formatting"""
    print(f"GAME EVENT: {event_record['event_type'].upper()}")
    print(f"Hand #{event_record['hand_number']} | Data: {event_record['event_data']}")
    print("*" * 40)

def _print_ai_analysis_log(analysis_record):
    """Print AI analysis log to console with formatting"""
    timestamp_str = datetime.fromtimestamp(analysis_record['timestamp']).strftime('%H:%M:%S.%f')[:-3]
    
    print(f"AI ANALYSIS: {analysis_record['analysis_type'].upper()}")
    print(f"Time: {timestamp_str}")
    
    for key, value in analysis_record['analysis_data'].items():
        if isinstance(value, (int, float)):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")
    
    print("-" * 40)

def _print_ai_strategy_log(strategy_record):
    """Print AI strategy log to console with formatting"""
    timestamp_str = datetime.fromtimestamp(strategy_record['timestamp']).strftime('%H:%M:%S.%f')[:-3]
    
    print(f"AI STRATEGY: {strategy_record['strategy_type'].upper()}")
    print(f"Time: {timestamp_str}")
    print(f"Strategy: {strategy_record['strategy_data']}")
    print("-" * 40)

def _print_ai_evaluation_log(evaluation_record):
    """Print AI evaluation log to console with formatting"""
    timestamp_str = datetime.fromtimestamp(evaluation_record['timestamp']).strftime('%H:%M:%S.%f')[:-3]
    
    print(f"AI EVALUATION: {evaluation_record['evaluation_type'].upper()}")
    print(f"Time: {timestamp_str} | Confidence: {evaluation_record['confidence']:.2f}")
    print(f"Evaluated {evaluation_record['candidates_evaluated']} options")
    print(f"Chosen: {evaluation_record['chosen_candidate']}")
    
    top_candidates = evaluation_record['all_candidates'][:3]
    for i, candidate in enumerate(top_candidates):
        print(f"  #{i+1}: {candidate}")
    
    if len(evaluation_record['all_candidates']) > 3:
        print(f"  ... and {len(evaluation_record['all_candidates']) - 3} more")
    
    print("-" * 40)

# =============================================================================
# DEBUG ENDPOINTS - FILE READING ONLY ON DEMAND
# =============================================================================

def get_environment_info():
    """Get information about the current environment - NO FILE READING"""
    return {
        'is_local_development': IS_LOCAL_DEVELOPMENT,
        'is_production': IS_PRODUCTION,
        'file_logging_enabled': LOG_TO_FILE,
        'console_logging_enabled': LOG_TO_CONSOLE,
        'gae_env': os.environ.get('GAE_ENV', 'Not set'),
        'platform': platform.system(),
        'logs_directory': LOGS_DIRECTORY,
        'current_log_file': os.path.basename(CURRENT_LOG_FILE) if CURRENT_LOG_FILE else None
    }

def get_logging_summary():
    """Get summary of current session only - NO FILE READING"""
    return {
        'current_log_file': os.path.basename(CURRENT_LOG_FILE) if CURRENT_LOG_FILE else None,
        'logging_enabled': LOGGING_ENABLED,
        'environment': 'local_development' if IS_LOCAL_DEVELOPMENT else 'production',
        'file_logging_available': IS_LOCAL_DEVELOPMENT,
        'message': 'Historical log analysis available via explicit debug endpoints only'
    }

# The following functions are only called by explicit debug routes, never during normal gameplay

def list_game_logs():
    """List all available game log files - ONLY for debug endpoints"""
    if not IS_LOCAL_DEVELOPMENT or not os.path.exists(LOGS_DIRECTORY):
        return []
    
    log_files = []
    for filename in os.listdir(LOGS_DIRECTORY):
        if filename.startswith('game_log_') and filename.endswith('.json'):
            filepath = os.path.join(LOGS_DIRECTORY, filename)
            try:
                parts = filename.replace('game_log_', '').replace('.json', '').split('_')
                if len(parts) >= 3:
                    stat = os.stat(filepath)
                    log_files.append({
                        'filename': filename,
                        'date': parts[0],
                        'time': parts[1],
                        'game_id': parts[2],
                        'size_bytes': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            except Exception:
                pass
    
    return sorted(log_files, key=lambda x: x['modified'], reverse=True)

def get_game_log_summary(filename):
    """Get summary of a specific game log file - ONLY for debug endpoints"""
    if not IS_LOCAL_DEVELOPMENT:
        return {'error': 'File logging not available in production'}
    
    filepath = os.path.join(LOGS_DIRECTORY, filename)
    if not os.path.exists(filepath):
        return {'error': f'Log file not found: {filename}'}
    
    try:
        with open(filepath, 'r') as f:
            logs = json.load(f)
        
        log_counts = {}
        for entry in logs:
            log_type = entry.get('log_type', 'unknown')
            log_counts[log_type] = log_counts.get(log_type, 0) + 1
        
        return {
            'filename': filename,
            'total_entries': len(logs),
            'log_type_counts': log_counts,
            'file_size_kb': round(os.path.getsize(filepath) / 1024, 2)
        }
        
    except Exception as e:
        return {'error': f'Could not analyze log file: {e}'}

# =============================================================================
# CONTROL FUNCTIONS
# =============================================================================

def enable_logging():
    """Enable all logging"""
    global LOGGING_ENABLED
    LOGGING_ENABLED = True
    if LOG_TO_CONSOLE:
        print("Logging ENABLED")

def disable_logging():
    """Disable all logging"""
    global LOGGING_ENABLED
    LOGGING_ENABLED = False
    if LOG_TO_CONSOLE:
        print("Logging DISABLED")

def set_console_log_level(level):
    """Set console logging level"""
    global CONSOLE_LOG_LEVEL
    valid_levels = ['ALL', 'ACTIONS_ONLY', 'AI_ONLY', 'EVENTS_ONLY', 'OFF']
    if level in valid_levels:
        CONSOLE_LOG_LEVEL = level
        if LOG_TO_CONSOLE:
            print(f"Console log level set to: {level}")
    else:
        if LOG_TO_CONSOLE:
            print(f"Invalid log level. Valid options: {valid_levels}")

def toggle_console_logging():
    """Toggle console logging on/off"""
    global LOG_TO_CONSOLE
    LOG_TO_CONSOLE = not LOG_TO_CONSOLE
    print(f"Console logging: {'ON' if LOG_TO_CONSOLE else 'OFF'}")