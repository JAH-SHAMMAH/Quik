"""API request/response shapes (provider-neutral)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

Cabin = Literal["economy", "premium_economy", "business", "first"]


class Airport(BaseModel):
    iata: str
    name: str
    city: str
    state: str
    country: str
    country_code: str
    lat: float
    lng: float
    distance_km: float | None = None


# ---------- Flights ----------

class FlightSearch(BaseModel):
    origin: str = Field(min_length=3, max_length=3, examples=["ABV"])
    destination: str = Field(min_length=3, max_length=3, examples=["YYZ"])
    departure_date: date
    return_date: date | None = None
    adults: int = Field(1, ge=1, le=9)
    children: int = Field(0, ge=0, le=8)
    infants: int = Field(0, ge=0, le=4)
    cabin_class: Cabin = "economy"

    @model_validator(mode="after")
    def _check(self):
        self.origin, self.destination = self.origin.upper(), self.destination.upper()
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if self.return_date and self.return_date < self.departure_date:
            raise ValueError("return_date is before departure_date")
        if self.infants > self.adults:
            raise ValueError("each infant needs an adult")
        return self


class Carrier(BaseModel):
    code: str
    name: str


class Segment(BaseModel):
    carrier: Carrier
    flight_number: str
    origin: str
    destination: str
    departing_at: datetime
    arriving_at: datetime
    duration_minutes: int
    aircraft: str | None = None


class Slice(BaseModel):
    origin: str
    destination: str
    duration_minutes: int
    stops: int
    segments: list[Segment]


class FlightOffer(BaseModel):
    id: str
    provider: str
    owner: Carrier  # the airline selling the fare
    slices: list[Slice]
    currency: str
    base_amount: float
    tax_amount: float
    total_amount: float  # airline fare, before Quik's fee
    checked_bags: int = 0
    refundable: bool = False
    changeable: bool = False
    expires_at: datetime | None = None
    tags: list[str] = []  # cheapest, fastest, quik_pick, ...
    score: float | None = None


class QuikPick(BaseModel):
    offer_id: str
    headline: str
    reasons: list[str]


class FlightSearchResult(BaseModel):
    search: FlightSearch
    offers: list[FlightOffer]
    pick: QuikPick | None
    service_fee: float
    currency: str


# ---------- Hotels ----------

class HotelSearch(BaseModel):
    city_iata: str = Field(min_length=3, max_length=3)
    check_in: date
    check_out: date
    guests: int = Field(1, ge=1, le=8)

    @model_validator(mode="after")
    def _check(self):
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        self.city_iata = self.city_iata.upper()
        return self


class HotelOffer(BaseModel):
    id: str
    provider: str
    name: str
    area: str
    stars: int
    guest_rating: float
    nights: int
    price_per_night: float
    total_amount: float
    currency: str
    amenities: list[str]
    distance_to_airport_km: float
    free_cancellation: bool


# ---------- Rides ----------

class Place(BaseModel):
    lat: float
    lng: float
    address: str | None = None


class RideQuoteRequest(BaseModel):
    pickup: Place
    dropoff: Place
    pickup_time: datetime | None = None


class RideQuote(BaseModel):
    provider: Literal["quik_driver", "uber", "bolt"]
    product: str
    eta_minutes: int | None
    estimate_low: float
    estimate_high: float
    currency: str
    in_app_booking: bool  # True = Quik dispatches & shares contacts; False = hand-off deep link
    deeplink: str | None = None
    note: str | None = None


class RideSelection(BaseModel):
    provider: Literal["quik_driver", "uber", "bolt"] = "quik_driver"
    pickup: Place
    dropoff: Place
    pickup_time: datetime | None = None  # default: derived from flight times


# ---------- Bookings ----------

class Passenger(BaseModel):
    type: Literal["adult", "child", "infant"] = "adult"
    title: Literal["mr", "ms", "mrs", "miss", "dr"]
    given_name: str
    family_name: str
    gender: Literal["m", "f"]
    born_on: date
    email: EmailStr | None = None
    phone: str | None = None
    passport_number: str | None = None  # needed for international; never logged or mailed


class CreateBooking(BaseModel):
    flight_offer_id: str
    hotel_offer_id: str | None = None
    ride: RideSelection | None = None
    passengers: list[Passenger] = Field(min_length=1)
    contact_email: EmailStr
    contact_phone: str


class PaymentInit(BaseModel):
    booking_id: str
    reference: str
    amount: float
    currency: str
    checkout_url: str
    provider: str


class BookingOut(BaseModel):
    id: str
    reference: str
    status: str
    bundle: str
    contact_email: str
    flight_offer: dict
    hotel_offer: dict | None
    ride: dict | None
    passengers: list
    currency: str
    fare_amount: float
    hotel_amount: float
    ride_amount: float
    service_fee: float
    total_amount: float
    airline_booking_reference: str | None
    events: list
    created_at: datetime


# ---------- Alerts / assistant ----------

class PriceWatchCreate(BaseModel):
    email: EmailStr
    search: FlightSearch


class AssistantMessage(BaseModel):
    text: str
    origin_hint: str | None = Field(None, description="IATA of nearest airport, from the client's location")
    session: dict = Field(default_factory=dict, description="Opaque state returned by the previous turn")



# ---------- Trains ----------

TrainClass = Literal["standard", "business", "first"]


class Station(BaseModel):
    code: str
    name: str
    city: str
    state: str
    line: str
    lat: float
    lng: float
    distance_km: float | None = None


class TrainSearch(BaseModel):
    origin: str = Field(description="Station code", examples=["IDU"])
    destination: str = Field(examples=["RGS"])
    date: date
    passengers: int = Field(1, ge=1, le=9)

    @model_validator(mode="after")
    def _check(self):
        self.origin, self.destination = self.origin.upper(), self.destination.upper()
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        return self


class TrainFare(BaseModel):
    travel_class: TrainClass
    amount: float  # per passenger
    seats_left: int


class TrainOffer(BaseModel):
    id: str
    provider: str
    operator: str
    line: str
    train_number: str
    origin: str
    destination: str
    departing_at: datetime
    arriving_at: datetime
    duration_minutes: int
    calls_at: list[str]
    fares: list[TrainFare]
    currency: str = "NGN"
    tags: list[str] = []


class TrainSearchResult(BaseModel):
    search: TrainSearch
    offers: list[TrainOffer]
    pick: QuikPick | None


class Coach(BaseModel):
    coach: str
    travel_class: TrainClass
    layout: str  # e.g. "2+2"
    rows: int
    taken: list[str]


class SeatMap(BaseModel):
    offer_id: str
    coaches: list[Coach]


class TrainPassenger(BaseModel):
    full_name: str = Field(min_length=2)
    id_number: str | None = None  # NIN/ID if the operator requires it; never persisted


class CreateTrainBooking(BaseModel):
    offer_id: str
    travel_class: TrainClass
    seats: list[str] = Field(min_length=1, description="Seat ids from the seat map, e.g. 'C2-07A'")
    passengers: list[TrainPassenger] = Field(min_length=1)
    contact_email: EmailStr
    contact_phone: str


# ---------- Restaurants ----------

class MenuItem(BaseModel):
    id: str
    name: str
    description: str
    price: float
    tags: list[str]


class Restaurant(BaseModel):
    id: str
    name: str
    city: str
    area: str
    cuisines: list[str]
    price_level: int = Field(ge=1, le=3)
    rating: float
    lat: float
    lng: float
    opens: str
    closes: str
    deposit_per_guest: float
    menu: list[MenuItem]
    distance_km: float | None = None
    matches: list[str] = []  # menu item ids that match the craving
    slots: list[str] = []  # available times for the requested date
    tags: list[str] = []


class RestaurantSearch(BaseModel):
    craving: str | None = Field(None, examples=["jollof", "suya", "sushi"])
    city: str | None = Field(None, examples=["Abuja"])
    lat: float | None = None
    lng: float | None = None
    date: date
    time: str = Field("19:30", pattern=r"^\d{2}:\d{2}$")
    party_size: int = Field(2, ge=1, le=20)
    budget: Literal["low", "mid", "high"] | None = None


class RestaurantSearchResult(BaseModel):
    search: RestaurantSearch
    restaurants: list[Restaurant]
    pick: QuikPick | None


class PreorderLine(BaseModel):
    item_id: str
    qty: int = Field(1, ge=1, le=20)
    note: str | None = None


class CreateTableBooking(BaseModel):
    restaurant_id: str
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    party_size: int = Field(ge=1, le=20)
    preorder: list[PreorderLine] = []
    pay_preorder_now: bool = False
    contact_name: str
    contact_email: EmailStr
    contact_phone: str
    notes: str | None = None


class ReservationOut(BaseModel):
    id: str
    reference: str
    kind: str
    status: str
    contact_name: str
    details: dict
    currency: str
    amount: float
    service_fee: float
    total_amount: float
    events: list
    created_at: datetime


class AssistantReply(BaseModel):
    reply: str
    intent: str
    mode: Literal["flight", "train", "food"] = "flight"
    session: dict
    search: FlightSearch | None = None
    results: FlightSearchResult | None = None
    train_results: TrainSearchResult | None = None
    restaurant_results: RestaurantSearchResult | None = None
    suggestions: list[str] = []
