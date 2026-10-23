"""Bookings, payments and provider webhooks."""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from ..auth import current_user, optional_user
from ..config import get_settings
from ..db import get_session
from ..models import Booking, BookingStatus, User
from ..providers.payments import get_payment_provider
from ..schemas import BookingOut, CreateBooking, PaymentInit
from ..services import bookings as svc
from ..services import tickets

log = logging.getLogger("quik.api")
router = APIRouter(prefix="/api", tags=["bookings"])


def trip_token(booking_id: str) -> str:
    """Unguessable per-trip token so links never carry the traveller's email."""
    return hmac.new(get_settings().jwt_secret.encode(), booking_id.encode(), hashlib.sha256).hexdigest()[:32]


def _load(booking_id: str, session: Session, user: User | None, token: str | None) -> Booking:
    b = session.get(Booking, booking_id)
    allowed = b and ((user and b.user_id == user.id) or (token and hmac.compare_digest(token, trip_token(b.id))))
    if not allowed:
        raise HTTPException(404, "Booking not found")
    return b


@router.post("/bookings", status_code=201)
async def create_booking(req: CreateBooking, session: Session = Depends(get_session),
                         user: User | None = Depends(optional_user)):
    """Locks in the fare (re-priced with the airline) and returns the trip total to pay,
    plus a trip token the client uses for follow-up calls."""
    b = await svc.create(req, session, user.id if user else None)
    return {"booking": BookingOut.model_validate(b, from_attributes=True), "token": trip_token(b.id)}


@router.get("/bookings", response_model=list[BookingOut])
def my_bookings(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return session.exec(select(Booking).where(Booking.user_id == user.id).order_by(Booking.created_at.desc())).all()


class Lookup(BaseModel):
    reference: str
    email: EmailStr


@router.post("/bookings/lookup")
def lookup(body: Lookup, session: Session = Depends(get_session)):
    """Find a trip by Quik reference + contact email (no account needed)."""
    b = session.exec(select(Booking).where(Booking.reference == body.reference.upper())).first()
    if not b or b.contact_email.lower() != body.email.lower():
        raise HTTPException(404, "Booking not found")
    return {"booking": BookingOut.model_validate(b, from_attributes=True), "token": trip_token(b.id)}


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: str, token: str | None = None, session: Session = Depends(get_session),
                user: User | None = Depends(optional_user)):
    return _load(booking_id, session, user, token)


@router.get("/bookings/{booking_id}/document")
def booking_document(booking_id: str, token: str | None = None, session: Session = Depends(get_session),
                     user: User | None = Depends(optional_user)):
    b = _load(booking_id, session, user, token)
    if b.status != BookingStatus.ticketed:
        raise HTTPException(409, "Your trip document is ready once the ticket is confirmed")
    return Response(tickets.render(b), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Quik-{b.reference}.pdf"'})


@router.post("/bookings/{booking_id}/pay", response_model=PaymentInit)
async def start_payment(booking_id: str, token: str | None = None, session: Session = Depends(get_session),
                        user: User | None = Depends(optional_user)):
    b = _load(booking_id, session, user, token)
    if b.status != BookingStatus.pending_payment:
        raise HTTPException(409, f"Booking is {b.status.value}")
    s = get_settings()
    provider = get_payment_provider()
    pay_ref = b.payment_reference or f"{b.reference}-{b.id[-6:]}"
    init = await provider.initialize(
        email=b.contact_email, amount=b.total_amount, currency=b.currency, reference=pay_ref,
        callback_url=f"{s.public_base_url}/api/payments/callback", metadata={"booking_id": b.id, "reference": b.reference},
    )
    b.payment_reference = init.reference
    session.add(b)
    session.commit()
    return PaymentInit(booking_id=b.id, reference=init.reference, amount=b.total_amount, currency=b.currency,
                       checkout_url=init.checkout_url, provider=provider.name)


async def _settle(pay_ref: str, session: Session) -> Booking | None:
    b = session.exec(select(Booking).where(Booking.payment_reference == pay_ref)).first()
    if not b:
        return None
    if b.status == BookingStatus.pending_payment and await get_payment_provider().verify(pay_ref):
        b = await svc.fulfil(b, session)
    return b


@router.get("/payments/callback")
async def payment_callback(reference: str, session: Session = Depends(get_session)):
    """Where Paystack sends the traveller after checkout."""
    b = await _settle(reference, session)
    if not b:
        raise HTTPException(404, "Unknown payment")
    return RedirectResponse(f"/?trip={b.id}&token={trip_token(b.id)}")


@router.post("/payments/paystack/webhook", include_in_schema=False)
async def paystack_webhook(request: Request, session: Session = Depends(get_session)):
    raw = await request.body()
    if not get_payment_provider().verify_webhook(raw, request.headers.get("x-paystack-signature")):
        raise HTTPException(401, "Bad signature")
    event = json.loads(raw)
    if event.get("event") == "charge.success":
        await _settle(event["data"]["reference"], session)
    return {"ok": True}


@router.get("/payments/mock/checkout/{reference}", response_class=HTMLResponse, include_in_schema=False)
def mock_checkout(reference: str, session: Session = Depends(get_session)):
    if get_settings().payment_provider != "mock":
        raise HTTPException(404)
    b = session.exec(select(Booking).where(Booking.payment_reference == reference)).first()
    if not b:
        raise HTTPException(404)
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Test checkout</title><body style="font-family:system-ui;max-width:420px;margin:60px auto;padding:0 16px">
<h2>Test checkout</h2><p>{b.reference} · <b>{b.currency} {b.total_amount:,.0f}</b></p>
<p style="color:#666">Dev mode — no real money moves. Set PAYMENT_PROVIDER=paystack for live payments.</p>
<form method=post action="/api/payments/mock/complete/{reference}"><button style="padding:12px 20px;font-size:16px">Pay now</button></form>"""


@router.post("/payments/mock/complete/{reference}", include_in_schema=False)
async def mock_complete(reference: str, session: Session = Depends(get_session)):
    if get_settings().payment_provider != "mock":
        raise HTTPException(404)
    b = await _settle(reference, session)
    if not b:
        raise HTTPException(404)
    return RedirectResponse(f"/?trip={b.id}&token={trip_token(b.id)}", status_code=303)


@router.post("/webhooks/duffel", include_in_schema=False)
async def duffel_webhook(request: Request, session: Session = Depends(get_session)):
    """Airline-initiated schedule changes and cancellations."""
    raw = await request.body()
    secret = get_settings().duffel_webhook_secret
    if secret:
        sig = request.headers.get("x-duffel-signature", "")
        parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
        expected = hmac.new(secret.encode(), f"{parts.get('t', '')}.".encode() + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts.get("v1", "")):
            raise HTTPException(401, "Bad signature")
    event = json.loads(raw)
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    order_id = obj.get("order_id") or obj.get("id")
    b = session.exec(select(Booking).where(Booking.airline_order_id == order_id)).first() if order_id else None
    if b and etype.startswith("order.airline_initiated_change"):
        svc.apply_schedule_change(b, session, "The airline changed your flight schedule. Review the new times in Quik.")
    elif b and etype == "order.cancelled":
        svc.apply_schedule_change(b, session, "The airline cancelled this order. An agent will contact you about options.")
    return {"ok": True}
