"""Flight providers.

`MockFlightProvider` produces realistic, deterministic offers so the whole product
works offline. `DuffelFlightProvider` talks to Duffel (search, re-price, ticket).
Both return the same provider-neutral `FlightOffer` shape.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

import httpx

from .. import airports
from ..config import get_settings
from ..schemas import Carrier, FlightOffer, FlightSearch, Passenger, Segment, Slice


@dataclass
class OrderResult:
    order_id: str
    booking_reference: str  # airline PNR


class FlightProvider(Protocol):
    name: str

    async def search(self, search: FlightSearch) -> list[FlightOffer]: ...

    async def refresh(self, offer: FlightOffer) -> FlightOffer | None:
        """Re-price an offer right before payment. None = no longer available."""

    async def create_order(self, offer: FlightOffer, passengers: list[Passenger], email: str, phone: str) -> OrderResult: ...


# --------------------------------------------------------------------------- mock

DOMESTIC = [
    Carrier(code="P4", name="Air Peace"),
    Carrier(code="QI", name="Ibom Air"),
    Carrier(code="W3", name="Arik Air"),
    Carrier(code="VK", name="ValueJet"),
    Carrier(code="OF", name="Overland Airways"),
]
# (carrier, hub IATA) for one-stop international itineraries
HUB_CARRIERS = [
    (Carrier(code="ET", name="Ethiopian Airlines"), "ADD"),
    (Carrier(code="EK", name="Emirates"), "DXB"),
    (Carrier(code="QR", name="Qatar Airways"), "DOH"),
    (Carrier(code="TK", name="Turkish Airlines"), "IST"),
    (Carrier(code="KL", name="KLM"), "AMS"),
    (Carrier(code="AF", name="Air France"), "CDG"),
    (Carrier(code="BA", name="British Airways"), "LHR"),
    (Carrier(code="KQ", name="Kenya Airways"), "NBO"),
    (Carrier(code="WB", name="RwandAir"), "KGL"),
]
# Nonstop routes worth modelling (either direction)
DIRECT = {
    frozenset({"LOS", "LHR"}): Carrier(code="BA", name="British Airways"),
    frozenset({"ABV", "LHR"}): Carrier(code="BA", name="British Airways"),
    frozenset({"LOS", "LGW"}): Carrier(code="P4", name="Air Peace"),
    frozenset({"LOS", "ATL"}): Carrier(code="DL", name="Delta Air Lines"),
    frozenset({"LOS", "DXB"}): Carrier(code="EK", name="Emirates"),
    frozenset({"LOS", "ACC"}): Carrier(code="AW", name="Africa World Airlines"),
    frozenset({"ABV", "ACC"}): Carrier(code="P4", name="Air Peace"),
    frozenset({"LOS", "JNB"}): Carrier(code="P4", name="Air Peace"),
    frozenset({"LOS", "IAH"}): Carrier(code="UA", name="United Airlines"),
}
CABIN_MULT = {"economy": 1.0, "premium_economy": 1.6, "business": 3.2, "first": 5.0}
CARRIER_PRICE_BIAS = {"ET": 0.88, "KQ": 0.9, "WB": 0.86, "TK": 0.93, "EK": 1.08, "QR": 1.05,
                      "BA": 1.15, "KL": 1.06, "AF": 1.04, "DL": 1.1, "UA": 1.08, "P4": 0.95,
                      "QI": 1.08, "W3": 1.0, "VK": 0.9, "OF": 0.97, "AW": 1.0}


def _flight_minutes(a: str, b: str) -> int:
    pa, pb = airports.get(a), airports.get(b)
    if not pa or not pb:
        return 120
    km = airports.haversine_km(pa.lat, pa.lng, pb.lat, pb.lng)
    return int(km / 820 * 60 + 35)


def _is_domestic(o: str, d: str) -> bool:
    pa, pb = airports.get(o), airports.get(d)
    return bool(pa and pb and pa.country_code == pb.country_code)


class MockFlightProvider:
    name = "mock"

    async def search(self, s: FlightSearch) -> list[FlightOffer]:
        # Deterministic per route/date, with a small hourly drift so price alerts fire in demos.
        drift_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        seed = int(hashlib.sha256(f"{s.origin}{s.destination}{s.departure_date}{s.return_date}{s.cabin_class}".encode()).hexdigest(), 16)
        rng = random.Random(seed)
        drift = 1 + (int(hashlib.md5(f"{seed}{drift_key}".encode()).hexdigest(), 16) % 1200 - 600) / 10_000

        itineraries = self._itineraries(s.origin, s.destination, rng)
        offers = []
        for i, (owner, legs) in enumerate(itineraries):
            out = self._slice(legs, s.departure_date, rng)
            slices = [out]
            if s.return_date:
                back_legs = [(c, b, a) for (c, a, b) in reversed(legs)]
                slices.append(self._slice(back_legs, s.return_date, rng))
            km = sum(_flight_minutes(a, b) for (_, a, b) in legs) / 60 * 820
            domestic = _is_domestic(s.origin, s.destination)
            per_pax = (62_000 + km * 115) if domestic else (180_000 + km * 155)
            per_pax *= CARRIER_PRICE_BIAS.get(owner.code, 1.0) * CABIN_MULT[s.cabin_class] * rng.uniform(0.85, 1.2) * drift
            if s.return_date:
                per_pax *= 1.75
            if out.stops == 0 and not domestic:
                per_pax *= 1.12  # nonstop premium
            pax_units = s.adults + s.children * 0.75 + s.infants * 0.1
            total = round(per_pax * pax_units / 100) * 100
            tax = round(total * (0.12 if domestic else 0.28) / 100) * 100
            offers.append(FlightOffer(
                id=f"off_mock_{seed % 10**8:08d}_{i}",
                provider=self.name,
                owner=owner,
                slices=slices,
                currency="NGN",
                base_amount=total - tax,
                tax_amount=tax,
                total_amount=total,
                checked_bags=rng.choice([1, 1, 2]) if not domestic else rng.choice([0, 1]),
                refundable=rng.random() < 0.25,
                changeable=rng.random() < 0.6,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            ))
        return offers

    def _itineraries(self, o: str, d: str, rng: random.Random):
        if _is_domestic(o, d):
            pool = rng.sample(DOMESTIC, k=min(len(DOMESTIC), rng.randint(3, 5)))
            out = [(c, [(c, o, d)]) for c in pool]
            out += [(c, [(c, o, d)]) for c in rng.sample(pool, k=min(2, len(pool)))]  # extra departure times
            return out
        result = []
        direct = DIRECT.get(frozenset({o, d}))
        if direct:
            result.append((direct, [(direct, o, d)]))
        for carrier, hub in HUB_CARRIERS:
            if hub in (o, d):
                result.append((carrier, [(carrier, o, d)]))
                continue
            # skip silly detours (hub much further than going straight)
            if _flight_minutes(o, hub) + _flight_minutes(hub, d) > _flight_minutes(o, d) * 1.7:
                continue
            result.append((carrier, [(carrier, o, hub), (carrier, hub, d)]))
        rng.shuffle(result)
        return result[:8]

    def _slice(self, legs, day: date, rng: random.Random) -> Slice:
        dep = datetime.combine(day, time(rng.choice([6, 7, 8, 9, 11, 13, 15, 17, 19, 21, 22]), rng.choice([0, 15, 30, 45])), tzinfo=timezone.utc)
        segs, t = [], dep
        for idx, (c, a, b) in enumerate(legs):
            if idx:
                t += timedelta(minutes=rng.randint(75, 300))  # layover
            mins = _flight_minutes(a, b)
            segs.append(Segment(carrier=c, flight_number=f"{c.code}{rng.randint(100, 989)}", origin=a, destination=b,
                                departing_at=t, arriving_at=t + timedelta(minutes=mins), duration_minutes=mins,
                                aircraft=rng.choice(["Boeing 737-800", "Embraer E195", "Airbus A330", "Boeing 787-9", "Airbus A350", "Boeing 777-300ER"])))
            t += timedelta(minutes=mins)
        total = int((segs[-1].arriving_at - segs[0].departing_at).total_seconds() // 60)
        return Slice(origin=legs[0][1], destination=legs[-1][2], duration_minutes=total, stops=len(segs) - 1, segments=segs)

    async def refresh(self, offer: FlightOffer) -> FlightOffer | None:
        return offer if not offer.expires_at or offer.expires_at > datetime.now(timezone.utc) else None

    async def create_order(self, offer, passengers, email, phone) -> OrderResult:
        h = hashlib.sha1(f"{offer.id}{email}".encode()).hexdigest().upper()
        return OrderResult(order_id=f"ord_mock_{h[:12]}", booking_reference=h[:6])


# --------------------------------------------------------------------------- Duffel

class DuffelFlightProvider:
    """Duffel Flights API (v2). Docs: https://duffel.com/docs/api"""

    name = "duffel"

    def __init__(self, api_key: str, base_url: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=40,
            headers={"Authorization": f"Bearer {api_key}", "Duffel-Version": "v2", "Accept": "application/json"},
        )

    async def search(self, s: FlightSearch) -> list[FlightOffer]:
        slices = [{"origin": s.origin, "destination": s.destination, "departure_date": s.departure_date.isoformat()}]
        if s.return_date:
            slices.append({"origin": s.destination, "destination": s.origin, "departure_date": s.return_date.isoformat()})
        passengers = [{"type": "adult"}] * s.adults + [{"age": 8}] * s.children + [{"age": 1}] * s.infants
        r = await self._client.post(
            "/air/offer_requests",
            params={"return_offers": "true", "supplier_timeout": 20000},
            json={"data": {"slices": slices, "passengers": passengers, "cabin_class": s.cabin_class}},
        )
        r.raise_for_status()
        return [self._map(o) for o in r.json()["data"].get("offers", [])]

    async def refresh(self, offer: FlightOffer) -> FlightOffer | None:
        r = await self._client.get(f"/air/offers/{offer.id}", params={"return_available_services": "false"})
        if r.status_code in (404, 422):
            return None
        r.raise_for_status()
        return self._map(r.json()["data"])

    async def create_order(self, offer, passengers, email, phone) -> OrderResult:
        # Fetch passenger ids Duffel assigned to this offer, then fill them in order.
        r = await self._client.get(f"/air/offers/{offer.id}")
        r.raise_for_status()
        pax_ids = [p["id"] for p in r.json()["data"]["passengers"]]
        pax = []
        for pid, p in zip(pax_ids, passengers, strict=False):
            entry = {
                "id": pid, "title": p.title, "given_name": p.given_name, "family_name": p.family_name,
                "gender": p.gender, "born_on": p.born_on.isoformat(),
                "email": p.email or email, "phone_number": p.phone or phone,
            }
            if p.passport_number:
                entry["identity_documents"] = [{"type": "passport", "unique_identifier": p.passport_number}]
            pax.append(entry)
        body = {"data": {
            "type": "instant",
            "selected_offers": [offer.id],
            "passengers": pax,
            "payments": [{"type": "balance", "currency": offer.currency, "amount": f"{offer.total_amount:.2f}"}],
        }}
        r = await self._client.post("/air/orders", json=body)
        r.raise_for_status()
        d = r.json()["data"]
        return OrderResult(order_id=d["id"], booking_reference=d["booking_reference"])

    @staticmethod
    def _map(o: dict) -> FlightOffer:
        def mins(iso: str | None) -> int:
            # ISO-8601 duration like PT7H25M or P1DT2H
            if not iso:
                return 0
            days = hours = m = 0
            num = ""
            for ch in iso:
                if ch.isdigit():
                    num += ch
                elif ch == "D":
                    days, num = int(num), ""
                elif ch == "H":
                    hours, num = int(num), ""
                elif ch == "M":
                    m, num = int(num), ""
            return days * 1440 + hours * 60 + m

        slices = []
        for sl in o["slices"]:
            segs = [Segment(
                carrier=Carrier(code=sg["marketing_carrier"]["iata_code"], name=sg["marketing_carrier"]["name"]),
                flight_number=f'{sg["marketing_carrier"]["iata_code"]}{sg["marketing_carrier_flight_number"]}',
                origin=sg["origin"]["iata_code"], destination=sg["destination"]["iata_code"],
                departing_at=datetime.fromisoformat(sg["departing_at"]).replace(tzinfo=timezone.utc),
                arriving_at=datetime.fromisoformat(sg["arriving_at"]).replace(tzinfo=timezone.utc),
                duration_minutes=mins(sg.get("duration")),
                aircraft=(sg.get("aircraft") or {}).get("name"),
            ) for sg in sl["segments"]]
            slices.append(Slice(origin=sl["origin"]["iata_code"], destination=sl["destination"]["iata_code"],
                                duration_minutes=mins(sl.get("duration")), stops=len(segs) - 1, segments=segs))
        bags = 0
        try:
            bags = sum(b["quantity"] for b in o["slices"][0]["segments"][0]["passengers"][0]["baggages"] if b["type"] == "checked")
        except (KeyError, IndexError):
            pass
        cond = o.get("conditions") or {}
        total = float(o["total_amount"])
        tax = float(o.get("tax_amount") or 0)
        return FlightOffer(
            id=o["id"], provider="duffel",
            owner=Carrier(code=o["owner"]["iata_code"], name=o["owner"]["name"]),
            slices=slices, currency=o["total_currency"],
            base_amount=float(o.get("base_amount") or total - tax), tax_amount=tax, total_amount=total,
            checked_bags=bags,
            refundable=bool((cond.get("refund_before_departure") or {}).get("allowed")),
            changeable=bool((cond.get("change_before_departure") or {}).get("allowed")),
            expires_at=datetime.fromisoformat(o["expires_at"].replace("Z", "+00:00")) if o.get("expires_at") else None,
        )


_provider: FlightProvider | None = None


def get_flight_provider() -> FlightProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.flight_provider == "duffel":
            if not s.duffel_api_key:
                raise RuntimeError("FLIGHT_PROVIDER=duffel but DUFFEL_API_KEY is not set")
            _provider = DuffelFlightProvider(s.duffel_api_key, s.duffel_base_url)
        else:
            _provider = MockFlightProvider()
    return _provider
