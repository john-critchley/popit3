#!/usr/bin/env python3
"""
RSS Feed Reader for JobServe
Reads RSS feeds from config file and saves raw data for inspection
"""

import feedparser
import os
import json
import datetime
from urllib.parse import urlparse


def load_rss_urls(config_file="rss_feeds.txt"):
    """Load RSS URLs from config file, ignoring comments"""
    urls = []
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
    return urls


def fetch_rss_feed(url):
    """Fetch and parse RSS feed from URL"""
    print(f"Fetching RSS feed: {url}")
    
    # Parse the RSS feed
    feed = feedparser.parse(url)
    
    # Check for errors
    if feed.bozo:
        print(f"Warning: Feed parsing had issues: {feed.bozo_exception}")
    
    print(f"Feed title: {feed.feed.get('title', 'Unknown')}")
    print(f"Feed description: {feed.feed.get('description', 'No description')}")
    print(f"Number of entries: {len(feed.entries)}")
    
    return feed


def save_feed_data(feed, url, output_dir="rss_output"):
    """Save feed data to files for inspection"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Generate filename from URL and timestamp
    parsed_url = urlparse(url)
    feed_id = parsed_url.path.split('/')[-1].replace('.rss', '')
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save raw feed info
    feed_info = {
        'url': url,
        'timestamp': timestamp,
        'feed_title': feed.feed.get('title', ''),
        'feed_description': feed.feed.get('description', ''),
        'feed_link': feed.feed.get('link', ''),
        'entry_count': len(feed.entries)
    }
    
    info_file = os.path.join(output_dir, f"{feed_id}_info_{timestamp}.json")
    with open(info_file, 'w') as f:
        json.dump(feed_info, f, indent=2)
    
    print(f"Feed info saved to: {info_file}")
    
    # Save each entry
    for i, entry in enumerate(feed.entries):
        entry_data = {
            'title': entry.get('title', ''),
            'link': entry.get('link', ''),
            'description': entry.get('description', ''),
            'published': entry.get('published', ''),
            'guid': entry.get('guid', ''),
            'id': entry.get('id', ''),
            'summary': entry.get('summary', ''),
            'author': entry.get('author', ''),
            # Include all available fields for inspection
            'all_fields': dict(entry)
        }
        
        entry_file = os.path.join(output_dir, f"{feed_id}_entry_{i:03d}_{timestamp}.json")
        with open(entry_file, 'w') as f:
            json.dump(entry_data, f, indent=2)
    
    print(f"Saved {len(feed.entries)} entries to {output_dir}/")
    
    # Save one human-readable summary
    summary_file = os.path.join(output_dir, f"{feed_id}_summary_{timestamp}.txt")
    with open(summary_file, 'w') as f:
        f.write(f"RSS Feed Summary\n")
        f.write(f"URL: {url}\n")
        f.write(f"Title: {feed.feed.get('title', 'Unknown')}\n")
        f.write(f"Entries: {len(feed.entries)}\n")
        f.write(f"Fetched: {timestamp}\n\n")
        
        for i, entry in enumerate(feed.entries):
            f.write(f"Entry {i+1}:\n")
            f.write(f"  Title: {entry.get('title', 'No title')}\n")
            f.write(f"  Published: {entry.get('published', 'No date')}\n")
            f.write(f"  GUID: {entry.get('guid', 'No GUID')}\n")
            f.write(f"  Link: {entry.get('link', 'No link')}\n")
            f.write(f"  Description: {entry.get('description', 'No description')[:200]}...\n")
            f.write("-" * 60 + "\n")
    
    print(f"Human-readable summary saved to: {summary_file}")


def main():
    """Main function to process all RSS feeds"""
    print("JobServe RSS Feed Reader")
    print("=" * 40)
    
    # Load RSS URLs from config
    urls = load_rss_urls()
    
    if not urls:
        print("No RSS URLs found in rss_feeds.txt")
        return
    
    print(f"Found {len(urls)} RSS URLs to process")
    
    # Process each URL
    for i, url in enumerate(urls, 1):
        print(f"\nProcessing feed {i}/{len(urls)}")
        try:
            feed = fetch_rss_feed(url)
            save_feed_data(feed, url)
        except Exception as e:
            print(f"Error processing {url}: {e}")
            continue
    
    print("\nRSS processing complete!")
    print("Check the 'rss_output' directory for saved data")


if __name__ == "__main__":
    main()