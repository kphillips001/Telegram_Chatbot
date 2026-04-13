#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_grok.py
Grok-based classifier for sentiment, sexual intent, and sexual intensity.
Hardened + normalized version for PINW2.
"""

# ==========================================================
# LOAD .ENV BEFORE ANY CONFIG IMPORTS  (CRITICAL FIX)
# ==========================================================
from dotenv import load_dotenv
load_dotenv()   # Must come BEFORE importing tg_config

import os
from config import GROK_API_KEY, GROK_MODEL, GROK_BASE_URL
from openai import AsyncOpenAI

print("DEBUG KEY FROM ENV IN tg_grok.py:", os.getenv("GROK_API_KEY"))
print("Loaded Grok API Key:", GROK_API_KEY)

# Initialize Grok/OpenAI client (NEW GROK API — correct)
client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url=GROK_BASE_URL
)

print("Client sending this API KEY to Grok:", client.api_key)

# ==========================================================
# SAFE RESPONSE EXTRACTOR
# ==========================================================

def clean_response(resp):
    if not resp:
        return ""

    try:
        msg = resp.choices[0].message.content
        if not msg:
            return ""
        msg = msg.strip().lower()
        msg = msg.replace(".", "").replace("!", "").replace(",", "")

        # STEP 1: Debug output
        print("CLEANED RESULT:", msg)

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
            )
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
        allowed = ["sexual", "affectionate", "jealous", "rude", "neutral"]

        return result if result in allowed else "neutral"

    except Exception as e:
        print(f"❌ Error in grok_sentiment: {e}")
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
            )
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
        print(f"❌ Error in grok_is_sexual: {e}")
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
            )
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

        # ==========================================================
        # STEP 1: DEBUG — PRINT RAW GROK OUTPUT
        # ==========================================================
        print("\n================ GROK DEBUG ================")
        print("INPUT:", message)
        print("RAW RESPONSE OBJECT:", resp)
        print("===========================================\n")

        result = clean_response(resp)

        # Normalization
        if "explicit" in result:
            result = "explicit"
        elif "strong" in result:
            result = "strong"
        elif "flirt" in result:
            result = "flirty"

        # Sentiment override (NO internal import)
        sentiment = await grok_sentiment(message)
        if sentiment == "rude":
            return "none"

        allowed = ["explicit", "strong", "flirty", "none"]
        return result if result in allowed else "none"

    except Exception as e:
        print(f"❌ Error in grok_sexual_intensity: {e}")
        return "none"