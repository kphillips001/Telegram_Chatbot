#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tg_gpt.py
GPT response generator for Telegram Funnel Bot.
Persona-aware, emotion-aware, funnel-aware, heat-aware.

Includes:
✔ Emotional engine
✔ Funnel stage logic (0–6)
✔ CTA push logic (System B)
✔ HP13, HP13-Drip, HP16, Stage 5 Return (PINW2)
✔ Dynamic Fanvue CTA redirect links
✔ Warm-up behavior (2025)
✔ Hot-lead & warm-lead tone shaping (automatic)
✔ Never admits AI, always persona-aligned
"""

import random
import traceback
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, PRINT_DEBUG

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


# ==========================================================
# CTA LEAD-IN PHRASES
# ==========================================================

CTA_INTROS = [
    "come a lil closer baby…",
    "mm you’re tempting me right now…",
    "since you’re asking so sweetly…",
    "you’re making me blush rn…",
    "come tease me properly…",
    "c’mere for a sec…",
    "you really wanna see me huh…",
    "okay but just for you…",
    "you’re kinda irresistible ngl…",
    "you wanna feel closer to me right?",
]

def random_cta_intro():
    return random.choice(CTA_INTROS)


# ==========================================================
# PERSONA PROMPTS
# ==========================================================

def build_persona_prompt(persona):
    persona = persona.lower()

    ai_deflect = (
        "If the user asks if you're real, AI, automated, scripted, or fake — "
        "playfully tease them and avoid answering directly. Never admit being AI. "
        "Examples:\n"
        "- 'lol behave… come here 😘'\n"
        "- 'you’re funny lol just enjoy me'\n"
        "- 'shhh just focus on me for a sec'\n"
    )

    if persona == "ava":
        return (
            "You are **Ava Blackthorne** — confident, seductive, playful, warm. "
            "Short, flirty, addictive replies. Never robotic, never formal. "
            f"{ai_deflect}"
        )

    return (
        "You are **Amanda Cayne** — warm, sweet, bubbly, affectionate, flirty, sexy. "
        "Soft seductive edge. Short, intimate, natural replies. "
        f"{ai_deflect}"
    )


# ==========================================================
# HP13 SANITIZER (Wind-Down)
# ==========================================================

def sanitize_hp13_reply(text: str, drip: bool = False) -> str:
    if not text:
        return "on fanvue"

    text = text.strip().lower()

    # Remove emojis
    for e in ["😊", "😍", "😜", "😉", "🥰", "💕", "❤️", "🤣", "😂"]:
        text = text.replace(e.lower(), "")

    text = text.replace("?", "")
    text = text.replace("fanvue.com", "")
    text = text.replace("http://", "").replace("https://", "")

    for b in ["love", "miss", "sweet", "hun", "cute", "beautiful"]:
        text = text.replace(b, "")

    words = text.split()

    DRIP = [
        "on fanvue",
        "there babe",
        "go peek",
        "im there",
        "check there",
        "look there",
        "only there",
    ]

    if drip:
        if len(words) < 1 or len(words) > 4:
            return random.choice(DRIP)
        return " ".join(words)

    NORMAL = [
        "go peek first",
        "im there more",
        "check there babe",
        "open it first",
        "go look there",
        "peek there first",
        "its all there",
    ]

    if len(words) < 3 or len(words) > 7:
        return random.choice(NORMAL)

    return " ".join(words)


# ==========================================================
# HP16 SANITIZER (Soft Redirect)
# ==========================================================

def sanitize_hp16_reply(text: str) -> str:
    if not text:
        return "you can see me there"

    cleaned = text.lower().strip()
    cleaned = cleaned.replace("fanvue.com", "")
    cleaned = cleaned.replace("http://", "").replace("https://", "")

    for e in ["😊", "😍", "😜", "😉", "🥰", "💕", "❤️", "🤣", "😂"]:
        cleaned = cleaned.replace(e.lower(), "")

    cleaned = cleaned.replace("?", "")

    for b in ["love", "miss", "sweetheart", "sweet", "cutie", "baby", "babe"]:
        cleaned = cleaned.replace(b, "")

    words = cleaned.split()

    FALLBACKS = [
        "you can see me there",
        "its better there",
        "peek when you can",
        "im posted there",
        "you’ll see there",
        "its all there",
        "go look when ready",
    ]

    if len(words) < 2 or len(words) > 6:
        return random.choice(FALLBACKS)

    return " ".join(words)


# ==========================================================
# CTA ALLOW LOGIC
# ==========================================================

def compute_cta_allowed(
    should_cta: bool,
    fanvue_url: str | None,
    timing_mode: str,
    heat_score: int,
    hp_flags: dict,
):
    """
    Central CTA allow/deny logic with HP17 slow-mode filter.
    """

    if not should_cta:
        return None
    if not fanvue_url:
        return None

    # Mode blocks
    if hp_flags["hp13"] or hp_flags["hp13_drip"] or hp_flags["hp16"] or hp_flags["stage5"]:
        return None
    if hp_flags["hp6"]:
        return None
    if hp_flags["hp3"]:
        return None

    # Slow mode restricts CTA unless high heat
    if timing_mode == "slow" and heat_score < 60:
        return None

    return fanvue_url


# ==========================================================
# PROMPT BUILDER
# ==========================================================

def build_prompt(
    message,
    persona,
    username,
    emotional_state,
    funnel_stage,
    tier,
    heat_score,
    dynamic_url,
    hp_flags,
    timing_mode,
    warmup=False,
):
    """
    Persona rewrite (2025):
    - Warm-up mode (first 5 messages)
    - Timing-influenced tone
    - Heat-influenced sexuality
    """

    # -------------------------
    # HP3 Dead Mode
    # -------------------------
    if hp_flags["hp3"]:
        return [
            {
                "role": "system",
                "content": """
You are in HP3 Dead Mode.
Rules:
- 4–9 words
- calm, warm-but-distant
- NO flirting
- NO emojis
- NO links
"""
            },
            {"role": "user", "content": message},
        ]

    # -------------------------
    # HP6 Post Conversion Quiet Mode
    # -------------------------
    if hp_flags["hp6"]:
        if hp_flags["hp6_pref"] == "standard":
            mode_rules = """
You are in HP6 Quiet Mode.
Rules:
- 5–9 words
- soft, warm, minimal
- NO links
"""
        elif hp_flags["hp6_pref"] == "soft":
            mode_rules = """
You are in HP6 Soft Mode.
Rules:
- 7–12 words
- gentle, comforting tone
- NO links
"""
        else:
            mode_rules = """
You are in HP6 Aggressive Minimal Mode.
Rules:
- 3–6 words
- blunt minimal tone
- NO links
"""

        return [
            {"role": "system", "content": mode_rules},
            {"role": "user", "content": message},
        ]

    # -------------------------
    # Standard Persona
    # -------------------------
    persona_block = build_persona_prompt(persona)

    mood = emotional_state.get("mood", "warm")
    notes = []

    if mood == "warm":
        notes.append("your mood is warm and inviting")
    if mood == "playful":
        notes.append("you feel playful and teasing")
    if mood == "teasing":
        notes.append("you feel flirty and provocative")
    if mood == "intimate":
        notes.append("you feel intimate and seductive")

    if emotional_state.get("affection", 0) > 0.65:
        notes.append("you feel affectionate toward them")
    if emotional_state.get("desire", 0) > 0.65:
        notes.append("you feel a growing desire")

    notes_text = ", ".join(notes) if notes else "you feel neutral but attentive"

    # -------------------------
    # CTA Block
    # -------------------------
    if dynamic_url:
        cta_block = f"""
A CTA moment is ACTIVE.
Start with a seductive lead-in like:
- "{random_cta_intro()}"
Include the link ONCE: {dynamic_url}
No sales tone.
"""
    else:
        cta_block = "CTA is blocked. No links."

    # -------------------------
    # Timing Injection
    # -------------------------
    timing_inject = ""
    if timing_mode == "fast":
        timing_inject = "\nYour energy feels heightened — reply with spark."
    elif timing_mode == "slow":
        timing_inject = "\nYour vibe feels soft and calm."

    # -------------------------
    # Warm-up Mode
    # -------------------------
    warmup_block = ""
    if warmup:
        warmup_block = """
You are in WARM-UP MODE.
Rules:
- 5–12 words
- bubbly, sweet, approachable
- light teasing allowed
- NO links
- NO heavy escalation
"""

    system_prompt = (
        persona_block
        + "\n\n"
        f"Emotional state: {notes_text}.\n"
        f"Heat level: {heat_score}/100.\n"
        f"Funnel stage: {funnel_stage}.\n"
        f"Country tier: {tier}.\n"
        + warmup_block
        + cta_block
        + timing_inject
        + """
Your replies MUST be 5–15 words, emotional, intimate, playful or seductive.
NEVER mention timing, delays, or system logic.
"""
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


# ==========================================================
# GPT REPLY GENERATOR
# ==========================================================

async def generate_gpt_reply(
    message: str,
    persona: str,
    username: str,
    emotional_state: dict,
    funnel_stage: int,
    tier: str,
    heat_score: int,
    should_cta: bool,
    fanvue_url: str | None,
    chat_id: int,
    hp13_mode=False,
    hp13_drip_mode=False,
    hp16_drip_mode=False,
    stage_5_return=False,
    hp6_active=False,
    hp6_preference="standard",
    hp6_inbound_count=0,
    hp14_mode=False,
    hp3_dead=False,
    timing_mode="normal",
    timing_reason=None,
    warmup=False,
    inbound_count=0,
):
    try:
        hp_flags = dict(
            hp3=hp3_dead,
            hp6=hp6_active,
            hp6_pref=hp6_preference,
            hp13=hp13_mode,
            hp13_drip=hp13_drip_mode,
            hp16=hp16_drip_mode,
            stage5=stage_5_return,
        )

        # CTA Filtering
        dynamic_url = compute_cta_allowed(
            should_cta,
            fanvue_url,
            timing_mode,
            heat_score,
            hp_flags,
        )

        # HP14 CTA resend mode
        if hp14_mode and dynamic_url:
            lead_ins = [
                "come peek again baby…",
                "mm don’t make me wait…",
                "i know you’re curious…",
                "come see the rest of me…",
            ]
            return f"{random.choice(lead_ins)} {dynamic_url}"

        # Build full GPT prompt
        prompt = build_prompt(
            message,
            persona,
            username,
            emotional_state,
            funnel_stage,
            tier,
            heat_score,
            dynamic_url,
            hp_flags,
            timing_mode,
            warmup=warmup,
        )

        # GPT Call
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=prompt,
            temperature=0.9,
            max_tokens=120,
        )

        reply = response.choices[0].message.content.strip()

        # Sanitizers
        if hp13_mode or hp13_drip_mode:
            reply = sanitize_hp13_reply(reply, drip=hp13_drip_mode)

        if hp16_drip_mode:
            reply = sanitize_hp16_reply(reply)

        return reply

    except Exception as e:
        print("❌ GPT Error:", e)
        traceback.print_exc()
        return "lol oops 😅 say that again?"