"""Stripe test-mode provider.

Written against the documented shapes of the `stripe` Python SDK (SetupIntent
plus the Payment Element, off session PaymentIntents, webhook signature
verification). Never exercised against the live Stripe test API in this
environment: no network egress and no test API keys are available here. See
docs/KNOWN-ISSUES.md. FakeProvider (app.payments.fake_provider) is the
fully exercised default; this class only activates when PAYMENTS_PROVIDER=stripe
and real Stripe test keys are configured.
"""

import stripe

from app.payments.base import (
    ChargeResult,
    MethodDetails,
    RefundResult,
    SignatureVerificationError,
)


class StripeProvider:
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str) -> None:
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        stripe.api_key = secret_key

    def _ensure_customer(self, billing_account_id: str, email: str) -> str:
        existing = stripe.Customer.list(email=email, limit=1)
        if existing.data:
            return existing.data[0].id
        customer = stripe.Customer.create(
            email=email, metadata={"billing_account_id": billing_account_id}
        )
        return customer.id

    def setup_payment_method(
        self, billing_account_id: str, email: str, kind: str, fake_token: str | None = None
    ) -> MethodDetails:
        customer_id = self._ensure_customer(billing_account_id, email)
        payment_method_types = ["card"] if kind == "card" else ["us_bank_account"]
        intent = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=payment_method_types,
            usage="off_session",
        )
        # Real brand/last4/expiry are not known until the resident completes
        # the Payment Element client side and setup_intent.succeeded arrives;
        # resolve_setup_intent fills them in from that webhook
        return MethodDetails(
            provider_customer_id=customer_id,
            provider_method_id=intent.id,
            kind=kind,
            brand=None,
            last4="0000",
            exp_month=None,
            exp_year=None,
            pending=True,
            client_secret=intent.client_secret,
        )

    def resolve_setup_intent(self, setup_intent_id: str) -> MethodDetails:
        """Called from the setup_intent.succeeded webhook to fill in real card details."""
        intent = stripe.SetupIntent.retrieve(setup_intent_id)
        payment_method = stripe.PaymentMethod.retrieve(intent.payment_method)
        if payment_method.type == "card":
            kind = "card"
            brand = payment_method.card.brand
            last4 = payment_method.card.last4
            exp_month = payment_method.card.exp_month
            exp_year = payment_method.card.exp_year
        else:
            kind = "bank"
            brand = None
            last4 = payment_method.us_bank_account.last4
            exp_month = None
            exp_year = None
        return MethodDetails(
            provider_customer_id=intent.customer,
            provider_method_id=payment_method.id,
            kind=kind,
            brand=brand,
            last4=last4,
            exp_month=exp_month,
            exp_year=exp_year,
            pending=False,
        )

    def charge(
        self, method: MethodDetails, amount_cents: int, idempotency_key: str
    ) -> ChargeResult:
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                customer=method.provider_customer_id,
                payment_method=method.provider_method_id,
                off_session=True,
                confirm=True,
                idempotency_key=idempotency_key,
            )
        except stripe.error.CardError as exc:
            return ChargeResult(
                status="failed",
                provider_payment_id=None,
                failure_reason=str(exc.user_message or exc),
            )
        except stripe.error.StripeError as exc:
            return ChargeResult(status="failed", provider_payment_id=None, failure_reason=str(exc))

        if intent.status == "succeeded":
            return ChargeResult(status="succeeded", provider_payment_id=intent.id)
        if intent.status == "requires_action":
            return ChargeResult(status="requires_action", provider_payment_id=intent.id)
        return ChargeResult(status="processing", provider_payment_id=intent.id)

    def refund(self, provider_payment_id: str, amount_cents: int) -> RefundResult:
        try:
            refund = stripe.Refund.create(payment_intent=provider_payment_id, amount=amount_cents)
        except stripe.error.StripeError as exc:
            return RefundResult(status="failed", provider_refund_id=None, failure_reason=str(exc))
        return RefundResult(status="succeeded", provider_refund_id=refund.id)

    def verify_webhook(self, payload: bytes, signature_header: str) -> dict:
        try:
            event = stripe.Webhook.construct_event(payload, signature_header, self.webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            raise SignatureVerificationError(str(exc)) from exc
        return dict(event)
