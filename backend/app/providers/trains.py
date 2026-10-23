"""Trains.

Nigeria's corridors sell e-tickets through concessioned ticketing operators, none
of which publish a booking API today. `MockTrainProvider` models the real lines,
stations, classes and seat maps so the product works end to end; when an operator
deal is signed, write an adapter with the same three methods (search, seat_map, issue).
For international rail later (UK/Europe), Trainline's partner API fits the same shape.

Timetables and fares below are illustrative samples, not official NRC data.
"""
import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from .. import airports
from ..schemas import Coach, SeatMap, Station, TrainFare, TrainOffer, TrainSearch

LAGOS = timezone(timedelta(hours=1))

# (code, name, city, state, lat, lng, minutes from line start)
LINES = {
    "Abuja–Kaduna": {
        "short": "AKTS",
        "fares": {"standard": 6_500, "business": 9_500, "first": 12_000},
        "departures": ["07:00", "10:45", "14:00", "17:30"],
        "stations": [
            ("IDU", "Idu Station", "Abuja", "FCT", 9.0436, 7.3620, 0),
            ("KBW", "Kubwa Station", "Abuja", "FCT", 9.1531, 7.3223, 14),
            ("JER", "Jere Station", "Jere", "Kaduna", 9.5491, 7.4259, 48),
            ("RJN", "Rijana Station", "Rijana", "Kaduna", 10.1550, 7.4010, 85),
            ("KKU", "Kakau Station", "Kakau", "Kaduna", 10.3920, 7.3880, 105),
            ("RGS", "Rigasa Station", "Kaduna", "Kaduna", 10.5370, 7.3760, 125),
        ],
    },
    "Lagos–Ibadan": {
        "short": "LIRP",
        "fares": {"standard": 6_000, "business": 8_000, "first": 10_000},
        "departures": ["08:00", "12:30", "16:00"],
        "stations": [
            ("EBM", "Mobolaji Johnson Station, Ebute Metta", "Lagos", "Lagos", 6.4905, 3.3795, 0),
            ("AGG", "Babatunde Raji Fashola Station, Agege", "Lagos", "Lagos", 6.6260, 3.3230, 18),
            ("AGB", "Lateef Jakande Station, Agbado", "Lagos", "Ogun", 6.6800, 3.2680, 27),
            ("ABK", "Professor Wole Soyinka Station, Abeokuta", "Abeokuta", "Ogun", 7.1250, 3.3600, 70),
            ("MNY", "Obafemi Awolowo Station, Moniya", "Ibadan", "Oyo", 7.5330, 3.9070, 140),
        ],
    },
    "Warri–Itakpe": {
        "short": "WIR",
        "fares": {"standard": 4_500, "business": 6_500, "first": 8_500},
        "departures": ["09:00"],
        "stations": [
            ("UJV", "Ujevwu Station, Warri", "Warri", "Delta", 5.5340, 5.7800, 0),
            ("AGR", "Agbor Station", "Agbor", "Delta", 6.2520, 6.1940, 90),
            ("URM", "Uromi Station", "Uromi", "Edo", 6.7000, 6.3300, 150),
            ("AJK", "Ajaokuta Station", "Ajaokuta", "Kogi", 7.5600, 6.6540, 250),
            ("ITK", "Itakpe Station", "Itakpe", "Kogi", 7.6200, 6.3100, 290),
        ],
    },
    "Port Harcourt–Aba": {
        "short": "PHA",
        "fares": {"standard": 3_500, "business": 5_000, "first": 6_500},
        "departures": ["07:00", "16:00"],
        "stations": [
            ("PHR", "Port Harcourt Station", "Port Harcourt", "Rivers", 4.7800, 7.0100, 0),
            ("ABA", "Aba Station", "Aba", "Abia", 5.1100, 7.3700, 75),
        ],
    },
}

# coach id, class, layout, rows
CONSIST = [("F1", "first", "2+1", 10), ("B1", "business", "2+2", 14),
           ("C1", "standard", "2+3", 18), ("C2", "standard", "2+3", 18), ("C3", "standard", "2+3", 18)]
LETTERS = {"2+1": "ABD", "2+2": "ABCD", "2+3": "ABCDE"}


def _stations() -> list[tuple[str, Station, int]]:
    out = []
    for line, spec in LINES.items():
        for code, name, city, state, lat, lng, mins in spec["stations"]:
            out.append((line, Station(code=code, name=name, city=city, state=state, line=line, lat=lat, lng=lng), mins))
    return out


def all_stations(lat: float | None = None, lng: float | None = None, q: str | None = None) -> list[Station]:
    st = [s for _, s, _ in _stations()]
    if q:
        ql = q.lower()
        st = [s for s in st if ql in s.code.lower() or ql in s.city.lower() or ql in s.name.lower() or ql in s.line.lower()]
    if lat is not None and lng is not None:
        st = [s.model_copy(update={"distance_km": round(airports.haversine_km(lat, lng, s.lat, s.lng), 1)}) for s in st]
        st.sort(key=lambda s: s.distance_km)
    return st


def station(code: str) -> Station | None:
    return next((s for _, s, _ in _stations() if s.code == code.upper()), None)


def stations_in_city(city: str) -> list[Station]:
    c = city.lower()
    return [s for _, s, _ in _stations() if s.city.lower() == c]


def seat_ids(coach: str, layout: str, rows: int) -> list[str]:
    return [f"{coach}-{r:02d}{l}" for r in range(1, rows + 1) for l in LETTERS[layout]]


@dataclass
class IssuedTicket:
    ticket_numbers: list[str]


class TrainProvider(Protocol):
    name: str

    def search(self, s: TrainSearch) -> list[TrainOffer]: ...

    def seat_map(self, offer: TrainOffer, sold: set[str]) -> SeatMap: ...

    def issue(self, offer: TrainOffer, seats: list[str], reference: str) -> IssuedTicket: ...


class MockTrainProvider:
    name = "mock"

    def search(self, s: TrainSearch) -> list[TrainOffer]:
        line_o = next(((l, m) for l, st, m in _stations() if st.code == s.origin), None)
        line_d = next(((l, m) for l, st, m in _stations() if st.code == s.destination), None)
        if not line_o or not line_d or line_o[0] != line_d[0]:
            return []  # different lines: no through train
        line, spec = line_o[0], LINES[line_o[0]]
        m_o, m_d = line_o[1], line_d[1]
        forward = m_d > m_o
        full = spec["stations"][-1][6]
        span = abs(m_d - m_o)
        calls = [c for c, *_, m in spec["stations"] if min(m_o, m_d) < m < max(m_o, m_d)]
        if not forward:
            calls.reverse()
        frac = max(0.4, span / full)
        offers = []
        for i, dep in enumerate(spec["departures"]):
            hh, mm = map(int, dep.split(":"))
            # trains leave each terminus at the same times; intermediate stations offset by running time
            start_offset = m_o if forward else (full - m_o)
            departs = datetime.combine(s.date, time(hh, mm), tzinfo=LAGOS) + timedelta(minutes=start_offset)
            arrives = departs + timedelta(minutes=span + 3 * len(calls))
            rng = random.Random(int(hashlib.md5(f"{line}{s.date}{dep}{forward}".encode()).hexdigest(), 16))
            fares = []
            for cls, base in spec["fares"].items():
                capacity = sum(len(LETTERS[lay]) * rows for _, c, lay, rows in CONSIST if c == cls)
                left = max(0, int(capacity * rng.uniform(0.05, 0.6)))
                fares.append(TrainFare(travel_class=cls, amount=round(base * frac / 100) * 100, seats_left=left))
            num = f"{spec['short']}{(2 * i + (1 if forward else 2)):02d}"
            offers.append(TrainOffer(
                id=f"trn_{spec['short']}_{s.date:%Y%m%d}_{dep.replace(':', '')}_{s.origin}{s.destination}",
                provider=self.name, operator="Nigerian Railway Corporation", line=line, train_number=num,
                origin=s.origin, destination=s.destination, departing_at=departs, arriving_at=arrives,
                duration_minutes=int((arrives - departs).total_seconds() // 60), calls_at=calls, fares=fares,
            ))
        now = datetime.now(LAGOS) + timedelta(minutes=30)  # sales close 30 min before departure
        return [o for o in offers if o.departing_at > now]

    def seat_map(self, offer: TrainOffer, sold: set[str]) -> SeatMap:
        rng = random.Random(int(hashlib.md5(offer.id.encode()).hexdigest(), 16))
        left = {f.travel_class: f.seats_left for f in offer.fares}
        coaches = []
        for coach, cls, layout, rows in CONSIST:
            ids = seat_ids(coach, layout, rows)
            per_coach_free = left[cls] // sum(1 for c in CONSIST if c[1] == cls)
            free = set(rng.sample(ids, k=min(len(ids), per_coach_free)))
            taken = sorted((set(ids) - free) | (sold & set(ids)))
            coaches.append(Coach(coach=coach, travel_class=cls, layout=layout, rows=rows, taken=taken))
        return SeatMap(offer_id=offer.id, coaches=coaches)

    def issue(self, offer: TrainOffer, seats: list[str], reference: str) -> IssuedTicket:
        h = hashlib.sha1(f"{offer.id}{reference}".encode()).hexdigest().upper()
        return IssuedTicket(ticket_numbers=[f"NRC{h[:6]}{i + 1:02d}" for i in range(len(seats))])


def get_train_provider() -> TrainProvider:
    return MockTrainProvider()
