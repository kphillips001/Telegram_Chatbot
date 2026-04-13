#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_login_amanda.py
One-time Telethon login script for Amanda Cayne.
Creates tg_sessions/amanda.session after successful login.
"""

import os
import asyncio
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()   # ← THIS loads your .env variables

# ---------------------------------------------------------
# Load API credentials
# ---------------------------------------------------------
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")

SESSION_FOLDER = "tg_sessions"
SESSION_NAME = f"{SESSION_FOLDER}/amanda"   # final path = tg_sessions/amanda.session

# ---------------------------------------------------------
# MAIN LOGIN
# ---------------------------------------------------------
async def main():
    print("📲 Starting Amanda login...")

    # Ensure folder exists
    if not os.path.exists(SESSION_FOLDER):
        os.makedirs(SESSION_FOLDER, exist_ok=True)
        print(f"📁 Created session folder: {SESSION_FOLDER}")

    if not API_ID or not API_HASH:
        print("❌ Missing TG_API_ID or TG_API_HASH in .env")
        return

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    print("➡️  Telethon client created. Beginning login flow...")
    await client.start()   # Prompts for phone + code

    print("✅ Login successful!")
    print(f"💾 Session saved as {SESSION_NAME}.session")

    await client.disconnect()


# ---------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())