"""Airport rides.

Reality check that shapes this module:
- Uber's ride-request API is partner-gated; the public, reliable path is the Uber
  universal deep link (pre-fills pickup/drop-off in the rider's own Uber app).
- Bolt has no public ride-hailing API; business booking is via Bolt's Ride Booker
  and private partnerships.

So Quik offers two kinds of ride:
1. `quik_driver` — Quik's own vetted airport-driver network. Quik dispatches,
   schedules it to the flight, and shares driver <-> traveller contacts. This is
   fully in-app and is where the ride margin comes from.
2. `uber` / `bolt` — hand-off links with a fare estimate. When a partnership with
   either is signed, add an adapter here with `in_app_booking=True`.
"""
import hashlib
import random
from datetime import datetime, timedelta
from urllib.parse import urlencode

from .. import airports
from ..schemas import Place, RideQuote, RideQuoteRequest, RideSelection

DRIVERS = [
    {"name": "Emeka Okafor", "phone": "+2348030000101", "car": "Toyota Corolla 2019 · Silver", "plate": "ABJ-342-KD", "rating": 4.9},
    {"name": "Aisha Bello", "phone": "+2348030000102", "car": "Toyota Camry 2018 · Black", "plate": "ABC-118-FG", "rating": 4.8},
    {"name": "Tunde Adeyemi", "phone": "+2348030000103", "car": "Lexus RX 350 2017 · White", "plate": "LND-901-AA", "rating": 4.9},
    {"name": "Ibrahim Musa", "phone": "+2348030000104", "car": "Honda Accord 2020 · Grey", "plate": "KUJ-554-BC", "rating": 4.7},
]


def _km(a: Place, b: Place) -> float:
    return airports.haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.3  # road factor


def _estimate(km: float, base: float, per_km: float) -> tuple[float, float]:
    mid = base + per_km * km
    return round(mid * 0.85 / 100) * 100, round(mid * 1.2 / 100) * 100


def uber_link(r: RideQuoteRequest | RideSelection) -> str:
    q = {
        "action": "setPickup",
        "pickup[latitude]": r.pickup.lat, "pickup[longitude]": r.pickup.lng,
        "dropoff[latitude]": r.dropoff.lat, "dropoff[longitude]": r.dropoff.lng,
    }
    if r.dropoff.address:
        q["dropoff[nickname]"] = r.dropoff.address
    return "https://m.uber.com/ul/?" + urlencode(q)


def quotes(r: RideQuoteRequest) -> list[RideQuote]:
    km = _km(r.pickup, r.dropoff)
    lo, hi = _estimate(km, 2_500, 480)
    ulo, uhi = _estimate(km, 1_500, 420)
    blo, bhi = _estimate(km, 1_300, 400)
    return [
        RideQuote(provider="quik_driver", product="Quik Airport · Sedan", eta_minutes=None, estimate_low=lo,
                  estimate_high=hi, currency="NGN", in_app_booking=True,
                  note="Fixed price, scheduled to your flight. Driver waits 45 min after landing."),
        RideQuote(provider="uber", product="UberX", eta_minutes=None, estimate_low=ulo, estimate_high=uhi,
                  currency="NGN", in_app_booking=False, deeplink=uber_link(r),
                  note="Opens Uber with pickup and drop-off filled in. Paid in Uber."),
        RideQuote(provider="bolt", product="Bolt", eta_minutes=None, estimate_low=blo, estimate_high=bhi,
                  currency="NGN", in_app_booking=False, deeplink="https://bolt.eu/en/rides/",
                  note="Opens Bolt; confirm the destination there. Paid in Bolt."),
    ]


def price_for(sel: RideSelection) -> float:
    q = next(x for x in quotes(RideQuoteRequest(pickup=sel.pickup, dropoff=sel.dropoff)) if x.provider == sel.provider)
    return q.estimate_high if q.in_app_booking else 0.0  # hand-off rides are paid in the partner app


def default_pickup_time(flight_offer: dict, to_airport: bool) -> datetime:
    """To the airport: 3h before international / 2h before domestic. From: 20 min after landing."""
    first = flight_offer["slices"][0]["segments"][0]
    last = flight_offer["slices"][0]["segments"][-1]
    if to_airport:
        dep = datetime.fromisoformat(str(first["departing_at"]))
        intl = airports.get(first["origin"]) and airports.get(last["destination"]) and \
            airports.get(first["origin"]).country_code != airports.get(last["destination"]).country_code
        return dep - timedelta(hours=3 if intl else 2) - timedelta(minutes=45)
    return datetime.fromisoformat(str(last["arriving_at"])) + timedelta(minutes=20)


def dispatch(sel: RideSelection, booking_ref: str, pickup_time: datetime, traveller_name: str, traveller_phone: str) -> dict:
    """Assign a Quik driver and return the ride record (contacts shared both ways)."""
    if sel.provider != "quik_driver":
        return {
            "provider": sel.provider, "status": "handoff", "pickup": sel.pickup.model_dump(),
            "dropoff": sel.dropoff.model_dump(), "pickup_time": pickup_time.isoformat(),
            "deeplink": uber_link(sel) if sel.provider == "uber" else "https://bolt.eu/en/rides/",
        }
    rng = random.Random(int(hashlib.md5(booking_ref.encode()).hexdigest(), 16))
    driver = rng.choice(DRIVERS)
    return {
        "provider": "quik_driver", "status": "driver_assigned",
        "pickup": sel.pickup.model_dump(), "dropoff": sel.dropoff.model_dump(),
        "pickup_time": pickup_time.isoformat(),
        "driver": driver,
        "shared_with_driver": {"name": traveller_name, "phone": traveller_phone, "booking_reference": booking_ref},
        "price": price_for(sel),
    }
