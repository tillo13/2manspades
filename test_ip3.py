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
IP_MASK_IN_CSV = False              # Set to False to show full IPs in CSV
IP_MASK_IN_CONSOLE = True           # Keep masking in console for privacy
IP_MASK_PREFIX_CHARS = 3            # Console display only
IP_MASK_SUFFIX_CHARS = 3            # Console display only

# Output settings
CONSOLE_OUTPUT_ENABLED = True       # Show detailed console output
CSV_EXPORT_ENABLED = True           # Export results to CSV
CSV_FILENAME_PREFIX = "twomanspades_geolocation"  # CSV file prefix

# Multiple CSV output files
EXPORT_SUMMARY_CSV = True           # Main summary with all data points
EXPORT_COUNTRIES_CSV = True         # Countries breakdown
EXPORT_REGIONS_CSV = True           # Regions breakdown  
EXPORT_ISPS_CSV = True              # ISPs breakdown
EXPORT_FAILED_LOOKUPS_CSV = True    # Failed geolocation attempts

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
                        'zip': data.get('zip', 'Unknown'),
                        'org': data.get('org', data.get('isp', 'Unknown')),
                        'as': data.get('as', 'Unknown')
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
    """Format IP for privacy display - separate from CSV export"""
    if not IP_MASK_IN_CONSOLE:
        return ip
    if len(ip) <= (IP_MASK_PREFIX_CHARS + IP_MASK_SUFFIX_CHARS):
        return ip  # Too short to mask
    return f"{ip[:IP_MASK_PREFIX_CHARS]}***{ip[-IP_MASK_SUFFIX_CHARS:]}"

# =============================================================================
# ENHANCED CSV EXPORT FUNCTIONS
# =============================================================================

def save_comprehensive_csv(results, filename):
    """Save the main comprehensive CSV with all possible data points"""
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                # IP and Activity Data
                'ip_address', 'total_activities', 'first_seen_date', 'first_seen_time', 
                'last_seen_date', 'last_seen_time', 'activity_span_days',
                
                # Location Data
                'city', 'region', 'country', 'timezone', 'zip_code',
                
                # Geographic Coordinates
                'latitude', 'longitude',
                
                # Network Data
                'isp', 'org', 'as_number', 'as_name',
                
                # Analysis Fields
                'activities_per_day', 'player_type', 'lookup_success',
                
                # Timestamps for sorting
                'first_seen_timestamp', 'last_seen_timestamp'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
                # Calculate activity patterns
                activity_span_days = 0
                activities_per_day = 0
                
                if result['first_seen'] and result['last_seen']:
                    activity_span = result['last_seen'] - result['first_seen']
                    activity_span_days = activity_span.days + 1  # Include partial days
                    if activity_span_days > 0:
                        activities_per_day = round(result['activities'] / activity_span_days, 2)
                
                # Determine player type based on activity patterns
                player_type = "Unknown"
                if result['activities'] >= 1000:
                    player_type = "Heavy Player"
                elif result['activities'] >= 100:
                    player_type = "Regular Player" 
                elif result['activities'] >= 10:
                    player_type = "Casual Player"
                else:
                    player_type = "Light Player"
                
                # Base row data
                row = {
                    'ip_address': result['ip'] if not IP_MASK_IN_CSV else result['ip_display'],
                    'total_activities': result['activities'],
                    'first_seen_date': result['first_seen'].strftime('%Y-%m-%d') if result['first_seen'] else '',
                    'first_seen_time': result['first_seen'].strftime('%H:%M:%S') if result['first_seen'] else '',
                    'last_seen_date': result['last_seen'].strftime('%Y-%m-%d') if result['last_seen'] else '',
                    'last_seen_time': result['last_seen'].strftime('%H:%M:%S') if result['last_seen'] else '',
                    'first_seen_timestamp': result['first_seen'].isoformat() if result['first_seen'] else '',
                    'last_seen_timestamp': result['last_seen'].isoformat() if result['last_seen'] else '',
                    'activity_span_days': activity_span_days,
                    'activities_per_day': activities_per_day,
                    'player_type': player_type,
                    'lookup_success': 'Yes' if result['location'] else 'No'
                }
                
                # Add location data if available
                if result['location']:
                    loc = result['location']
                    row.update({
                        'city': loc.get('city', ''),
                        'region': loc.get('region', ''),
                        'country': loc.get('country', ''),
                        'timezone': loc.get('timezone', ''),
                        'zip_code': loc.get('zip', ''),
                        'latitude': loc.get('lat', ''),
                        'longitude': loc.get('lon', ''),
                        'isp': loc.get('isp', ''),
                        'org': loc.get('org', loc.get('isp', '')),  # Fallback to ISP if org not available
                        'as_number': loc.get('as', '').split(' ')[0] if loc.get('as') else '',
                        'as_name': ' '.join(loc.get('as', '').split(' ')[1:]) if loc.get('as') else ''
                    })
                else:
                    # Fill with empty values for failed lookups
                    row.update({
                        'city': '', 'region': '', 'country': '', 'timezone': '', 'zip_code': '',
                        'latitude': '', 'longitude': '', 'isp': '', 'org': '', 'as_number': '', 'as_name': ''
                    })
                
                writer.writerow(row)
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"✅ Comprehensive CSV saved: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save comprehensive CSV: {e}")
        return None

def save_countries_csv(results, filename):
    """Save countries breakdown CSV"""
    try:
        country_stats = defaultdict(lambda: {'players': 0, 'activities': 0, 'cities': set()})
        
        for result in results:
            if result['location']:
                country = result['location']['country']
                city = result['location']['city']
                country_stats[country]['players'] += 1
                country_stats[country]['activities'] += result['activities']
                country_stats[country]['cities'].add(city)
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['country', 'total_players', 'total_activities', 'unique_cities', 'avg_activities_per_player']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for country, stats in sorted(country_stats.items(), key=lambda x: x[1]['activities'], reverse=True):
                writer.writerow({
                    'country': country,
                    'total_players': stats['players'],
                    'total_activities': stats['activities'],
                    'unique_cities': len(stats['cities']),
                    'avg_activities_per_player': round(stats['activities'] / stats['players'], 2)
                })
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"✅ Countries CSV saved: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save countries CSV: {e}")
        return None

def save_regions_csv(results, filename):
    """Save regions breakdown CSV"""
    try:
        region_stats = defaultdict(lambda: {'players': 0, 'activities': 0})
        
        for result in results:
            if result['location']:
                region_key = f"{result['location']['region']}, {result['location']['country']}"
                region_stats[region_key]['players'] += 1
                region_stats[region_key]['activities'] += result['activities']
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['region_country', 'region', 'country', 'total_players', 'total_activities', 'avg_activities_per_player']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for region_key, stats in sorted(region_stats.items(), key=lambda x: x[1]['activities'], reverse=True):
                region, country = region_key.rsplit(', ', 1)
                writer.writerow({
                    'region_country': region_key,
                    'region': region,
                    'country': country,
                    'total_players': stats['players'],
                    'total_activities': stats['activities'],
                    'avg_activities_per_player': round(stats['activities'] / stats['players'], 2)
                })
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"✅ Regions CSV saved: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save regions CSV: {e}")
        return None

def save_isps_csv(results, filename):
    """Save ISPs breakdown CSV"""
    try:
        isp_stats = defaultdict(lambda: {'players': 0, 'activities': 0, 'countries': set()})
        
        for result in results:
            if result['location']:
                isp = result['location']['isp']
                country = result['location']['country']
                isp_stats[isp]['players'] += 1
                isp_stats[isp]['activities'] += result['activities']
                isp_stats[isp]['countries'].add(country)
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['isp', 'total_players', 'total_activities', 'countries_served', 'avg_activities_per_player']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for isp, stats in sorted(isp_stats.items(), key=lambda x: x[1]['activities'], reverse=True):
                writer.writerow({
                    'isp': isp,
                    'total_players': stats['players'],
                    'total_activities': stats['activities'],
                    'countries_served': len(stats['countries']),
                    'avg_activities_per_player': round(stats['activities'] / stats['players'], 2)
                })
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"✅ ISPs CSV saved: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save ISPs CSV: {e}")
        return None

def save_failed_lookups_csv(failed_results, filename):
    """Save failed geolocation lookups CSV for investigation"""
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['ip_address', 'total_activities', 'first_seen', 'last_seen', 'failure_reason']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in failed_results:
                writer.writerow({
                    'ip_address': result['ip'] if not IP_MASK_IN_CSV else result['ip_display'],
                    'total_activities': result['activities'],
                    'first_seen': result['first_seen'].isoformat() if result['first_seen'] else '',
                    'last_seen': result['last_seen'].isoformat() if result['last_seen'] else '',
                    'failure_reason': 'Geolocation API failed or returned invalid data'
                })
        
        if CONSOLE_OUTPUT_ENABLED:
            print(f"✅ Failed lookups CSV saved: {filename}")
        return filename
        
    except Exception as e:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"❌ Failed to save failed lookups CSV: {e}")
        return None

def save_enhanced_results_to_csv(results, all_ip_data, base_filename=None):
    """Save comprehensive geolocation results to multiple CSV files"""
    if not CSV_EXPORT_ENABLED:
        return []
        
    if not base_filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"{CSV_FILENAME_PREFIX}_{timestamp}"
    
    saved_files = []
    
    # 1. Main comprehensive summary CSV
    if EXPORT_SUMMARY_CSV:
        filename = f"{base_filename}_comprehensive.csv"
        result = save_comprehensive_csv(results, filename)
        if result:
            saved_files.append(result)
    
    # 2. Countries breakdown CSV
    if EXPORT_COUNTRIES_CSV:
        filename = f"{base_filename}_countries.csv"
        result = save_countries_csv(results, filename)
        if result:
            saved_files.append(result)
    
    # 3. Regions breakdown CSV  
    if EXPORT_REGIONS_CSV:
        filename = f"{base_filename}_regions.csv"
        result = save_regions_csv(results, filename)
        if result:
            saved_files.append(result)
    
    # 4. ISPs breakdown CSV
    if EXPORT_ISPS_CSV:
        filename = f"{base_filename}_isps.csv"
        result = save_isps_csv(results, filename)
        if result:
            saved_files.append(result)
    
    # 5. Failed lookups CSV (if any)
    if EXPORT_FAILED_LOOKUPS_CSV:
        failed_results = [r for r in results if not r['location']]
        if failed_results:
            filename = f"{base_filename}_failed_lookups.csv"
            result = save_failed_lookups_csv(failed_results, filename)
            if result:
                saved_files.append(result)
    
    return saved_files

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
        print(f"   - Full IPs in CSV: {'Yes' if not IP_MASK_IN_CSV else 'No'}")
    
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
    
    # Enhanced CSV export
    if CSV_EXPORT_ENABLED:
        if CONSOLE_OUTPUT_ENABLED:
            print(f"\n💾 Saving enhanced results to multiple CSV files...")
        
        saved_files = save_enhanced_results_to_csv(results, all_ip_data)
        
        if saved_files and CONSOLE_OUTPUT_ENABLED:
            print(f"\n📊 Enhanced CSV Export Complete!")
            print(f"📁 Saved {len(saved_files)} CSV files:")
            for file in saved_files:
                print(f"   - {file}")
            
            print(f"\n📋 CSV Features:")
            print(f"   - Full IP addresses: {'Yes' if not IP_MASK_IN_CSV else 'No (masked)'}")
            print(f"   - Geographic coordinates: Yes (for mapping)")
            print(f"   - Activity patterns: Yes (span, frequency)")
            print(f"   - Player classification: Yes (Heavy/Regular/Casual/Light)")
            print(f"   - Separate breakdowns: Countries, Regions, ISPs")
            print(f"   - Sortable timestamps: Yes (ISO format)")
            print(f"   - Google Sheets ready: Yes")
            
            print(f"\n🔍 Analysis Tips:")
            print(f"   - Import comprehensive CSV to Google Sheets")
            print(f"   - Sort by country/region to see geographic distribution")
            print(f"   - Filter by player_type to focus on active users")
            print(f"   - Use lat/lon columns for mapping visualization")
            print(f"   - Check activities_per_day for engagement patterns")
    
    if CONSOLE_OUTPUT_ENABLED:
        print("\n✨ Enhanced spam-filtered geolocation analysis complete!")

if __name__ == "__main__":
    main()