from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
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

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
