#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from datetime import datetime

from database import (
    get_user_by_slug,
    update_field,
    update_next_reply_after,   # ⭐ HP17 REQUIRED
)

from config import FANVUE_LINK_AMANDA, FANVUE_LINK_AVA

app = FastAPI()


# ======================================================
# HP18 — Short Slug Redirect Handler
# ======================================================what 
@app.get("/go/{slug}")
async def handle_slug_click(slug: str):

    # ======================================================
    # 1. Fetch user by CTA slug
    # ======================================================
    user = await get_user_by_slug(slug)
    if not user:
        return {"error": "invalid slug"}

    telegram_id = user["telegram_id"]
    now = datetime.utcnow()

    # ======================================================
    # ⭐ 2. Mark CTA Click Event  (Stage 4)
    # ======================================================

    # Move user into Stage 4 (CTA Clicked)
    await update_field(telegram_id, "funnel_stage", 4)

    # Increment click count
    clicked_count = (user.get("cta_link_clicked_count") or 0) + 1
    await update_field(telegram_id, "cta_link_clicked_count", clicked_count)

    # Save timestamps
    await update_field(telegram_id, "cta_last_clicked_ts", now)
    await update_field(telegram_id, "post_cta_last_seen_ts", now)

    # Seed Stage 5 return timer
    await update_field(telegram_id, "stage5_return_seed_ts", now)

    # Reset stage-5 tracking counters
    await update_field(telegram_id, "post_cta_message_count", 0)
    await update_field(telegram_id, "post_cta_responses_given", 0)

    # Reset conversion flags to start fresh
    await update_field(telegram_id, "inferred_conversion", False)
    await update_field(telegram_id, "inferred_conversion_ts", None)
    await update_field(telegram_id, "dormant_stage_ts", None)

    # Reset CTA counters
    await update_field(telegram_id, "sexual_trigger_count", 0)

    # ======================================================
    # ⭐ HP16 — Reset ALL Soft Redirect Window Fields
    # ======================================================
    await update_field(telegram_id, "soft_redirect_active", False)
    await update_field(telegram_id, "soft_redirect_message_count", 0)
    await update_field(telegram_id, "soft_redirect_last_message_ts", None)
    await update_field(telegram_id, "soft_redirect_window_expires", None)

    # ======================================================
    # ⭐ HP17 — TIMING ENGINE RESET
    # ======================================================

    # Make sure the bot can reply IMMEDIATELY after a CTA click.
    await update_next_reply_after(telegram_id, now)

    # CTA click resets the long-haul timer
    await update_field(telegram_id, "last_reply_time", now)

    # ======================================================
    # 3. Persona-based Fanvue Redirect
    # ======================================================
    persona = (user.get("persona") or "amanda").lower()

    if persona == "ava":
        return RedirectResponse(FANVUE_LINK_AVA)

    return RedirectResponse(FANVUE_LINK_AMANDA)