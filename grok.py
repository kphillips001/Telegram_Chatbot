#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_grok.py

Grok-based classifier for sentiment, sexual intent, and sexual intensity.
Hardened + normalized version for PINW2.

Cleanup status:
- Removed raw API key printing
- Removed module-level dotenv loading
- Added safe optional debug logging via PRINT_DEBUG
- Kept classifier behavior intact
"""

from openai import AsyncOpenAI

from config import GROK_API_KEY, GROK_MODEL, GROK_BASE_URL, PRINT_DEBUG


# ==========================================================
# OPTIONAL DEBUG LOGGER
# ==========================================================
def debug_log(*args) -> None:
    if PRINT_DEBUG:
        print(*args)


# ==========================================================
# CLIENT SETUP
# ==========================================================
client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url=GROK_BASE_URL,
)

debug_log("✅ Grok client initialized")


# ==========================================================
# SAFE RESPONSE EXTRACTOR
# ==========================================================
def clean_response(resp) -> str:
    if not resp:
        return ""

    try:
        msg = resp.choices[0].message.content
        if not msg:
            return ""

        msg = msg.strip().lower()
        msg = msg.replace(".", "").replace("!", "").replace(",", "")

        debug_log("CLEANED RESULT:", msg)
        return msg

    except Exception:
        return ""


# ==========================================================
# SENTIMENT CLASSIFIER
# ==========================================================
async def grok_sentiment(message: str) -> str:
    if not message or not message.strip():
        return "neutral"

    prompt = [
        {
            "role": "system",
            "content": (
                "Classify the user's message into EXACTLY one category:\n"
                "- sexual\n"
                "- affectionate\n"
                "- jealous\n"
                "- rude\n"
                "- neutral\n\n"
                "You must return ONLY the single word. No punctuation. No explanation."
            ),
        },
        {"role": "user", "content": message},
    ]

    try:
        resp = await client.chat.completions.create(
            model=GROK_MODEL,
            messages=prompt,
            temperature=0.0,
            max_tokens=5,
        )

        result = clean_response(resp)
        allowed = {"sexual", "affectionate", "jealous", "rude", "neutral"}

        return result if result in allowed else "neutral"

    except Exception as e:
        debug_log(f"❌ Error in grok_sentiment: {e}")
        return "neutral"


# ==========================================================
# SEXUAL INTENT (YES / NO)
# ==========================================================
async def grok_is_sexual(message: str) -> bool:
    if not message or not message.strip():
        return False

    prompt = [
        {
            "role": "system",
            "content": (
                "Does this message show sexual intent?\n"
                "Sexual intent includes explicit desire, fantasies, wanting sexual access, "
                "dirty talk, or attempts to sexualize the conversation.\n\n"
                "Respond ONLY with YES or NO."
            ),
        },
        {"role": "user", "content": message},
    ]

    try:
        resp = await client.chat.completions.create(
            model=GROK_MODEL,
            messages=prompt,
            temperature=0.0,
            max_tokens=5,
        )

        ans = clean_response(resp)
        return ans.startswith("y")

    except Exception as e:
        debug_log(f"❌ Error in grok_is_sexual: {e}")
        return False


# ==========================================================
# SEXUAL INTENSITY CLASSIFIER
# ==========================================================
async def grok_sexual_intensity(message: str) -> str:
    if not message or not message.strip():
        return "none"

    prompt = [
        {
            "role": "system",
            "content": (
                "You will classify the sexual intensity of this message into EXACTLY one category:\n"
                "- explicit\n"
                "- strong\n"
                "- flirty\n"
                "- none\n\n"
                "Return ONLY the single word."
            ),
        },
        {"role": "user", "content": message},
    ]

    try:
        resp = await client.chat.completions.create(
            model=GROK_MODEL,
            messages=prompt,
            temperature=0.0,
            max_tokens=5,
        )

        debug_log("\n================ GROK DEBUG ================")
        debug_log("INPUT:", message)
        debug_log("RAW RESPONSE OBJECT:", resp)
        debug_log("===========================================\n")

        result = clean_response(resp)

        if "explicit" in result:
            result = "explicit"
        elif "strong" in result:
            result = "strong"
        elif "flirt" in result:
            result = "flirty"

        sentiment = await grok_sentiment(message)
        if sentiment == "rude":
            return "none"

        allowed = {"explicit", "strong", "flirty", "none"}
        return result if result in allowed else "none"

    except Exception as e:
        debug_log(f"❌ Error in grok_sexual_intensity: {e}")
        return "none"