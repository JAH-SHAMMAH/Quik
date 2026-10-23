"""Quik Pick: rank offers and explain the suggestion in plain language.

Score (lower is better) blends price, journey time, stops and flexibility. The user
always sees the cheapest and fastest too and confirms the pick themselves.
"""
from ..schemas import FlightOffer, QuikPick

# Rough on-time / reliability priors (0..1). Replace with real OTP data when available.
RELIABILITY = {"ET": 0.86, "EK": 0.9, "QR": 0.9, "TK": 0.84, "KL": 0.85, "AF": 0.82, "BA": 0.8,
               "KQ": 0.78, "WB": 0.84, "DL": 0.86, "UA": 0.82, "P4": 0.72, "QI": 0.82, "W3": 0.68,
               "VK": 0.74, "OF": 0.7, "AW": 0.78}

WEIGHTS = {"price": 0.5, "time": 0.22, "stops": 0.13, "reliability": 0.1, "flex": 0.05}


def _hours(m: int) -> str:
    h, mm = divmod(m, 60)
    return f"{h}h {mm:02d}m" if mm else f"{h}h"


def _money(amount: float, currency: str) -> str:
    sym = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}.get(currency, currency + " ")
    return f"{sym}{amount:,.0f}"


def rank(offers: list[FlightOffer]) -> tuple[list[FlightOffer], QuikPick | None]:
    if not offers:
        return [], None
    prices = [o.total_amount for o in offers]
    times = [sum(s.duration_minutes for s in o.slices) for o in offers]
    pmin, pmax, tmin, tmax = min(prices), max(prices), min(times), max(times)

    def norm(v, lo, hi):
        return 0.0 if hi == lo else (v - lo) / (hi - lo)

    for o, p, t in zip(offers, prices, times, strict=True):
        stops = sum(s.stops for s in o.slices) / max(1, len(o.slices))
        flex = (0.5 if o.changeable else 0) + (0.5 if o.refundable else 0)
        o.score = round(
            WEIGHTS["price"] * norm(p, pmin, pmax)
            + WEIGHTS["time"] * norm(t, tmin, tmax)
            + WEIGHTS["stops"] * min(stops, 2) / 2
            + WEIGHTS["reliability"] * (1 - RELIABILITY.get(o.owner.code, 0.75))
            + WEIGHTS["flex"] * (1 - flex),
            4,
        )
        o.tags = []

    cheapest = min(offers, key=lambda o: o.total_amount)
    fastest = min(offers, key=lambda o: sum(s.duration_minutes for s in o.slices))
    ranked = sorted(offers, key=lambda o: o.score)
    best = ranked[0]
    cheapest.tags.append("cheapest")
    fastest.tags.append("fastest")
    best.tags.append("quik_pick")

    reasons = []
    best_time = sum(s.duration_minutes for s in best.slices)
    if best is cheapest:
        avg = sum(prices) / len(prices)
        reasons.append(f"Lowest fare on this route — {_money(avg - best.total_amount, best.currency)} below the average")
    else:
        diff = best.total_amount - cheapest.total_amount
        saved = sum(s.duration_minutes for s in cheapest.slices) - best_time
        if saved > 30:
            reasons.append(f"Only {_money(diff, best.currency)} more than the cheapest, but {_hours(saved)} quicker")
        else:
            reasons.append(f"{_money(diff, best.currency)} more than the cheapest, with a better schedule and airline record")
    stops = best.slices[0].stops
    reasons.append("Nonstop" if stops == 0 else f"{stops} stop via {best.slices[0].segments[0].destination}")
    if RELIABILITY.get(best.owner.code, 0) >= 0.84:
        reasons.append(f"{best.owner.name} has a strong on-time record")
    if best.checked_bags:
        reasons.append(f"{best.checked_bags} checked bag{'s' if best.checked_bags > 1 else ''} included")
    if best.changeable:
        reasons.append("Changes allowed before departure")

    headline = f"{best.owner.name} · {_money(best.total_amount, best.currency)} · {_hours(best.slices[0].duration_minutes)}"
    return ranked, QuikPick(offer_id=best.id, headline=headline, reasons=reasons[:4])


def service_fee(fare: float, currency: str, flat_ngn: int, percent: float) -> float:
    fee = fare * percent / 100
    if currency == "NGN":
        fee += flat_ngn
    return round(fee, 2)
