#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_database.py
Async Postgres integration for Telegram Funnel Bot.
Rewritten to use psycopg3 async instead of asyncpg.

Current cleanup:
- Removed Fanvue tracking assignment logic
- Preserved general user, message, event, timing, CTA, and state helpers
"""

import json
from datetime import datetime, date, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from psycopg.types.json import Jsonb

from config import (
    TG_DB_HOST,
    TG_DB_NAME,
    TG_DB_USER,
    TG_DB_PASSWORD,
    TG_DB_PORT,
    PRINT_DEBUG,
)


# =============================================================
# INIT CONNECTION POOL
# =============================================================
_pool: AsyncConnectionPool | None = None


async def init_pool():
    global _pool

    if PRINT_DEBUG:
        print("🔌 Initializing psycopg3 async pool...")

    _pool = AsyncConnectionPool(
        conninfo=(
            f"host={TG_DB_HOST} "
            f"port={TG_DB_PORT} "
            f"dbname={TG_DB_NAME} "
            f"user={TG_DB_USER} "
            f"password={TG_DB_PASSWORD}"
        ),
        open=True,
        max_size=10,
        kwargs={"row_factory": dict_row},
    )

    if PRINT_DEBUG:
        print("✅ psycopg3 async pool ready.")


# =============================================================
# EXEC HELPERS
# =============================================================
async def fetchrow(query: str, *args):
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchone()


async def fetch(query: str, *args):
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchall()


async def execute(query: str, *args):
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return cur.rowcount


# =============================================================
# SMART FIELD UPDATE (AUTO JSONB SUPPORT)
# =============================================================
async def update_field(telegram_id: int, field: str, value):
    col = await fetchrow(
        """
        SELECT data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = %s
        """,
        field,
    )

    if not col:
        raise ValueError(f"Unknown column: {field}")

    data_type = col["data_type"]
    udt = col["udt_name"]
    is_jsonb = data_type == "jsonb" or udt == "jsonb"

    if is_jsonb:
        if not isinstance(value, dict):
            raise TypeError(f"Column '{field}' is jsonb but value is not dict.")
        value = Jsonb(value)
        cast = "::jsonb"
    else:
        if isinstance(value, dict):
            raise TypeError(f"Column '{field}' is {data_type}/{udt}, but value is dict.")
        cast = ""

    sql = f"""
        UPDATE users
        SET {field} = %s{cast},
            updated_at = NOW()
        WHERE telegram_id = %s
    """

    await execute(sql, value, telegram_id)


# =============================================================
# USER CRUD
# =============================================================
async def get_user(telegram_id: int):
    """Fetch a single user row by Telegram ID."""
    return await fetchrow(
        "SELECT * FROM users WHERE telegram_id = %s",
        telegram_id,
    )


async def load_or_create_user(update):
    """Create a new DB user or load an existing one."""
    tg_user = update.effective_user

    telegram_id = tg_user.id
    username = tg_user.username or ""
    first = tg_user.first_name or ""
    last = tg_user.last_name or ""

    row = await get_user(telegram_id)
    if row:
        return row

    lang = (tg_user.language_code or "").upper()
    country = ""

    if "-" in lang:
        country = lang.split("-")[1]
    elif len(lang) == 2:
        country = lang

    await execute(
        """
        INSERT INTO users (telegram_id, username, first_name, last_name, country)
        VALUES (%s, %s, %s, %s, %s)
        """,
        telegram_id,
        username,
        first,
        last,
        country,
    )

    if PRINT_DEBUG:
        print(f"🆕 New user created: {telegram_id}")

    return await get_user(telegram_id)


# =============================================================
# SEXUAL TRIGGER COUNTER
# =============================================================
async def increment_sexual_trigger_count(telegram_id: int):
    """Increase sexual_trigger_count by 1."""
    await execute(
        """
        UPDATE users
        SET sexual_trigger_count = COALESCE(sexual_trigger_count, 0) + 1,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def reset_sexual_trigger_count(telegram_id: int):
    """Reset the sexual trigger counter to zero."""
    await execute(
        """
        UPDATE users
        SET sexual_trigger_count = 0,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def get_sexual_trigger_count(telegram_id: int) -> int:
    """Return current sexual trigger count."""
    row = await fetchrow(
        "SELECT sexual_trigger_count FROM users WHERE telegram_id = %s",
        telegram_id,
    )
    if not row:
        return 0
    return row.get("sexual_trigger_count", 0)


# =============================================================
# ACTIVITY & DAILY COUNTERS
# =============================================================
async def touch_user_activity(telegram_id: int):
    row = await get_user(telegram_id)
    today = date.today()

    last_date = row.get("last_reply_date")
    if last_date != today:
        await execute(
            """
            UPDATE users
            SET last_reply_date = %s,
                reply_count_today = 0,
                long_pause_used = FALSE,
                updated_at = NOW(),
                next_reply_after = NULL
            WHERE telegram_id = %s
            """,
            today,
            telegram_id,
        )

    await execute(
        """
        UPDATE users
        SET last_activity_ts = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


# =============================================================
# TIMING ENGINE SUPPORT
# =============================================================
async def update_next_reply_after(telegram_id: int, ts):
    """
    Stores the next timestamp when the bot is allowed to reply.
    Accepts both datetime objects and ISO strings.
    """
    if isinstance(ts, datetime):
        ts = ts.isoformat()

    await update_field(telegram_id, "next_reply_after", ts)


async def update_last_reply_time(telegram_id: int, ts=None):
    """
    Tracks the timestamp of the bot's last outbound reply.
    Used for streak scoring, ghost-return detection, and timing cadence.
    """
    if ts is None:
        ts = datetime.utcnow()

    await update_field(telegram_id, "last_reply_time", ts.isoformat())


# =============================================================
# MESSAGE LOGGING
# =============================================================
async def log_message(telegram_id: int, direction: str, text: str, bot_name: str):
    await execute(
        """
        INSERT INTO messages (telegram_id, direction, text, ts, bot_name)
        VALUES (%s, %s, %s, NOW(), %s)
        """,
        telegram_id,
        direction,
        text,
        bot_name,
    )

    if direction == "outbound":
        await execute(
            """
            UPDATE users
            SET reply_count_today = COALESCE(reply_count_today, 0) + 1,
                last_reply_date = CURRENT_DATE,
                updated_at = NOW()
            WHERE telegram_id = %s
            """,
            telegram_id,
        )


# =============================================================
# EVENT LOGGING
# =============================================================
async def log_event(telegram_id: int, event_type: str):
    await execute(
        """
        INSERT INTO events (telegram_id, event_type, ts)
        VALUES (%s, %s, NOW())
        """,
        telegram_id,
        event_type,
    )


# =============================================================
# EMOTIONAL STATE
# =============================================================
async def save_emotional_state(telegram_id: int, emotional_state: dict):
    safe = json.loads(json.dumps(emotional_state, default=str))
    await update_field(telegram_id, "emotional_state", safe)


# =============================================================
# FUNNEL STAGE
# =============================================================
async def update_funnel_stage(telegram_id: int, stage: int):
    await update_field(telegram_id, "funnel_stage", stage)


# =============================================================
# LONG-HAUL SUPPORT
# =============================================================
async def mark_longhaul_user(telegram_id: int):
    await execute(
        """
        UPDATE users
        SET is_longhaul = TRUE,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def clear_longhaul_if_active(telegram_id: int):
    await execute(
        """
        UPDATE users
        SET is_longhaul = FALSE,
            updated_at = NOW()
        WHERE telegram_id = %s AND is_longhaul = TRUE
        """,
        telegram_id,
    )


# =============================================================
# RETURN DETECTION
# =============================================================
async def record_return_if_needed(user: dict):
    """
    Ghost-return detection:
    - If user has been inactive ≥ 48 hours:
        • mark returned_after_ghost = TRUE
        • mark ghost_return = TRUE
        • force long_pause_used = TRUE
        • log return event
    - If already marked on a previous message, no double-marking.
    """
    telegram_id = user["telegram_id"]

    last = user.get("last_activity_ts")
    if not last:
        return

    if isinstance(last, str):
        try:
            last = datetime.fromisoformat(last)
        except Exception:
            return

    now = datetime.utcnow()
    diff_hours = (now - last).total_seconds() / 3600.0
    already_marked = user.get("returned_after_ghost", False)

    if diff_hours >= 48 and not already_marked:
        await log_event(telegram_id, "return_after_ghost")

        await execute(
            """
            UPDATE users
            SET returned_after_ghost = TRUE,
                ghost_return = TRUE,
                long_pause_used = TRUE,
                updated_at = NOW()
            WHERE telegram_id = %s
            """,
            telegram_id,
        )


# ==========================================================
# CTA IGNORED COUNTERS
# ==========================================================
async def mark_cta_ignored(telegram_id: int):
    """Increment cta_ignored_count by 1."""
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE users
                SET cta_ignored_count = COALESCE(cta_ignored_count, 0) + 1
                WHERE telegram_id = %s
                """,
                (telegram_id,),
            )


async def reset_ignored_count(telegram_id: int):
    """Reset ignored CTA count after user clicks or CTA successfully lands."""
    await update_field(telegram_id, "cta_ignored_count", 0)


# =============================================================
# TELETHON USER LOADER
# =============================================================
async def load_or_create_user_from_telethon(sender):
    telegram_id = sender.id
    username = sender.username or ""
    first = sender.first_name or ""
    last = sender.last_name or ""

    row = await get_user(telegram_id)
    if row:
        return row

    lang = getattr(sender, "language_code", "") or ""
    lang = lang.upper()

    country = ""
    if "-" in lang:
        country = lang.split("-")[1]
    elif len(lang) == 2:
        country = lang

    from logic import determine_country_tier

    tier = determine_country_tier(country)

    await execute(
        """
        INSERT INTO users (
            telegram_id, username, first_name, last_name,
            country, country_tier,
            returned_after_ghost,
            post_conversion_active,
            post_conversion_message_count,
            fanvue_chat_preference
        )
        VALUES (%s, %s, %s, %s, %s, %s, FALSE, FALSE, 0, 'standard')
        """,
        telegram_id,
        username,
        first,
        last,
        country,
        tier,
    )

    return await get_user(telegram_id)


# =============================================================
# SOFT REDIRECT WINDOW HELPERS
# =============================================================
async def activate_soft_redirect(telegram_id: int):
    """
    Begin the soft redirect window.
    - Marks soft_redirect_active = TRUE
    - Resets soft_redirect_message_count = 0
    - Sets soft_redirect_last_message_ts = NOW()
    - Sets soft_redirect_window_expires = NOW() + 4 hours
    """
    await execute(
        """
        UPDATE users
        SET soft_redirect_active = TRUE,
            soft_redirect_message_count = 0,
            soft_redirect_last_message_ts = NOW(),
            soft_redirect_window_expires = NOW() + INTERVAL '4 hours',
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def increment_soft_redirect_message_count(telegram_id: int):
    """
    Increase the drip-feed count for the soft redirect window.
    Updates soft_redirect_last_message_ts to NOW().
    """
    await execute(
        """
        UPDATE users
        SET soft_redirect_message_count =
                COALESCE(soft_redirect_message_count, 0) + 1,
            soft_redirect_last_message_ts = NOW(),
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def end_soft_redirect(telegram_id: int):
    """
    Terminate the soft redirect window.
    """
    await execute(
        """
        UPDATE users
        SET soft_redirect_active = FALSE,
            soft_redirect_message_count = 0,
            soft_redirect_last_message_ts = NULL,
            soft_redirect_window_expires = NULL,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


def get_soft_redirect_state(user: dict) -> dict:
    """Return a clean soft redirect state structure."""
    return {
        "active": bool(user.get("soft_redirect_active") or False),
        "count": int(user.get("soft_redirect_message_count") or 0),
        "last_ts": user.get("soft_redirect_last_message_ts"),
        "expires": user.get("soft_redirect_window_expires"),
    }


async def auto_end_soft_redirect_if_expired(user: dict) -> bool:
    """
    Automatically ends soft redirect if the 4-hour window has expired.
    Returns True if ended, False otherwise.
    """
    telegram_id = user["telegram_id"]
    expires = user.get("soft_redirect_window_expires")

    if not expires:
        return False

    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires)
        except Exception:
            return False

    now = datetime.utcnow()

    if now >= expires:
        await end_soft_redirect(telegram_id)
        return True

    return False


async def mark_post_conversion_message(telegram_id: int):
    """
    Increments message count once user is in Stage 5.
    """
    await execute(
        """
        UPDATE users
        SET post_conversion_message_count = COALESCE(post_conversion_message_count, 0) + 1,
            post_conversion_active = TRUE,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def set_fanvue_chat_preference(telegram_id: int, mode: str):
    """
    Temporary legacy helper.
    Left in place to avoid breaking existing logic.
    Can be renamed in a later cleanup pass.
    """
    await execute(
        """
        UPDATE users
        SET fanvue_chat_preference = %s,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        mode,
        telegram_id,
    )


async def get_fanvue_chat_preference(telegram_id: int) -> str:
    row = await fetchrow(
        "SELECT fanvue_chat_preference FROM users WHERE telegram_id = %s",
        telegram_id,
    )
    return row.get("fanvue_chat_preference", "standard") if row else "standard"


# =============================================================
# POST-CTA TRACKING
# =============================================================
async def increment_post_cta_responses(telegram_id: int):
    """Track how many replies we have made after CTA click."""
    await execute(
        """
        UPDATE users
        SET post_cta_responses_given = COALESCE(post_cta_responses_given, 0) + 1,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def mark_inferred_conversion(telegram_id: int):
    """Mark Stage 5 (assumed conversion)."""
    await execute(
        """
        UPDATE users
        SET inferred_conversion = TRUE,
            inferred_conversion_ts = NOW(),
            funnel_stage = 5,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def mark_dormant_stage(telegram_id: int):
    """Mark Stage 6 (dormant)."""
    await execute(
        """
        UPDATE users
        SET dormant_stage_ts = NOW(),
            funnel_stage = 6,
            updated_at = NOW()
        WHERE telegram_id = %s
        """,
        telegram_id,
    )


async def get_post_cta_state(telegram_id: int):
    row = await get_user(telegram_id)
    return {
        "last_seen": row.get("post_cta_last_seen_ts"),
        "msg_count": row.get("post_cta_message_count", 0),
        "responses": row.get("post_cta_responses_given", 0),
        "inferred_conversion": row.get("inferred_conversion", False),
        "inferred_ts": row.get("inferred_conversion_ts"),
        "dormant_ts": row.get("dormant_stage_ts"),
    }


async def mark_post_cta_message(telegram_id: int):
    """
    Increase post-CTA message count and bump last-seen timestamp.
    Used when user returns after clicking the CTA.
    """
    user = await get_user(telegram_id)
    count = (user.get("post_cta_message_count") or 0) + 1

    await update_field(telegram_id, "post_cta_message_count", count)
    await update_field(telegram_id, "post_cta_last_seen_ts", datetime.utcnow())


async def mark_post_cta_response(telegram_id: int):
    """
    Track outbound responses during Stage 5.
    """
    user = await get_user(telegram_id)
    count = (user.get("post_cta_responses_given") or 0) + 1

    await update_field(telegram_id, "post_cta_responses_given", count)
    await update_field(telegram_id, "post_cta_last_seen_ts", datetime.utcnow())


async def move_to_dormant_stage(telegram_id: int):
    """
    Move user to Stage 6 (Dormant Post-Conversion).
    """
    await update_field(telegram_id, "funnel_stage", 6)
    await update_field(telegram_id, "dormant_stage_ts", datetime.utcnow())


async def get_user_by_slug(slug: str):
    """
    Look up a Telegram user by their short CTA slug.
    Used by redirect handler logic.
    """
    return await fetchrow(
        """
        SELECT *
        FROM users
        WHERE cta_slug = %s
        """,
        slug,
    )


# ==========================================================
# CTA COOLDOWN & DEAD MODE HELPERS
# ==========================================================
async def set_cta_cooldown(telegram_id: int, hours: int = 6):
    """Start a CTA cooldown window."""
    until = datetime.utcnow() + timedelta(hours=hours)
    await update_field(telegram_id, "cta_cooldown_until", until)


async def is_cta_in_cooldown(user: dict) -> bool:
    ts = user.get("cta_cooldown_until")
    if not ts:
        return False

    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            return False

    return datetime.utcnow() < ts


async def activate_dead_mode(telegram_id: int, hours: int = 24):
    """Enter CTA dead mode (no CTA allowed)."""
    until = datetime.utcnow() + timedelta(hours=hours)
    await update_field(telegram_id, "cta_dead_mode_active", True)
    await update_field(telegram_id, "cta_dead_mode_until", until)


async def deactivate_dead_mode(telegram_id: int):
    """Leave CTA dead mode."""
    await update_field(telegram_id, "cta_dead_mode_active", False)
    await update_field(telegram_id, "cta_dead_mode_until", None)
    await update_field(telegram_id, "cta_ignored_count", 0)


async def check_dead_mode(user: dict) -> bool:
    active = user.get("cta_dead_mode_active", False)
    until = user.get("cta_dead_mode_until")

    if not active:
        return False

    if until and isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except Exception:
            return False

    if until and datetime.utcnow() >= until:
        return False

    return True


# =============================================================
# CTA TIMESTAMP HELPERS
# =============================================================
async def update_cta_sent_ts(telegram_id: int):
    """Record when the CTA message was sent."""
    await update_field(
        telegram_id,
        "cta_last_sent_ts",
        datetime.utcnow().isoformat(),
    )


async def increment_ignored_count(telegram_id: int):
    """Increase ignore count when user does not click CTA."""
    user = await get_user(telegram_id)
    count = (user.get("cta_ignored_count") or 0) + 1
    await update_field(telegram_id, "cta_ignored_count", count)
    return count


# =============================================================
# SEXUAL MOMENTUM SUPPORT
# =============================================================
async def update_last_inbound_ts(telegram_id: int):
    """Record the timestamp of the most recent inbound message."""
    await update_field(
        telegram_id,
        "last_inbound_ts",
        datetime.utcnow().isoformat(),
    )