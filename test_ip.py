#!/usr/bin/env python3
"""
Test script to geolocate all IP addresses from the Two-Man Spades database
Uses ip-api.com free service to lookup locations for all unique player IPs
"""

import sys
import os
import time
import urllib.request
import urllib.error
import json
from collections import defaultdict

# Add the current directory to path to import utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utilities.postgres_utils import get_db_connection, get_ip_address_game_stats
    print("✅ Successfully imported postgres_utils")
except ImportError as e:
    print(f"❌ Failed to import postgres_utils: {e}")
    print("Make sure you're running this script from the same directory as app.py")
    sys.exit(1)

def get_top_players_stats():
    """Get top 10 players from your existing stats view"""
    try:
        # Use your existing function to get all player stats
        all_stats = get_ip_address_game_stats()
        
        # Filter out any with no games and take top 10
        valid_stats = [stat for stat in all_stats if stat.get('total_games', 0) > 0]
        top_10 = valid_stats[:10]
        
        # Convert to format we need (ip, games, first_seen, last_seen)
        formatted_data = []
        for stat in top_10:
            formatted_data.append((
                stat['client_ip'],
                stat['total_games'],
                stat.get('first_game'),  # These are already datetime objects
                stat.get('last_game')
            ))
        
        return formatted_data, len(all_stats)
        
    except Exception as e:
        print(f"❌ Error getting player stats: {e}")
        return [], 0

def get_all_unique_ips():
    """Get all unique IP addresses with their game counts and timestamps"""
    try:
        # Use your existing function to get all player stats
        all_stats = get_ip_address_game_stats()
        
        # Filter out any with no games
        valid_stats = [stat for stat in all_stats if stat.get('total_games', 0) > 0]
        
        # Convert to format we need (ip, games, first_seen, last_seen)
        formatted_data = []
        for stat in valid_stats:
            formatted_data.append((
                stat['client_ip'],
                stat['total_games'],
                stat.get('first_game'),  # These are already datetime objects
                stat.get('last_game')
            ))
        
        # Sort by game count (descending) to get most active first
        formatted_data.sort(key=lambda x: x[1], reverse=True)
        
        return formatted_data
        
    except Exception as e:
        print(f"❌ Error getting IP addresses: {e}")
        return []

def geolocate_ip(ip_address):
    """
    Use ip-api.com free service to geolocate an IP address
    Returns dict with location info or None if failed
    """
    try:
        # Free API endpoint - no key needed
        url = f"http://ip-api.com/json/{ip_address}"
        
        # Make request with timeout using urllib
        request = urllib.request.Request(url)
        request.add_header('User-Agent', 'TwoManSpades-GeoTest/1.0')
        
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                
                # Check if the lookup was successful
                if data.get('status') == 'success':
                    return {
                        'country': data.get('country', 'Unknown'),
                        'region': data.get('regionName', 'Unknown'),
                        'city': data.get('city', 'Unknown'),
                        'isp': data.get('isp', 'Unknown'),
                        'lat': data.get('lat', 0),
                        'lon': data.get('lon', 0),
                        'timezone': data.get('timezone', 'Unknown'),
                        'zip': data.get('zip', 'Unknown')
                    }
                else:
                    print(f"  ⚠️  API returned failure for {ip_address}: {data.get('message', 'Unknown error')}")
                    return None
            else:
                print(f"  ❌ HTTP error {response.getcode()} for {ip_address}")
                return None
            
    except urllib.error.URLError as e:
        if hasattr(e, 'reason'):
            if 'timeout' in str(e.reason).lower():
                print(f"  ⏱️  Timeout for {ip_address}")
            else:
                print(f"  ❌ URL error for {ip_address}: {e.reason}")
        else:
            print(f"  ❌ URL error for {ip_address}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"  ❌ Invalid JSON response for {ip_address}")
        return None
    except Exception as e:
        print(f"  ❌ Unexpected error for {ip_address}: {e}")
        return None

def format_ip_for_display(ip):
    """Format IP for privacy (show first 3 and last 3 chars)"""
    if len(ip) <= 6:
        return ip  # Too short to mask
    return f"{ip[:3]}***{ip[-3:]}"

def main():
    print("🌍 Two-Man Spades IP Geolocation Test")
    print("=" * 50)
    
    # Test database connection first
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        print("✅ Database connection successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    # Get all unique IPs
    print("\n📋 Fetching unique IP addresses from database...")
    ip_data = get_all_unique_ips()
    
    if not ip_data:
        print("❌ No IP addresses found in database")
        return
    
    total_players = len(ip_data)  # Define total_players here
    print(f"✅ Found {total_players} unique IP addresses")
    
    # Limit to top 10 most active IPs
    top_ips = ip_data[:10]
    print(f"🎯 Focusing on top {len(top_ips)} most active players")
    print(f"📊 Rate limit: 45 requests/minute (will pace requests automatically)")
    
    # Initialize results storage
    results = []
    country_stats = defaultdict(int)
    region_stats = defaultdict(int)
    isp_stats = defaultdict(int)
    
    print("\n🔍 Starting geolocation lookups for top players...")
    print("=" * 70)
    
    # Process only the top IPs, not all of them
    for i, (ip, games, first_seen, last_seen) in enumerate(top_ips, 1):
        print(f"\n[{i:2}/{len(top_ips)}] {format_ip_for_display(ip)} ({games} games)")
        if first_seen and last_seen:
            print(f"         First: {first_seen.strftime('%Y-%m-%d %H:%M')} | Last: {last_seen.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"         First/Last: Unknown")
        
        # Rate limiting - free tier allows 45 requests/minute
        if i > 1:
            time.sleep(1.5)  # ~40 requests/minute to stay under limit
        
        # Geolocate the IP
        location = geolocate_ip(ip)
        
        if location:
            print(f"         📍 {location['city']}, {location['region']}, {location['country']}")
            print(f"         🌐 ISP: {location['isp']}")
            print(f"         🕐 Timezone: {location['timezone']}")
            
            # Store results
            result = {
                'ip': ip,
                'ip_display': format_ip_for_display(ip),
                'games': games,
                'first_seen': first_seen,
                'last_seen': last_seen,
                'location': location
            }
            results.append(result)
            
            # Update statistics
            country_stats[location['country']] += games
            region_key = f"{location['region']}, {location['country']}"
            region_stats[region_key] += games
            isp_stats[location['isp']] += games
            
        else:
            print(f"         ❌ Geolocation failed")
            # Store failed result
            result = {
                'ip': ip,
                'ip_display': format_ip_for_display(ip),
                'games': games,
                'first_seen': first_seen,
                'last_seen': last_seen,
                'location': None
            }
            results.append(result)
    
    # Print summary statistics
    print("\n" + "=" * 70)
    print("📊 GEOLOCATION SUMMARY")
    print("=" * 70)
    
    successful_lookups = len([r for r in results if r['location']])
    print(f"✅ Successful lookups: {successful_lookups}/{len(results)} ({successful_lookups/len(results)*100:.1f}%)")
    
    print(f"\n🌍 TOP COUNTRIES BY GAME ACTIVITY:")
    for country, games in sorted(country_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"   {country:<20} {games:>3} games")
    
    print(f"\n🏙️  TOP REGIONS BY GAME ACTIVITY:")
    for region, games in sorted(region_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"   {region:<35} {games:>3} games")
    
    print(f"\n🔗 TOP ISPs BY GAME ACTIVITY:")
    for isp, games in sorted(isp_stats.items(), key=lambda x: x[1], reverse=True):
        # Truncate long ISP names
        isp_display = isp[:40] + "..." if len(isp) > 40 else isp
        print(f"   {isp_display:<43} {games:>3} games")
    
    print(f"\n🎮 TOP {len(results)} PLAYERS BY ACTIVITY:")
    print("-" * 70)
    for result in results:
        ip_display = result['ip_display']
        games = result['games']
        
        if result['location']:
            loc = result['location']
            location_str = f"{loc['city']}, {loc['region']}, {loc['country']}"
            print(f"{ip_display:<12} | {games:>3} games | {location_str}")
        else:
            print(f"{ip_display:<12} | {games:>3} games | Location unknown")
    
    total_games_top10 = sum(r['games'] for r in results)
    
    print(f"\n🎯 TOP 10 TOTALS: {len(results)} players, {total_games_top10} games")
    print(f"🌍 ALL PLAYERS: {total_players} players total")
    print(f"📈 Top 10 represent a significant portion of all game activity")
    
    print("\n✨ Geolocation test complete!")

if __name__ == "__main__":
    main()