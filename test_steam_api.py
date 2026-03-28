#!/usr/bin/env python3
"""Test script to verify Steam API connection and key validity."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from services.dota_monitor import DotaMonitor


async def main():
    """Test Steam API connection."""
    print("=" * 60)
    print("Steam API Connection Test")
    print("=" * 60)

    monitor = DotaMonitor()

    print(f"\nConfiguration:")
    print(f"  Steam API Key: {monitor.steam_api_key[:8]}..." if monitor.steam_api_key else "  Steam API Key: NOT SET")
    print(f"  Account ID: {monitor.account_id}" if monitor.account_id else "  Account ID: NOT SET")
    print(f"  Base URL: {monitor.base_url}")

    print("\n" + "-" * 60)
    print("Testing API Connection...")
    print("-" * 60)

    try:
        result = await monitor.test_api_connection()

        print(f"\nTest Results:")
        print(f"  Status: {result['status'].upper()}")
        print(f"  API Key Valid: {result['api_key_valid']}")
        print(f"  Steam ID: {result['steam_id']}")
        print(f"  API Key (masked): {result['steam_api_key']}")

        if result.get('error'):
            print(f"  Error: {result['error']}")

        if result.get('endpoints_tested'):
            print(f"\n  Endpoints Tested:")
            for endpoint in result['endpoints_tested']:
                status_icon = "✓" if endpoint['status'] == 'success' else "✗"
                print(f"    {status_icon} {endpoint['endpoint']} - HTTP {endpoint['response_code']}")

        print("\n" + "=" * 60)

        if result['status'] == 'failed':
            print("\nTROUBLESHOOTING STEPS:")
            print("1. Verify your Steam API key at: https://steamcommunity.com/dev/apikey")
            print("2. Ensure the API key has the required permissions")
            print("3. Check that the API key hasn't expired or been revoked")
            print("4. Verify your Steam ID is correct")
            print("5. Check Steam API status: https://steamcommunity.com/dev/")
            return 1
        else:
            print("\nAPI connection successful!")
            return 0

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)