#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_config.py

Loads environment variables for the Telegram bot and exposes validated
configuration values for the rest of the app.
"""

import os
from dotenv import load_dotenv


# =====================================================
# 1. Load .env before any os.getenv calls
# =====================================================
ENV_LOADED = load_dotenv()


# =====================================================
# 2. Helpers
# =====================================================
def fetch_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def fetch_bool(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in ("1", "true", "yes", "on")


# =====================================================
# 3. Telegram Tokens
# =====================================================
TELEGRAM_BOT_TOKEN_AVA = fetch_env("TELEGRAM_BOT_TOKEN_AVA")
TELEGRAM_BOT_TOKEN_AMANDA = fetch_env("TELEGRAM_BOT_TOKEN_AMANDA")


# =====================================================
# 4. QA Testing
# =====================================================
QA_MODE = fetch_bool("QA_MODE", "0")
QA_TESTER_ID = os.getenv("QA_TESTER_ID", "").strip()


# =====================================================
# 5. LLM API Keys
# =====================================================
OPENAI_API_KEY = fetch_env("OPENAI_API_KEY")

GROK_API_KEY = fetch_env("GROK_API_KEY")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini").strip()
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").strip()


# =====================================================
# 6. Database Credentials
# =====================================================
TG_DB_HOST = fetch_env("TG_DB_HOST")
TG_DB_NAME = fetch_env("TG_DB_NAME")
TG_DB_USER = fetch_env("TG_DB_USER")
TG_DB_PASSWORD = fetch_env("TG_DB_PASSWORD")
TG_DB_PORT = os.getenv("TG_DB_PORT", "5432").strip()


# =====================================================
# 7. Telegram / DM entry links
# =====================================================
DMGATE_URL_AMANDA = fetch_env("DMGATE_URL_AMANDA")
DMGATE_URL_AVA = fetch_env("DMGATE_URL_AVA")


# =====================================================
# 8. Persona / bot names
# =====================================================
BOT_NAME_AMANDA = os.getenv("BOT_NAME_AMANDA", "amandacayne").strip()
BOT_NAME_AVA = os.getenv("BOT_NAME_AVA", "avablackthorne").strip()


# =====================================================
# 9. Persona Tone Settings
# =====================================================
AI_TONE = {
    "short_replies": True,
    "flirty": True,
    "witty": True,
    "emoji_density": "medium",
    "cta_to_fanvue": False,
    "cta_to_telegram": True,
    "deflect_ai_accusations": True,
}


# =====================================================
# 10. Safe startup debug
# =====================================================
PRINT_DEBUG = fetch_bool("PRINT_DEBUG", "0")

if PRINT_DEBUG:
    print("====================================================")
    print("Telegram Config Loaded")
    print("----------------------------------------------------")
    print(f"ENV_LOADED: {ENV_LOADED}")
    print(f"GROK_MODEL: {GROK_MODEL}")
    print(f"GROK_BASE_URL: {GROK_BASE_URL}")
    print(f"TG_DB_HOST: {TG_DB_HOST}")
    print(f"TG_DB_NAME: {TG_DB_NAME}")
    print(f"TG_DB_USER: {TG_DB_USER}")
    print(f"TG_DB_PORT: {TG_DB_PORT}")
    print(f"QA_MODE: {QA_MODE}")
    print(f"QA_TESTER_ID set: {bool(QA_TESTER_ID)}")
    print(f"BOT_NAME_AMANDA: {BOT_NAME_AMANDA}")
    print(f"BOT_NAME_AVA: {BOT_NAME_AVA}")
    print("====================================================")