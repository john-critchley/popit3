#!/usr/bin/env python3
"""
Process lock utility to prevent concurrent popit3 runs
"""

import os
import sys
import fcntl
import atexit
import errno
import time
import dbm.gnu as gdbm


class ProcessLock:
    """Simple file-based process lock to prevent concurrent execution"""
    
    def __init__(self, lock_file_path):
        self.lock_file_path = lock_file_path
        self.lock_file = None
    
    def acquire(self):
        """Acquire the lock. Returns True if successful, False if already locked"""
        try:
            self.lock_file = open(self.lock_file_path, 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Write PID to lock file for debugging
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            
            # Ensure lock is released on exit
            atexit.register(self.release)
            
            return True
            
        except (IOError, OSError):
            # Lock already held by another process
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            return False
    
    def release(self):
        """Release the lock"""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                # Remove lock file
                if os.path.exists(self.lock_file_path):
                    os.unlink(self.lock_file_path)
            except (IOError, OSError):
                pass
            finally:
                self.lock_file = None
    
    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another popit3 process is already running")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def is_gdbm_locked_error(exception):
    """Check if exception is a GDBM lock error (EAGAIN/Resource temporarily unavailable)"""
    if hasattr(exception, 'errno'):
        return exception.errno == errno.EAGAIN
    # GDBM errors might be wrapped differently
    return ('Resource temporarily unavailable' in str(exception) or 
            'errno 11' in str(exception).lower())


def retry_gdbm_operation(operation, max_timeout=600, initial_delay=2.0):
    """
    Retry a GDBM operation if it fails due to locking
    
    Args:
        operation: Function to execute
        max_timeout: Maximum time to keep retrying in seconds (default 10 minutes)
        initial_delay: Initial delay between retries in seconds
    
    Returns:
        Result of the operation
    
    Raises:
        The last exception if timeout is reached
    """
    start_time = time.time()
    delay = initial_delay
    attempt = 0
    last_exception = None
    
    while time.time() - start_time < max_timeout:
        try:
            return operation()
        except Exception as e:
            last_exception = e
            if is_gdbm_locked_error(e):
                elapsed = time.time() - start_time
                remaining = max_timeout - elapsed
                
                if remaining <= 0:
                    print(f"GDBM operation timed out after {max_timeout}s")
                    break
                    
                actual_delay = min(delay, remaining)
                attempt += 1
                print(f"GDBM locked, retrying in {actual_delay:.1f}s "
                      f"(attempt {attempt}, {remaining:.0f}s remaining)")
                time.sleep(actual_delay)
                
                # Exponential backoff with maximum cap
                delay = min(delay * 1.3, 30.0)  # Cap at 30 seconds
                continue
            else:
                # Re-raise if not a lock error
                raise
    
    # Timeout reached
    elapsed = time.time() - start_time
    print(f"GDBM operation failed after {elapsed:.1f}s timeout")
    raise last_exception or TimeoutError(f"GDBM operation timed out after {elapsed:.1f}s")


def check_for_running_process(lock_file_path="/tmp/popit3.lock"):
    """Check if another popit3 process is running"""
    lock = ProcessLock(lock_file_path)
    return lock.acquire()