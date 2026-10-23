"""Conversational booking ("I want to fly to Canada next Friday").

The client does speech-to-text and text-to-speech (Web Speech API / native SDKs);
this endpoint does the understanding. A rule-based parser handles common phrasing
offline; with ANTHROPIC_API_KEY set, Claude extracts the trip instead and the
rule-based parser is the fallback.
"""
import calendar
import json
import logging
import re
from datetime import date, timedelta

import httpx

from .. import airports
from ..config import get_settings

log = logging.getLogger("quik.assistant")

WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
YES = re.compile(r"^\s*(yes|yeah|yep|ok(ay)?|sure|book it|go ahead|do it|confirm|that one|sounds good)\b", re.I)


def _places() -> list[tuple[str, str]]:
    """(lowercase name, kind) for every city, state, country and IATA we know — longest first."""
    names = set()
    for a in airports.all_airports():
        names |= {(a.city.lower(), "city"), (a.country.lower(), "country"), (a.state.lower(), "state")}
    names |= {("uk", "country"), ("usa", "country"), ("us", "country"), ("america", "country"), ("dubai", "city")}
    return sorted(names, key=lambda n: -len(n[0]))


ALIASES = {"uk": "United Kingdom", "usa": "United States", "us": "United States", "america": "United States"}


def _find_place(fragment: str) -> str | None:
    frag = f" {fragment.lower()} "
    for name, _ in _places():
        if re.search(rf"\b{re.escape(name)}\b", frag):
            return ALIASES.get(name, name)
    m = re.search(r"\b([A-Z]{3})\b", fragment)
    if m and airports.get(m.group(1)):
        return m.group(1)
    return None


def _parse_date(text: str, today: date) -> date | None:
    t = text.lower()
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "today" in t or "tonight" in t:
        return today
    if m := re.search(r"in (\d+|\w+) (day|week)s?", t):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1), 0)
        if n:
            return today + timedelta(days=n * (7 if m.group(2) == "week" else 1))
    if "next week" in t:
        return today + timedelta(days=7)
    if "next month" in t:
        return (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    if m := re.search(r"\b(next|this|on|coming)?\s*(" + "|".join(WEEKDAYS) + r")\b", t):
        wd = WEEKDAYS[m.group(2)]
        # "next Friday" is read as the coming Friday, which is what most people mean.
        delta = (wd - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    mon = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({mon})\b", t) or re.search(rf"\b({mon})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
    if m:
        a, b = m.groups()
        day, month = (int(a), MONTHS[b]) if a.isdigit() else (int(b), MONTHS[a])
        try:
            d = date(today.year, month, day)
        except ValueError:
            return None
        return d if d >= today else date(today.year + 1, month, day)
    return None


def rule_parse(text: str, today: date) -> dict:
    t = text.strip()
    out: dict = {}
    if m := re.search(r"\bfrom ([a-zA-Z .'-]+?)(?=\s+(?:to|on|next|this|tomorrow|today|in|for|with|and)\b|[,.?!]|$)", t, re.I):
        out["origin_place"] = _find_place(m.group(1))
    if m := re.search(r"\bto ([a-zA-Z .'-]+?)(?=\s+(?:from|on|next|this|tomorrow|today|in|for|with|and|by)\b|[,.?!]|$)", t, re.I):
        out["destination_place"] = _find_place(m.group(1))
    elif not out.get("origin_place"):
        out["destination_place"] = _find_place(t)

    dep_text, ret_text = t, None
    if m := re.search(r"\b(?:return(?:ing)?|back|coming back)\b(.*)", t, re.I):
        dep_text, ret_text = t[: m.start()], m.group(1)
    if d := _parse_date(dep_text, today):
        out["departure_date"] = d
    if ret_text and (r := _parse_date(ret_text, out.get("departure_date") or today)):
        out["return_date"] = r
    if m := re.search(r"\bfor (\d+|\w+) (day|night|week)s?\b", t, re.I):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1).lower(), 0)
        if n and out.get("departure_date"):
            out["return_date"] = out["departure_date"] + timedelta(days=n * (7 if m.group(2).lower() == "week" else 1))

    if m := re.search(r"\b(\d+|\w+)\s+(?:adults?|people|persons|passengers|of us)\b", t, re.I):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1).lower())
        if n:
            out["adults"] = n
    elif re.search(r"\b(me and my|my (wife|husband|partner)|the two of us)\b", t, re.I):
        out["adults"] = 2
    if m := re.search(r"\b(\d+|\w+)\s+(?:kids|children|child)\b", t, re.I):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1).lower())
        if n:
            out["children"] = n
    for cabin, pat in [("business", r"business"), ("first", r"first class"), ("premium_economy", r"premium")]:
        if re.search(pat, t, re.I):
            out["cabin_class"] = cabin
    if re.search(r"\b(hotel|stay|accommodation|room)\b", t, re.I):
        out["want_hotel"] = True
    if re.search(r"\b(driver|ride|pick ?up|taxi|uber|bolt|car)\b", t, re.I):
        out["want_ride"] = True
    if re.search(r"\b(cheap|cheapest|budget|lowest)\b", t, re.I):
        out["priority"] = "cheapest"
    elif re.search(r"\b(fast|fastest|quick|nonstop|direct)\b", t, re.I):
        out["priority"] = "fastest"
    return {k: v for k, v in out.items() if v is not None}


async def llm_parse(text: str, today: date) -> dict | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    tool = {
        "name": "extract_trip",
        "description": "Extract the flight the traveller wants. Leave fields out if not stated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin_place": {"type": "string", "description": "City, country or IATA code they fly from"},
                "destination_place": {"type": "string", "description": "City, country or IATA code they fly to"},
                "departure_date": {"type": "string", "format": "date"},
                "return_date": {"type": "string", "format": "date"},
                "adults": {"type": "integer"}, "children": {"type": "integer"},
                "cabin_class": {"enum": ["economy", "premium_economy", "business", "first"]},
                "want_hotel": {"type": "boolean"}, "want_ride": {"type": "boolean"},
                "priority": {"enum": ["cheapest", "fastest", "balanced"]},
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": s.assistant_model, "max_tokens": 400,
                    "system": f"Today is {today:%A %d %B %Y}. You extract flight requests for Quik, a Nigerian travel app.",
                    "tools": [tool], "tool_choice": {"type": "tool", "name": "extract_trip"},
                    "messages": [{"role": "user", "content": text}],
                },
            )
            r.raise_for_status()
            block = next(b for b in r.json()["content"] if b["type"] == "tool_use")
            data = block["input"]
    except Exception:
        log.exception("LLM parse failed; falling back to rules")
        return None
    for k in ("departure_date", "return_date"):
        if data.get(k):
            try:
                data[k] = date.fromisoformat(data[k])
            except ValueError:
                data.pop(k)
    return data


def to_iata(place: str | None) -> tuple[str | None, list[str]]:
    """Returns (chosen IATA, other candidates)."""
    if not place:
        return None, []
    if len(place) == 3 and place.isupper() and airports.get(place):
        return place, []
    cands = airports.resolve_place(place)
    if not cands:
        return None, []
    return cands[0].iata, [c.iata for c in cands[1:]]


def is_yes(text: str) -> bool:
    return bool(YES.search(text))


def dumps(session: dict) -> dict:
    return json.loads(json.dumps(session, default=str))
