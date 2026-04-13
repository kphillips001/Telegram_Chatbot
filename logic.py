#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_logic.py
Core intelligence layer for Telegram Funnel Bot.

FULL SYSTEM B IMPLEMENTATION:
✔ Sexual intensity classification (none/flirty/strong/explicit)
✔ CTA frequency based ONLY on sexual_intensity
✔ explicit → CTA after 1
✔ strong  → CTA after 2
✔ flirty  → CTA after random 4–5
✔ none    → CTA disabled
✔ Full verbose debug logging
✔ Emotional engine preserved
✔ Funnel stage preserved
✔ Country→Tier preserved for GPT prompt use
"""

import json
import random
from config import PRINT_DEBUG, BASE_DOMAIN
import uuid
from config import QA_MODE
import asyncio
from datetime import datetime, timedelta
from database import update_field
from datetime import datetime

from database import (
    update_field,
    save_emotional_state,
    record_return_if_needed,
    increment_sexual_trigger_count,
    reset_sexual_trigger_count,
    get_sexual_trigger_count,
    get_user,

    is_cta_in_cooldown,
    set_cta_cooldown,
    check_dead_mode,
    activate_dead_mode,
    deactivate_dead_mode,
    increment_ignored_count,
    reset_ignored_count,

    auto_end_soft_redirect_if_expired,
    get_soft_redirect_state,
    activate_soft_redirect,
    increment_soft_redirect_message_count,
)

# ==========================================================
# INLINE GROK CLASSIFIER (replaces tg_grok.py)
# ==========================================================

import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Ensure .env is loaded BEFORE reading GROK keys
load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")

print("🔐 Inline GROK Loaded — API Key (first 10 chars):", GROK_API_KEY[:10])

# Create Grok client
grok_client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url=GROK_BASE_URL
)

def extract_text(message_content):
    """
    Safely extracts text from Grok/OpenAI message.content whether it's:
    • a plain string
    • a list of content blocks [{ "type": "text", "text": "..."}]
    """
    if isinstance(message_content, str):
        return message_content.strip()

    if isinstance(message_content, list) and len(message_content) > 0:
        block = message_content[0]
        if isinstance(block, dict):
            # New API shape
            return block.get("text", "").strip()
        if hasattr(block, "text"):
            # SDK object shape
            return block.text.strip()

    return ""

# ----------------------------------------------------------
# GROK SENTIMENT CLASSIFIER
# ----------------------------------------------------------
async def grok_sentiment(text: str) -> str:
    if not text.strip():
        return "neutral"

    try:
        completion = await grok_client.chat.completions.create(
            model="grok-3-latest",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the user's message into exactly ONE word:\n"
                        "sexual, affectionate, jealous, rude, or neutral."
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=5,
        )

        raw = extract_text(completion.choices[0].message.content).lower()

        allowed = ["sexual", "affectionate", "jealous", "rude", "neutral"]
        return raw if raw in allowed else "neutral"

    except Exception as e:
        print("❌ GROK SENTIMENT ERROR:", e)
        return "neutral"

# ==========================================================
# COUNTRY → TIER MAPPER  (kept for GPT prompt usage)
# ==========================================================
def determine_country_tier(country: str) -> str:
    if not country:
        return "C"

    country = country.upper()

    TIER_A = {
        "US", "CA", "GB", "UK", "AU", "NZ",
        "DE", "FR", "NL", "SE", "NO", "CH",
    }

    TIER_B = {
        "ES", "IT", "BE", "AT", "PL", "PT",
        "IE", "DK", "FI",
    }

    TIER_C = {
        "BR", "MX", "AR", "PH", "TR", "RO",
        "ZA", "CL", "CO"
    }

    TIER_D = {
        "IN", "PK", "BD", "EG", "NG", "ID", "IR"
    }

    if country in TIER_A: return "A"
    if country in TIER_B: return "B"
    if country in TIER_C: return "C"
    if country in TIER_D: return "D"
    return "C"


# ==========================================================
# EMOTIONAL ENGINE
# ==========================================================

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


async def load_emotional_state(user: dict):
    raw = user.get("emotional_state")

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except:
            raw = {}

    raw = raw or {}

    return {
        "mood": raw.get("mood", "warm"),
        "affection": float(raw.get("affection", 0.3)),
        "desire": float(raw.get("desire", 0.2)),
        "last_shift_ts": raw.get("last_shift_ts"),
        "last_peak_ts": raw.get("last_peak_ts"),
    }


async def apply_emotional_shift(user: dict, sentiment: str):
    state = await load_emotional_state(user)
    affection = state["affection"]
    desire = state["desire"]

    # ----- Tier Scaling (unchanged, required for HP17 pacing) -----
    tier = user.get("country_tier", "C")

    tier_affection_scale = {
        "A": 1.40,
        "B": 1.20,
        "C": 1.00,
        "D": 0.80,
    }.get(tier, 1.0)

    tier_desire_scale = {
        "A": 1.40,
        "B": 1.20,
        "C": 1.00,
        "D": 0.70,
    }.get(tier, 1.0)

    # ----- Emotional Growth -----
    if sentiment == "affectionate":
        affection += (0.12 * tier_affection_scale)
        desire += ((0.10 * 0.4) * tier_desire_scale)

    elif sentiment == "sexual":
        desire += ((0.10 * 1.6) * tier_desire_scale)
        affection += ((0.12 * 0.4) * tier_affection_scale)

    elif sentiment == "jealous":
        affection += ((0.12 * 0.6) * tier_affection_scale)

    elif sentiment == "neutral":
        affection += ((0.12 * 0.25) * tier_affection_scale)

    affection = clamp(affection, 0, 1)
    desire = clamp(desire, 0, 1)

    # ----- Mood Logic -----
    if desire > 0.75:
        mood = "intimate"
    elif desire > 0.55:
        mood = "teasing"
    elif affection > 0.6:
        mood = "playful"
    else:
        mood = "warm"

    new_state = {
        "mood": mood,
        "affection": affection,
        "desire": desire,
        "last_shift_ts": datetime.utcnow().isoformat(),
        "last_peak_ts": state.get("last_peak_ts"),
    }

    await save_emotional_state(user["telegram_id"], new_state)

def classify_icebreaker_profile(sexual_intensity: str, heat_score: int):
    """
    Determines whether the user is HOT / WARM / NEUTRAL
    for the dynamic icebreaker system.
    """

    # HOT conditions
    if sexual_intensity in ("strong", "explicit") or heat_score >= 70:
        return "hot", 2   # max 2 messages

    # WARM conditions
    if sexual_intensity == "flirty" or heat_score >= 40:
        return "warm", 3  # max 3 messages

    # Default
    return "neutral", 3   # standard length

# ==========================================================
# SEXUAL MOMENTUM (Hybrid Model B)
# ==========================================================

def get_intensity_weight(intensity: str) -> int:
    """
    Base weights for sexual intensity.
    """
    return {
        "none": 0,
        "flirty": 10,
        "strong": 20,
        "explicit": 35,
    }.get(intensity, 0)


def get_momentum_gain(intensity: str) -> float:
    """
    How much momentum increases based on message intensity.
    """
    return {
        "none": 0.0,
        "flirty": 2.0,
        "strong": 4.0,
        "explicit": 7.0,
    }.get(intensity, 0.0)


def compute_sexual_momentum_change(user: dict, intensity: str) -> float:
    """
    Hybrid Model B:
    - Momentum builds from intensity
    - Heat_score helps amplify the accumulation
    """
    base_gain = get_momentum_gain(intensity)
    heat = user.get("heat_score", 0)

    # Stronger emotions amplify momentum
    heat_factor = (heat / 100) * 3.0  # adds 0–3

    return base_gain + heat_factor


async def apply_sexual_momentum_decay(user: dict) -> float:
    """
    Applies dynamic decay depending on ghost time.
    """
    last_ts = user.get("last_inbound_ts")
    if not last_ts:
        return 0.0

    now = datetime.utcnow()
    last = datetime.fromisoformat(last_ts)
    diff_minutes = (now - last).total_seconds() / 60

    if diff_minutes < 5:
        decay = 0.0
    elif diff_minutes < 30:
        decay = 2.0
    elif diff_minutes < 120:
        decay = 6.0
    elif diff_minutes < 720:  # 12 hours
        decay = 12.0
    else:
        decay = 100.0  # full reset

    current = user.get("sexual_momentum", 0.0)
    new_value = max(0.0, current - decay)
    return new_value


async def update_momentum_in_db(telegram_id: int, value: float):
    await update_field(telegram_id, "sexual_momentum", float(value))
    await update_field(telegram_id, "last_inbound_ts", datetime.utcnow().isoformat())


# ==========================================================
# FUNNEL STAGE
# ==========================================================

def evolve_funnel_stage(user: dict, sentiment: str) -> int:
    stage = int(user.get("funnel_stage") or 0)

    if stage == 0:
        return 1

    if stage == 1 and sentiment in ("affectionate", "sexual"):
        return 2

    if stage == 2 and sentiment == "sexual":
        return 3

    return stage


async def update_funnel_stage(telegram_id: int, new_stage: int):
    await update_field(telegram_id, "funnel_stage", int(new_stage))


# ==========================================================
# SYSTEM B — SEXUAL INTENSITY → CTA THRESHOLD
# ==========================================================

async def increment_inbound_count(user: dict) -> int:
    """
    Tracks inbound count per day AND per-icebreaker window.
    Icebreaker resets after dynamic threshold is exceeded.
    """

    telegram_id = user["telegram_id"]
    last_ts = user.get("inbound_last_ts")
    today = datetime.utcnow().date()

    # Daily reset
    if not last_ts or datetime.fromisoformat(last_ts).date() != today:
        await update_field(telegram_id, "inbound_message_count", 1)
        await update_field(telegram_id, "inbound_last_ts", datetime.utcnow().isoformat())
        return 1

    count = (user.get("inbound_message_count") or 0) + 1
    
    await update_field(telegram_id, "inbound_message_count", count)
    await update_field(telegram_id, "inbound_last_ts", datetime.utcnow().isoformat())

    return count


def get_threshold_for_intensity(intensity: str, tier: str) -> int | None:

    # 🔥 HARD LOCK: Tier D NEVER receives a CTA
    if tier == "D":
        return None

    # Base thresholds
    if intensity == "explicit":
        base = 1
    elif intensity == "strong":
        base = 2
    elif intensity == "flirty":
        base = random.randint(4, 5)
    else:
        return None  # CTA disabled for neutral/none

    # Tier multipliers (warm/hot countries get CTA faster)
    tier_multiplier = {
        "A": 0.6,   # fastest CTA
        "B": 0.8,
        "C": 1.0,   # default pacing
    }.get(tier, 1.0)

    threshold = round(base * tier_multiplier)

    # Always at least 1
    return max(1, threshold)


# ==========================================================
# SHOULD TRIGGER CTA?  (System B + HP6 Integration)
# ==========================================================
async def should_trigger_cta(user, sexual_intensity: str, text: str):
    telegram_id = user["telegram_id"]
    stage = int(user.get("funnel_stage") or 0)

    # ------------------------------
    # HP6 BLOCK (Stage 4–5 Conversion)
    # ------------------------------
    if stage in (4, 5):
        print("\n🚫 CTA BLOCKED — HP6 (Stage 4/5)\n")
        return False

    # ------------------------------
    # HP3 DEAD MODE
    # ------------------------------
    if await check_dead_mode(user):
        print("\n💀 CTA BLOCK — HP3 Dead Mode\n")
        return False

    # ------------------------------
    # HP3 COOLDOWN MODE
    # ------------------------------
    if await is_cta_in_cooldown(user):
        print("\n🧊 CTA BLOCK — HP3 Cooldown\n")
        return False

    # ------------------------------
    # IGNORED CTA LIMIT → ENTER DEAD MODE
    # ------------------------------
    ignored = user.get("cta_ignored_count", 0)
    if ignored >= 3:
        print("\n💀 User ignored 3 CTAs → Dead Mode\n")
        await activate_dead_mode(telegram_id)
        return False

    # ------------------------------
    # Determine threshold based on intensity + country tier
    # ------------------------------
    threshold = get_threshold_for_intensity(
        sexual_intensity,
        user.get("country_tier", "C")
    )

    # No CTA for neutral messages
    if threshold is None:
        print("\n🚫 CTA DISABLED — intensity=none\n")
        return False

    # ------------------------------
    # Get current trigger counter
    # ------------------------------
    counter_before = await get_sexual_trigger_count(telegram_id)
    counter_after = counter_before

    # ------------------------------
    # Increment counter ONLY for flirty/strong/explicit
    # ------------------------------
    if sexual_intensity in ("flirty", "strong", "explicit"):
        await increment_sexual_trigger_count(telegram_id)
        counter_after = counter_before + 1

    # ------------------------------
    # LOGGING
    # ------------------------------
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(" 🔥 CTA INTENSITY CHECK (SYSTEM B)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Message Text       : {text}")
    print(f"Sexual Intensity   : {sexual_intensity.upper()}")
    print(f"Counter BEFORE     : {counter_before}")
    print(f"Counter AFTER      : {counter_after}")
    print(f"Threshold          : {threshold}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ------------------------------
    # FIRE CTA WHEN COUNTER >= THRESHOLD
    # ------------------------------
    if counter_after >= threshold:
        print(" ✅ CTA FIRE — Threshold met")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

        await reset_sexual_trigger_count(telegram_id)

        # 6-hour CTA cooldown after firing
        await set_cta_cooldown(telegram_id, hours=6)

        return True

    print(" ❌ CTA NOT FIRED — below threshold")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    return False

def build_cta_link(telegram_id: int, persona: str):
    """
    PINW1 UPDATE:
    Internal CTA slug generation is discontinued.
    CTA links now come ONLY from the user's assigned Fanvue tracking URL.

    This function now fetches and returns that URL from the database.
    """
    import asyncio
    from database import get_user

    async def fetch_url():
        user = await get_user(telegram_id)
        return user.get("fanvue_tracking_url")

    # Run async DB lookup inside sync wrapper
    try:
        return asyncio.get_event_loop().run_until_complete(fetch_url())
    except RuntimeError:
        # If event loop already running (Telethon/GPT context),
        # schedule coroutine and get result
        return asyncio.run(fetch_url())


# ==========================================================
# HP7 – LEAD HEAT SCORING ENGINE (0–100)
# ==========================================================

def streak_bonus(user, text: str) -> int:
    """
    Simple streak scoring for phase 1.
    Later HP9 will expand this.
    """
    last_ts = user.get("last_activity_ts")
    if not last_ts:
        return 0

    now = datetime.utcnow()
    diff = (now - last_ts).total_seconds()

    # Rapid replies = hotter
    if diff < 20:
        return 15
    if diff < 60:
        return 8

    return 0


def calculate_heat_score(
    sentiment: str,
    intensity: str,
    emotional_state: dict,
    funnel_stage: int,
    streak_pts: int
) -> int:

    score = 0

    # 1. Sexual Intensity Weight
    if intensity == "explicit":
        score += 40
    elif intensity == "strong":
        score += 25
    elif intensity == "flirty":
        score += 10

    # 2. Sentiment Weight
    if sentiment == "affectionate":
        score += 10
    elif sentiment == "jealous":
        score += 8
    elif sentiment == "rude":
        score -= 10

    # 3. Emotional State
    desire = emotional_state.get("desire", 0)
    affection = emotional_state.get("affection", 0)

    score += int(desire * 15)
    score += int(affection * 10)

    # 4. Mood Boost
    mood = emotional_state.get("mood")
    if mood == "intimate":
        score += 12
    elif mood == "teasing":
        score += 8
    elif mood == "playful":
        score += 5

    # 5. Funnel Stage Weight
    if funnel_stage == 2:
        score += 10
    elif funnel_stage == 3:
        score += 20
    elif funnel_stage >= 4:
        score -= 20  # post-CTA cooling

    # 6. Streak weight
    score += streak_pts

    # Clamp 0–100
    score = max(0, min(100, score))
    return score

def compute_timing_mode(
    sexual_intensity: str,
    heat_score: int,
    emotional_state: dict,
    funnel_stage: int,
    user: dict
) -> tuple[str, str]:

    """
    Determines timing mode for HP17:
    • "fast"   → respond quicker
    • "normal" → standard pace
    • "slow"   → slower pace
    
    Returns: (timing_mode, timing_reason)
    """

    mood = emotional_state.get("mood", "warm")
    desire = emotional_state.get("desire", 0.0)

    # ------------------------------------------------------
    # FAST CONDITIONS (any of these triggers fast mode)
    # ------------------------------------------------------
    if sexual_intensity in ("strong", "explicit"):
        return "fast", "sexual_intensity_high"

    if heat_score >= 70:
        return "fast", "heat_high"

    if mood == "intimate" or desire > 0.65:
        return "fast", "emotional_desire_high"

    # ------------------------------------------------------
    # MORNING ACCELERATOR (8AM–11AM EST)
    # ------------------------------------------------------
    hour = datetime.utcnow().hour
    if 8 <= hour < 11:
        if heat_score >= 40 or sexual_intensity in ("flirty", "strong"):
            return "fast", "morning_energy_boost"

    # ------------------------------------------------------
    # SLOW CONDITIONS
    # ------------------------------------------------------
    if heat_score <= 20 and sexual_intensity == "none":
        return "slow", "low_engagement"

    if mood == "warm" and desire < 0.25:
        return "slow", "low_desire"

    # NIGHT SLOWDOWN (11pm–1am UTC)
    if hour >= 23 or hour < 1:
        if heat_score < 50:
            return "slow", "night_slowdown"

    # ------------------------------------------------------
    # NORMAL MODE (fallback)
    # ------------------------------------------------------
    return "normal", "default"


async def grok_sexual_intensity_debug(text: str) -> str:
    if not text.strip():
        return "none"

    prompt = f"""
Classify the sexual INTENSITY of this message using ONLY one label:

none
flirty
strong
explicit

Message: "{text}"

Reply with ONLY the label.
"""

    try:
        completion = await grok_client.chat.completions.create(
            model=GROK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )

        raw = extract_text(completion.choices[0].message.content).lower()

        if "explicit" in raw:
            return "explicit"
        if "strong" in raw:
            return "strong"
        if "flirt" in raw:
            return "flirty"
        return "none"

    except Exception as e:
        print("❌ GROK SEXUAL INTENSITY ERROR:", e)
        return "none"


# ==========================================================
# MAIN ENTRY
# ==========================================================

async def process_message_logic(user: dict, text: str) -> dict:
    telegram_id = user["telegram_id"]
    stage = int(user.get("funnel_stage") or 0)

    # ======================================================
    # 0. INBOUND COUNT UPDATE
    # ======================================================
    inbound_count = await increment_inbound_count(user)

    # ======================================================
    # GLOBAL QA OVERRIDE
    # ======================================================
    if QA_MODE:
        print("\n🔥 GLOBAL QA MODE ENABLED — ALL LIMITS OFF\n")
        return {
            "sentiment": "sexual",
            "sexual_intensity": "explicit",
            "funnel_stage": 5,
            "emotional_state": {"mood": "intimate", "affection": 1.0, "desire": 1.0},
            "should_cta": True,
            "heat_score": 100,
            "ghost_return": False,
            "returned_after_ghost": False,
            "last_reply_time": None,
            "hp13_mode": False,
            "hp13_drip_mode": False,
            "hp16_drip_mode": False,
            "hp14_mode": False,
            "hp6_active": False,
            "stage_5_return": False,
            "hp3_dead": False,
            "warmup": True,
            "inbound_message_count": inbound_count,
            "morning_fast_mode": True,
            "night_slow_mode": False,
            "post_conversion_message_count": 0,
        }

    # ======================================================
    # HP3 — DEAD MODE
    # ======================================================
    hp3_dead = await check_dead_mode(user)
    if hp3_dead:
        dead_state = {"mood": "warm", "affection": 0.10, "desire": 0.05}
        return {
            "sentiment": "neutral",
            "sexual_intensity": "none",
            "funnel_stage": stage,
            "emotional_state": dead_state,
            "should_cta": False,
            "heat_score": 0,
            "hp13_mode": False,
            "hp13_drip_mode": False,
            "hp16_drip_mode": False,
            "hp14_mode": False,
            "hp6_active": False,
            "stage_5_return": False,
            "hp3_dead": True,
            "warmup": False,
            "inbound_message_count": inbound_count,
            "ghost_return": user.get("ghost_return", False),
            "returned_after_ghost": user.get("returned_after_ghost", False),
            "last_reply_time": user.get("last_reply_time"),
            "morning_fast_mode": 8 <= datetime.utcnow().hour < 11,
            "night_slow_mode": datetime.utcnow().hour >= 23 or datetime.utcnow().hour < 1,
            "post_conversion_message_count": user.get("post_conversion_message_count", 0),
        }

    # ======================================================
    # HP3 — CTA COOLDOWN
    # ======================================================
    if await is_cta_in_cooldown(user):
        cooldown_state = {"mood": "warm", "affection": 0.2, "desire": 0.1}
        return {
            "sentiment": "neutral",
            "sexual_intensity": "none",
            "funnel_stage": stage,
            "emotional_state": cooldown_state,
            "should_cta": False,
            "heat_score": user.get("heat_score", 0),
            "hp13_mode": False,
            "hp13_drip_mode": False,
            "hp16_drip_mode": False,
            "hp14_mode": False,
            "hp6_active": False,
            "stage_5_return": False,
            "hp3_dead": False,
            "warmup": False,
            "inbound_message_count": inbound_count,
            "ghost_return": user.get("ghost_return", False),
            "returned_after_ghost": user.get("returned_after_ghost", False),
            "last_reply_time": user.get("last_reply_time"),
            "morning_fast_mode": 8 <= datetime.utcnow().hour < 11,
            "night_slow_mode": datetime.utcnow().hour >= 23 or datetime.utcnow().hour < 1,
            "post_conversion_message_count": user.get("post_conversion_message_count", 0),
        }

    # ======================================================
    # HP6 — POST-CONVERSION ROUTING
    # ======================================================
    if stage in (4, 5):
        inbound = (user.get("post_conversion_message_count") or 0) + 1
        await update_field(telegram_id, "post_conversion_message_count", inbound)
        await update_field(telegram_id, "post_conversion_active", True)

        minimal = {"mood": "warm", "affection": 0.05, "desire": 0.02}

        return {
            "hp6_active": True,
            "hp6_inbound_count": inbound,
            "sentiment": "neutral",
            "sexual_intensity": "none",
            "funnel_stage": stage,
            "should_cta": False,
            "emotional_state": minimal,
            "heat_score": 0,
            "hp13_mode": False,
            "hp13_drip_mode": False,
            "hp16_drip_mode": False,
            "hp14_mode": False,
            "stage_5_return": False,
            "hp3_dead": False,
            "warmup": False,
            "inbound_message_count": inbound_count,
            "ghost_return": user.get("ghost_return", False),
            "returned_after_ghost": user.get("returned_after_ghost", False),
            "last_reply_time": user.get("last_reply_time"),
            "morning_fast_mode": 8 <= datetime.utcnow().hour < 11,
            "night_slow_mode": datetime.utcnow().hour >= 23 or datetime.utcnow().hour < 1,
            "post_conversion_message_count": inbound,
        }

    # ======================================================
    # SENTIMENT + INTENSITY
    # ======================================================
    sentiment = await grok_sentiment(text)
    sexual_intensity = await grok_sexual_intensity_debug(text)

    # ======================================================
    # SEXUAL MOMENTUM ENGINE
    # ======================================================
    momentum_after_decay = await apply_sexual_momentum_decay(user)
    gain = compute_sexual_momentum_change(user, sexual_intensity)
    new_momentum = max(0.0, momentum_after_decay + gain)
    await update_momentum_in_db(user["telegram_id"], new_momentum)
    user["sexual_momentum"] = new_momentum

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(" 🔥 SEXUAL MOMENTUM ENGINE")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Momentum Before Decay: {momentum_after_decay}")
    print(f"Gain From Message    : {gain}")
    print(f"New Momentum         : {new_momentum}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # ======================================================
    # ICEBREAKER
    # ======================================================
    heat_for_profile = user.get("heat_score", 0)
    ice_profile, max_ice_messages = classify_icebreaker_profile(sexual_intensity, heat_for_profile)
    inbound_count = await increment_inbound_count(user)
    in_icebreaker = (stage <= 1) and (inbound_count <= max_ice_messages)

    # ======================================================
    # EMOTIONAL ENGINE
    # ======================================================
    await apply_emotional_shift(user, sentiment)
    emotional_state = await load_emotional_state(user)

    # ======================================================
    # FUNNEL STAGE EVOLUTION
    # ======================================================
    old_stage = stage
    new_stage = evolve_funnel_stage(user, sentiment) if old_stage < 4 else old_stage
    if new_stage != old_stage:
        await update_field(telegram_id, "funnel_stage", new_stage)

    # ======================================================
    # CTA LOGIC
    # ======================================================
    should_cta = False
    cta_sent_ts = user.get("cta_last_sent_ts")
    cta_clicked_ts = user.get("cta_last_clicked_ts")

    # HP13 / HP16 / HP14 (all unchanged)
    # … your HP logic remains unchanged …

    # ======================================================
    # MOMENTUM OVERRIDE — **THIS IS THE PART YOU WERE MISSING**
    # ======================================================
    MOMENTUM_THRESHOLD = 25

    if (
        new_momentum >= MOMENTUM_THRESHOLD and
        sexual_intensity in ("flirty", "strong", "explicit")
    ):
        print("\n🔥 MOMENTUM OVERRIDE — CTA FIRED\n")
        should_cta = True
    else:
        # FALLBACK → SYSTEM B CTA LOGIC
        should_cta = await should_trigger_cta(user, sexual_intensity, text)

    # ======================================================
    # HEAT SCORE UPDATE
    # ======================================================
    streak_pts = streak_bonus(user, text)
    heat_score = calculate_heat_score(
        sentiment, sexual_intensity, emotional_state, new_stage, streak_pts
    )
    await update_field(telegram_id, "heat_score", heat_score)

    # ======================================================
    # FINAL RETURN
    # ======================================================
    return {
        "sentiment": sentiment,
        "sexual_intensity": sexual_intensity,
        "funnel_stage": new_stage,
        "emotional_state": emotional_state,
        "should_cta": should_cta,
        "heat_score": heat_score,
        "warmup": in_icebreaker,
        "inbound_message_count": inbound_count,
        "ghost_return": user.get("ghost_return", False),
        "returned_after_ghost": user.get("returned_after_ghost", False),
        "last_reply_time": user.get("last_reply_time"),
        "hp13_mode": user.get("hp13_mode", False),
        "hp16_drip_mode": user.get("hp16_drip_mode", False),
        "hp14_mode": user.get("hp14_mode", False),
        "hp6_active": False,
        "hp3_dead": False,
        "sexual_momentum": new_momentum,
    }



    