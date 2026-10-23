import os

os.environ["DATABASE_URL"] = "sqlite:///./test_quik.db"
os.environ["PRICE_WATCH_INTERVAL_SECONDS"] = "3600"
if os.path.exists("test_quik.db"):
    os.remove("test_quik.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    os.remove("test_quik.db")
