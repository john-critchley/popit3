#!/usr/bin/env python3
"""
Test GDBM concurrent access behavior to understand error conditions
"""

import dbm.gnu as gdbm
import os
import time
import subprocess
import sys
from multiprocessing import Process


def test_concurrent_writers():
    """Test what happens when two processes try to write to the same GDBM file"""
    db_file = "/tmp/test_gdbm_concurrent.db"
    
    # Clean up any existing file
    if os.path.exists(db_file):
        os.unlink(db_file)
    
    def writer_process(process_id, delay=0):
        """Writer process that holds the DB open for a while"""
        try:
            print(f"Process {process_id}: Attempting to open DB for writing")
            with gdbm.open(db_file, 'c') as db:
                print(f"Process {process_id}: Successfully opened DB")
                db[f'key_{process_id}'] = f'value_from_process_{process_id}'
                print(f"Process {process_id}: Written data, holding lock for {delay} seconds")
                time.sleep(delay)
                print(f"Process {process_id}: Releasing lock")
        except Exception as e:
            print(f"Process {process_id}: ERROR - {type(e).__name__}: {e}")
    
    # Start first writer that holds the lock for 3 seconds
    p1 = Process(target=writer_process, args=(1, 3))
    p1.start()
    
    # Wait a bit, then start second writer
    time.sleep(1)
    p2 = Process(target=writer_process, args=(2, 1))
    p2.start()
    
    p1.join()
    p2.join()
    
    # Check final state
    try:
        with gdbm.open(db_file, 'r') as db:
            print("Final DB contents:")
            for key in db.keys():
                print(f"  {key.decode()}: {db[key].decode()}")
    except Exception as e:
        print(f"Error reading final state: {e}")
    
    # Cleanup
    if os.path.exists(db_file):
        os.unlink(db_file)


def test_reader_writer():
    """Test what happens when reader and writer access simultaneously"""
    db_file = "/tmp/test_gdbm_reader_writer.db"
    
    # Clean up and create initial data
    if os.path.exists(db_file):
        os.unlink(db_file)
    
    with gdbm.open(db_file, 'c') as db:
        db['initial'] = 'data'
    
    def reader_process():
        """Reader process"""
        try:
            print("Reader: Attempting to open DB for reading")
            with gdbm.open(db_file, 'r') as db:
                print("Reader: Successfully opened DB")
                for i in range(5):
                    try:
                        value = db['initial']
                        print(f"Reader: Read value: {value.decode()}")
                        time.sleep(1)
                    except KeyError:
                        print("Reader: Key not found")
        except Exception as e:
            print(f"Reader: ERROR - {type(e).__name__}: {e}")
    
    def writer_process():
        """Writer process"""
        try:
            time.sleep(1)  # Let reader start first
            print("Writer: Attempting to open DB for writing")
            with gdbm.open(db_file, 'w') as db:
                print("Writer: Successfully opened DB")
                db['initial'] = 'modified_data'
                db['new_key'] = 'new_value'
                print("Writer: Written data, holding for 3 seconds")
                time.sleep(3)
                print("Writer: Releasing lock")
        except Exception as e:
            print(f"Writer: ERROR - {type(e).__name__}: {e}")
    
    # Start both processes
    reader = Process(target=reader_process)
    writer = Process(target=writer_process)
    
    reader.start()
    writer.start()
    
    reader.join()
    writer.join()
    
    # Cleanup
    if os.path.exists(db_file):
        os.unlink(db_file)


if __name__ == "__main__":
    print("=== Testing Concurrent Writers ===")
    test_concurrent_writers()
    
    print("\n=== Testing Reader + Writer ===")
    test_reader_writer()