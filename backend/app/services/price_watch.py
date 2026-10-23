"""Fare tracking: re-search watched routes on a schedule and alert on drops."""
import asyncio
import logging
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from ..config import get_settings
from ..db import engine
from ..models import Notification, PriceWatch
from ..providers.flights import get_flight_provider
from ..schemas import FlightSearch
from . import mailer

log = logging.getLogger("quik.pricewatch")


async def check_once(session: Session) -> int:
    """Returns how many alerts were sent."""
    s = get_settings()
    alerts = 0
    for w in session.exec(select(PriceWatch).where(PriceWatch.active == True)).all():  # noqa: E712
        search = FlightSearch(**w.search)
        if search.departure_date < date.today():
            w.active = False
            session.add(w)
            continue
        try:
            offers = await get_flight_provider().search(search)
        except Exception:
            log.exception("price watch search failed for %s", w.id)
            continue
        if not offers:
            continue
        price = min(o.total_amount for o in offers)
        w.last_checked_at = datetime.now(timezone.utc)
        if w.lowest_price and price < w.lowest_price * (1 - s.price_drop_threshold_percent / 100):
            drop = w.lowest_price - price
            title = f"Price drop: {search.origin} → {search.destination}"
            body = f"Fares fell by ₦{drop:,.0f} to ₦{price:,.0f} for {search.departure_date:%a %d %b}. Book before it rises."
            session.add(Notification(email=w.email, kind="price_drop", title=title, body=body,
                                     data={"search": w.search, "price": price, "previous": w.lowest_price}))
            await mailer.send(w.email, title, body)
            alerts += 1
        w.last_price = price
        w.lowest_price = min(price, w.lowest_price or price)
        session.add(w)
    session.commit()
    return alerts


async def run_forever(stop: asyncio.Event) -> None:
    interval = get_settings().price_watch_interval_seconds
    while not stop.is_set():
        try:
            with Session(engine) as session:
                n = await check_once(session)
                if n:
                    log.info("sent %d price alerts", n)
        except Exception:
            log.exception("price watch loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
