#!/usr/bin/env python3
"""
Migration script to update existing database entries from JobServe ref keys to Message-ID keys.
This should be run once after updating the jobserve_parser.py to use Message-ID as primary key.
"""

import gdata
import os
import json

def migrate_database():
    """Migrate existing database from JS ref keys to Message-ID keys, creating new database."""
    home = os.environ['HOME']
    old_gdbm_path = os.path.join(home, '.js.gdbm')
    new_gdbm_path = os.path.join(home, '.js_new.gdbm')
    
    if not os.path.exists(old_gdbm_path):
        print(f"ERROR: Old database not found at {old_gdbm_path}")
        return False
    
    if os.path.exists(new_gdbm_path):
        print(f"ERROR: New database already exists at {new_gdbm_path}")
        print("Please remove it first or rename the old one")
        return False
    
    print("Starting database migration...")
    print(f"Reading from: {old_gdbm_path}")
    print(f"Creating: {new_gdbm_path}")
    
    # Read all data from old database
    with gdata.gdata(old_gdbm_path) as old_db:
        # Find all keys that look like JS references
        js_keys = []
        other_keys = []
        
        for key in old_db.keys():
            if isinstance(key, str) and key.startswith('JS'):
                js_keys.append(key)
            else:
                other_keys.append(key)
        
        print(f"Found {len(js_keys)} JobServe reference keys to migrate")
        print(f"Found {len(other_keys)} other keys to copy")
        
        # Prepare migrations
        migrations = []
        
        for js_key in js_keys:
            try:
                email_data = old_db[js_key]
                headers = email_data.get('headers', {})
                message_id = headers.get('Message-ID')
                
                if message_id:
                    # Prepare migrated data with jobserve_ref added
                    new_data = dict(email_data)
                    new_data['jobserve_ref'] = js_key  # Store original JS ref as metadata
                    
                    migrations.append((js_key, message_id, new_data))
                    print(f"Will migrate: {js_key} -> {message_id}")
                else:
                    print(f"WARNING: No Message-ID found for {js_key}, skipping")
            
            except Exception as e:
                print(f"ERROR processing {js_key}: {e}")
        
        # Create new database and copy/migrate data
        with gdata.gdata(new_gdbm_path) as new_db:
            # Migrate JS keys to Message-ID keys
            migrated_mapping = {}  # js_key -> message_id
            
            for js_key, message_id, new_data in migrations:
                try:
                    # Check if new key already exists
                    if message_id in new_db:
                        print(f"WARNING: Message-ID {message_id} already exists, skipping {js_key}")
                        continue
                    
                    # Add under new key
                    new_db[message_id] = new_data
                    migrated_mapping[js_key] = message_id
                    print(f"Migrated: {js_key} -> {message_id}")
                    
                except Exception as e:
                    print(f"ERROR migrating {js_key}: {e}")
            
            # Copy other keys (metadata, date sets, etc.)
            for key in other_keys:
                try:
                    value = old_db[key]
                    
                    # Update metadata sets and date sets to use new Message-IDs
                    if (key.startswith('M:') or (key.isdigit() and len(key) == 8)):
                        if isinstance(value, list):
                            new_value = []
                            for item in value:
                                if item in migrated_mapping:
                                    new_value.append(migrated_mapping[item])
                                elif not item.startswith('JS'):
                                    # Keep non-JS keys (might already be Message-IDs)
                                    new_value.append(item)
                                # Skip JS keys that weren't migrated
                            
                            if new_value:  # Only store non-empty lists
                                new_db[key] = new_value
                                print(f"Updated {key}: {len(value)} -> {len(new_value)} entries")
                        else:
                            new_db[key] = value
                    else:
                        # Copy as-is
                        new_db[key] = value
                        print(f"Copied: {key}")
                
                except Exception as e:
                    print(f"ERROR copying {key}: {e}")
    
    print("\nMigration complete!")
    print(f"Old database preserved at: {old_gdbm_path}")
    print(f"New database created at: {new_gdbm_path}")
    print("\nTo use the new database:")
    print(f"1. Test with: python3 -c 'import query_jobs; print(len(query_jobs.get_all_jobs()))'")
    print(f"2. If OK, rename: mv {old_gdbm_path} {old_gdbm_path}.backup")
    print(f"3. Then: mv {new_gdbm_path} {old_gdbm_path}")
    
    return True

if __name__ == '__main__':
    migrate_database()