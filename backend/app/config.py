from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    postgres_password: str = ""
    redis_password: str = ""
    database_url: str = "postgresql+asyncpg://hvac:hvac123@db:5432/hvacdb"
    redis_url: str = "redis://redis:6379/0"
    brise_base_url: str = "https://brisev2.agst.com.br:8090/api/v2"
    brise_authkey_url: str = "https://brisev2.agst.com.br:8090/api/v2/request-authkey"
    brise_token_url: str = "https://brisev2.agst.com.br:8090/api/v2/exchange-code"
    brise_client_id: str = "ClienteAGST"
    brise_client_secret: str = ""
    brise_username: str = ""
    brise_password: str = ""
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    brise_verify_tls: bool = True
    allowed_sensor_cidrs: str = "172.20.0.0/16"
    auth_cookie_name: str = "hvac_session"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    microsoft_auth_enabled: bool = False
    microsoft_tenant_id: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_redirect_uri: str = ""
    microsoft_allowed_domains: str = ""
    microsoft_auto_create_users: bool = True
    microsoft_default_role: str = "VIEWER"
    post_login_redirect_url: str = "/dashboard"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    poll_variables_interval: int = 300
    poll_parameters_interval: int = 1800
    poll_configs_interval: int = 21600
    max_concurrent_polls: int = 20
    no_reading_threshold_minutes: int = 15
    offline_threshold_minutes: int = 30
    alert_cooldown_hours: int = 4
    energy_price_per_kwh: float = 0.93
    energy_consumption_scale: float = 0.0195
    email_consolidated_interval_minutes: int = 30

    # ── IA / Ollama ────────────────────────────────────────────────────────────
    ai_analysis_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    # Modelo rápido para análise de monitoramento em tempo real
    ollama_model: str = "llama3.2:3b"
    # Modelo pesado para relatórios aprofundados (uso sob demanda)
    ollama_model_deep: str = "mirage335/NVIDIA-Nemotron-Nano-9B-v2-virtuoso:latest"

    # ── Email (SMTP) ───────────────────────────────────────────────────────────
    email_enabled: bool = False
    email_host: str = ""
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = "refrigeracao@bemol.com.br"
    email_alert_recipients: str = ""   # ex: "fulano@bemol.com.br,ciclano@bemol.com.br"
    email_use_tls: bool = True
    email_use_ssl: bool = False
    allowed_email_domain: str = ""     # se definido, filtra destinatários pelo domínio

    app_timezone: str = "America/Manaus"

    # ── Sensores externos HTTP ─────────────────────────────────────────────────
    # JSON: [{"source_url": "http://...", "name": "...", "is_critical": false, "setpoint_cool": 24}]
    external_sensors_seed: str = "[]"

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if value in {"", "change-me-in-production", "your-super-secret-key-change-in-production"}:
            raise ValueError("SECRET_KEY deve ser definido com um valor forte no .env")
        if len(value) < 32:
            raise ValueError("SECRET_KEY deve ter pelo menos 32 caracteres")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def microsoft_domains(self) -> set[str]:
        return {domain.strip().lower() for domain in self.microsoft_allowed_domains.split(",") if domain.strip()}

    class Config:
        env_file = ".env"
        extra = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
