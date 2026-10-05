from fastapi import HTTPException
from jwt import PyJWKClient, PyJWTError, decode

from app.config import get_settings


def authorize(authorization: str | None) -> None:
    settings = get_settings()
    if settings.auth_mode == "development":
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    try:
        jwks_client = PyJWKClient(f"{settings.oidc_issuer.rstrip('/')}/.well-known/jwks.json")
        signing_key = jwks_client.get_signing_key_from_jwt(authorization[7:])
        claims = decode(
            authorization[7:],
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
        )
    except (PyJWTError, OSError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc

    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Access token has no subject")
