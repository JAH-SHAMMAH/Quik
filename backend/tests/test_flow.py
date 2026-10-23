"""End-to-end: search -> pick -> book (flight+hotel+ride) -> pay -> ticket -> PDF."""
from datetime import date, timedelta


import pytest
from app.services.assistant import rule_parse

DEP = date.today() + timedelta(days=21)




def test_nearby_airports(client):
    r = client.get("/api/airports", params={"lat": 9.07, "lng": 7.48, "country": "NG", "limit": 3})
    assert r.status_code == 200
    assert r.json()[0]["iata"] == "ABV"


def test_domestic_search_has_pick(client):
    r = client.post("/api/flights/search", json={"origin": "ABV", "destination": "LOS", "departure_date": DEP.isoformat()})
    body = r.json()
    assert r.status_code == 200, body
    assert body["offers"] and body["pick"]["reasons"]
    assert all(o["slices"][0]["stops"] == 0 for o in body["offers"])
    tags = {t for o in body["offers"] for t in o["tags"]}
    assert {"cheapest", "fastest", "quik_pick"} <= tags


def test_full_trip(client):
    s = client.post("/api/flights/search", json={
        "origin": "ABV", "destination": "YYZ", "departure_date": DEP.isoformat(),
        "return_date": (DEP + timedelta(days=14)).isoformat(), "adults": 1}).json()
    offer_id = s["pick"]["offer_id"]
    hotels = client.post("/api/hotels/search", json={"city_iata": "YYZ", "check_in": DEP.isoformat(),
                                                      "check_out": (DEP + timedelta(days=3)).isoformat()}).json()
    r = client.post("/api/bookings", json={
        "flight_offer_id": offer_id,
        "hotel_offer_id": hotels[0]["id"],
        "ride": {"provider": "quik_driver", "pickup": {"lat": 9.08, "lng": 7.49, "address": "Wuse II"},
                 "dropoff": {"lat": 9.0068, "lng": 7.2632, "address": "ABV"}},
        "passengers": [{"title": "mr", "given_name": "Ada", "family_name": "Obi", "gender": "m",
                        "born_on": "1992-04-10", "passport_number": "A00000000"}],
        "contact_email": "ada@example.com", "contact_phone": "+2348000000000",
    })
    assert r.status_code == 201, r.text
    created = r.json()
    b, token = created["booking"], created["token"]
    assert b["bundle"] == "flight_hotel_ride"
    assert "passport_number" not in b["passengers"][0]
    assert b["total_amount"] == pytest.approx(b["fare_amount"] + b["hotel_amount"] + b["ride_amount"] + b["service_fee"])

    assert client.get(f"/api/bookings/{b['id']}").status_code == 404  # no token, no access
    pay = client.post(f"/api/bookings/{b['id']}/pay", params={"token": token}).json()
    done = client.post(f"/api/payments/mock/complete/{pay['reference']}", follow_redirects=False)
    assert done.status_code == 303

    final = client.get(f"/api/bookings/{b['id']}", params={"token": token}).json()
    assert final["status"] == "ticketed"
    assert final["airline_booking_reference"]
    assert final["ride"]["driver"]["phone"]
    assert final["ride"]["shared_with_driver"]["phone"] == "+2348000000000"

    pdf = client.get(f"/api/bookings/{b['id']}/document", params={"token": token})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"

    notes = client.get("/api/notifications", params={"trip": b["id"], "token": token}).json()
    assert any(n["kind"] == "ticket_issued" for n in notes)


def test_assistant_canada(client):
    r = client.post("/api/assistant", json={"text": "I want to fly to Canada next Friday", "origin_hint": "ABV"}).json()
    assert r["intent"] == "offer_suggested", r
    assert r["search"]["destination"] == "YYZ"
    r2 = client.post("/api/assistant", json={"text": "yes, book it", "session": r["session"]}).json()
    assert r2["intent"] == "confirm_offer"


def test_assistant_asks_for_missing_bits(client):
    r = client.post("/api/assistant", json={"text": "book me a flight"}).json()
    assert r["intent"] == "need_destination"


def test_rule_parse():
    today = date(2026, 10, 23)  # a Friday
    p = rule_parse("Fly me and my wife from Lagos to London on 12 December, back on 2 January, business class", today)
    assert p["origin_place"] == "lagos" and p["destination_place"] == "london"
    assert p["departure_date"] == date(2026, 12, 12) and p["return_date"] == date(2027, 1, 2)
    assert p["adults"] == 2 and p["cabin_class"] == "business"
    assert rule_parse("to Dubai tomorrow for 5 days with a driver", today)["return_date"] == date(2026, 10, 29)


def test_price_watch(client):
    r = client.post("/api/price-watches", json={"email": "ada@example.com", "search": {
        "origin": "LOS", "destination": "LHR", "departure_date": DEP.isoformat()}})
    assert r.status_code == 201 and r.json()["starting_price"] > 0
