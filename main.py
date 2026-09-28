"""Just Talk - Lightweight Desktop Voice Input with Gemini Formatting."""

import multiprocessing
import sys

# Critical for PyInstaller: prevents helper worker processes from re-running main()
multiprocessing.freeze_support()

from just_talk.app.main import main

if __name__ == "__main__":
    main()
