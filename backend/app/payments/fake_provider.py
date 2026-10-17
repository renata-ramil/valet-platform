"""Deterministic offline payment provider. The default (PAYMENTS_PROVIDER=fake).

A caller picks the simulated behavior explicitly with fake_token: "ok" (default)
succeeds, "decline" always declines, "requires_action" always needs a step the
resident never completes in tests (mirrors 3DS), and "delayed_settle" charges
into "processing" until simulate_settle() is called, mirroring a bank debit
that clears a few days later.
"""

import hashlib
import hmac
import json
import secrets

from app.payments.base import ChargeResult, MethodDetails, RefundResult, SignatureVerificationError

FAKE_TOKEN_TO_BEHAVIOR = {
    "ok": "succeed",
    "decline": "decline",
    "requires_action": "requires_action",
    "delayed_settle": "delayed_settle",
}


class FakeProvider:
    name = "fake"

    def __init__(self, webhook_secret: str = "whsec_fake_dev_secret") -> None:
        self.webhook_secret = webhook_secret

    def setup_payment_method(
        self, billing_account_id: str, email: str, kind: str, fake_token: str | None = None
    ) -> MethodDetails:
        behavior = FAKE_TOKEN_TO_BEHAVIOR.get(fake_token or "ok", "succeed")
        digest = hashlib.sha256(f"{kind}:{fake_token or 'ok'}".encode()).hexdigest()
        return MethodDetails(
            provider_customer_id=f"fake_cus_{billing_account_id}",
            provider_method_id=f"fake_pm_{secrets.token_hex(8)}",
            kind=kind,
            brand="visa" if kind == "card" else None,
            last4=digest[:4],
            exp_month=12 if kind == "card" else None,
            exp_year=2030 if kind == "card" else None,
            fake_behavior=behavior,
        )

    def charge(
        self, method: MethodDetails, amount_cents: int, idempotency_key: str
    ) -> ChargeResult:
        provider_payment_id = f"fake_ch_{idempotency_key}"
        if method.fake_behavior == "decline":
            return ChargeResult(
                status="failed", provider_payment_id=None, failure_reason="card_declined"
            )
        if method.fake_behavior == "requires_action":
            return ChargeResult(status="requires_action", provider_payment_id=provider_payment_id)
        if method.fake_behavior == "delayed_settle":
            return ChargeResult(status="processing", provider_payment_id=provider_payment_id)
        return ChargeResult(status="succeeded", provider_payment_id=provider_payment_id)

    def simulate_settle(self, provider_payment_id: str) -> ChargeResult:
        """Test/worker hook: completes a delayed bank debit that was left processing."""
        return ChargeResult(status="succeeded", provider_payment_id=provider_payment_id)

    def refund(self, provider_payment_id: str, amount_cents: int) -> RefundResult:
        if provider_payment_id is None:
            raise ValueError("Cannot refund a charge that never succeeded")
        return RefundResult(
            status="succeeded", provider_refund_id=f"fake_re_{secrets.token_hex(6)}"
        )

    def verify_webhook(self, payload: bytes, signature_header: str) -> dict:
        expected = (
            "sha256=" + hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        )
        if not signature_header or not hmac.compare_digest(expected, signature_header):
            raise SignatureVerificationError("Fake webhook signature mismatch")
        return json.loads(payload)

    def sign(self, payload: bytes) -> str:
        """Test helper: produces a valid signature header for a given payload."""
        return (
            "sha256=" + hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        )
