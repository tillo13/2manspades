#!/usr/bin/env python3
"""
Two-Man Spades IP Geolocation Analysis Script
Analyzes all IP addresses from the database and provides geographic insights
"""

# =============================================================================
# GLOBAL CONFIGURATION VARIABLES - ADJUST THESE AS NEEDED
# =============================================================================

# Spam filtering settings
MINIMUM_ACTIVITIES = 3              # Filter out IPs with fewer activities (likely spam/bots)
INCLUDE_FAILED_GEOLOCATIONS = True  # Whether to include IPs that failed geolocation

# Rate limiting settings (ip-api.com free tier: 45 requests/minute)
REQUESTS_PER_MINUTE = 40            # Conservative rate to stay under limit
DELAY_BETWEEN_REQUESTS = 60 / REQUESTS_PER_MINUTE  # Auto-calculated delay

# IP privacy settings
IP_MASK_PREFIX_CHARS = 3            # How many chars to show at start of IP
IP_MASK_SUFFIX_CHARS = 3            # How many chars to show at end of IP

# Output settings
CONSOLE_OUTPUT_ENABLED = True       # Show detailed console output
CSV_EXPORT_ENABLED = True           # Export results to CSV
CSV_FILENAME_PREFIX = "twomanspades_geolocation"  # CSV file prefix

# Database query settings
COMBINE_HANDS_AND_EVENTS = True     # Query both hands and game_events tables
SORT_BY_ACTIVITY_COUNT = True       # Sort results by activity count (desc)

# Geolocation API settings
API_TIMEOUT_SECONDS = 5             # Timeout for each API request
USER_AGENT = "TwoManSpades-GeoAnalysis/1.0"  # User agent for API requests
API_BASE_URL = "http://ip-api.com/json"      # API endpoint

# =============================================================================
# IMPORTS AND SETUP
# =============================================================================

import sys
import os
import time
import urllib.request
import urllib.error
import json
import csv
from collections import defaultdict
from datetime import datetime

# Add the current directory to path to import utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utilities.postgres_utils import get_db_connection, get_ip_address_game_stats
    print("✅ Successfully imported postgres_utils")
except ImportError as e:
    print(f"❌ Failed to import postgres_utils: {e}")
    print("Make sure you're running this script from the same directory as app.py")
    sys.exit(1)

# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def get_all_unique_ips():
    """Get all unique IP addresses from both hands and game_events tables"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if COMBINE_HANDS_AND_EVENTS:
            # Query to get all unique IPs from both tables with activity stats
            query = """
            WITH combined_ips AS (
                -- IPs from hands table
                SELECT 
                    client_ip,
                    started_at as activity_time,
                    'hand' as source_table
                FROM twomanspades.hands 
                WHERE client_ip IS NOT NULL AND client_ip != ''
                
                UNION ALL
                
                -- IPs from game_events table  
                SELECT 
                    client_ip,
                    timestamp as activity_time,
                    'event' as source_table
                FROM twomanspades.game_events 
                WHERE client_ip IS NOT NULL AND client_ip != ''
            ),
            ip_stats AS (
                SELECT 
                    client_ip,
                    COUNT(*) as total_activities,
                    MIN(activity_time) as first_seen,
                    MAX(activity_time) as last_seen,
                    COUNT(CASE WHEN source_table = 'hand' THEN 1 END) as hand_count,
                    COUNT(CASE WHEN source_table = 'event' THEN 1 END) as event_count
                FROM combined_ips
                GROUP BY client_ip
            )
            SELECT 
                client_ip,
                total_activities,
                first_seen,
                last_seen,
                hand_count,
                event_count
            FROM ip_stats
            ORDER BY total_activities DESC, hand_count DESC
            """
        else:
            # Use existing view for hands table only
            all_stats = get_ip_address_game_stats()
            valid_stats = [stat for stat in all_stats if stat.get('total_games', 0) > 0]
            formatted_data = []
            for stat in valid_stats:
                formatted_data.append((
                    stat['client_ip'],
                    stat['total_games'],
                    stat.get('first_game'),
                    stat.get('last_game')
                ))
            return formatted_data
        
        cur.execute(query)
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        # Convert to format we need (ip, activity_count, first_seen, last_seen)
        formatted_data = []
        for row in results:
            ip, total_activities, first_seen, last_seen, hand_count, event_count = row
            formatted_data.append((
                ip,
                total_activities,
                first_seen,
                last_seen
            ))
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"📊 Found IPs across both tables:")
            print(f"   - {len(set(r[0] for r in formatted_data))} unique IP addresses")
            print(f"   - Total activities: {sum(r[1] for r in formatted_data)}")
        
        return formatted_data
        
    except Exception as e:
        print(f"❌ Error getting IP addresses from both tables: {e}")
        return []

def geolocate_ip(ip_address):
    """Use ip-api.com free service to geolocate an IP address"""
    try:
        url = f"{API_BASE_URL}/{ip_address}"
        
        request = urllib.request.Request(url)
        request.add_header('User-Agent', USER_AGENT)
        
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                
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
                    if CONSOLE_OUTPUT_ENABLED:
                        print(f"  ⚠️  API returned failure for {ip_address}: {data.get('message', 'Unknown error')}")
                    return None
            else:
                if CONSOLE_OUTPUT_ENABLED:
                    print(f"  ❌ HTTP error {response.getcode()} for {ip_address}")
                return None
            
    except urllib.error.URLError as e:
        if CONSOLE_OUTPUT_ENABLED:
            if hasattr(e, 'reason'):
                if 'timeout' in str(e.reason).lower():
                    print(f"  ⏱️  Timeout for {ip_address}")
                else:
                    print(f"  ❌ URL error for {ip_address}: {e.reason}")
            else:
                print(f"  ❌ URL error for {ip_address}: {e}")
        return None
    except json.JSONDecodeError:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"  ❌ Invalid JSON response for {ip_address}")
        return None
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"  ❌ Unexpected error for {ip_address}: {e}")
        return None

def format_ip_for_display(ip):
    """Format IP for privacy display"""
    if len(ip) <= (IP_MASK_PREFIX_CHARS + IP_MASK_SUFFIX_CHARS):
        return ip  # Too short to mask
    return f"{ip[:IP_MASK_PREFIX_CHARS]}***{ip[-IP_MASK_SUFFIX_CHARS:]}"

def save_results_to_csv(results, all_ip_data, filename=None):
    """Save geolocation results to CSV file"""
    if not CSV_EXPORT_ENABLED:
        return None
        
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{CSV_FILENAME_PREFIX}_{timestamp}.csv"
    
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'ip_masked', 'activities', 'first_seen', 'last_seen', 
                'city', 'region', 'country', 'isp', 'timezone', 
                'latitude', 'longitude', 'zip_code', 'lookup_success'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
                row = {
                    'ip_masked': result['ip_display'],
                    'activities': result['activities'],
                    'first_seen': result['first_seen'].strftime('%Y-%m-%d %H:%M:%S') if result['first_seen'] else '',
                    'last_seen': result['last_seen'].strftime('%Y-%m-%d %H:%M:%S') if result['last_seen'] else '',
                    'lookup_success': 'Yes' if result['location'] else 'No'
                }
                
                if result['location']:
                    loc = result['location']
                    row.update({
                        'city': loc['city'],
                        'region': loc['region'], 
                        'country': loc['country'],
                        'isp': loc['isp'],
                        'timezone': loc['timezone'],
                        'latitude': loc['lat'],
                        'longitude': loc['lon'],
                        'zip_code': loc['zip']
                    })
                else:
                    row.update({
                        'city': 'Unknown', 'region': 'Unknown', 'country': 'Unknown',
                        'isp': 'Unknown', 'timezone': 'Unknown', 'latitude': 0,
                        'longitude': 0, 'zip_code': 'Unknown'
                    })
                
                writer.writerow(row)
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"💾 Results saved to: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save CSV: {e}")
        return None

# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    if CONSOLE_OUTPUT_ENABLED:
        print("🌍 Two-Man Spades IP Geolocation Analysis")
        print("=" * 50)
        print(f"⚙️  Configuration:")
        print(f"   - Minimum activities filter: {MINIMUM_ACTIVITIES}")
        print(f"   - Rate limit: {REQUESTS_PER_MINUTE} requests/minute")
        print(f"   - Combine tables: {COMBINE_HANDS_AND_EVENTS}")
        print(f"   - CSV export: {CSV_EXPORT_ENABLED}")
    
    # Test database connection first
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        if CONSOLE_OUTPUT_ENABLED:
            print("✅ Database connection successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    # Get all unique IPs
    if CONSOLE_OUTPUT_ENABLED:
        print("\n📋 Fetching unique IP addresses from database...")
    all_ip_data = get_all_unique_ips()
    
    if not all_ip_data:
        print("❌ No IP addresses found in database")
        return
    
    # Filter out likely spam/automated traffic
    ip_data = [ip for ip in all_ip_data if ip[1] >= MINIMUM_ACTIVITIES]
    
    total_all_ips = len(all_ip_data)
    total_filtered_ips = len(ip_data)
    filtered_out = total_all_ips - total_filtered_ips
    
    if CONSOLE_OUTPUT_ENABLED:
        print(f"✅ Found {total_all_ips} unique IP addresses")
        print(f"🔍 Filtered to {total_filtered_ips} IPs with {MINIMUM_ACTIVITIES}+ activities (removed {filtered_out} likely spam/automated)")
    
    # Process ALL filtered IP addresses
    if CONSOLE_OUTPUT_ENABLED:
        print(f"🎯 Processing ALL {total_filtered_ips} legitimate players")
        print(f"📊 Rate limit: {REQUESTS_PER_MINUTE} requests/minute")
        print(f"⏱️  Estimated time: ~{(total_filtered_ips * DELAY_BETWEEN_REQUESTS) / 60:.1f} minutes")
        print("\n🔍 Starting geolocation lookups...")
        print("=" * 70)
    
    # Initialize results storage
    results = []
    country_stats = defaultdict(int)
    region_stats = defaultdict(int)
    isp_stats = defaultdict(int)
    
    for i, (ip, activities, first_seen, last_seen) in enumerate(ip_data, 1):
        if CONSOLE_OUTPUT_ENABLED:
            print(f"\n[{i:2}/{total_filtered_ips}] {format_ip_for_display(ip)} ({activities} activities)")
            if first_seen and last_seen:
                print(f"         First: {first_seen.strftime('%Y-%m-%d %H:%M')} | Last: {last_seen.strftime('%Y-%m-%d %H:%M')}")
            else:
                print(f"         First/Last: Unknown")
        
        # Rate limiting
        if i > 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        
        # Geolocate the IP
        location = geolocate_ip(ip)
        
        if location:
            if CONSOLE_OUTPUT_ENABLED:
                print(f"         📍 {location['city']}, {location['region']}, {location['country']}")
                print(f"         🌐 ISP: {location['isp']}")
                print(f"         🕐 Timezone: {location['timezone']}")
            
            # Store results
            result = {
                'ip': ip,
                'ip_display': format_ip_for_display(ip),
                'activities': activities,
                'first_seen': first_seen,
                'last_seen': last_seen,
                'location': location
            }
            results.append(result)
            
            # Update statistics
            country_stats[location['country']] += activities
            region_key = f"{location['region']}, {location['country']}"
            region_stats[region_key] += activities
            isp_stats[location['isp']] += activities
            
        else:
            if CONSOLE_OUTPUT_ENABLED:
                print(f"         ❌ Geolocation failed")
            
            if INCLUDE_FAILED_GEOLOCATIONS:
                # Store failed result
                result = {
                    'ip': ip,
                    'ip_display': format_ip_for_display(ip),
                    'activities': activities,
                    'first_seen': first_seen,
                    'last_seen': last_seen,
                    'location': None
                }
                results.append(result)
    
    # Print summary statistics
    if CONSOLE_OUTPUT_ENABLED:
        print("\n" + "=" * 70)
        print("📊 GEOLOCATION SUMMARY")
        print("=" * 70)
        
        successful_lookups = len([r for r in results if r['location']])
        print(f"✅ Successful lookups: {successful_lookups}/{len(results)} ({successful_lookups/len(results)*100:.1f}%)")
        
        print(f"\n🌍 TOP COUNTRIES BY ACTIVITY:")
        for country, activities in sorted(country_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {country:<20} {activities:>3} activities")
        
        print(f"\n🏙️  TOP REGIONS BY ACTIVITY:")
        for region, activities in sorted(region_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {region:<35} {activities:>3} activities")
        
        print(f"\n🔗 TOP ISPs BY ACTIVITY:")
        for isp, activities in sorted(isp_stats.items(), key=lambda x: x[1], reverse=True):
            isp_display = isp[:40] + "..." if len(isp) > 40 else isp
            print(f"   {isp_display:<43} {activities:>3} activities")
        
        print(f"\n🎮 ALL {total_filtered_ips} LEGITIMATE PLAYERS SORTED BY CITY:")
        print("-" * 70)
        
        # Sort results by city for final display
        results_by_city = sorted(results, key=lambda x: (
            x['location']['city'] if x['location'] else 'zzz_Unknown',
            x['location']['region'] if x['location'] else '',
            x['location']['country'] if x['location'] else ''
        ))
        
        for result in results_by_city:
            ip_display = result['ip_display']
            activities = result['activities']
            
            if result['location']:
                loc = result['location']
                location_str = f"{loc['city']}, {loc['region']}, {loc['country']}"
                print(f"{ip_display:<12} | {activities:>3} activities | {location_str}")
            else:
                print(f"{ip_display:<12} | {activities:>3} activities | Location unknown")
        
        total_activities_filtered = sum(r['activities'] for r in results)
        total_activities_all = sum(ip[1] for ip in all_ip_data)
        spam_activities = total_activities_all - total_activities_filtered
        
        print(f"\n🎯 LEGITIMATE PLAYERS: {len(results)} players, {total_activities_filtered} activities")
        print(f"🤖 FILTERED OUT: {filtered_out} likely spam/bot IPs, {spam_activities} activities")
        print(f"🌍 TOTAL IN DATABASE: {total_all_ips} IPs, {total_activities_all} total activities")
        print(f"🌍 ALL PLAYERS: {total_filtered_ips} legitimate players processed")
        print(f"📈 Players with {MINIMUM_ACTIVITIES}+ activities sorted by city alphabetically")
    
    # Save results to CSV
    if CSV_EXPORT_ENABLED:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"\n💾 Saving results to CSV...")
        csv_filename = save_results_to_csv(results, all_ip_data)
        if csv_filename and CONSOLE_OUTPUT_ENABLED:
            print(f"📊 CSV contains {len(results)} legitimate players with detailed geolocation data")
            print(f"📁 File includes columns: IP (masked), activities, timestamps, location details, ISP info")
            print(f"🔍 You can now sort/filter by any column in Excel or other tools")
    
    if CONSOLE_OUTPUT_ENABLED:
        print("\n✨ Spam-filtered geolocation analysis complete!")

if __name__ == "__main__":
    main()