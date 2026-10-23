# Quik

Your booking buddy. Flights (local and international) with a hotel and an airport driver, train seats, and restaurant tables with food ready when you arrive. Talk to it — "fly me to Canada next Friday", "train to Kaduna tomorrow, two seats", "I'm hungry, I want pepper soup in Wuse for 4 at 8pm" — and it searches, suggests one pick with reasons, and books once you say yes.

## What's in here

```
backend/    FastAPI API (Python 3.11+)
  app/
    providers/   flights (mock + Duffel), trains, restaurants, hotels, rides, payments (mock + Paystack)
    services/    Quik Pick ranking, bookings + reservations, fare alerts, assistant, PDF tickets, email
  scripts/       build_demo_data.py — regenerates frontend/demo-data.js from the mock providers
    routers/     HTTP + WebSocket endpoints
  tests/         end-to-end: search → pick → book → pay → ticket → PDF
frontend/   mobile-first web client (no build step), served by the API
  app.js       flights, voice, agent chat, shared helpers
  more.js      trains (seat maps) and restaurants (menus, pre-order)
  demo-data.js generated sample data so the page also runs with no backend
```

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set JWT_SECRET; everything else works on mock
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the app and http://localhost:8000/docs for the API. Run tests with `pytest` from `backend/`.

On mock providers the whole flow works offline: fares are realistic sample data, checkout is a test page, and emails land in `backend/outbox/`.

## Features and where they live

| Feature | Endpoint | Notes |
|---|---|---|
| Airports near me / by country & state | `GET /api/airports?lat=&lng=` | Curated Nigerian + hub list in `app/data/airports.json` |
| Flight search + Quik Pick | `POST /api/flights/search` | Ranks on price, time, stops, reliability, flexibility; returns plain-language reasons |
| Hotels | `POST /api/hotels/search` | Mock; plug a supplier into `providers/hotels.py` |
| Airport ride quotes | `POST /api/rides/quotes` | Quik driver (in-app) or Uber/Bolt hand-off |
| Book a trip | `POST /api/bookings` | Re-prices with the airline first; returns a trip token |
| Pay | `POST /api/bookings/{id}/pay` | Paystack checkout; webhook is signature-verified |
| Ticket + trip PDF + email | automatic after payment | `services/bookings.py::fulfil` |
| Schedule changes | `POST /api/webhooks/duffel` | Timeline event + notification |
| Fare alerts | `POST /api/price-watches` | Background job re-checks and emails on drops |
| Train search + Quik Pick | `POST /api/trains/search` | Abuja–Kaduna, Lagos–Ibadan, Warri–Itakpe, Port Harcourt–Aba; seats left per class |
| Seat map + seat hold | `GET /api/trains/{id}/seats`, `POST /api/trains/bookings` | Seats held 15 min while paying; a DB unique key stops double-selling |
| Restaurants by craving | `POST /api/restaurants/search` | Matches dishes on menus ("pepper soup" ≠ pepperoni), free tables, ranked with reasons |
| Table + pre-order | `POST /api/restaurants/bookings` | Deposit and/or food paid now; free tables confirm instantly |
| Train/table tickets | `GET /api/reservations/{id}/document` | PDF with QR, emailed on confirmation |
| Voice / chat assistant | `POST /api/assistant` | Flights, trains and food in one conversation; switches topic as you talk |
| Live agents | `WS /api/ws/support` | Minimal relay; swap for Intercom/Freshchat in production |
| Accounts | `POST /api/auth/register`, `/login` | JWT; booking works without an account |

## Going live: what each integration really needs

- **Flights — Duffel.** Set `FLIGHT_PROVIDER=duffel` and `DUFFEL_API_KEY`. Duffel lets you sell without your own IATA accreditation and charges per order. Check its coverage of Nigerian domestic carriers before launch: Air Peace, Ibom Air, Arik and others are often only bookable through local GDS/consolidator deals or the airline directly, so domestic may need a second provider. Amadeus closed its self-service APIs in 2026; it's enterprise-only now.
- **Payments — Paystack.** Set `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY`, and point the Paystack webhook at `/api/payments/paystack/webhook`.
- **Uber / Bolt.** Neither offers open ride-booking APIs in Nigeria (Uber's is partner-gated; Bolt has none public). Quik deep-links into their apps today. In-app booking with shared contacts runs through Quik's own driver network (`quik_driver`), which is also where ride margin comes from.
- **Trains.** Nigeria's corridors sell e-tickets through concessioned ticketing operators with no public API. Quik models the lines, classes and seat maps now (`providers/trains.py`); real booking needs a reseller deal with the operator for each corridor. For UK/Europe rail later, Trainline's partner API fits the same interface.
- **Restaurants.** Reservation APIs (OpenTable, TheFork, resOS and others) are partner-approved and thin in Nigeria. The practical route is signing restaurants directly: they list menu, hours and tables on Quik and pay a commission per booking (`RESTAURANT_COMMISSION_PERCENT`). Guests pay no Quik fee. The sample venues in `providers/restaurants.py` are invented.
- **Boarding passes.** Airlines issue these at check-in. Quik emails a trip document with the PNR and QR now; attach real passes when airline check-in APIs are available.
- **Scale-out.** Offers are cached in-process (`app/cache.py`); move to Redis before running more than one worker. Use Postgres via `DATABASE_URL`.

## Secrets

Never commit keys. Real values go in `backend/.env`, which is git-ignored; `.env.example` lists the names only.
