#!/usr/bin/env python3
"""Test OpenDota API functionality."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from services.dota_monitor import DotaMonitor


async def main():
    """Test OpenDota API connection."""
    print("=" * 60)
    print("OpenDota API Test")
    print("=" * 60)

    monitor = DotaMonitor()

    print(f"\nConfiguration:")
    print(f"  Steam API Key: {monitor.steam_api_key[:8]}..." if monitor.steam_api_key else "  Steam API Key: NOT SET")
    print(f"  Account ID: {monitor.account_id}" if monitor.account_id else "  Account ID: NOT SET")
    print(f"  OpenDota URL: {monitor.opendota_url}")

    print("\n" + "-" * 60)
    print("Testing OpenDota API...")
    print("-" * 60)

    try:
        # Test player summary
        print("\n1. Testing player summary...")
        player_summary = await monitor.get_player_summary()
        if player_summary:
            print("  ✓ Player summary retrieved successfully")
            print(f"    Name: {player_summary.get('personaname', 'Unknown')}")
            print(f"    Rank: {player_summary.get('rank_tier', 'Unknown')}")
        else:
            print("  ✗ Failed to retrieve player summary")

        # Test match history
        print("\n2. Testing match history...")
        match_history = await monitor.get_match_history(5)
        if match_history:
            print("  ✓ Match history retrieved successfully")
            print(f"    Found {len(match_history)} matches")
        else:
            print("  ✗ Failed to retrieve match history")

        # Test match details
        print("\n3. Testing match details...")
        if match_history and len(match_history) > 0:
            match_id = match_history[0].get('match_id', match_history[0].get('match_id'))
            if match_id:
                match_details = await monitor.get_match_details(match_id)
                if match_details:
                    print("  ✓ Match details retrieved successfully")
                    print(f"    Match ID: {match_id}")
                else:
                    print("  ✗ Failed to retrieve match details")
            else:
                print("  ✗ No valid match ID found")
        else:
            print("  ✗ No matches to test details with")

        print("\n" + "=" * 60)
        print("\nOpenDota API test completed!")
        return 0

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)