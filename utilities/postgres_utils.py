"""
Two-Man Spades PostgreSQL Utilities - Updated for Hands Table
"""
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List

def get_monthly_stats_by_location():
    """Get monthly statistics grouped by family member location"""
    query = """
        SELECT 
            DATE_TRUNC('month', h.started_at) as month,
            CASE
                WHEN loc.city = 'Helena' AND loc.region = 'Montana' THEN 'Helena'
                WHEN loc.city IN ('Missoula', 'Blackfoot') AND loc.region = 'Montana' THEN 'Elliston'
                WHEN loc.city IN ('Rocklin', 'Sacramento') AND loc.region = 'California' THEN 'Rocklin'
                WHEN loc.city IN ('Bellevue', 'Seattle', 'Bothell', 'Redmond') AND loc.region = 'Washington' THEN 'Bothell'
                WHEN loc.region = 'Washington' THEN 'Bothell'
                WHEN loc.region = 'Montana' AND loc.city IS NOT NULL THEN 'Helena'
                WHEN loc.region = 'California' AND loc.city IS NOT NULL THEN 'Rocklin'
                ELSE 'Other'
            END as family_member,
            COUNT(DISTINCT h.hand_id) as total_hands,
            COUNT(DISTINCT CASE WHEN h.hand_player_score > h.hand_computer_score THEN h.hand_id END) as hands_won,
            COUNT(DISTINCT CASE WHEN h.hand_player_score < h.hand_computer_score THEN h.hand_id END) as hands_lost,
            COUNT(*) as total_records,
            ROUND(AVG(h.hand_player_score), 2) as avg_player_score,
            ROUND(AVG(h.hand_computer_score), 2) as avg_computer_score,
            SUM(h.player_bags) as total_bags
        FROM twomanspades.hands h
        JOIN twomanspades.players p ON h.player_id = p.player_id
        LEFT JOIN twomanspades.ip_location_data loc ON p.ip_address = loc.ip_address
        WHERE h.completed_at IS NOT NULL
        GROUP BY DATE_TRUNC('month', h.started_at), 
            CASE
                WHEN loc.city = 'Helena' AND loc.region = 'Montana' THEN 'Helena'
                WHEN loc.city IN ('Missoula', 'Blackfoot') AND loc.region = 'Montana' THEN 'Elliston'
                WHEN loc.city IN ('Rocklin', 'Sacramento') AND loc.region = 'California' THEN 'Rocklin'
                WHEN loc.city IN ('Bellevue', 'Seattle', 'Bothell', 'Redmond') AND loc.region = 'Washington' THEN 'Bothell'
                WHEN loc.region = 'Washington' THEN 'Bothell'
                WHEN loc.region = 'Montana' AND loc.city IS NOT NULL THEN 'Helena'
                WHEN loc.region = 'California' AND loc.city IS NOT NULL THEN 'Rocklin'
                ELSE 'Other'
            END
        HAVING CASE
            WHEN loc.city = 'Helena' AND loc.region = 'Montana' THEN 'Helena'
            WHEN loc.city IN ('Missoula', 'Blackfoot') AND loc.region = 'Montana' THEN 'Elliston'
            WHEN loc.city IN ('Rocklin', 'Sacramento') AND loc.region = 'California' THEN 'Rocklin'
            WHEN loc.city IN ('Bellevue', 'Seattle', 'Bothell', 'Redmond') AND loc.region = 'Washington' THEN 'Bothell'
            WHEN loc.region = 'Washington' THEN 'Bothell'
            WHEN loc.region = 'Montana' AND loc.city IS NOT NULL THEN 'Helena'
            WHEN loc.region = 'California' AND loc.city IS NOT NULL THEN 'Rocklin'
            ELSE 'Other'
        END != 'Other'
        ORDER BY family_member, month DESC;
    """
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query)
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    # Organize by family member with current month first
    organized = {}
    for row in results:
        member = row['family_member']
        if member not in organized:
            organized[member] = {'monthly': [], 'lifetime': None}
        organized[member]['monthly'].append(row)
    
    return organized

def get_secret(secret_id: str, project_id: str = "kumori-404602") -> str:
    """Get secret from Google Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_db_connection():
    """Create database connection using TWOMANSPADES secrets"""
    is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
    
    if is_gcp:
        # Production - use secrets and Cloud SQL socket
        connection_name = get_secret('TWOMANSPADES_POSTGRES_CONNECTION_NAME')
        host = f"/cloudsql/{connection_name}"
        dbname = get_secret('TWOMANSPADES_POSTGRES_DB_NAME') 
        user = get_secret('TWOMANSPADES_POSTGRES_USERNAME')
        password = get_secret('TWOMANSPADES_POSTGRES_PASSWORD')
    else:
        # Local development - use environment variables or direct secrets
        try:
            # Try secrets first (in case you want to test with real DB locally)
            host = get_secret('TWOMANSPADES_POSTGRES_IP')
            dbname = get_secret('TWOMANSPADES_POSTGRES_DB_NAME')
            user = get_secret('TWOMANSPADES_POSTGRES_USERNAME')
            password = get_secret('TWOMANSPADES_POSTGRES_PASSWORD')
        except:
            # Fallback to env vars for local dev
            host = os.getenv('DB_HOST', 'localhost')
            dbname = os.getenv('DB_NAME', 'twomanspades_dev')
            user = os.getenv('DB_USER', 'postgres') 
            password = os.getenv('DB_PASSWORD', 'password')
    
    return psycopg2.connect(
        host=host,
        database=dbname,
        user=user,
        password=password,
        connect_timeout=10
    )

def test_connection():
    """Test database connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"PostgreSQL connection successful: {version[0]}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False

def insert_hand(hand_data: Dict[str, Any]) -> bool:
    """Insert new hand record"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Debug: print what we're trying to insert
        print(f"Attempting to insert hand: {hand_data.get('hand_id')}")
        
        cur.execute("""
            INSERT INTO twomanspades.hands 
            (hand_id, started_at, player_parity, computer_parity, first_leader, client_ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            hand_data['hand_id'],
            datetime.fromtimestamp(hand_data['game_started_at']),  # Still using game_started_at from session
            hand_data['player_parity'],
            hand_data['computer_parity'], 
            hand_data['first_leader'],
            hand_data.get('client_info', {}).get('ip_address'),
            hand_data.get('client_info', {}).get('user_agent')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"Hand {hand_data.get('hand_id')} successfully inserted")
        return True
    except Exception as e:
        print(f"Failed to insert hand {hand_data.get('hand_id')}: {e}")
        # Try to close connection if it exists
        try:
            if 'conn' in locals():
                conn.close()
        except:
            pass
        return False

def log_game_event_to_db(hand_id: str, event_type: str, event_data: Dict, **kwargs) -> bool:
    """Log game event to database using hand_id"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO twomanspades.game_events 
            (hand_id, event_type, event_data, hand_number, session_sequence, 
             player, action_type, client_ip, google_email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            hand_id,
            event_type,
            json.dumps(event_data),
            kwargs.get('hand_number'),
            kwargs.get('session_sequence'),
            kwargs.get('player'),
            kwargs.get('action_type'),
            kwargs.get('client_ip'),
            kwargs.get('google_email')  # Add this
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to log event: {e}")
        return False

def finalize_hand(hand_id: str, final_data: Dict[str, Any]) -> bool:
    """Update hand record when hand completes"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE twomanspades.hands 
            SET completed_at = %s,
                hand_player_score = %s,
                hand_computer_score = %s,
                player_bags = %s,
                computer_bags = %s
            WHERE hand_id = %s
        """, (
            datetime.now(),
            final_data.get('player_score', 0),
            final_data.get('computer_score', 0),
            final_data.get('player_bags', 0),
            final_data.get('computer_bags', 0),
            hand_id
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to finalize hand: {e}")
        return False

def upsert_player(ip_address: str, user_agent: str = None) -> Optional[int]:
    """Create or update player record, return player_id"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO twomanspades.players (ip_address, user_agent_latest, total_games)
            VALUES (%s, %s, 0)
            ON CONFLICT (ip_address) DO UPDATE SET
                last_seen = NOW(),
                user_agent_latest = COALESCE(EXCLUDED.user_agent_latest, players.user_agent_latest)
            RETURNING player_id
        """, (ip_address, user_agent))
        
        player_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return player_id
    except Exception as e:
        print(f"Failed to upsert player: {e}")
        return None


def batch_log_events(hand_id: str, events: List[Dict]) -> bool:
    """Log multiple events in a single database transaction"""
    if not events:
        return True
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        events_data = []
        for event in events:
            events_data.append((
                hand_id,
                event.get('event_type'),
                json.dumps(event.get('event_data', {})),
                event.get('hand_number'),
                event.get('session_sequence'),
                event.get('player'),
                event.get('action_type'),
                event.get('client_ip'),
                event.get('google_email')  # Add this
            ))
        
        cur.executemany("""
            INSERT INTO twomanspades.game_events 
            (hand_id, event_type, event_data, hand_number, session_sequence, 
             player, action_type, client_ip, google_email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, events_data)
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Batch event logging failed: {e}")
        try:
            if 'conn' in locals():
                conn.rollback()
                conn.close()
        except:
            pass
        return False


def create_hand_with_player(hand_data: Dict[str, Any], client_info: Dict[str, Any] = None) -> bool:
    """Create hand and update player in single transaction"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        player_id = None
        google_email = None
        google_id = None
        
        if client_info:
            ip_address = client_info.get('ip_address')
            user_agent = client_info.get('user_agent')
            
            # Extract Google auth if available
            google_auth = client_info.get('google_auth')
            if google_auth:
                google_email = google_auth.get('email')
                google_id = google_auth.get('google_id')
            
            # Update player record with Google info
            if google_auth:
                cur.execute("""
                    INSERT INTO twomanspades.players 
                    (ip_address, user_agent_latest, total_hands, 
                     google_email, google_name, google_id, google_picture_url,
                     first_google_login, last_google_login)
                    VALUES (%s, %s, 1, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (ip_address) DO UPDATE SET
                        last_seen = NOW(),
                        user_agent_latest = EXCLUDED.user_agent_latest,
                        total_hands = players.total_hands + 1,
                        google_email = COALESCE(EXCLUDED.google_email, players.google_email),
                        google_name = COALESCE(EXCLUDED.google_name, players.google_name),
                        google_id = COALESCE(EXCLUDED.google_id, players.google_id),
                        google_picture_url = COALESCE(EXCLUDED.google_picture_url, players.google_picture_url),
                        last_google_login = NOW()
                    RETURNING player_id
                """, (
                    ip_address, user_agent,
                    google_email,
                    google_auth.get('name'),
                    google_id,
                    google_auth.get('picture')
                ))
            else:
                # Anonymous user
                cur.execute("""
                    INSERT INTO twomanspades.players (ip_address, user_agent_latest, total_hands)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (ip_address) DO UPDATE SET
                        last_seen = NOW(),
                        user_agent_latest = EXCLUDED.user_agent_latest,
                        total_hands = players.total_hands + 1
                    RETURNING player_id
                """, (ip_address, user_agent))
            
            player_id = cur.fetchone()[0]
        
        # Insert hand record WITH google_email and google_id
        cur.execute("""
            INSERT INTO twomanspades.hands 
            (hand_id, started_at, player_parity, computer_parity, first_leader, 
             client_ip, user_agent, player_id, google_email, google_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            hand_data['current_hand_id'],
            datetime.fromtimestamp(hand_data['game_started_at']),
            hand_data['player_parity'],
            hand_data['computer_parity'], 
            hand_data['first_leader'],
            client_info.get('ip_address') if client_info else None,
            client_info.get('user_agent') if client_info else None,
            player_id,
            google_email,  # Add this
            google_id      # Add this
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to create hand with player: {e}")
        try:
            if 'conn' in locals():
                conn.rollback()
                conn.close()
        except:
            pass
        return False

# Legacy function names for backward compatibility
def insert_game(game_data: Dict[str, Any]) -> bool:
    """Legacy wrapper - use insert_hand instead"""
    return insert_hand(game_data)

def finalize_game(game_id: str, final_data: Dict[str, Any]) -> bool:
    """Legacy wrapper - use finalize_hand instead"""
    return finalize_hand(game_id, final_data)

def create_game_with_player(game_data: Dict[str, Any], client_info: Dict[str, Any] = None) -> bool:
    """Legacy wrapper - use create_hand_with_player instead"""
    return create_hand_with_player(game_data, client_info)

def get_ip_address_game_stats(client_ip: str = None) -> List[Dict[str, Any]]:
    """Get game statistics from the view, optionally filtered by IP address"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        if client_ip:
            cur.execute("""
                SELECT * FROM twomanspades.vw_ip_address_game_win_loss_stats 
                WHERE client_ip = %s
                ORDER BY total_games DESC, win_rate DESC
            """, (client_ip,))
        else:
            cur.execute("""
                SELECT * FROM twomanspades.vw_ip_address_game_win_loss_stats 
                ORDER BY total_games DESC, win_rate DESC
            """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        # Convert to list of dicts for easier handling
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get game stats: {e}")
        return []
    
# Replace the save_ip_location_data function in postgres_utils.py

def save_ip_location_data(ip_address: str, location_data: Dict[str, Any]) -> bool:
    """Save IP location data - ONLY data that comes from the IP API call"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO twomanspades.ip_location_data 
            (ip_address, country, region, city, latitude, longitude, timezone, zip_code,
             isp, org, as_info, lookup_success)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ip_address) DO UPDATE SET
                country = EXCLUDED.country,
                region = EXCLUDED.region,
                city = EXCLUDED.city,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                timezone = EXCLUDED.timezone,
                zip_code = EXCLUDED.zip_code,
                isp = EXCLUDED.isp,
                org = EXCLUDED.org,
                as_info = EXCLUDED.as_info,
                lookup_success = EXCLUDED.lookup_success,
                created_at = NOW()
        """, (
            ip_address,
            location_data.get('country'),
            location_data.get('region'),
            location_data.get('city'),
            location_data.get('lat'),
            location_data.get('lon'),
            location_data.get('timezone'),
            location_data.get('zip'),
            location_data.get('isp'),
            location_data.get('org'),
            location_data.get('as'),  # Store the full AS string
            True  # lookup_success
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Failed to save IP location data for {ip_address}: {e}")
        try:
            if 'conn' in locals():
                conn.rollback()
                conn.close()
        except:
            pass
        return False

def save_failed_ip_lookup(ip_address: str) -> bool:
    """Save a record for failed IP lookup"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO twomanspades.ip_location_data (ip_address, lookup_success)
            VALUES (%s, %s)
            ON CONFLICT (ip_address) DO UPDATE SET
                lookup_success = EXCLUDED.lookup_success,
                created_at = NOW()
        """, (ip_address, False))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Failed to save failed lookup for {ip_address}: {e}")
        return False

def get_player_city_membership(client_ip):
    """Get which city/family member this IP belongs to"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Query the ip_location_data to determine city mapping
        cur.execute("""
            SELECT city, region, country FROM twomanspades.ip_location_data 
            WHERE ip_address = %s AND lookup_success = true
        """, (client_ip,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if not result:
            return 'Other'
            
        city, region, country = result
        
        # Apply the same logic as the view
        if city == 'Helena' and region == 'Montana':
            return 'Helena'
        elif city in ['Missoula', 'Blackfoot'] and region == 'Montana':
            return 'Elliston'
        elif city in ['Rocklin', 'Sacramento'] and region == 'California':
            return 'Rocklin'
        elif city in ['Bellevue', 'Seattle', 'Bothell', 'Redmond'] and region == 'Washington':
            return 'Bothell'
        elif region == 'Washington':
            return 'Bothell'
        elif region == 'Montana' and city:
            return 'Helena'
        elif region == 'California' and city:
            return 'Rocklin'
        else:
            return 'Other'
            
    except Exception as e:
        print(f"Failed to get player city membership: {e}")
        return 'Other'
    
def get_unified_leaderboard() -> List[Dict[str, Any]]:
    """Get unified leaderboard from vw_unified_leaderboard view.
    Combines Google-auth games with location-inferred games for known players:
    Tom (Helena/MT), Luke (Rocklin/CA + Virginia), Andy (Seattle/WA), Jon (Elliston/MT).
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT * FROM twomanspades.vw_unified_leaderboard")

        results = cur.fetchall()
        cur.close()
        conn.close()

        return [dict(row) for row in results]

    except Exception as e:
        print(f"Failed to get unified leaderboard: {e}")
        return []


def get_google_players_leaderboard() -> List[Dict[str, Any]]:
    """Legacy function - now wraps get_unified_leaderboard for backward compatibility"""
    return get_unified_leaderboard()

def get_competitive_leaders_stats() -> List[Dict[str, Any]]:
    """Get competitive win/loss records from vw_city_leaders view"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT family_member, unique_ips, games_started, total_games, 
                   games_abandoned, total_wins, total_losses, win_rate_percent,
                   avg_winning_score, avg_winning_margin, avg_losing_score, avg_losing_margin
            FROM twomanspades.vw_city_leaders 
            ORDER BY win_rate_percent DESC, total_games DESC
        """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get competitive leaders stats: {e}")
        return []


def get_city_leaders_stats() -> List[Dict[str, Any]]:
    """Get detailed hand performance stats from vw_city_leaders_totals view"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT family_member, total_hands_with_bids, total_hands_with_scoring,
                   avg_player_bid, avg_computer_bid, total_player_nil_bids,
                   total_player_nils_successful,
                   total_player_bags, total_computer_bags, 
                   avg_player_bags, avg_computer_bags
            FROM twomanspades.vw_city_leaders_totals 
            ORDER BY total_hands_with_bids DESC
        """)
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get city leaders stats: {e}")
        return []


def get_fun_stats() -> Dict[str, Any]:
    """Get fun/interesting stats for display.
    Uses game_completed events as source of truth for finished games."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        stats = {}

        # Total hands played (all completed hands, not just games)
        cur.execute('SELECT COUNT(DISTINCT hand_id) FROM twomanspades.hands WHERE completed_at IS NOT NULL')
        stats['total_hands'] = cur.fetchone()[0]

        # Total completed GAMES - from game_completed events (authoritative source)
        cur.execute("SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = 'game_completed'")
        stats['total_games'] = cur.fetchone()[0]

        cur.execute('SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = %s', ('trick_completed',))
        stats['total_tricks'] = cur.fetchone()[0]

        # Win/loss from game_completed events (authoritative source)
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END),
                SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END)
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
        ''')
        row = cur.fetchone()
        stats['human_wins'] = row[0] or 0
        stats['marta_wins'] = row[1] or 0
        total = stats['human_wins'] + stats['marta_wins']
        stats['human_win_pct'] = round(100 * stats['human_wins'] / total, 1) if total > 0 else 0

        # Bid distribution
        cur.execute('''
            SELECT
                (event_data->'action_data'->>'bid_amount')::int as bid,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'action_regular_bid' AND player = 'player'
            GROUP BY (event_data->'action_data'->>'bid_amount')::int
            ORDER BY 1
        ''')
        stats['bid_distribution'] = [{'bid': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Average game length - from game_completed events
        cur.execute('''
            SELECT
                ROUND(AVG((event_data->>'hands_played')::int), 1),
                MIN((event_data->>'hands_played')::int),
                MAX((event_data->>'hands_played')::int)
            FROM twomanspades.game_events
            WHERE event_type = 'game_completed'
            AND event_data->>'hands_played' IS NOT NULL
        ''')
        row = cur.fetchone()
        stats['avg_game_length'] = row[0]
        stats['shortest_game'] = row[1]
        stats['longest_game'] = row[2]

        cur.close()
        conn.close()
        return stats

    except Exception as e:
        print(f"Failed to get fun stats: {e}")
        return {}


def get_player_achievements() -> Dict[str, Any]:
    """Get notable achievements for all known players (Tom/Luke/Jon/Andy).
    Uses vw_player_game_details view (based on game_completed events)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Bid accuracy - uses player identity from view
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            tricks_data AS (
                SELECT hand_id, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                GROUP BY hand_id
            )
            SELECT
                b.player,
                COUNT(*) as hands,
                ROUND(AVG(b.bid), 2) as avg_bid,
                ROUND(AVG(COALESCE(t.player_tricks, 0)), 2) as avg_tricks,
                SUM(CASE WHEN COALESCE(t.player_tricks, 0) = b.bid THEN 1 ELSE 0 END) as exact_bids,
                ROUND(100.0 * SUM(CASE WHEN COALESCE(t.player_tricks, 0) = b.bid THEN 1 ELSE 0 END) / COUNT(*), 1) as exact_pct
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id
            GROUP BY b.player ORDER BY exact_pct DESC
        ''')
        bid_accuracy = [dict(row) for row in cur.fetchall()]

        # Nil stats
        cur.execute('''
            WITH nil_bids AS (
                SELECT v.player_name as player, ge.hand_id
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND (ge.event_data->'action_data'->>'bid_amount') = '0'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            nil_results AS (
                SELECT n.player, n.hand_id, COALESCE(COUNT(t.*), 0) as tricks_taken
                FROM nil_bids n
                LEFT JOIN twomanspades.game_events t ON n.hand_id = t.hand_id
                    AND t.event_type = 'trick_completed' AND t.event_data->>'winner' = 'player'
                GROUP BY n.player, n.hand_id
            )
            SELECT player, COUNT(*) as attempts,
                SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) as successful,
                ROUND(100.0 * SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as rate
            FROM nil_results GROUP BY player ORDER BY attempts DESC
        ''')
        nil_stats = [dict(row) for row in cur.fetchall()]

        # Closest wins (Nail-biters) - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT player_name as player, final_player_score, final_computer_score,
                   margin, player_bags
            FROM twomanspades.vw_player_game_details
            WHERE won = true AND player_name != 'Other'
            AND final_player_score IS NOT NULL
            ORDER BY margin ASC LIMIT 5
        ''')
        closest_wins = [dict(row) for row in cur.fetchall()]

        # Biggest blowouts - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT player_name as player, final_player_score, final_computer_score,
                   margin, player_bags
            FROM twomanspades.vw_player_game_details
            WHERE won = true AND player_name != 'Other'
            AND final_player_score IS NOT NULL
            ORDER BY margin DESC LIMIT 5
        ''')
        biggest_wins = [dict(row) for row in cur.fetchall()]

        # Current streaks - both wins AND losses (actual counts, not capped)
        cur.execute('''
            WITH recent_games AS (
                SELECT
                    player_name as player,
                    completed_at,
                    won,
                    ROW_NUMBER() OVER (PARTITION BY player_name ORDER BY completed_at DESC) as rn
                FROM twomanspades.vw_player_game_details
                WHERE player_name IS NOT NULL AND player_name != 'Other'
            ),
            win_streaks AS (
                SELECT player,
                    MIN(CASE WHEN NOT won THEN rn ELSE 9999 END) - 1 as streak
                FROM recent_games
                GROUP BY player
                HAVING MIN(CASE WHEN NOT won THEN rn ELSE 9999 END) > 1
            ),
            loss_streaks AS (
                SELECT player,
                    MIN(CASE WHEN won THEN rn ELSE 9999 END) - 1 as streak
                FROM recent_games
                GROUP BY player
                HAVING MIN(CASE WHEN won THEN rn ELSE 9999 END) > 1
            )
            SELECT 'win' as streak_type, player, streak FROM win_streaks WHERE streak > 0
            UNION ALL
            SELECT 'loss' as streak_type, player, streak FROM loss_streaks WHERE streak > 1
            ORDER BY streak DESC
        ''')
        all_streaks = [dict(row) for row in cur.fetchall()]
        win_streaks = [s for s in all_streaks if s['streak_type'] == 'win']
        loss_streaks = [s for s in all_streaks if s['streak_type'] == 'loss']

        # Overbid stats (bags per hand) - bags = overbidding penalty
        cur.execute('''
            SELECT
                player_name as player,
                SUM(player_bags) as total_bags,
                SUM(hands_played) as total_hands,
                ROUND(SUM(player_bags)::numeric / NULLIF(SUM(hands_played), 0), 2) as bags_per_hand,
                COUNT(*) as games
            FROM twomanspades.vw_player_game_details
            WHERE player_name IS NOT NULL AND player_name != 'Other'
            AND player_bags IS NOT NULL
            GROUP BY player_name
            ORDER BY bags_per_hand DESC
        ''')
        bag_stats = [dict(row) for row in cur.fetchall()]

        # Most common bid per player
        cur.execute('''
            WITH bid_counts AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    COUNT(*) as times
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                GROUP BY v.player_name, (ge.event_data->'action_data'->>'bid_amount')::int
            ),
            ranked AS (
                SELECT player, bid, times,
                    ROW_NUMBER() OVER (PARTITION BY player ORDER BY times DESC) as rn
                FROM bid_counts
            )
            SELECT player, bid as favorite_bid, times
            FROM ranked WHERE rn = 1
            ORDER BY times DESC
        ''')
        favorite_bids = [dict(row) for row in cur.fetchall()]

        # Worst losses - from vw_player_game_details with parsed scores
        cur.execute('''
            SELECT player_name as player, final_player_score, final_computer_score,
                   final_computer_score - final_player_score as margin, player_bags
            FROM twomanspades.vw_player_game_details
            WHERE won = false AND player_name != 'Other'
            AND final_player_score IS NOT NULL
            ORDER BY (final_computer_score - final_player_score) DESC LIMIT 5
        ''')
        worst_losses = [dict(row) for row in cur.fetchall()]

        # Blind bid stats - when offered blind (down 100+), did they take it and succeed?
        cur.execute('''
            WITH blind_decisions AS (
                SELECT
                    v.player_name as player,
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'action_data'->>'chose_blind')::boolean as chose_blind
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_blind_decision'
                AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            blind_bids AS (
                SELECT
                    v.player_name as player,
                    ge.hand_id,
                    ge.hand_number,
                    (ge.event_data->'action_data'->>'bid_amount')::int as blind_bid
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_blind_bid'
                AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            ),
            hand_results AS (
                SELECT hand_id, hand_number,
                    SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as tricks_won
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                d.player,
                COUNT(*) as times_offered,
                SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END) as times_went_blind,
                SUM(CASE WHEN d.chose_blind AND COALESCE(hr.tricks_won, 0) >= bb.blind_bid THEN 1 ELSE 0 END) as blind_successes,
                ROUND(100.0 * SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as blind_rate,
                ROUND(100.0 * SUM(CASE WHEN d.chose_blind AND COALESCE(hr.tricks_won, 0) >= bb.blind_bid THEN 1 ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN d.chose_blind THEN 1 ELSE 0 END), 0), 1) as blind_success_rate
            FROM blind_decisions d
            LEFT JOIN blind_bids bb ON d.hand_id = bb.hand_id AND d.hand_number = bb.hand_number AND d.player = bb.player
            LEFT JOIN hand_results hr ON d.hand_id = hr.hand_id AND d.hand_number = hr.hand_number
            GROUP BY d.player
            HAVING COUNT(*) >= 3
            ORDER BY times_offered DESC
        ''')
        blind_stats = [dict(row) for row in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            'bid_accuracy': bid_accuracy,
            'nil_stats': nil_stats,
            'closest_wins': closest_wins,
            'biggest_wins': biggest_wins,
            'win_streaks': win_streaks,
            'loss_streaks': loss_streaks,
            'bag_stats': bag_stats,
            'favorite_bids': favorite_bids,
            'worst_losses': worst_losses,
            'blind_stats': blind_stats
        }

    except Exception as e:
        print(f"Failed to get player achievements: {e}")
        return {}


def get_special_card_stats() -> Dict[str, Any]:
    """Get stats about the special cards (10 of clubs, 7 of diamonds).
    Uses vw_player_identity for consistent player mapping."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Overall special card captures
        cur.execute('''
            SELECT
                CASE WHEN event_data->>'beneficiary' = 'You' THEN 'Players' ELSE 'Marta' END as winner,
                CASE
                    WHEN event_data->>'explanation' LIKE '%10%' THEN '10 of Clubs'
                    WHEN event_data->>'explanation' LIKE '%7%' THEN '7 of Diamonds'
                END as card,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
            GROUP BY 1, 2
            ORDER BY card, winner
        ''')
        overall_captures = [dict(row) for row in cur.fetchall()]

        # Special card captures by player - uses vw_player_identity for unified mapping
        cur.execute('''
            SELECT
                COALESCE(v.player_name, 'Other') as player,
                SUM(CASE WHEN ge.event_data->>'explanation' LIKE '%10%' THEN 1 ELSE 0 END) as ten_clubs,
                SUM(CASE WHEN ge.event_data->>'explanation' LIKE '%7%' THEN 1 ELSE 0 END) as seven_diamonds,
                COUNT(*) as total_special,
                SUM((ge.event_data->>'bag_reduction')::int) as total_bags_saved
            FROM twomanspades.game_events ge
            JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
            WHERE ge.event_type = 'special_card_effect'
            AND ge.event_data->>'beneficiary' = 'You'
            AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            GROUP BY COALESCE(v.player_name, 'Other')
            ORDER BY total_special DESC
        ''')
        player_captures = [dict(row) for row in cur.fetchall()]

        # Win rate when capturing special cards - uses game_completed events
        cur.execute('''
            WITH special_games AS (
                SELECT DISTINCT ge.hand_id, v.player_name
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'special_card_effect'
                AND ge.event_data->>'beneficiary' = 'You'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
            )
            SELECT
                sg.player_name as player,
                COUNT(*) as games_with_special,
                SUM(CASE WHEN gc.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as wins,
                ROUND(100.0 * SUM(CASE WHEN gc.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
            FROM special_games sg
            JOIN twomanspades.game_events gc ON sg.hand_id = gc.hand_id
            WHERE gc.event_type = 'game_completed'
            GROUP BY sg.player_name
            ORDER BY games_with_special DESC
        ''')
        win_rate_with_special = [dict(row) for row in cur.fetchall()]

        # Marta's special card captures (for comparison)
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'explanation' LIKE '%10%' THEN 1 ELSE 0 END) as ten_clubs,
                SUM(CASE WHEN event_data->>'explanation' LIKE '%7%' THEN 1 ELSE 0 END) as seven_diamonds,
                COUNT(*) as total
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
            AND event_data->>'beneficiary' = 'Marta'
        ''')
        marta_captures = dict(cur.fetchone())

        # Total special card appearances
        cur.execute('''
            SELECT COUNT(*) as total_appearances
            FROM twomanspades.game_events
            WHERE event_type = 'special_card_effect'
        ''')
        total = cur.fetchone()['total_appearances']

        cur.close()
        conn.close()

        return {
            'overall_captures': overall_captures,
            'player_captures': player_captures,
            'win_rate_with_special': win_rate_with_special,
            'marta_captures': marta_captures,
            'total_appearances': total
        }

    except Exception as e:
        print(f"Failed to get special card stats: {e}")
        return {}


def get_overall_game_stats() -> Dict[str, Any]:
    """Get fun overall game statistics across all players - big numbers and interesting data."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        stats = {}

        # Total points scored ever (all completed hands)
        cur.execute('''
            SELECT
                SUM(hand_player_score) as total_player_points,
                SUM(hand_computer_score) as total_computer_points,
                SUM(hand_player_score) + SUM(hand_computer_score) as grand_total_points
            FROM twomanspades.hands
            WHERE completed_at IS NOT NULL
            AND hand_player_score IS NOT NULL
        ''')
        points = dict(cur.fetchone())
        stats['total_player_points'] = points['total_player_points'] or 0
        stats['total_computer_points'] = points['total_computer_points'] or 0
        stats['grand_total_points'] = points['grand_total_points'] or 0

        # Total bags accumulated
        cur.execute('''
            SELECT
                SUM(player_bags) as total_player_bags,
                SUM(computer_bags) as total_computer_bags
            FROM twomanspades.hands
            WHERE completed_at IS NOT NULL
        ''')
        bags = dict(cur.fetchone())
        stats['total_player_bags'] = bags['total_player_bags'] or 0
        stats['total_computer_bags'] = bags['total_computer_bags'] or 0

        # Total cards played (13 cards per hand, 2 players)
        cur.execute('SELECT COUNT(*) FROM twomanspades.game_events WHERE event_type = %s', ('trick_completed',))
        tricks = cur.fetchone()['count']
        stats['total_cards_played'] = tricks * 2  # 2 cards per trick

        # Nil attempts and success rate overall
        cur.execute('''
            WITH nil_bids AS (
                SELECT ge.hand_id
                FROM twomanspades.game_events ge
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND (ge.event_data->'action_data'->>'bid_amount') = '0'
            ),
            nil_results AS (
                SELECT n.hand_id, COALESCE(COUNT(t.*), 0) as tricks_taken
                FROM nil_bids n
                LEFT JOIN twomanspades.game_events t ON n.hand_id = t.hand_id
                    AND t.event_type = 'trick_completed' AND t.event_data->>'winner' = 'player'
                GROUP BY n.hand_id
            )
            SELECT
                COUNT(*) as total_nil_attempts,
                SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) as successful_nils,
                ROUND(100.0 * SUM(CASE WHEN tricks_taken = 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as nil_success_rate
            FROM nil_results
        ''')
        nil = dict(cur.fetchone())
        stats['total_nil_attempts'] = nil['total_nil_attempts'] or 0
        stats['successful_nils'] = nil['successful_nils'] or 0
        stats['nil_success_rate'] = nil['nil_success_rate'] or 0

        # Highest single game score ever
        cur.execute('''
            SELECT
                MAX(hand_player_score) as highest_player_score,
                MAX(hand_computer_score) as highest_computer_score
            FROM twomanspades.hands
            WHERE completed_at IS NOT NULL
        ''')
        highest = dict(cur.fetchone())
        stats['highest_player_score_ever'] = highest['highest_player_score']
        stats['highest_computer_score_ever'] = highest['highest_computer_score']

        # Lowest winning score (closest game)
        cur.execute('''
            SELECT
                v.final_player_score,
                v.final_computer_score,
                v.player_name
            FROM twomanspades.vw_player_game_details v
            WHERE v.won = true
            ORDER BY v.final_player_score ASC
            LIMIT 1
        ''')
        lowest_win = cur.fetchone()
        if lowest_win:
            stats['lowest_winning_score'] = lowest_win['final_player_score']
            stats['lowest_win_opponent_score'] = lowest_win['final_computer_score']

        # Biggest comeback (largest negative to positive swing)
        cur.execute('''
            WITH game_scores AS (
                SELECT
                    hand_id,
                    event_data->>'player_score' as player_score,
                    event_data->>'computer_score' as computer_score,
                    hand_number
                FROM twomanspades.game_events
                WHERE event_type = 'hand_complete'
            )
            SELECT
                hand_id,
                MIN((player_score)::int - (computer_score)::int) as worst_deficit
            FROM game_scores
            GROUP BY hand_id
            HAVING MIN((player_score)::int - (computer_score)::int) < -100
            ORDER BY worst_deficit ASC
            LIMIT 1
        ''')
        comeback = cur.fetchone()
        if comeback:
            # Check if this game was won
            cur.execute('''
                SELECT event_data->>'winner' as winner
                FROM twomanspades.game_events
                WHERE hand_id = %s AND event_type = 'game_completed'
            ''', (comeback['hand_id'],))
            result = cur.fetchone()
            if result and result['winner'] == 'player':
                stats['biggest_comeback_deficit'] = abs(comeback['worst_deficit'])

        # Spades broken stats
        cur.execute('''
            SELECT COUNT(*) as times_spades_broken
            FROM twomanspades.game_events
            WHERE event_type = 'spades_broken'
        ''')
        stats['times_spades_broken'] = cur.fetchone()['times_spades_broken']

        # Average tricks per hand won by players vs Marta
        cur.execute('''
            SELECT
                SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as player_tricks,
                SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END) as computer_tricks
            FROM twomanspades.game_events
            WHERE event_type = 'trick_completed'
        ''')
        trick_wins = dict(cur.fetchone())
        stats['total_player_tricks'] = trick_wins['player_tricks'] or 0
        stats['total_computer_tricks'] = trick_wins['computer_tricks'] or 0

        # Most popular bid overall
        cur.execute('''
            SELECT
                (event_data->'action_data'->>'bid_amount')::int as bid,
                COUNT(*) as times
            FROM twomanspades.game_events
            WHERE event_type = 'action_regular_bid' AND player = 'player'
            GROUP BY (event_data->'action_data'->>'bid_amount')::int
            ORDER BY times DESC
            LIMIT 1
        ''')
        popular = cur.fetchone()
        if popular:
            stats['most_popular_bid'] = popular['bid']
            stats['most_popular_bid_times'] = popular['times']

        # Blind nil stats
        cur.execute('''
            SELECT
                COUNT(*) as blind_nil_attempts,
                SUM(CASE WHEN event_data->>'result' = 'success' THEN 1 ELSE 0 END) as blind_nil_successes
            FROM twomanspades.game_events
            WHERE event_type = 'blind_nil_result'
        ''')
        blind = cur.fetchone()
        if blind and blind['blind_nil_attempts']:
            stats['blind_nil_attempts'] = blind['blind_nil_attempts']
            stats['blind_nil_successes'] = blind['blind_nil_successes'] or 0

        # First game ever date
        cur.execute('''
            SELECT MIN(started_at) as first_game
            FROM twomanspades.hands
        ''')
        first = cur.fetchone()
        if first and first['first_game']:
            stats['first_game_date'] = first['first_game'].strftime('%B %d, %Y')

        cur.close()
        conn.close()
        return stats

    except Exception as e:
        print(f"Failed to get overall game stats: {e}")
        return {}


def get_per_hand_stats() -> Dict[str, Any]:
    """Get fun per-hand statistics - things that happen within individual hands.
    Note: hand_id is actually a game_id, hand_number identifies hands within a game."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        stats = {}

        # Most overtricks in a single hand (biggest overbid) - using hand_number to identify individual hands
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id,
                    ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            tricks_data AS (
                SELECT hand_id, hand_number, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                b.bid,
                COALESCE(t.player_tricks, 0) as tricks_won,
                COALESCE(t.player_tricks, 0) - b.bid as overtricks
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id AND b.hand_number = t.hand_number
            WHERE b.bid > 0 AND COALESCE(t.player_tricks, 0) <= 13
            ORDER BY (COALESCE(t.player_tricks, 0) - b.bid) DESC
            LIMIT 5
        ''')
        stats['biggest_overtricks'] = [dict(row) for row in cur.fetchall()]

        # Most underbid (set by most) - bid high, won few
        cur.execute('''
            WITH bid_data AS (
                SELECT
                    v.player_name as player,
                    (ge.event_data->'action_data'->>'bid_amount')::int as bid,
                    ge.hand_id,
                    ge.hand_number
                FROM twomanspades.game_events ge
                JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
                WHERE ge.event_type = 'action_regular_bid' AND ge.player = 'player'
                AND v.player_name IS NOT NULL AND v.player_name != 'Other'
                AND ge.hand_number IS NOT NULL
            ),
            tricks_data AS (
                SELECT hand_id, hand_number, COUNT(*) as player_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed' AND event_data->>'winner' = 'player'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                b.player,
                b.bid,
                COALESCE(t.player_tricks, 0) as tricks_won,
                b.bid - COALESCE(t.player_tricks, 0) as undertricks
            FROM bid_data b
            LEFT JOIN tricks_data t ON b.hand_id = t.hand_id AND b.hand_number = t.hand_number
            WHERE b.bid > 0 AND COALESCE(t.player_tricks, 0) < b.bid
            ORDER BY (b.bid - COALESCE(t.player_tricks, 0)) DESC
            LIMIT 5
        ''')
        stats['biggest_sets'] = [dict(row) for row in cur.fetchall()]

        # Average tricks per hand won (using hand_number to get per-hand averages)
        cur.execute('''
            WITH hand_tricks AS (
                SELECT
                    hand_id,
                    hand_number,
                    SUM(CASE WHEN event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as player_tricks,
                    SUM(CASE WHEN event_data->>'winner' = 'computer' THEN 1 ELSE 0 END) as computer_tricks
                FROM twomanspades.game_events
                WHERE event_type = 'trick_completed'
                AND hand_number IS NOT NULL
                GROUP BY hand_id, hand_number
            )
            SELECT
                ROUND(AVG(player_tricks), 2) as avg_player_tricks,
                ROUND(AVG(computer_tricks), 2) as avg_computer_tricks
            FROM hand_tricks
            WHERE player_tricks + computer_tricks = 13
        ''')
        avg_tricks = cur.fetchone()
        stats['avg_player_tricks_per_hand'] = avg_tricks['avg_player_tricks']
        stats['avg_computer_tricks_per_hand'] = avg_tricks['avg_computer_tricks']

        cur.close()
        conn.close()
        return stats

    except Exception as e:
        print(f"Failed to get per-hand stats: {e}")
        return {}