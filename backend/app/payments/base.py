"""The PaymentProvider interface. Card and bank details never reach our servers:

every provider stores only a provider customer id, a provider method id, and
display details (kind, brand, last four, expiry). FakeProvider (app.payments.fake_provider)
is the default and is deterministic. StripeProvider (app.payments.stripe_provider) talks to
Stripe in test mode.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class MethodDetails:
    provider_customer_id: str
    provider_method_id: str
    kind: str
    brand: str | None
    last4: str
    exp_month: int | None
    exp_year: int | None
    # FakeProvider only; ignored by StripeProvider
    fake_behavior: str = "succeed"
    # True for a Stripe SetupIntent not yet confirmed; the webhook fills in
    # the real method details once setup_intent.succeeded arrives
    pending: bool = False
    # Only set by StripeProvider, for the frontend's Payment Element
    client_secret: str | None = None


@dataclass
class ChargeResult:
    status: str  # succeeded, failed, requires_action, processing
    provider_payment_id: str | None
    failure_reason: str | None = None


@dataclass
class RefundResult:
    status: str  # succeeded, failed
    provider_refund_id: str | None
    failure_reason: str | None = None


class SignatureVerificationError(Exception):
    pass


class PaymentProvider(Protocol):
    name: str

    def setup_payment_method(
        self, billing_account_id: str, email: str, kind: str, fake_token: str | None = None
    ) -> MethodDetails: ...

    def charge(
        self,
        method: MethodDetails,
        amount_cents: int,
        idempotency_key: str,
    ) -> ChargeResult: ...

    def refund(self, provider_payment_id: str, amount_cents: int) -> RefundResult: ...

    def verify_webhook(self, payload: bytes, signature_header: str) -> dict: ...
