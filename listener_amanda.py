#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_listener_amanda.py

Telethon user-mode DM listener for Amanda Cayne.
Fully wired into PostgreSQL + emotional engine + GPT reply +
typing simulation + HP17 timing engine + CTA safety + ban detection.

Current cleanup status:
- Uses Telegram/DMGate CTA URL via build_cta_link()
- No Fanvue link dependency in listener flow
- Avoids double-incrementing inbound message count
- Reads API/session config from config.py
"""

import asyncio
import random
import sys
from datetime import datetime

from telethon import TelegramClient, events

# Safe Windows event loop policy
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# DB Layer
from database import (
    init_pool,
    load_or_create_user_from_telethon,
    log_message,
    touch_user_activity,
    record_return_if_needed,
    mark_post_cta_response,
    update_field,
    update_last_inbound_ts,
    update_cta_sent_ts,
    update_last_reply_time,
)

# Logic Layer
from logic import process_message_logic, build_cta_link

# Timing (HP17)
from timing import (
    has_reached_daily_limit,
    should_reply_now,
    compute_next_reply_time,
    now_est,
    is_icebreaker_scenario,
)

# GPT
from gpt import generate_gpt_reply

from config import (
    TG_API_ID,
    TG_API_HASH,
    BOT_NAME_AMANDA,
    PRINT_DEBUG,
)


# ==========================================================
# SUPER DEBUG LOGGER
# ==========================================================
def debug_state(label: str, user_row: dict, logic: dict, inbound_count: int) -> None:
    if not PRINT_DEBUG:
        return

    print("\n" + "=" * 70)
    print(f"🔍 DEBUG → {label}")
    print("=" * 70)

    print(f"Telegram ID       : {user_row.get('telegram_id')}")
    print(f"Username          : {user_row.get('username')}")
    print(f"Message Count     : {inbound_count}")

    print("\n--- Funnel & Heat ---")
    print(f"Funnel Stage      : {logic.get('funnel_stage')}")
    print(f"Heat Score        : {logic.get('heat_score')}")
    print(f"Sexual Intensity  : {logic.get('sexual_intensity')}")

    print("\n--- Emotional Engine ---")
    emo = logic.get("emotional_state", {})
    print(f"Mood              : {emo.get('mood')}")
    print(f"Affection         : {emo.get('affection')}")
    print(f"Desire            : {emo.get('desire')}")

    print("\n--- HP Flags ---")
    print(f"HP3 Dead Mode     : {logic.get('hp3_dead')}")
    print(f"HP6 Active        : {logic.get('hp6_active')}")
    print(f"HP13 Mode         : {logic.get('hp13_mode')}")
    print(f"HP13 Drip         : {logic.get('hp13_drip_mode')}")
    print(f"HP14 Mode         : {logic.get('hp14_mode')}")
    print(f"HP16 Drip         : {logic.get('hp16_drip_mode')}")
    print(f"Stage5 Return     : {logic.get('stage_5_return')}")

    print("\n--- Warmup / Icebreaker ---")
    print(f"Warm-Up Active    : {logic.get('warmup_active')}")
    print(f"Icebreaker        : {logic.get('icebreaker_hit')}")

    print("\n--- CTA ---")
    print(f"Should CTA        : {logic.get('should_cta')}")
    print(f"CTA Block Reason  : {logic.get('cta_block_reason')}")

    print("\n--- Timing ---")
    print(f"Timing Mode       : {logic.get('timing_mode')}")
    print(f"Next Allowed Time : {user_row.get('next_reply_after')}")

    print("=" * 70 + "\n")


# ==========================================================
# SESSION
# ==========================================================
SESSION_NAME = "tg_sessions/amanda"
BOT_NAME = BOT_NAME_AMANDA


def projected_inbound_count(user_row: dict) -> int:
    """
    Compute what the inbound count will be for this message
    without writing to the DB here. process_message_logic()
    performs the real increment.
    """
    return (user_row.get("inbound_message_count") or 0) + 1


# ==========================================================
# TYPING SIMULATION
# ==========================================================
def get_typing_speed(persona: str, emotional_state: dict) -> float:
    mood = emotional_state.get("mood", "warm")

    base = 0.9
    mood_map = {
        "intimate": 0.75,
        "teasing": 0.85,
        "playful": 1.00,
        "warm": 1.10,
    }

    return base * mood_map.get(mood, 1.0)


async def send_typing_action(
    client: TelegramClient,
    chat_id: int,
    reply: str,
    emotional_state: dict,
) -> None:
    length = len(reply)
    speed = get_typing_speed("amanda", emotional_state)

    thinking = random.uniform(0.3, 1.0) * speed
    if emotional_state.get("mood") == "intimate":
        thinking += random.uniform(0.2, 0.6)

    await asyncio.sleep(thinking)

    char_time = 0.045 * speed
    total = min(max(length * char_time, 1.8), 6.0)
    total += random.uniform(0.2, 0.8)

    if random.random() < 0.25:
        total += random.uniform(0.4, 0.9)

    end_time = asyncio.get_event_loop().time() + total
    while asyncio.get_event_loop().time() < end_time:
        try:
            await client.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        await asyncio.sleep(0.7)


# ==========================================================
# MAIN LISTENER
# ==========================================================
async def main() -> None:
    print("🔌 Initializing database pool...")
    await init_pool()

    print("📲 Starting Amanda TG listener...")
    client = TelegramClient(SESSION_NAME, TG_API_ID, TG_API_HASH)

    await client.start()
    print("💬 Amanda Listener Ready.\n")

    @client.on(events.NewMessage(incoming=True))
    async def handle_new_message(event):
        if not event.is_private:
            return

        sender = await event.get_sender()
        telegram_id = sender.id
        incoming_text = event.raw_text.strip()

        if not incoming_text:
            return

        print(f"\n📥 Incoming DM from {sender.username or telegram_id}: {incoming_text}")

        # -----------------------------------------------------
        # Load/create user
        # -----------------------------------------------------
        user_row = await load_or_create_user_from_telethon(sender)

        # -----------------------------------------------------
        # Compute projected inbound count
        # NOTE: process_message_logic() performs the actual DB increment.
        # -----------------------------------------------------
        inbound_count = projected_inbound_count(user_row)

        # -----------------------------------------------------
        # HP17 BLOCK — enforce schedule (AFTER warm-up only)
        # -----------------------------------------------------
        next_after = user_row.get("next_reply_after")

        if next_after:
            if isinstance(next_after, str):
                try:
                    next_after = datetime.fromisoformat(next_after)
                except Exception:
                    next_after = None

            if next_after and next_after.tzinfo:
                next_after = next_after.replace(tzinfo=None)

            now_local = now_est().replace(tzinfo=None)

            if inbound_count > 5 and next_after and now_local < next_after:
                print(f"⏳ HP17 BLOCK → Too early. Next allowed: {next_after}")
                return

        # -----------------------------------------------------
        # Sleep mode (1am–8am EST)
        # -----------------------------------------------------
        hour = now_est().hour
        if 1 <= hour < 8:
            print("🌙 Sleep mode active — no reply until 8am EST")
            return

        # -----------------------------------------------------
        # CTA URL (Telegram / DMGate)
        # -----------------------------------------------------
        cta_url = build_cta_link(telegram_id, "amanda")

        # -----------------------------------------------------
        # Ghost return detection
        # -----------------------------------------------------
        await record_return_if_needed(user_row)

        # -----------------------------------------------------
        # Log inbound message
        # -----------------------------------------------------
        await log_message(telegram_id, "inbound", incoming_text, BOT_NAME)
        await touch_user_activity(telegram_id)
        await update_last_inbound_ts(telegram_id)

        # -----------------------------------------------------
        # Daily limit enforcement
        # -----------------------------------------------------
        if has_reached_daily_limit(user_row):
            print("🚫 Daily limit reached — NOT replying.")
            return

        # -----------------------------------------------------
        # PROCESS MESSAGE (logic engine)
        # -----------------------------------------------------
        logic = await process_message_logic({**user_row}, incoming_text)
        logic["raw_message"] = incoming_text

        # -----------------------------------------------------
        # Inject warmup + icebreaker flags for debugging
        # -----------------------------------------------------
        is_warmup = (
            logic["funnel_stage"] <= 1
            and inbound_count <= 5
            and logic["sexual_intensity"] in ("none", "flirty")
        )
        logic["warmup_active"] = is_warmup
        logic["icebreaker_hit"] = is_icebreaker_scenario(user_row, logic)

        debug_state("POST-LOGIC STATE", user_row, logic, inbound_count)

        emotional_state = logic["emotional_state"]
        funnel_stage = logic["funnel_stage"]
        should_cta = logic["should_cta"]
        heat_score = logic["heat_score"]

        hp13_mode = logic.get("hp13_mode", False)
        hp13_drip_mode = logic.get("hp13_drip_mode", False)
        hp16_drip_mode = logic.get("hp16_drip_mode", False)
        stage_5_return = logic.get("stage_5_return", False)
        hp6_active = logic.get("hp6_active", False)
        hp6_pref = logic.get("hp6_preference", None)
        hp6_inbound_cnt = logic.get("hp6_inbound_count", 0)
        hp3_dead = logic.get("hp3_dead", False)
        hp14_mode = logic.get("hp14_mode", False)

        # -----------------------------------------------------
        # HP3 — DEAD MODE
        # -----------------------------------------------------
        if hp3_dead:
            print("💀 HP3 ACTIVE — No reply will be sent.")
            return

        # -----------------------------------------------------
        # WARM-UP FAST MODE
        # -----------------------------------------------------
        if is_warmup:
            warm_map = {
                1: (2, 8),
                2: (4, 12),
                3: (6, 18),
                4: (8, 25),
                5: (10, 45),
            }
            lo, hi = warm_map.get(inbound_count, (6, 18))
            delay = random.uniform(lo, hi)
            print(f"🔥 WARM-UP FAST MODE → replying in {delay:.1f}s")
            await asyncio.sleep(delay)

        else:
            if logic["icebreaker_hit"] and inbound_count <= 5:
                delay = random.uniform(2.0, 8.0)
                print(f"✨ ICEBREAKER → replying fast in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                if funnel_stage == 5 and not hp6_active:
                    print("🔥 Stage 5 override → Immediate reply allowed")
                else:
                    if not should_reply_now({**user_row, **logic}):
                        print("⏳ BLOCKED by HP17 timing")
                        return

        # -----------------------------------------------------
        # Generate GPT reply
        # -----------------------------------------------------
        reply_text = await generate_gpt_reply(
            message=incoming_text,
            persona="amanda",
            username=sender.username or "",
            emotional_state=emotional_state,
            funnel_stage=funnel_stage,
            tier=user_row.get("country_tier", "C"),
            heat_score=heat_score,
            should_cta=should_cta,
            cta_url=cta_url,
            chat_id=telegram_id,
            hp13_mode=hp13_mode,
            hp13_drip_mode=hp13_drip_mode,
            hp16_drip_mode=hp16_drip_mode,
            stage_5_return=stage_5_return,
            hp6_active=hp6_active,
            hp6_preference=hp6_pref,
            hp6_inbound_count=hp6_inbound_cnt,
            hp3_dead=hp3_dead,
            hp14_mode=hp14_mode,
            warmup=is_warmup,
            inbound_count=inbound_count,
        )

        # -----------------------------------------------------
        # Typing simulation + send
        # -----------------------------------------------------
        try:
            mood_for_typing = {"mood": "warm"} if hp6_active else emotional_state
            await send_typing_action(client, telegram_id, reply_text, mood_for_typing)

            await event.respond(reply_text)
            print(f"📤 Sent → {reply_text}")

            if logic.get("should_cta"):
                await update_cta_sent_ts(telegram_id)

            if stage_5_return and not hp6_active:
                await mark_post_cta_response(telegram_id)

        except Exception as e:
            print(f"❌ Sending Error: {e}")
            return

        # -----------------------------------------------------
        # Log outbound message
        # -----------------------------------------------------
        await log_message(telegram_id, "outbound", reply_text, BOT_NAME)

        # -----------------------------------------------------
        # Save last reply time
        # -----------------------------------------------------
        await update_last_reply_time(telegram_id)

        # -----------------------------------------------------
        # SCHEDULE NEXT REPLY (HP17)
        # -----------------------------------------------------
        next_ts = await compute_next_reply_time(
            {**user_row, **logic, "inbound_message_count": inbound_count}
        )
        await update_field(telegram_id, "next_reply_after", next_ts.isoformat())

        print(f"⏱️ HP17 SCHEDULED → Next reply allowed after: {next_ts}")

        await touch_user_activity(telegram_id)

    await client.run_until_disconnected()


# ==========================================================
# ENTRYPOINT
# ==========================================================
if __name__ == "__main__":
    asyncio.run(main())