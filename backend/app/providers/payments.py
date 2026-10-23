"""Payments. Paystack for NGN cards, bank transfer and USSD; mock for local dev.

Flow: initialize -> traveller pays on Paystack checkout -> Paystack calls our
webhook (signature-verified) -> we verify the transaction server-side -> ticket.
"""
import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import get_settings


@dataclass
class InitResult:
    reference: str
    checkout_url: str


class PaymentProvider(Protocol):
    name: str

    async def initialize(self, email: str, amount: float, currency: str, reference: str, callback_url: str, metadata: dict) -> InitResult: ...

    async def verify(self, reference: str) -> bool: ...

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool: ...


class MockPaymentProvider:
    name = "mock"

    async def initialize(self, email, amount, currency, reference, callback_url, metadata) -> InitResult:
        base = get_settings().public_base_url
        return InitResult(reference=reference, checkout_url=f"{base}/api/payments/mock/checkout/{reference}")

    async def verify(self, reference: str) -> bool:
        return True

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        return True


class PaystackPaymentProvider:
    name = "paystack"

    def __init__(self, secret_key: str, base_url: str):
        self._secret = secret_key
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30, headers={"Authorization": f"Bearer {secret_key}"})

    async def initialize(self, email, amount, currency, reference, callback_url, metadata) -> InitResult:
        r = await self._client.post("/transaction/initialize", json={
            "email": email,
            "amount": int(round(amount * 100)),  # kobo
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata,
        })
        r.raise_for_status()
        d = r.json()["data"]
        return InitResult(reference=d["reference"], checkout_url=d["authorization_url"])

    async def verify(self, reference: str) -> bool:
        r = await self._client.get(f"/transaction/verify/{reference}")
        r.raise_for_status()
        return r.json()["data"]["status"] == "success"

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        if not signature:
            return False
        expected = hmac.new(self._secret.encode(), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)


_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.payment_provider == "paystack":
            if not s.paystack_secret_key:
                raise RuntimeError("PAYMENT_PROVIDER=paystack but PAYSTACK_SECRET_KEY is not set")
            _provider = PaystackPaymentProvider(s.paystack_secret_key, s.paystack_base_url)
        else:
            _provider = MockPaymentProvider()
    return _provider
