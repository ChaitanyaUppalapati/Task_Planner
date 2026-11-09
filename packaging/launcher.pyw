"""PyInstaller entry point (windowed, no console)."""
import sys

from taskplanner.app import main

if __name__ == "__main__":
    sys.exit(main())
