"""Trip document PDF (e-ticket receipt + hotel + ride + QR).

Note: a real *boarding pass* is issued by the airline at check-in (its barcode is
the airline's BCBP). Quik's document carries the airline PNR so the traveller can
check in; once airline check-in APIs are available we attach the true pass here.
"""
from datetime import datetime
from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from ..models import Booking

INK, MUTED, BRAND, LINE = HexColor("#0E1726"), HexColor("#5B6576"), HexColor("#FF5A1F"), HexColor("#E4E7EC")


def _dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _money(v: float, cur: str) -> str:
    return f"{'₦' if cur == 'NGN' else cur + ' '}{v:,.0f}".replace("₦", "NGN ")  # base fonts lack ₦


def render(b: Booking) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    m = 48

    # header band
    c.setFillColor(INK)
    c.rect(0, h - 110, w, 110, fill=1, stroke=0)
    c.setFillColor(BRAND)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(m, h - 62, "quik")
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica", 10)
    c.drawString(m, h - 82, "Trip document · e-ticket receipt")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(w - m - 90, h - 50, "QUIK REF")
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - m - 90, h - 72, b.reference)
    c.setFont("Helvetica", 9)
    c.drawRightString(w - m - 90, h - 88, f"Airline PNR  {b.airline_booking_reference or 'pending'}")

    qr = QrCodeWidget(f"QUIK:{b.reference}:{b.airline_booking_reference or ''}")
    x1, y1, x2, y2 = qr.getBounds()
    d = Drawing(76, 76, transform=[76 / (x2 - x1), 0, 0, 76 / (y2 - y1), 0, 0])
    d.add(qr)
    c.setFillColor(HexColor("#FFFFFF"))
    c.roundRect(w - m - 80, h - 100, 82, 82, 6, fill=1, stroke=0)
    renderPDF.draw(d, c, w - m - 77, h - 97)

    y = h - 150
    offer = b.flight_offer

    def section(title):
        nonlocal y
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(m, y, title.upper())
        y -= 8
        c.setStrokeColor(LINE)
        c.line(m, y, w - m, y)
        y -= 18

    section(f"Flights · {offer['owner']['name']}")
    for idx, sl in enumerate(offer["slices"]):
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(m, y, f"{'Outbound' if idx == 0 else 'Return'}  {sl['origin']} → {sl['destination']}".replace("→", "-"))
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTED)
        c.drawRightString(w - m, y, f"{sl['stops']} stop(s) · {sl['duration_minutes'] // 60}h {sl['duration_minutes'] % 60:02d}m")
        y -= 18
        for sg in sl["segments"]:
            dep, arr = _dt(sg["departing_at"]), _dt(sg["arriving_at"])
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(m + 10, y, sg["flight_number"])
            c.setFont("Helvetica", 10)
            c.drawString(m + 70, y, f"{sg['origin']} {dep:%a %d %b %H:%M}")
            c.drawString(m + 240, y, f"{sg['destination']} {arr:%a %d %b %H:%M}")
            c.setFillColor(MUTED)
            c.drawString(m + 410, y, (sg.get("aircraft") or "")[:22])
            y -= 15
        y -= 8

    section("Passengers")
    c.setFont("Helvetica", 10)
    for p in b.passengers:
        c.setFillColor(INK)
        c.drawString(m, y, f"{p['title'].upper()} {p['given_name']} {p['family_name']}".strip())
        c.setFillColor(MUTED)
        c.drawRightString(w - m, y, f"{p.get('type', 'adult').title()} · {offer.get('checked_bags', 0)} checked bag(s)")
        y -= 15
    y -= 8

    if b.hotel_offer:
        ho = b.hotel_offer
        section("Hotel")
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(m, y, f"{ho['name']}  ({'*' * ho['stars']})")
        y -= 15
        c.setFont("Helvetica", 10)
        c.setFillColor(MUTED)
        c.drawString(m, y, f"{ho['area']} · {ho['nights']} night(s) · {'Free cancellation' if ho['free_cancellation'] else 'Non-refundable'}")
        y -= 23

    if b.ride:
        r = b.ride
        section("Airport ride")
        c.setFillColor(INK)
        c.setFont("Helvetica", 10)
        c.drawString(m, y, f"Pickup {_dt(r['pickup_time']):%a %d %b, %H:%M} · {r['pickup'].get('address') or 'your location'}")
        y -= 15
        if r.get("driver"):
            dr = r["driver"]
            c.drawString(m, y, f"Driver {dr['name']} · {dr['phone']} · {dr['car']} · {dr['plate']}")
        else:
            c.drawString(m, y, f"Book in the {r['provider'].title()} app: {r.get('deeplink', '')[:70]}")
        y -= 23

    section("Payment")
    rows = [("Airfare", b.fare_amount), ("Hotel", b.hotel_amount), ("Ride", b.ride_amount), ("Quik service fee", b.service_fee)]
    c.setFont("Helvetica", 10)
    for label, val in rows:
        if val:
            c.setFillColor(MUTED)
            c.drawString(m, y, label)
            c.setFillColor(INK)
            c.drawRightString(w - m, y, _money(val, b.currency))
            y -= 15
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m, y - 4, "Total paid")
    c.drawRightString(w - m, y - 4, _money(b.total_amount, b.currency))
    y -= 40

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8.5)
    for line in [
        "Check in with the airline using the PNR above (online check-in usually opens 24 hours before departure).",
        "Your boarding pass is issued by the airline at check-in. Bring a valid ID/passport and any required visas.",
        "Schedule changes are sent to you by email and in the Quik app.",
    ]:
        c.drawString(m, y, line)
        y -= 12
    c.showPage()
    c.save()
    return buf.getvalue()
