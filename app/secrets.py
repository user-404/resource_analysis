import re
from urllib.parse import urlparse

from app.config import get_settings


class SecretProvider:
    def resolve(self, reference: str) -> str:
        settings = get_settings()
        if settings.environment == "production":
            raise ValueError("The environment secret provider is disabled in production")
        parsed = urlparse(reference)
        if parsed.scheme != "env" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("Only env://NAME secret references are supported by the local provider")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parsed.netloc):
            raise ValueError("Invalid environment secret reference")
        import os

        value = os.environ.get(f"{settings.secret_env_prefix}{parsed.netloc}")
        if not value:
            raise ValueError(f"Secret reference {reference!r} is not configured")
        return value


secret_provider = SecretProvider()
