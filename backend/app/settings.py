from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRETS = {
    "changeme",
    "change-me",
    "secret",
    "password",
    "insecure",
    "replace-me",
    "test",
    "example",
    "dev",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    secret_key: str | None = None
    database_url: str = "sqlite:///./valet.db"
    cors_origins: str = "http://localhost:5173"
    min_lead_minutes: int = 10
    # departure_aware is the measured winner in reports/policies_summary.md;
    # set to nearest_free to fall back to the simpler baseline
    spot_assignment_policy: str = "departure_aware"
    max_request_body_bytes: int = 65_536
    # Twilio's auth token signs inbound webhook requests; a dev default lets
    # the signature-verification code path run in tests and demos without a
    # real Twilio account. Never use the default in production.
    twilio_auth_token: str = "dev-only-twilio-auth-token"
    public_base_url: str = "http://localhost:8000"
    # fake (default, offline and deterministic) or stripe (test mode)
    payments_provider: str = "fake"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    fake_webhook_secret: str = "whsec_fake_dev_secret"
    refund_approval_threshold_cents: int = 20_000
    idempotency_record_hours: int = 24

    def validate_for_runtime(self) -> None:
        # Refusing to boot in production without a real, operator-supplied secret
        if self.app_env != "production":
            return
        if not self.secret_key:
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
        if self.secret_key.strip().lower() in PLACEHOLDER_SECRETS or len(self.secret_key) < 16:
            raise RuntimeError(
                "SECRET_KEY looks like a placeholder or is too short for APP_ENV=production"
            )


settings = Settings()
settings.validate_for_runtime()
