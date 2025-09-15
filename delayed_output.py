#!/usr/bin/env python3
import sys
import time
import random

def main():
    try:
        for line in sys.stdin:
            # Output the line immediately
            sys.stdout.write(line)
            sys.stdout.flush()
            
            # Random delay between 500 microseconds (0.0005s) and 3 seconds
            delay = random.uniform(0.0002, 1.5)
            time.sleep(delay)
            
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        sys.exit(0)
    except BrokenPipeError:
        # Handle broken pipe gracefully
        sys.exit(0)

if __name__ == "__main__":
    main()