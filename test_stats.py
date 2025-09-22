#!/usr/bin/env python3
"""
Test script to debug stats page data queries
Run this sibling to app.py to test database connections and data retrieval
"""

import sys
import os
import json

# Add the current directory to path to import utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utilities.postgres_utils import get_db_connection
    print("✅ Successfully imported postgres_utils")
except ImportError as e:
    print(f"❌ Failed to import postgres_utils: {e}")
    sys.exit(1)

def test_database_connection():
    """Test basic database connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()
        cur.close()
        conn.close()
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def test_competitive_leaders_query():
    """Test the competitive leaders query directly"""
    print("\n🔍 Testing Competitive Leaders Query...")
    print("=" * 50)
    
    try:
        conn = get_db_connection()
        
        # Try to use RealDictCursor for better output
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            dict_cursor = True
        except:
            cur = conn.cursor()
            dict_cursor = False
            print("⚠️  Using regular cursor (no RealDictCursor available)")
        
        # First, check if the view exists
        cur.execute("""
            SELECT table_name FROM information_schema.views 
            WHERE table_schema = 'twomanspades' 
            AND table_name = 'vw_city_leaders'
        """)
        view_exists = cur.fetchone()
        
        if not view_exists:
            print("❌ View 'vw_city_leaders' does not exist")
            cur.close()
            conn.close()
            return []
        
        print("✅ View 'vw_city_leaders' exists")
        
        # Now query the actual data
        cur.execute("""
            SELECT * FROM twomanspades.vw_city_leaders 
            ORDER BY total_games DESC, total_wins DESC
        """)
        
        results = cur.fetchall()
        
        print(f"📊 Query returned {len(results)} rows")
        
        if dict_cursor:
            data = [dict(row) for row in results]
        else:
            # Get column names for regular cursor
            col_names = [desc[0] for desc in cur.description]
            data = [dict(zip(col_names, row)) for row in results]
        
        cur.close()
        conn.close()
        
        # Print the results nicely
        for i, row in enumerate(data, 1):
            print(f"\n--- Row {i} ---")
            for key, value in row.items():
                print(f"  {key}: {value}")
        
        return data
        
    except Exception as e:
        print(f"❌ Competitive leaders query failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def test_detailed_leaders_query():
    """Test the detailed leaders query directly"""
    print("\n🔍 Testing Detailed Leaders Query...")
    print("=" * 50)
    
    try:
        conn = get_db_connection()
        
        # Try to use RealDictCursor for better output
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            dict_cursor = True
        except:
            cur = conn.cursor()
            dict_cursor = False
            print("⚠️  Using regular cursor (no RealDictCursor available)")
        
        # First, check if the view exists
        cur.execute("""
            SELECT table_name FROM information_schema.views 
            WHERE table_schema = 'twomanspades' 
            AND table_name = 'vw_city_leaders_totals'
        """)
        view_exists = cur.fetchone()
        
        if not view_exists:
            print("❌ View 'vw_city_leaders_totals' does not exist")
            cur.close()
            conn.close()
            return []
        
        print("✅ View 'vw_city_leaders_totals' exists")
        
        # Now query the actual data
        cur.execute("""
            SELECT * FROM twomanspades.vw_city_leaders_totals 
            ORDER BY total_hands_with_bids DESC
        """)
        
        results = cur.fetchall()
        
        print(f"📊 Query returned {len(results)} rows")
        
        if dict_cursor:
            data = [dict(row) for row in results]
        else:
            # Get column names for regular cursor
            col_names = [desc[0] for desc in cur.description]
            data = [dict(zip(col_names, row)) for row in results]
        
        cur.close()
        conn.close()
        
        # Print the results nicely
        for i, row in enumerate(data, 1):
            print(f"\n--- Row {i} ---")
            for key, value in row.items():
                print(f"  {key}: {value}")
        
        return data
        
    except Exception as e:
        print(f"❌ Detailed leaders query failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def test_functions():
    """Test the actual functions from postgres_utils"""
    print("\n🔍 Testing postgres_utils Functions...")
    print("=" * 50)
    
    try:
        from utilities.postgres_utils import get_competitive_leaders_stats, get_city_leaders_stats
        
        print("Testing get_competitive_leaders_stats()...")
        competitive_data = get_competitive_leaders_stats()
        print(f"✅ Returned {len(competitive_data)} competitive records")
        
        print("\nTesting get_city_leaders_stats()...")
        detailed_data = get_city_leaders_stats()
        print(f"✅ Returned {len(detailed_data)} detailed records")
        
        return competitive_data, detailed_data
        
    except ImportError as e:
        print(f"❌ Cannot import functions: {e}")
        return [], []
    except Exception as e:
        print(f"❌ Function test failed: {e}")
        import traceback
        traceback.print_exc()
        return [], []

def list_available_views():
    """List all views in the twomanspades schema"""
    print("\n🔍 Available Views in twomanspades Schema...")
    print("=" * 50)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT table_name, view_definition 
            FROM information_schema.views 
            WHERE table_schema = 'twomanspades'
            ORDER BY table_name
        """)
        
        results = cur.fetchall()
        
        for table_name, view_def in results:
            print(f"📋 View: {table_name}")
            # Truncate view definition for readability
            short_def = view_def[:100] + "..." if len(view_def) > 100 else view_def
            print(f"   Definition: {short_def}")
            print()
        
        cur.close()
        conn.close()
        
        return [row[0] for row in results]
        
    except Exception as e:
        print(f"❌ Failed to list views: {e}")
        return []

def main():
    """Main test function"""
    print("🚀 Two-Man Spades Stats Database Tester")
    print("=" * 60)
    
    # Test 1: Basic connection
    if not test_database_connection():
        return
    
    # Test 2: List available views
    views = list_available_views()
    
    # Test 3: Test direct queries
    competitive_data = test_competitive_leaders_query()
    detailed_data = test_detailed_leaders_query()
    
    # Test 4: Test the actual functions
    func_competitive, func_detailed = test_functions()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"Available views: {len(views)}")
    print(f"Direct competitive query: {len(competitive_data)} rows")
    print(f"Direct detailed query: {len(detailed_data)} rows")
    print(f"Function competitive results: {len(func_competitive)} rows")
    print(f"Function detailed results: {len(func_detailed)} rows")
    
    if len(competitive_data) == 0:
        print("\n❌ ISSUE: Competitive data is empty")
        print("   - Check if vw_city_leaders view has data")
        print("   - Verify the view definition includes win/loss columns")
    
    if len(detailed_data) > 0 and len(func_detailed) == 0:
        print("\n❌ ISSUE: Function returns empty but direct query works")
        print("   - Check get_city_leaders_stats() function definition")
    
    print("\n✨ Test complete!")

if __name__ == "__main__":
    main()