"""Hotel provider. Mock today; plug Duffel Stays, Hotelbeds or direct hotel deals in behind the same interface."""
import hashlib
import random
from typing import Protocol

from .. import airports
from ..schemas import HotelOffer, HotelSearch

AREAS = {
    "ABV": ["Maitama", "Wuse II", "Asokoro", "Central Area", "Jabi"],
    "LOS": ["Victoria Island", "Ikoyi", "Ikeja GRA", "Lekki Phase 1"],
    "PHC": ["GRA Phase 2", "Trans Amadi", "Old GRA"],
}
NAMES = ["Grand Meridian", "Palm Court", "The Harbour", "Skyline Suites", "Crescent House",
         "Baobab Lodge", "Emerald Towers", "Westbridge", "The Residency", "Atlantic View"]
AMENITIES = ["Free Wi-Fi", "Airport shuttle", "Pool", "Gym", "Breakfast included", "24h power", "Spa", "Restaurant"]


class HotelProvider(Protocol):
    name: str

    async def search(self, s: HotelSearch) -> list[HotelOffer]: ...


class MockHotelProvider:
    name = "mock"

    async def search(self, s: HotelSearch) -> list[HotelOffer]:
        rng = random.Random(int(hashlib.sha256(f"{s.city_iata}{s.check_in}".encode()).hexdigest(), 16))
        ap = airports.get(s.city_iata)
        city = ap.city if ap else s.city_iata
        domestic = bool(ap and ap.country_code == "NG")
        areas = AREAS.get(s.city_iata, ["City Centre", "Downtown", "Airport District", "Old Town"])
        nights = (s.check_out - s.check_in).days
        out = []
        for i, name in enumerate(rng.sample(NAMES, 6)):
            stars = rng.choice([3, 3, 4, 4, 4, 5])
            base = (28_000 if domestic else 95_000) * (1 + (stars - 3) * 0.55) * rng.uniform(0.8, 1.3)
            ppn = round(base * (1 + 0.15 * (s.guests - 1)) / 500) * 500
            out.append(HotelOffer(
                id=f"htl_mock_{s.city_iata}_{s.check_in:%Y%m%d}_{i}",
                provider=self.name, name=f"{name} {city}", area=rng.choice(areas), stars=stars,
                guest_rating=round(rng.uniform(7.2, 9.6), 1), nights=nights, price_per_night=ppn,
                total_amount=ppn * nights, currency="NGN", amenities=rng.sample(AMENITIES, 4),
                distance_to_airport_km=round(rng.uniform(4, 38), 1), free_cancellation=rng.random() < 0.6,
            ))
        return sorted(out, key=lambda h: h.total_amount)


def get_hotel_provider() -> HotelProvider:
    return MockHotelProvider()
