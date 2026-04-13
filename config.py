#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_config.py
Enhanced debugging version (PINW2 ready)
Corrected dotenv load order — ensures Grok API key loads properly.
"""

import os
from dotenv import load_dotenv

# =====================================================
# 1. LOAD .env FIRST — BEFORE ANY os.getenv CALL
# =====================================================
ENV_LOADED = load_dotenv()
if not ENV_LOADED:
    print("⚠️ WARNING: .env file not found or not loaded!")

# =====================================================
# 2. Helper for strict environment variable loading
# =====================================================
def fetch_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"❌ Missing {name} in .env")
    return value


# =====================================================
# 3. Telegram Tokens
# =====================================================
TELEGRAM_BOT_TOKEN_AVA = fetch_env("TELEGRAM_BOT_TOKEN_AVA")
TELEGRAM_BOT_TOKEN_AMANDA = fetch_env("TELEGRAM_BOT_TOKEN_AMANDA")


# =====================================================
# 4. QA Testing
# =====================================================
QA_MODE = os.getenv("QA_MODE", "0") in ("1", "true", "True", "TRUE")
QA_TESTER_ID = os.getenv("QA_TESTER_ID", "")


# =====================================================
# 5. OpenAI API Key
# =====================================================
OPENAI_API_KEY = fetch_env("OPENAI_API_KEY")


# =====================================================
# 6. GROK API Keys (CRITICAL SECTION)
# =====================================================
GROK_API_KEY = fetch_env("GROK_API_KEY")   # MUST load after dotenv
GROK_MODEL   = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")

# Debug print to CONFIRM correct key
print(f"🔍 [tg_config] Loaded GROK_API_KEY (first 12): {GROK_API_KEY[:12]}...")


# =====================================================
# 7. Database Credentials
# =====================================================
TG_DB_HOST = fetch_env("TG_DB_HOST")
TG_DB_NAME = fetch_env("TG_DB_NAME")
TG_DB_USER = fetch_env("TG_DB_USER")
TG_DB_PASSWORD = fetch_env("TG_DB_PASSWORD")


# =====================================================
# 8. Fanvue Persona Links
# =====================================================
FANVUE_LINK_AMANDA = fetch_env("FANVUE_LINK_AMANDA")
FANVUE_LINK_AVA = fetch_env("FANVUE_LINK_AVA")


# =====================================================
# 9. CTA Redirect Domain
# =====================================================
BASE_DOMAIN = fetch_env("BASE_DOMAIN")


# =====================================================
# 10. Persona Tone Settings
# =====================================================
AI_TONE = {
    "short_replies": True,
    "flirty": True,
    "witty": True,
    "emoji_density": "medium",
    "cta_to_fanvue": True,
    "cta_to_telegram": False,
    "deflect_ai_accusations": True,
}


# =====================================================
# 11. Debug Dump
# =====================================================
PRINT_DEBUG = True

if PRINT_DEBUG:
    print("====================================================")
    print("🔧 Telegram Config Loaded (Corrected)")
    print("----------------------------------------------------")
    print(f"ENV_LOADED: {ENV_LOADED}")

    print(f"AVA TOKEN (first 8):      {TELEGRAM_BOT_TOKEN_AVA[:8]}…")
    print(f"AMANDA TOKEN (first 8):   {TELEGRAM_BOT_TOKEN_AMANDA[:8]}…")

    print(f"OPENAI KEY (first 8):     {OPENAI_API_KEY[:8]}…")

    print(f"GROK KEY (first 12):      {GROK_API_KEY[:12]}…")
    print(f"GROK MODEL:               {GROK_MODEL}")
    print(f"GROK BASE URL:            {GROK_BASE_URL}")

    print(f"TG_DB_HOST:               {TG_DB_HOST}")
    print(f"TG_DB_NAME:               {TG_DB_NAME}")
    print(f"TG_DB_USER:               {TG_DB_USER}")

    print(f"FANVUE_LINK_AMANDA:       {FANVUE_LINK_AMANDA}")
    print(f"FANVUE_LINK_AVA:          {FANVUE_LINK_AVA}")

    print(f"BASE_DOMAIN:              {BASE_DOMAIN}")

    print(f"QA_MODE:                  {QA_MODE}")
    print(f"QA_TESTER_ID:             {QA_TESTER_ID}")
    print("====================================================")