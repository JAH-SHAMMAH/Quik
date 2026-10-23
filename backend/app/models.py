"""Database tables."""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str):
    return lambda: f"{prefix}_{uuid4().hex[:16]}"


class User(SQLModel, table=True):
    id: str = Field(default_factory=_id("usr"), primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    phone: str | None = None
    password_hash: str
    created_at: datetime = Field(default_factory=_now)


class BookingStatus(str, Enum):
    pending_payment = "pending_payment"
    paid = "paid"
    ticketed = "ticketed"
    failed = "failed"
    cancelled = "cancelled"


class Booking(SQLModel, table=True):
    """One trip: a flight, optionally a hotel and an airport ride."""

    id: str = Field(default_factory=_id("bkg"), primary_key=True)
    reference: str = Field(index=True)  # short code shown to the traveller, e.g. QK7F2A
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    contact_email: str
    contact_phone: str
    status: BookingStatus = BookingStatus.pending_payment

    bundle: str = "flight"  # flight | flight_hotel | flight_hotel_ride | flight_ride
    flight_offer: dict = Field(sa_column=Column(JSON))
    hotel_offer: dict | None = Field(default=None, sa_column=Column(JSON))
    ride: dict | None = Field(default=None, sa_column=Column(JSON))
    passengers: list = Field(sa_column=Column(JSON))

    currency: str = "NGN"
    fare_amount: float
    hotel_amount: float = 0
    ride_amount: float = 0
    service_fee: float
    total_amount: float

    payment_reference: str | None = Field(default=None, index=True)
    airline_order_id: str | None = None
    airline_booking_reference: str | None = None  # PNR from the airline
    events: list = Field(default_factory=list, sa_column=Column(JSON))  # timeline: schedule changes etc.

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PriceWatch(SQLModel, table=True):
    id: str = Field(default_factory=_id("pw"), primary_key=True)
    email: str
    search: dict = Field(sa_column=Column(JSON))  # the FlightSearch payload
    last_price: float | None = None
    lowest_price: float | None = None
    currency: str = "NGN"
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    last_checked_at: datetime | None = None


class Notification(SQLModel, table=True):
    id: str = Field(default_factory=_id("ntf"), primary_key=True)
    email: str = Field(index=True)
    kind: str  # price_drop | schedule_change | ticket_issued | ride_assigned
    title: str
    body: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    read: bool = False
    created_at: datetime = Field(default_factory=_now)


class Reservation(SQLModel, table=True):
    """Train tickets and restaurant tables (flights stay in Booking)."""

    id: str = Field(default_factory=_id("rsv"), primary_key=True)
    reference: str = Field(index=True)
    kind: str = Field(index=True)  # train | restaurant
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    contact_name: str
    contact_email: str
    contact_phone: str
    status: BookingStatus = BookingStatus.pending_payment
    details: dict = Field(sa_column=Column(JSON))
    currency: str = "NGN"
    amount: float  # what the supplier gets (fare, deposit, pre-order)
    service_fee: float
    total_amount: float
    payment_reference: str | None = Field(default=None, index=True)
    events: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TrainSeat(SQLModel, table=True):
    """One row per seat sold or held. (offer_id, seat) is unique, so two people can't get the same seat."""

    offer_id: str = Field(primary_key=True)
    seat: str = Field(primary_key=True)
    reservation_id: str = Field(foreign_key="reservation.id", index=True)
    created_at: datetime = Field(default_factory=_now)
