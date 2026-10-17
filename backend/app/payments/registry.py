from app.payments.base import PaymentProvider
from app.payments.fake_provider import FakeProvider
from app.settings import settings

_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    global _provider
    if _provider is not None:
        return _provider
    if settings.payments_provider == "stripe":
        from app.payments.stripe_provider import StripeProvider

        _provider = StripeProvider(
            settings.stripe_secret_key or "", settings.stripe_webhook_secret or ""
        )
    else:
        _provider = FakeProvider(settings.fake_webhook_secret)
    return _provider


def set_payment_provider(provider: PaymentProvider) -> None:
    global _provider
    _provider = provider


def reset_payment_provider() -> None:
    global _provider
    _provider = None
