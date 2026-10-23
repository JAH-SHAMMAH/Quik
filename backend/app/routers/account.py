"""Accounts, fare alerts and notifications."""
import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

from ..auth import current_user, hash_password, issue_token, verify_password
from ..config import get_settings
from ..db import get_session
from ..models import Booking, Notification, PriceWatch, User
from ..schemas import PriceWatchCreate
from ..services import price_watch
from .bookings import trip_token

router = APIRouter(prefix="/api", tags=["account"])


class Register(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2)
    phone: str | None = None
    password: str = Field(min_length=8)


class Login(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/register", status_code=201)
def register(body: Register, session: Session = Depends(get_session)):
    if session.exec(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=body.email.lower(), full_name=body.full_name, phone=body.phone,
                password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    return {"token": issue_token(user), "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@router.post("/auth/login")
def login(body: Login, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": issue_token(user), "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@router.post("/price-watches", status_code=201)
async def create_watch(body: PriceWatchCreate, session: Session = Depends(get_session)):
    """Track a route+date. We re-check on a schedule and email when the fare drops."""
    w = PriceWatch(email=body.email, search=body.search.model_dump(mode="json"))
    session.add(w)
    session.commit()
    await price_watch.check_once(session)  # record the starting price right away
    session.refresh(w)
    return {"id": w.id, "starting_price": w.last_price, "currency": w.currency}


@router.delete("/price-watches/{watch_id}", status_code=204)
def stop_watch(watch_id: str, email: EmailStr, session: Session = Depends(get_session)):
    w = session.get(PriceWatch, watch_id)
    if not w or w.email.lower() != email.lower():
        raise HTTPException(404)
    w.active = False
    session.add(w)
    session.commit()


@router.post("/price-watches/run", include_in_schema=False)
async def run_watches(session: Session = Depends(get_session)):
    if get_settings().environment == "prod":
        raise HTTPException(404)
    return {"alerts_sent": await price_watch.check_once(session)}


@router.get("/notifications")
def notifications(trip: str | None = None, token: str | None = None, session: Session = Depends(get_session)):
    """Notifications for the traveller who owns `trip` (authorised by its trip token)."""
    b = session.get(Booking, trip) if trip else None
    if not b or not token or not hmac.compare_digest(token, trip_token(b.id)):
        raise HTTPException(404)
    rows = session.exec(select(Notification).where(Notification.email == b.contact_email)
                        .order_by(Notification.created_at.desc()).limit(50)).all()
    return rows


@router.get("/me/notifications")
def my_notifications(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return session.exec(select(Notification).where(Notification.email == user.email)
                        .order_by(Notification.created_at.desc()).limit(50)).all()
