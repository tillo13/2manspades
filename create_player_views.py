#!/usr/bin/env python3
"""Create SQL views for unified player identity mapping"""
import sys
sys.path.insert(0, '.')
from utilities.postgres_utils import get_db_connection
import psycopg2.extras

def create_views():
    conn = get_db_connection()
    cur = conn.cursor()

    # View 1: Player identity mapping (maps locations to known players)
    print("Creating vw_player_identity...")
    cur.execute('''
        CREATE OR REPLACE VIEW twomanspades.vw_player_identity AS
        SELECT
            p.player_id,
            p.ip_address,
            h.hand_id,
            h.hand_player_score,
            h.hand_computer_score,
            h.completed_at,
            h.player_bags,
            h.started_at,
            COALESCE(
                SPLIT_PART(p.google_name, ' ', 1),
                CASE
                    -- Jon: Elliston area (Missoula/Blackfoot in Montana)
                    WHEN loc.city IN ('Missoula', 'Blackfoot', 'Elliston') AND loc.region = 'Montana' THEN 'Jon'
                    -- Tom: Helena and rest of Montana
                    WHEN loc.city = 'Helena' AND loc.region = 'Montana' THEN 'Tom'
                    WHEN loc.region = 'Montana' THEN 'Tom'
                    -- Luke: Sacramento metro area (Rocklin, Sacramento, Florin, Elk Grove, etc.) + Virginia
                    WHEN loc.city IN ('Rocklin', 'Sacramento', 'Florin', 'Elk Grove', 'Roseville', 'Folsom', 'Citrus Heights')
                         AND loc.region = 'California' THEN 'Luke'
                    WHEN loc.region = 'Virginia' THEN 'Luke'
                    -- Andy: Seattle metro area (all Washington state)
                    WHEN loc.region = 'Washington' THEN 'Andy'
                    ELSE NULL
                END
            ) as player_name,
            CASE WHEN p.google_id IS NOT NULL THEN true ELSE false END as is_google_auth,
            loc.city,
            loc.region
        FROM twomanspades.hands h
        JOIN twomanspades.players p ON h.player_id = p.player_id
        LEFT JOIN twomanspades.ip_location_data loc ON p.ip_address = loc.ip_address
    ''')
    print("  ✓ vw_player_identity created")

    # View 2: Unified leaderboard - uses game_completed events as source of truth
    # This is the authoritative record of finished games
    print("Creating vw_unified_leaderboard...")
    cur.execute('''
        CREATE OR REPLACE VIEW twomanspades.vw_unified_leaderboard AS
        SELECT
            COALESCE(v.player_name, 'Other') as player_name,
            COUNT(*) as total_games,
            SUM(CASE WHEN ge.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN ge.event_data->>'winner' = 'computer' THEN 1 ELSE 0 END) as losses,
            ROUND(100.0 * SUM(CASE WHEN ge.event_data->>'winner' = 'player' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as win_rate,
            ROUND(AVG(CASE WHEN ge.event_data->>'winner' = 'player' THEN v.hand_player_score END)::numeric, 0) as avg_winning_score,
            MAX(v.hand_player_score) as highest_score,
            SUM(CASE WHEN v.is_google_auth THEN 1 ELSE 0 END) as google_games,
            SUM(CASE WHEN NOT v.is_google_auth THEN 1 ELSE 0 END) as location_games
        FROM twomanspades.game_events ge
        JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
        WHERE ge.event_type = 'game_completed'
        GROUP BY COALESCE(v.player_name, 'Other')
        ORDER BY wins DESC
    ''')
    print("  ✓ vw_unified_leaderboard created")

    # View 3: Player game details - uses game_completed events as source of truth
    print("Creating vw_player_game_details...")
    cur.execute('''
        CREATE OR REPLACE VIEW twomanspades.vw_player_game_details AS
        SELECT
            COALESCE(v.player_name, 'Other') as player_name,
            v.hand_id,
            v.hand_player_score,
            v.hand_computer_score,
            v.completed_at,
            v.player_bags,
            v.started_at,
            v.is_google_auth,
            CASE WHEN ge.event_data->>'winner' = 'player' THEN true ELSE false END as won,
            v.hand_player_score - v.hand_computer_score as margin,
            ge.event_data->>'final_message' as final_message,
            ge.event_data->>'game_end_reason' as game_end_reason
        FROM twomanspades.game_events ge
        JOIN twomanspades.vw_player_identity v ON ge.hand_id = v.hand_id
        WHERE ge.event_type = 'game_completed'
    ''')
    print("  ✓ vw_player_game_details created")

    conn.commit()
    cur.close()
    conn.close()
    print("\nAll views created successfully!")

def test_views():
    print("\n" + "="*60)
    print("TESTING VIEWS")
    print("="*60)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Test unified leaderboard
    print("\n--- vw_unified_leaderboard ---")
    cur.execute("SELECT * FROM twomanspades.vw_unified_leaderboard")
    for row in cur.fetchall():
        print(dict(row))

    # Test player game details - count per player
    print("\n--- Game counts by player ---")
    cur.execute('''
        SELECT player_name, COUNT(*) as games,
               SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins
        FROM twomanspades.vw_player_game_details
        GROUP BY player_name
        ORDER BY games DESC
    ''')
    for row in cur.fetchall():
        print(dict(row))

    # Check what's in "Other"
    print("\n--- 'Other' breakdown (if any) ---")
    cur.execute('''
        SELECT city, region, COUNT(*) as games
        FROM twomanspades.vw_player_identity
        WHERE player_name IS NULL
        AND completed_at IS NOT NULL
        AND (hand_player_score >= 300 OR hand_computer_score >= 300)
        GROUP BY city, region
        ORDER BY games DESC
    ''')
    for row in cur.fetchall():
        print(dict(row))

    cur.close()
    conn.close()

if __name__ == '__main__':
    create_views()
    test_views()
