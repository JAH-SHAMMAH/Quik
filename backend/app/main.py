"""Quik API — book a flight in minutes, add a hotel and an airport driver."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import account, assistant, bookings, catalog, reservations
from .services import price_watch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = asyncio.Event()
    task = asyncio.create_task(price_watch.run_forever(stop))
    yield
    stop.set()
    await task


settings = get_settings()
app = FastAPI(title="Quik API", version="0.1.0", lifespan=lifespan,
              description="Your booking buddy: flights, trains, restaurants, hotels and airport rides, with payments, alerts and a voice assistant.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

for r in (catalog.router, bookings.router, reservations.router, account.router, assistant.router):
    app.include_router(r)


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "flights": settings.flight_provider, "payments": settings.payment_provider,
            "assistant": "llm" if settings.anthropic_api_key else "rules"}


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="web")
