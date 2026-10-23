"""Trains and restaurants."""
import hmac
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

from .. import cache
from ..auth import optional_user
from ..config import get_settings
from ..db import get_session
from ..models import BookingStatus, Reservation, User
from ..providers import restaurants as rest
from ..providers import trains
from ..providers.payments import get_payment_provider
from ..providers.restaurants import get_restaurant_provider
from ..providers.trains import get_train_provider
from ..schemas import (CreateTableBooking, CreateTrainBooking, PaymentInit, ReservationOut, Restaurant,
                       RestaurantSearch, RestaurantSearchResult, SeatMap, Station, TrainSearch, TrainSearchResult)
from ..services import reservations as svc
from ..services import tickets
from ..services.recommend import rank_restaurants, rank_trains
from .bookings import trip_token

router = APIRouter(prefix="/api", tags=["trains & restaurants"])


def _out(r: Reservation) -> dict:
    return {"reservation": ReservationOut.model_validate(r, from_attributes=True), "token": trip_token(r.id)}


def _load(rid: str, token: str | None, session: Session, user: User | None) -> Reservation:
    r = session.get(Reservation, rid)
    ok = r and ((user and r.user_id == user.id) or (token and hmac.compare_digest(token, trip_token(r.id))))
    if not ok:
        raise HTTPException(404, "Reservation not found")
    return r


# ---------------------------------------------------------------- trains

@router.get("/stations", response_model=list[Station])
def stations(q: str | None = None, lat: float | None = Query(None, ge=-90, le=90),
             lng: float | None = Query(None, ge=-180, le=180)):
    return trains.all_stations(lat=lat, lng=lng, q=q)


def run_train_search(search: TrainSearch) -> TrainSearchResult:
    if not trains.station(search.origin) or not trains.station(search.destination):
        raise HTTPException(422, "Unknown station")
    offers = get_train_provider().search(search)
    for o in offers:
        cache.offers.set(o.id, o)
    offers, pick = rank_trains(offers)
    return TrainSearchResult(search=search, offers=offers, pick=pick)


@router.post("/trains/search", response_model=TrainSearchResult)
def search_trains(search: TrainSearch):
    """Trains between two stations on the same line, with live seat counts per class."""
    return run_train_search(search)


@router.get("/trains/{offer_id}/seats", response_model=SeatMap)
def train_seats(offer_id: str, session: Session = Depends(get_session)):
    return svc.seat_map(session, offer_id)


@router.post("/trains/bookings", status_code=201)
def book_train(req: CreateTrainBooking, session: Session = Depends(get_session),
               user: User | None = Depends(optional_user)):
    """Holds the chosen seats for 15 minutes while the traveller pays."""
    return _out(svc.create_train(req, session, user.id if user else None))


# ---------------------------------------------------------------- restaurants

def run_restaurant_search(search: RestaurantSearch) -> RestaurantSearchResult:
    found = get_restaurant_provider().search(search)
    ranked, pick = rank_restaurants(found, search)
    return RestaurantSearchResult(search=search, restaurants=ranked, pick=pick)


@router.post("/restaurants/search", response_model=RestaurantSearchResult)
def search_restaurants(search: RestaurantSearch):
    """Tell us what you're craving; get the best places that serve it, with free tables."""
    return run_restaurant_search(search)


@router.get("/restaurants/{restaurant_id}", response_model=Restaurant)
def restaurant(restaurant_id: str, date: str, time: str = "19:30", party_size: int = Query(2, ge=1, le=20)):
    r = rest.get(restaurant_id)
    if not r:
        raise HTTPException(404, "Restaurant not found")
    r.slots = rest.slots(r, Date.fromisoformat(date), time, party_size)
    return r


@router.post("/restaurants/bookings", status_code=201)
async def book_table(req: CreateTableBooking, session: Session = Depends(get_session),
                     user: User | None = Depends(optional_user)):
    """Book a table and optionally pre-order. If nothing is due, it's confirmed straight away."""
    r = svc.create_table(req, session, user.id if user else None)
    if r.total_amount == 0:
        r = await svc.confirm(r, session)
    return _out(r)


# ---------------------------------------------------------------- shared

@router.get("/reservations/{rid}", response_model=ReservationOut)
def get_reservation(rid: str, token: str | None = None, session: Session = Depends(get_session),
                    user: User | None = Depends(optional_user)):
    return _load(rid, token, session, user)


@router.post("/reservations/{rid}/pay", response_model=PaymentInit)
async def pay_reservation(rid: str, token: str | None = None, session: Session = Depends(get_session),
                          user: User | None = Depends(optional_user)):
    r = _load(rid, token, session, user)
    if r.status != BookingStatus.pending_payment:
        raise HTTPException(409, f"Reservation is {r.status.value}")
    s, provider = get_settings(), get_payment_provider()
    init = await provider.initialize(
        email=r.contact_email, amount=r.total_amount, currency=r.currency,
        reference=r.payment_reference or f"{r.reference}-{r.id[-6:]}",
        callback_url=f"{s.public_base_url}/api/payments/callback",
        metadata={"reservation_id": r.id, "reference": r.reference, "kind": r.kind},
    )
    r.payment_reference = init.reference
    session.add(r)
    session.commit()
    return PaymentInit(booking_id=r.id, reference=init.reference, amount=r.total_amount, currency=r.currency,
                       checkout_url=init.checkout_url, provider=provider.name)


@router.get("/reservations/{rid}/document")
def reservation_document(rid: str, token: str | None = None, session: Session = Depends(get_session),
                         user: User | None = Depends(optional_user)):
    r = _load(rid, token, session, user)
    if r.status != BookingStatus.ticketed:
        raise HTTPException(409, "Your ticket is ready once the booking is confirmed")
    return Response(tickets.render_reservation(r), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Quik-{r.reference}.pdf"'})
