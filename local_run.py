"""
Run this locally (on your PC) to test the bot before deploying to Railway.
It just loads your token from a .env file into the environment, then
starts the same main.py Railway will run.

Usage:
1. Create a file called ".env" in this folder (no filename before the dot)
2. Put this one line inside it: BOT_TOKEN=your_actual_token_here
3. Run: python local_run.py
"""

from dotenv import load_dotenv

load_dotenv()  # reads .env and loads BOT_TOKEN into the environment

import main

if __name__ == "__main__":
    main.main()
