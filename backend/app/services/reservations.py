"""Train tickets and restaurant tables: create -> pay (if anything is due) -> confirm -> email."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from .. import cache
from ..config import get_settings
from ..models import BookingStatus, Notification, Reservation, TrainSeat
from ..providers import restaurants as rest
from ..providers.trains import get_train_provider, seat_ids
from ..schemas import CreateTableBooking, CreateTrainBooking, TrainOffer
from . import mailer, tickets
from .bookings import new_reference

log = logging.getLogger("quik.reservations")
SEAT_HOLD = timedelta(minutes=15)


def _event(r: Reservation, kind: str, text: str) -> None:
    r.events = [*r.events, {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "text": text}]
    r.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------- trains

def release_expired_holds(session: Session) -> None:
    cutoff = datetime.now(timezone.utc) - SEAT_HOLD
    stale = session.exec(select(Reservation.id).where(
        Reservation.kind == "train", Reservation.status == BookingStatus.pending_payment,
        Reservation.created_at < cutoff)).all()
    if stale:
        session.exec(delete(TrainSeat).where(TrainSeat.reservation_id.in_(stale)))
        for r in session.exec(select(Reservation).where(Reservation.id.in_(stale))).all():
            r.status = BookingStatus.cancelled
            _event(r, "expired", "Seat hold expired before payment")
            session.add(r)
        session.commit()


def sold_seats(session: Session, offer_id: str) -> set[str]:
    release_expired_holds(session)
    return set(session.exec(select(TrainSeat.seat).where(TrainSeat.offer_id == offer_id)).all())


def seat_map(session: Session, offer_id: str):
    offer: TrainOffer | None = cache.offers.get(offer_id)
    if not offer:
        raise HTTPException(410, "This train is no longer available. Please search again.")
    return get_train_provider().seat_map(offer, sold_seats(session, offer_id))


def create_train(req: CreateTrainBooking, session: Session, user_id: str | None) -> Reservation:
    offer: TrainOffer | None = cache.offers.get(req.offer_id)
    if not offer:
        raise HTTPException(410, "This train is no longer available. Please search again.")
    if len(req.seats) != len(req.passengers):
        raise HTTPException(422, "Pick one seat per passenger")
    if len(set(req.seats)) != len(req.seats):
        raise HTTPException(422, "Each passenger needs a different seat")
    smap = seat_map(session, req.offer_id)
    by_seat = {}
    for c in smap.coaches:
        for sid in seat_ids(c.coach, c.layout, c.rows):
            by_seat[sid] = (c.travel_class, sid in c.taken)
    for sid in req.seats:
        if sid not in by_seat:
            raise HTTPException(422, f"Seat {sid} doesn't exist on this train")
        cls, taken = by_seat[sid]
        if cls != req.travel_class:
            raise HTTPException(422, f"Seat {sid} is in {cls}, not {req.travel_class}")
        if taken:
            raise HTTPException(409, f"Seat {sid} was just taken. Pick another.")

    fare = next(f for f in offer.fares if f.travel_class == req.travel_class)
    amount = fare.amount * len(req.passengers)
    fee = float(get_settings().train_booking_fee_ngn)
    r = Reservation(
        reference=new_reference(), kind="train", user_id=user_id,
        contact_name=req.passengers[0].full_name, contact_email=req.contact_email, contact_phone=req.contact_phone,
        details={"offer": offer.model_dump(mode="json"), "travel_class": req.travel_class, "seats": req.seats,
                 "passengers": [{"full_name": p.full_name} for p in req.passengers], "fare_per_passenger": fare.amount},
        amount=amount, service_fee=fee, total_amount=amount + fee,
    )
    _event(r, "created", f"Seats {', '.join(req.seats)} held for 15 minutes — awaiting payment")
    session.add(r)
    session.flush()
    try:
        for sid in req.seats:
            session.add(TrainSeat(offer_id=offer.id, seat=sid, reservation_id=r.id))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "One of those seats was just taken. Pick another.") from None
    session.refresh(r)
    return r


# ---------------------------------------------------------------- restaurants

def create_table(req: CreateTableBooking, session: Session, user_id: str | None) -> Reservation:
    venue = rest.get(req.restaurant_id)
    if not venue:
        raise HTTPException(404, "Restaurant not found")
    free = rest.slots(venue, req.date, req.time, req.party_size)
    if req.time not in free:
        raise HTTPException(409, {"message": f"{req.time} is no longer free", "free": free})
    menu = {m.id: m for m in venue.menu}
    lines = []
    for line in req.preorder:
        item = menu.get(line.item_id)
        if not item:
            raise HTTPException(422, f"{line.item_id} isn't on {venue.name}'s menu")
        lines.append({"item_id": item.id, "name": item.name, "qty": line.qty, "price": item.price,
                      "subtotal": item.price * line.qty, "note": line.note})
    preorder_total = sum(l["subtotal"] for l in lines)
    deposit = venue.deposit_per_guest * req.party_size
    due = deposit + (preorder_total if req.pay_preorder_now else 0)

    r = Reservation(
        reference=new_reference(), kind="restaurant", user_id=user_id,
        contact_name=req.contact_name, contact_email=req.contact_email, contact_phone=req.contact_phone,
        details={"restaurant": venue.model_dump(mode="json", exclude={"menu", "matches", "slots", "tags"}),
                 "date": req.date.isoformat(), "time": req.time, "party_size": req.party_size,
                 "preorder": lines, "preorder_total": preorder_total, "preorder_paid": req.pay_preorder_now,
                 "deposit": deposit, "notes": req.notes,
                 "commission_percent": get_settings().restaurant_commission_percent},
        amount=due, service_fee=0, total_amount=due,  # guests pay no Quik fee; restaurants pay commission
    )
    _event(r, "created", f"Table for {req.party_size} at {req.time} requested")
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ---------------------------------------------------------------- shared

async def confirm(r: Reservation, session: Session) -> Reservation:
    """Payment verified (or nothing was due). Idempotent."""
    if r.status in (BookingStatus.ticketed, BookingStatus.failed, BookingStatus.cancelled):
        return r
    if r.total_amount:
        _event(r, "paid", "Payment received")
    d = dict(r.details)
    if r.kind == "train":
        offer = TrainOffer(**d["offer"])
        issued = get_train_provider().issue(offer, d["seats"], r.reference)
        d["ticket_numbers"] = issued.ticket_numbers
        r.details = d
        _event(r, "ticketed", f"Tickets issued: {', '.join(issued.ticket_numbers)}. Show the QR at the gate.")
        subject = f"Your train tickets {r.reference}: {offer.train_number} {offer.departing_at:%a %d %b %H:%M}"
        body = (f"Train {offer.train_number} ({offer.line}) departs {offer.departing_at:%H:%M} on {offer.departing_at:%a %d %b}.\n"
                f"Seats: {', '.join(d['seats'])} ({d['travel_class']}).\nArrive at the station 30 minutes early with a valid ID.")
    else:
        v = d["restaurant"]
        _event(r, "ticketed", f"{v['name']} confirmed your table for {d['party_size']} at {d['time']}")
        if d["preorder"]:
            _event(r, "preorder_sent", f"Your pre-order ({len(d['preorder'])} item{'s' if len(d['preorder']) > 1 else ''}) was sent to the kitchen")
        subject = f"Table booked {r.reference}: {v['name']}, {d['time']}"
        body = (f"{v['name']}, {v['area']}, {v['city']}\n{d['date']} at {d['time']} for {d['party_size']}.\n"
                + (f"Deposit paid: ₦{d['deposit']:,.0f} (taken off your bill).\n" if d["deposit"] else "")
                + ("Pre-order: " + ", ".join(f"{l['qty']}× {l['name']}" for l in d["preorder"]) + "\n" if d["preorder"] else ""))
    r.status = BookingStatus.ticketed
    session.add(r)
    session.add(Notification(email=r.contact_email, kind="ticket_issued", title=subject, body=body.splitlines()[0],
                             data={"reservation_id": r.id}))
    session.commit()
    session.refresh(r)
    await mailer.send(r.contact_email, subject, body,
                      attachments=[(f"Quik-{r.reference}.pdf", tickets.render_reservation(r), "application/pdf")])
    return r
