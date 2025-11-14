"""
Test script for monthly stats functionality
Run this locally to verify the get_monthly_stats_by_location() function works
"""

import os
import sys
from pprint import pprint

# Add the parent directory to the path so we can import utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utilities.postgres_utils import get_monthly_stats_by_location

def test_monthly_stats():
    print("=" * 80)
    print("Testing get_monthly_stats_by_location()")
    print("=" * 80)
    
    try:
        results = get_monthly_stats_by_location()
        
        print("\n📊 Results structure:")
        print(f"   Number of family members: {len(results)}")
        print(f"   Family members: {list(results.keys())}")
        
        print("\n" + "=" * 80)
        print("DETAILED RESULTS BY FAMILY MEMBER")
        print("=" * 80)
        
        for family_member, data in results.items():
            print(f"\n🏠 {family_member.upper()}")
            print("-" * 80)
            
            monthly_data = data['monthly']
            print(f"   Total months with data: {len(monthly_data)}")
            
            if monthly_data:
                print("\n   Monthly breakdown:")
                for month_stat in monthly_data:
                    month = month_stat['month'].strftime('%B %Y')
                    print(f"\n   📅 {month}")
                    print(f"      Hands Played:     {month_stat['hands_played']}")
                    print(f"      Hands Won:        {month_stat['hands_won']}")
                    print(f"      Hands Lost:       {month_stat['hands_lost']}")
                    print(f"      Avg Player Score: {month_stat['avg_player_score']}")
                    print(f"      Avg CPU Score:    {month_stat['avg_computer_score']}")
                    print(f"      Total Bags:       {month_stat['total_bags']}")
                    
                    if month_stat['hands_played'] > 0:
                        win_rate = (month_stat['hands_won'] / month_stat['hands_played']) * 100
                        print(f"      Win Rate:         {win_rate:.1f}%")
        
        print("\n" + "=" * 80)
        print("✅ TEST COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ ERROR OCCURRED")
        print("=" * 80)
        print(f"\nError type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        
        return False
    
    return True

if __name__ == "__main__":
    print("\n🧪 Starting monthly stats test...\n")
    success = test_monthly_stats()
    
    if success:
        print("\n✨ All tests passed! Function is working correctly.\n")
        sys.exit(0)
    else:
        print("\n💥 Tests failed. Check the error messages above.\n")
        sys.exit(1)