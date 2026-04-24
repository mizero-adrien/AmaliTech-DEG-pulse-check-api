import json
import logging
import os
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None

_SYSTEM_PROMPT = (
    "You are an IoT device monitoring expert. Analyze the device failure and return "
    "ONLY a JSON object with: diagnosis, recommended_action, confidence, health_score"
)


def _get_client() -> anthropic.AsyncAnthropic:
    # Lazy init so missing API key doesn't crash the server on startup
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


async def analyze_device_failure(
    device_id: str,
    last_ping: datetime | None,
    timeout: int,
    previous_alert_count: int,
) -> dict:
    now = datetime.now(timezone.utc)
    last_ping_aware = last_ping.replace(tzinfo=timezone.utc) if last_ping.tzinfo is None else last_ping
    down_for = int((now - last_ping_aware).total_seconds()) if last_ping else timeout

    user_message = (
        f"Device '{device_id}' has gone offline.\n"
        f"Last heartbeat: {last_ping.isoformat() if last_ping else 'unknown'}\n"
        f"Configured timeout: {timeout} seconds\n"
        f"Estimated downtime so far: {down_for} seconds\n"
        f"Previous failure count: {previous_alert_count}\n\n"
        "Return ONLY a JSON object with these exact keys:\n"
        '- "diagnosis": one of "power failure", "network issue", "theft", "hardware failure"\n'
        '- "recommended_action": short action string\n'
        '- "confidence": percentage string e.g. "87%"\n'
        '- "health_score": integer 0-100'
    )

    logger.info("Requesting AI analysis for device '%s' (down ~%ds)", device_id, down_for)

    response = await _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    logger.debug("AI raw response for '%s': %s", device_id, raw)

    # Strip markdown fences Claude sometimes wraps around JSON
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)
    logger.info(
        "AI analysis for '%s': diagnosis=%s confidence=%s health=%s",
        device_id,
        result.get("diagnosis"),
        result.get("confidence"),
        result.get("health_score"),
    )
    return result
