"""Two-Man Spades players database operations."""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import os
import threading
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List
from .connection import get_db_connection
from .connection import return_db_connection

def get_monthly_stats_by_location():
    """Get monthly statistics grouped by family member location"""
    conn = None
    try:
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
        return_db_connection(conn)
    
        # Organize by family member with current month first
        organized = {}
        for row in results:
            member = row['family_member']
            if member not in organized:
                organized[member] = {'monthly': [], 'lifetime': None}
            organized[member]['monthly'].append(row)
    
        return organized
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_suspected_player_from_ip(ip_address: str) -> Optional[str]:
    """Get suspected player name based on IP location mapping.
    Returns player name (Tom, Luke, Jon, Andy) or None if unknown."""
    if not ip_address:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                CASE
                    WHEN city IN ('Missoula', 'Blackfoot', 'Elliston') AND region = 'Montana' THEN 'Jon'
                    WHEN city = 'Helena' AND region = 'Montana' THEN 'Tom'
                    WHEN region = 'Montana' THEN 'Tom'
                    WHEN city IN ('Rocklin', 'Sacramento', 'Florin', 'Elk Grove', 'Roseville', 'Folsom', 'Citrus Heights')
                         AND region = 'California' THEN 'Luke'
                    WHEN region = 'Virginia' THEN 'Luke'
                    WHEN region = 'Washington' THEN 'Andy'
                    ELSE NULL
                END as player_name
            FROM twomanspades.ip_location_data
            WHERE ip_address = %s
        """, (ip_address,))
        result = cur.fetchone()
        cur.close()
        return_db_connection(conn)
        return result[0] if result else None
    except Exception as e:
        print(f"[DB] Error getting suspected player: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_user_difficulty(google_email: str) -> Optional[str]:
    """Get user's saved difficulty preference by email."""
    if not google_email:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT difficulty FROM twomanspades.players
            WHERE google_email = %s
        """, (google_email,))
        result = cur.fetchone()
        cur.close()
        return_db_connection(conn)
        return result[0] if result else None
    except Exception as e:
        print(f"[DB] Error getting user difficulty: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_user_level_record(google_email: str) -> Dict[str, Dict[str, int]]:
    """{level: {wins, losses}} of completed games for one player, keyed by the difficulty
    the deciding hand was played at. Empty for anonymous players or on any failure."""
    if not google_email:
        return {}
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT h.difficulty,
                   COUNT(*) FILTER (WHERE ge.event_data->>'winner' = 'player')   AS wins,
                   COUNT(*) FILTER (WHERE ge.event_data->>'winner' = 'computer') AS losses
              FROM twomanspades.game_events ge
              JOIN twomanspades.hands h ON h.hand_id = ge.hand_id
             WHERE ge.event_type = 'game_completed' AND h.google_email = %s
             GROUP BY h.difficulty
        """, (google_email,))
        out = {row[0]: {'wins': row[1], 'losses': row[2]} for row in cur.fetchall()}
        cur.close()
        return out
    except Exception as e:
        print(f"[DB] Error getting level record: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)


def save_user_difficulty(google_email: str, difficulty: str) -> bool:
    """Save user's difficulty preference."""
    from utilities.computer_logic import DIFFICULTY_LEVELS
    if not google_email or difficulty not in DIFFICULTY_LEVELS:
        return False
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE twomanspades.players SET difficulty = %s
            WHERE google_email = %s
        """, (difficulty, google_email))
        conn.commit()
        cur.close()
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"[DB] Error saving user difficulty: {e}")
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def upsert_player(ip_address: str, user_agent: str = None) -> Optional[int]:
    """Create or update player record, return player_id"""
    conn = None
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
        return_db_connection(conn)
        return player_id
    except Exception as e:
        print(f"Failed to upsert player: {e}")
        return None
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_ip_address_game_stats(client_ip: str = None) -> List[Dict[str, Any]]:
    """Get game statistics from the view, optionally filtered by IP address"""
    conn = None
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
        return_db_connection(conn)
        
        # Convert to list of dicts for easier handling
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get game stats: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)


def save_ip_location_data(ip_address: str, location_data: Dict[str, Any]) -> bool:
    """Save IP location data - ONLY data that comes from the IP API call"""
    conn = None
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
        return_db_connection(conn)
        return True
        
    except Exception as e:
        print(f"Failed to save IP location data for {ip_address}: {e}")
        try:
            if 'conn' in locals():
                conn.rollback()
                return_db_connection(conn)
        except:
            pass
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def save_failed_ip_lookup(ip_address: str) -> bool:
    """Save a record for failed IP lookup"""
    conn = None
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
        return_db_connection(conn)
        return True
        
    except Exception as e:
        print(f"Failed to save failed lookup for {ip_address}: {e}")
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_player_city_membership(client_ip):
    """Get which city/family member this IP belongs to"""
    conn = None
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
        return_db_connection(conn)
        
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
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_unified_leaderboard() -> List[Dict[str, Any]]:
    """Get unified leaderboard from vw_unified_leaderboard view.
    Combines Google-auth games with location-inferred games for known players:
    Tom (Helena/MT), Luke (Rocklin/CA + Virginia), Andy (Seattle/WA), Jon (Elliston/MT).
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT * FROM twomanspades.vw_unified_leaderboard")

        results = cur.fetchall()
        cur.close()
        return_db_connection(conn)

        return [dict(row) for row in results]

    except Exception as e:
        print(f"Failed to get unified leaderboard: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_google_players_leaderboard() -> List[Dict[str, Any]]:
    """Legacy function - now wraps get_unified_leaderboard for backward compatibility"""
    return get_unified_leaderboard()


def get_competitive_leaders_stats() -> List[Dict[str, Any]]:
    """Get competitive win/loss records from vw_city_leaders view"""
    conn = None
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
        return_db_connection(conn)
        
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get competitive leaders stats: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)


def get_city_leaders_stats() -> List[Dict[str, Any]]:
    """Get detailed hand performance stats from vw_city_leaders_totals view"""
    conn = None
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
        return_db_connection(conn)
        
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"Failed to get city leaders stats: {e}")
        return []
    finally:
        if conn is not None:
            return_db_connection(conn)
