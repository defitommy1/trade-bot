"""
Generates written bias/reasoning text from raw news + calendar data, using
an OpenAI-compatible chat completions endpoint (e.g. AgentRouter).

UNVERIFIED: this assumes a standard OpenAI-compatible /chat/completions
format. If AgentRouter's actual API differs, this will need adjusting —
check their docs for the exact base URL, auth header, and model name.
"""
import os
import requests

API_KEY = os.environ.get("AGENTROUTER_API_KEY")
BASE_URL = os.environ.get("AGENTROUTER_BASE_URL", "https://agentrouter.org/v1")
MODEL = os.environ.get("AGENTROUTER_MODEL", "gpt-4o-mini")


def generate_bias(headlines, calendar_events):
    """
    Takes a list of headline strings and a list of calendar event dicts,
    returns a short written market bias with reasoning. Returns None on failure.
    """
    if not API_KEY:
        return None

    headline_text = "\n".join(f"- {h}" for h in headlines) if headlines else "No major headlines."
    event_text = "\n".join(
        f"- {e.get('event', 'Unknown event')} ({e.get('country', '')})"
        for e in calendar_events
    ) if calendar_events else "No high-impact events in the next 24h."

    prompt = (
        "You are a concise trading assistant. Based on the following market news "
        "and upcoming economic events, write a short daily market bias (bullish/"
        "bearish/neutral per major asset class where relevant — forex, indices, "
        "crypto) with 2-3 sentences of reasoning per point. Keep it factual and "
        "grounded in the data given, not speculative beyond it. Under 200 words.\n\n"
        f"Recent headlines:\n{headline_text}\n\n"
        f"Upcoming high-impact events (next 24h):\n{event_text}"
    )

    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
            },
            timeout=30
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
