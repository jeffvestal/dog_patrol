#!/usr/bin/env python3
"""
Backfill Script for Dog Patrol Activity Renaming

This script fetches past Strava activities and renames outdoor Walk activities
using the same time-based naming logic as the Cloud Function.

Usage:
    # Dry run - see what would change (uses Firestore credentials)
    python backfill_activities.py --dry-run --months 6

    # Actually update (uses Firestore credentials)
    python backfill_activities.py --months 6

    # Use direct credentials instead of Firestore
    python backfill_activities.py --months 6 \
        --client-id YOUR_CLIENT_ID \
        --client-secret YOUR_CLIENT_SECRET \
        --refresh-token YOUR_REFRESH_TOKEN

    # Update just the last 30 days
    python backfill_activities.py --days 30
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import pytz
import requests

# Try to import Firestore (optional for standalone mode)
try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    print("⚠️  google-cloud-firestore not available. Use --client-id, --client-secret, and --refresh-token flags.")


# Constants
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
FIRESTORE_COLLECTION = "auth"
FIRESTORE_DOCUMENT = "strava_config"

# Rate limiting (Strava: 100 requests per 15 min, 1000 per day)
REQUEST_DELAY = 0.2  # 200ms between requests (safe margin)
MAX_RETRIES = 3
RATE_LIMIT_BUFFER = 5  # Seconds to wait after rate limit reset


class StravaBackfiller:
    """Handles backfilling of Strava activity names."""
    
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, 
                 timezone: str = "America/Los_Angeles", dry_run: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.timezone = timezone
        self.dry_run = dry_run
        self.access_token = None
        self.stats = {
            "total_fetched": 0,
            "walks_found": 0,
            "already_named": 0,
            "to_rename": 0,
            "renamed": 0,
            "errors": 0
        }
    
    def _parse_rate_limit_headers(self, headers: dict) -> dict:
        """
        Parse Strava rate limit headers.
        Strava has two separate limits:
        - Overall: X-RateLimit-* (200/15min, 2000/day)
        - Non-upload: X-ReadRateLimit-* (100/15min, 1000/day) - STRICTER
        
        Returns dict with all rate limit info.
        """
        result = {}
        
        try:
            # Overall limits (X-RateLimit-Limit: "200,2000")
            limit = headers.get('X-RateLimit-Limit', '')
            if limit:
                limits = limit.split(',')
                result['overall_15min_limit'] = int(limits[0])
                result['overall_daily_limit'] = int(limits[1])
            
            # Overall usage (X-RateLimit-Usage: "105,408")
            usage = headers.get('X-RateLimit-Usage', '')
            if usage:
                usages = usage.split(',')
                result['overall_15min_usage'] = int(usages[0])
                result['overall_daily_usage'] = int(usages[1])
            
            # Non-upload (read) limits (X-ReadRateLimit-Limit: "100,1000")
            # This is the ACTUAL limiting factor for GET/PUT activity calls
            read_limit = headers.get('X-ReadRateLimit-Limit', '')
            if read_limit:
                limits = read_limit.split(',')
                result['read_15min_limit'] = int(limits[0])
                result['read_daily_limit'] = int(limits[1])
            
            # Non-upload (read) usage (X-ReadRateLimit-Usage: "100,342")
            read_usage = headers.get('X-ReadRateLimit-Usage', '')
            if read_usage:
                usages = read_usage.split(',')
                result['read_15min_usage'] = int(usages[0])
                result['read_daily_usage'] = int(usages[1])
        
        except (ValueError, IndexError):
            pass
        
        return result
    
    def _calculate_next_reset_time(self) -> Tuple[datetime, int]:
        """
        Calculate the next 15-minute rate limit reset time.
        Strava resets at 0, 15, 30, 45 minutes past each hour.
        
        Returns: (next_reset_datetime, seconds_until_reset)
        """
        now = datetime.now()
        current_minute = now.minute
        
        # Find next reset minute (0, 15, 30, 45)
        if current_minute < 15:
            next_reset_minute = 15
        elif current_minute < 30:
            next_reset_minute = 30
        elif current_minute < 45:
            next_reset_minute = 45
        else:
            next_reset_minute = 0
        
        # Calculate next reset time
        if next_reset_minute == 0:
            # Next hour
            next_reset = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_reset = now.replace(minute=next_reset_minute, second=0, microsecond=0)
        
        seconds_until_reset = int((next_reset - now).total_seconds())
        
        return next_reset, seconds_until_reset
    
    def _make_request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request with smart retry logic for rate limiting."""
        for attempt in range(MAX_RETRIES):
            response = requests.request(method, url, **kwargs)
            
            if response.status_code == 429:
                # Parse rate limit headers
                limits = self._parse_rate_limit_headers(response.headers)
                
                # Calculate wait time until next reset
                next_reset, seconds_until_reset = self._calculate_next_reset_time()
                wait_time = seconds_until_reset + RATE_LIMIT_BUFFER
                
                # Log detailed rate limit information
                now = datetime.now()
                retry_time = now + timedelta(seconds=wait_time)
                
                print(f"\n   ⏳ Rate limited (429) - Attempt {attempt + 1}/{MAX_RETRIES}")
                print(f"   Current time: {now.strftime('%H:%M:%S')}")
                print()
                
                # Show both rate limits (overall and non-upload)
                if limits.get('overall_15min_usage') is not None:
                    print(f"   Overall 15-min:    {limits['overall_15min_usage']}/{limits['overall_15min_limit']} requests")
                
                if limits.get('read_15min_usage') is not None:
                    print(f"   Non-upload 15-min: {limits['read_15min_usage']}/{limits['read_15min_limit']} requests ⚠️  LIMITING FACTOR")
                
                if limits.get('read_daily_usage') is not None:
                    print(f"   Daily usage:       {limits['read_daily_usage']}/{limits['read_daily_limit']} requests")
                
                print()
                print(f"   Next 15-min reset: {next_reset.strftime('%H:%M:%S')}")
                print(f"   Waiting {seconds_until_reset}s until reset + {RATE_LIMIT_BUFFER}s buffer = {wait_time}s total")
                print(f"   Will retry at: {retry_time.strftime('%H:%M:%S')}")
                print()
                
                time.sleep(wait_time)
                continue
            
            return response
        
        # If we exhausted retries, return the last response
        return response
    
    def get_access_token(self) -> str:
        """Get a fresh access token using the refresh token."""
        print("🔑 Getting access token...")
        
        response = self._make_request_with_retry(
            "POST",
            STRAVA_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=10,
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to refresh token: {response.status_code} - {response.text}")
        
        token_data = response.json()
        self.access_token = token_data.get("access_token")
        print("✅ Access token obtained")
        return self.access_token
    
    def fetch_activities(self, after: datetime, per_page: int = 100) -> List[Dict[str, Any]]:
        """Fetch all activities after a given date."""
        print(f"📥 Fetching activities since {after.strftime('%Y-%m-%d')}...")
        
        activities = []
        page = 1
        after_timestamp = int(after.timestamp())
        
        while True:
            url = f"{STRAVA_API_BASE}/athlete/activities"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            params = {
                "after": after_timestamp,
                "per_page": per_page,
                "page": page
            }
            
            response = self._make_request_with_retry("GET", url, headers=headers, params=params, timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch activities: {response.status_code} - {response.text}")
            
            page_activities = response.json()
            
            if not page_activities:
                break
            
            activities.extend(page_activities)
            print(f"   Fetched page {page}: {len(page_activities)} activities")
            
            page += 1
            time.sleep(REQUEST_DELAY)
        
        self.stats["total_fetched"] = len(activities)
        print(f"✅ Total activities fetched: {len(activities)}")
        return activities
    
    def determine_activity_name(self, start_date_local: str) -> str:
        """
        Determine activity name based on time of day.
        Same logic as the Cloud Function.
        
        Note: start_date_local is ALREADY in local time from Strava.
        """
        # Parse the datetime - it's already in local time
        dt = datetime.fromisoformat(start_date_local.replace("Z", ""))
        hour = dt.hour
        
        if 4 <= hour < 11:
            return "Morning Shakeout 🐕‍🦺"
        elif 11 <= hour < 14:
            return "Lunch Break Sniffari 👃🐕‍🦺"
        else:
            return "Evening Patrol 🐕‍🦺"
    
    def is_already_dog_named(self, name: str) -> bool:
        """Check if activity is already named with dog theme."""
        dog_keywords = ["Dog Patrol", "Sniffari", "🐕", "👃"]
        return any(keyword in name for keyword in dog_keywords)
    
    def update_activity_name(self, activity_id: int, new_name: str) -> bool:
        """Update activity name via Strava API."""
        url = f"{STRAVA_API_BASE}/activities/{activity_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        data = {"name": new_name}
        
        response = self._make_request_with_retry("PUT", url, headers=headers, json=data, timeout=10)
        
        if response.status_code != 200:
            print(f"   ❌ Failed to update activity {activity_id}: {response.status_code}")
            return False
        
        return True
    
    def process_activities(self, activities: List[Dict[str, Any]]) -> None:
        """Process and rename eligible activities."""
        print("\n🔍 Processing activities...\n")
        
        for i, activity in enumerate(activities, 1):
            activity_id = activity.get("id")
            activity_type = activity.get("type")
            trainer = activity.get("trainer", False)
            old_name = activity.get("name", "Unnamed")
            start_date = activity.get("start_date_local")
            
            # Filter 1: Must be a Walk
            if activity_type != "Walk":
                continue
            
            self.stats["walks_found"] += 1
            
            # Filter 2: Must be outdoor
            if trainer:
                continue
            
            # Determine new name
            new_name = self.determine_activity_name(start_date)
            
            # Skip if already has the correct name
            if old_name == new_name:
                print(f"[{i}/{len(activities)}] ✅ Already correct: {old_name}")
                self.stats["already_named"] += 1
                continue
            
            # Format date for display
            dt = datetime.fromisoformat(start_date.replace("Z", ""))
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            
            print(f"[{i}/{len(activities)}] 📝 {date_str}")
            print(f"   Old: {old_name}")
            print(f"   New: {new_name}")
            
            self.stats["to_rename"] += 1
            
            if not self.dry_run:
                if self.update_activity_name(activity_id, new_name):
                    print(f"   ✅ Renamed successfully")
                    self.stats["renamed"] += 1
                else:
                    self.stats["errors"] += 1
                
                time.sleep(REQUEST_DELAY)
            else:
                print(f"   🔍 [DRY RUN - would rename]")
            
            print()
    
    def print_summary(self) -> None:
        """Print summary statistics."""
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"Total activities fetched:    {self.stats['total_fetched']}")
        print(f"Walk activities found:       {self.stats['walks_found']}")
        print(f"Already dog-named:           {self.stats['already_named']}")
        print(f"Activities to rename:        {self.stats['to_rename']}")
        
        if self.dry_run:
            print(f"\n🔍 DRY RUN MODE - No changes were made")
            print(f"   Run without --dry-run to actually rename activities")
        else:
            print(f"\n✅ Successfully renamed:     {self.stats['renamed']}")
            if self.stats['errors'] > 0:
                print(f"❌ Errors:                   {self.stats['errors']}")
        
        print("="*60 + "\n")


def get_credentials_from_firestore() -> Dict[str, str]:
    """Get credentials from Firestore."""
    if not FIRESTORE_AVAILABLE:
        raise Exception("google-cloud-firestore not installed. Use pip install google-cloud-firestore")
    
    print("🔐 Fetching credentials from Firestore...")
    db = firestore.Client()
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOCUMENT)
    doc = doc_ref.get()
    
    if not doc.exists:
        raise ValueError(f"Firestore document {FIRESTORE_COLLECTION}/{FIRESTORE_DOCUMENT} does not exist")
    
    config = doc.to_dict()
    
    return {
        "refresh_token": config.get("refresh_token"),
        "client_id": os.environ.get("STRAVA_CLIENT_ID"),
        "client_secret": os.environ.get("STRAVA_CLIENT_SECRET"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Strava walk activity names with dog-themed titles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Time range options
    time_group = parser.add_mutually_exclusive_group()
    time_group.add_argument("--days", type=int, help="Number of days to look back (e.g., 30)")
    time_group.add_argument("--months", type=int, help="Number of months to look back (e.g., 6)")
    
    # Credential options (standalone mode)
    parser.add_argument("--client-id", help="Strava Client ID (or use STRAVA_CLIENT_ID env var)")
    parser.add_argument("--client-secret", help="Strava Client Secret (or use STRAVA_CLIENT_SECRET env var)")
    parser.add_argument("--refresh-token", help="Strava Refresh Token")
    
    # Other options
    parser.add_argument("--timezone", default="America/Los_Angeles", 
                       help="Timezone for activity times (default: America/Los_Angeles)")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Preview changes without actually renaming")
    
    args = parser.parse_args()
    
    # Determine time range
    if args.days:
        after = datetime.now() - timedelta(days=args.days)
    elif args.months:
        after = datetime.now() - timedelta(days=args.months * 30)
    else:
        # Default to 6 months
        after = datetime.now() - timedelta(days=180)
    
    # Get credentials
    if args.client_id and args.client_secret and args.refresh_token:
        # Standalone mode: use provided credentials
        client_id = args.client_id
        client_secret = args.client_secret
        refresh_token = args.refresh_token
        print("🔧 Using provided credentials (standalone mode)")
    else:
        # Firestore mode: fetch from Firestore and env vars
        try:
            creds = get_credentials_from_firestore()
            client_id = args.client_id or creds["client_id"]
            client_secret = args.client_secret or creds["client_secret"]
            refresh_token = args.refresh_token or creds["refresh_token"]
            
            if not all([client_id, client_secret, refresh_token]):
                print("❌ Error: Missing credentials")
                print("   Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET environment variables")
                print("   Or use --client-id, --client-secret, and --refresh-token flags")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Error fetching credentials: {e}")
            print("\nTry using standalone mode with flags:")
            print("   --client-id YOUR_ID --client-secret YOUR_SECRET --refresh-token YOUR_TOKEN")
            sys.exit(1)
    
    # Run backfill
    try:
        print("\n🐕‍🦺 Dog Patrol Activity Backfiller")
        print("="*60)
        if args.dry_run:
            print("🔍 DRY RUN MODE - No changes will be made")
        print(f"📅 Looking back: {after.strftime('%Y-%m-%d')}")
        print(f"🌍 Timezone: {args.timezone}")
        print("="*60 + "\n")
        
        backfiller = StravaBackfiller(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            timezone=args.timezone,
            dry_run=args.dry_run
        )
        
        # Get access token
        backfiller.get_access_token()
        
        # Fetch activities
        activities = backfiller.fetch_activities(after)
        
        if not activities:
            print("\n📭 No activities found in the specified time range.")
            return
        
        # Process and rename
        backfiller.process_activities(activities)
        
        # Print summary
        backfiller.print_summary()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

