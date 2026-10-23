"""Trains: search -> seat map -> hold -> pay -> ticket. Restaurants: craving -> pick -> table + pre-order -> pay."""
from datetime import date, timedelta


import pytest

DAY = date.today() + timedelta(days=5)




def _free_seats(seatmap, cls, n):
    from app.providers.trains import seat_ids
    for c in seatmap["coaches"]:
        if c["travel_class"] == cls:
            free = [s for s in seat_ids(c["coach"], c["layout"], c["rows"]) if s not in c["taken"]]
            if len(free) >= n:
                return free[:n]
    raise AssertionError("no free seats")


def test_nearest_station(client):
    st = client.get("/api/stations", params={"lat": 9.06, "lng": 7.46}).json()
    assert st[0]["city"] == "Abuja"


def test_train_flow(client):
    res = client.post("/api/trains/search", json={"origin": "IDU", "destination": "RGS", "date": DAY.isoformat(), "passengers": 2}).json()
    assert res["offers"] and res["pick"]
    offer = next(o for o in res["offers"] if o["id"] == res["pick"]["offer_id"])
    assert offer["calls_at"] == ["KBW", "JER", "RJN", "KKU"]

    smap = client.get(f"/api/trains/{offer['id']}/seats").json()
    seats = _free_seats(smap, "standard", 2)
    body = {"offer_id": offer["id"], "travel_class": "standard", "seats": seats,
            "passengers": [{"full_name": "Ada Obi"}, {"full_name": "Chidi Obi"}],
            "contact_email": "ada@example.com", "contact_phone": "+2348000000000"}
    r = client.post("/api/trains/bookings", json=body)
    assert r.status_code == 201, r.text
    rsv, token = r.json()["reservation"], r.json()["token"]

    # the same seats can't be sold twice
    assert client.post("/api/trains/bookings", json=body).status_code == 409
    taken = client.get(f"/api/trains/{offer['id']}/seats").json()
    assert set(seats) <= {s for c in taken["coaches"] for s in c["taken"]}

    pay = client.post(f"/api/reservations/{rsv['id']}/pay", params={"token": token}).json()
    client.post(f"/api/payments/mock/complete/{pay['reference']}", follow_redirects=False)
    done = client.get(f"/api/reservations/{rsv['id']}", params={"token": token}).json()
    assert done["status"] == "ticketed" and len(done["details"]["ticket_numbers"]) == 2
    pdf = client.get(f"/api/reservations/{rsv['id']}/document", params={"token": token})
    assert pdf.content[:4] == b"%PDF"


def test_no_train_across_lines(client):
    res = client.post("/api/trains/search", json={"origin": "IDU", "destination": "MNY", "date": DAY.isoformat()}).json()
    assert res["offers"] == []


def test_restaurant_flow(client):
    res = client.post("/api/restaurants/search", json={"craving": "I'm hungry, I want jollof", "city": "Abuja",
                                                      "date": DAY.isoformat(), "time": "19:30", "party_size": 2}).json()
    assert res["restaurants"] and res["pick"]
    best = res["restaurants"][0]
    assert best["matches"], "pick should serve the craving"
    assert any("jollof" in it["name"].lower() for it in best["menu"] if it["id"] in best["matches"])

    # book the pick with a pre-order paid now
    slot = best["slots"][0]
    item = best["matches"][0]
    r = client.post("/api/restaurants/bookings", json={
        "restaurant_id": best["id"], "date": DAY.isoformat(), "time": slot, "party_size": 2,
        "preorder": [{"item_id": item, "qty": 2}], "pay_preorder_now": True,
        "contact_name": "Ada Obi", "contact_email": "ada@example.com", "contact_phone": "+2348000000000"})
    assert r.status_code == 201, r.text
    rsv, token = r.json()["reservation"], r.json()["token"]
    price = next(it["price"] for it in best["menu"] if it["id"] == item)
    assert rsv["total_amount"] == best["deposit_per_guest"] * 2 + price * 2
    if rsv["total_amount"]:
        pay = client.post(f"/api/reservations/{rsv['id']}/pay", params={"token": token}).json()
        client.post(f"/api/payments/mock/complete/{pay['reference']}", follow_redirects=False)
    done = client.get(f"/api/reservations/{rsv['id']}", params={"token": token}).json()
    assert done["status"] == "ticketed"
    assert any(e["kind"] == "preorder_sent" for e in done["events"])


def test_free_table_confirms_instantly(client):
    res = client.post("/api/restaurants/search", json={"craving": "suya", "city": "Abuja", "date": DAY.isoformat(),
                                                      "time": "20:00", "party_size": 3}).json()
    free = next(r for r in res["restaurants"] if r["deposit_per_guest"] == 0 and r["slots"])
    r = client.post("/api/restaurants/bookings", json={
        "restaurant_id": free["id"], "date": DAY.isoformat(), "time": free["slots"][0], "party_size": 3,
        "contact_name": "Ada", "contact_email": "ada@example.com", "contact_phone": "+2348000000000"}).json()
    assert r["reservation"]["status"] == "ticketed" and r["reservation"]["total_amount"] == 0


def test_lookup_finds_reservations(client):
    res = client.post("/api/restaurants/search", json={"craving": "suya", "city": "Abuja", "date": DAY.isoformat(),
                                                      "time": "20:00", "party_size": 2}).json()
    free = next(r for r in res["restaurants"] if r["deposit_per_guest"] == 0 and r["slots"])
    made = client.post("/api/restaurants/bookings", json={
        "restaurant_id": free["id"], "date": DAY.isoformat(), "time": free["slots"][0], "party_size": 2,
        "contact_name": "Ada", "contact_email": "ada@example.com", "contact_phone": "+2348000000000"}).json()
    found = client.post("/api/bookings/lookup", json={"reference": made["reservation"]["reference"], "email": "ADA@example.com"}).json()
    assert found["kind"] == "restaurant"


def test_assistant_train(client):
    r = client.post("/api/assistant", json={"text": "Book a train from Abuja to Kaduna on Saturday for 2 people"}).json()
    assert r["mode"] == "train" and r["intent"] == "train_suggested", r
    assert r["train_results"]["search"]["passengers"] == 2
    r2 = client.post("/api/assistant", json={"text": "yes", "session": r["session"]}).json()
    assert r2["intent"] == "confirm_train"


def test_assistant_food_then_flight(client):
    r = client.post("/api/assistant", json={"text": "I'm hungry, I want suya in Jabi for 4 at 8pm"}).json()
    assert r["mode"] == "food" and r["intent"] == "table_suggested", r
    assert r["restaurant_results"]["search"]["party_size"] == 4
    assert r["session"]["pick_restaurant_id"]
    # switching topic keeps working in the same conversation
    r2 = client.post("/api/assistant", json={"text": "also fly me to Lagos tomorrow", "session": r["session"], "origin_hint": "ABV"}).json()
    assert r2["mode"] == "flight" and r2["intent"] == "offer_suggested"
    assert r2["session"]["pick_restaurant_id"] == r["session"]["pick_restaurant_id"]


def test_assistant_asks_what_to_eat(client):
    r = client.post("/api/assistant", json={"text": "I'm starving"}).json()
    assert r["mode"] == "food" and r["intent"] == "need_craving"
    r2 = client.post("/api/assistant", json={"text": "pepper soup", "session": r["session"]}).json()
    assert r2["intent"] == "table_suggested"
