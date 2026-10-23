"""Booking orchestration: quote -> pay -> ticket -> ride -> email."""
import logging
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import Session

from .. import cache
from ..config import get_settings
from ..models import Booking, BookingStatus, Notification
from ..providers import rides
from ..providers.flights import get_flight_provider
from ..schemas import CreateBooking, FlightOffer, HotelOffer, Passenger
from . import mailer, tickets
from .recommend import service_fee

log = logging.getLogger("quik.bookings")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_reference() -> str:
    return "QK" + "".join(secrets.choice(_ALPHABET) for _ in range(4))


def _event(b: Booking, kind: str, text: str, **data) -> None:
    b.events = [*b.events, {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "text": text, **data}]
    b.updated_at = datetime.now(timezone.utc)


async def create(req: CreateBooking, session: Session, user_id: str | None) -> Booking:
    offer: FlightOffer | None = cache.offers.get(req.flight_offer_id)
    if not offer:
        raise HTTPException(410, "This fare has expired. Please search again.")

    fresh = await get_flight_provider().refresh(offer)
    if not fresh:
        raise HTTPException(410, "The airline no longer offers this fare. Please search again.")
    if abs(fresh.total_amount - offer.total_amount) > 0.5:
        cache.offers.set(fresh.id, fresh)
        raise HTTPException(409, {"message": "The fare changed", "old": offer.total_amount, "new": fresh.total_amount,
                                  "offer_id": fresh.id})

    search = cache.searches.get(offer.id)
    if search:
        expected = search.adults + search.children + search.infants
        if len(req.passengers) != expected:
            raise HTTPException(422, f"This fare is for {expected} passenger(s)")

    hotel: HotelOffer | None = None
    if req.hotel_offer_id:
        hotel = cache.offers.get(req.hotel_offer_id)
        if not hotel:
            raise HTTPException(410, "The hotel rate has expired. Please search again.")

    ride_amount = rides.price_for(req.ride) if req.ride else 0.0
    s = get_settings()
    fee = service_fee(fresh.total_amount, fresh.currency, s.service_fee_flat_ngn, s.service_fee_percent)
    hotel_amount = hotel.total_amount if hotel else 0.0
    bundle = "flight" + ("_hotel" if hotel else "") + ("_ride" if req.ride else "")

    b = Booking(
        reference=new_reference(), user_id=user_id, contact_email=req.contact_email, contact_phone=req.contact_phone,
        bundle=bundle, flight_offer=fresh.model_dump(mode="json"),
        hotel_offer=hotel.model_dump(mode="json") if hotel else None,
        ride=req.ride.model_dump(mode="json") if req.ride else None,
        passengers=[p.model_dump(mode="json", exclude={"passport_number"}) for p in req.passengers],
        currency=fresh.currency, fare_amount=fresh.total_amount, hotel_amount=hotel_amount,
        ride_amount=ride_amount, service_fee=fee,
        total_amount=round(fresh.total_amount + hotel_amount + ride_amount + fee, 2),
    )
    _event(b, "created", "Trip created — awaiting payment")
    session.add(b)
    session.commit()
    session.refresh(b)
    # Passport numbers stay in memory only until ticketing; they are never persisted.
    cache.offers.set(f"pax:{b.id}", req.passengers)
    return b


async def fulfil(b: Booking, session: Session) -> Booking:
    """Called once payment is verified. Idempotent."""
    if b.status in (BookingStatus.ticketed, BookingStatus.failed):
        return b
    b.status = BookingStatus.paid
    _event(b, "paid", "Payment received")

    offer = FlightOffer(**b.flight_offer)
    passengers: list[Passenger] = cache.offers.get(f"pax:{b.id}") or [Passenger(**p) for p in b.passengers]
    try:
        order = await get_flight_provider().create_order(offer, passengers, b.contact_email, b.contact_phone)
    except Exception as exc:  # paid but not ticketed: needs refund/manual handling
        log.exception("ticketing failed for %s", b.reference)
        b.status = BookingStatus.failed
        _event(b, "ticketing_failed", "The airline could not confirm this ticket. A refund has been queued and an agent will contact you.",
               error=str(exc)[:200])
        session.add(b)
        session.commit()
        return b

    b.airline_order_id, b.airline_booking_reference = order.order_id, order.booking_reference
    b.status = BookingStatus.ticketed
    _event(b, "ticketed", f"Ticket confirmed by {offer.owner.name} · PNR {order.booking_reference}")

    if b.ride:
        from ..schemas import RideSelection
        sel = RideSelection(**b.ride)
        lead = b.passengers[0]
        to_airport = True
        pickup_time = sel.pickup_time or rides.default_pickup_time(b.flight_offer, to_airport)
        b.ride = rides.dispatch(sel, b.reference, pickup_time, f"{lead['given_name']} {lead['family_name']}", b.contact_phone)
        if b.ride.get("driver"):
            d = b.ride["driver"]
            _event(b, "ride_assigned", f"Driver {d['name']} ({d['phone']}) will pick you up at {pickup_time:%H:%M, %a %d %b}")
        else:
            _event(b, "ride_handoff", f"Open {sel.provider.title()} to book your ride — we've pre-filled the trip")

    session.add(b)
    session.commit()
    session.refresh(b)

    pdf = tickets.render(b)
    first = offer.slices[0]
    await mailer.send(
        b.contact_email,
        f"Your Quik trip {b.reference}: {first.origin} → {first.destination}",
        text=(f"You're booked!\n\nQuik reference: {b.reference}\nAirline PNR: {b.airline_booking_reference}\n"
              f"{offer.owner.name} {first.segments[0].flight_number}, departs {first.segments[0].departing_at:%a %d %b %H:%M}\n\n"
              "Your trip document is attached. Check in with the airline using your PNR."),
        attachments=[(f"Quik-{b.reference}.pdf", pdf, "application/pdf")],
    )
    session.add(Notification(email=b.contact_email, kind="ticket_issued", title=f"You're booked · {b.reference}",
                             body=f"{offer.owner.name} confirmed your ticket. PNR {b.airline_booking_reference}.",
                             data={"booking_id": b.id}))
    session.commit()
    cache.offers.set(f"pax:{b.id}", None)
    return b


def apply_schedule_change(b: Booking, session: Session, text: str, new_offer: dict | None = None) -> Booking:
    """Record an airline-initiated change (from a provider webhook) and notify."""
    if new_offer:
        b.flight_offer = new_offer
    _event(b, "schedule_change", text)
    session.add(Notification(email=b.contact_email, kind="schedule_change", title=f"Flight change · {b.reference}",
                             body=text, data={"booking_id": b.id}))
    session.add(b)
    session.commit()
    return b
