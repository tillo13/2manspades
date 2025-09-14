"""
Two-Man Spades PostgreSQL Utilities
"""
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional

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
        print(f"✅ PostgreSQL connection successful: {version[0]}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def insert_game(game_data: Dict[str, Any]) -> bool:
    """Insert new game record"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Debug: print what we're trying to insert
        print(f"Attempting to insert game: {game_data.get('game_id')}")
        
        cur.execute("""
            INSERT INTO twomanspades.games 
            (game_id, started_at, player_parity, computer_parity, first_leader, client_ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            game_data['game_id'],
            datetime.fromtimestamp(game_data['game_started_at']),
            game_data['player_parity'],
            game_data['computer_parity'], 
            game_data['first_leader'],
            game_data.get('client_info', {}).get('ip_address'),
            game_data.get('client_info', {}).get('user_agent')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Game {game_data.get('game_id')} successfully inserted")
        return True
    except Exception as e:
        print(f"❌ Failed to insert game {game_data.get('game_id')}: {e}")
        # Try to close connection if it exists
        try:
            if 'conn' in locals():
                conn.close()
        except:
            pass
        return False

def log_game_event_to_db(game_id: str, event_type: str, event_data: Dict, **kwargs) -> bool:
    """Log game event to database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO twomanspades.game_events 
            (game_id, event_type, event_data, hand_number, session_sequence, player, action_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            game_id,
            event_type,
            json.dumps(event_data),
            kwargs.get('hand_number'),
            kwargs.get('session_sequence'),
            kwargs.get('player'),
            kwargs.get('action_type')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to log event: {e}")
        return False

def finalize_game(game_id: str, final_data: Dict[str, Any]) -> bool:
    """Update game record when game ends"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE twomanspades.games 
            SET completed_at = %s,
                final_player_score = %s,
                final_computer_score = %s,
                final_player_bags = %s,
                final_computer_bags = %s,
                winner = %s,
                hands_played = %s,
                game_end_reason = %s
            WHERE game_id = %s
        """, (
            datetime.now(),
            final_data.get('player_score', 0),
            final_data.get('computer_score', 0),
            final_data.get('player_bags', 0),
            final_data.get('computer_bags', 0),
            final_data.get('winner'),
            final_data.get('hand_number', 1),
            final_data.get('game_end_reason', 'completed'),
            game_id
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to finalize game: {e}")
        return False