from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://resource_analysis:change-me@127.0.0.1:3307/resource_analysis"
    environment: str = "development"
    auth_mode: str = "development"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    secret_env_prefix: str = "APP_SECRET_"
    prometheus_cpu_query_template: str = (
        'sum by (pod) (rate(container_cpu_usage_seconds_total'
        '{{namespace="{namespace}",container!="",container!="POD"}}[5m]))'
    )
    prometheus_memory_query_template: str = (
        'sum by (pod) (container_memory_working_set_bytes'
        '{{namespace="{namespace}",container!="",container!="POD"}})'
    )
    worker_poll_seconds: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def validate_auth(self):
        if self.auth_mode not in {"development", "oidc"}:
            raise ValueError("AUTH_MODE must be 'development' or 'oidc'")
        if self.environment == "production" and self.auth_mode != "oidc":
            raise ValueError("OIDC authentication is required in production")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_audience):
            raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required in OIDC mode")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
