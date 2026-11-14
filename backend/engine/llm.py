"""Optional plain-language explainer (and translation) using Claude.

Only used if ANTHROPIC_API_KEY is set. The model is given ONLY our computed facts as JSON and told
not to add new numbers, so it rephrases rather than invents. Without a key, a template summary is used.
"""
from __future__ import annotations

import json

import requests

from backend import config

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You explain crop-rotation analysis to smallholder farmers. Use short sentences and everyday words. "
    "Use ONLY the facts in the JSON you are given; never invent numbers, crops, prices or dates. "
    "Structure: 1) what the plan is, 2) why it could help, 3) what to watch out for, "
    "4) what to check with an extension officer. Keep it under 160 words. "
    "Remind the farmer this is a support tool, not a replacement for local advice."
)


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def explain_plain(strategy: dict, site_name: str, language: str = "English") -> dict:
    facts = {
        "site": site_name, "plan": strategy.get("sequence"), "name": strategy.get("name"),
        "why": strategy.get("explanation", {}).get("why"), "benefits": strategy.get("explanation", {}).get("benefits"),
        "risks": strategy.get("explanation", {}).get("risks"),
        "check_with_expert": strategy.get("explanation", {}).get("ask_expert"),
        "confidence": strategy.get("explanation", {}).get("confidence"),
    }
    fallback = strategy.get("explanation", {}).get("summary", "")
    if not available():
        return {"text": fallback, "source": "template", "note": "Set ANTHROPIC_API_KEY in .env for AI plain-language and translation."}
    body = {
        "model": config.LLM_MODEL, "max_tokens": 600, "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Language: {language}\n\nFacts (JSON):\n{json.dumps(facts, ensure_ascii=False)}"}],
    }
    headers = {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    try:
        resp = requests.post(API_URL, headers=headers, json=body, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return {"text": text.strip() or fallback, "source": config.LLM_MODEL}
    except requests.RequestException as err:
        return {"text": fallback, "source": "template", "note": f"AI explainer unavailable: {err}"}

