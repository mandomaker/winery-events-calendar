#!/usr/bin/env python3
"""
search_winery_emails.py
Search Gmail for winery/vineyard event emails using gog CLI.
Returns JSON array of candidate emails.

Usage:
    python3 search_winery_emails.py --account user@gmail.com [--days 30] [--max 50]
"""

import subprocess
import json
import argparse
import sys

SEARCH_QUERY = (
    '(winery OR vineyard OR "wine club" OR "wine tasting" OR "wine dinner" '
    'OR "wine release" OR "barrel tasting" OR "winemaker dinner" OR "harvest event" '
    'OR "club pickup" OR "member pickup" OR "wine pickup" OR "tasting room" '
    'OR "wine event" OR "release party" OR "cellar door") '
    '-subject:receipt -subject:invoice -subject:unsubscribe'
)

def search_emails(account: str, days: int, max_results: int) -> list:
    query = f"{SEARCH_QUERY} newer_than:{days}d"
    
    cmd = [
        "gog", "gmail", "messages", "search",
        query,
        "--max", str(max_results),
        "--account", account,
        "--json"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"Error searching Gmail: {result.stderr}", file=sys.stderr)
            return []
        
        data = json.loads(result.stdout)
        
        # Normalize output — gog may return list or wrapped object
        if isinstance(data, list):
            messages = data
        elif isinstance(data, dict):
            messages = data.get("messages", data.get("results", []))
        else:
            messages = []
        
        # Return simplified list
        return [
            {
                "id": m.get("id", ""),
                "subject": m.get("subject", m.get("snippet", "")[:60]),
                "date": m.get("date", m.get("internalDate", "")),
                "snippet": m.get("snippet", "")[:200],
                "from": m.get("from", ""),
            }
            for m in messages
        ]
    
    except subprocess.TimeoutExpired:
        print("Gmail search timed out", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Failed to parse gog output: {e}", file=sys.stderr)
        return []

def main():
    parser = argparse.ArgumentParser(description="Search Gmail for winery event emails")
    parser.add_argument("--account", required=True, help="Gmail account (e.g. user@gmail.com)")
    parser.add_argument("--days", type=int, default=30, help="Search emails from last N days (default: 30)")
    parser.add_argument("--max", type=int, default=50, help="Max emails to return (default: 50)")
    args = parser.parse_args()

    emails = search_emails(args.account, args.days, args.max)
    print(json.dumps(emails, indent=2))
    print(f"\n# Found {len(emails)} candidate emails", file=sys.stderr)

if __name__ == "__main__":
    main()
