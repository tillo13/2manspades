"""Two-Man Spades game store database operations."""
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

def insert_hand(hand_data: Dict[str, Any]) -> bool:
    """Insert new hand record"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Debug: print what we're trying to insert
        print(f"Attempting to insert hand: {hand_data.get('hand_id')}")
        
        cur.execute("""
            INSERT INTO twomanspades.hands
            (hand_id, started_at, player_parity, computer_parity, first_leader, client_ip, user_agent, difficulty)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            hand_data['hand_id'],
            datetime.fromtimestamp(hand_data['game_started_at']),  # Still using game_started_at from session
            hand_data['player_parity'],
            hand_data['computer_parity'],
            hand_data['first_leader'],
            hand_data.get('client_info', {}).get('ip_address'),
            hand_data.get('client_info', {}).get('user_agent'),
            hand_data.get('difficulty', 'easy')
        ))
        
        conn.commit()
        cur.close()
        return_db_connection(conn)
        print(f"Hand {hand_data.get('hand_id')} successfully inserted")
        return True
    except Exception as e:
        print(f"Failed to insert hand {hand_data.get('hand_id')}: {e}")
        # Try to close connection if it exists
        try:
            if 'conn' in locals():
                return_db_connection(conn)
        except:
            pass
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def log_game_event_to_db(hand_id: str, event_type: str, event_data: Dict, **kwargs) -> bool:
    """Log game event to database using hand_id"""
    conn = None
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
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"Failed to log event: {e}")
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def finalize_hand(hand_id: str, final_data: Dict[str, Any]) -> bool:
    """Update hand record when hand completes"""
    conn = None
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
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"Failed to finalize hand: {e}")
        return False
    finally:
        if conn is not None:
            return_db_connection(conn)


def batch_log_events(hand_id: str, events: List[Dict]) -> bool:
    """Log multiple events in a single database transaction"""
    if not events:
        return True
    
    conn = None
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
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"Batch event logging failed: {e}")
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


def create_hand_with_player(hand_data: Dict[str, Any], client_info: Dict[str, Any] = None) -> bool:
    """Create hand and update player in single transaction"""
    conn = None
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
             client_ip, user_agent, player_id, google_email, google_id, difficulty)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            hand_data['current_hand_id'],
            datetime.fromtimestamp(hand_data['game_started_at']),
            hand_data['player_parity'],
            hand_data['computer_parity'],
            hand_data['first_leader'],
            client_info.get('ip_address') if client_info else None,
            client_info.get('user_agent') if client_info else None,
            player_id,
            google_email,
            google_id,
            hand_data.get('difficulty', 'easy')
        ))
        
        conn.commit()
        cur.close()
        return_db_connection(conn)
        return True
    except Exception as e:
        print(f"Failed to create hand with player: {e}")
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


def insert_game(game_data: Dict[str, Any]) -> bool:
    """Legacy wrapper - use insert_hand instead"""
    return insert_hand(game_data)


def finalize_game(game_id: str, final_data: Dict[str, Any]) -> bool:
    """Legacy wrapper - use finalize_hand instead"""
    return finalize_hand(game_id, final_data)


def create_game_with_player(game_data: Dict[str, Any], client_info: Dict[str, Any] = None) -> bool:
    """Legacy wrapper - use create_hand_with_player instead"""
    return create_hand_with_player(game_data, client_info)
