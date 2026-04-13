#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_timing.py
Human-like timing engine for Telegram Funnel Bot.

Handles:
✔ Sleep schedule (1am–8am EST)
✔ Busy-hour delays (1pm–5pm)
✔ Emotional pacing (mood → timing speed)
✔ Funnel stage pacing
✔ Tier-based pace
✔ Long-haul timing behavior
✔ Random long pauses
✔ Daily reply limits (per-tier)
✔ next_reply_after scheduling
"""

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # << FIXED (no pytz)

from config import PRINT_DEBUG
from database import update_field


# ==========================================================
# TIMEZONE (correct version)
# ==========================================================

TZ = ZoneInfo("America/New_York")


def now_est():
    return datetime.now(TZ)


# ==========================================================
# SLEEP MODE
# ==========================================================

def is_sleep_hours(ts: datetime) -> bool:
    """
    No replies 1:00 AM → 8:00 AM EST.
    """
    return 1 <= ts.hour < 8


# ==========================================================
# BUSY HOURS (slower pace)
# ==========================================================

def is_busy_hours(ts: datetime) -> bool:
    """
    Busy IRL window: 1pm–5pm EST.
    """
    return 13 <= ts.hour < 17

def is_icebreaker_scenario(user: dict, logic: dict) -> bool:
    """
    Icebreaker Fast-Reply Override:
    Trigger a fast 2–8 second reply ONLY for early,
    low-intensity, low-information messages.

    NOTE: No content-based hardcoding, timing engine only
    evaluates structural message properties and funnel state.
    """

    stage = logic.get("funnel_stage", 0)
    intensity = logic.get("sexual_intensity", "none")

    # Prefer new field but gracefully fall back
    inbound_cnt = (
        logic.get("inbound_message_count")
        or logic.get("hp6_inbound_count")
        or 0
    )

    # Raw message (structural analysis only)
    msg = (logic.get("raw_message") or "").strip()

    # --------------------------------------------------
    # 1. Only early funnel (Stages 0–1)
    # --------------------------------------------------
    if stage > 1:
        return False

    # --------------------------------------------------
    # 2. Sexual intensity must NOT be high (GPT handles semantics)
    # --------------------------------------------------
    if intensity not in ("none", "flirty"):
        return False

    # --------------------------------------------------
    # 3. Only for first 3 inbound messages of day
    # --------------------------------------------------
    if inbound_cnt > 3:
        return False

    # --------------------------------------------------
    # 4. STRUCTURAL icebreaker identification:
    #    (no hardcoded greetings or emoji rules)
    # --------------------------------------------------

    # ― Very short messages = opener
    if len(msg) <= 8:
        return True

    # ― Messages with no spaces = opener (e.g., "Hey", "Hi", "Hola")
    if " " not in msg and len(msg) < 12:
        return True

    # ― Messages that contain *only non-alphanumeric characters*
    #    (emojis, symbols, punctuation) count as simple openers
    if msg and msg.replace(" ", "").isalnum() is False and msg.isascii() is False:
        return True

    return False


# ==========================================================
# RANDOM LONG PAUSE
# ==========================================================

def generate_long_pause():
    """
    Occasional long break: 10–25 minutes.
    """
    return random.randint(600, 1500)


def should_use_long_pause(user) -> bool:
    """
    ~5% chance per message, unless already used today.
    """
    used = user.get("long_pause_used") or False
    last = user.get("last_reply_date")
    today = now_est().date()

    # Reset if new day
    if last != today:
        return random.random() <= 0.05

    return (not used) and (random.random() <= 0.05)


# ==========================================================
# DAILY LIMITS PER TIER
# ==========================================================

def get_daily_limit(tier: str) -> int:
    # Tier A = high value markets
    if tier == "A":
        return random.randint(7, 10)

    # Tier B = medium value
    if tier == "B":
        return random.randint(3, 5)

    # Tier C = low value
        # RETURN INTENTIONALLY LEFT UNCHANGED
    if tier == "C":
        return 1

    # Tier D = one-reply-and-done (0 = no more replies after first)
    if tier == "D":
        return 0

    return 0


def has_reached_daily_limit(user) -> bool:
    """
    PINW2 UPDATE:
    • Stage 5 (assumed conversion) ALWAYS bypasses limits
    • Stage 6 (dormant user returned) ALWAYS bypasses limits

    Your old logic (fully disabled daily limits) is preserved BELOW this block.
    """

    stage = int(user.get("funnel_stage") or 0)

    # ⭐ PINW2 RULE: Stage 5 always gets replies
    if stage == 5:
        return False

    # ⭐ PINW2 RULE: Stage 6 always gets replies
    if stage == 6:
        return False

    # --------------------------------------------
    # Your existing version always returns False:
    # --------------------------------------------
    return False

    # BELOW WAS YOUR ORIGINAL (DISABLED) LIMIT LOGIC:
    #
    # today = now_est().date()
    # last = user.get("last_reply_date")
    # count = user.get("reply_count_today") or 0
    #
    # # Reset daily
    # if last != today:
    #     return False
    #
    # limit = get_daily_limit(user.get("country_tier"))
    # return count >= limit


# ==========================================================
# EMOTIONAL PACE MODIFIERS
# ==========================================================

def emotional_delay_modifier(emotional_state: dict) -> int:
    """
    Converts emotional mood → timing behavior.
    Returns extra seconds to ADD.
    """

    mood = emotional_state.get("mood", "warm")

    if mood == "intimate":
        return random.randint(10, 45)     # fast

    if mood == "teasing":
        return random.randint(20, 60)     # fast-medium

    if mood == "playful":
        return random.randint(30, 90)     # medium

    if mood == "warm":
        return random.randint(45, 120)    # slower baseline

    # fallback / distant mode
    return random.randint(60, 150)


# ==========================================================
# FUNNEL STAGE TIMING
# ==========================================================

def funnel_delay(stage: int) -> int:
    """
    Option A — Fast & Flirty Conversion Mode
    High-responsiveness pacing optimized for adult funnel engagement.
    """

    # Stage 0 — Cold opener
    if stage == 0:
        return random.randint(40, 90)

    # Stage 1 — Warm opener
    if stage == 1:
        return random.randint(30, 75)

    # Stage 2 — Hot user (fast replies)
    if stage == 2:
        return random.randint(8, 25)

    # Stage 3 — CTA build-up moment
    if stage == 3:
        return random.randint(5, 20)

    # Stage 4 — CTA clicked (slow slightly to feel natural)
    if stage == 4:
        return random.randint(60, 120)

    # Stage 5 — Converted (post-CTA nurturing)
    if stage == 5:
        return random.randint(300, 600)   # 5–10 min

    # Stage 6 — Dormant returning user
    if stage == 6:
        return random.randint(120, 360)   # 2–6 min

    # Fallback
    return random.randint(40, 120)


def hp13_delay(user, hp13_drip_mode: bool):
    """
    HP13 Timing Model:
    
    1st message  = immediate (handled in HP13 itself)
    2nd message  = 5–15 minutes
    3rd–5th      = 30–90 minutes
    6th–10th     = 2–6 hours
    11+          = 6–12 hours
    """

    count = user.get("hp13_inbound_count", 1)

    if count == 1:
        return 0

    if count == 2:
        return random.randint(5*60, 15*60)

    if 3 <= count <= 5:
        return random.randint(30*60, 90*60)

    if 6 <= count <= 10:
        return random.randint(2*3600, 6*3600)

    return random.randint(6*3600, 12*3600)


# ==========================================================
# MAIN: Compute Next Reply Time
# ==========================================================
async def compute_next_reply_time(user) -> datetime:
    """
    UPDATED FOR NEW ICEBREAKER/WARMUP SYSTEM:
    - Uses user["warmup"] from process_message_logic
    - Uses user["sexual_intensity"]
    - Uses user["heat_score"]
    """

    now = now_est()
    tid = user["telegram_id"]

    stage = user.get("funnel_stage", 0)
    intensity = user.get("sexual_intensity", "none")
    heat = user.get("heat_score", 0)
    warmup = user.get("warmup", False)
    emotional_state = user.get("emotional_state", {})

    # ------------------------------------------------------
    # ⭐ 1. NEW WARMUP FAST MODE (from logic['warmup'])
    # ------------------------------------------------------
    if warmup:
        delay = random.uniform(2, 8)
        return now + timedelta(seconds=delay)

    # ------------------------------------------------------
    # ⭐ 2. HOT LEAD OVERRIDE (strong/explicit)
    # ------------------------------------------------------
    if intensity in ("strong", "explicit"):
        return now + timedelta(seconds=random.uniform(4, 10))

    # ------------------------------------------------------
    # ⭐ 3. WARM LEAD OVERRIDE (heat ≥ 60)
    # ------------------------------------------------------
    if heat >= 60:
        return now + timedelta(seconds=random.uniform(8, 25))

    # ------------------------------------------------------
    # ⭐ 4. HP MODES (same)
    # ------------------------------------------------------
    if user.get("hp13_mode") or user.get("hp13_drip_mode"):
        delay = hp13_delay(user, user.get("hp13_drip_mode", False))
        return now + timedelta(seconds=delay)

    if user.get("hp16_drip_mode"):
        return now

    if user.get("hp6_active"):
        pref = user.get("hp6_preference", "standard")
        inbound = user.get("hp6_inbound_count", 0)

        if pref == "aggressive":
            base = random.randint(10, 40)
        elif pref == "soft":
            base = random.randint(180, 480)
        else:
            base = random.randint(90, 300)

        if inbound >= 5: base *= 1.3
        if inbound >= 10: base *= 1.6

        return now + timedelta(seconds=base)

    # ------------------------------------------------------
    # Sleep window (unchanged)
    # ------------------------------------------------------
    if is_sleep_hours(now):
        return now.replace(hour=8, minute=0, second=0, microsecond=0)

    # ------------------------------------------------------
    # Stage pacing (unchanged)
    # ------------------------------------------------------
    delay = funnel_delay(stage)
    delay += emotional_delay_modifier(emotional_state)

    # ghost return slowdown
    if user.get("returned_after_ghost"):
        delay += random.randint(90, 240)

    # morning boost
    if 8 <= now.hour < 11:
        delay *= 0.55

    # night slowdown
    if now.hour >= 23 or now.hour < 1:
        delay *= 1.25

    # busy-hours slowdown
    if is_busy_hours(now):
        delay += random.randint(120, 480)

    # random realism long pause
    if should_use_long_pause(user):
        longp = generate_long_pause()
        delay = max(delay, longp)
        await update_field(tid, "long_pause_used", True)

    next_ts = now + timedelta(seconds=int(delay))

    if PRINT_DEBUG:
        print(f"⏳ HP17 FINAL DELAY = {int(delay)}s → next reply @ {next_ts}")

    return next_ts


def warmup_delay(n: int) -> float:
    """
    First-5-messages warm-up timing.
    """
    if n <= 1:
        return random.uniform(2, 6)
    if n == 2:
        return random.uniform(3, 7)
    if n == 3:
        return random.uniform(4, 9)
    if n == 4:
        return random.uniform(5, 12)
    if n == 5:
        return random.uniform(8, 15)
    return None


# ==========================================================
# Should Reply Now?  (HP17 + Icebreaker + Hot User Override)
# ==========================================================

def should_reply_now(user) -> bool:
    """
    HP17 Timing Gate (UPDATED)
    - Warmup fast pass → immediate
    - Hot leads → immediate
    - Warm leads → immediate
    """

    now = now_est()

    stage = int(user.get("funnel_stage") or 0)
    intensity = user.get("sexual_intensity", "none")
    heat = user.get("heat_score", 0)
    inbound = user.get("inbound_message_count", 0)
    warmup = user.get("warmup", False)

    next_ts = user.get("next_reply_after")

    # ------------------------------------------------------
    # ⭐ 1. WARMUP MODE ALWAYS ALLOWS REPLY
    # ------------------------------------------------------
    if warmup:
        return True

    # ------------------------------------------------------
    # ⭐ 2. HOT LEAD OVERRIDE (explicit / strong)
    # ------------------------------------------------------
    if intensity in ("strong", "explicit"):
        return True

    # ------------------------------------------------------
    # ⭐ 3. WARM LEAD OVERRIDE (heat ≥ 60)
    # ------------------------------------------------------
    if heat >= 60:
        return True

    # ------------------------------------------------------
    # Stage 4–5 / HP6 / HP16 always reply
    # ------------------------------------------------------
    if stage in (4, 5):
        return True
    if user.get("hp6_active"):
        return True
    if user.get("hp16_drip_mode"):
        return True

    # ------------------------------------------------------
    # If no scheduled timestamp → reply
    # ------------------------------------------------------
    if not next_ts:
        return True

    # Normalize time
    if isinstance(next_ts, str):
        try:
            next_ts = datetime.fromisoformat(next_ts)
        except:
            return True

    if next_ts.tzinfo:
        next_ts = next_ts.replace(tzinfo=None)

    now_naive = now.replace(tzinfo=None)

    # ------------------------------------------------------
    # Hot stage-2 early window
    # ------------------------------------------------------
    if stage == 2 and now_naive + timedelta(seconds=10) >= next_ts:
        return True

    # long haul grace window
    if user.get("is_longhaul") and now_naive + timedelta(seconds=5) >= next_ts:
        return True

    return now_naive >= next_ts