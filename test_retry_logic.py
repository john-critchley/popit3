#!/usr/bin/env python3
"""
Test the enhanced GDBM retry logic with realistic timeouts
"""

from process_lock import retry_gdbm_operation, is_gdbm_locked_error
import time


def test_retry_logic():
    """Test the retry logic with a simulated lock error"""
    
    def failing_operation():
        """Simulates a GDBM lock error for a few attempts"""
        if not hasattr(failing_operation, 'attempts'):
            failing_operation.attempts = 0
        
        failing_operation.attempts += 1
        
        if failing_operation.attempts <= 3:
            # Simulate GDBM lock error
            import errno
            error = OSError()
            error.errno = errno.EAGAIN
            raise error
        
        return f"Success after {failing_operation.attempts} attempts"
    
    print("Testing retry logic with short timeout (20s)...")
    start = time.time()
    
    try:
        result = retry_gdbm_operation(failing_operation, max_timeout=20, initial_delay=1.0)
        elapsed = time.time() - start
        print(f"✓ {result} (took {elapsed:.1f}s)")
    except Exception as e:
        elapsed = time.time() - start
        print(f"✗ Failed: {e} (took {elapsed:.1f}s)")


def test_timeout():
    """Test the timeout behavior"""
    
    def always_failing_operation():
        """Always fails with GDBM lock error"""
        import errno
        error = OSError()
        error.errno = errno.EAGAIN
        raise error
    
    print("\nTesting timeout behavior (10s timeout)...")
    start = time.time()
    
    try:
        result = retry_gdbm_operation(always_failing_operation, max_timeout=10, initial_delay=1.0)
        print(f"Unexpected success: {result}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"✓ Timed out as expected after {elapsed:.1f}s: {type(e).__name__}")


if __name__ == "__main__":
    test_retry_logic()
    test_timeout()