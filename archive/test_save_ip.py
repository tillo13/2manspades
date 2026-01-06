#!/usr/bin/env python3
"""
Import IP location data from CSV to database
Only inserts unique IP addresses that don't already exist
"""

import csv
import os
import sys
from typing import Dict, Any, List

# Add the current directory to path to import utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utilities.postgres_utils import get_db_connection, save_ip_location_data
    print("✅ Successfully imported postgres_utils")
except ImportError as e:
    print(f"❌ Failed to import postgres_utils: {e}")
    print("Make sure you're running this script from the same directory as app.py")
    sys.exit(1)

def get_existing_ips() -> set:
    """Get all IP addresses that already exist in the database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT ip_address FROM twomanspades.ip_location_data")
        existing_ips = {row[0] for row in cur.fetchall()}
        
        cur.close()
        conn.close()
        
        print(f"📊 Found {len(existing_ips)} existing IP addresses in database")
        return existing_ips
        
    except Exception as e:
        print(f"❌ Error getting existing IPs: {e}")
        return set()

def read_csv_data(filename: str) -> List[Dict[str, Any]]:
    """Read IP location data from CSV file"""
    csv_path = os.path.join(os.path.dirname(__file__), filename)
    
    if not os.path.exists(csv_path):
        print(f"❌ CSV file not found: {csv_path}")
        return []
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            # Use DictReader to automatically handle headers
            reader = csv.DictReader(csvfile)
            
            data = []
            for row in reader:
                # Map CSV columns to our database fields
                location_data = {
                    'ip_address': row.get('ip_address', '').strip(),
                    'country': row.get('country', '').strip(),
                    'region': row.get('region', '').strip(), 
                    'city': row.get('city', '').strip(),
                    'lat': float(row.get('latitude', 0)) if row.get('latitude') else None,
                    'lon': float(row.get('longitude', 0)) if row.get('longitude') else None,
                    'timezone': row.get('timezone', '').strip(),
                    'zip': row.get('zip_code', '').strip(),
                    'isp': row.get('isp', '').strip(),
                    'org': row.get('org', '').strip(),
                    'as': row.get('as_number', '').strip() + ' ' + row.get('as_name', '').strip()
                }
                
                # Only add if we have an IP address
                if location_data['ip_address']:
                    data.append(location_data)
            
            print(f"✅ Read {len(data)} records from CSV")
            return data
            
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return []

def import_unique_ips(csv_filename: str = "data.csv") -> bool:
    """Import IP location data from CSV, only inserting unique IPs"""
    
    print("🌍 Starting IP Location Data Import")
    print("=" * 50)
    
    # Get existing IPs from database
    existing_ips = get_existing_ips()
    
    # Read CSV data
    csv_data = read_csv_data(csv_filename)
    if not csv_data:
        return False
    
    # Filter out IPs that already exist
    new_ips = []
    skipped_count = 0
    
    for record in csv_data:
        ip_address = record['ip_address']
        if ip_address not in existing_ips:
            new_ips.append(record)
        else:
            skipped_count += 1
    
    print(f"📊 Import Summary:")
    print(f"   - Total IPs in CSV: {len(csv_data)}")
    print(f"   - Already in database: {skipped_count}")
    print(f"   - New IPs to import: {len(new_ips)}")
    
    if not new_ips:
        print("✅ No new IPs to import - all already exist in database")
        return True
    
    # Import new IPs
    success_count = 0
    error_count = 0
    
    print(f"\n🔄 Importing {len(new_ips)} new IP records...")
    
    for i, record in enumerate(new_ips, 1):
        ip_address = record['ip_address']
        
        # Use the existing save_ip_location_data function
        if save_ip_location_data(ip_address, record):
            success_count += 1
            print(f"[{i:3}/{len(new_ips)}] ✅ {ip_address[:15]:<15} -> {record.get('city', 'Unknown')}, {record.get('country', 'Unknown')}")
        else:
            error_count += 1
            print(f"[{i:3}/{len(new_ips)}] ❌ {ip_address[:15]:<15} -> Failed to insert")
    
    print(f"\n📊 Import Results:")
    print(f"   - Successfully imported: {success_count}")
    print(f"   - Failed imports: {error_count}")
    print(f"   - Success rate: {success_count/len(new_ips)*100:.1f}%")
    
    return error_count == 0

def verify_import(sample_size: int = 5) -> None:
    """Verify the import by checking a few random records"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT ip_address, city, region, country, isp 
            FROM twomanspades.ip_location_data 
            WHERE lookup_success = true
            ORDER BY created_at DESC 
            LIMIT %s
        """, (sample_size,))
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            print(f"\n🔍 Recent imports verification (last {len(results)} records):")
            print("-" * 70)
            for ip, city, region, country, isp in results:
                location = f"{city}, {region}, {country}"
                print(f"{ip[:15]:<15} | {location[:30]:<30} | {isp[:20]}")
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")

def main():
    """Main execution function"""
    
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
    
    # Import the data
    success = import_unique_ips("data.csv")
    
    if success:
        # Verify the import
        verify_import()
        print("\n✨ IP location data import completed successfully!")
    else:
        print("\n❌ Import completed with errors")

if __name__ == "__main__":
    main()