"""
Wrapper around Finnhub for general market news and the economic calendar.
Free tier: sign up at finnhub.io, no card required.
"""
import os
import requests
from datetime import datetime, timedelta, timezone

API_KEY = os.environ.get("FINNHUB_API_KEY")
BASE_URL = "https://finnhub.io/api/v1"


def fetch_general_news(limit=8):
    """Returns recent general market news headlines."""
    if not API_KEY:
        return []
    try:
        resp = requests.get(
            f"{BASE_URL}/news",
            params={"category": "general", "token": API_KEY},
            timeout=10
        )
        data = resp.json()
        if not isinstance(data, list):
            return []
        return data[:limit]
    except Exception:
        return []


def fetch_economic_calendar(days_ahead=1):
    """Returns upcoming economic calendar events over the next `days_ahead` days."""
    if not API_KEY:
        return []
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days_ahead)
    try:
        resp = requests.get(
            f"{BASE_URL}/calendar/economic",
            params={"from": today.isoformat(), "to": end.isoformat(), "token": API_KEY},
            timeout=10
        )
        data = resp.json()
        return data.get("economicCalendar", [])
    except Exception:
        return []


def fetch_high_impact_events_soon(hours_ahead=1):
    """
    Returns high-impact calendar events starting within the next `hours_ahead` hours.
    Each item: {event, country, impact, time}
    """
    events = fetch_economic_calendar(days_ahead=1)
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)
    upcoming = []

    for e in events:
        impact = str(e.get("impact", "")).lower()
        if impact not in ("high", "3"):  # Finnhub sometimes uses numeric impact levels
            continue
        try:
            event_time = datetime.fromisoformat(e.get("time", "").replace("Z", "+00:00"))
        except Exception:
            continue
        if now <= event_time <= cutoff:
            upcoming.append(e)

    return upcoming
