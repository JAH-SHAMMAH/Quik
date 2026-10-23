"""Search endpoints: airports, flights, hotels, rides."""
import asyncio

from fastapi import APIRouter, HTTPException, Query

from .. import airports, cache
from ..config import get_settings
from ..providers import rides
from ..providers.flights import get_flight_provider
from ..providers.hotels import get_hotel_provider
from ..schemas import (Airport, FlightSearch, FlightSearchResult, HotelOffer, HotelSearch, RideQuote,
                       RideQuoteRequest)
from ..services.recommend import rank, service_fee

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/airports", response_model=list[Airport])
def list_airports(
    q: str | None = None,
    country: str | None = None,
    state: str | None = None,
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    limit: int = Query(10, ge=1, le=100),
):
    """Filter by country/state, free text, or sort by distance from the traveller's location."""
    return airports.search(q=q, country=country, state=state, lat=lat, lng=lng, limit=limit)


@router.get("/airports/countries")
def countries():
    out: dict[str, set[str]] = {}
    for a in airports.all_airports():
        out.setdefault(a.country, set()).add(a.state)
    return [{"country": c, "states": sorted(s)} for c, s in sorted(out.items())]


async def run_flight_search(search: FlightSearch) -> FlightSearchResult:
    if not airports.get(search.origin) and get_settings().flight_provider == "mock":
        raise HTTPException(422, f"Unknown airport {search.origin}")
    try:
        offers = await asyncio.wait_for(get_flight_provider().search(search), timeout=45)
    except TimeoutError:
        raise HTTPException(504, "Airlines took too long to respond. Please try again.") from None
    ranked, pick = rank(offers)
    for o in ranked:
        cache.offers.set(o.id, o)
        cache.searches.set(o.id, search)
    s = get_settings()
    best = ranked[0] if ranked else None
    fee = service_fee(best.total_amount, best.currency, s.service_fee_flat_ngn, s.service_fee_percent) if best else 0
    return FlightSearchResult(search=search, offers=ranked, pick=pick, service_fee=fee,
                              currency=best.currency if best else "NGN")


@router.post("/flights/search", response_model=FlightSearchResult)
async def search_flights(search: FlightSearch):
    """Search all connected airlines. Results come ranked with a Quik Pick and reasons."""
    return await run_flight_search(search)


@router.post("/hotels/search", response_model=list[HotelOffer])
async def search_hotels(search: HotelSearch):
    offers = await get_hotel_provider().search(search)
    for o in offers:
        cache.offers.set(o.id, o)
    return offers


@router.post("/rides/quotes", response_model=list[RideQuote])
def ride_quotes(req: RideQuoteRequest):
    return rides.quotes(req)
