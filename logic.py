#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_logic.py
Core intelligence layer for Telegram Funnel Bot.

Current cleanup:
- Removed old BASE_DOMAIN dependency
- Removed Fanvue tracking URL lookup
- CTA link builder now returns DMGate / Telegram entry URLs
- Removed duplicate imports and secret debug printing
- Grok config now comes from config.py
"""

import json
import random
from datetime import datetime, timedelta

from openai import AsyncOpenAI

from config import (
    PRINT_DEBUG,
    QA_MODE,
    GROK_API_KEY,
    GROK_MODEL,
    GROK_BASE_URL,
    DMGATE_URL_AMANDA,
    DMGATE_URL_AVA,
)
from database import (
    update_field,
    save_emotional_state,
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
# GROK CLIENT
# ==========================================================
grok_client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url=GROK_BASE_URL,
)


def extract_text(message_content):
    """
    Safely extracts text from Grok/OpenAI message.content whether it's:
    - a plain string
    - a list of content blocks
    """
    if isinstance(message_content, str):
        return message_content.strip()

    if isinstance(message_content, list) and len(message_content) > 0:
        block = message_content[0]
        if isinstance(block, dict):
            return block.get("text", "").strip()
        if hasattr(block, "text"):
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
            model=GROK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the user's message into exactly ONE word:\n"
                        "sexual, affectionate, jealous, rude, or neutral."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=5,
        )

        raw = extract_text(completion.choices[0].message.content).lower()
        allowed = ["sexual", "affectionate", "jealous", "rude", "neutral"]
        return raw if raw in allowed else "neutral"

    except Exception as e:
        if PRINT_DEBUG:
            print("❌ GROK SENTIMENT ERROR:", e)
        return "neutral"


# ==========================================================
# COUNTRY → TIER MAPPER
# ==========================================================
def determine_country_tier(country: str) -> str:
    if not country:
        return "C"

    country = country.upper()

    tier_a = {
        "US", "CA", "GB", "UK", "AU", "NZ",
        "DE", "FR", "NL", "SE", "NO", "CH",
    }

    tier_b = {
        "ES", "IT", "BE", "AT", "PL", "PT",
        "IE", "DK", "FI",
    }

    tier_c = {
        "BR", "MX", "AR", "PH", "TR", "RO",
        "ZA", "CL", "CO",
    }

    tier_d = {
        "IN", "PK", "BD", "EG", "NG", "ID", "IR",
    }

    if country in tier_a:
        return "A"
    if country in tier_b:
        return "B"
    if country in tier_c:
        return "C"
    if country in tier_d:
        return "D"
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
        except Exception:
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

    if sentiment == "affectionate":
        affection += 0.12 * tier_affection_scale
        desire += (0.10 * 0.4) * tier_desire_scale

    elif sentiment == "sexual":
        desire += (0.10 * 1.6) * tier_desire_scale
        affection += (0.12 * 0.4) * tier_affection_scale

    elif sentiment == "jealous":
        affection += (0.12 * 0.6) * tier_affection_scale

    elif sentiment == "neutral":
        affection += (0.12 * 0.25) * tier_affection_scale

    affection = clamp(affection, 0, 1)
    desire = clamp(desire, 0, 1)

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
    if sexual_intensity in ("strong", "explicit") or heat_score >= 70:
        return "hot", 2

    if sexual_intensity == "flirty" or heat_score >= 40:
        return "warm", 3

    return "neutral", 3


# ==========================================================
# SEXUAL MOMENTUM
# ==========================================================
def get_intensity_weight(intensity: str) -> int:
    return {
        "none": 0,
        "flirty": 10,
        "strong": 20,
        "explicit": 35,
    }.get(intensity, 0)


def get_momentum_gain(intensity: str) -> float:
    return {
        "none": 0.0,
        "flirty": 2.0,
        "strong": 4.0,
        "explicit": 7.0,
    }.get(intensity, 0.0)


def compute_sexual_momentum_change(user: dict, intensity: str) -> float:
    base_gain = get_momentum_gain(intensity)
    heat = user.get("heat_score", 0)
    heat_factor = (heat / 100) * 3.0
    return base_gain + heat_factor


async def apply_sexual_momentum_decay(user: dict) -> float:
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
    elif diff_minutes < 720:
        decay = 12.0
    else:
        decay = 100.0

    current = user.get("sexual_momentum", 0.0)
    return max(0.0, current - decay)


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
# SEXUAL INTENSITY → CTA THRESHOLD
# ==========================================================
async def increment_inbound_count(user: dict) -> int:
    telegram_id = user["telegram_id"]
    last_ts = user.get("inbound_last_ts")
    today = datetime.utcnow().date()

    if not last_ts or datetime.fromisoformat(last_ts).date() != today:
        await update_field(telegram_id, "inbound_message_count", 1)
        await update_field(telegram_id, "inbound_last_ts", datetime.utcnow().isoformat())
        return 1

    count = (user.get("inbound_message_count") or 0) + 1
    await update_field(telegram_id, "inbound_message_count", count)
    await update_field(telegram_id, "inbound_last_ts", datetime.utcnow().isoformat())
    return count


def get_threshold_for_intensity(intensity: str, tier: str) -> int | None:
    if tier == "D":
        return None

    if intensity == "explicit":
        base = 1
    elif intensity == "strong":
        base = 2
    elif intensity == "flirty":
        base = random.randint(4, 5)
    else:
        return None

    tier_multiplier = {
        "A": 0.6,
        "B": 0.8,
        "C": 1.0,
    }.get(tier, 1.0)

    threshold = round(base * tier_multiplier)
    return max(1, threshold)


# ==========================================================
# SHOULD TRIGGER CTA?
# ==========================================================
async def should_trigger_cta(user, sexual_intensity: str, text: str):
    telegram_id = user["telegram_id"]
    stage = int(user.get("funnel_stage") or 0)

    if stage in (4, 5):
        if PRINT_DEBUG:
            print("\n🚫 CTA BLOCKED — HP6 (Stage 4/5)\n")
        return False

    if await check_dead_mode(user):
        if PRINT_DEBUG:
            print("\n💀 CTA BLOCK — HP3 Dead Mode\n")
        return False

    if await is_cta_in_cooldown(user):
        if PRINT_DEBUG:
            print("\n🧊 CTA BLOCK — HP3 Cooldown\n")
        return False

    ignored = user.get("cta_ignored_count", 0)
    if ignored >= 3:
        if PRINT_DEBUG:
            print("\n💀 User ignored 3 CTAs → Dead Mode\n")
        await activate_dead_mode(telegram_id)
        return False

    threshold = get_threshold_for_intensity(
        sexual_intensity,
        user.get("country_tier", "C"),
    )

    if threshold is None:
        if PRINT_DEBUG:
            print("\n🚫 CTA DISABLED — intensity=none\n")
        return False

    counter_before = await get_sexual_trigger_count(telegram_id)
    counter_after = counter_before

    if sexual_intensity in ("flirty", "strong", "explicit"):
        await increment_sexual_trigger_count(telegram_id)
        counter_after = counter_before + 1

    if PRINT_DEBUG:
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(" 🔥 CTA INTENSITY CHECK (SYSTEM B)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Message Text       : {text}")
        print(f"Sexual Intensity   : {sexual_intensity.upper()}")
        print(f"Counter BEFORE     : {counter_before}")
        print(f"Counter AFTER      : {counter_after}")
        print(f"Threshold          : {threshold}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if counter_after >= threshold:
        if PRINT_DEBUG:
            print(" ✅ CTA FIRE — Threshold met")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

        await reset_sexual_trigger_count(telegram_id)
        await set_cta_cooldown(telegram_id, hours=6)
        return True

    if PRINT_DEBUG:
        print(" ❌ CTA NOT FIRED — below threshold")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    return False


def build_cta_link(telegram_id: int, persona: str) -> str:
    """
    Return the Telegram DM entry link for the given persona.
    No database lookup. No Fanvue tracking URL.
    """
    persona_key = (persona or "").strip().lower()

    if persona_key in ("amanda", "amandacayne", "amanda_cayne"):
        return DMGATE_URL_AMANDA

    if persona_key in ("ava", "avablackthorne", "ava_blackthorne"):
        return DMGATE_URL_AVA

    return DMGATE_URL_AMANDA


# ==========================================================
# HEAT SCORING ENGINE
# ==========================================================
def streak_bonus(user, text: str) -> int:
    last_ts = user.get("last_activity_ts")
    if not last_ts:
        return 0

    now = datetime.utcnow()
    diff = (now - last_ts).total_seconds()

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
    streak_pts: int,
) -> int:
    score = 0

    if intensity == "explicit":
        score += 40
    elif intensity == "strong":
        score += 25
    elif intensity == "flirty":
        score += 10

    if sentiment == "affectionate":
        score += 10
    elif sentiment == "jealous":
        score += 8
    elif sentiment == "rude":
        score -= 10

    desire = emotional_state.get("desire", 0)
    affection = emotional_state.get("affection", 0)

    score += int(desire * 15)
    score += int(affection * 10)

    mood = emotional_state.get("mood")
    if mood == "intimate":
        score += 12
    elif mood == "teasing":
        score += 8
    elif mood == "playful":
        score += 5

    if funnel_stage == 2:
        score += 10
    elif funnel_stage == 3:
        score += 20
    elif funnel_stage >= 4:
        score -= 20

    score += streak_pts
    return max(0, min(100, score))


def compute_timing_mode(
    sexual_intensity: str,
    heat_score: int,
    emotional_state: dict,
    funnel_stage: int,
    user: dict,
) -> tuple[str, str]:
    mood = emotional_state.get("mood", "warm")
    desire = emotional_state.get("desire", 0.0)

    if sexual_intensity in ("strong", "explicit"):
        return "fast", "sexual_intensity_high"

    if heat_score >= 70:
        return "fast", "heat_high"

    if mood == "intimate" or desire > 0.65:
        return "fast", "emotional_desire_high"

    hour = datetime.utcnow().hour
    if 8 <= hour < 11:
        if heat_score >= 40 or sexual_intensity in ("flirty", "strong"):
            return "fast", "morning_energy_boost"

    if heat_score <= 20 and sexual_intensity == "none":
        return "slow", "low_engagement"

    if mood == "warm" and desire < 0.25:
        return "slow", "low_desire"

    if hour >= 23 or hour < 1:
        if heat_score < 50:
            return "slow", "night_slowdown"

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
        if PRINT_DEBUG:
            print("❌ GROK SEXUAL INTENSITY ERROR:", e)
        return "none"


# ==========================================================
# MAIN ENTRY
# ==========================================================
async def process_message_logic(user: dict, text: str) -> dict:
    telegram_id = user["telegram_id"]
    stage = int(user.get("funnel_stage") or 0)

    inbound_count = await increment_inbound_count(user)

    if QA_MODE:
        if PRINT_DEBUG:
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

    sentiment = await grok_sentiment(text)
    sexual_intensity = await grok_sexual_intensity_debug(text)

    momentum_after_decay = await apply_sexual_momentum_decay(user)
    gain = compute_sexual_momentum_change(user, sexual_intensity)
    new_momentum = max(0.0, momentum_after_decay + gain)
    await update_momentum_in_db(user["telegram_id"], new_momentum)
    user["sexual_momentum"] = new_momentum

    if PRINT_DEBUG:
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(" 🔥 SEXUAL MOMENTUM ENGINE")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Momentum Before Decay: {momentum_after_decay}")
        print(f"Gain From Message    : {gain}")
        print(f"New Momentum         : {new_momentum}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    heat_for_profile = user.get("heat_score", 0)
    _ice_profile, max_ice_messages = classify_icebreaker_profile(sexual_intensity, heat_for_profile)

    # Keep existing behavior, but avoid double-incrementing inbound count.
    in_icebreaker = (stage <= 1) and (inbound_count <= max_ice_messages)

    await apply_emotional_shift(user, sentiment)
    emotional_state = await load_emotional_state(user)

    old_stage = stage
    new_stage = evolve_funnel_stage(user, sentiment) if old_stage < 4 else old_stage
    if new_stage != old_stage:
        await update_field(telegram_id, "funnel_stage", new_stage)

    should_cta = False

    momentum_threshold = 25
    if (
        new_momentum >= momentum_threshold
        and sexual_intensity in ("flirty", "strong", "explicit")
    ):
        if PRINT_DEBUG:
            print("\n🔥 MOMENTUM OVERRIDE — CTA FIRED\n")
        should_cta = True
    else:
        should_cta = await should_trigger_cta(user, sexual_intensity, text)

    streak_pts = streak_bonus(user, text)
    heat_score = calculate_heat_score(
        sentiment,
        sexual_intensity,
        emotional_state,
        new_stage,
        streak_pts,
    )
    await update_field(telegram_id, "heat_score", heat_score)

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