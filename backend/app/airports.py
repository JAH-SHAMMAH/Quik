"""Airport directory + "airports near me".

Ships with a curated list (all major Nigerian airports + key international hubs).
Swap `_load()` for a full OurAirports import when you need global coverage.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

from .schemas import Airport

_DATA = Path(__file__).parent / "data" / "airports.json"


@lru_cache
def _load() -> list[Airport]:
    return [Airport(**a) for a in json.loads(_DATA.read_text(encoding="utf-8"))]


def all_airports() -> list[Airport]:
    return list(_load())


def get(iata: str) -> Airport | None:
    iata = iata.upper()
    return next((a for a in _load() if a.iata == iata), None)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search(
    q: str | None = None,
    country: str | None = None,
    state: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    limit: int = 10,
) -> list[Airport]:
    results = _load()
    if country:
        c = country.lower()
        results = [a for a in results if c in (a.country.lower(), a.country_code.lower())]
    if state:
        s = state.lower()
        results = [a for a in results if a.state.lower() == s]
    if q:
        ql = q.lower()
        results = [
            a for a in results
            if ql in a.iata.lower() or ql in a.city.lower() or ql in a.name.lower() or ql in a.country.lower()
        ]
    if lat is not None and lng is not None:
        results = [a.model_copy(update={"distance_km": round(haversine_km(lat, lng, a.lat, a.lng), 1)}) for a in results]
        results.sort(key=lambda a: a.distance_km or 0)
    return results[:limit]


def resolve_place(text: str) -> list[Airport]:
    """Map a free-text place ("Canada", "London", "LOS") to candidate airports."""
    t = text.strip().lower()
    by_code = [a for a in _load() if a.iata.lower() == t]
    if by_code:
        return by_code
    by_city = [a for a in _load() if a.city.lower() == t]
    if by_city:
        return by_city
    by_state = [a for a in _load() if a.state.lower() == t]
    if by_state:
        return by_state
    return [a for a in _load() if a.country.lower() == t or a.country_code.lower() == t]
