#!/usr/bin/env python3
"""
Cron-safe wrapper for tracker operations.
"""

import os
import sys
import fcntl
import subprocess
from pathlib import Path

PIDFILE = "/tmp/tracker-process.pid"

def acquire_lock():
    """Acquire PID lock to prevent concurrent runs."""
    try:
        fd = os.open(PIDFILE, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.truncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except (IOError, OSError):
        print("Another tracker process is already running. Exiting.")
        sys.exit(0)

def release_lock(fd):
    """Release PID lock."""
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    try:
        os.unlink(PIDFILE)
    except:
        pass

if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    
    # Forward all arguments to the actual processing script
    # Default: search for my open issues
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # First arg is a subcommand
        subcommand = sys.argv[1]
        args = sys.argv[2:]
        
        script_map = {
            "search": "search_issues.py",
            "create": "create_issue.py",
            "my": "my_issues.py",
            "get": "get_issue.py",
            "comment": "add_comment.py",
            "update": "update_issue.py",
            "board": "get_board.py",
            "queues": "get_queues.py",
        }
        
        script = script_map.get(subcommand, "my_issues.py")
        script_path = script_dir / script
    else:
        # No subcommand, just forward all args to my_issues.py
        script_path = script_dir / "my_issues.py"
        args = sys.argv[1:]
    
    if not script_path.exists():
        print(f"Script not found: {script_path}")
        sys.exit(1)
    
    lock_fd = acquire_lock()
    
    try:
        result = subprocess.run([sys.executable, str(script_path)] + args)
        sys.exit(result.returncode)
    finally:
        release_lock(lock_fd)
