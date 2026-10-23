# Quik

Book a flight in minutes — local and international — and add a hotel and an airport driver in the same tap. Talk to it ("fly me to Canada next Friday") and it searches, suggests a pick, and books once you say yes.

## What's in here

```
backend/    FastAPI API (Python 3.11+)
  app/
    providers/   flights (mock + Duffel), hotels, rides, payments (mock + Paystack)
    services/    Quik Pick ranking, booking orchestration, fare alerts, assistant, PDF trip document, email
    routers/     HTTP + WebSocket endpoints
  tests/         end-to-end: search → pick → book → pay → ticket → PDF
frontend/   mobile-first web client (no build step), served by the API
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
| Voice / chat assistant | `POST /api/assistant` | Rule-based offline; Claude-powered if `ANTHROPIC_API_KEY` set |
| Live agents | `WS /api/ws/support` | Minimal relay; swap for Intercom/Freshchat in production |
| Accounts | `POST /api/auth/register`, `/login` | JWT; booking works without an account |

## Going live: what each integration really needs

- **Flights — Duffel.** Set `FLIGHT_PROVIDER=duffel` and `DUFFEL_API_KEY`. Duffel lets you sell without your own IATA accreditation and charges per order. Check its coverage of Nigerian domestic carriers before launch: Air Peace, Ibom Air, Arik and others are often only bookable through local GDS/consolidator deals or the airline directly, so domestic may need a second provider. Amadeus closed its self-service APIs in 2026; it's enterprise-only now.
- **Payments — Paystack.** Set `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY`, and point the Paystack webhook at `/api/payments/paystack/webhook`.
- **Uber / Bolt.** Neither offers open ride-booking APIs in Nigeria (Uber's is partner-gated; Bolt has none public). Quik deep-links into their apps today. In-app booking with shared contacts runs through Quik's own driver network (`quik_driver`), which is also where ride margin comes from.
- **Boarding passes.** Airlines issue these at check-in. Quik emails a trip document with the PNR and QR now; attach real passes when airline check-in APIs are available.
- **Scale-out.** Offers are cached in-process (`app/cache.py`); move to Redis before running more than one worker. Use Postgres via `DATABASE_URL`.

## Secrets

Never commit keys. Real values go in `backend/.env`, which is git-ignored; `.env.example` lists the names only.
